"""The public status page's data (status.calevate.tech, D-701).

Built from `heal_incidents` rows an operator or the outage playbook marked `public`, and
nothing else: no tenant, no agent, no alarm code, no count of affected clients. A
component's state is the worst open public incident filed against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ComponentState = Literal["operational", "degraded", "outage"]

#: The components shown, in order, with their public names.
COMPONENTS: Final[tuple[tuple[str, str], ...]] = (
    ("calls", "Phone calls"),
    ("numbers", "Phone numbers"),
    ("dashboard", "Dashboard"),
    ("assistant", "Assistant"),
)
#: How far back the incident history reaches.
HISTORY_DAYS: Final = 90
HISTORY_LIMIT: Final = 50
#: Playbooks whose open incidents mean a component is down rather than degraded.
OUTAGE_PLAYBOOKS: Final = frozenset({"engine_outage"})


@dataclass(frozen=True, slots=True)
class PublicIncident:
    id: str
    title: str
    component: str | None
    state: Literal["ongoing", "resolved"]
    started_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class Component:
    key: str
    name: str
    state: ComponentState


@dataclass(frozen=True, slots=True)
class StatusPage:
    components: tuple[Component, ...]
    incidents: tuple[PublicIncident, ...]
    updated_at: datetime


async def status_page(session: AsyncSession) -> StatusPage:
    rows = (
        await session.execute(
            text(
                "SELECT id, public_title, component, playbook, opened_at, resolved_at "
                "FROM heal_incidents WHERE public AND (resolved_at IS NULL OR opened_at >= "
                "now() - make_interval(days => :days)) ORDER BY (resolved_at IS NULL) DESC, "
                "opened_at DESC LIMIT :limit"
            ),
            {"days": HISTORY_DAYS, "limit": HISTORY_LIMIT},
        )
    ).all()
    worst: dict[str, ComponentState] = {}
    for row in rows:
        if row[5] is not None or row[2] is None:
            continue
        state: ComponentState = "outage" if row[3] in OUTAGE_PLAYBOOKS else "degraded"
        if worst.get(row[2]) != "outage":
            worst[row[2]] = state
    now = (await session.execute(text("SELECT now()"))).scalar_one()
    return StatusPage(
        components=tuple(
            Component(key=key, name=name, state=worst.get(key, "operational"))
            for key, name in COMPONENTS
        ),
        incidents=tuple(
            PublicIncident(
                id=str(row[0]),
                title=str(row[1]),
                component=row[2],
                state="ongoing" if row[5] is None else "resolved",
                started_at=row[4],
                resolved_at=row[5],
            )
            for row in rows
        ),
        updated_at=now,
    )


__all__ = [
    "COMPONENTS",
    "HISTORY_DAYS",
    "Component",
    "ComponentState",
    "PublicIncident",
    "StatusPage",
    "status_page",
]
