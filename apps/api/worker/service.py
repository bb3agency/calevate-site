"""What the voice worker's three routes actually do (D-621).

**EVERY STATEMENT HERE IS THE ONE `voice_worker/sink.py` AND `voice_worker/config.py`
ISSUED YESTERDAY, MOVED TO THE SIDE THAT OWNS THE DATABASE.** Same columns, same
idempotency keys, same forward-only status clause, same all-or-nothing settlement. What
changed is WHERE it runs, and with it three things that could not be true in a container on
somebody else's infrastructure: the tenant is resolved here, the redactor runs here, and
the rate card is here.

**HARD RULE 1.** Every read and write runs inside `tenant_session`, whose transaction sets
`app.tenant_id`. The tenant is never taken from the request body — it is PARSED out of the
engine-space ref the worker presents (`tenant_of_pipecat_ref` /
`parse_owned_runtime_agent_ref`) and then everything else happens under that tenant's RLS.
A body that names a different tenant or agent than the ref is refused rather than
reconciled: `_refuse_identity` is `sink.SinkIdentityError` moved across the wire, and it
matters more here than it did there, because there the producer was in the same process.

**HARD RULE 4 AND 7, WHICH ARE ONE DECISION SEEN TWICE.** `usage_events` is INSERT-only, so
a leg written wrong can only be corrected by a compensating row. That is why `settle` writes
all legs or none, why a leg nobody can price produces a `call_metering_refusals` row instead
of a zero, and why a re-delivered settlement is ANSWERED (`already_settled`) rather than
re-applied. The rate card is `apps/api/billing/rates.py` — the one door a rupee comes
through — and it RAISES on an unattested model rather than returning a number.

**HARD RULE 6.** Transcript text reaches exactly two places: the `text` column and
`redact()`. It is never logged, never rendered into an exception, and never counted in a log
line beyond its index. No phone number exists on this path at all — the worker is handed
none, and `calls.from_e164`/`to_e164` stay NULL for the reconciliation that owns them
(§1.2: the carrier is the authority for who rang whom).

**WHY THE REDACTOR MOVED WITH THE WRITE, WHICH IS THE ONE BEHAVIOUR CHANGE IN THIS FILE.**
`text_redacted` is the column hard rule 5 promises every API response serves from, and until
now the value in it was computed by a process running on a vendor's infrastructure. A server
that stored a client-supplied redaction would be trusting the least trusted party in the
system with the one column that decides what a dashboard may show. `apps/workers/redaction.
redact` is the repository's single redaction primitive and it now runs on our side of the
wall; a `text_redacted` arriving in the body is IGNORED rather than refused, because the
worker has no way to know what our redactor would have said and a 422 would turn a
harmless field into a lost transcript.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from calevate_shared.engine import (
    AgentConfig,
    ModelConfig,
    parse_owned_runtime_agent_ref,
    tenant_of_pipecat_ref,
)
from calevate_shared.events import TERMINAL_STATUSES
from calevate_shared.worker_api import (
    AttestationIn,
    AttestationOut,
    MeteredQuantity,
    ObservationBatch,
    ObservationsOut,
    SettlementOut,
    SettlementRefusal,
    SettlementRequest,
    WorkerSessionOut,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.config_versions import record_attestation
from apps.api.billing.rates import (
    llm_inr_per_ktok,
    stt_rate_inr_per_second,
    tts_rate_inr_per_char,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability.service import enqueue_outbox_once
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The engine every row this module writes belongs to. `apps/api/engine/pipecat.py`'s own
#: name for itself, restated as a literal for `sink.POSTCALL_JOB`'s reason: importing the
#: adapter from here would be an `apps.api.worker` -> `apps.api.engine.pipecat` edge that
#: `pyproject.toml`'s import-linter contract forbids by name.
ENGINE_NAME: Final = "pipecat"

#: The ARQ job the post-call pipeline runs under — extraction, the CRM columns, the lead,
#: the hot-lead alert. `apps/workers/pipeline.POSTCALL_JOB`, restated rather than imported
#: so `scripts/check_job_wiring.py` can resolve it as a module-level constant in the file
#: that enqueues it (that scan resolves a job name only where it reaches the queue).
POSTCALL_JOB: Final = "run_post_call_pipeline"

#: What makes the post-call promise idempotent, and — see `settle_call` — what tells a
#: re-delivered settlement that it is one. The key names the SIDE EFFECT and not the row.
POSTCALL_DEDUPE_PREFIX: Final = "post-call:"

# --- the statements. Each is `voice_worker/sink.py`'s, unchanged. ----------------------

#: One read, three tables. `voice_worker/config._SESSION_CONFIG_SQL` verbatim: three round
#: trips would let a publish land between them and produce a session whose prompt came from
#: one version and whose knowledge pack came from the next.
_SESSION_SQL: Final = """
SELECT p.agent_config_version_id,
       p.resolved_config,
       v.composed_prompt,
       v.prompt_sha256,
       v.model_config,
       a.knowledge_pack_sha256,
       a.engine_agent_ref,
       a.ai_disclosure_line
