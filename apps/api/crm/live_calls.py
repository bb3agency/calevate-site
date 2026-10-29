"""Calls that are still running, as the call log shows them (D-886).

An outbound call has a row from the moment it is dialled (`agents/service.dispatch_call`), in
`queued`, and that row does not move until the call is over: ThinnestAI reports nothing
between placing a call and `call.completed` (`engine/dial_lines.ENGINE_LINE_HORIZON`). So
"ringing" and "on the call" are the engine's to say, and `engine_live_status` asks it, once
per call per read, only while the row is live and young enough to still be a call. A terminal
row, an inbound row, a row whose dial was never confirmed and a row past the horizon are
answered from the row and never cost a vendor read.

Inbound calls have no row while they ring. One is written mid-call only when the agent runs
an in-call action (`worker/engine_actions.call_locator`, `in_progress`); otherwise the first
row is the one the pipeline writes when the call ends. The pre-answer caller lookup
(`worker/engine_lookups`) is not used to write one: whether its `callId` is the id the
completed call carries is unverified (OPERATIONS F-5), and a mismatch would leave a second,
never-finished row beside the real one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.events import CallStatus
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine import get_engine
from apps.api.engine.dial_lines import LIVE_LINE_HORIZON

log = get_logger(__name__)

#: The statuses of a call that has not ended.
LIVE_STATUSES: Final[frozenset[str]] = frozenset({"queued", "ringing", "in_progress"})

#: How many calls one live read answers. ThinnestAI's pay-as-you-go account runs 20 calls at
#: once (VENDOR-STATED 23 Oct 2026, replies §28), so a log never has more live rows than this.
MAX_LIVE_IDS: Final = 20

#: Engine reads in flight at once for one live read.
_ENGINE_READS_AT_ONCE: Final = 4

LiveState = Literal["live", "unreported"]


def live_state(status: str, created_at: datetime, *, now: datetime) -> LiveState | None:
    """`live` for a call still running, `unreported` for a row that never heard its end
    within the longest call an agent may run plus a margin (it ended; the details are late),
    None for a call that has ended."""
    if status not in LIVE_STATUSES:
        return None
    return "live" if now - created_at < LIVE_LINE_HORIZON else "unreported"


#: `live_state` as a SQL expression over `calls c`, for ordering the log with live calls
#: first. The statuses and the horizon are bound (`live_state_params`) rather than spliced,
#: so the text is a literal `scripts.check_raw_sql` can trace.
LIVE_STATE_SQL: Final = (
    "CASE WHEN c.status::text <> ALL(CAST(:live_statuses AS text[])) THEN NULL "
    "WHEN c.created_at > now() - make_interval(secs => CAST(:live_horizon_s AS double precision)) "
    "THEN 'live' ELSE 'unreported' END"
)

#: `LIVE_STATE_SQL = 'live'` as a plain predicate, which a planner can answer from the
#: `(tenant_id, created_at)` index; the CASE form it equals cannot be.
RUNNING_SQL: Final = (
    "(c.status::text = ANY(CAST(:live_statuses AS text[])) "
    "AND c.created_at > now() - make_interval(secs => CAST(:live_horizon_s AS double precision)))"
)


def live_state_params() -> dict[str, object]:
    return {
        "live_statuses": sorted(LIVE_STATUSES),
        "live_horizon_s": LIVE_LINE_HORIZON.total_seconds(),
    }


class EngineLiveStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: CallStatus
    started_at: datetime | None = None
    duration_s: int | None = None
    terminal: bool = False


async def engine_live_status(
    *, call_id: UUID, handle: Any, status: str, placed_at: datetime, now: datetime | None = None
) -> EngineLiveStatus | None:
    """The engine's own status for a call our row still holds as live, or None when the
    engine is not to be asked (ended, too old, dial unconfirmed) or could not answer. A
    failed read is logged by id; the row's own status still answers for the screen."""
    young = (now or datetime.now(UTC)) - placed_at < LIVE_LINE_HORIZON
    if (
        status not in LIVE_STATUSES
        or not young
        or not isinstance(handle, str)
        or handle.startswith(UNCONFIRMED_ENGINE_CALL_PREFIX)
    ):
        return None
    try:
        snapshot = await get_engine().get_execution(handle)
    except Exception as exc:  # the row still answers; see the docstring
        code = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        log.warning("call_live_status_unread", extra={"call_id": str(call_id), "code": code})
        return None
    return EngineLiveStatus(
        status=snapshot.status,
        started_at=snapshot.started_at,
        duration_s=snapshot.duration_s,
        terminal=snapshot.terminal,
    )


class CallLiveOut(BaseModel):
    """Where one call the log shows as live stands now."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: CallStatus
    #: Where `status` came from: our row, or the engine's live read while the row is silent.
    status_source: Literal["call", "engine"] = "call"
    #: `live`, `unreported` (past the horizon with no end heard), or null once it has ended.
    live_state: LiveState | None = None
    #: When the person picked up, from the row or the engine; null until then.
    started_at: datetime | None = None


async def read_live_calls(session: AsyncSession, ids: list[UUID]) -> list[CallLiveOut]:
    """The calls among `ids` this tenant has (RLS scopes the read), each with its live
    status. Ids the tenant does not have are left out rather than refused, so a stale list
    on screen costs nothing."""
    if not ids:
        return []
    rows = (
        await session.execute(
            text(
                "SELECT id, status, direction, engine_call_id, created_at, started_at "
                "FROM calls WHERE id = ANY(:ids) ORDER BY id"
            ),
            {"ids": ids[:MAX_LIVE_IDS]},
        )
    ).all()
    now = datetime.now(UTC)
    gate = asyncio.Semaphore(_ENGINE_READS_AT_ONCE)

    async def one(row: Any) -> CallLiveOut:
        call_id, status, direction, handle, created_at, started_at = row
        out = CallLiveOut(
            id=call_id,
            status=status,
            live_state=live_state(status, created_at, now=now),
            started_at=started_at,
        )
        # Only an outbound row is silent while it runs; an inbound row exists mid-call only
        # once it is `in_progress`, which is already the truth.
        if direction != "outbound" or out.live_state != "live":
            return out
        async with gate:
            engine = await engine_live_status(
                call_id=call_id, handle=handle, status=status, placed_at=created_at, now=now
            )
        if engine is None:
            return out
        return out.model_copy(
            update={
                "status": engine.status,
                "status_source": "engine",
                "started_at": engine.started_at or started_at,
                # The engine has the end before our row does; the log re-reads the row.
                "live_state": None if engine.terminal else "live",
            }
        )

    return list(await asyncio.gather(*(one(row) for row in rows)))


__all__ = [
    "LIVE_STATE_SQL",
    "LIVE_STATUSES",
    "MAX_LIVE_IDS",
    "CallLiveOut",
    "EngineLiveStatus",
    "engine_live_status",
    "live_state",
    "live_state_params",
    "read_live_calls",
]
