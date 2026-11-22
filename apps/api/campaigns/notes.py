"""What a job's calls note: "What it notes" on a campaign or an inbound line (D-1003, D-1028).

The list of details a call writes down belongs to the job the call does, never to the agent,
which is only the voice (founder, 22 Nov 2026). A campaign keeps its list in
`campaigns.extraction_fields` and a line in `inbound_lines.extraction_fields`, in the
extraction-schema field shape. It is read in two places, both from these columns:

* the job's engine agent asks for these details (`script_builder.job_collect_fields`
  compiles them into its script);
* the post-call pipeline notes them (`workers/pipeline._load_call_context` picks the call's
  campaign's list, else its line's).

A call with no job (an agent's own test call) notes only the core every lead carries
(`calevate_shared.lead_fields`).

The list is held to the extraction rules (`agents/extraction_routes._validate_fields`) and
saved whole under a compare-and-set on the digest of the list the editor was showing, so two
people saving at once cannot drop each other's details.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import business_only
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import _validate_fields
from apps.api.core.errors import ProblemError

JobKind = Literal["campaign", "line"]


def job_table(kind: JobKind) -> str:
    """The job's table, as a conditional of literals so `scripts/check_raw_sql.py` can read it."""
    return "campaigns" if kind == "campaign" else "inbound_lines"


def _noun(kind: JobKind) -> str:
    return "Campaign" if kind == "campaign" else "Inbound line"


@dataclass(frozen=True, slots=True)
class JobNotes:
    job_id: UUID
    agent_id: UUID
    agent_name: str
    fields: tuple[ExtractionField, ...]
    #: The digest of `fields` as stored, sent back with a save.
    digest: str


def digest_of(raw: Any) -> str:
    return hashlib.sha256(json.dumps(raw or [], sort_keys=True).encode()).hexdigest()


def _fields(raw: Any) -> tuple[ExtractionField, ...]:
    return tuple(business_only([ExtractionField.model_validate(f) for f in (raw or [])]))