FROM pipecat_agents AS p
JOIN agent_config_versions AS v ON v.id = p.agent_config_version_id
JOIN agents AS a ON a.id = p.agent_id
WHERE p.agent_id = :aid AND p.tenant_id = :tid AND a.status = 'live'
"""

#: ⚠ **`a.status = 'live'` IS A COMPLIANCE PREDICATE, NOT A TIDINESS ONE (18 Sep 2026).**
#: Pausing or archiving an agent is supposed to stop it answering, and on the rented engine
#: it does — `_release_inbound_numbers` unbinds the number. This engine declares
#: `inbound_binding=False`, so that release takes the capability arm, logs `unsupported`,
#: reports `numbers_released=0` and the console shows the pause as done. Nothing else stood
#: in the way: the carrier answer route reads no row, and this query used to serve any agent
#: that had a `pipecat_agents` row — which `archive_agent` deliberately leaves in place. So a
#: paused agent went on answering its number, greeting callers and collecting their details,
#: with an owner who had been told it stopped. This is the one door every owned-runtime call
#: comes through, which is exactly where `voice_worker/config.refuse_unless_disclosed` argues
#: such a check belongs.

#: Does this agent belong to the tenant the call ref names, and is it real?
#:
#: RLS CANNOT ANSWER THIS AND THAT IS THE WHOLE REASON THE STATEMENT EXISTS. PostgreSQL runs
#: foreign-key checks as system-imposed triggers that BYPASS row security, and
#: `calls.agent_id -> agents.id` is a plain single-column FK with no `(tenant_id, agent_id)`
#: composite — so an INSERT naming another tenant's agent succeeds under this tenant's
#: policy. The read path already binds the pair (`_SESSION_SQL`); the write path did not, so
#: one token could file tenant B's agent onto tenant A's call and drive A's post-call
#: pipeline — extraction schema, CRM columns, lead, hot-lead alert — off B's agent, while
#: writing an APPEND-ONLY `usage_events` row that can only ever be compensated.
_AGENT_VISIBLE_SQL: Final = "SELECT 1 FROM agents WHERE id = :aid"

#: The call row, minted or converged on. `from_e164`/`to_e164` are ABSENT rather than
#: NULL-ed, which is the difference between "we do not know" and "there is nobody" — the
#: reconciliation that reads the carrier's CDR owns those two columns (§1.2).
#:
#: THE STATUS CLAUSE IS THE CONSTANT, NOT A COPY OF ITS MEMBERS: a sixth terminal status
#: added to `calevate_shared.events` must be terminal to every statement that asks.
_UPSERT_CALL_SQL: Final = """
INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status,
                   started_at, ended_at, duration_s, from_e164, to_e164, created_at, updated_at)
VALUES (:id, :tid, :aid, :ecid, :dir, :status, :started, :ended, :dur, :from_e, :to_e,
        now(), now())
ON CONFLICT (engine_call_id) DO UPDATE SET
  status = EXCLUDED.status,
  started_at = COALESCE(calls.started_at, EXCLUDED.started_at),
  ended_at = COALESCE(EXCLUDED.ended_at, calls.ended_at),
  duration_s = COALESCE(EXCLUDED.duration_s, calls.duration_s),
  -- ⚠ THE STORED VALUE WINS ON A DISAGREEMENT, WHICH IS THE OPPOSITE OF `ended_at` ABOVE.
  -- Argument order is the whole of the decision and it is easy to get backwards, so state
  -- it exactly: BOTH orderings preserve a stored number when the incoming one is NULL
  -- (`COALESCE` returns the first non-null either way), and most batches of a call do
  -- carry NULL because nothing can supply a party on Plivo. What the order decides is the
  -- case where BOTH are present and DIFFER — and there the first value learned wins.
  --
  -- A party is a fact about who was on the call, not a running total: a second value is a
  -- disagreement, not an update, and silently adopting the newer one would let a late or
  -- replayed batch rewrite whose call it was — under which a lead, a caller memory and a
  -- DPDP erasure subject all move to a different person with nothing logged. Keeping the
  -- first makes that impossible; a genuine correction is a deliberate write elsewhere.
  -- (What WOULD blank a known party is a bare `= EXCLUDED.from_e164`, which is why this
  -- line is a COALESCE at all.)
  from_e164 = COALESCE(calls.from_e164, EXCLUDED.from_e164),
  to_e164 = COALESCE(calls.to_e164, EXCLUDED.to_e164),
  updated_at = now()
WHERE calls.status <> ALL(:terminal) OR EXCLUDED.status = 'completed'
RETURNING id, from_e164, to_e164
"""

#: One turn. `ON CONFLICT (call_id, idx) DO NOTHING` — the contract's own choice for the
#: batch that may be re-delivered (`worker-http-contract.md`: "A retried batch inserts
#: nothing twice"), and the one that lets the route answer how many were ALREADY THERE.
#:
#: ⚠ **`DO NOTHING` AND NOT THE `DO UPDATE` THE IN-PROCESS SINK USED.** That sink was the
#: only writer of a turn while a call was running and could treat a repeat as a correction;
#: over a wire a repeat is a RETRY, and there is nothing in a retried batch that could be
#: more correct than what is already stored. `apps/workers/pipeline._persist_transcript` is
#: still the writer that REPLACES a turn on a re-read (D-187), and it runs after the call —
#: so the table still has exactly one corrector, and it is not this one.
_INSERT_TURN_SQL: Final = """
INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, text_redacted,
                              lang, start_ms, end_ms, created_at, updated_at)
VALUES (:id, :tid, :cid, :idx, :speaker, :text, :redacted, :lang, :start, :end, now(), now())
ON CONFLICT (call_id, idx) DO NOTHING
RETURNING id
"""

#: One metered leg. **`DO NOTHING`, NEVER `DO UPDATE`** — this table is append-only under
#: hard rule 4 and carries a `calevate_forbid_mutation` trigger, so `DO UPDATE` would be a
#: runtime error and not a design choice. The money is handed over UNQUANTIZED and the
#: NUMERIC(12,4) column rounds it half-away-from-zero, which is `MONEY_Q`'s ROUND_HALF_UP on
#: the non-negative values this ledger holds.
_INSERT_USAGE_SQL: Final = """
INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid,
                          occurred_at, meta, created_at)
VALUES (:id, :tid, :cid, :unit, :qty, :cost, :at, CAST(:meta AS jsonb), now())
ON CONFLICT DO NOTHING
"""

#: A leg we could not honestly price, recorded so that "why did this call meter nothing"
#: has an answer that is not a shrug. Append-only: a refusal is evidence about one
#: settlement attempt.
_INSERT_REFUSAL_SQL: Final = """
INSERT INTO call_metering_refusals (id, tenant_id, call_id, leg, code, detail, remediation,
                                    occurred_at, created_at)
