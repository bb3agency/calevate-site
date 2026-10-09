"""Protecting a client's line while their agent is broken, and giving it back (D-701).

INBOUND: callers are handed to the client's own fallback phone where the voice platform
can do it (`agents/service.ForwardsLine`; on ThinnestAI a hand-over the agent makes, whose
first-turn reliability is OPERATIONS gate T-26), otherwise the line answers with the
neutral can't-take-your-call sentence the empty-wallet path already uses. ThinnestAI
documents no number-level forward, so there is no way to divert a call before an agent
speaks.

THE CALL-BACK LIST IS THE INCIDENT'S OWN LIST OF CALLS, NOT `scheduled_callbacks`. That
table is dialled automatically by the agent at the booked time, and these callers never
asked to be rung back; an unrequested automated call is exactly what the dial gate exists
to refuse. The client sees how many callers reached the broken line and opens those calls
from the incident to ring them back themselves.

OUTBOUND: the agent's running campaigns are paused and marked with the incident
(`campaigns.paused_by_heal_id`), so the restore resumes only its own pauses; on restore,
contacts whose last attempt during the incident was a broken call get the attempt back,
the same refund `_refuse_contact` gives a dial blocked on our side.

Every function here runs inside the caller's `tenant_session` (RLS is the scoping).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import (
    INBOUND_SILENCE_HEALER,
    HealerHold,
    apply_healer_silence,
    lift_healer_silence,
)
from apps.api.db.base import uuid7
from apps.api.engine import get_engine
from apps.api.healer.health import SHORT_CALL_S

ClientIncidentKind = Literal["agent_unwell", "line_protected", "platform_outage"]


async def fallback_phone(session: AsyncSession) -> str | None:
    """The tenant's own fallback phone, or None."""
    row = (await session.execute(text("SELECT phone_e164 FROM heal_fallback_phones"))).first()
    return str(row[0]) if row else None


async def forward_target(session: AsyncSession, *, agent_id: UUID) -> str | None:
    """The phone to forward this agent's callers to, if the healer is forwarding them."""
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM heal_client_incidents WHERE agent_id = :aid AND state = 'open' "
                "AND protection = 'forwarded' LIMIT 1"
            ),
            {"aid": agent_id},
        )
    ).first()
    return await fallback_phone(session) if row else None


