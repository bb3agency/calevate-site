"""The two account-wide writes to the lead details agents capture, behind the Lead details
screen's buttons and Pip's `lead_fields_keep_draft` / `lead_fields_reset` (D-821, D-893).

Each is the service write plus the business-type apply that rebuilds what the scripts ask
for from the next call (D-722); the route writes its own audit row, Pip's framework the
tool's. A module of its own because `admin.business_type` already imports `lead_fields`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.business_type import queue_apply as queue_business_type_apply
from apps.api.agents import lead_fields as service
from apps.api.core.errors import ProblemError


async def keep_draft(
    session: AsyncSession, *, tenant_id: UUID, keep: list[str]
) -> service.Reviewed:
    """Keep the drafted fields named in `keep` (empty discards the draft), once."""
    reviewed = await service.review_draft(session, tenant_id=tenant_id, keep=keep)
    if reviewed.written:
        await queue_business_type_apply(session, tenant_id=tenant_id)
    return reviewed


async def replacement_fields(
    session: AsyncSession, *, tenant_id: UUID, business_type: str | None
) -> list[ExtractionField]:
    """The standard set for the type, or — for a custom business — what its owner kept of
    the draft. An unreviewed draft is not something to replace with (D-821)."""
    vertical = business_type or await service.vertical_of(session, tenant_id=tenant_id)
    if service.has_standard_set(vertical):
        return service.standard_fields(vertical)
    draft = await service.read_draft(session, tenant_id=tenant_id)
    if draft is None or draft.status != "done" or not draft.reviewed or not draft.fields:
        raise ProblemError.business_rule(
            "lead_fields_nothing_to_replace_with",
            (
                "This business has no standard set of lead details, and none have been "
                "drafted from its details and kept yet."
            ),
            remediation="Draft the details and keep them first, or edit each agent's details "
            "directly.",
        )
    return draft.fields


@dataclass(frozen=True, slots=True)
class Replaced:
    fields: list[ExtractionField]
    written: list[service.AgentWrite]


async def replace_with_standard(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_ids: list[UUID] | None,
    business_type: str | None = None,
) -> Replaced:
    """Start the named agents (every agent when None) again from the standard set."""
    fields = await replacement_fields(session, tenant_id=tenant_id, business_type=business_type)
    written = await service.replace_business_fields(session, fields=fields, agent_ids=agent_ids)
    await queue_business_type_apply(session, tenant_id=tenant_id)
    return Replaced(fields=fields, written=written)


__all__ = ["Replaced", "keep_draft", "replace_with_standard", "replacement_fields"]
