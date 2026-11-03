"""Write each ready-made job's steps for ONE business, from what it says about itself.

The owner picking a job ("Answer my calls", "Call new leads instantly", "Run calling
campaigns") should see the steps of their own call before creating the agent, not the same
six lines every business sees. This asks the model to rewrite each step of each job for the
business: a title in its words and one line of what the step is about for it. Count and
order are the platform's, and so is every step's instruction and "done when"
(`agents/starter_plans`), so the calling rules hold whatever the model writes.

Queued by `agents/starter_plans.maybe_write_starter_steps` whenever what the business sells
changes (and, for accounts that existed before, by migration a4c8e2f1b7d3). One request on
the dashboard AI ladder (`script_assist.ask_json`), no retry: a refusal leaves the platform's
steps showing, and the next change asks again. What the model sees is the business's own
redacted words about itself (`lead_fields_draft.business_context`), never a caller, and
nothing of it is logged. Metered at our cost under `ASSIST_FEATURE_LEAD_FIELDS` and
absorbed, like the core-detail names beside it.

The plans are stored only while the list of what the business sells is the one they were
written for: a slower answer to an older list never overwrites a newer one.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.starter_plans import (
    STEP_FOCUS_MAX,
    STEP_TITLE_MAX,
    Plan,
    PlanStep,
    clean_plan,
    plans_to_json,
)
from apps.api.agents.starters import CATALOGUE, JOB_LABEL, STARTER_JOBS, StarterJob, vertical_of
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.models import ASSIST_FEATURE_LEAD_FIELDS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.tenancy.business_copy import screen_text_problems
from apps.workers.lead_fields_draft import business_context
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

#: The ARQ name; `agents/starter_plans.WRITE_STEPS_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "write_starter_steps"

WRITE_TIMEOUT_S: Final = 40.0
# The script writer's budget: seventeen steps of JSON plus a reasoning model's thinking
# outgrew 1400 on a real account, and a cut-off answer is no answer.
WRITE_MAX_TOKENS: Final = 4096

#: Pinned by `tests/starter_steps_test.py`: same steps, the business's words.
SYSTEM_PROMPT: Final = (
    "An AI phone agent for a small Indian business follows a fixed plan of steps on each "
    "kind of call. Rewrite each step for THIS business so its owner recognises their own "
    "call: a title in their trade's plain English words, and a focus, one short clause of "
    "what that step is about for this business (what to ask, what to offer). Keep every "
    "step, in the same order, doing the same thing: never add, drop, merge or reorder "
    f"steps. Title: 2 to 6 words, at most {STEP_TITLE_MAX} characters, no two the same in a "
    f"job. Focus: at most {STEP_FOCUS_MAX} characters, or empty when the step needs none. "
    "Use only what the business says about itself: never invent a product, price, offer, "
    "discount, place, person or time, and never write what the agent says aloud. "
    "Plain words: no symbols or markdown, and keep the plan's own word for a booking. "
    "Return ONLY JSON with one key per job, each a list of "
    '{"title": str, "focus": str} in step order.'
)


def _jobs_brief(vertical: str | None) -> str:
    trade = vertical_of(vertical)
    blocks = []
    for job in STARTER_JOBS:
        steps = CATALOGUE[(trade, job)].steps
        lines = [f'Job "{job}" ({JOB_LABEL[job]}), {len(steps)} steps:']
        lines += [f"{i}. {s.title}: {s.instruction}" for i, s in enumerate(steps, 1)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _schema() -> dict[str, Any]:
    step = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "focus": {"type": "string"}},
        "required": ["title", "focus"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {job: {"type": "array", "items": step} for job in STARTER_JOBS},
        "required": list(STARTER_JOBS),
        "additionalProperties": False,
    }


def _kept(job: StarterJob, plan: Plan, *, trade: str) -> Plan | None:
    """`plan` with any line that breaks the rules of text a client reads
    (`business_copy.screen_text_problems`) put back: a title to the platform's for that step,
    a focus to none. One "appointment" in a property office's seventeen steps costs that one
    title, not the whole answer. None when a put-back title collides with another."""
    clinic = trade == "clinic"
    ours = CATALOGUE[(trade, job)].steps
    kept: list[PlanStep] = []
    for i, (step, platform) in enumerate(zip(plan, ours, strict=True)):
        title = step.title
        if screen_text_problems(f"{job}.{i}.title", title, clinic=clinic):
            title = platform.title
        focus = step.focus
        if screen_text_problems(f"{job}.{i}.focus", focus, clinic=clinic):
            focus = ""
        kept.append(PlanStep(title=title, focus=focus))
    titles = [s.title.casefold() for s in kept]
    return tuple(kept) if len(set(titles)) == len(titles) else None


def plans_from_model(raw: dict[str, Any], *, vertical: str | None) -> dict[str, Plan] | None:
    """Every job's plan, cleaned; None unless all of them fit their job's shape, so the
    ladder's next leg gets its chance rather than half a set being stored."""
    trade = vertical_of(vertical)
    plans: dict[str, Plan] = {}
    for job in STARTER_JOBS:
        plan = clean_plan(raw.get(job), steps=len(CATALOGUE[(trade, job)].steps))
        kept = None if plan is None else _kept(job, plan, trade=trade)
        if kept is None:
            return None
        plans[job] = kept
    return plans