VALUES (:id, :tid, :cid, :leg, :code, :detail, :remediation, :at, now())
"""


# --- authentication -------------------------------------------------------------------


def authorized(header: str | None) -> bool:
    """Does this request carry the token this deployment issued to its voice worker?

    `hmac.compare_digest`, not `==`: this is a secret comparison on an endpoint anybody can
    reach, and Python's string equality returns as soon as two bytes differ. The scheme
    check is a plain comparison because the word "Bearer" is not a secret.

    **AN UNCONFIGURED DEPLOYMENT AUTHENTICATES NOBODY.** A missing token is not "no
    authentication required" — it is a deployment that has not been wired to its worker yet,
    and the safe reading of an absent credential is that nothing may pass.
    `compliance/caller_data_routes._authorized`'s posture, and it matters more here: that
    endpoint READS a nicety, this one WRITES the ledger.
    """
    expected = get_settings().pipecat_worker_api_token
    if not expected or not header:
        return False
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    return hmac.compare_digest(presented.strip(), expected)


def engine_enabled() -> bool:
    """Is THIS deployment running the engine these routes write for?

    ⚠ **THE ROUTES USED TO WRITE WHATEVER ENGINE THE PROCESS WAS CONFIGURED FOR, AND THE
    CONSUMER OF WHAT THEY WRITE DOES NOT ASK (D-627).** `settle_call` enqueues a post-call
    job whose payload names `"engine": "pipecat"`, and `workers/pipeline._post_call_target`
    never reads that key — it resolves the adapter from the process-wide `ENGINE` through
    `get_engine()`. So on a deployment running `ENGINE=bolna`, a settlement accepted here
    minted `calls` rows, `usage_events` rows and an outbox promise whose pipeline then asked
    BOLNA for a `pipecat:` execution id, and the call's extraction, CRM columns and lead were
    lost to a vendor lookup that could never resolve.

    Two fixes were available and the SMALLER one is this: refuse the write. Teaching the
    consumer to switch adapters per payload would put a second engine-resolution path beside
    `get_engine()` — two ways of doing one thing, on the path that decides which vendor a
    client's call is reconciled against — for a configuration that is a deploy fault either
    way. A deployment not running this engine has no voice worker to serve.

    **`apps/voice-runtime/engine_intake.py:235` IS THE PRECEDENT AND IT WAS READ BEFORE IT
    WAS COPIED.** It compares `settings.engine != engine` and refuses. What it returns is an
    `IntakeVerdict(ok=False, …)` that its callers turn into a 401, not a 409 — so the SHAPE
    is borrowed and the status is chosen here on its own merits: nothing is wrong with the
    caller's credential, and the request would be valid against the same platform configured
    differently, which is what `conflict` means in this repo's error ladder.
    """
    return get_settings().engine == ENGINE_NAME


def refuse_wrong_engine() -> ProblemError:
    """409 for a worker talking to a deployment that is not running its engine."""
    return ProblemError.conflict(
        "worker_engine_not_enabled",
        (
            "This deployment is not running the voice worker's engine, so it cannot accept "
            "calls, observations or settlements from one."
        ),
        remediation=(
            "A worker reaching an API configured for another engine is a deploy fault: the "
            "rows it would write are reconciled by the process-wide ENGINE and would be "
            "unreadable. Point the worker at the deployment whose ENGINE is this one."
        ),
    )


# --- resolution: a ref the worker holds becomes a tenant we can act as -----------------


def _refuse_unknown_call() -> ProblemError:
    """The one refusal for every way an `engine_call_id` fails to name a call of ours.

    ONE MESSAGE FOR "not our ref", "not a call we minted" and "no such call", deliberately:
    a client that can tell the three apart can enumerate which call ids exist, and the
    worker has no use for the distinction — it holds exactly one call ref and either it
    works or the deploy is wrong. `carrier_routes.plivo_answer` refuses the same way for the
    same reason.
    """
    return ProblemError(
        kind="not_found",
        code="worker_call_unknown",
        title="That is not a call of this platform",
        detail="The call reference does not name a call this deployment is running.",
        remediation=(
            "The worker mints this reference itself (`pipecat_call_ref`); a call "
            "carrying another engine's id is a wiring fault, not a missing row."
        ),
    )


def _tenant_of_call(engine_call_id: str) -> UUID:
    """The tenant a `pipecat:<tenant>:<call>` ref names, or a refusal.

    **A PARSE AND NOT A QUERY, WHICH IS WHY THE WORKER NEVER SENDS A `calls.id`.**
    `pipecat_call_ref` mints the tenant INTO the handle precisely so an `owned_runtime` call
    can be found under RLS without a global routing table (`calevate_shared.engine`, which
    is also the only legal reader of that format). A worker that could name a row id could
    name somebody else's; a worker that names its own ref can only ever reach its own
    tenant, because the tenant is what the ref says.
    """
    tenant_id = tenant_of_pipecat_ref(engine_call_id)
    if tenant_id is None:
        raise _refuse_unknown_call()
    return tenant_id


def _refuse_identity(what: str) -> ProblemError:
    """A body that names a different tenant, agent or call than the ref it was posted to.

    `sink.SinkIdentityError` across the wire, and REFUSED rather than reconciled for its
    reason: picking one of the two claims is being right half the time on a hard rule 1
    question. Ids only (hard rule 6) — and not even those: the message names the FIELD that
    disagreed, because echoing an id a stranger supplied puts their string in our log.
    """
    return ProblemError(
        kind="validation",
        code="worker_identity_mismatch",
        title="This body is not about the call it was sent to",
        detail=f"This names a different {what} than the call reference it was sent to.",
        remediation="One sink, one call: build it from the session's own ids.",
    )


# --- GET /v1/worker/session/{engine_agent_ref} -----------------------------------------


async def load_session(engine_agent_ref: str) -> WorkerSessionOut:
    """One published agent, answered for a worker about to take its call.

    `voice_worker/config.load_session_config`'s SELECT, moved. The agent ref is PARSED for
    its tenant and agent (`parse_owned_runtime_agent_ref`) rather than looked up in
    `engine_agent_routes`: this engine mints the ref itself, so the resolution is a parse
    and the routing table it would otherwise need is the one `engine/pipecat.py` records as
    redundant under `owned_runtime`.

    **HARD RULE 5 IS ENFORCED ON BOTH SIDES OF THIS WIRE AND NEITHER IS REDUNDANT.** Here,
    because this is where the row is and a worker cannot be trusted to check what it was
    never sent; and in `voice_worker/config.refuse_unless_disclosed`, because that process
    is the last reader before a model speaks. `ai_disclosure_line` travels for exactly that
    second check.
    """
    parsed = parse_owned_runtime_agent_ref(engine_agent_ref)
    if parsed is None:
        raise _refuse_unknown_agent()
    tenant_id, agent_id = parsed
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text(_SESSION_SQL), {"aid": agent_id, "tid": tenant_id})
        ).first()
    if row is None:
        raise _refuse_unknown_agent()
    (
        version_id,
        resolved_config,
        composed_prompt,
        prompt_sha256,
        model_config,
        pack_sha,
        stored_ref,
        ai_disclosure_line,
    ) = row
    published = AgentConfig.model_validate(resolved_config)
    models = ModelConfig.model_validate(model_config)
    log.info(
        "worker_session_served",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "agent_config_version_id": str(version_id),
            # A digest is an id and is loggable; the prompt it was taken over is not.
            "prompt_sha256": prompt_sha256,
            "knowledge_pack": pack_sha is not None,
        },
    )
    return WorkerSessionOut(
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_config_version_id=version_id,
        system_prompt=composed_prompt,
        prompt_sha256=prompt_sha256,
        models=models,
        engine_agent_ref=None if stored_ref is None else str(stored_ref),
        language=_session_language(published, models),
        # EVERY AGENT SPEAKS FIRST, ON BOTH LEGS, AND NO COLUMN DECIDES IT TODAY (D-163).
        # `voice_worker/config.py` argued this when it held the read; the value moved with
        # the read rather than the argument being restated in two places.
        greet_first=True,
        knowledge_pack_sha256=pack_sha,
        ai_disclosure_line=ai_disclosure_line,
    )


def _refuse_unknown_agent() -> ProblemError:
    """404 for a ref that names no published agent — `carrier_routes.plivo_answer`'s answer
    to an unknown ref, for its reason: a stranger who guesses learns nothing."""
    return ProblemError(
        kind="not_found",
        code="worker_agent_unknown",
        title="That is not a published agent of this platform",
        detail="The agent reference names no agent with a published runtime row.",
        remediation="Publish the agent, then redeploy nothing — the worker reads this per call.",
    )


def _session_language(published: AgentConfig, models: ModelConfig) -> str | None:
    """The BCP-47 code to pin the transcriber to, or `None` to let it detect.

    `stt_autodetect` WINS, and that is not a preference: D-584 records that no Sarvam model
    on our declared leg accepts `te-IN` at all, so an operator who turned detection on did
    it because pinning was refused on the wire.
    """
    if models.stt_autodetect:
        return None
    return published.language_primary


# --- POST /v1/worker/agents/{engine_agent_ref}/attestation -----------------------------


async def record_prompt_attestation(
    engine_agent_ref: str, request: AttestationIn
) -> AttestationOut:
    """What a worker says it loaded, written as the witness `get_agent` answers from.

    **WITHOUT THIS THE TABLE HAD NO PRODUCTION WRITER (D-626).** `agents/config_versions.
    record_attestation` was reachable only from tests, so `agent_config_attestations` was
    empty on every deployment, `PipecatEngine.get_agent` answered
    `system_prompt_readable=False` for every agent for ever, and hard rule 5's engine-side
    verification — the thing OPERATIONS §2 gate 2 turns on — never ran once on this leg. The
    worker computed `observed_prompt_sha256` and it reached nothing.

    **THE WORKER SENDS WHAT IT OBSERVED; THE SERVER DECIDES WHAT THAT MEANS.** The body
    carries the digest and not the verdict. `voice_worker/pipeline.AssembledCall` also
    computes `prompt_matches_config_version`, and it is deliberately NOT what is stored: an
    attestation whose verdict came from the attesting process would agree with itself by
    construction, which is the `control_plane` defect `config_versions.py` exists to close.
    We re-read `agent_config_versions.prompt_sha256` under this tenant's RLS and compare.

    **A MISMATCH IS A 200 WITH `matches=False`.** It is the finding this whole arrangement
    exists to be able to make, and refusing the write would delete the evidence of exactly
    the condition the table was built to catch.
    """
    parsed = parse_owned_runtime_agent_ref(engine_agent_ref)
    if parsed is None:
        raise _refuse_unknown_agent()
    tenant_id, agent_id = parsed
    if request.agent_id != agent_id:
        raise _refuse_identity("agent")
    async with tenant_session(tenant_id) as session:
        attestation = await record_attestation(
            session,
            tenant_id,
            agent_id=agent_id,
            agent_config_version_id=request.agent_config_version_id,
            prompt_sha256=request.observed_prompt_sha256,
        )
    log.info(
        "worker_attestation_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "agent_config_version_id": str(request.agent_config_version_id),
            "attestation_id": str(attestation.id),
            "matches": attestation.matches,
        },
    )
    return AttestationOut(attestation_id=attestation.id, matches=attestation.matches)


# --- POST /v1/worker/calls/{engine_call_id}/observations -------------------------------


async def record_observations(engine_call_id: str, batch: ObservationBatch) -> ObservationsOut:
    """Statuses and spoken turns, in one transaction, idempotent on `(call_id, idx)`.

    **ONE BODY FOR BOTH BECAUSE THEY ARE ONE FACT** — what happened on this call — and
    because the server has to order them anyway: Pipecat dispatches every handler as its own
    task, so a turn can arrive before the status that opened the call. Both converge on one
    call-row upsert, which is also what keeps the `transcript_turns` foreign key satisfiable
    (`ON DELETE RESTRICT`: a turn before its call is an IntegrityError mid-call).

    An empty batch is a legal no-op the client may send rather than a condition it must
    check for.
    """
    tenant_id = _tenant_of_call(engine_call_id)
    _check_batch_identity(tenant_id, batch)
    status = _forward_status(batch)
    written = already = 0
    async with tenant_session(tenant_id) as session:
        call_row_id = (
            await _upsert_call(
                session,
                engine_call_id=engine_call_id,
                tenant_id=tenant_id,
                agent_id=batch.agent_id,
                direction=batch.direction,
                status=status,
                started_at=_first(batch, "started_at"),
                ended_at=_first(batch, "ended_at"),
                from_e164=batch.from_e164,
                to_e164=batch.to_e164,
            )
        ).id
        for turn in batch.turns:
            # THE ONE REDACTION CALL, ON OUR SIDE OF THE WALL. `RedactionResult.kinds` says
            # WHAT was found and is loggable; the text either side of it is not.
            redacted = redact(turn.text)
            inserted = (
                await session.execute(
                    text(_INSERT_TURN_SQL),
                    {
                        "id": uuid7(),
                        "tid": tenant_id,
                        "cid": call_row_id,
                        "idx": turn.idx,
                        "speaker": turn.speaker,
                        "text": turn.text,
                        "redacted": redacted.text,
                        "lang": turn.lang,
                        "start": turn.start_ms,
                        "end": turn.end_ms,
                    },
                )
            ).first()
            if inserted is None:
                already += 1
            else:
                written += 1
    log.info(
        "worker_observations_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_row_id),
            "events": len(batch.events),
            "turns_written": written,
            "turns_already_present": already,
            "status": status,
        },
    )
    return ObservationsOut(turns_written=written, turns_already_present=already, status=status)


def _check_batch_identity(tenant_id: UUID, batch: ObservationBatch) -> None:
    """Refuse a batch whose contents claim a different call, tenant or agent than the ref.

    What is checked is DISAGREEMENT, not presence: `TranscriptTurn` carries no tenant and
    `CallEvent` declares both `| None`, so a `None` is an event that never claimed and a
    claim that differs is the fault.
    """
    for event in batch.events:
        if event.tenant_id is not None and event.tenant_id != tenant_id:
            raise _refuse_identity("tenant")
        if event.agent_id is not None and event.agent_id != batch.agent_id:
            raise _refuse_identity("agent")
    # ONE BATCH IS ABOUT ONE CALL. The worker's own `call_id` is OURS and is not the engine
    # ref, so it cannot be compared to the path segment — but a batch holding two call ids
    # is a crossed wire between two concurrent sessions in one container, which is the hard
    # rule 1 fault `sink.SinkIdentityError` existed to stop before the write.
    call_ids = {event.call_id for event in batch.events} | {t.call_id for t in batch.turns}
    if len(call_ids) > 1:
        raise _refuse_identity("call")


def _first(batch: ObservationBatch, field: str) -> datetime | None:
    for event in batch.events:
        value = getattr(event, field)
        if value is not None:
            return value  # type: ignore[no-any-return]
    return None


def _forward_status(batch: ObservationBatch) -> str:
    """The furthest-forward status this batch reports, or `in_progress`.

    A batch with no events is a flush of turns, and a flush of turns OPENS the call if it is
    the first thing to arrive — `sink._ensure_call_row`'s rule, which exists because the
    order of Pipecat's handlers is not ours to choose.
    """
    for event in batch.events:
        if event.status in TERMINAL_STATUSES:
            return event.status
    for event in batch.events:
        return event.status
    return "in_progress"


# --- POST /v1/worker/calls/{engine_call_id}/settlement ---------------------------------


@dataclass(frozen=True, slots=True)
class _Priced:
    """One `usage_events` row, assembled from a quantity the worker sent and a rate we hold."""

    unit_type: str
    qty: Decimal
    unit_cost_inr: Decimal
    meta: dict[str, str]


class _LegNotPriceableError(Exception):
    """A leg with a quantity and no honest price. Carries the refusal row's four fields."""

    def __init__(self, refusal: SettlementRefusal) -> None:
        super().__init__(refusal.detail)
        self.refusal = refusal


