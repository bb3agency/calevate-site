"""Pip writes the outcome of each step that has none, for one campaign or inbound line (D-1036).

Queued by `campaigns/step_outcomes.queue_after_save` and by the hourly sweep below. One answer
on the account's dashboard AI ladder (`script_assist.ask_json`), written from each missing
step's own name, instruction, lines and procedure, the holder's main task and aims, what is
known about the business (`lead_fields_draft.business_context`) and the sources the holder is
written from (`company_training_draft.knowledge_words`, read as onboarding reads documents:
`first_run.documents_block`). Everything sent is redacted (D-127 G-1).

GROUNDED OR NOT KEPT. Each outcome comes with a word-for-word quote of the material it rests
on, which the CODE must find there (`campaign_script_ask.quoted_in`), and every figure in it
must be one the material has, so an outcome that invents a fact is dropped rather than saved
(company training's rule, `company_training_draft`). An outcome that names a technology
company the material does not is dropped too (D-679: the owner reads it).

NEVER OVER THE OWNER. Only steps with no outcome get one; an outcome already there, the
owner's or Pip's, is never touched. The save is a compare-and-set on the script as it was
read (a line's `version`, a campaign's script itself, which has no version), under the
holder's row lock, so an owner's save made while Pip wrote wins and its own pass follows.
The save is the holder's own column write, not `save_script`, because that would queue this
pass again; the length check it makes (`script_builder.refuse_job_if_too_long`) is made here.
A live line or a campaign holding its engine agent is then put live, as an owner's save is.

Metered as a script draft (hard rule 7), in the transaction that saves.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import (
    STEP_OUTCOME_MAX,
    CallScript,
    ConversationStage,
    StepOutcome,
    stage_steps,
)
from sqlalchemy import text

from apps.api.agents import agent_pass
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns.step_outcomes import (
    DEBOUNCE_S,
    SLOTS,
    HolderKind,
    missing_steps,
    table_of,
)
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.crm import assist as crm_assist
from apps.api.db.session import admin_session, tenant_session
from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
from apps.api.tenancy.business_copy import provider_words
from apps.workers.campaign_script_ask import quoted_in
from apps.workers.company_training_draft import figures_in, knowledge_words
from apps.workers.first_run import documents_block
from apps.workers.fleet_walk import WalkBudget, resumed_walk
from apps.workers.lead_fields_draft import business_context
from apps.workers.opening_notices import put_holder_live
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json
from apps.workers.script_proposal import PROPOSAL_REQUEST_TIMEOUT_S

log = get_logger(__name__)

#: `campaigns/step_outcomes.JOB`; a literal here so `scripts/check_job_wiring` can read this
#: file's own deferred enqueue (`_defer`).
JOB_NAME: Final = "write_step_outcomes"
SWEEP_JOB: Final = "sweep_step_outcomes"
#: Room for twelve one-sentence outcomes and their quotes, with headroom for a repair.
MAX_TOKENS: Final = 4_000
_QUOTE_MAX: Final = 300

#: The sweep's cadence and bounds. Hourly at :47, a minute no other fleet walk takes. Each
#: holder it queues is one model call, so `HOLDERS_PER_TICK` is the most it spends in an hour;
#: the next tick resumes after the last account reached, so a backlog drains in turn.
SWEEP_MINUTE: Final = 47
HOLDERS_PER_TICK: Final = 50
SWEEP_BUDGET: Final = timedelta(seconds=120)
#: A pass that failed is tried again by the sweep after this long; one whose
#: inputs did not change since costs nothing (`_digest`).
RETRY_MINUTES: Final = 6 * 60

ASK: Final = (
    "You write the outcome of each step listed under STEPS WITHOUT AN OUTCOME in a phone "
    "agent's call script. An outcome is one plain English sentence saying what is true once "
    "that step is done, checkable from what the person says on the call (for example: The "
    "person says the app is open on their phone). The agent reaches it however the call goes; "
    "the step's scenarios are examples of how. Write each from that step's own name, "
    "instruction, lines and procedure, with the main task and the goal; the other steps and "
    "their outcomes are listed so each outcome covers only its own step. Use only what the "
    "material states: never add a price, product, place, time, promise or detail it does not "
    "state, and keep the names of products, screens and buttons exactly as written. For each "
    "outcome, put under quote a short passage copied word for word from that step's material "
    "or the main task that the outcome rests on. At most 300 characters per outcome. No "
    "markdown, no emoji. Return one entry per listed step."
)

_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "step_outcomes",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "outcomes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "outcome": {"type": "string"},
                            "quote": {"type": "string"},
                        },
                        "required": ["step", "outcome", "quote"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["outcomes"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class Holder:
    """One campaign or line as the pass read it."""

    kind: HolderKind
    id: UUID
    script: CallScript
    #: The script column exactly as stored, for the campaign's compare-and-set.
    stored: Any
    #: A line's version, for its compare-and-set; None for a campaign.
    version: int | None
    main_task: str
    aims: str
    source_ids: tuple[UUID, ...]


def _clean(value: str) -> str:
    return redact(" ".join(value.split())).text


def step_material(stages: list[ConversationStage]) -> str:
    """One step's scenarios as the model reads them: name, instruction, how it sounds, its
    procedure, its lines, its questions and answers and its ways out."""
    parts: list[str] = []
    for stage in stages:
        parts.append(f"Scenario: {stage.name}")
        parts.append(f"Instruction: {stage.instruction}")
        if stage.sounds_like:
            parts.append(f"How it sounds: {stage.sounds_like}")
        for item in stage.procedure:
            wait = f" (wait for: {item.wait_for})" if item.wait_for else ""
            parts.append(f"Procedure: {item.action}{wait}")
        for language, line in stage.scripts.items():
            parts.append(f"Line ({language}): {line}")
        for qa in stage.qa:
            parts.append(f"If asked: {qa.question} Answer: {qa.answer}")
        for branch in stage.branches:
            parts.append(f"Way out when: {branch.when}")
    return "\n".join(_clean(p) for p in parts if p.strip())


def _by_step(script: CallScript) -> dict[int, list[ConversationStage]]:
    out: dict[int, list[ConversationStage]] = defaultdict(list)
    for stage, step in zip(script.stages, stage_steps(script.stages), strict=True):
        out[step].append(stage)
    return dict(out)


def request_text(holder: Holder, *, business: str, documents: str) -> tuple[str, str]:
    """(the request, the material a quote must be found in), both redacted."""
    script = holder.script
    steps = _by_step(script)
    missing = missing_steps(script)
    said = {o.step: o.outcome for o in script.step_outcomes}
    flow = [
        f"Step {n}: {', '.join(s.name for s in stages)}"
        + (f" (outcome: {said[n]})" if n in said else "")
        for n, stages in sorted(steps.items())
    ]
    blocks = [f"STEP {n}\n{step_material(steps[n])}" for n in missing]
    main = _clean(holder.main_task) or "Not written."
    aims = _clean(holder.aims)
    material = "\n\n".join([main, aims, *blocks, documents])
    request = "\n\n".join(
        part
        for part in [
            f"MAIN TASK\n{main}",
            f"GOAL\n{aims}" if aims else "",
            f"THE BUSINESS\n{business}" if business else "",
            "THE CALL'S STEPS\n" + "\n".join(_clean(line) for line in flow),
            "STEPS WITHOUT AN OUTCOME\n" + "\n\n".join(blocks),
            documents,
        ]
        if part
    )
    return request, material


def accepted(raw: dict[str, Any], *, missing: list[int], material: str) -> dict[int, str]:
    """The outcomes the code can stand behind, by step: for a step without one, one sentence
    of the allowed length, its quote found in the material, no figure and no provider name
    the material lacks."""
    figures = figures_in(material)
    named = provider_words(material)
    out: dict[int, str] = {}
    rows = raw.get("outcomes")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        step, outcome, quote = row.get("step"), row.get("outcome"), row.get("quote")
        if not isinstance(step, int) or step not in missing or step in out:
            continue
        if not isinstance(outcome, str) or not isinstance(quote, str):
            continue
        sentence = " ".join(outcome.split())
        if not sentence or len(sentence) > STEP_OUTCOME_MAX:
            continue
        if not quoted_in(" ".join(quote.split())[:_QUOTE_MAX], material):
            continue
        if not figures_in(sentence) <= figures or not provider_words(sentence) <= named:
            continue
        out[step] = sentence
    return out


def with_outcomes(script: CallScript, written: dict[int, str]) -> CallScript:
    """`script` with an outcome for each written step that still has none; every outcome
    already there is kept as it is."""
    have = {o.step for o in script.step_outcomes}
    added = [StepOutcome(step=n, outcome=t) for n, t in written.items() if n not in have]
    if not added:
        return script
    return CallScript.model_validate(
        script.model_copy(
            update={"step_outcomes": sorted([*script.step_outcomes, *added], key=lambda o: o.step)}
        ).model_dump()
    )


def _digest(request: str) -> str:
    return hashlib.sha256(request.encode()).hexdigest()


def _holder_of(payload: dict[str, Any]) -> tuple[HolderKind, UUID]:
    if payload.get("campaign_id"):
        return "campaign", UUID(str(payload["campaign_id"]))
    return "line", UUID(str(payload["line_id"]))


async def _read(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> Holder | None:
    from apps.api.kb.picks import CAMPAIGN_PICKS, LINE_PICKS, read_picks

    async with tenant_session(tenant_id) as session:
        if kind == "campaign":
            row = (
                await session.execute(
                    text(
                        "SELECT script, main_task, purpose, goal FROM campaigns "
                        "WHERE id = :h AND archived_at IS NULL"
                    ),
                    {"h": holder_id},
                )
            ).first()
            version = None
        else:
            row = (
                await session.execute(
                    text(
                        "SELECT script, main_task, NULL AS purpose, NULL AS goal, version "
                        "FROM inbound_lines WHERE id = :h AND archived_at IS NULL"
                    ),
                    {"h": holder_id},
                )
            ).first()
            version = None if row is None else int(row.version)
        if row is None or not row.script:
            return None
        picks = await read_picks(
            session, CAMPAIGN_PICKS if kind == "campaign" else LINE_PICKS, [holder_id]
        )
    script = CallScript.model_validate(row.script)
    aims = [str(a) for a in (row.purpose, row.goal, script.goal, script.outbound_purpose) if a]
    return Holder(
        kind=kind,
        id=holder_id,
        script=script,
        stored=row.script,
        version=version,
        main_task=str(row.main_task or ""),
        aims="\n".join(aims),
        source_ids=tuple(picks[holder_id]),
    )


async def _finish(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID, state: str, digest: str | None = None
) -> None:
    """Close the pass (or start the next one asked for meanwhile), remembering what it read
    when the same read would only fail again."""
    async with tenant_session(tenant_id) as session:
        if digest is not None:
            await session.execute(
                text(f"UPDATE {table_of(kind)} SET step_outcomes_inputs = :d WHERE id = :h"),
                {"d": digest, "h": holder_id},
            )
        await agent_pass.finish(
            session, SLOTS[kind], tenant_id=tenant_id, row_id=holder_id, state=state
        )


async def _due(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> datetime | None:
    """When a waiting pass may start, if that is still ahead: `DEBOUNCE_S` after the last
    save that asked for it."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    f"SELECT step_outcomes_state, step_outcomes_at FROM {table_of(kind)} "
                    "WHERE id = :h"
                ),
                {"h": holder_id},
            )
        ).first()
    if row is None or row[0] != "queued" or row[1] is None:
        return None
    due: datetime = row[1] + timedelta(seconds=DEBOUNCE_S)
    return due if due > datetime.now(UTC) else None


