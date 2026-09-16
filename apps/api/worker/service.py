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

from apps.api.billing.rates import (
    llm_inr_per_ktok,
    stt_rate_inr_per_second,
    tts_rate_inr_per_char,
)
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
WHERE p.agent_id = :aid AND p.tenant_id = :tid
"""

#: The call row, minted or converged on. `from_e164`/`to_e164` are ABSENT rather than
#: NULL-ed, which is the difference between "we do not know" and "there is nobody" — the
#: reconciliation that reads the carrier's CDR owns those two columns (§1.2).
#:
#: THE STATUS CLAUSE IS THE CONSTANT, NOT A COPY OF ITS MEMBERS: a sixth terminal status
#: added to `calevate_shared.events` must be terminal to every statement that asks.
_UPSERT_CALL_SQL: Final = """
INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status,
                   started_at, ended_at, duration_s, created_at, updated_at)
VALUES (:id, :tid, :aid, :ecid, :dir, :status, :started, :ended, :dur, now(), now())
ON CONFLICT (engine_call_id) DO UPDATE SET
  status = EXCLUDED.status,
  started_at = COALESCE(calls.started_at, EXCLUDED.started_at),
  ended_at = COALESCE(EXCLUDED.ended_at, calls.ended_at),
  duration_s = COALESCE(EXCLUDED.duration_s, calls.duration_s),
  updated_at = now()
WHERE calls.status <> ALL(:terminal) OR EXCLUDED.status = 'completed'
RETURNING id
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
        call_row_id = await _upsert_call(
            session,
            engine_call_id=engine_call_id,
            tenant_id=tenant_id,
            agent_id=batch.agent_id,
            direction=batch.direction,
            status=status,
            started_at=_first(batch, "started_at"),
            ended_at=_first(batch, "ended_at"),
        )
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
        call_row_id = await _upsert_call(
            session,
            engine_call_id=engine_call_id,
            tenant_id=tenant_id,
            agent_id=request.agent_id,
            direction=request.direction,
            status=request.final_status,
            started_at=None,
            ended_at=None,
        )
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
                refusal_recorded=False,
                post_call_enqueued=False,
            )
        refusal = request.refusal
        rows: tuple[_Priced, ...] = ()
        if refusal is None:
            try:
                rows = _price(request.quantities)
            except _LegNotPriceableError as unpriceable:
                refusal = unpriceable.refusal
        if refusal is not None:
            await _write_refusal(session, tenant_id, call_row_id, refusal, at=occurred_at)
        else:
            await _write_usage(session, tenant_id, call_row_id, rows, at=occurred_at)

    if refusal is not None:
        # `error` and not `warning`: an unmetered call is spend we absorbed and cannot bill,
        # and it is the state `admin/health.calls_unmetered` stops the board for.
        log.error(
            "worker_call_not_meterable",
            extra={
                "tenant_id": str(tenant_id),
                "call_id": str(call_row_id),
                "leg": refusal.leg,
                "code": refusal.code,
            },
        )
        return SettlementOut(
            already_settled=False,
            rows_written=0,
            refusal_recorded=True,
            post_call_enqueued=True,
        )
    log.info(
        "worker_call_settled",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_row_id),
            "rows": len(rows),
        },
    )
    return SettlementOut(
        already_settled=False,
        rows_written=len(rows),
        refusal_recorded=False,
        post_call_enqueued=True,
    )


def _check_settlement(request: SettlementRequest) -> None:
    """A REFUSAL OR QUANTITIES, NEVER BOTH. Validated rather than trusted.

    A client is a thing on somebody else's infrastructure, and `metered_rows` is
    all-or-nothing by design ("THERE IS NO PARTIAL SETTLEMENT") — so a body offering three
    priced legs AND a refusal is a shape the ledger cannot hold, and is refused.

    ⚠ **NEITHER IS LEGAL, AND THIS CHECK BRIEFLY REFUSED IT BY MISTAKE.** A settlement with
    no refusal and no quantities is the THIRD state `meter.py` distinguishes on purpose: a
    session that transcribed and synthesised nothing has no leg to price, which is not the
    same thing as a leg nobody can price. `sink.Settlement`'s docstring names all three
    ("zero of both is a call with nothing to meter at all"), the in-process sink wrote
    neither row for it, and `admin/health.calls_unmetered` is what notices a call carrying no
    money. Turning it into a 422 would have left such a call permanently unsettled and its
    post-call pipeline never promised — extraction, CRM columns and lead, silently absent.
    Caught by `tests/voice_worker_sink_test.py::test_settlement_sends_the_transcript_before_
    it_settles_anything`, which drives that state through a real request.
    """
    if request.refusal is not None and request.quantities:
        raise ProblemError(
            kind="validation",
            code="worker_settlement_shape",
            title="A settlement is a refusal or a set of quantities",
            detail=(
                "This settlement carried both a refusal and metered quantities. There is no "
                "partial settlement."
            ),
            remediation="Send the refusal the meter reached, or the quantities it measured.",
        )


def _price(quantities: tuple[MeteredQuantity, ...] | list[MeteredQuantity]) -> tuple[_Priced, ...]:
    """Every leg, or the first refusal. **THERE IS NO PARTIAL SETTLEMENT.**

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
    for quantity in quantities:
        priced.append(_price_one(quantity))
    return tuple(priced)


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
                "meta": json.dumps({"total_inr": str(row.unit_cost_inr * row.qty), **row.meta}),
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
) -> UUID:
    """Write the call row and answer its id. Status only ever moves forward.

    A status the forward-only clause REFUSES returns no row, which is not an error: a
    terminal call receiving a late `in_progress` is exactly what that clause is for, and the
    id is then read back — the same fallback `apps/workers/pipeline._upsert_call_row` uses.

    `agent_id` is REQUIRED and not derived. A `calls` row cannot be minted without one, and
    the only two callers both hold it as a session fact — which is why `ObservationBatch`
    carries it rather than leaving it to be picked out of whichever event arrived first.
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
                "terminal": sorted(TERMINAL_STATUSES),
            },
        )
    ).first()
    if row is None:
        row = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :ecid"),
                {"ecid": engine_call_id},
            )
        ).first()
        if row is None:  # pragma: no cover - only on a concurrent delete
            raise RuntimeError("call row vanished during upsert")
    return UUID(str(row[0]))


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
    "load_session",
    "record_observations",
    "settle_call",
]