async def _store(tenant_id: UUID, services: str, answer: JsonAnswer[dict[str, Plan]]) -> bool:
    """Store the plans and meter the answer in ONE transaction, only while what the business
    sells is still the list they were written for."""
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "UPDATE organizations o SET starter_plans = CAST(:plans AS jsonb) "
                    "FROM business_profiles bp WHERE o.id = :tid AND bp.tenant_id = o.id "
                    "AND md5(bp.services::text) = :services RETURNING o.id"
                ),
                {"tid": tenant_id, "plans": plans_to_json(answer.value), "services": services},
            )
        ).first()
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=ASSIST_FEATURE_LEAD_FIELDS
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=ASSIST_FEATURE_LEAD_FIELDS,
            model=answer.model,
        )
    return stored is not None


async def write_starter_steps(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Ask the model once for every job's steps, store what came back."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    services = str(payload["services"])
    try:
        description, vertical = await business_context(tenant_id)
        async with tenant_session(tenant_id) as session:
            tenant_leg = await account_assist_leg(session)
        try:
            answer = await ask_json(
                f"{description}\n\nThe plan, job by job:\n{_jobs_brief(vertical)}",
                SYSTEM_PROMPT,
                parse=lambda raw: plans_from_model(raw, vertical=vertical),
                azure_format={
                    "type": "json_schema",
                    "json_schema": {"name": "starter_steps", "strict": True, "schema": _schema()},
                },
                tenant_leg=tenant_leg,
                max_tokens=WRITE_MAX_TOKENS,
                temperature=0.3,
                timeout_s=WRITE_TIMEOUT_S,
                health_leg="lead_fields",
            )
        except ProblemError as refused:
            async with tenant_session(tenant_id) as session:
                await crm_assist.meter_refusal(
                    session,
                    tenant_id=tenant_id,
                    refusal=refused,
                    feature=ASSIST_FEATURE_LEAD_FIELDS,
                )
            log.info(
                "starter_steps_refused", extra={"tenant_id": str(tenant_id), "reason": refused.code}
            )
            return "refused"
        stored = await _store(tenant_id, services, answer)
    except Exception:
        log.exception("starter_steps_crashed", extra={"tenant_id": str(tenant_id)})
        return "failed"
    log.info("starter_steps_written", extra={"tenant_id": str(tenant_id), "stored": stored})
    return "written" if stored else "superseded"


__all__ = ["JOB_NAME", "SYSTEM_PROMPT", "plans_from_model", "write_starter_steps"]