async def _defer(payload: dict[str, Any], holder_id: UUID, due: datetime) -> None:
    """Run again once the burst is over; keyed by the due instant, so each push-back is its
    own delivery and a repeated one is deduped by arq."""
    await enqueue(
        JOB_NAME,
        payload,
        job_id=job_id_for(JOB_NAME, str(holder_id), due.isoformat()),
        _defer_until=due,
    )


async def write_step_outcomes(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    kind, holder_id = _holder_of(payload)
    due = await _due(tenant_id, kind, holder_id)
    if due is not None:
        await _defer(payload, holder_id, due)
        return "deferred"
    async with tenant_session(tenant_id) as session:
        claimed, previous = await agent_pass.claim(session, SLOTS[kind], row_id=holder_id)
    if not claimed:
        return "not_queued"
    try:
        return await _run(tenant_id, kind, holder_id, previous)
    except Exception:
        log.exception("step_outcomes_crashed", extra={"kind": kind, "holder_id": str(holder_id)})
        await _finish(tenant_id, kind, holder_id, "failed")
        return "failed"


async def _run(tenant_id: UUID, kind: HolderKind, holder_id: UUID, previous: str | None) -> str:
    holder = await _read(tenant_id, kind, holder_id)
    missing = missing_steps(holder.script) if holder is not None else []
    if holder is None or not missing:
        await _finish(tenant_id, kind, holder_id, "done")
        return "complete"
    async with tenant_session(tenant_id) as session:
        allowed = await account_content_may_reach_models(session, tenant_id=tenant_id)
    if not allowed:
        await _finish(tenant_id, kind, holder_id, "skipped")
        return "skipped"
    async with tenant_session(tenant_id) as session:
        words = await knowledge_words(session, only=holder.source_ids or None)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    business, _vertical = await business_context(tenant_id, include_type=False)
    documents = documents_block(words, budget=KNOWLEDGE_DOCUMENT_CHARS)
    request, material = request_text(holder, business=business, documents=documents)
    digest = _digest(request)
    if previous == digest:
        await _finish(tenant_id, kind, holder_id, "done")
        return "unchanged"

    def parse(raw: dict[str, Any]) -> dict[int, str] | None:
        return accepted(raw, missing=missing, material=material) or None

    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    try:
        answer: JsonAnswer[dict[int, str]] = await ask_json(
            request,
            ASK,
            parse=parse,
            azure_format=_FORMAT,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling or quota.platform_paused,
            max_tokens=MAX_TOKENS,
            temperature=0.2,
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        log.info("step_outcomes_refused", extra={"reason": refused.code, "kind": kind})
        # A refusal that can pass (no answer this time) is tried again; one that would only
        # repeat on the same script waits for the script to change.
        await _finish(
            tenant_id,
            kind,
            holder_id,
            "failed",
            digest=None if refused.kind == "transient" else digest,
        )
        return refused.code
    result = await _save(tenant_id, holder, answer, digest)
    if result == "saved":
        await put_holder_live(tenant_id, kind, holder_id, event="step_outcomes_not_live")
    log.info(
        "step_outcomes_written",
        extra={
            "kind": kind,
            "holder_id": str(holder_id),
            "missing": len(missing),
            "written": len(answer.value),
            "result": result,
        },
    )
    return result


async def _save(
    tenant_id: UUID, holder: Holder, answer: JsonAnswer[dict[int, str]], digest: str
) -> str:
    """Meter, then save the outcomes onto the script as it was read: `saved`, `stale` (the
    script changed meanwhile; its own pass follows) or `too_long`."""
    from apps.api.agents import script_builder

    kind, table = holder.kind, table_of(holder.kind)
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    script = with_outcomes(holder.script, answer.value)
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=feature,
        )
        await session.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :h FOR UPDATE"), {"h": holder.id}
        )
        try:
            async with session.begin_nested():
                await script_builder.refuse_job_if_too_long(
                    session, kind=kind, tenant_id=tenant_id, job_id=holder.id, script=script
                )
        except ProblemError as refused:
            log.info("step_outcomes_too_long", extra={"kind": kind, "reason": refused.code})
            await session.execute(
                text(f"UPDATE {table} SET step_outcomes_inputs = :d WHERE id = :h"),
                {"d": digest, "h": holder.id},
            )
            await agent_pass.finish(
                session, SLOTS[kind], tenant_id=tenant_id, row_id=holder.id, state="failed"
            )
            return "too_long"
        if kind == "campaign":
            written = await session.execute(
                text(
                    "UPDATE campaigns SET script = CAST(:s AS jsonb), "
                    "step_outcomes_inputs = :d, updated_at = now() "
                    "WHERE id = :h AND script = CAST(:old AS jsonb) RETURNING id"
                ),
                {
                    "s": script.model_dump_json(),
                    "d": digest,
                    "h": holder.id,
                    "old": json.dumps(holder.stored),
                },
            )
        else:
            written = await session.execute(
                text(
                    "UPDATE inbound_lines SET script = CAST(:s AS jsonb), "
                    "version = version + 1, step_outcomes_inputs = :d, updated_at = now() "
                    "WHERE id = :h AND version = :v RETURNING id"
                ),
                {"s": script.model_dump_json(), "d": digest, "h": holder.id, "v": holder.version},
            )
        saved = written.first() is not None
        await agent_pass.finish(
            session, SLOTS[kind], tenant_id=tenant_id, row_id=holder.id, state="done"
        )
    return "saved" if saved else "stale"


