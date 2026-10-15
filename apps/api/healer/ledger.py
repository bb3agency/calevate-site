"""`heal_actions`: one append-only row for everything the healer did, skipped or was told.

Written in the caller's transaction, so an action and its row commit together. The detail
is authored by us and still goes through `redact_mapping` and a cap, because it routinely
carries an exception's class name and, through a careless call site, could carry more.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
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


@dataclass(frozen=True, slots=True)
class ActionRow:
    id: UUID
    at: datetime
    incident_id: UUID | None
    playbook: str
    step: str
    outcome: Outcome
    attempt: int
    tenant_id: UUID | None
    agent_id: UUID | None
    alarm_code: str | None
    detail: str | None
    actor_type: ActorType


_ACTION_COLUMNS = (
    "id, at, incident_id, playbook, step, outcome, attempt, tenant_id, agent_id, alarm_code, "
    "detail, actor_type"
)


def _action(r: Any) -> ActionRow:
    return ActionRow(
        id=r[0],
        at=r[1],
        incident_id=r[2],
        playbook=str(r[3]),
        step=str(r[4]),
        outcome=r[5],
        attempt=int(r[6]),
        tenant_id=r[7],
        agent_id=r[8],
        alarm_code=r[9],
        detail=r[10],
        actor_type=r[11],
    )


async def list_actions(
    session: AsyncSession, *, incident_id: UUID | None, limit: int
) -> list[ActionRow]:
    """The ledger newest first, optionally one incident's steps only."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_ACTION_COLUMNS} FROM heal_actions WHERE (CAST(:iid AS uuid) IS NULL "
                "OR incident_id = :iid) ORDER BY at DESC LIMIT :limit"
            ),
            {"iid": incident_id, "limit": limit},
        )
    ).all()
    return [_action(r) for r in rows]


async def recent_steps(
    session: AsyncSession, incident_ids: list[UUID], *, per_incident: int
) -> dict[UUID, list[ActionRow]]:
    """The newest `per_incident` steps of each incident, newest first, in one statement."""
    if not incident_ids:
        return {}
    rows = (
        await session.execute(
            text(
                f"SELECT {_ACTION_COLUMNS} FROM (SELECT *, row_number() OVER (PARTITION BY "
                "incident_id ORDER BY at DESC) AS n FROM heal_actions WHERE incident_id = "
                "ANY(CAST(:ids AS uuid[]))) ranked WHERE n <= :per ORDER BY at DESC"
            ),
            {"ids": [str(i) for i in incident_ids], "per": per_incident},
        )
    ).all()
    found: dict[UUID, list[ActionRow]] = {}
    for row in rows:
        action = _action(row)
        assert action.incident_id is not None
        found.setdefault(action.incident_id, []).append(action)
    return found


#: The steps whose detail is the healer's own reading of an incident it cannot fix: the
#: evidence it escalated with, and each re-check after.
FINDING_STEPS: Final = ("escalate", "verify")


async def latest_findings(session: AsyncSession, incident_ids: list[UUID]) -> dict[UUID, str]:
    """The newest finding the healer wrote on each incident, where it wrote one."""
    if not incident_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (incident_id) incident_id, detail FROM heal_actions "
                "WHERE incident_id = ANY(CAST(:ids AS uuid[])) AND actor_type = 'healer' "
                "AND step = ANY(CAST(:steps AS text[])) AND detail IS NOT NULL "
                "ORDER BY incident_id, at DESC"
            ),
            {"ids": [str(i) for i in incident_ids], "steps": list(FINDING_STEPS)},
        )
    ).all()
    return {row[0]: str(row[1]) for row in rows}


__all__ = [
    "FINDING_STEPS",
    "ActionRow",
    "ActorType",
    "Outcome",
    "Step",
    "latest_findings",
    "list_actions",
    "recent_steps",
    "record",
]