async def settle_call(engine_call_id: str, request: SettlementRequest) -> SettlementOut:
    """The terminal write, and the one that carries D-607.

    **THE CALL ROW, THE LEDGER-OR-REFUSAL AND THE OUTBOX ROW COMMIT TOGETHER OR NOT AT
    ALL.** Before D-607 there were three transactions and one branch opened none, so a crash
    between them could leave a settled call with no trigger — which on this engine means no
    extraction, no CRM columns and no lead, silently and for ever (there is no poller behind
    it: `PipecatEngine.list_executions` reports nothing by design). The guarantee is
    RELOCATED to the side that owns the database, which is where a transaction belongs.

    **A RE-DELIVERY IS ANSWERED, NEVER RE-APPLIED.** `usage_events` is append-only: there is
    no UPDATE with which to correct a double write, and `call_metering_refusals` carries no
    unique index at all, so a second settlement would simply write a second refusal. The
    marker this reads is the one the settlement already writes — the outbox row keyed
    `post-call:{calls.id}`, which `enqueue_outbox_once` puts on the books exactly once ever.
    Claiming it FIRST turns "have we settled this call?" into the same atomic question as
    "have we promised its pipeline?", with no new column, no new table and no read-then-
    write. A worker whose POST timed out after we committed retries and is told
    `already_settled`.
    """
    tenant_id = _tenant_of_call(engine_call_id)
    _check_settlement(request)
    occurred_at = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        call = await _upsert_call(
            session,
            engine_call_id=engine_call_id,
            tenant_id=tenant_id,
            agent_id=request.agent_id,
            direction=request.direction,
            status=request.final_status,
            started_at=None,
            ended_at=None,
            from_e164=request.from_e164,
            to_e164=request.to_e164,
        )
        call_row_id = call.id
        message_id = await enqueue_outbox_once(
            session,
            job=POSTCALL_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "call_id": str(call_row_id),
                "engine": ENGINE_NAME,
                # The ENGINE-SPACE handle, which is what `get_execution` takes and what the
                # adapter parses this call's tenant back out of. Never the bare uuid.
                "execution_id": engine_call_id,
            },
            dedupe_key=f"{POSTCALL_DEDUPE_PREFIX}{call_row_id}",
        )
        if message_id is None:
            # ALREADY SETTLED. The call row upsert above still ran and is correct — it is
            # forward-only and idempotent, and a retry that carries a terminal status the
            # first attempt did not is the one thing a re-delivery may legitimately move.
            log.info(
                "worker_settlement_replayed",
                extra={"tenant_id": str(tenant_id), "call_id": str(call_row_id)},
            )
            return SettlementOut(
                already_settled=True,
                rows_written=0,
                refusals_recorded=0,
                post_call_enqueued=False,
            )
        # THE WORKER'S REFUSALS AND OURS, IN THAT ORDER. They are different kinds of
        # failure — the worker could not READ a quantity, we could not PRICE one — and both
        # belong on the record against the leg they happened to.
        rows, priced_refusals = _price(request.quantities)
        refusals = (*request.refusals, *priced_refusals)
        await _write_usage(session, tenant_id, call_row_id, rows, at=occurred_at)
        for refusal in refusals:
            await _write_refusal(session, tenant_id, call_row_id, refusal, at=occurred_at)

    if refusals:
        # `error` and not `warning`: an unmetered leg is spend we absorbed and cannot bill,
        # and it is the state `admin/health.calls_unmetered` stops the board for. It is
        # logged even when other legs settled — a call priced on three legs of five is still
        # a call whose cost we do not know.
        log.error(
            "worker_call_not_meterable",
            extra={
                "tenant_id": str(tenant_id),
                "call_id": str(call_row_id),
                "legs": ",".join(refusal.leg for refusal in refusals),
                "codes": ",".join(refusal.code for refusal in refusals),
                "rows": len(rows),
            },
        )
    else:
        log.info(
            "worker_call_settled",
            extra={
                "tenant_id": str(tenant_id),
                "call_id": str(call_row_id),
                "rows": len(rows),
            },
        )
    _alert_if_nobody_was_on_the_call(
        tenant_id=tenant_id, call=call, final_status=request.final_status
    )
    return SettlementOut(
        already_settled=False,
        rows_written=len(rows),
        refusals_recorded=len(refusals),
        post_call_enqueued=True,
    )


