"""The two account-wide writes to what campaigns and lines note, behind the Lead details
screen's buttons and Pip's `lead_fields_keep_draft` / `lead_fields_reset` (D-821, D-893,
D-1029).

Both end in `lead_fields.apply_to_jobs`: the set is written onto the campaigns and lines the
owner ticked, each under a compare-and-set on the list the screen showed. The route writes
its own audit row, Pip's framework the tool's, and the caller puts the changed jobs that hold
calls live again once the transaction has committed (`campaigns/notes_live`).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lead_fields as service
from apps.api.core.errors import ProblemError


@dataclass(frozen=True, slots=True)
class Kept:
    kept: list[ExtractionField]
    written: list[service.JobWrite]


async def keep_draft(
    session: AsyncSession, *, tenant_id: UUID, keep: list[str], jobs: list[service.JobRef]
) -> Kept:
    """Keep the drafted fields named in `keep` (empty discards the draft), once. What is kept
    becomes the starting set and is written onto `jobs`; a discard writes nothing."""
    reviewed = await service.review_draft(session, tenant_id=tenant_id, keep=keep)
    written = (
        await service.apply_to_jobs(session, fields=reviewed.kept, jobs=jobs)
        if reviewed.kept
        else []
    )
    return Kept(kept=reviewed.kept, written=written)


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
            remediation="Draft the details and keep them first, or edit each campaign's or "
            "line's details directly.",
        )
    return draft.fields


@dataclass(frozen=True, slots=True)
class Replaced:
    fields: list[ExtractionField]
    written: list[service.JobWrite]


async def replace_with_standard(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    jobs: list[service.JobRef],
    business_type: str | None = None,
) -> Replaced:
    """Start the named campaigns and lines again from the standard set."""
    fields = await replacement_fields(session, tenant_id=tenant_id, business_type=business_type)
    written = await service.apply_to_jobs(session, fields=fields, jobs=jobs)
    return Replaced(fields=fields, written=written)


__all__ = ["Kept", "Replaced", "keep_draft", "replace_with_standard", "replacement_fields"]
