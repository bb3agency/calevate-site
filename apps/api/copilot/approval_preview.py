"""What approving a waiting action would do, read fresh, before anybody clicks (D-694).

The Approvals inbox row stores the server's one-line summary. A person deciding whether to
let a background job launch a campaign needs more than that: what changes, from what, what
it costs and whether it can be taken back — the same four things a proposal card shows.

So the preview RE-RUNS THE PLANNER on the row's pending arguments, under the person's own
session, and returns its `Plan`. That is the same call `write_tools.approve` makes before it
executes, so what the person reads is what Approve would do to the world as it is now — a
campaign whose launch blockers appeared overnight previews as refused, with them named. A
planner only reads (`actions.Plan`'s contract), so asking costs nothing and changes nothing.

The row is read through the log's one row reader, which locks it for the length of this
short request; that serialises a preview against an Approve clicked in another tab rather
than previewing a row that is being decided.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot import action_log, write_tools
from apps.api.copilot.actions import (
    WriteRefusedError,
    actor_for,
    assistant_closed_to,
    may_act,
)
from apps.api.copilot.routine_schemas import CopilotApprovalPreviewOut
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.workers.redaction import redact


def _said(sentence: str) -> str:
    """A planner's sentence as the person reads it: redacted, invisible characters gone —
    the treatment `action_log` gives the same sentences on their way into the log."""
    return strip_invisible(redact(sentence).text)


async def preview_approval(
    session: AsyncSession, action_id: UUID, *, principal: Principal
) -> CopilotApprovalPreviewOut:
    actor = actor_for(principal)
    if actor is None or assistant_closed_to(actor) is not None:
        raise ProblemError.not_found("Approval")
    row = await action_log.read_for_update(session, realm="client", action_id=action_id)
    if row is None or row.actor_id != actor.user_id:
        raise ProblemError.not_found("Approval")
    expires_at = row.created_at + action_log.APPROVAL_TTL
    tool = write_tools.tool_named(row.tool)

    def refused(title: str, why: str) -> CopilotApprovalPreviewOut:
        return CopilotApprovalPreviewOut(
            action_id=str(action_id),
            tool=row.tool,
            object_type=row.object_type,
            expires_at=expires_at,
            title=title,
            summary=row.summary or "",
            still_applies=False,
            refusal=why,
        )

    if (
        row.status != "pending_approval"
        or row.pending_args is None
        or expires_at <= datetime.now(UTC)
        or tool is None
        or tool.tier != "confirm"
    ):
        return refused("This is no longer waiting", "This has already been decided or has expired.")
    if not await may_act(session, actor, tool.permission):
        return refused(
            "You cannot approve this",
            "Your role does not allow this change. Ask an owner or manager.",
        )
    try:
        plan = await tool.plan(session, actor, row.pending_args)
    except WriteRefusedError as refusal:
        return refused("This no longer applies", _said(refusal.reason))
    return CopilotApprovalPreviewOut(
        action_id=str(action_id),
        tool=row.tool,
        object_type=row.object_type,
        expires_at=expires_at,
        title=_said(plan.title),
        summary=_said(plan.summary),
        current=None if plan.current is None else _said(plan.current),
        proposed=_said(plan.proposed),
        cost=None if plan.cost is None else _said(plan.cost),
        reversal=_said(plan.reversal),
        still_applies=True,
        refusal=None,
    )


__all__ = ["preview_approval"]
