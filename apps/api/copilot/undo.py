"""Taking back what the assistant did (D-694).

ONE FUNCTION, BOTH REALMS' DOORS. `POST /v1/copilot/actions/{id}/undo` and its admin twin
both come here. The sequence is the confirm door's, mirrored:

    lock the row → it is yours → it is `done` and inside its window → the tool still has an
    inverse → you may still do what the tool does → the inverse runs (it CASes the record
    itself) → the row becomes `undone` → an audit row says so

all in the caller's ONE transaction, so an inverse that refuses or fails leaves both the
record and the log exactly as they were, and two clicks on one Undo serialise on the row
lock and the second is told it was already undone.

The admin realm has no immediate actions yet (`admin_actions.AdminActionTool` refuses
one), so its door answers every row with "nothing to undo" — the door exists so the next
admin action that is reversible has somewhere to land without a second mechanism.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.copilot import action_log, write_tools
from apps.api.copilot.actions import (
    UndoRecord,
    UndoRefusedError,
    actor_for,
    assistant_closed_to,
    may_act,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.schemas import CopilotUndoOut
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError


def _cannot(code: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(
        kind="conflict",
        code=code,
        title="That could not be undone",
        detail=detail,
        remediation=remediation,
    )


async def undo_client_action(
    session: AsyncSession, action_id: UUID, *, principal: Principal, ip: str | None
) -> CopilotUndoOut:
    actor = actor_for(principal)
    if actor is None:  # pragma: no cover - the route's dependency guarantees a tenant
        raise ProblemError.not_found("Action")
    if assistant_closed_to(actor) is not None:
        raise ProblemError.forbidden()
    row = await action_log.read_for_update(session, realm="client", action_id=action_id)
    # ANOTHER ACCOUNT'S ID IS RLS'S ZERO ROWS, and another colleague's row gets the same
    # answer: whose action it was is part of what the row says.
    if row is None or row.actor_id != actor.user_id:
        raise ProblemError.not_found("Action")
    if row.status == "undone":
        raise _cannot(
            "copilot_action_already_undone",
            "This was already undone.",
            "Nothing else needs doing.",
        )
    if not row.can_undo(datetime.now(UTC)):
        raise _cannot(
            "copilot_action_not_undoable",
            "This can no longer be undone from here.",
            "Change it yourself on the screen where it lives.",
        )
    tool = write_tools.tool_named(row.tool)
    if tool is None or tool.undo is None or row.prior_state is None or row.result_state is None:
        raise _cannot(
            "copilot_action_not_undoable",
            "This kind of change cannot be undone from here.",
            "Change it yourself on the screen where it lives.",
        )
    if not await may_act(session, actor, tool.permission):
        raise ProblemError(
            kind="permission",
            code="forbidden",
            title="Forbidden",
            detail="You no longer have permission to change this.",
            remediation="Ask an owner or manager on this account to change it back.",
        )
    try:
        sentence = await tool.undo.invert(
            session,
            actor,
            UndoRecord(
                object_id=row.object_id or "",
                # Ids are never redacted (`action_log.redact_args`), and an inverse reads only
                # ids from here — the values it restores come from `prior_state`.
                args=row.args_redacted or {},
                prior_state=row.prior_state,
                result_state=row.result_state,
            ),
        )
    except UndoRefusedError as refused:
        raise _cannot(
            "copilot_action_changed_since",
            f"{refused.reason[:1].upper()}{refused.reason[1:]}.",
            "Check the record and change it yourself if you still want to.",
        ) from refused
    if not await action_log.mark_undone(
        session, realm="client", action_id=action_id, by=actor.user_id
    ):  # pragma: no cover - the row lock above makes the CAS uncontended
        raise _cannot(
            "copilot_action_already_undone", "This was already undone.", "Nothing else needs doing."
        )
    await write_audit(
        session,
        action="copilot.action_undone",
        actor=principal,
        tenant_id=actor.tenant_id,
        object_type=tool.object_type,
        object_id=row.object_id,
        ip=ip,
        summary={"via": "copilot", "tool": tool.name, "action_id": str(action_id)},
    )
    return CopilotUndoOut(
        action_id=str(action_id), tool=tool.name, detail=strip_invisible(sentence)
    )


async def undo_admin_action(
    session: AsyncSession, action_id: UUID, *, principal: Principal
) -> CopilotUndoOut:
    """The admin door. No admin action is immediate yet, so every row answers the same."""
    row = await action_log.read_for_update(session, realm="admin", action_id=action_id)
    if row is None or row.actor_id != principal.user_id:
        raise ProblemError.not_found("Action")
    raise _cannot(
        "copilot_action_not_undoable",
        "This kind of change cannot be undone from here.",
        "Reverse it from the screen where it lives.",
    )


__all__ = ["undo_admin_action", "undo_client_action"]
