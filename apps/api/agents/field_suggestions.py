"""Lead details that follow the business: suggested changes, waiting for the owner (D-889).

Founder, 25 Oct 2026: a choice field's list (a real-estate agent's BHK sizes, a salon's
services, a garage's vehicle types) is the business's own, and has to follow what the
business sells and what its callers ask for, for every kind of business. Three things feed it:

* **the agent's script, the business's details and its quick facts**, which say what is sold;
* **unlisted answers** (`call_extractions.unlisted`): what callers asked for that none of a
  field's choices fits, kept as their own words instead of the nearest wrong choice;
* **what the owner already turned down** (`agents.field_suggestions_dismissed`).

A pass (`workers/field_suggestions`) reads them and writes at most `MAX_FIELD_SUGGESTIONS`
suggestions onto the agent: add choices, remove choices, or a new detail to capture. Nothing
changes the agent's fields until the owner accepts one, and accepting writes a new schema
version like every other edit, so leads captured earlier keep the names they were captured
under. Removing a choice the agent captured in the last `RECENT_DAYS` is never suggested.

**When a pass is queued.** On a script save, a business-details save, a quick-facts change,
the first publish, the second caller to ask for the same unlisted thing, and the owner's "Check
again". A pass whose inputs hash the same as the last finished one spends nothing, so these
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

from apps.api.agents.models import MAX_DISMISSED_SUGGESTIONS
from apps.api.core.errors import ProblemError
from apps.api.reliability.service import enqueue_outbox

#: The ARQ name of the pass (`workers/field_suggestions`).
JOB: Final = "suggest_lead_details"
#: The ARQ name of one agent's "what to collect" rebuild after its lead details changed.
RECOMPILE_COLLECT_JOB: Final = "rebuild_collect"

#: A pass `running` longer than this died (a worker killed mid-way) and may be queued again.
STALE_MINUTES: Final = 15
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
#: `agents.models.FIELD_SUGGESTION_STATES`, plus `none` for an agent no pass has run for.
PassState = Literal["none", "queued", "running", "done", "failed", "skipped"]
Source = Literal["script", "business", "facts", "calls"]


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


async def current_fields(session: AsyncSession, agent_id: UUID) -> list[ExtractionField]:
    row = (
        await session.execute(
            text(
                "SELECT es.fields FROM agents a JOIN extraction_schemas es "
                "ON es.id = a.extraction_schema_id WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    return business_only(row[0] or []) if row is not None else []


#: A pass queued or running for longer than `STALE_MINUTES` has no live job behind it: the
#: worker died mid-pass, or a pass marked `queued` while it ran died before re-queuing.
_DEAD_SQL: Final = (
    "(field_suggestions_state IN ('queued', 'running') AND field_suggestions_at < "
    f"now() - interval '{STALE_MINUTES} minutes')"
)


async def queue_pass(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, force: bool = False
) -> bool:
    """Ask for a pass over this agent's lead details, in the caller's transaction.

    True when a job was queued. A pass already queued is left as it is; one running is
    marked `queued` without a job, and queues the next one itself when it finishes. A dead
    one (`_DEAD_SQL`) gets a fresh job; the worker's claim lets only one of two run.

    `force` is the owner's "Check again": the last reading's hash is forgotten, so the next
    pass reads afresh even when nothing changed. On the row, not the job, because a pass
    already queued is the one that runs.
    """
    if force:
        await session.execute(
            text("UPDATE agents SET field_suggestions_inputs = NULL WHERE id = :aid"),
            {"aid": agent_id},
        )
    prev = (
        await session.execute(
            text(
                "WITH prev AS (SELECT field_suggestions_state AS state, "
                f"  {_DEAD_SQL} AS dead FROM agents "
                "  WHERE id = :aid AND deleted_at IS NULL FOR UPDATE) "
                "UPDATE agents a SET field_suggestions_state = 'queued', "
                "  field_suggestions_at = now() FROM prev "
                "WHERE a.id = :aid AND (prev.state IS DISTINCT FROM 'queued' OR prev.dead) "
                "RETURNING prev.state, prev.dead"
            ),
            {"aid": agent_id},
        )
    ).first()
    if prev is None:
        return False
    if prev[0] == "running" and not prev[1]:
        return False
    await enqueue_outbox(
        session, job=JOB, payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    )
    return True


async def queue_first_pass(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> bool:
    """At publish: the agent's first pass, once. Later publishes change nothing a pass reads
    that a script, details or facts save has not already queued one for."""
    state = (
        await session.execute(
            text("SELECT field_suggestions_state FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).first()
    if state is None or state[0] is not None:
        return False
    return await queue_pass(session, tenant_id=tenant_id, agent_id=agent_id)


async def queue_account(session: AsyncSession, *, tenant_id: UUID) -> int:
    """`queue_pass` for every agent of the account: its business details or facts changed."""
    ids = (await session.execute(text("SELECT id FROM agents WHERE deleted_at IS NULL"))).scalars()
    queued = 0
    for agent_id in list(ids):
        queued += await queue_pass(session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)))
    return queued


async def queue_on_repeat(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, unlisted: dict[str, str]
) -> bool:
    """After a call stored unlisted answers: queue a pass when one of them has now been
    heard exactly `REPEAT_THRESHOLD` times, so the second caller asking for the same thing is
    what brings it to the owner, and the tenth does not buy another pass."""
    if not unlisted:
        return False
    rows = (
        await session.execute(
            text(
                "SELECT kv.key, kv.value FROM call_extractions ce "
                "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
                "CROSS JOIN LATERAL jsonb_each_text(ce.unlisted) AS kv "
                "WHERE c.agent_id = :aid AND ce.unlisted IS NOT NULL "
                f"AND ce.updated_at > now() - interval '{RECENT_DAYS} days'"
            ),
            {"aid": agent_id},
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
    return await queue_pass(session, tenant_id=tenant_id, agent_id=agent_id)


async def read_state(session: AsyncSession, *, agent_id: UUID) -> SuggestionsState:
    row = (
        await session.execute(
            text(
                "SELECT field_suggestions, field_suggestions_state, field_suggestions_at, "
                f"  {_DEAD_SQL} FROM agents WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    fields = await current_fields(session, agent_id)
    state: PassState = "failed" if row[3] else (row[1] or "none")
    return SuggestionsState(
        state=state,
        suggestions=[s for s in stored(row[0]) if applicable(s, fields)],
        checked_at=row[2] if state in ("done", "failed", "skipped") else None,
    )


async def _locked(session: AsyncSession, agent_id: UUID) -> tuple[list[Suggestion], list[str]]:
    row = (
        await session.execute(
            text(
                "SELECT field_suggestions, field_suggestions_dismissed FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return stored(row[0]), [str(f) for f in row[1] or []]


async def _save(
    session: AsyncSession, agent_id: UUID, suggestions: list[Suggestion], dismissed: list[str]
) -> None:
    await session.execute(
        text(
            "UPDATE agents SET field_suggestions = CAST(:s AS jsonb), "
            "field_suggestions_dismissed = CAST(:d AS jsonb), updated_at = now() "
            "WHERE id = :aid"
        ),
        {
            "aid": agent_id,
            "s": json.dumps([s.model_dump(mode="json") for s in suggestions]),
            "d": json.dumps(dismissed[-MAX_DISMISSED_SUGGESTIONS:]),
        },
    )


_GONE: Final = (
    "That suggestion no longer fits this agent's lead details, which changed since it was "
    "made. Check again for fresh ones."
)


async def accept(session: AsyncSession, *, agent_id: UUID, suggestion_id: str) -> Suggestion:
    """Make the change: a new schema version through the one write path, then the
    suggestion is gone. 409 when it no longer fits the agent's current fields."""
    from apps.api.agents.extraction_routes import validate_fields, write_schema

    suggestions, dismissed = await _locked(session, agent_id)
    chosen = next((s for s in suggestions if s.id == suggestion_id), None)
    if chosen is None:
        raise ProblemError.not_found("Suggestion")
    fields = await current_fields(session, agent_id)
    remaining = [s for s in suggestions if s.id != suggestion_id]
    if not applicable(chosen, fields):
        await _save(session, agent_id, remaining, dismissed)
        raise ProblemError.conflict("suggestion_out_of_date", _GONE)
    changed = apply(chosen, fields)
    validate_fields(changed)
    await write_schema(session, agent_id=agent_id, fields=changed)
    await _save(session, agent_id, remaining, dismissed)
    return chosen


async def dismiss(session: AsyncSession, *, agent_id: UUID, suggestion_id: str) -> Suggestion:
    """The owner said no: the suggestion goes, and its fingerprint is kept so the same idea
    is not offered again."""
    suggestions, dismissed = await _locked(session, agent_id)
    chosen = next((s for s in suggestions if s.id == suggestion_id), None)
    if chosen is None:
        raise ProblemError.not_found("Suggestion")
    remaining = [s for s in suggestions if s.id != suggestion_id]
    await _save(session, agent_id, remaining, [*dismissed, chosen.id])
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
    "Kind",
    "Source",
    "Suggestion",
    "SuggestionsState",
    "accept",
    "applicable",
    "apply",
    "current_fields",
    "dismiss",
    "normalise",
    "queue_account",
    "queue_collect_rebuild",
    "queue_on_repeat",
    "queue_pass",
    "read_state",
    "stored",
    "suggestion_fingerprint",
]
