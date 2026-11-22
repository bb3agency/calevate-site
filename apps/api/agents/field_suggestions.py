"""Lead details that follow the business: suggested changes, waiting for the owner (D-889).

Founder, 25 Oct 2026: a choice field's list (a real-estate agent's BHK sizes, a salon's
services, a garage's vehicle types) is the business's own, and has to follow what the
business sells and what its callers ask for, for every kind of business. Three things feed it:

* **the voice's script, the business's details and its quick facts**, which say what is sold;
* **unlisted answers** (`call_extractions.unlisted`) on the job's own calls: what callers asked
  for that none of a field's choices fits, kept as their own words instead of the nearest
  wrong choice;
* **what the owner already turned down** (`field_suggestions_dismissed` on the job).

Since D-1029 a pass belongs to one job, a campaign or an inbound line, because the list it
suggests changes to is that job's "What it notes" (D-1028). It reads them and writes at most
`MAX_FIELD_SUGGESTIONS` suggestions onto the job: add choices, remove choices, or a new detail
to capture. Nothing changes the job's list until the owner accepts one, and accepting saves
the list through the editor's own write (`campaigns/notes.save_notes`); leads captured earlier
keep what they noted. Removing a choice the job's calls captured in the last `RECENT_DAYS` is
never suggested.

**When a pass is queued.** On a script save (for every job in that voice), a business-details
save, a quick-facts change, the first publish, the second caller on a job to ask for the same
unlisted thing, and the owner's "Check again". A pass whose inputs hash the same as the last
finished one spends nothing, so these
triggers can be generous. A pass already running when another is asked for leaves the state
`queued`; the running pass sees that when it finishes and queues the next one itself, so a
change made mid-pass is never lost.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import business_only
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import agent_pass
from apps.api.agents.agent_pass import dead_sql
from apps.api.agents.models import MAX_DISMISSED_SUGGESTIONS
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.errors import ProblemError
from apps.api.reliability.service import enqueue_outbox

#: The ARQ name of the pass (`workers/field_suggestions`).
JOB: Final = "suggest_lead_details"
#: The ARQ name of one agent's "what to collect" rebuild after its lead details changed.
RECOMPILE_COLLECT_JOB: Final = "rebuild_collect"

#: A pass `running` longer than this died (a worker killed mid-way) and may be queued again.
STALE_MINUTES: Final = agent_pass.STALE_MINUTES
#: How far back unlisted answers and captured choices are read.
RECENT_DAYS: Final = 90
#: An unlisted answer heard this many times queues a pass; once is noise, twice is demand.
REPEAT_THRESHOLD: Final = 2

REASON_MAX: Final = 200
CHOICE_MAX: Final = 40
LABEL_MAX: Final = 40
HINT_MAX: Final = 300
#: Choices a suggested list may end with. Long lists are read on every call and steer badly.
MAX_CHOICES: Final = 20

Kind = Literal["add_choices", "remove_choices", "new_field"]
#: `campaigns.notes.JobKind`, restated: that module imports this one's neighbours.
JobKind = Literal["campaign", "line"]
#: `agents.models.FIELD_SUGGESTION_STATES`, plus `none` for a job no pass has run for.
PassState = Literal["none", "queued", "running", "done", "failed", "skipped"]
Source = Literal["purpose", "script", "business", "facts", "calls"]


class Suggestion(BaseModel):
    """One change waiting for the owner. `id` is a fingerprint of the change itself, so the
    same idea offered again has the same id and a dismissed one stays dismissed."""

    model_config = {"extra": "forbid"}

    id: str
    kind: Kind
    field_key: str
    field_label: str
    #: Choices to add or remove; for a new field, its choices (empty for a text field).
    values: list[str] = Field(default_factory=list, max_length=MAX_CHOICES)
    #: The field to add, for `new_field` only.
    field: ExtractionField | None = None
    #: One sentence for the owner saying why, in English.
    reason: str
    source: Source
    #: Calls in the last `RECENT_DAYS` whose unlisted answer this would have caught.
    callers: int = 0


class SuggestionsState(BaseModel):
    model_config = {"extra": "forbid"}

    state: PassState
    suggestions: list[Suggestion]
    checked_at: datetime | None = None


def normalise(value: str) -> str:
    """The form two spellings of one answer share: "6 BHK", "6bhk" and "6-BHK" are one."""
    return re.sub(r"[\W_]+", "", value.casefold())


def suggestion_fingerprint(kind: str, field_key: str, values: list[str], label: str = "") -> str:
    canon = "|".join([kind, field_key, normalise(label), *sorted(normalise(v) for v in values)])
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def applicable(suggestion: Suggestion, fields: list[ExtractionField]) -> bool:
    """Does the change still make sense against the fields the agent has NOW? The owner may
    have edited them since the pass ran; a suggestion that no longer fits is not shown."""
    by_key = {f.key: f for f in fields}
    if suggestion.kind == "new_field":
        return suggestion.field is not None and suggestion.field.key not in by_key
    field = by_key.get(suggestion.field_key)
    if field is None or field.type != "enum":
        return False
    have = {normalise(v) for v in field.enum_values or []}
    wanted = {normalise(v) for v in suggestion.values}
    if suggestion.kind == "add_choices":
        return bool(wanted - have) and len(have | wanted) <= MAX_CHOICES
    left = have - wanted
    return wanted <= have and len(left) >= 2


def apply(suggestion: Suggestion, fields: list[ExtractionField]) -> list[ExtractionField]:
    """The agent's fields with the change made. The caller has checked `applicable`."""
    if suggestion.kind == "new_field":
        assert suggestion.field is not None
        return [*fields, suggestion.field]
    out: list[ExtractionField] = []
    for field in fields:
        if field.key != suggestion.field_key:
            out.append(field)
            continue
        current = list(field.enum_values or [])
        if suggestion.kind == "add_choices":
            have = {normalise(v) for v in current}
            current += [v for v in suggestion.values if normalise(v) not in have]
        else:
            gone = {normalise(v) for v in suggestion.values}
            current = [v for v in current if normalise(v) not in gone]
        out.append(field.model_copy(update={"enum_values": current}))
    return out