_SCAN_SQL: Final = (
    "SELECT scanned_tenant_id, kind, holder_id FROM step_outcome_scan(:stale, :retry)"
)


async def sweep_step_outcomes(ctx: dict[str, Any]) -> str:
    """Queue a pass for each open holder lacking an outcome that no pass has covered: scripts
    saved before outcomes were Pip's, a pass that died, and accounts that since turned Pip on.
    One admin read of the worklist (`step_outcome_scan`, a per-tenant loop inside Postgres
    under each tenant's own policy), then one tenant session per account with work, at most
    `HOLDERS_PER_TICK` holders, resuming after the last account reached."""
    del ctx
    async with admin_session() as directory:
        rows = (
            await directory.execute(
                text(_SCAN_SQL), {"stale": agent_pass.STALE_MINUTES, "retry": RETRY_MINUTES}
            )
        ).all()
    holders: dict[UUID, list[tuple[HolderKind, UUID]]] = defaultdict(list)
    for tenant, kind, holder in rows:
        holders[UUID(str(tenant))].append(("campaign" if kind == "campaign" else "line", holder))
    queued = 0
    budget = WalkBudget(SWEEP_BUDGET)
    async for tenant_id in resumed_walk(SWEEP_JOB, list(holders), budget):
        if queued >= HOLDERS_PER_TICK:
            break
        async with tenant_session(tenant_id) as session:
            if not await account_content_may_reach_models(session, tenant_id=tenant_id):
                continue
            for kind, holder_id in holders[tenant_id][: HOLDERS_PER_TICK - queued]:
                queued += await agent_pass.queue(
                    session, SLOTS[kind], tenant_id=tenant_id, row_id=UUID(str(holder_id))
                )
    log.info(
        "step_outcomes_sweep",
        extra={"holders": len(rows), "tenants": len(holders), "queued": queued},
    )
    return f"holders={len(rows)} queued={queued}"


__all__ = [
    "HOLDERS_PER_TICK",
    "JOB_NAME",
    "SWEEP_JOB",
    "SWEEP_MINUTE",
    "accepted",
    "request_text",
    "step_material",
    "sweep_step_outcomes",
    "with_outcomes",
    "write_step_outcomes",
]
