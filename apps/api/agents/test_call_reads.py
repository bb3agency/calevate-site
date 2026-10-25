"""Reading back the test calls an account placed from its dashboard card (D-885).

Two reads, one shape (`TestCallOut`):

* `recent_test_calls` — today's test calls (IST day), newest first, from our rows only. The
  card lists them so they are still there after a reload or a trip to another page.
* `read_test_call` — one test call by our id, for the card's live status while it runs.

WHY THE ENGINE IS ASKED WHILE A CALL RUNS. ThinnestAI reports nothing between the dial and
the end (`call.completed` is its first event, `engine/dial_lines.ENGINE_LINE_HORIZON`), so
our row says `queued` until the call is over and cannot tell ringing from talking. While the
row is live and young enough to still be a call, the one read asks the engine for its own
status (`get_execution`, our normalised `ExecutionSnapshot`) and answers with that. Once the
row is terminal the engine is not asked again, and a row past the live horizon is reported
as stored rather than polled at the vendor forever.

A failed engine read is not an error for the screen: the row's own status still answers,
and the failure is logged by id for an operator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.events import CallStatus
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX
from apps.api.compliance.trial_access import ist_day_start
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm.outcomes import normalise as normalise_outcome
from apps.api.crm.schemas import CallOutcome
from apps.api.engine import get_engine
from apps.api.engine.dial_lines import LIVE_LINE_HORIZON

log = get_logger(__name__)

#: How many of today's test calls the card lists.
RECENT_TEST_CALLS: Final = 3

_LIVE: Final[frozenset[str]] = frozenset({"queued", "ringing", "in_progress"})


class TestCallOut(BaseModel):
    """One test call as the dashboard card shows it. No number of the person rung: the card
    names the agent, the time and the number of ours it rang from, and the call's own page
    has the rest."""

    __test__ = False  # pytest: a schema, not a test class
    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    status: CallStatus
    #: Where `status` came from: our row, or the engine's live read while the row is silent.
    status_source: Literal["call", "engine"] = "call"
    placed_at: datetime
    #: When the person picked up; null until then and for a call nobody answered.
    started_at: datetime | None = None
    duration_s: int | None = None
    outcome_tag: CallOutcome | None = None
    business_outcome_label: str | None = None
    #: The one-line English summary, stored redacted (`calls.headline`); null until written.
    headline: str | None = None
    #: The number it rang from (`calls.from_e164` of an outbound call: ours, or the
    #: account's own line), E.164; null until known.
    caller_number: str | None = None


_COLUMNS: Final = (
    "SELECT c.id, c.agent_id, a.name, c.status, c.created_at, c.started_at, c.duration_s, "
    "c.outcome_tag, c.business_outcome_label, c.headline, c.engine_call_id, c.from_e164 "
    "FROM calls c JOIN agents a ON a.id = c.agent_id "
    "WHERE c.tenant_id = :tid AND (c.trial_call OR c.paid_test_call) "
)


def _out(row: Any) -> TestCallOut:
    return TestCallOut(
        id=row[0],
        agent_id=row[1],
        agent_name=row[2],
        status=row[3],
        placed_at=row[4],
        started_at=row[5],
        duration_s=row[6],
        outcome_tag=normalise_outcome(row[7]),
        business_outcome_label=row[8],
        headline=row[9],
        caller_number=row[11],
    )


async def recent_test_calls(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> list[TestCallOut]:
    """Today's test calls, newest first, at most `RECENT_TEST_CALLS`. Ordered by when they
    were placed, not `started_at`, which a call still ringing does not have."""
    since = ist_day_start(at or datetime.now(UTC))
    rows = (
        await session.execute(
            text(
                f"{_COLUMNS}AND c.created_at >= :since "
                "ORDER BY c.created_at DESC, c.id DESC LIMIT :limit"
            ),
            {"tid": tenant_id, "since": since, "limit": RECENT_TEST_CALLS},
        )
    ).all()
    return [_out(row) for row in rows]


async def read_test_call(session: AsyncSession, *, tenant_id: UUID, call_id: UUID) -> TestCallOut:
    """One test call of this account, with the engine's live status while it runs."""
    row = (
        await session.execute(
            text(f"{_COLUMNS}AND c.id = :cid"), {"tid": tenant_id, "cid": call_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Test call")
    out = _out(row)
    handle = row[10]
    young = datetime.now(UTC) - out.placed_at < LIVE_LINE_HORIZON
    if (
        out.status not in _LIVE
        or not young
        or not isinstance(handle, str)
        or handle.startswith(UNCONFIRMED_ENGINE_CALL_PREFIX)
    ):
        return out
    try:
        snapshot = await get_engine().get_execution(handle)
    except Exception as exc:  # the row still answers; see the module docstring
        code = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        log.warning("test_call_live_status_unread", extra={"call_id": str(call_id), "code": code})
        return out
    return out.model_copy(
        update={
            "status": snapshot.status,
            "status_source": "engine",
            "started_at": snapshot.started_at or out.started_at,
            "duration_s": snapshot.duration_s if snapshot.terminal else out.duration_s,
        }
    )


__all__ = ["RECENT_TEST_CALLS", "TestCallOut", "read_test_call", "recent_test_calls"]