def stored(raw: Any) -> list[Suggestion]:
    """The suggestions column as models. A malformed item is skipped: the column is ours, and
    one bad entry must not hide the rest."""
    out: list[Suggestion] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(Suggestion.model_validate(item))
        except ValidationError:
            continue
    return out


def _table(kind: JobKind) -> str:
    """The job's table, as a conditional of literals so `scripts/check_raw_sql.py` can read it."""
    return "campaigns" if kind == "campaign" else "inbound_lines"


def _calls_of(kind: JobKind) -> str:
    """The calls a job made: a campaign's own (its Test calls count in no result, so they are
    left out) or a line's."""
    return "c.campaign_id = :jid" if kind == "campaign" else "c.inbound_line_id = :jid"


def _noun(kind: JobKind) -> str:
    return "Campaign" if kind == "campaign" else "Inbound line"


async def current_fields(
    session: AsyncSession, kind: JobKind, job_id: UUID
) -> list[ExtractionField]:
    """The job's own "What it notes" list (D-1028); empty for a job that is gone."""
    raw = (
        await session.execute(
            text(f"SELECT extraction_fields FROM {_table(kind)} WHERE id = :jid"),
            {"jid": job_id},
        )
    ).scalar()
    return business_only(raw or [])


#: The pass's columns and job on the shared queue (`agents/agent_pass`), one slot per table.
SLOTS: Final[dict[JobKind, agent_pass.PassSlot]] = {
    "campaign": agent_pass.PassSlot(
        "field_suggestions", JOB, table="campaigns", gone="archived_at", id_key="campaign_id"
    ),
    "line": agent_pass.PassSlot(
        "field_suggestions", JOB, table="inbound_lines", gone="archived_at", id_key="line_id"
    ),
}


def job_of_payload(payload: dict[str, Any]) -> tuple[JobKind, UUID] | None:
    """The job a queued pass names. None for a payload queued before D-1029, which named an
    agent: its pass has no list of its own to read any more."""
    if payload.get("campaign_id"):
        return "campaign", UUID(str(payload["campaign_id"]))
    if payload.get("line_id"):
        return "line", UUID(str(payload["line_id"]))
    return None


async def queue_pass(
    session: AsyncSession, *, tenant_id: UUID, kind: JobKind, job_id: UUID, force: bool = False
) -> bool:
    """Ask for a pass over this job's list, in the caller's transaction (`agent_pass.queue`).
    `force` is the owner's "Check again"."""
    return await agent_pass.queue(
        session, SLOTS[kind], tenant_id=tenant_id, row_id=job_id, force=force
    )


async def queue_job(session: AsyncSession, kind: JobKind, job_id: UUID) -> bool:
    """`queue_pass` for one job whose aim or script just changed, or that was just made: an
    empty list gets its starting set suggested, a full one is checked against the new aim."""
    sql = (
        "SELECT tenant_id FROM campaigns WHERE id = :jid"
        if kind == "campaign"
        else "SELECT tenant_id FROM inbound_lines WHERE id = :jid"
    )
    tenant_id = (await session.execute(text(sql), {"jid": job_id})).scalar()
    if tenant_id is None:
        return False
    tenant = UUID(str(tenant_id))
    # Nobody pressed a button for this pass, so the account's content waits for Pip to be
    # turned on (`account_content_may_reach_models`); "Check again" is the way without it.
    if not await account_content_may_reach_models(session, tenant_id=tenant):
        return False
    return await queue_pass(session, tenant_id=tenant, kind=kind, job_id=job_id)


