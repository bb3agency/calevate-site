"""The lead details a business captures: the fixed core, its business fields, and the one
AI draft a custom business gets (founder decision 15, 10 Oct 2026).

Three sources can fill an agent's business fields, and every one ends as an ordinary
`extraction_schemas` version written by `extraction_routes.write_schema`, so history and
"leads render by the version they were captured under" hold for all of them:

* **A known business type's standard set** (`scripts/seed.VERTICAL_TEMPLATES`), at account
  creation, at agent creation, or when an operator moves the account to another type and
  chooses to replace the fields (`replace_business_fields`; never as a side effect of the
  type change itself).
* **The AI draft**, for a custom business only: drafted ONCE by a worker
  (`apps/workers/lead_fields_draft.py`) from the business's own details, kept on
  `lead_field_drafts`, and written onto every agent that has no business fields yet. It is
  never redrafted; `UNIQUE(tenant_id)` makes a second draft unrepresentable.
* **The client's own edits**, through the per-agent editor, at any time.

The core is never stored (`calevate_shared.lead_fields`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import business_only
from scripts.seed import BUSINESS_TYPE_LABELS, CUSTOM_EXTRACTION_FIELDS, VERTICAL_TEMPLATES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

#: The ARQ job that drafts the fields (`apps/workers/lead_fields_draft.JOB_NAME`).
DRAFT_JOB: Final = "draft_lead_fields"

CUSTOM: Final = "custom"


def business_type_label(vertical: str | None) -> str:
    return BUSINESS_TYPE_LABELS.get(vertical or CUSTOM, BUSINESS_TYPE_LABELS[CUSTOM])


def has_standard_set(vertical: str | None) -> bool:
    """A known type with its own standard fields. Anything else is drafted by AI."""
    return vertical is not None and vertical in VERTICAL_TEMPLATES


def standard_fields(vertical: str | None) -> list[ExtractionField]:
    raw = VERTICAL_TEMPLATES.get(vertical or CUSTOM, CUSTOM_EXTRACTION_FIELDS)
    return [ExtractionField.model_validate(f) for f in raw]


# ------------------------------------------------------------------------ the draft row


@dataclass(frozen=True, slots=True)
class Draft:
    status: str
    fields: list[ExtractionField]
    requested_at: datetime
    completed_at: datetime | None
    error_code: str | None


_DRAFT_SQL: Final = (
    "SELECT status, fields, requested_at, completed_at, error_code FROM lead_field_drafts "
    "WHERE tenant_id = :tid"
)


async def read_draft(session: AsyncSession, *, tenant_id: UUID) -> Draft | None:
    row = (await session.execute(text(_DRAFT_SQL), {"tid": tenant_id})).first()
    if row is None:
        return None
    return Draft(
        status=str(row[0]),
        fields=business_only(row[1] or []),
        requested_at=row[2],
        completed_at=row[3],
        error_code=row[4],
    )


async def vertical_of(session: AsyncSession, *, tenant_id: UUID) -> str | None:
    row = (
        await session.execute(
            text("SELECT vertical_template FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).first()
    return None if row is None or row[0] is None else str(row[0])


async def starting_business_fields(
    session: AsyncSession, *, tenant_id: UUID, vertical: str | None
) -> list[ExtractionField]:
    """What a NEW agent of this business starts with: its type's standard set, or — for a
    custom business whose draft is done — the drafted set. Never a redraft."""
    if has_standard_set(vertical):
        return standard_fields(vertical)
    draft = await read_draft(session, tenant_id=tenant_id)
    if draft is not None and draft.status == "done":
        return draft.fields
    return standard_fields(CUSTOM)


async def request_draft(
    session: AsyncSession, *, tenant_id: UUID, requested_by: UUID | None
) -> Draft:
    """Queue the one AI draft for a custom business, in the caller's transaction.

    Idempotent while a draft is queued or running (the same row is returned). A finished
    draft is never redrafted; a failed one produced nothing and is queued again.
    """
    vertical = await vertical_of(session, tenant_id=tenant_id)
    if has_standard_set(vertical):
        raise ProblemError.business_rule(
            "lead_fields_draft_not_custom",
            (
                f"This business is set up as {business_type_label(vertical)}, which has its "
                "own standard lead details. Drafting is for businesses set up as "
                "'Something else'."
            ),
        )
    existing = await read_draft(session, tenant_id=tenant_id)
    if existing is not None and existing.status in ("queued", "running"):
        return existing
    if existing is not None and existing.status == "done":
        raise ProblemError.conflict(
            "lead_fields_already_drafted",
            (
                "The lead details for this business were already drafted once. They are "
                "yours to change on this screen; they are never drafted again."
            ),
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO lead_field_drafts (id, tenant_id, status, requested_by, "
                "requested_at, created_at, updated_at) VALUES (:id, :tid, "
                "'queued', :by, now(), now(), now()) "
                "ON CONFLICT (tenant_id) DO UPDATE SET status = 'queued', error_code = NULL, "
                "requested_by = EXCLUDED.requested_by, requested_at = now(), "
                "completed_at = NULL, updated_at = now() "
                "WHERE lead_field_drafts.status = 'failed' "
                "RETURNING status, requested_at"
            ),
            {"id": uuid7(), "tid": tenant_id, "by": requested_by},
        )
    ).first()
    if row is None:
        # Another request moved the row first; answer with what is there now.
        current = await read_draft(session, tenant_id=tenant_id)
        assert current is not None
        return current
    await enqueue_outbox(session, job=DRAFT_JOB, payload={"tenant_id": str(tenant_id)})
    return Draft(
        status="queued", fields=[], requested_at=row[1], completed_at=None, error_code=None
    )


async def maybe_request_draft(
    session: AsyncSession, *, tenant_id: UUID, requested_by: UUID | None
) -> bool:
    """Queue the draft the first time a custom business says what it sells.

    Called after a business-profile save. Does nothing for a known type, for a business
    that already has a draft row in any state, or before any service is on file — a draft
    made from a name alone would be a guess. Returns whether one was queued.
    """
    if has_standard_set(await vertical_of(session, tenant_id=tenant_id)):
        return False
    if await read_draft(session, tenant_id=tenant_id) is not None:
        return False
    services = (
        await session.execute(
            text(
                "SELECT jsonb_array_length(services) FROM business_profiles WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    if not services:
        return False
    await request_draft(session, tenant_id=tenant_id, requested_by=requested_by)
    return True


# ------------------------------------------------------------- writing onto the agents


@dataclass(frozen=True, slots=True)
class AgentWrite:
    agent_id: UUID
    version: int
    changed: bool


#: Agents one business runs, read at most this many at a time: a handful in practice, and a
#: ceiling against a pathological roster rather than a product limit.
MAX_AGENTS: Final = 50

_AGENTS_SQL: Final = (
    "SELECT a.id, es.fields FROM agents a "
    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
    "WHERE a.deleted_at IS NULL ORDER BY a.created_at, a.id LIMIT :limit"
)


async def replace_business_fields(
    session: AsyncSession,
    *,
    fields: list[ExtractionField],
    agent_ids: list[UUID] | None = None,
    only_empty: bool = False,
) -> list[AgentWrite]:
    """Write `fields` as the business fields of this tenant's agents (RLS scopes them).

    `agent_ids=None` means every agent that is not deleted. `only_empty` skips an agent
    that already has business fields of its own — how a finished draft lands without
    overwriting anything a client already chose. Every write is a new schema version;
    earlier versions and the values captured under them are untouched.
    """
    validate_fields(fields)
    rows = (await session.execute(text(_AGENTS_SQL), {"limit": MAX_AGENTS})).all()
    wanted = None if agent_ids is None else set(agent_ids)
    if wanted is not None:
        unknown = wanted - {UUID(str(r[0])) for r in rows}
        if unknown:
            raise ProblemError.not_found("Agent")
    written: list[AgentWrite] = []
    for row in rows:
        agent_id = UUID(str(row[0]))
        if wanted is not None and agent_id not in wanted:
            continue
        if only_empty and business_only(row[1] or []):
            continue
        result = await write_schema(session, agent_id=agent_id, fields=fields)
        written.append(
            AgentWrite(agent_id=agent_id, version=result.version, changed=result.changed)
        )
    return written


async def agents_with_fields(session: AsyncSession) -> list[dict[str, Any]]:
    """Every agent that is not deleted, with its current business fields and version."""
    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.direction, a.status, es.version, es.fields "
                "FROM agents a LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE a.deleted_at IS NULL ORDER BY a.created_at, a.id LIMIT :limit"
            ),
            {"limit": MAX_AGENTS},
        )
    ).all()
    return [
        {
            "id": UUID(str(r[0])),
            "name": str(r[1]),
            "direction": str(r[2]),
            "status": str(r[3]),
            "version": int(r[4]) if r[4] is not None else 0,
            "fields": business_only(r[5] or []),
        }
        for r in rows
    ]


__all__ = [
    "CUSTOM",
    "DRAFT_JOB",
    "MAX_AGENTS",
    "AgentWrite",
    "Draft",
    "agents_with_fields",
    "business_type_label",
    "has_standard_set",
    "maybe_request_draft",
    "read_draft",
    "replace_business_fields",
    "request_draft",
    "standard_fields",
    "starting_business_fields",
    "vertical_of",
]
