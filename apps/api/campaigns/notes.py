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
                f"SELECT extraction_fields, tenant_id FROM {table} WHERE id = :jid "
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
    # The notes are compiled into the job's script, so more of them can push a saved script
    # past the engine's box. Measured after the write, on the job as its publish would build
    # it, so a refusal rolls the write back with the transaction.
    from apps.api.agents.script_builder import refuse_job_if_too_long

    await refuse_job_if_too_long(
        session, kind=kind, tenant_id=UUID(str(current[1])), job_id=job_id, for_notes=True
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


#: Every campaign's and line's list, open ones first (archived ones only when asked), newest
#: edit first; RLS scopes both to the tenant.
_ACCOUNT_LISTS_SQL: Final = (
    "SELECT fields FROM (SELECT extraction_fields AS fields, updated_at AS at, agent_id, "
    "archived_at IS NOT NULL AS archived FROM campaigns "
    "UNION ALL SELECT extraction_fields, updated_at, agent_id, archived_at IS NOT NULL "
    "FROM inbound_lines) lists "
    "WHERE jsonb_array_length(fields) > 0 AND (CAST(:aid AS uuid) IS NULL OR agent_id = :aid) "
    "AND (CAST(:archived AS boolean) OR NOT archived) "
    "ORDER BY archived, at DESC LIMIT 500"
)


#: The job a call was made for: its campaign, the campaign whose Test call it was, or its line.
#: Unlike `CALL_JOB_SQL` it does not ask whether the job has a list of its own.
_CALL_JOB_IDS_SQL: Final = (
    "SELECT c.campaign_id, (SELECT t.id FROM campaigns t WHERE c.campaign_id IS NULL "
    "AND c.id = ANY (t.test_call_ids) LIMIT 1), c.inbound_line_id FROM calls c WHERE c.id = :cid"
)


async def call_job(session: AsyncSession, call_id: UUID) -> tuple[JobKind, UUID] | None:
    """The job a call did, whatever its list holds; None for a call with no job."""
    row = (await session.execute(text(_CALL_JOB_IDS_SQL), {"cid": call_id})).first()
    if row is None or not any(row):
        return None
    if row[0] is not None or row[1] is not None:
        return "campaign", UUID(str(row[0] or row[1]))
    return "line", UUID(str(row[2]))


async def account_fields(
    session: AsyncSession, *, agent_id: UUID | None = None, archived: bool = False
) -> list[ExtractionField]:
    """Every detail the account's open campaigns and lines note, one per key, the most
    recently edited job's wording first: alerts, actions and filters across jobs.
    `agent_id` narrows it to the jobs in that agent's voice. `archived` adds what archived
    jobs noted, after the open ones: their leads keep those details (the Leads columns)."""
    rows = (
        await session.execute(
            text(_ACCOUNT_LISTS_SQL),
            {"aid": str(agent_id) if agent_id else None, "archived": archived},
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
    "call_job",
    "digest_of",
    "job_table",
    "read_notes",
    "save_notes",
    "starting_fields",
]