def _alert_if_nobody_was_on_the_call(*, tenant_id: UUID, call: _CallRow, final_status: str) -> None:
    """A call that ended with NEITHER party known is an operator event, not a NULL column.

    **WHY THIS IS LOUD AND NOT COSMETIC.** `calls.from_e164`/`to_e164` have no producer on
    this engine at all — verified rather than recalled: nothing under `apps/voice-worker/`
    assigns either field, Pipecat's Plivo handshake parses neither party, and
    `voice_worker/carrier.PlivoHandshake` refuses to model what is always `None` (DEPLOYMENT
    §12.5 gate 9). Three consequences follow for every call that settles this way, and each
    one is somebody's right rather than a missing screen field:

    * **A post-call OPT-OUT cannot be attributed.** `workers/pipeline.py:1600` takes the
      number to suppress from this row (by way of `PipecatEngine.get_execution`, which reads
      the column), so a caller who asked not to be called again gets no DNC row — a TRAI
      matter and not an engineering inconvenience. That path raises its own alarm when it
      happens, which is later and only when a caller actually opted out; this one says the
      capability was already gone before anyone needed it.
    * **No lead is filed.** `leads.phone_e164` is NOT NULL and `pipeline.py:1968` derives it
      from here, so the thing the client is paying for is silently absent.
    * **A DPDP erasure has no subject.** There is nothing to match a request against.

    **IT DOES NOT INVENT A NUMBER AND MUST NOT.** There is no second source to fall back on:
    our own session has no party, and substituting the agent's own line would file a lead
    against ourselves. The honest act is to make the silence audible.

    `attention` rather than `page`: this fires on every call of this engine until gate 9 is
    closed, and a code that pages on every call is the D-591 defect that made an inbox
    unreadable. Its neighbours are already on that rung — `opt_out_unattributable` and the
    `in_call_optout_*` family are all `attention` for the same shape of failure.

    **TERMINAL ONLY.** A call still in progress has not finished learning who is on it; only
    the settlement can say nobody ever did.
    """
    if final_status not in TERMINAL_STATUSES:
        return
    if call.from_e164 is not None or call.to_e164 is not None:
        return
    alert(
        "WORKER_TERMINAL",
        "call_settled_without_parties",
        detail=(
            "This call settled with neither party known, so no opt-out can be attributed to "
            "a number, no lead can be filed, and a DPDP erasure has no subject for it."
        ),
        tenant_id=str(tenant_id),
        call_id=str(call.id),
    )