async def read_notes(session: AsyncSession, kind: JobKind, job_id: UUID) -> JobNotes:
    table, noun = job_table(kind), _noun(kind)
    row = (
        await session.execute(
            text(
                f"SELECT j.agent_id, a.name, j.extraction_fields FROM {table} j "
                "JOIN agents a ON a.id = j.agent_id "
                "WHERE j.id = :jid AND j.archived_at IS NULL"
            ),
            {"jid": job_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found(noun)
    return JobNotes(
        job_id=job_id,
        agent_id=UUID(str(row[0])),
        agent_name=str(row[1]),
        fields=_fields(row[2]),
        digest=digest_of(row[2]),
    )


async def save_notes(
    session: AsyncSession,
    kind: JobKind,
    job_id: UUID,
    fields: list[ExtractionField],
    *,
    expected_digest: str | None,
) -> bool:
    """Replace the job's list. Refused when the list changed since the editor read it
    (`expected_digest`). True when something changed."""
    table, noun = job_table(kind), _noun(kind)
    own = business_only(fields)
    _validate_fields(own)
    current = (
        await session.execute(
            text(
                f"SELECT extraction_fields FROM {table} WHERE id = :jid "
                "AND archived_at IS NULL FOR UPDATE"
            ),
            {"jid": job_id},
        )
    ).first()
    if current is None:
        raise ProblemError.not_found(noun)
    stored = [field.model_dump(mode="json", exclude_none=True) for field in own]
    # Asked before the compare-and-set: a list that already holds exactly what is sent loses
    # nobody's change, and it is what a Save again sends after a save whose put-live was
    # refused, from an editor still holding the digest of the list before that save.
    if digest_of(stored) == digest_of(current[0]):
        return False
    if expected_digest is not None and digest_of(current[0]) != expected_digest:
        raise ProblemError.conflict(
            f"{kind}_notes_changed_elsewhere",
            f"Someone else changed what this {noun.lower()} notes while you were editing.",
            remediation="Load the current list, then make your change again.",
        )
    await session.execute(
        text(
            f"UPDATE {table} SET extraction_fields = CAST(:f AS jsonb), updated_at = now() "
            "WHERE id = :jid"
        ),
        {"f": json.dumps(stored), "jid": job_id},
    )
    return True


async def starting_fields(session: AsyncSession, *, tenant_id: UUID) -> list[dict[str, Any]]:
    """The list a new campaign or line starts with: the business's starting set
    (`lead_fields.starting_business_fields`, D-1029), whichever agent's voice it is in."""
    from apps.api.agents.lead_fields import starting_business_fields, vertical_of

    fields = business_only(
        await starting_business_fields(
            session,
            tenant_id=tenant_id,
            vertical=await vertical_of(session, tenant_id=tenant_id),
        )
    )
    return [field.model_dump(mode="json", exclude_none=True) for field in fields]


#: The joins that find a call's job, for `CALL_JOB_FIELDS_SQL` and `CALL_JOB_SQL`. The caller
#: aliases `calls` as `c`. A campaign's Test call is not in `calls.campaign_id` (it would count
#: in the campaign's results) but in `campaigns.test_call_ids`, so it is found there and notes
#: what the campaign it tested notes.
CALL_JOB_JOINS: Final = (
    "LEFT JOIN campaigns g ON g.id = c.campaign_id "
    "LEFT JOIN LATERAL (SELECT t.id, t.extraction_fields FROM campaigns t "
    "WHERE c.campaign_id IS NULL AND c.id = ANY (t.test_call_ids) LIMIT 1) gt ON true "
    "LEFT JOIN inbound_lines l ON l.id = c.inbound_line_id "
)
#: The list a call notes: its campaign's, else the campaign it tested, else its line's; NULL
#: for a call with no job, which notes only the core.
CALL_JOB_FIELDS_SQL: Final = (
    "COALESCE(NULLIF(g.extraction_fields, '[]'::jsonb), "
    "NULLIF(gt.extraction_fields, '[]'::jsonb), NULLIF(l.extraction_fields, '[]'::jsonb))"
)
#: Which job that list belongs to, as `campaign` or `line`, and its id; NULLs with no list.
CALL_JOB_SQL: Final = (
    "CASE WHEN jsonb_array_length(g.extraction_fields) > 0 THEN 'campaign' "
    "WHEN jsonb_array_length(gt.extraction_fields) > 0 THEN 'campaign' "
    "WHEN jsonb_array_length(l.extraction_fields) > 0 THEN 'line' END, "
    "CASE WHEN jsonb_array_length(g.extraction_fields) > 0 THEN g.id "
    "WHEN jsonb_array_length(gt.extraction_fields) > 0 THEN gt.id "
    "WHEN jsonb_array_length(l.extraction_fields) > 0 THEN l.id END"
)


#: Every open campaign's and line's list, newest edit first; RLS scopes both to the tenant.
_ACCOUNT_LISTS_SQL: Final = (
    "SELECT fields FROM (SELECT extraction_fields AS fields, updated_at AS at, agent_id "
    "FROM campaigns WHERE archived_at IS NULL "
    "UNION ALL SELECT extraction_fields, updated_at, agent_id FROM inbound_lines "
    "WHERE archived_at IS NULL) lists "
    "WHERE jsonb_array_length(fields) > 0 AND (CAST(:aid AS uuid) IS NULL OR agent_id = :aid) "
    "ORDER BY at DESC LIMIT 500"
)


async def account_fields(
    session: AsyncSession, *, agent_id: UUID | None = None
) -> list[ExtractionField]:
    """Every detail the account's campaigns and lines note, one per key, the most recently
    edited job's wording first: the Leads columns, alerts and filters across jobs.
    `agent_id` narrows it to the jobs in that agent's voice."""
    rows = (
        await session.execute(
            text(_ACCOUNT_LISTS_SQL), {"aid": str(agent_id) if agent_id else None}
        )
    ).all()
    out: list[ExtractionField] = []
    seen: set[str] = set()
    for (raw,) in rows:
        for field in _fields(raw):
            if field.key not in seen:
                seen.add(field.key)
                out.append(field)
    return out


__all__ = [
    "JobKind",
    "JobNotes",
    "account_fields",
    "digest_of",
    "job_table",
    "read_notes",
    "save_notes",
    "starting_fields",
]
