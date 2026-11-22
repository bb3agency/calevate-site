"""The lead details a business captures: the fixed core, its starting set of business fields,
and the one AI draft every business gets (founder decision 15, 10 Oct 2026; every type since
5 Nov 2026).

What a call notes is its campaign's or inbound line's own list (D-1028), edited on that job's
What it notes and on the Lead details screen, one card per job (D-1029). This module holds
what those lists start from and the account-wide writes that reach several at once:

* **The business's starting set** (`starting_business_fields`): what its owner kept of the AI
  draft, else its business type's standard set (`calevate_shared/verticals.json`). A new
  campaign or line copies it (`campaigns/notes.starting_fields`). A business-type move changes
  it by changing the type; since 5 Nov 2026 a standard set is only a starting point and the
  draft's seed (founder: "make everything that matters dynamic").
* **The AI draft**, for every business: drafted ONCE by a worker
  (`apps/workers/lead_fields_draft.py`) from the business's own details, kept on
  `lead_field_drafts`, reviewed by the owner field by field (D-821). It is never redrafted;
  `UNIQUE(tenant_id)` makes a second draft unrepresentable.
* **An apply** (`apply_to_jobs`): the starting set written onto the campaigns and lines the
  owner ticked, each under a compare-and-set on the list the screen showed. The screen ticks
  the jobs nobody customised (`JobRow.untouched`); an owner's own list is changed only when
  they tick it (D-715).

The core is never stored (`calevate_shared.lead_fields`). An agent's own `extraction_schemas`
list is read by nothing that decides a call and is dropped in a later release (hard rule 8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared import verticals
from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import business_only, clean_core_labels
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.starter_plans import business_known
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox, enqueue_outbox_once
from apps.api.tenancy.core_labels import core_labels

#: The ARQ job that drafts the fields (`apps/workers/lead_fields_draft.JOB_NAME`).
DRAFT_JOB: Final = "draft_lead_fields"

CUSTOM: Final = verticals.CUSTOM


def business_type_label(vertical: str | None) -> str:
    return verticals.label_of(vertical)


def has_standard_set(vertical: str | None) -> bool:
    """A known type with its own standard fields. Anything else is drafted by AI."""
    return bool(verticals.of(vertical).fields)


def standard_fields(vertical: str | None) -> list[ExtractionField]:
    return [ExtractionField.model_validate(f) for f in verticals.of(vertical).field_dicts()]


# ------------------------------------------------------------------------ the draft row


@dataclass(frozen=True, slots=True)
class Draft:
    status: str
    fields: list[ExtractionField]
    requested_at: datetime
    completed_at: datetime | None
    error_code: str | None
    #: The owner kept or discarded what was drafted (D-821). A `done` draft that is not
    #: reviewed has reached no agent yet.
    reviewed: bool = False


#: A draft still `running` this long after its last write died with its worker (the job
#: asks the model once, `DRAFT_TIMEOUT_S` 45 s; a timed-out or killed job is not retried and
#: its claim is spent). It reads as failed, so the owner may ask again.
DRAFT_STALE_MINUTES: Final = 10

_DRAFT_SQL: Final = (
    "SELECT CASE WHEN status = 'running' AND updated_at < now() - make_interval(mins => :stale) "
    "THEN 'failed' ELSE status END, fields, requested_at, completed_at, "
    "CASE WHEN status = 'running' AND updated_at < now() - make_interval(mins => :stale) "
    "THEN 'draft_crashed' ELSE error_code END, reviewed_at "
    "FROM lead_field_drafts "
    "WHERE tenant_id = :tid"
)


async def read_draft(session: AsyncSession, *, tenant_id: UUID) -> Draft | None:
    row = (
        await session.execute(text(_DRAFT_SQL), {"tid": tenant_id, "stale": DRAFT_STALE_MINUTES})
    ).first()
    if row is None:
        return None
    return Draft(
        status=str(row[0]),
        fields=business_only(row[1] or []),
        requested_at=row[2],
        completed_at=row[3],
        error_code=row[4],
        reviewed=row[5] is not None,
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
    """The business's starting set, which a new campaign or line copies: what its owner kept of
    its draft, else its type's standard set. Never a redraft."""
    draft = await read_draft(session, tenant_id=tenant_id)
    if draft is not None and draft.status == "done" and draft.reviewed and draft.fields:
        return draft.fields
    return standard_fields(vertical)


