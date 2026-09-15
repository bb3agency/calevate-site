"""`NormalizedEventSink`, over the database. The worker's record of what happened on a call.

**WHAT ALREADY EXISTED, AND WHAT THIS IS.** `apps/workers/pipeline.py` is this repository's
writer of `calls`, `transcript_turns` and `usage_events`, and nothing here replaces it: every
statement below is the SAME shape, against the same columns, with the same idempotency key
and the same redactor, so the two writers converge on one row rather than producing two
readings of it. What did not exist is a writer that runs while the call is still happening,
because until D-592 no process of ours was ON the call — a rented engine told us afterwards.
That is the whole difference, and it is why this is a new file and not a new function over
there: `apps/workers/pipeline.py` reaches its rows through `apps.api.db.session`,
`apps.api.core.settings` and the engine factory, i.e. the monolith, which this container
does not carry (`pyproject.toml`, `storage.py`, `db.py`).

**THE ONE THING IT DOES NOT DO IS REDACT ITS OWN WAY.** `apps/workers/redaction.py::redact`
is the repository's single redaction primitive — validators, Luhn, the numbering plan, the
Telugu spoken-digit pass, and a coverage-ratchet entry naming it "hard rule 5/6: the
redaction primitive". A second redactor here would be two ways of doing one thing with the
WEAKER of the two on the live path, which is the drift the quality bar refuses outright. So
it is imported, and the import is safe to make from this container for a measured reason
rather than a hopeful one: `apps.workers.redaction` imports `re` and `dataclasses` and
nothing else, `apps/__init__.py` and `apps/workers/__init__.py` are both empty, and the
module graph it pulls in contains no `apps.api` module at all (measured 15 Sep 2026;
`tests/voice_worker_sink_test.py::test_the_redaction_import_does_not_drag_the_monolith`
asserts it, so it cannot quietly stop being true).

**HARD RULE 1.** Every statement runs inside `WorkerDatabase.tenant_connection`, whose
transaction sets `app.tenant_id`; the `tenant_id` in each WHERE/VALUES clause is belt to
that braces, on `config.py`'s and `apps/api/kb/pack.py`'s stated pattern. The sink is built
for ONE session and refuses an event naming a different tenant, agent or call than the
four ids it was built from — see `_check_identity`. That refusal is not paranoia
about our own code: `NormalizedEventBoundary` is the only producer today, and the day a
second one exists it must not be able to write across a tenant boundary by constructing an
event badly.

**HARD RULE 6.** Transcript text reaches exactly two places: the `text` column and
`redact()`. It is never logged, never rendered into an exception (`db.py` sets
`hide_parameters=True` for exactly that), and never counted in a log line beyond its
index. Nothing here logs a phone number because nothing here HAS one — the worker is
handed no party numbers, and `calls.from_e164`/`to_e164` stay NULL for the reconciliation
that owns them to fill (§1.2: the carrier is the authority for who rang whom).

**HARD RULE 4 AND 7, WHICH ARE THE SAME DECISION SEEN TWICE.** `usage_events` is
INSERT-only, so a leg written wrong can never be corrected by an UPDATE — only by a
compensating row. That is why `settle` writes all five legs or none of them, and why a leg
whose quantity could not be read produces a `call_metering_refusals` row instead of a
zero. `meter.py`'s refusal classes already carry the four things such a row needs (`leg`,
`code`, `detail`, `remediation`); this catches `LegNotMeterableError` to RECORD it, which
is the one thing that base class's docstring permits — what it forbids is catching it to
substitute a zero, and no zero is written anywhere below.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from apps.workers.redaction import redact
from calevate_shared.engine import pipecat_call_ref
from calevate_shared.events import (
    TERMINAL_STATUSES,
    CallDirection,
    CallEvent,
    CallStatus,
    TranscriptTurn,
)
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# `uuid_utils.compat.uuid7` and NOT `apps.api.db.base.uuid7`, which is what the rest of the
# tree imports. The two produce the same thing — a stdlib `uuid.UUID` holding a v7 — and the
# repo's helper exists only because it predates the vendor shipping this shim (it hand-copies
# `.bytes`). Reaching into `apps.api` for one line would contradict this container's whole
# dependency argument for no gain. Hard rule 9: `uuid-utils` already resolves in this one
# venv for `apps/api`; declaring it in `apps/voice-worker/pyproject.toml` adds an edge, not a
# distribution.
from uuid_utils.compat import uuid7

from voice_worker.db import WorkerDatabase
from voice_worker.meter import CallMeter, CarrierCdr, LegNotMeterableError, RuntimeUsage, UsageRow
from voice_worker.outbox import enqueue_outbox_once
from voice_worker.pipeline import ENGINE_NAME

#: The call row, minted or converged on. `apps/workers/pipeline.py::_upsert_call_row`'s
#: statement with the columns this worker is the author of and no others.
#:
#: **`from_e164`/`to_e164` ARE ABSENT RATHER THAN NULL-ED**, which is the difference between
#: "we do not know" and "there is nobody". The reconciliation that reads the carrier's CDR
#: owns those two columns (§1.2), and an UPDATE from here would overwrite a witnessed number
#: with our own ignorance the moment a late event arrived.
#:
#: **THE STATUS CLAUSE IS THE CONSTANT, NOT A COPY OF ITS MEMBERS**, for the reason
#: `_upsert_call_row` records in full: a sixth terminal status added to
#: `calevate_shared.events` must be terminal to every statement that asks the question, and
#: a SQL literal is the one that silently would not be.
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

#: One turn. `ON CONFLICT (call_id, idx) DO UPDATE` rather than `DO NOTHING` so this agrees
#: with `_persist_transcript`, which is the other writer of this table and replaces a turn
#: on a re-read (D-187). `transcript_turns` is NOT an append-only ledger
#: (`db/registry.APPEND_ONLY_TABLES`), so a correction is a correction and not a rewrite of
#: evidence.
_INSERT_TURN_SQL: Final = """
INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, text_redacted,
                              lang, start_ms, end_ms, created_at, updated_at)
