"""Each business's own steps for the ready-made jobs, written once from what it sells.

A job's plan (`trade_playbooks`) is the same for every business of a type: "Find out what
they need", "Offer a booking". The owner choosing a job should see the steps of THEIR call,
so the model rewrites each step for the business: a title in its words and one line of what
that step is about for it ("Ask which crop and what is wrong"). It rewrites, it does not
redesign: the count, order, instruction and "done when" of every step stay the platform's,
because those carry the calling rules (take no for an answer, one fact in the value step, a
read-back the person can check). The written plan is what the preview shows, what the new
agent's first script names its sections, and what the script writer follows.

Stored on `organizations.starter_plans` as `{job: [{"title", "focus"}, ...]}`, written by
`workers/starter_steps` whenever what the business sells changes. A plan that does not fit
its job's shape is ignored, never repaired, and the platform's steps are shown instead.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import STAGE_DETAIL_MAX
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox_once

#: The ARQ job that writes the plans (`workers/starter_steps`).
WRITE_STEPS_JOB: Final = "write_starter_steps"

#: A title is a line on the "pick a job" screen and a section name: a few words.
STEP_TITLE_MAX: Final = 48
#: One clause of what the step is about for this business, appended to its instruction.
STEP_FOCUS_MAX: Final = 140


@dataclass(frozen=True, slots=True)
class PlanStep:
    title: str
    focus: str = ""


Plan = tuple[PlanStep, ...]


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit].strip() if isinstance(value, str) else ""


def clean_plan(raw: Any, *, steps: int) -> Plan | None:
    """`raw` as a plan for a job of `steps` steps, or None when it is not one: the wrong
    count, a blank title, or two steps with one title."""
    if not isinstance(raw, list) or len(raw) != steps:
        return None
    plan: list[PlanStep] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None
        title = _clean(item.get("title"), STEP_TITLE_MAX)
        if not title or title.casefold() in seen:
            return None
        seen.add(title.casefold())
        plan.append(PlanStep(title=title, focus=_clean(item.get("focus"), STEP_FOCUS_MAX)))
    return tuple(plan)


def plans_from_row(raw: Any, shapes: Mapping[str, int]) -> dict[str, Plan]:
    """The stored plans that still fit their job's shape (`shapes`: job to step count)."""
    if not isinstance(raw, dict):
        return {}
    plans: dict[str, Plan] = {}
    for job, steps in shapes.items():
        plan = clean_plan(raw.get(job), steps=steps)
        if plan is not None:
            plans[job] = plan
    return plans


def plans_to_json(plans: Mapping[str, Plan]) -> str:
    return json.dumps(
        {job: [{"title": s.title, "focus": s.focus} for s in plan] for job, plan in plans.items()}
    )


def with_focus(instruction: str, focus: str) -> str:
    """The platform's instruction with the business's focus after it, when it fits the
    section's limit; past it, the instruction alone."""
    if not focus:
        return instruction
    combined = f"{instruction} For this business: {focus}"
    return combined if len(combined) <= STAGE_DETAIL_MAX else instruction


async def stored_plans(
    session: AsyncSession, *, tenant_id: UUID, shapes: Mapping[str, int]
) -> dict[str, Plan]:
    raw = (
        await session.execute(
            text("SELECT starter_plans FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar_one_or_none()
    return plans_from_row(raw, shapes)


async def maybe_write_starter_steps(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Queue the steps written for this business once it says what it sells, again each
    time that changes. Deduped per list of what it sells, so one change asks once."""
    row = (
        await session.execute(
            text(
                "SELECT coalesce(jsonb_array_length(services), 0), md5(services::text) "
                "FROM business_profiles WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or not row[0]:
        return False
    queued = await enqueue_outbox_once(
        session,
        job=WRITE_STEPS_JOB,
        payload={"tenant_id": str(tenant_id), "services": str(row[1])},
        dedupe_key=f"starter-steps:{tenant_id}:{row[1]}",
    )
    return queued is not None


__all__ = [
    "STEP_FOCUS_MAX",
    "STEP_TITLE_MAX",
    "WRITE_STEPS_JOB",
    "Plan",
    "PlanStep",
    "clean_plan",
    "maybe_write_starter_steps",
    "plans_from_row",
    "plans_to_json",
    "stored_plans",
    "with_focus",
]
