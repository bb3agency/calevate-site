"""A client's own names for the core lead details, as every screen and export reads them.

One reader, so the leads list, a lead, a call, an export, a team alert and Pip all show the
same name (`calevate_shared.lead_fields.core_fields`). A module of its own, depending on
nothing in the app, because the readers sit in CRM, agents and alerts alike. The extraction
spec never asks it: the call reader always reads the platform's names and instructions.
"""

from __future__ import annotations

from uuid import UUID

from calevate_shared.lead_fields import clean_core_labels
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def core_labels(session: AsyncSession, *, tenant_id: UUID | None = None) -> dict[str, str]:
    """The names for `tenant_id`, or for the tenant the session is scoped to when omitted;
    `{}` (the platform's names) when there is no such account."""
    if tenant_id is None:
        statement = (
            "SELECT core_field_labels FROM organizations "
            "WHERE id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        )
        params: dict[str, object] = {}
    else:
        statement = "SELECT core_field_labels FROM organizations WHERE id = :tid"
        params = {"tid": tenant_id}
    raw = (await session.execute(text(statement), params)).scalar()
    return clean_core_labels(raw if isinstance(raw, dict) else None)


__all__ = ["core_labels"]
