"""Each agent's own call outcomes (D-836): read, written by the owner, drafted once by AI.

The outcomes live on the agent (`agents.business_outcomes`) rather than in a table of their
own: they are read whole every time (the extraction prompt, the editor), there are at most
`MAX_BUSINESS_OUTCOMES`, and a call keeps the label it was given
(`calls.business_outcome_label`), so an edit here never needs to reach back into history.

The AI draft happens once per agent (`business_outcomes_draft`, compare-and-swap from NULL),
queued when the agent is published and, for an agent published before D-836, by its first
call after it (`workers/pipeline`). A person's list always wins: the draft writes only
where `business_outcomes` is still NULL.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.business_outcomes import (
    STARTING_OUTCOMES,
    BusinessOutcome,
    LeadMove,
    outcome_key,
    outcome_problems,
)
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.lead_fields import MAX_AGENTS
from apps.api.core.errors import ProblemError
from apps.api.reliability.service import enqueue_outbox

#: The ARQ job that drafts them (`apps/workers/business_outcomes_draft.JOB_NAME`).
DRAFT_JOB: Final = "draft_business_outcomes"


def stored_outcomes(raw: object) -> list[BusinessOutcome] | None:
    """`agents.business_outcomes` as outcomes; None when the agent has none of its own.

    An item that no longer validates is dropped rather than failing every call of the agent:
    the CHECK bounds the array, not each item's shape.
    """
    if not isinstance(raw, list):
        return None
    out: list[BusinessOutcome] = []
    for item in raw:
        try:
            out.append(BusinessOutcome.model_validate(item))
        except ValidationError:
            continue
    return out


def outcomes_in_use(raw: object) -> tuple[list[BusinessOutcome], bool]:
    """What the extraction offers for this agent, and whether it is the starting set."""
    own = stored_outcomes(raw)
    if own is None:
        return list(STARTING_OUTCOMES), True
    return own, False


@dataclass(frozen=True, slots=True)
class OutcomeDraft:
    """One outcome as an owner sends it: `key` names one already on the agent, or None."""

    key: str | None
    label: str
    meaning: str
    lead_status: LeadMove


def _invalid(code: str, detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code=code,
        title="These outcomes cannot be saved",
        detail=detail,
        remediation=(
            "Give each outcome a short, different name and choose how far it moves the lead."
        ),
    )


def with_keys(
    items: Sequence[OutcomeDraft], *, current: Sequence[BusinessOutcome]
) -> list[BusinessOutcome]:
    """The owner's list as outcomes. A known key is kept, so past calls still name it; a new
    or unknown one gets a key from its label. Raises a 422 the owner can act on."""
    known = {o.key for o in current}
    taken = {i.key for i in items if i.key in known}
    out: list[BusinessOutcome] = []
    for item in items:
        key = item.key if item.key in known else outcome_key(item.label, taken)
        if key is None:
            raise _invalid(
                "call_outcome_label_invalid",
                "Each outcome needs a name with at least one letter.",
            )
        taken.add(key)
        try:
            out.append(
                BusinessOutcome(
                    key=key, label=item.label, meaning=item.meaning, lead_status=item.lead_status
                )
            )
        except ValidationError as exc:
            raise _invalid(
                "call_outcome_invalid",
                "One of the outcomes could not be saved: check its name and meaning.",
            ) from exc
    problems = outcome_problems(out)
    if problems:
        raise _invalid("call_outcomes_invalid", " ".join(problems))
    return out


_AGENT_COLUMNS: Final = (
    "SELECT id, name, direction, status, business_outcomes, business_outcomes_draft FROM agents "
)


def _agent_row(r: Sequence[Any]) -> dict[str, Any]:
    outcomes, starting = outcomes_in_use(r[4])
    return {
        "id": UUID(str(r[0])),
        "name": str(r[1]),
        "direction": str(r[2]),
        "status": str(r[3]),
        "outcomes": outcomes,
        "starting": starting,
        "draft": None if r[5] is None else str(r[5]),
    }


async def agents_with_outcomes(session: AsyncSession) -> list[dict[str, Any]]:
    """Every agent that is not deleted, with the outcomes its calls are read against."""
    rows = (
        await session.execute(
            text(_AGENT_COLUMNS + "WHERE deleted_at IS NULL ORDER BY created_at, id LIMIT :limit"),
            {"limit": MAX_AGENTS},
        )
    ).all()
    return [_agent_row(r) for r in rows]


async def agent_with_outcomes(session: AsyncSession, agent_id: UUID) -> dict[str, Any]:
    """One agent's row, as `agents_with_outcomes` renders it; 404 when not in reach."""
    row = (
        await session.execute(
            text(_AGENT_COLUMNS + "WHERE id = :aid AND deleted_at IS NULL"), {"aid": agent_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _agent_row(row)


async def save_outcomes(
    session: AsyncSession, *, agent_id: UUID, items: Sequence[OutcomeDraft]
) -> list[BusinessOutcome]:
    """Replace one agent's outcomes with the owner's list. 404 for an agent not in reach."""
    row = (
        await session.execute(
            text(
                "SELECT business_outcomes FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    outcomes = with_keys(items, current=stored_outcomes(row[0]) or list(STARTING_OUTCOMES))
    await session.execute(
        text(
            "UPDATE agents SET business_outcomes = CAST(:outcomes AS jsonb), updated_at = now() "
            "WHERE id = :aid"
        ),
        {"aid": agent_id, "outcomes": dump_outcomes(outcomes)},
    )
    return outcomes


def dump_outcomes(outcomes: Sequence[BusinessOutcome]) -> str:
    return json.dumps([o.model_dump() for o in outcomes])


async def queue_draft(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> bool:
    """Queue the agent's one AI draft in the caller's transaction; False when it was queued
    before or the agent already has outcomes of its own. Compare-and-swap from NULL, so two
    callers racing queue it once."""
    claimed = (
        await session.execute(
            text(
                "UPDATE agents SET business_outcomes_draft = 'queued', updated_at = now() "
                "WHERE id = :aid AND business_outcomes_draft IS NULL "
                "AND business_outcomes IS NULL AND deleted_at IS NULL RETURNING id"
            ),
            {"aid": agent_id},
        )
    ).first()
    if claimed is None:
        return False
    await enqueue_outbox(
        session,
        job=DRAFT_JOB,
        payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
    )
    return True


__all__ = [
    "DRAFT_JOB",
    "OutcomeDraft",
    "agent_with_outcomes",
    "agents_with_outcomes",
    "dump_outcomes",
    "outcomes_in_use",
    "queue_draft",
    "save_outcomes",
    "stored_outcomes",
    "with_keys",
]
