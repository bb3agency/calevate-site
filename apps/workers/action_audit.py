"""Append the audit row for one in-call/after-call ACTION invocation.

The execution layer (`apps/api/actions/execution.py`) enqueues this so the latency-critical
tool path writes no DB row of its own (hard rule 3), exactly as the opt-out tool defers its
suppression to `record_in_call_optout`. Here, off the caller's audio path, the row is
written to the append-only, tamper-evident `audit_log` (hard rule 4).

HARD RULE 6: the payload carries ids, the kind/provider and a short outcome code — never a
number, a message body or an external response. There is nothing here to redact because
nothing sensitive was queued.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.compliance.audit import write_audit
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

ACTION_AUDIT_JOB = "record_action_invocation"

# The audit action name a client-facing "action history" screen and any drift sweep filter
# on. Named once, here with the enqueuer's constant, so the two cannot drift.
ACTION_AUDIT_ACTION = "action_tool.invoked"


async def record_action_invocation(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Write one audit row for an action invocation. Idempotency is not required — an
    over-count of a benign audit row is harmless, and the queue collapses obvious retries —
    so this stays a plain append rather than carrying a dedupe key."""
    tenant_id = UUID(str(payload["tenant_id"]))
    tool_id = str(payload["tool_id"])
    async with tenant_session(tenant_id) as session:
        await write_audit(
            session,
            action=ACTION_AUDIT_ACTION,
            actor=None,  # engine-initiated → actor_type "system"
            tenant_id=tenant_id,
            object_type="action_tool",
            object_id=tool_id,
            summary={
                "agent_id": str(payload.get("agent_id") or ""),
                "kind": str(payload.get("kind") or ""),
                "provider": str(payload.get("provider") or ""),
                "status": str(payload.get("status") or ""),
                "source": str(payload.get("source") or ""),
            },
        )
    log.info(
        "action_invocation_audited",
        extra={"tenant_id": str(tenant_id), "tool_id": tool_id, "status": payload.get("status")},
    )
    return str(payload.get("status") or "recorded")


__all__ = ["ACTION_AUDIT_ACTION", "ACTION_AUDIT_JOB", "record_action_invocation"]
