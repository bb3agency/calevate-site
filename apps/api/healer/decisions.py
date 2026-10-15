"""What a person may do to an incident: run its next step now, or close it (D-701, D-776).

ONE implementation for both doors: the console's buttons (`healer/routes.py`) and Pip's
confirmed actions (`copilot/admin_actions.py`). Each door writes its own audit row in its
own transaction; the ledger row here says which person acted.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.healer import incidents, ledger
from apps.api.healer.incidents import Incident
from apps.api.healer.ledger import ActorType
from apps.api.healer.playbooks import PLAYBOOK_BY_KEY, may_run

#: The playbooks that may be holding a client's line or pausing campaigns while open, so
#: closing one gives them back. Every other incident closes with one UPDATE.
LINE_HOLDING: Final = frozenset({"line_protection", "agent_repair", "engine_outage"})


def retry_refusal(incident: Incident) -> str | None:
    """Why running this incident's next step now would do nothing, or None."""
    if incident.resolved_at is not None:
        return "This problem is already closed."
    playbook = PLAYBOOK_BY_KEY.get(incident.playbook)
    if playbook is None or not playbook.automatic:
        return (
            "The healer never acts on this kind of problem itself, so there is no step to "
            "run again. A person decides it."
        )
    if not may_run(playbook.key):
        return (
            f"The {playbook.title.lower()} repair is switched off in configuration "
            "(the auto-healer switch or its paused list), so it would only record that it "
            "is paused."
        )
    return None


async def retry(session: AsyncSession, incident: Incident) -> None:
    """Make the incident due on the healer's next minute, or refuse with the reason."""
    refusal = retry_refusal(incident)
    if refusal is not None:
        raise ProblemError.conflict(
            "heal_incident_not_retryable",
            refusal,
            remediation="Mark it as handled once its cause is fixed.",
        )
    await incidents.retry_now(session, incident.id)


async def resolve(
    session: AsyncSession,
    incident: Incident,
    *,
    actor_type: ActorType,
    actor_id: UUID | None,
    reason: str | None,
) -> bool:
    """Close an incident a person handled; False when it was already closed.

    A line-holding incident gives its lines back through the worker's own restore, which
    commits on its own sessions; any other incident closes in the caller's transaction, so
    it commits with whatever the caller did beside it (Pip's rate attestation)."""
    if incident.resolved_at is not None:
        return False
    if incident.playbook in LINE_HOLDING:
        from apps.workers.healer import restore_by_person

        await restore_by_person(incident, actor_type=actor_type, actor_id=actor_id)
    else:
        await incidents.close_by_person(session, incident.id)
    await ledger.record(
        session,
        playbook=incident.playbook,
        step="decide",
        outcome="ok",
        incident_id=incident.id,
        tenant_id=incident.tenant_id,
        agent_id=incident.agent_id,
        alarm_code=incident.trigger_code,
        detail="marked as handled" + (f": {reason}" if reason else ""),
        actor_type=actor_type,
        actor_id=actor_id,
    )
    return True


__all__ = ["LINE_HOLDING", "resolve", "retry", "retry_refusal"]
