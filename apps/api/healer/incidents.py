"""`heal_incidents`: one row per problem the healer is working on, opened once per key.

`uq_heal_incidents_open_key` is a partial unique index on `dedupe_key WHERE resolved_at IS
NULL`, so `open_incident` is the alert-episode pattern (`core/alert_records.py`): an
INSERT that either opens the incident or finds the open one, and `xmax = 0` says which.
Every state change is a compare-and-swap on the state it read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.base import uuid7

Scope = Literal["agent", "tenant", "platform"]
State = Literal["open", "mitigated", "escalated", "resolved"]
Component = Literal["calls", "dashboard", "numbers", "assistant"]

_OPEN = text(
    "INSERT INTO heal_incidents (id, dedupe_key, playbook, trigger_code, scope, tenant_id, "
    "agent_id, state, attempts, next_attempt_at, component, public, public_title, opened_at, "
    "created_at, updated_at) VALUES (:id, :key, :playbook, :code, :scope, :tenant, :agent, "
    "'open', 0, now(), :component, :public, :title, now(), now(), now()) "
    "ON CONFLICT (dedupe_key) WHERE resolved_at IS NULL DO UPDATE SET updated_at = now() "
    "RETURNING id, (xmax = 0) AS opened"
)

_COLUMNS = (
    "id, dedupe_key, playbook, trigger_code, scope, tenant_id, agent_id, state, attempts, "
    "next_attempt_at, component, public, public_title, last_outcome, opened_at, "
    "mitigated_at, escalated_at, resolved_at"
)


@dataclass(frozen=True, slots=True)
class Incident:
    id: UUID
    dedupe_key: str
    playbook: str
    trigger_code: str
    scope: str
    tenant_id: UUID | None
    agent_id: UUID | None
    state: str
    attempts: int
    next_attempt_at: datetime | None
    component: str | None
    public: bool
    public_title: str | None
    last_outcome: str | None
    opened_at: datetime
    mitigated_at: datetime | None
    escalated_at: datetime | None
    resolved_at: datetime | None


def _incident(row: Any) -> Incident:
    return Incident(
        id=row[0],
        dedupe_key=str(row[1]),
        playbook=str(row[2]),
        trigger_code=str(row[3]),
        scope=str(row[4]),
        tenant_id=row[5],
        agent_id=row[6],
        state=str(row[7]),
        attempts=int(row[8]),
        next_attempt_at=row[9],
        component=row[10],
        public=bool(row[11]),
        public_title=row[12],
        last_outcome=row[13],
        opened_at=row[14],
        mitigated_at=row[15],
        escalated_at=row[16],
        resolved_at=row[17],
    )


def dedupe_key(playbook: str, *parts: object) -> str:
    """`playbook:part:part`. Parts are ids and codes, never personal data."""
    return ":".join([playbook, *(str(p) for p in parts if p is not None)])


async def open_incident(
    session: AsyncSession,
    *,
    key: str,
    playbook: str,
    trigger_code: str,
    scope: Scope,
    tenant_id: UUID | None = None,
    agent_id: UUID | None = None,
    component: Component | None = None,
    public_title: str | None = None,
) -> tuple[UUID, bool]:
    """The open incident for `key`, and whether this call opened it."""
    row = (
        await session.execute(
            _OPEN,
            {
                "id": uuid7(),
                "key": key,
                "playbook": playbook,
                "code": trigger_code,
                "scope": scope,
                "tenant": tenant_id,
                "agent": agent_id,
                "component": component,
                "public": public_title is not None,
                "title": public_title,
            },
        )
    ).one()
    return row[0], bool(row[1])


async def read_incident(session: AsyncSession, incident_id: UUID) -> Incident | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM heal_incidents WHERE id = :id"), {"id": incident_id}
        )
    ).first()
    return _incident(row) if row else None


async def open_for(session: AsyncSession, key: str) -> Incident | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM heal_incidents "
                "WHERE dedupe_key = :k AND resolved_at IS NULL"
            ),
            {"k": key},
        )
    ).first()
    return _incident(row) if row else None


#: How long a claimed incident is leased to the tick that claimed it. A tick that dies
#: mid-step leaves the incident due again after this, never stuck.
CLAIM_LEASE_S = 300


async def claim_due(session: AsyncSession, *, limit: int) -> list[Incident]:
    """Unresolved incidents whose next step is due, oldest first, leased for
    `CLAIM_LEASE_S` in one statement so two workers cannot advance the same one. The step
    then runs on its own sessions; `advance` CASes on state and attempts, not on the lease."""
    rows = (
        await session.execute(
            text(
                "UPDATE heal_incidents SET next_attempt_at = now() + make_interval(secs => "
                ":lease) WHERE id IN (SELECT id FROM heal_incidents WHERE resolved_at IS NULL "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= now()) "
                "ORDER BY next_attempt_at NULLS FIRST, opened_at LIMIT :limit "
                f"FOR UPDATE SKIP LOCKED) RETURNING {_COLUMNS}"
            ),
            {"limit": limit, "lease": CLAIM_LEASE_S},
        )
    ).all()
    return [_incident(r) for r in rows]


async def advance(
    session: AsyncSession,
    incident: Incident,
    *,
    state: State,
    next_in_s: int | None,
    outcome: str | None = None,
    attempted: bool = False,
) -> bool:
    """Move an incident on, as a CAS on the state and attempt count it was read with."""
    result = await session.execute(
        text(
            "UPDATE heal_incidents SET state = CAST(:state AS text), "
            "last_outcome = COALESCE(CAST(:outcome AS text), last_outcome), "
            "attempts = attempts + :inc, "
            "next_attempt_at = CASE WHEN CAST(:next_s AS integer) IS NULL THEN NULL "
            "ELSE now() + make_interval(secs => CAST(:next_s AS integer)) END, "
            "mitigated_at = CASE WHEN CAST(:state AS text) = 'mitigated' "
            "AND mitigated_at IS NULL THEN now() ELSE mitigated_at END, "
            "escalated_at = CASE WHEN CAST(:state AS text) = 'escalated' "
            "AND escalated_at IS NULL THEN now() ELSE escalated_at END, "
            "resolved_at = CASE WHEN CAST(:state AS text) = 'resolved' THEN now() ELSE NULL END, "
            "updated_at = now() WHERE id = :id AND state = :was AND attempts = :attempts "
            "AND resolved_at IS NULL"
        ),
        {
            "id": incident.id,
            "state": state,
            "outcome": outcome,
            "inc": 1 if attempted else 0,
            "next_s": next_in_s,
            "was": incident.state,
            "attempts": incident.attempts,
        },
    )
    return bool(getattr(result, "rowcount", 0))


async def set_public(
    session: AsyncSession, incident_id: UUID, *, title: str | None, component: Component | None
) -> bool:
    """Show an incident on the status page under `title`, or take it off (`title=None`)."""
    result = await session.execute(
        text(
            "UPDATE heal_incidents SET public = CAST(:title AS text) IS NOT NULL, "
            "public_title = CAST(:title AS text), component = COALESCE(:component, component), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": incident_id, "title": title, "component": component},
    )
    return bool(getattr(result, "rowcount", 0))


async def list_incidents(
    session: AsyncSession, *, days: int, limit: int, open_only: bool = False
) -> list[Incident]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM heal_incidents WHERE (opened_at >= now() - "
                "make_interval(days => :days) OR resolved_at IS NULL) "
                "AND (NOT :open_only OR resolved_at IS NULL) "
                "ORDER BY (resolved_at IS NULL) DESC, opened_at DESC LIMIT :limit"
            ),
            {"days": days, "limit": limit, "open_only": open_only},
        )
    ).all()
    return [_incident(r) for r in rows]


__all__ = [
    "CLAIM_LEASE_S",
    "Component",
    "Incident",
    "Scope",
    "State",
    "advance",
    "claim_due",
    "dedupe_key",
    "list_incidents",
    "open_for",
    "open_incident",
    "read_incident",
    "set_public",
]