def _check_settlement(request: SettlementRequest) -> None:
    """A REFUSAL NAMES A LEG; QUANTITIES NAME OTHER LEGS. Validated rather than trusted.

    ⚠ **THIS USED TO BE "A REFUSAL OR QUANTITIES, NEVER BOTH" (D-625).** That exclusivity
    mirrored an all-or-nothing meter, and between them they made this engine settle nothing
    at all: no production call has a carrier CDR (BLOCKER-1), so every call arrived as one
    refusal and the STT seconds, TTS characters and LLM tokens the worker really measured
    were discarded into an append-only ledger that can never take them later. The rejected
    alternative IS the old rule, and it was rejected because "nobody witnessed the connected
    minute" is not a reason to disown the three legs somebody did.

    What the old rule protected survives per leg and is what this function now checks:

    * **No leg is settled twice and no leg is both priced and refused.** That is the shape
      the ledger genuinely cannot hold — one leg of one call with two contradictory records,
      neither correctable, because `usage_events` and `call_metering_refusals` are both
      append-only under hard rule 4.
    * **The carrier's authority is untouched.** Nothing here lets a quantity stand in for a
      connected minute; `_price` refuses the carrier and runtime legs by name.

    ⚠ **BOTH EMPTY IS LEGAL, AND THIS CHECK BRIEFLY REFUSED IT BY MISTAKE.** A settlement
    with no refusals and no quantities is the THIRD state `meter.py` distinguishes on
    purpose: a session that transcribed and synthesised nothing has no leg to price, which is
    not the same thing as a leg nobody can price. Turning it into a 422 would leave such a
    call permanently unsettled and its post-call pipeline never promised — extraction, CRM
    columns and lead, silently absent.
    """
    refused: set[str] = set()
    for refusal in request.refusals:
        if refusal.leg in refused:
            raise _refuse_settlement_shape(
                f"This settlement refused the {refusal.leg} leg twice.",
                "One refusal per leg: a leg has one reason it could not be priced.",
            )
        refused.add(refusal.leg)
    for quantity in request.quantities:
        if quantity.leg in refused:
            raise _refuse_settlement_shape(
                f"This settlement both priced and refused the {quantity.leg} leg.",
                "A refusal names a leg; quantities name other legs.",
            )