#: Every open job, or those in one agent's voice. RLS scopes both tables to the tenant.
_OPEN_JOBS_SQL: Final = (
    "SELECT 'campaign', id FROM campaigns WHERE archived_at IS NULL "
    "AND (CAST(:aid AS uuid) IS NULL OR agent_id = :aid) "
    "UNION ALL SELECT 'line', id FROM inbound_lines WHERE archived_at IS NULL "
    "AND (CAST(:aid AS uuid) IS NULL OR agent_id = :aid)"
)


async def _open_jobs(session: AsyncSession, agent_id: UUID | None) -> list[tuple[JobKind, UUID]]:
    rows = (
        await session.execute(text(_OPEN_JOBS_SQL), {"aid": str(agent_id) if agent_id else None})
    ).all()
    return [("campaign" if r[0] == "campaign" else "line", UUID(str(r[1]))) for r in rows]


async def queue_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, first: bool = False
) -> int:
    """`queue_pass` for every open job in this agent's voice: its script says what the
    business sells. `first` (at publish) queues only a job no pass has ever run for."""
    queued = 0
    for kind, job_id in await _open_jobs(session, agent_id):
        if first:
            queued += await agent_pass.queue_first(
                session, SLOTS[kind], tenant_id=tenant_id, row_id=job_id
            )
        else:
            queued += await queue_pass(session, tenant_id=tenant_id, kind=kind, job_id=job_id)
    return queued


async def queue_account(session: AsyncSession, *, tenant_id: UUID) -> int:
    """`queue_pass` for every open job of the account: its business details or facts changed."""
    queued = 0
    for kind, job_id in await _open_jobs(session, None):
        queued += await queue_pass(session, tenant_id=tenant_id, kind=kind, job_id=job_id)
    return queued


#: The job a call was made for: its campaign, the campaign whose Test call it was, or its line.
_CALL_JOB_SQL: Final = (
    "SELECT c.campaign_id, (SELECT t.id FROM campaigns t WHERE c.campaign_id IS NULL "
    "AND c.id = ANY (t.test_call_ids) LIMIT 1), c.inbound_line_id FROM calls c WHERE c.id = :cid"
)


async def queue_on_repeat(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, unlisted: dict[str, str]
) -> bool:
    """After a call stored unlisted answers: queue a pass over the call's job when one of them
    has now been heard exactly `REPEAT_THRESHOLD` times on that job's calls, so the second
    caller asking for the same thing is what brings it to the owner, and the tenth does not buy
    another pass. A call with no job notes only the core, so it has nothing to suggest for."""
    if not unlisted:
        return False
    # The one trigger nobody presses: a call. The pass sends callers' answers to a model,
    # so it waits for the owner to turn Pip on; "Check again" is the way without it.
    if not await account_content_may_reach_models(session, tenant_id=tenant_id):
        return False
    row = (await session.execute(text(_CALL_JOB_SQL), {"cid": call_id})).first()
    if row is None or not any(row):
        return False
    kind: JobKind = "line" if row[0] is None and row[1] is None else "campaign"
    job_id = UUID(str(row[0] or row[1] or row[2]))
    rows = (
        await session.execute(
            text(
                "SELECT kv.key, kv.value FROM call_extractions ce "
                "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
                "CROSS JOIN LATERAL jsonb_each_text(ce.unlisted) AS kv "
                f"WHERE {_calls_of(kind)} AND ce.unlisted IS NOT NULL "
                f"AND ce.updated_at > now() - interval '{RECENT_DAYS} days'"
            ),
            {"jid": job_id},
        )
    ).all()
    counts: dict[tuple[str, str], int] = {}
    for key, said in rows:
        counts[(str(key), normalise(str(said)))] = (
            counts.get((str(key), normalise(str(said))), 0) + 1
        )
    if not any(
        counts.get((key, normalise(said)), 0) == REPEAT_THRESHOLD for key, said in unlisted.items()
    ):
        return False
    return await queue_pass(session, tenant_id=tenant_id, kind=kind, job_id=job_id)


