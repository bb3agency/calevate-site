"""How many calls one client may have at once (founder decision F7, 12 Oct 2026).

An operator sets it per client on the admin client page; `organizations.call_lines` NULL is
Calevate's default: 2 for a paying client, 1 on a free trial.

Where it is enforced depends on where the client's calls run:

* A paying client has its own ThinnestAI customer workspace (D-693), and ThinnestAI caps it
  there: `allottedCallLines` on the customer (`engine/thinnest_customers.
  set_customer_call_lines`). The value is sent when the workspace is provisioned and whenever
  an operator changes it (job `sync_engine_call_lines`, through the outbox so it shares the
  saving transaction's fate), read back by the same call, and the daily workspace sweep
  repairs a value changed in the vendor's console. The read-back is recorded
  (`record_engine_call_lines`), and a client's request for more lines is closed THEN, not when
  the operator saves: until the platform holds the raise, the client still has the old cap
  and is told it is being applied. This is the quota-increase shape (a request is approved
  when the quota is applied, not when it is decided).
* A free-trial account has no workspace of its own; its agents live in our developer
  workspace, which one `allottedCallLines` cannot split between clients. So its cap is ours:
  the dial gate (`compliance/service.check_dispatch`) counts this client's calls in progress
  and refuses one more with `call_lines_busy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.trial_access import restricting_trial, trial_line_horizon
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.call_line_requests import LineRequest, close_on_raise
from apps.api.tenancy.engine_workspace import engine_has_workspaces, read_workspace_state
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


#: Where the number in force is held:
#: `ours`: our dial gate (a free trial) or nowhere yet (no workspace of its own), so it holds
#: the moment it is saved; `applied`: the client's own workspace read it back; `applying`:
#: sent to the workspace and not yet read back.
EngineState = Literal["ours", "applied", "applying"]


@dataclass(frozen=True, slots=True)
class CallLines:
    #: The number in force.
    lines: int
    #: The operator's choice, or None for Calevate's default.
    chosen: int | None
    on_trial: bool
    source: Literal["organization", "platform"]
    engine_state: EngineState = "ours"
    #: What the client's own workspace last read back, and when; None before a sync.
    applied: int | None = None
    applied_at: datetime | None = None


async def _engine_holds_it(session: AsyncSession, *, tenant_id: UUID, on_trial: bool) -> bool:
    """Whether the client's own workspace, rather than our dial gate, enforces its cap."""
    if on_trial or not engine_has_workspaces():
        return False
    return (await read_workspace_state(session, tenant_id)).active


async def read_call_lines(session: AsyncSession, *, tenant_id: UUID) -> CallLines:
    """The client's calls at once, in its tenant session. An organization that does not
    exist is a 404, never Calevate's default."""
    row = (
        await session.execute(
            text(
                "SELECT call_lines, call_lines_applied, call_lines_applied_at "
                "FROM organizations WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    chosen, applied, applied_at = row[0], row[1], row[2]
    on_trial = await restricting_trial(session, tenant_id=tenant_id) is not None
    source: Literal["organization", "platform"] = "organization"
    if chosen is not None:
        lines = int(chosen)
    else:
        lines = TRIAL_CALL_LINES_DEFAULT if on_trial else PAID_CALL_LINES_DEFAULT
        source = "platform"
    state: EngineState = "ours"
    if await _engine_holds_it(session, tenant_id=tenant_id, on_trial=on_trial):
        state = "applied" if applied == lines else "applying"
    return CallLines(
        lines,
        None if chosen is None else int(chosen),
        on_trial,
        source,
        engine_state=state,
        applied=None if applied is None else int(applied),
        applied_at=applied_at,
    )


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
    session: AsyncSession, *, tenant_id: UUID, lines: int | None, admin_id: UUID | None = None
) -> tuple[CallLines, bool, LineRequest | None]:
    """Set the client's calls at once (None: Calevate's default) and owe its workspace the
    new value when it moved. A raise above what the client had when it asked closes its
    open request: in this transaction when the cap is ours, or once the client's own
    workspace reads it back (`record_engine_call_lines`). Answers the state, whether it
    moved, and the request it closed."""
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
    closed = None
    if after.lines != before.lines:
        await queue_call_lines_sync(session, tenant_id=tenant_id)
        if after.engine_state == "ours":
            closed = await close_on_raise(
                session, tenant_id=tenant_id, lines_in_force=after.lines, admin_id=admin_id
            )
    log.info(
        "call_lines_set",
        extra={
            "tenant_id": str(tenant_id),
            "lines": after.lines,
            "moved": moved,
            "engine_state": after.engine_state,
        },
    )
    return after, moved, closed


async def record_engine_call_lines(
    session: AsyncSession, *, tenant_id: UUID, held: int
) -> LineRequest | None:
    """The client's own workspace read back `held`: record it, and close the client's open
    request when that is a raise above what it had when it asked. Tenant session."""
    await session.execute(
        text(
            "UPDATE organizations SET call_lines_applied = :held, call_lines_applied_at = now() "
            "WHERE id = :tid"
        ),
        {"held": held, "tid": tenant_id},
    )
    closed = await close_on_raise(session, tenant_id=tenant_id, lines_in_force=held, admin_id=None)
    if closed is not None:
        await write_audit(
            session,
            action="call_lines_request.done",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="call_line_request",
            object_id=str(closed.id),
            summary={"lines_granted": closed.lines_granted},
        )
    return closed


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
    "EngineState",
    "call_lines_blocker",
    "call_lines_busy_reason",
    "calls_in_progress",
    "queue_call_lines_sync",
    "read_call_lines",
    "record_engine_call_lines",
    "refuse_call_lines_out_of_range",
    "set_call_lines",
]