async def has_business_fields(
    session: AsyncSession, *, tenant_id: UUID, vertical: str | None
) -> bool:
    """Does a new agent start with details about THIS kind of business, or only the core?
    False for a custom business whose owner has not kept a draft yet (D-821)."""
    if has_standard_set(vertical):
        return True
    draft = await read_draft(session, tenant_id=tenant_id)
    return draft is not None and draft.status == "done" and draft.reviewed and bool(draft.fields)


async def request_draft(
    session: AsyncSession, *, tenant_id: UUID, requested_by: UUID | None
) -> Draft:
    """Queue the one AI draft for this business, in the caller's transaction.

    Idempotent while a draft is queued or running (the same row is returned). A finished
    draft is never redrafted; a failed one produced nothing and is queued again.
    """
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
                "WHERE lead_field_drafts.status = 'failed' OR (lead_field_drafts.status = "
                "'running' AND lead_field_drafts.updated_at "
                "< now() - make_interval(mins => :stale)) "
                "RETURNING status, requested_at"
            ),
            {"id": uuid7(), "tid": tenant_id, "by": requested_by, "stale": DRAFT_STALE_MINUTES},
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
    """Queue the draft the first time a business says what it offers.

    Called after a business-profile save. Does nothing for a business that already has a
    draft row in any state, or before any service is on file — a draft made from a name
    alone would be a guess. Returns whether one was queued.
    """
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


@dataclass(frozen=True, slots=True)
class Reviewed:
    kept: list[ExtractionField]