async def healer_holds_line(session: AsyncSession, *, agent_id: UUID) -> bool:
    row = (
        await session.execute(
            text("SELECT inbound_silence_reason FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).first()
    return row is not None and row[0] == INBOUND_SILENCE_HEALER


async def client_incident(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    incident_id: UUID,
    agent_id: UUID | None,
    kind: ClientIncidentKind,
) -> UUID:
    """The client's row for this incident (one per incident, tenant and agent)."""
    row = (
        await session.execute(
            text(
                "INSERT INTO heal_client_incidents (id, tenant_id, incident_id, agent_id, kind, "
                "protection, state, opened_at, created_at, updated_at) VALUES (:id, :tid, :iid, "
                ":aid, :kind, 'none', 'open', now(), now(), now()) ON CONFLICT (incident_id, "
                "tenant_id, agent_id) DO UPDATE SET kind = CASE WHEN heal_client_incidents.kind "
                "= 'agent_unwell' THEN EXCLUDED.kind ELSE heal_client_incidents.kind END, "
                "updated_at = now() RETURNING id"
            ),
            {"id": uuid7(), "tid": tenant_id, "iid": incident_id, "aid": agent_id, "kind": kind},
        )
    ).one()
    return UUID(str(row[0]))


@dataclass(frozen=True, slots=True)
class Held:
    hold: HealerHold
    campaigns_paused: int


async def protect_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    incident_id: UUID,
    agent_id: UUID,
    kind: ClientIncidentKind = "line_protected",
    forward: bool = True,
) -> Held:
    """Hold one agent's line and pause its running campaigns. Vendor errors propagate."""
    client_row = await client_incident(
        session, tenant_id=tenant_id, incident_id=incident_id, agent_id=agent_id, kind=kind
    )
    phone = await fallback_phone(session) if forward else None
    hold = await apply_healer_silence(
        session, get_engine(), tenant_id=tenant_id, agent_id=agent_id, forward_to=phone
    )
    paused = (
        await session.execute(
            text(
                "UPDATE campaigns SET status = 'paused', paused_by_heal_id = :iid, "
                "updated_at = now() WHERE agent_id = :aid AND status = 'running' RETURNING id"
            ),
            {"iid": incident_id, "aid": agent_id},
        )
    ).all()
    protection = hold if hold in ("paused", "forwarded") else "none"
    await session.execute(
        text(
            "UPDATE heal_client_incidents SET protection = CASE WHEN CAST(:p AS text) = 'none' "
            "THEN protection "
            "ELSE CAST(:p AS text) END, protected_at = COALESCE(protected_at, now()), "
            "campaigns_paused = "
            "campaigns_paused + CAST(:n AS integer), must_act = must_act OR "
            "(CAST(:p AS text) = 'none' AND CAST(:n AS integer) = 0), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": client_row, "p": protection, "n": len(paused)},
    )
    return Held(hold=hold, campaigns_paused=len(paused))


@dataclass(frozen=True, slots=True)
class Restored:
    lifted: bool
    campaigns_resumed: int
    requeued: int
    missed_calls: int


async def restore_agent(
    session: AsyncSession, *, tenant_id: UUID, incident_id: UUID, agent_id: UUID
) -> Restored:
    """Give the line back, resume only this incident's campaign pauses, re-queue the
    attempts that failed while the agent was broken, and close the client's row."""
    opened = (
        await session.execute(
            text(
                "SELECT opened_at FROM heal_client_incidents WHERE incident_id = :iid "
                "AND agent_id = :aid"
            ),
            {"iid": incident_id, "aid": agent_id},
        )
    ).first()
    since: datetime | None = opened[0] if opened else None
    lifted = await lift_healer_silence(session, tenant_id=tenant_id, agent_id=agent_id)
    resumed = (
        await session.execute(
            text(
                "UPDATE campaigns SET status = CASE WHEN status = 'paused' THEN 'running' "
                "ELSE status END, paused_by_heal_id = NULL, updated_at = now() "
                "WHERE paused_by_heal_id = :iid AND agent_id = :aid RETURNING status"
            ),
            {"iid": incident_id, "aid": agent_id},
        )
    ).all()
    requeued = 0
    missed = 0
    if since is not None:
        requeued = len(
            (
                await session.execute(
                    text(
                        "UPDATE campaign_contacts cc SET status = 'pending', attempts = "
                        "GREATEST(cc.attempts - 1, 0), next_attempt_at = now(), updated_at = "
                        "now() FROM calls c, campaigns k WHERE cc.last_call_id = c.id AND "
                        "cc.campaign_id = k.id AND k.agent_id = :aid AND c.created_at >= "
                        ":since AND cc.status IN ('pending', 'no_answer', 'failed') AND "
                        "(c.status = 'failed' OR (c.status = 'completed' AND "
                        "coalesce(c.duration_s, 0) < :short)) RETURNING cc.id"
                    ),
                    {"aid": agent_id, "since": since, "short": SHORT_CALL_S},
                )
            ).all()
        )
        missed = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM calls WHERE agent_id = :aid AND direction = "
                        "'inbound' AND created_at >= :since AND NOT trial_call AND (status = "
                        "'failed' OR (status = 'completed' AND coalesce(duration_s, 0) < :short))"
                    ),
                    {"aid": agent_id, "since": since, "short": SHORT_CALL_S},
                )
            ).scalar_one()
        )
    await session.execute(
        text(
            "UPDATE heal_client_incidents SET state = 'resolved', resolved_at = now(), "
            "requeued = requeued + :rq, missed_calls = :missed, updated_at = now() "
            "WHERE incident_id = :iid AND agent_id = :aid AND state = 'open'"
        ),
        {"iid": incident_id, "aid": agent_id, "rq": requeued, "missed": missed},
    )
    return Restored(
        lifted=lifted, campaigns_resumed=len(resumed), requeued=requeued, missed_calls=missed
    )


async def resolve_client_rows(session: AsyncSession, *, incident_id: UUID) -> int:
    """Close the client's rows for an incident that needed no protection."""
    result = await session.execute(
        text(
            "UPDATE heal_client_incidents SET state = 'resolved', resolved_at = now(), "
            "updated_at = now() WHERE incident_id = :iid AND state = 'open'"
        ),
        {"iid": incident_id},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def live_answering_agents(session: AsyncSession) -> list[UUID]:
    """The tenant's live agents that answer calls, for a platform-wide hold."""
    rows = (
        await session.execute(
            text(
                "SELECT id FROM agents WHERE status = 'live' AND engine_agent_ref IS NOT NULL "
                "AND direction IN ('inbound', 'both') AND deleted_at IS NULL "
                "AND archived_at IS NULL ORDER BY id"
            )
        )
    ).all()
    return [UUID(str(r[0])) for r in rows]


__all__ = [
    "ClientIncidentKind",
    "Held",
    "Restored",
    "client_incident",
    "fallback_phone",
    "forward_target",
    "healer_holds_line",
    "live_answering_agents",
    "protect_agent",
    "resolve_client_rows",
    "restore_agent",
]
