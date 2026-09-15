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
            await self._ensure_call_row(
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
        event, and `COALESCE(text_redacted, text)` is how every reader in this repository
        asks for the default view (`apps/workers/pipeline.py::_AGENT_TRANSCRIPT_SQL`,
        hard rule 5). A row written with `text_redacted` NULL therefore serves RAW TEXT to
        the dashboard for as long as it stays that way — which is why it is not written that
        way here and left for a later pass to fix.
        """
        self._check_identity(call_id=turn.call_id)
        # The one call. `RedactionResult.kinds` says WHAT was found and is loggable; the
        # text either side of it is not, and neither is counted or sampled anywhere below.
        redacted = redact(turn.text)
        async with self._lock, self._db.tenant_connection(self._tenant_id) as connection:
            call_row_id = await self._ensure_call_row(connection, status="in_progress")
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
        try:
            rows = meter.metered_rows(carrier=carrier, runtime=runtime)
        except LegNotMeterableError as refusal:
            await self._record_refusal(refusal, at=occurred_at)
            return Settlement(rows=0, refusal_code=refusal.code, refusal_leg=refusal.leg.value)
        return await self._write_usage(rows, at=occurred_at)

    async def _write_usage(self, rows: tuple[UsageRow, ...], *, at: datetime) -> Settlement:
        if not rows:
            # A call with nothing to meter. `meter.py` distinguishes this from a call it
            # cannot price and so does this: no rows, no refusal, nothing to record.
            return Settlement(rows=0)
        async with self._lock, self._db.tenant_connection(self._tenant_id) as connection:
            call_row_id = await self._ensure_call_row(connection, status="in_progress")
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
        logger.info(
            "call settled",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            legs=",".join(sorted({row.leg.value for row in rows})),
            rows=len(rows),
        )
        return Settlement(rows=len(rows))

    async def _record_refusal(self, refusal: LegNotMeterableError, *, at: datetime) -> None:
        async with self._lock, self._db.tenant_connection(self._tenant_id) as connection:
            call_row_id = await self._ensure_call_row(connection, status="in_progress")
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
        # `error` and not `warning`: an unmetered call is spend we absorbed and cannot bill,
        # and it is the state `admin/health.py::calls_unmetered` stops the board for.
        logger.error(
            "call leg not meterable",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            leg=refusal.leg.value,
            code=refusal.code,
        )

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

    async def _ensure_call_row(
        self,
        connection: AsyncConnection,
        *,
        status: CallStatus,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> UUID:
        """This call's `calls.id`, minting the row if it is not there yet.

        **IT IS CALLED FROM EVERY WRITE PATH AND NOT ONLY FROM `on_call_event`**, because
        the order the two arrive in is not ours to choose: Pipecat runs each handler as its
        own task, so a first turn can reach the sink before the pipeline-started event that
        opened the call. Every path therefore converges on the same upsert, and the FK from
        `transcript_turns` can never be reached with nothing on the other end.

        The memoised id is only trusted once the row is known to exist; a status that the
        forward-only clause REFUSES returns no row, which is the same "read the existing id"
        fallback `_upsert_call_row` uses and for the same reason — a terminal call receiving
        a late `in_progress` is not an error.
        """
        if self._call_row_id is not None:
            return self._call_row_id
        row = (
            await connection.execute(
                text(_UPSERT_CALL_SQL),
                {
                    "id": uuid7(),
                    "tid": self._tenant_id,
                    "aid": self._agent_id,
                    "ecid": self._call_id,
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
                    {"ecid": self._call_id},
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