async def review_draft(session: AsyncSession, *, tenant_id: UUID, keep: list[str]) -> Reviewed:
    """The owner's review of the finished draft (D-821): the fields whose keys are in `keep`
    become the business's starting set (`starting_business_fields`); the rest are dropped.
    `keep=[]` discards the draft. Once, under a row lock: a second review is refused, and the
    draft is never redrafted. Which campaigns and lines take the kept set is the caller's
    (`lead_fields_writes.keep_draft`, D-1029).
    """
    row = (
        await session.execute(
            text(
                "SELECT status, fields, reviewed_at FROM lead_field_drafts "
                "WHERE tenant_id = :tid FOR UPDATE"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or str(row[0]) != "done":
        raise ProblemError.business_rule(
            "lead_fields_nothing_to_review", "There is no finished draft to review."
        )
    if row[2] is not None:
        raise ProblemError.conflict(
            "lead_fields_already_reviewed",
            "This draft was already reviewed. Change the details on this screen instead.",
        )
    wanted = set(keep)
    kept = [f for f in business_only(row[1] or []) if f.key in wanted]
    await session.execute(
        text(
            "UPDATE lead_field_drafts SET reviewed_at = now(), fields = CAST(:fields AS jsonb), "
            "updated_at = now() WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id, "fields": json.dumps([f.model_dump() for f in kept])},
    )
    return Reviewed(kept=kept)


# ------------------------------------------------------- the campaigns' and lines' lists


#: Agents one business runs, read at most this many at a time: a handful in practice, and a
#: ceiling against a pathological roster rather than a product limit.
MAX_AGENTS: Final = 50
#: Campaigns, and separately lines, the Lead details screen lists: open ones only, which a
#: business keeps to a handful, so a ceiling against a pathological account.
MAX_JOBS: Final = 200

JobKind = Literal["campaign", "line"]


@dataclass(frozen=True, slots=True)
class JobRef:
    """A campaign or line an account-wide apply writes, with the digest of the list the
    screen showed for it (`campaigns/notes.digest_of`)."""

    kind: JobKind
    job_id: UUID
    digest: str


@dataclass(frozen=True, slots=True)
class JobWrite:
    kind: JobKind
    job_id: UUID
    changed: bool


@dataclass(frozen=True, slots=True)
class JobRow:
    kind: JobKind
    id: UUID
    name: str
    #: A campaign's status (`campaigns.models.CAMPAIGN_STATUSES`); `live` or `draft` for a line.
    status: str
    #: Running now: a running campaign, or a line callers hear.
    live: bool
    agent_id: UUID
    agent_name: str
    fields: list[ExtractionField]
    digest: str
    #: Nobody chose this list: it is empty, or exactly a set the platform offered (the
    #: business's starting set or any business type's standard set). An apply of a new
    #: starting set ticks these by default.
    untouched: bool


_JOBS_SQL: Final = (
    "SELECT 'campaign' AS kind, g.id, g.name, g.status, g.status = 'running' AS live, "
    "g.agent_id, a.name AS agent_name, g.extraction_fields FROM campaigns g "
    "JOIN agents a ON a.id = g.agent_id WHERE g.archived_at IS NULL "
    "ORDER BY (g.status = 'running') DESC, lower(g.name), g.id LIMIT :limit"
)
_LINES_SQL: Final = (
    "SELECT 'line' AS kind, l.id, l.name, "
    "CASE WHEN l.engine_agent_ref IS NOT NULL AND l.published_at IS NOT NULL "
    "THEN 'live' ELSE 'draft' END, "
    "l.engine_agent_ref IS NOT NULL AND l.published_at IS NOT NULL, "
    "l.agent_id, a.name, l.extraction_fields FROM inbound_lines l "
    "JOIN agents a ON a.id = l.agent_id WHERE l.archived_at IS NULL "
    "ORDER BY (l.engine_agent_ref IS NOT NULL AND l.published_at IS NOT NULL) DESC, "
    "lower(l.name), l.id LIMIT :limit"
)


def platform_sets(starting: list[ExtractionField]) -> list[list[ExtractionField]]:
    """Every list the platform ever offered this business: its starting set and each business
    type's standard set. A job holding exactly one of them holds nobody's choice, which is how
    a business-type move finds the jobs still on the old type's set without knowing it."""
    sets = [starting]
    for key in verticals.all_keys():
        standard = standard_fields(key)
        if standard:
            sets.append(standard)
    return sets


def untouched(fields: list[ExtractionField], offered: list[list[ExtractionField]]) -> bool:
    return not fields or any(_same_fields(fields, each) for each in offered)


async def jobs_with_fields(
    session: AsyncSession, *, starting: list[ExtractionField]
) -> list[JobRow]:
    """Every open campaign, then every line, each running one first and then by name, with its
    list. RLS scopes both to the session's tenant."""
    from apps.api.campaigns.notes import digest_of

    offered = platform_sets(starting)
    rows = [
        *(await session.execute(text(_JOBS_SQL), {"limit": MAX_JOBS})).all(),
        *(await session.execute(text(_LINES_SQL), {"limit": MAX_JOBS})).all(),
    ]
    out: list[JobRow] = []
    for row in rows:
        fields = business_only(row[7] or [])
        out.append(
            JobRow(
                kind="campaign" if row[0] == "campaign" else "line",
                id=UUID(str(row[1])),
                name=str(row[2]),
                status=str(row[3]),
                live=bool(row[4]),
                agent_id=UUID(str(row[5])),
                agent_name=str(row[6]),
                fields=fields,
                digest=digest_of(row[7]),
                untouched=untouched(fields, offered),
            )
        )
    return out


async def apply_to_jobs(
    session: AsyncSession, *, fields: list[ExtractionField], jobs: list[JobRef]
) -> list[JobWrite]:
    """Write `fields` as the list of each named campaign and line, each under a compare-and-set
    on the digest the screen showed (`campaigns/notes.save_notes`), so a list somebody changed
    while the owner was choosing is refused rather than overwritten. One transaction: a refusal
    writes none of them."""
    from apps.api.campaigns.notes import save_notes

    validate_fields(fields)
    written: list[JobWrite] = []
    for job in jobs:
        changed = await save_notes(
            session, job.kind, job.job_id, fields, expected_digest=job.digest
        )
        written.append(JobWrite(kind=job.kind, job_id=job.job_id, changed=changed))
    return written


def _same_fields(own: list[ExtractionField], seed: list[ExtractionField] | None) -> bool:
    return seed is not None and [f.model_dump() for f in own] == [f.model_dump() for f in seed]


async def refresh_field_reason(
    session: AsyncSession,
    *,
    agent_id: UUID,
    key: str,
    old_reason: str,
    new_reason: str,
    old_enum_values: list[str] | None = None,
    new_enum_values: list[str] | None = None,
) -> bool:
    """Give one agent a template field's new wording, if it still has the old one verbatim.

    For a standard set whose wording we improved after agents were made from it: matching
    the whole old reason, not the key alone, is what leaves a reason the owner rewrote
    untouched. With `old_enum_values` the field's choices must also be exactly those, in
    that order, and are replaced by `new_enum_values` (D-887, the BHK sizes): an owner who
    added or renamed a choice keeps their list. The fields are read under the agent's row
    lock, so an edit saved meanwhile is the list this compares against rather than one it
    overwrites. A new schema version, like every other write. Returns whether one was
    written.
    """
    row = (
        await session.execute(
            text(
                "SELECT es.fields FROM agents a "
                "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    fields = business_only(row[0] or []) if row is not None else []

    def _matches(field: ExtractionField) -> bool:
        return (
            field.key == key
            and field.reason == old_reason
            and (old_enum_values is None or field.enum_values == old_enum_values)
        )

    if not any(_matches(f) for f in fields):
        return False
    change: dict[str, Any] = {"reason": new_reason}
    if new_enum_values is not None:
        change["enum_values"] = new_enum_values
    updated = [f.model_copy(update=change) if _matches(f) else f for f in fields]
    validate_fields(updated)
    return (await write_schema(session, agent_id=agent_id, fields=updated)).changed


#: The worker that names the core details for one business (`workers/core_labels`).
NAME_CORE_JOB: Final = "name_core_details"


async def save_core_labels(
    session: AsyncSession, *, tenant_id: UUID, labels: dict[str, str | None]
) -> dict[str, str]:
    """Replace the client's names for the core details; a blank or default name is the
    platform's again. Stamps the one AI naming as taken, so it never writes over these."""
    named = clean_core_labels({k: v for k, v in labels.items() if v is not None})
    await session.execute(
        text(
            "UPDATE organizations SET core_field_labels = CAST(:labels AS jsonb), "
            "core_labels_drafted_at = coalesce(core_labels_drafted_at, now()) WHERE id = :tid"
        ),
        {"tid": tenant_id, "labels": json.dumps(named)},
    )
    return named


async def maybe_name_core_details(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Queue the one AI naming of the core details once anything describes the business
    (`starter_plans.business_known`: the owner's own words or what it sells), whatever its
    type. Does nothing once it was taken or the owner named any detail.

    Deduped per description, not per account: a naming the model refused frees its claim,
    and the next change to what describes the business must be able to ask again."""
    open_ = (
        await session.execute(
            text(
                "SELECT core_labels_drafted_at IS NULL AND core_field_labels = '{}'::jsonb "
                "FROM organizations WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    known = await business_known(session, tenant_id=tenant_id) if open_ else None
    if known is None:
        return False
    queued = await enqueue_outbox_once(
        session,
        job=NAME_CORE_JOB,
        payload={"tenant_id": str(tenant_id)},
        dedupe_key=f"core-labels:{tenant_id}:{known}",
    )
    return queued is not None


__all__ = [
    "CUSTOM",
    "DRAFT_JOB",
    "MAX_AGENTS",
    "MAX_JOBS",
    "NAME_CORE_JOB",
    "Draft",
    "JobKind",
    "JobRef",
    "JobRow",
    "JobWrite",
    "Reviewed",
    "apply_to_jobs",
    "business_type_label",
    "core_labels",
    "has_business_fields",
    "has_standard_set",
    "jobs_with_fields",
    "maybe_name_core_details",
    "maybe_request_draft",
    "platform_sets",
    "read_draft",
    "refresh_field_reason",
    "request_draft",
    "review_draft",
    "save_core_labels",
    "standard_fields",
    "starting_business_fields",
    "untouched",
    "vertical_of",
]