def _refuse_settlement_shape(detail: str, remediation: str) -> ProblemError:
    """One code for every way a settlement body contradicts itself about a leg.

    ONE CODE AND TWO MESSAGES: an operator reading the log needs to know the worker sent a
    self-contradictory body, and the two ways it can are one fault with one fix.
    """
    return ProblemError(
        kind="validation",
        code="worker_settlement_shape",
        title="A settlement cannot say two things about one leg",
        detail=detail,
        remediation=remediation,
    )


def _price(
    quantities: tuple[MeteredQuantity, ...] | list[MeteredQuantity],
) -> tuple[tuple[_Priced, ...], tuple[SettlementRefusal, ...]]:
    """Every leg we hold a rate for, and a refusal for every leg we do not (D-625).

    ⚠ **IT USED TO BE "every leg, or the FIRST refusal — THERE IS NO PARTIAL SETTLEMENT",
    AND THAT WAS THE SERVER HALF OF THE SAME DEFECT `meter.MeteredCall` NAMES.** One leg
    whose model nobody has attested a price for discarded every other leg of the call,
    permanently, into an append-only ledger. The legs are priced independently because they
    FAIL independently: an unattested `gemini-2.5-flash-lite` says nothing about whether we
    can price the STT seconds beside it.

    Nothing here writes a zero for a refused leg, and nothing prices a leg twice — the caller
    has already checked that no leg arrives both priced and refused (`_check_settlement`).

    **THE RATE CARD IS HERE AND NOWHERE ELSE, WHICH IS WHY THE WIRE CARRIES NO MONEY.**
    `billing/rates.py` is the one door a rupee comes through and it RAISES on a model nobody
    attested (hard rule 7); a worker holding a rate card would be a container on a vendor's
    infrastructure that can invent a price.

    ⚠ **TWO OF THE FIVE LEGS §1.3 NAMES CANNOT BE PRICED FROM A RATE CARD AT ALL, AND ARE
    REFUSED HERE BY NAME.** The carrier's connected minute is priced by the CARRIER (§1.2
    makes their CDR the authority for both the quantity and the charge) and Pipecat Cloud's
    active minute is an UNANSWERED VENDOR QUESTION (§7 P-1). Neither is a number this
    process holds, and neither is a number the worker may assert — so a quantity naming
    either leg settles as a recorded refusal, exactly as `CarrierFactsMissingError` and
    `RuntimePriceUnknownError` do today. That is the same outcome production already has,
    with the reason on the row instead of in a container's memory.
    """
    priced: list[_Priced] = []
    refusals: list[SettlementRefusal] = []
    for quantity in quantities:
        try:
            priced.append(_price_one(quantity))
        except _LegNotPriceableError as unpriceable:
            refusals.append(unpriceable.refusal)
    return tuple(priced), tuple(refusals)


def _price_one(quantity: MeteredQuantity) -> _Priced:
    unit = quantity.unit_type
    if unit == "stt_s":
        return _Priced(unit, quantity.qty, stt_rate_inr_per_second(), dict(quantity.meta))
    if unit == "tts_kchars":
        # Per THOUSAND characters, because `unit_cost_paid` is NUMERIC(12,4) and a per-
        # character rate of ₹0.0034496 stores as 0.0034 — 1.4% light on every call.
        # `billing/models.py` argues the quantum in full at the column.
        return _Priced(
            unit, quantity.qty, tts_rate_inr_per_char() * Decimal(1000), dict(quantity.meta)
        )
    if unit in ("llm_ktok_in", "llm_ktok_out"):
        return _Priced(unit, quantity.qty, _llm_rate(quantity), dict(quantity.meta))
    raise _LegNotPriceableError(
        SettlementRefusal(
            leg=quantity.leg,
            code="meter_leg_not_priceable_here",
            detail=(
                f"the {quantity.leg} leg reported {unit!r}, which no rate card prices: this "
                "leg's charge is a fact somebody else witnessed, not a rate we hold."
            ),
            remediation=(
                "The carrier's connected minute comes from their CDR (PIPECAT-MIGRATION.md "
                "§1.2) and the platform's active minute is an unanswered vendor question "
                "(§7 P-1). Settle both from the reconciliation that reads them, never from "
                "the worker's own clock."
            ),
        )
    )


def _llm_rate(quantity: MeteredQuantity) -> Decimal:
    """The attested per-1,000-token rate for the model this leg ran on, or a refusal.

    The model travels in `meta` because it is a property of the MEASUREMENT — which model
    reported these tokens — and not of the unit. `llm_inr_per_ktok` is the one door and it
    raises rather than returning zero for a price nobody attested.
    """
    model = quantity.meta.get("model")
    if not model:
        raise _LegNotPriceableError(
            SettlementRefusal(
                leg=quantity.leg,
                code="meter_llm_model_unnamed",
                detail="an LLM leg reported tokens without naming the model that produced them.",
                remediation=(
                    "Two models in one call, or a report with no model, cannot be priced: "
                    "the rate is per model. Check the agent's published ModelConfig."
                ),
            )
        )
    try:
        price = llm_inr_per_ktok(model)
    except (ValueError, LookupError) as exc:
        raise _LegNotPriceableError(
            SettlementRefusal(
                leg=quantity.leg,
                code="meter_rate_refused",
                detail=f"the rate card refused to price {model!r} on the llm leg: {exc}",
                remediation=(
                    "Enter the price from the vendor invoice in the ops console. Until it "
                    "is attested this leg is unmetered, which is not the same as free."
                ),
            )
        ) from exc
    key = "in" if quantity.unit_type == "llm_ktok_in" else "out"
    rate = price.get(key)
    if rate is None:
        raise _LegNotPriceableError(
            SettlementRefusal(
                leg=quantity.leg,
                code="meter_rate_refused",
                detail=f"the rate card returned no {key!r} rate for {model!r}.",
                remediation="Attest both halves of the model's price in the ops console.",
            )
        )
    return rate


