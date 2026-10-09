"""`heal_actions`: one append-only row for everything the healer did, skipped or was told.

Written in the caller's transaction, so an action and its row commit together. The detail
is authored by us and still goes through `redact_mapping` and a cap, because it routinely
carries an exception's class name and, through a careless call site, could carry more.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger, redact_mapping
from apps.api.db.base import uuid7
from apps.api.healer.models import MAX_ACTION_DETAIL

log = get_logger(__name__)

Step = Literal[
    "schedule",
    "act",
    "verify",
    "undo",
    "escalate",
    "protect",
    "restore",
    "notify",
    "propose",
    "decide",
]
Outcome = Literal["ok", "failed", "skipped", "refused"]
ActorType = Literal["healer", "admin", "user"]

_INSERT = text(
    "INSERT INTO heal_actions (id, at, incident_id, playbook, step, outcome, attempt, "
    "tenant_id, agent_id, alarm_code, alert_id, detail, actor_type, actor_id) VALUES (:id, "
    "now(), :incident, :playbook, :step, :outcome, :attempt, :tenant, :agent, :code, :alert, "
    ":detail, :actor_type, :actor)"
)


def _bounded(detail: str | None) -> str | None:
    if not detail:
        return None
    safe = str(redact_mapping({"detail": detail}).get("detail", ""))
    return safe[:MAX_ACTION_DETAIL] or None


async def record(
    session: AsyncSession,
    *,
    playbook: str,
    step: Step,
    outcome: Outcome,
    incident_id: UUID | None = None,
    attempt: int = 0,
    tenant_id: UUID | None = None,
    agent_id: UUID | None = None,
    alarm_code: str | None = None,
    alert_id: UUID | None = None,
    detail: str | None = None,
    actor_type: ActorType = "healer",
    actor_id: UUID | None = None,
) -> UUID:
    action_id = uuid7()
    await session.execute(
        _INSERT,
        {
            "id": action_id,
            "incident": incident_id,
            "playbook": playbook,
            "step": step,
            "outcome": outcome,
            "attempt": attempt,
            "tenant": tenant_id,
            "agent": agent_id,
            "code": alarm_code,
            "alert": alert_id,
            "detail": _bounded(detail),
            "actor_type": actor_type,
            "actor": actor_id,
        },
    )
    log.info(
        "healer_action",
        extra={
            "playbook": playbook,
            "step": step,
            "outcome": outcome,
            "incident_id": str(incident_id) if incident_id else None,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "agent_id": str(agent_id) if agent_id else None,
        },
    )
    return action_id


__all__ = ["ActorType", "Outcome", "Step", "record"]