VALUES (:id, :tid, :cid, :idx, :speaker, :text, :redacted, :lang, :start, :end, now(), now())
ON CONFLICT (call_id, idx) DO UPDATE SET
  speaker = EXCLUDED.speaker, text = EXCLUDED.text,
  text_redacted = EXCLUDED.text_redacted, lang = EXCLUDED.lang,
  start_ms = EXCLUDED.start_ms, end_ms = EXCLUDED.end_ms,
  updated_at = now()
"""

#: One metered leg. **`DO NOTHING`, NEVER `DO UPDATE`** — this table is append-only under
#: hard rule 4 and carries a `calevate_forbid_mutation` trigger, so an `ON CONFLICT DO
#: UPDATE` would not be a design choice here, it would be a runtime error on the second
#: settlement of a call. Converging on the first row is also the right SEMANTICS: a
#: re-settlement that priced the leg differently is a fact somebody needs to see, and the
#: way this ledger shows it is a compensating entry, never an overwrite.
#:
#: The money is handed over UNQUANTIZED and the COLUMN rounds it. `UsageRow` promises an
#: exact, unquantized rate and asks the writer to quantize once at the column's own quantum
#: with `ROUND_HALF_UP`; `NUMERIC(12,4)` rounds half-away-from-zero, which is the same
#: function on the non-negative values this ledger holds (verified against Postgres 16 —
#: `0.00005::numeric(12,4)` = `0.0001`). Doing it here instead would put a second home for
#: `billing/rates.MONEY_Q` in a deployable that does not otherwise know that constant
#: exists.
_INSERT_USAGE_SQL: Final = """
INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid,
                          occurred_at, meta, created_at)
