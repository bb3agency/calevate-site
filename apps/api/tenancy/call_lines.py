"""How many calls one client may have at once (founder decision F7, 12 Oct 2026).

An operator sets it per client on the admin client page; `organizations.call_lines` NULL is
Calevate's default: 2 for a paying client, 1 on a free trial.

Where it is enforced depends on where the client's calls run:

* A paying client has its own ThinnestAI customer workspace (D-693), and ThinnestAI caps it
  there: `allottedCallLines` on the customer (`engine/thinnest_customers.
  set_customer_call_lines`). The value is sent when the workspace is provisioned and whenever
  an operator changes it (job `sync_engine_call_lines`, through the outbox so it shares the
  saving transaction's fate), read back by the same call, and the daily workspace sweep
  repairs a value changed in the vendor's console.
* A free-trial account has no workspace of its own; its agents live in our developer
  workspace, which one `allottedCallLines` cannot split between clients. So its cap is ours:
  the dial gate (`compliance/service.check_dispatch`) counts this client's calls in progress
  and refuses one more with `call_lines_busy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.trial_access import restricting_trial, trial_line_horizon
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import engine_has_workspaces
from apps.api.tenancy.models import CALL_LINES_MAX, CALL_LINES_MIN

log = get_logger(__name__)

#: Calevate's defaults (F7): a paying client two calls at once, a free trial one.
PAID_CALL_LINES_DEFAULT: Final = 2
TRIAL_CALL_LINES_DEFAULT: Final = 1

#: The outbox job that sends a client's value to its own workspace.
CALL_LINES_SYNC_JOB: Final = "sync_engine_call_lines"

CALL_LINES_BUSY_RULE: Final = "call_lines_busy"

#: A call row in one of these holds a line until it ends (`agents/service._hold_trial_line`).
_LIVE_STATUSES: Final = ["queued", "ringing", "in_progress"]


@dataclass(frozen=True, slots=True)
class CallLines:
    #: The number in force.
    lines: int
    #: The operator's choice, or None for Calevate's default.
    chosen: int | None
    on_trial: bool
    source: Literal["organization", "platform"]


async def read_call_lines(session: AsyncSession, *, tenant_id: UUID) -> CallLines:
    """The client's calls at once, in its tenant session."""
    chosen = (
        await session.execute(
            text("SELECT call_lines FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    on_trial = await restricting_trial(session, tenant_id=tenant_id) is not None
    if chosen is not None:
        return CallLines(int(chosen), int(chosen), on_trial, "organization")
    default = TRIAL_CALL_LINES_DEFAULT if on_trial else PAID_CALL_LINES_DEFAULT
    return CallLines(default, None, on_trial, "platform")


def refuse_call_lines_out_of_range(lines: int | None) -> None:
    if lines is None or CALL_LINES_MIN <= lines <= CALL_LINES_MAX:
        return
    raise ProblemError(
        kind="validation",
        code="call_lines_out_of_range",
        title="Calls at once is out of range",
        detail=f"A client can have {CALL_LINES_MIN} to {CALL_LINES_MAX} calls at once.",
        remediation=(
            f"Choose {CALL_LINES_MIN}-{CALL_LINES_MAX}, or clear it to use the default "
            f"({PAID_CALL_LINES_DEFAULT} for a paying client, {TRIAL_CALL_LINES_DEFAULT} on a "
            "free trial)."
        ),
        fields=[
            {
                "field": "call_lines",
                "rule": "out_of_range",
                "message": f"Must be {CALL_LINES_MIN}-{CALL_LINES_MAX}, or null for the default.",
            }
        ],
    )


async def queue_call_lines_sync(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Owe the client's own workspace its value, in the caller's transaction. False on an
    engine without client workspaces, where there is nothing to send."""
    if not engine_has_workspaces():
        return False
    await enqueue_outbox(session, job=CALL_LINES_SYNC_JOB, payload={"tenant_id": str(tenant_id)})
    return True


async def set_call_lines(
    session: AsyncSession, *, tenant_id: UUID, lines: int | None
) -> tuple[CallLines, bool]:
    """Set the client's calls at once (None: Calevate's default) and owe its workspace the
    new value when it moved. Answers the state and whether it moved."""
    refuse_call_lines_out_of_range(lines)
    row = (
        await session.execute(
            text(
                "SELECT call_lines FROM organizations WHERE id = :tid AND deleted_at IS NULL "
                "FOR UPDATE"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    before = await read_call_lines(session, tenant_id=tenant_id)
    moved = row[0] != lines
    if moved:
        await session.execute(
            text("UPDATE organizations SET call_lines = :n, updated_at = now() WHERE id = :tid"),
            {"n": lines, "tid": tenant_id},
        )
    after = await read_call_lines(session, tenant_id=tenant_id)
    if after.lines != before.lines:
        await queue_call_lines_sync(session, tenant_id=tenant_id)
    log.info(
        "call_lines_set",
        extra={"tenant_id": str(tenant_id), "lines": after.lines, "moved": moved},
    )
    return after, moved


async def calls_in_progress(session: AsyncSession, *, tenant_id: UUID) -> int:
    """This client's calls holding a line now. A row whose end was never reported stops
    counting at `trial_line_horizon()` (the longest test call plus a margin), so a lost
    delivery cannot hold a line for good."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM calls WHERE tenant_id = :tid "
                    "AND status = ANY(:statuses) "
                    "AND created_at > now() - make_interval(secs => :horizon)"
                ),
                {
                    "tid": tenant_id,
                    "statuses": _LIVE_STATUSES,
                    "horizon": trial_line_horizon().total_seconds(),
                },
            )
        ).scalar_one()
    )


def call_lines_busy_reason(lines: int) -> str:
    calls = "call" if lines == 1 else "calls"
    return (
        f"This account can have {lines} {calls} at once, and that many are in progress. "
        "Try again when a call ends."
    )


async def call_lines_blocker(session: AsyncSession, *, tenant_id: UUID) -> tuple[str, str] | None:
    """`(rule, reason)` when a free-trial account already has as many calls in progress as it
    may hold, else None. A paying client's cap is held by its own workspace, not here."""
    lines = await read_call_lines(session, tenant_id=tenant_id)
    if not lines.on_trial:
        return None
    in_progress = await calls_in_progress(session, tenant_id=tenant_id)
    if in_progress < lines.lines:
        return None
    log.info(
        "dial_refused_call_lines_busy",
        extra={"tenant_id": str(tenant_id), "lines": lines.lines, "in_progress": in_progress},
    )
    return CALL_LINES_BUSY_RULE, call_lines_busy_reason(lines.lines)


__all__ = [
    "CALL_LINES_BUSY_RULE",
    "CALL_LINES_SYNC_JOB",
    "PAID_CALL_LINES_DEFAULT",
    "TRIAL_CALL_LINES_DEFAULT",
    "CallLines",
    "call_lines_blocker",
    "call_lines_busy_reason",
    "calls_in_progress",
    "queue_call_lines_sync",
    "read_call_lines",
    "refuse_call_lines_out_of_range",
    "set_call_lines",
]