#: The only `meta` keys a worker may contribute to an append-only ledger row.
#:
#: ⚠ **AN ALLOW-LIST, AND THE TWO KEYS IT DELIBERATELY OMITS ARE THE POINT (18 Sep 2026).**
#: `meta->>'tts_tier'` is the rung every client-facing usage split reads and `meta->>'model'`
#: is what chooses the LLM rate — so both are money, decided by us from the agent's published
#: config, never asserted by a container running on a vendor's infrastructure. They were
#: copied through verbatim, and `**row.meta` sat AFTER `total_inr` in the JSON, so a body
#: carrying `{"total_inr": "0.0001"}` overwrote the server's own computed total in a row
#: hard rule 4 makes uncorrectable.
#:
#: What remains is measurement: what the worker counted and how. Anything not named here is
#: DROPPED rather than refused — an unknown key is a client of a newer version describing its
#: own measurement, which is not a reason to lose a call's whole settlement.
_WORKER_META_KEYS: Final[frozenset[str]] = frozenset(
    {"processors", "reports", "characters", "total_tokens", "audio_seconds"}
)


def _worker_meta(meta: Mapping[str, str]) -> dict[str, str]:
    """The worker's measurement notes, less anything that decides money."""
    return {key: value for key, value in meta.items() if key in _WORKER_META_KEYS}


async def _write_usage(
    session: AsyncSession,
    tenant_id: UUID,
    call_row_id: UUID,
    rows: tuple[_Priced, ...],
    *,
    at: datetime,
) -> None:
    """The metered legs. Zero rows writes nothing and is not an error — a call that
    transcribed and synthesised nothing has no leg to price, which is distinct from a leg
    nobody can price."""
    for row in rows:
        await session.execute(
            text(_INSERT_USAGE_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": call_row_id,
                "unit": row.unit_type,
                "qty": row.qty,
                "cost": row.unit_cost_inr,
                "at": at,
                # THE SERVER'S OWN FIELDS GO LAST so nothing on the wire can displace
                # them. `total_inr` is the product this function just computed from an
                # attested rate; it is not a value anyone else gets a say in.
                "meta": json.dumps(
                    {**_worker_meta(row.meta), "total_inr": str(row.unit_cost_inr * row.qty)}
                ),
            },
        )


async def _write_refusal(
    session: AsyncSession,
    tenant_id: UUID,
    call_row_id: UUID,
    refusal: SettlementRefusal,
    *,
    at: datetime,
) -> None:
    await session.execute(
        text(_INSERT_REFUSAL_SQL),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "cid": call_row_id,
            "leg": refusal.leg,
            "code": refusal.code,
            # OUR OWN PROSE. Every refusal string is authored in this repository or in
            # `voice_worker/meter.py`'s refusal classes and quotes no payload, no transcript
            # and no number — the same bar `core/alerting.alert` sets for its `detail`.
            "detail": refusal.detail,
            "remediation": refusal.remediation or "",
            "at": at,
        },
    )


# --- the call row, which every path passes through -------------------------------------


@dataclass(frozen=True, slots=True)
class _CallRow:
    """The call row as it stands after the upsert: its id and who was on it.

    **THE PARTIES ARE READ BACK RATHER THAN ECHOED, AND THAT IS THE POINT.** The upsert
    COALESCEs the stored value over the incoming one, so a settlement carrying no parties
    against a call whose first observation batch DID carry them must not read as "nobody was
    on this call". What the statement RETURNS is what the column holds; what the request said
    is a claim about one delivery.
    """

    id: UUID
    from_e164: str | None
    to_e164: str | None


async def _upsert_call(
    session: AsyncSession,
    *,
    engine_call_id: str,
    tenant_id: UUID,
    agent_id: UUID,
    direction: str,
    status: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    from_e164: str | None,
    to_e164: str | None,
) -> _CallRow:
    """Write the call row and answer it. Status only ever moves forward.

    A status the forward-only clause REFUSES returns no row, which is not an error: a
    terminal call receiving a late `in_progress` is exactly what that clause is for, and the
    id is then read back — the same fallback `apps/workers/pipeline._upsert_call_row` uses.

    `agent_id` is REQUIRED and not derived. A `calls` row cannot be minted without one, and
    the only two callers both hold it as a session fact — which is why `ObservationBatch`
    carries it rather than leaving it to be picked out of whichever event arrived first.

    `from_e164`/`to_e164` are OPTIONAL and are learned once: see the SQL's own comment for
    why the stored value wins on conflict. Today no carrier leg supplies them (DEPLOYMENT
    §12.5 gate 9), so in practice they arrive `None` and the column stays NULL — which is
    what `leads`, caller memory and the erasure subject all already handle, badly but
    knowingly. This function's job is to make sure that when a producer DOES exist, nothing
    between the wire and the column has to change.
    """
    row = (
        await session.execute(
            text(_UPSERT_CALL_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": engine_call_id,
                "dir": direction,
                "status": status,
                "started": started_at,
                "ended": ended_at,
                "dur": _duration_s(started_at, ended_at),
                "from_e": from_e164,
                "to_e": to_e164,
                "terminal": sorted(TERMINAL_STATUSES),
            },
        )
    ).first()
    if row is None:
        row = (
            await session.execute(
                text("SELECT id, from_e164, to_e164 FROM calls WHERE engine_call_id = :ecid"),
                {"ecid": engine_call_id},
            )
        ).first()
        if row is None:  # pragma: no cover - only on a concurrent delete
            raise RuntimeError("call row vanished during upsert")
    return _CallRow(id=UUID(str(row[0])), from_e164=row[1], to_e164=row[2])


def _duration_s(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    """Our own wall clock across the session, or `None`.

    ⚠ **NOT THE BILLABLE DURATION AND NEVER USABLE AS ONE.** §1.2 gives the connected minute
    to the carrier; this column is what a screen shows a client about their own call.
    """
    if started_at is None or ended_at is None:
        return None
    return max(0, round((ended_at - started_at).total_seconds()))


__all__ = [
    "ENGINE_NAME",
    "POSTCALL_DEDUPE_PREFIX",
    "POSTCALL_JOB",
    "authorized",
    "engine_enabled",
    "load_session",
    "record_observations",
    "record_prompt_attestation",
    "refuse_wrong_engine",
    "settle_call",
]