VALUES (:id, :tid, :cid, :unit, :qty, :cost, :at, CAST(:meta AS jsonb), now())
ON CONFLICT DO NOTHING
"""

#: A leg we could not honestly price, recorded so that "why did this call meter nothing" has
#: an answer that is not a shrug. Append-only: a refusal is evidence about one settlement
#: attempt, and a later attempt that succeeds writes `usage_events` rows rather than editing
#: the record of the attempt that failed.
_INSERT_REFUSAL_SQL: Final = """
INSERT INTO call_metering_refusals (id, tenant_id, call_id, leg, code, detail, remediation,
                                    occurred_at, created_at)
VALUES (:id, :tid, :cid, :leg, :code, :detail, :remediation, :at, now())
"""

#: The ARQ job the post-call pipeline runs under — extraction, the CRM columns, the lead,
#: the hot-lead alert. `apps/workers/pipeline.POSTCALL_JOB`, RESTATED AS A LITERAL RATHER
#: THAN IMPORTED, and the duplication is deliberate and tested rather than accidental.
#:
#: Importing it would drag `apps.workers.pipeline` — and through it `apps.api.engine`,
#: `apps.api.db.session` and the whole monolith — into a voice container whose entire
#: dependency argument is that it carries none of that (`pyproject.toml`, `db.py`,
#: `storage.py`). `apps/workers/pipeline.py:136-145` records the same trade for
#: `billing.service.INBOUND_CUTOVER_JOB` and the same reason it must be a module-level
#: constant and not an inline literal: `scripts/check_job_wiring.py` resolves a job name
#: only as a literal or a module-level constant IN THE FILE THAT ENQUEUES IT, and an
#: unresolvable name is exactly the hole its shape 3 hides in.
#:
#: `tests/voice_worker_postcall_test.py::test_the_worker_and_the_fleet_name_one_job`
#: is what holds the two spellings in step.
POSTCALL_JOB: Final = "run_post_call_pipeline"

#: What makes the promise idempotent. The KEY NAMES THE SIDE EFFECT AND NOT THE ROW
#: (`enqueue_outbox_once`'s own rule: "a key containing a fresh uuid is a key that dedupes
#: nothing"), and the side effect here is "this call's post-call pipeline", once, ever.
#:
#: **KEYED ON `calls.id` AND NOT ON THE ENGINE CALL REF**, which is the narrower of the two
#: and the correct one: `calls.engine_call_id` is the unique key the row converges on, so
#: the surrogate id is one-to-one with it, and every OTHER consumer of this pipeline
#: already addresses a call by `calls.id` — including `job_id_for(POSTCALL_JOB,
#: str(call_id))`, the ARQ-level dedupe the dispatcher applies on top of this one.
#: `post-call:` prefixed for the reason the existing keyspaces are (`hot-lead:`,
#: `campaign-escalation:`): a reader of the column can tell what promised it.
_POSTCALL_DEDUPE_PREFIX: Final = "post-call:"


class SinkIdentityError(RuntimeError):
    """An event named a tenant, agent or call this sink was not built for.

    RAISED and not logged-and-dropped. A sink is built for one session; an event carrying
    another session's ids is either a bug in the producer or a crossed wire between two
    concurrent calls in one container, and both of those are hard rule 1 faults that must
    stop the write rather than pick one of the two tenants and be right half the time.

    Ids only (hard rule 6).
    """


@dataclass(frozen=True, slots=True)
class Settlement:
    """What one settlement attempt did. Returned so a caller can log the branch, not decide it.

    `refused` is a tri-state in disguise and the three cases matter: `rows` written and no
    refusal is a settled call; a `refusal_code` and no rows is a call recorded as unmetered;
    and zero of both is a call with nothing to meter at all (a session that transcribed and
    synthesised nothing), which `meter.py` distinguishes from an unpriceable one by design.
    """

    rows: int
    refusal_code: str | None = None
    refusal_leg: str | None = None
    #: Whether THIS settlement wrote the outbox row that starts the post-call pipeline.
    #: `False` on a re-settlement is the correct and expected answer — the promise was
    #: already on the books and the pipeline must run once, not twice (`_enqueue_post_call`).
    post_call_enqueued: bool = False


class DatabaseEventSink:
    """The production `NormalizedEventSink`: OUR normalized models in, our own rows out.

    **ONE PER CALL, AND THAT IS WHAT MAKES THE TENANCY CHECK POSSIBLE.** `TranscriptTurn`
    carries a `call_id` and no tenant — it cannot, it is the shape every engine's transcript
    normalizes to — so the tenant a turn belongs to has to come from somewhere, and the only
    honest somewhere is the `SessionConfig` this call was assembled from. A process-wide
    sink would have to infer it from the call id, i.e. read it back out of a table it is
    about to write to, which is how a crossed wire becomes a cross-tenant write.

    **WRITES ARE SERIALIZED BEHIND ONE LOCK.** Pipecat dispatches every event handler as its
    own task (`pipecat/utils/base_object.py:256-261`, read in the installed 1.10.0 tree), so
    two turns and the call-ended event can be in flight at once. Serializing them costs
    nothing on a path that is already off the conversation's critical path — the same
    dispatch that makes them concurrent is what keeps them off it — and it buys two
    properties worth having: the `calls` row exists before any turn references it (the FK is
    `ON DELETE RESTRICT`, so a race would surface as an IntegrityError mid-call), and one
    connection is the most this sink ever holds, which is what `db.MAX_OVERFLOW` being zero
    rests on.
    """

    def __init__(
        self,
        database: WorkerDatabase,
        *,
        call_id: str,
        tenant_id: UUID,
        agent_id: UUID,
        direction: CallDirection,
    ) -> None:
        """The four ids this call is, and nothing else.

        **FOUR IDS RATHER THAN A `SessionConfig`, WHICH IS THE ONE SHAPE DECISION HERE.**
        Those are the only fields of that object this sink would read — and taking the whole
        thing would mean the sink could not exist until the config had been loaded out of the
        database, which is precisely the order `session.start_session` does NOT have: it
        takes the sink as an argument and loads the config itself, exactly as it takes the
        transport. Narrowing the dependency is what lets that function keep its signature and
        keeps this testable with no `SessionConfig` at all.
        """
        self._db = database
        self._call_id = call_id
        #: What lands in `calls.engine_call_id` — the idempotency key every writer of that
        #: row converges on, and the handle `apps/api/engine/pipecat.py` is later handed
        #: back as `get_execution(call_id)`.
        #:
        #: **MINTED HERE RATHER THAN TAKEN AS A FIFTH ARGUMENT**, because this is the only
        #: place that has both halves by construction and the only place that writes the
        #: column. A caller that had to assemble it could assemble it wrongly, and the
        #: failure would be silent and late: the adapter parses the tenant back OUT of this
        #: string to find the row under RLS (`pipecat_call_ref`), so a plain uuid here is a
        #: call whose post-call pipeline can never read its own transcript.
        self._engine_call_id = pipecat_call_ref(tenant_id, call_id)
        self._tenant_id = tenant_id
        self._agent_id = agent_id
        self._direction = direction
        self._lock = asyncio.Lock()
        #: `calls.id`, resolved on the first write and reused. NOT the same value as
        #: `config.call_id`: that is OUR call id and lands in `engine_call_id`, which is the
        #: idempotency key; this is the row's own surrogate, which every child table's FK
        #: points at.
        self._call_row_id: UUID | None = None

    # -- the Protocol --------------------------------------------------------------------

    async def on_call_event(self, event: CallEvent) -> None:
        """One lifecycle event. Status only ever moves forward."""
        self._check_identity(
            call_id=event.call_id, tenant_id=event.tenant_id, agent_id=event.agent_id
        )
        async with self._lock, self._db.tenant_connection(self._tenant_id) as connection:
            # `_upsert_call` and NOT `_ensure_call_row`: a lifecycle event is the one path
            # that must ALWAYS issue the statement. The memo below is what stops a turn
            # costing a round trip it does not need, and routing the terminal event through
            # it left every call sitting at `in_progress` for ever — caught by
            # `test_a_call_event_and_its_turns_persist_under_the_calling_tenant`, which read
            # the status back rather than trusting that the write happened.
            await self._upsert_call(
                connection,
                status=event.status,
                started_at=event.started_at,
                ended_at=event.ended_at,
            )
        logger.info(
            "call event recorded",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            agent_id=str(self._agent_id),
            status=event.status,
        )

    async def on_transcript_turn(self, turn: TranscriptTurn) -> None:
        """One turn, raw and redacted, in the two columns every reader already knows.

        **`text_redacted` IS FILLED HERE AND `NormalizedEventBoundary` LEAVES IT `None` —
        BOTH ARE CORRECT AND THE SPLIT IS THE POINT.** The boundary converts a vendor object
        into our model and does nothing else; redaction is a property of the ROW, not of the
        event.

        **WHAT A NULL IN THAT COLUMN ACTUALLY COSTS, CHECKED RATHER THAN ASSUMED.** This
        paragraph first said a NULL "serves RAW TEXT to the dashboard", on the strength of a
        `COALESCE(text_redacted, text)` the author had seen and not opened. That is wrong in
        the direction that matters, and the truth is worse for a different reason. Every
        CONTENT reader in this repository names `text_redacted` and only `text_redacted` —
        `apps/api/crm/assist.py::_TURNS_SQL` ("THE COLUMN IS `text_redacted` AND THE RAW ONE
        IS NOT NAMED IN THIS FILE", `:270-279`) and `apps/workers/caller_memory_distil.py::
        _TURNS_SQL`, which SKIPS a turn whose redaction has not landed and says why
        (`:235-242`). The two places that do COALESCE ask for a `length()` and never a
        character (`apps/workers/pipeline.py:3112-3128`,
        `apps/api/billing/tts_speaking_rate.py:107`), so they engage no rule.

        So a turn written with `text_redacted` NULL is not a leak — it is INVISIBLE. It does
        not reach the client's transcript, the copilot or caller memory. ⚠ **AND IT USED TO
        STAY INVISIBLE FOR EVER, WHICH IS NO LONGER TRUE AND THIS PARAGRAPH USED TO SAY IT
        WAS.** The pass that fills that column downstream is `apps/workers/pipeline.py::
        _persist_transcript`, and until D-607 it had no way to run on this engine: it rides
        the post-call pipeline, which rode the reconciliation poller, and
        `PipecatEngine.list_executions` reports nothing for an `owned_runtime` call by
        design. `settle` now writes the outbox row that starts that pipeline in its own
        transaction, so the downstream pass DOES run.

        Writing the column here is still right and is not made redundant by that. It is what
        makes a turn visible WHILE THE CALL IS HAPPENING and for the minutes between hang-up
        and the dispatcher's next tick, and it is what a call whose pipeline is retrying
        still has. Doing it with the repository's one redactor is what keeps hard rule 5's
        promise about which column that is.
        """
        self._check_identity(call_id=turn.call_id)
        # The one call. `RedactionResult.kinds` says WHAT was found and is loggable; the
        # text either side of it is not, and neither is counted or sampled anywhere below.
        redacted = redact(turn.text)
        async with self._lock, self._db.tenant_connection(self._tenant_id) as connection:
            call_row_id = await self._ensure_call_row(connection)
            await connection.execute(
                text(_INSERT_TURN_SQL),
                {
                    "id": uuid7(),
                    "tid": self._tenant_id,
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
        logger.info(
            "transcript turn recorded",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            idx=turn.idx,
            speaker=turn.speaker,
            # WHAT was redacted, never what was said. `kinds` is a list of category names
            # this repository authored ("phone", "aadhaar"); an operator needs it to know
            # the pass is running at all, and it quotes nothing.
            redacted_kinds=",".join(redacted.kinds),
        )

    # -- settlement ----------------------------------------------------------------------

    async def settle(
        self,
        meter: CallMeter,
        *,
        carrier: CarrierCdr | None,
        runtime: RuntimeUsage | None,
        at: datetime | None = None,
    ) -> Settlement:
        """Price the five legs and write them, or record why they could not be priced.

        **ALL FIVE OR NONE, IN ONE TRANSACTION.** `metered_rows` is all-or-nothing by design
        ("THERE IS NO PARTIAL SETTLEMENT") and so is this: a crash between the STT row and
        the LLM row would leave an append-only ledger holding a call that cost a third of
        what it cost, with no UPDATE available to finish it.

        **AND THE POST-CALL TRIGGER IS INSIDE THAT SAME TRANSACTION (D-607).** The outbox row
        that starts `run_post_call_pipeline` commits with the ledger and with the call row, so
        a settled call cannot exist without its trigger and a trigger cannot exist without
        the row that justifies it. The cost of putting it here is stated rather than hidden:
        a settlement that RAISES rolls the trigger back with everything else, so a call whose
        settlement crashed has no pipeline — which is the correct pairing (nothing claims to
        have settled) and is loud (the exception reaches `runtime.run_call`), rather than a
        half-written call quietly carrying a promise about a ledger that was never written.

        **CALLED AFTER THE PIPELINE HAS DRAINED, NEVER FROM INSIDE ITS TEARDOWN.**
        `CallMeter.attach` states the reason: usage reports arrive as their own tasks, so a
        report pushed in the last instants of a session is only counted if the loop gets one
        more turn. `runtime.py` settles after `PipelineWorker` has stopped and before the
        pool is disposed.

        Both `carrier` and `runtime` are required-and-nullable rather than optional, which
        is `metered_rows`' own choice carried through unchanged: a caller must SPELL
        `carrier=None` to reach a refusal, and cannot reach one by forgetting an argument.
        ⚠ **TODAY EVERY PRODUCTION CALL REACHES `CarrierFactsMissingError` HERE**, because
        the CDR is the carrier's and there is no carrier yet (BLOCKER-1). That is not a
        defect in this method: it is §1.2's split working — the worker cannot witness the
        billable minute, so it records that nobody has, and the reconciliation settles the
        call when the CDR lands.
        """
        occurred_at = at or datetime.now(UTC)
        refusal: LegNotMeterableError | None = None
        rows: tuple[UsageRow, ...] = ()
        try:
            rows = meter.metered_rows(carrier=carrier, runtime=runtime)
        except LegNotMeterableError as caught:
            refusal = caught

        # ONE TRANSACTION FOR ALL THREE WRITES, AND THAT IS THE WHOLE GUARANTEE (D-607).
        # The call row, the ledger (or the refusal that stands in for it) and the outbox
        # row that triggers the post-call pipeline commit together or not at all. Before
        # this there were three transactions and one of the three branches — a call with
        # nothing to meter — opened none at all; a crash between them could leave a settled
        # call with no trigger, which on this engine means no extraction, no CRM columns
        # and no lead, silently and for ever (there is no poller behind it: `PipecatEngine.
        # list_executions` reports nothing by design, `apps/api/engine/pipecat.py`).
        async with self._lock, self._db.tenant_connection(self._tenant_id) as connection:
            call_row_id = await self._ensure_call_row(connection)
            if refusal is not None:
                await self._write_refusal(connection, call_row_id, refusal, at=occurred_at)
            else:
                await self._write_usage(connection, call_row_id, rows, at=occurred_at)
            enqueued = await self._enqueue_post_call(connection, call_row_id)

        if refusal is not None:
            # `error` and not `warning`: an unmetered call is spend we absorbed and cannot
            # bill, and it is the state `admin/health.py::calls_unmetered` stops the board
            # for.
            logger.error(
                "call leg not meterable",
                call_id=self._call_id,
                tenant_id=str(self._tenant_id),
                leg=refusal.leg.value,
                code=refusal.code,
                post_call_enqueued=enqueued,
            )
            return Settlement(
                rows=0,
                refusal_code=refusal.code,
                refusal_leg=refusal.leg.value,
                post_call_enqueued=enqueued,
            )
        logger.info(
            "call settled",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            legs=",".join(sorted({row.leg.value for row in rows})),
            rows=len(rows),
            post_call_enqueued=enqueued,
        )
        return Settlement(rows=len(rows), post_call_enqueued=enqueued)

    async def _write_usage(
        self,
        connection: AsyncConnection,
        call_row_id: UUID,
        rows: tuple[UsageRow, ...],
        *,
        at: datetime,
    ) -> None:
        """The metered legs. Zero rows writes nothing and is not an error — `meter.py`
        distinguishes a call with nothing to meter from one it cannot price, and so does
        this."""
        for row in rows:
            await connection.execute(
                text(_INSERT_USAGE_SQL),
                {
                    "id": uuid7(),
                    "tid": self._tenant_id,
                    "cid": call_row_id,
                    "unit": row.unit_type,
                    "qty": row.qty,
                    "cost": row.unit_cost_inr,
                    "at": at,
                    "meta": _meta_json(row),
                },
            )

    async def _write_refusal(
        self,
        connection: AsyncConnection,
        call_row_id: UUID,
        refusal: LegNotMeterableError,
        *,
        at: datetime,
    ) -> None:
        await connection.execute(
            text(_INSERT_REFUSAL_SQL),
            {
                "id": uuid7(),
                "tid": self._tenant_id,
                "cid": call_row_id,
                "leg": refusal.leg.value,
                "code": refusal.code,
                # OUR OWN PROSE, from `meter.py`'s refusal classes. Every one of these
                # strings is authored in this repository and quotes no payload, no
                # transcript and no number — which is the same bar `core/alerting.alert`
                # sets for its `detail` ("a message we authored — never a payload").
                "detail": refusal.detail,
                "remediation": refusal.remediation,
                "at": at,
            },
        )

    async def _enqueue_post_call(self, connection: AsyncConnection, call_row_id: UUID) -> bool:
        """Promise the post-call pipeline, in the settlement's own transaction. Once ever.

        **WHY A ROW AND NOT A JOB.** This container can reach Postgres and nothing else;
        it holds no Redis client and must not grow one (`pyproject.toml` declares no arq
        and no redis, and an enqueue that failed after the ledger committed would be a
        call that settled and never extracted). The outbox is this repository's existing
        answer to exactly that — BACKEND-PATTERNS §4 — and `dispatch_outbox` on its
        ten-second beat is the half that owns Redis.

        **WHY THE POST-CALL PIPELINE AND NOT THE INGEST JOB.** `ingest_engine_event` exists
        to turn a vendor's webhook into a call row: it fetches the execution, resolves the
        tenant from `engine_agent_routes` and upserts `calls`. This worker has already done
        all three — it IS the engine — so routing through ingest would re-derive facts it
        wrote itself and would need an `engine_agent_ref` it has no reason to carry.
        `run_post_call_pipeline` is the entry point the Bolna path reaches after that
        resolution, and it is the SAME function, not a copy: extraction, the moments, the
        knowledge gaps, the lead, the hot-lead alert and the CRM fan-out all run there.

        **IDEMPOTENT AT THE DATABASE.** A re-settlement of the same call — a retried
        container, a second `settle()` after a resumed session — hits the partial unique
        index on `dedupe_key` and writes nothing, exactly as the `usage_events` insert next
        to it converges with `ON CONFLICT DO NOTHING`. `False` here therefore means "it was
        already promised", never "it failed".
        """
        message_id = await enqueue_outbox_once(
            connection,
            job=POSTCALL_JOB,
            payload={
                "tenant_id": str(self._tenant_id),
                "call_id": str(call_row_id),
                "engine": ENGINE_NAME,
                # The ENGINE-SPACE handle, which is what `get_execution` takes and what
                # the adapter parses this call's tenant back out of. Never the bare uuid.
                "execution_id": self._engine_call_id,
            },
            dedupe_key=f"{_POSTCALL_DEDUPE_PREFIX}{call_row_id}",
        )
        return message_id is not None

    # -- internals -----------------------------------------------------------------------

    def _check_identity(
        self,
        *,
        call_id: str,
        tenant_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> None:
        """Refuse an event that is not this session's. See `SinkIdentityError`.

        `tenant_id`/`agent_id` are optional because `TranscriptTurn` carries neither and
        `CallEvent` declares both `| None` (an adapter resolves them from a vendor ref and
        they stay None until it does). What is checked is DISAGREEMENT, not presence: a
        `None` is an event that never claimed, and a claim that differs is the fault.
        """
        if call_id != self._call_id:
            raise SinkIdentityError(
                f"event names call {call_id!r}, sink was built for {self._call_id!r}"
            )
        if tenant_id is not None and tenant_id != self._tenant_id:
            raise SinkIdentityError(
                f"event names tenant {tenant_id}, sink was built for {self._tenant_id}"
            )
        if agent_id is not None and agent_id != self._agent_id:
            raise SinkIdentityError(
                f"event names agent {agent_id}, sink was built for {self._agent_id}"
            )

    async def _ensure_call_row(self, connection: AsyncConnection) -> UUID:
        """This call's `calls.id`, minting the row in `in_progress` if it is not there yet.

        **IT EXISTS BECAUSE THE ORDER OF EVENTS IS NOT OURS TO CHOOSE.** Pipecat runs each
        handler as its own task, so a first turn can reach the sink before the
        pipeline-started event that opened the call — and `transcript_turns.call_id` is a
        foreign key, so a race would surface as an IntegrityError mid-call. Every write path
        therefore passes through here, and the one that is NOT a lifecycle event opens the
        call rather than failing on its absence.

        The memo is what keeps that from costing a round trip per turn. It is deliberately
        NOT used by `on_call_event`: a status must always be written.
        """
        if self._call_row_id is not None:
            return self._call_row_id
        return await self._upsert_call(connection, status="in_progress")

    async def _upsert_call(
        self,
        connection: AsyncConnection,
        *,
        status: CallStatus,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> UUID:
        """Write the call row and answer its id. Status only ever moves forward.

        A status the forward-only clause REFUSES returns no row, which is not an error: a
        terminal call receiving a late `in_progress` is exactly what that clause is for, and
        the id is then read back — the same fallback `_upsert_call_row` uses.
        """
        row = (
            await connection.execute(
                text(_UPSERT_CALL_SQL),
                {
                    "id": uuid7(),
                    "tid": self._tenant_id,
                    "aid": self._agent_id,
                    "ecid": self._engine_call_id,
                    "dir": self._direction,
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
                await connection.execute(
                    text("SELECT id FROM calls WHERE engine_call_id = :ecid"),
                    {"ecid": self._engine_call_id},
                )
            ).first()
            if row is None:  # pragma: no cover - only on a concurrent delete
                raise RuntimeError("call row vanished during upsert")
        self._call_row_id = UUID(str(row[0]))
        return self._call_row_id


def _duration_s(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    """Our own wall clock across the session, or `None`.

    ⚠ **THIS IS NOT THE BILLABLE DURATION AND MUST NEVER BE USED AS ONE.** §1.2 gives the
    connected minute to the carrier, and `CarrierFactsMissingError`'s remediation names
    substituting our own clock as the thing not to do. It is written to `calls.duration_s`
    because that column is what a screen shows a client about their own call; the meter
    reads `CarrierCdr.connected_seconds` and never this.
    """
    if started_at is None or ended_at is None:
        return None
    return max(0, round((ended_at - started_at).total_seconds()))


def _meta_json(row: UsageRow) -> str:
    """`usage_events.meta`, as JSON text for the CAST in the statement.

    Built by hand rather than with `json.dumps(dict(row.meta))` plus a total, because the
    one field that is NOT in `UsageRow.meta` is the leg name — and a ledger row whose
    `unit_type` is `llm_ktok_in` needs to say which of §1.3's five legs produced it without
    a reader having to know the mapping.
    """
    return json.dumps({"leg": row.leg.value, "total_inr": str(row.total_inr), **dict(row.meta)})


__all__ = ["DatabaseEventSink", "Settlement", "SinkIdentityError"]