async def read_state(session: AsyncSession, kind: JobKind, job_id: UUID) -> SuggestionsState:
    row = (
        await session.execute(
            text(
                "SELECT field_suggestions, field_suggestions_state, field_suggestions_at, "
                f"  {dead_sql(SLOTS[kind])}, extraction_fields FROM {_table(kind)} "
                "WHERE id = :jid AND archived_at IS NULL"
            ),
            {"jid": job_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found(_noun(kind))
    fields = business_only(row[4] or [])
    state: PassState = "failed" if row[3] else (row[1] or "none")
    return SuggestionsState(
        state=state,
        suggestions=[s for s in stored(row[0]) if applicable(s, fields)],
        checked_at=row[2] if state in ("done", "failed", "skipped") else None,
    )


async def _locked(
    session: AsyncSession, kind: JobKind, job_id: UUID
) -> tuple[list[Suggestion], list[str]]:
    row = (
        await session.execute(
            text(
                "SELECT field_suggestions, field_suggestions_dismissed "
                f"FROM {_table(kind)} WHERE id = :jid AND archived_at IS NULL FOR UPDATE"
            ),
            {"jid": job_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found(_noun(kind))
    return stored(row[0]), [str(f) for f in row[1] or []]


async def _save(
    session: AsyncSession,
    kind: JobKind,
    job_id: UUID,
    suggestions: list[Suggestion],
    dismissed: list[str],
) -> None:
    await session.execute(
        text(
            f"UPDATE {_table(kind)} SET field_suggestions = CAST(:s AS jsonb), "
            "field_suggestions_dismissed = CAST(:d AS jsonb), updated_at = now() "
            "WHERE id = :jid"
        ),
        {
            "jid": job_id,
            "s": json.dumps([s.model_dump(mode="json") for s in suggestions]),
            "d": json.dumps(dismissed[-MAX_DISMISSED_SUGGESTIONS:]),
        },
    )


def _gone(kind: JobKind) -> str:
    return (
        f"That suggestion no longer fits what this {_noun(kind).lower()} notes, which changed "
        "since it was made. Check again for fresh ones."
    )


async def accept(
    session: AsyncSession, kind: JobKind, job_id: UUID, *, suggestion_id: str
) -> Suggestion:
    """Make the change to the job's list through its own write (`campaigns/notes.save_notes`),
    then the suggestion is gone. 409 when it no longer fits the job's current list. The job's
    engine agent learns the list at its next put-live, which the route asks for."""
    from apps.api.campaigns.notes import save_notes

    suggestions, dismissed = await _locked(session, kind, job_id)
    chosen = next((s for s in suggestions if s.id == suggestion_id), None)
    if chosen is None:
        raise ProblemError.not_found("Suggestion")
    fields = await current_fields(session, kind, job_id)
    remaining = [s for s in suggestions if s.id != suggestion_id]
    if not applicable(chosen, fields):
        await _save(session, kind, job_id, remaining, dismissed)
        raise ProblemError.conflict("suggestion_out_of_date", _gone(kind))
    await save_notes(session, kind, job_id, apply(chosen, fields), expected_digest=None)
    await _save(session, kind, job_id, remaining, dismissed)
    return chosen


async def dismiss(
    session: AsyncSession, kind: JobKind, job_id: UUID, *, suggestion_id: str
) -> Suggestion:
    """The owner said no: the suggestion goes, and its fingerprint is kept so the same idea
    is not offered again."""
    suggestions, dismissed = await _locked(session, kind, job_id)
    chosen = next((s for s in suggestions if s.id == suggestion_id), None)
    if chosen is None:
        raise ProblemError.not_found("Suggestion")
    remaining = [s for s in suggestions if s.id != suggestion_id]
    await _save(session, kind, job_id, remaining, [*dismissed, chosen.id])
    return chosen


async def queue_collect_rebuild(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> None:
    """After the agent's lead details changed: rebuild what it asks callers for, in a worker,
    so a live agent asks for the new details on its next call rather than at the owner's next
    script save. A worker, not inline, because a live agent's rebuild republishes it, and a
    voice-platform hiccup must not fail the owner's save."""
    await enqueue_outbox(
        session,
        job=RECOMPILE_COLLECT_JOB,
        payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
    )


__all__ = [
    "CHOICE_MAX",
    "HINT_MAX",
    "JOB",
    "LABEL_MAX",
    "MAX_CHOICES",
    "REASON_MAX",
    "RECENT_DAYS",
    "RECOMPILE_COLLECT_JOB",
    "REPEAT_THRESHOLD",
    "SLOTS",
    "JobKind",
    "Kind",
    "Source",
    "Suggestion",
    "SuggestionsState",
    "accept",
    "applicable",
    "apply",
    "current_fields",
    "dismiss",
    "job_of_payload",
    "normalise",
    "queue_account",
    "queue_agent",
    "queue_collect_rebuild",
    "queue_on_repeat",
    "queue_pass",
    "read_state",
    "stored",
    "suggestion_fingerprint",
]
