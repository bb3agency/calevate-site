"""Runs one queued set of test conversations, and prepares an auto-improve proposal
(`apps/api/agents/test_conversations.py` describes the loop, D-724).

`run_agent_test_conversations`: claim the queued run, write this run's callers with the
dashboard AI (or fall back to the standard set), talk to the live agent through the engine's
test chat with a pause between messages, judge every conversation with the AI and the hard
checks, and store the results worst first. One attempt: a run that cannot finish is marked
failed with a machine code and the owner may start another.

`improve_agent_test_run`: the auto-improve step, queued by a finished run with failures
when its owner asked for it. It writes the proposal onto the run for the owner to review;
it never changes the script and never puts anything live.

Generation, judging and improving are separate metered AI requests (`meter_assist`, one
feature name each). The routes refuse a new run or proposal at the allowance ceiling; a
run that crosses it part-way passes the ceiling to the ladder, which then answers on the
platform's standby model as every dashboard assist does, so the client's allowance stops
moving at that point.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Final, cast
from uuid import UUID

import httpx
from calevate_shared.call_script import upgrade_to_v2
from calevate_shared.engine import VoiceEngine
from sqlalchemy import text

from apps.api.agents import script_builder
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.service import AgentRow, in_call_model
from apps.api.agents.specimen_scenarios import specimen_scenarios
from apps.api.agents.test_conversations import (
    ASSIST_FEATURE_TEST_GENERATE,
    ASSIST_FEATURE_TEST_IMPROVE,
    ASSIST_FEATURE_TEST_JUDGE,
    IMPROVE_JOB,
    MAX_GENERATED,
    MAX_SAVED,
    MAX_TURNS,
    PROBES,
    RUN_JOB,
    AgentBrief,
    Judged,
    Scenario,
    Turn,
    decide,
    ensure_probes,
    get_run,
    load_brief,
    needs_improving,
    queue_improvement,
    standard_scenarios,
    store_improve_failure,
    store_improvement,
    wants_auto_improvement,
    within_budget,
    worst_first,
)
from apps.api.agents.test_window import send_test_message
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HoldsCatalogue
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.test_chat import RunsTestChat, TestChatTool
from apps.workers.agent_test_ai import (
    conversation_text,
    generate_scenarios,
    improvement_record,
    judge_conversations,
    judge_leg,
    judge_order,
    model_family,
    propose_improvement,
)
from apps.workers.extraction import TenantModelLeg
from apps.workers.script_assist import JsonAnswer

log = get_logger(__name__)

#: The ARQ names; `agents/test_conversations` is the enqueue side's spelling.
JOB_NAME: Final = RUN_JOB
IMPROVE_JOB_NAME: Final = IMPROVE_JOB

#: Seconds between messages: the engine answers 429 to "messages sent faster than a person
#: types" (test-chat.md:438-445) without saying how fast that is.
PAUSE_S: Final = 4.0
#: The most failures of the previous run asked again on "Test again".
MAX_RETESTED: Final = 6

#: Why AI help could not do its part, by the refusal's code (`extraction.assist_unavailable`
#: answers `assist_<reason>`), in the owner's words with what to do. The log line beside each
#: (`agent_tests_standard_set`, `agent_tests_not_judged`) carries the same code for us.
_AI_REFUSAL: Final[dict[str, str]] = {
    "assist_quota_exhausted": (
        "this month's AI help allowance is used up. Add credit, or wait for next month."
    ),
    "assist_provider_unavailable": (
        "the AI that does this did not answer in time. Test again in a few minutes; if it "
        "keeps happening, contact us."
    ),
    "assist_no_credential": (
        "AI help is not switched on for your account yet. Ask your Calevate team to switch it on."
    ),
    "assist_tenant_provider_unsupported": (
        "AI help is not switched on for your account yet. Ask your Calevate team to switch it on."
    ),
}
_AI_REFUSAL_OTHER: Final = "AI help was not available. Test again in a few minutes."


def not_written_note(code: str) -> str:
    """The run's note when the standard callers ran instead of new ones."""
    why = _AI_REFUSAL.get(code, _AI_REFUSAL_OTHER)
    return f"The standard test callers ran instead of new ones for your business, because {why}"


def not_judged_reason(code: str) -> str:
    """A result's reason when no AI could check it."""
    why = _AI_REFUSAL.get(code, _AI_REFUSAL_OTHER)
    return f"Not checked, because {why} Read the reply yourself."


#: A result the AI checker answered for the others but not for this one.
LEFT_OUT_REASON: Final = (
    "Not checked: the AI checker gave no verdict on this one. Read the reply yourself."
)


#: The fallback when the improve job fails on something that is not an AI refusal.
IMPROVE_FAILED_NOTE: Final = (
    "Suggestions could not be worked out this time. Try again in a few minutes; if it keeps "
    "happening, contact us."
)

Pause = Callable[[], Awaitable[None]]


async def _pause() -> None:
    await asyncio.sleep(PAUSE_S)


async def _meter(tenant_id: UUID, answer: JsonAnswer[Any], feature: str) -> None:
    """A completed AI step is money spent: recorded in its own transaction (crm/assist §4)."""
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=feature,
            model=answer.model,
        )


async def _allowance_used(tenant_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    return quota.at_ceiling or quota.platform_paused


async def _finish(
    tenant_id: UUID,
    run_id: UUID,
    *,
    status: str,
    results: Any,
    failure: str | None,
    note: str | None = None,
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_test_runs SET status = :status, "
                "results = CAST(:results AS jsonb), error_code = :code, note = :note, "
                "completed_at = now(), updated_at = now() WHERE id = :id AND status = 'running'"
            ),
            {
                "status": status,
                "results": json.dumps(results) if results is not None else None,
                "code": failure,
                "note": note,
                "id": run_id,
            },
        )


async def _saved_scenarios(tenant_id: UUID, agent_id: UUID) -> list[Scenario]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, title, caller_lines, expected FROM agent_test_cases "
                    "WHERE agent_id = :aid ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                {"aid": agent_id, "limit": MAX_SAVED},
            )
        ).all()
    return [
        Scenario(
            key=f"saved_{str(row[0])[-12:]}",
            title=str(row[1]),
            category="business",
            turns=tuple(str(line) for line in (row[2] or []))[:MAX_TURNS],
            expect=str(row[3]),
            source="saved",
            case_id=str(row[0]),
        )
        for row in rows
        if row[2]
    ]


def _retests(previous: list[dict[str, Any]]) -> list[Scenario]:
    out = []
    for raw in previous:
        if raw.get("verdict") not in ("needs_fix", "failed"):
            continue
        scenario = Scenario.of(raw)
        if scenario.turns:
            out.append(
                Scenario(
                    key=scenario.key,
                    title=scenario.title,
                    category=scenario.category,
                    turns=scenario.turns,
                    expect=scenario.expect,
                    probe=scenario.probe,
                    source="retest",
                    case_id=scenario.case_id,
                )
            )
    return out[:MAX_RETESTED]


async def write_scenarios(
    brief: AgentBrief,
    *,
    tenant_id: UUID,
    round_key: str,
    count: int,
    tenant_leg: TenantModelLeg | None,
) -> tuple[list[Scenario], str | None]:
    """This run's fresh callers, and a note when they are not AI-written."""
    exhausted = await _allowance_used(tenant_id)
    try:
        answer = await generate_scenarios(
            brief,
            round_key=round_key,
            count=count,
            tenant_leg=tenant_leg,
            quota_exhausted=exhausted,
        )
    except ProblemError as refused:
        log.info("agent_tests_standard_set", extra={"reason": refused.code})
        standard = standard_scenarios(brief.language, brief.direction)
        return ensure_probes(standard, brief.language, cap=count), not_written_note(refused.code)
    await _meter(tenant_id, answer, ASSIST_FEATURE_TEST_GENERATE)
    return ensure_probes(answer.value, brief.language, cap=count), answer.capability.disclosure


async def talk(
    engine: RunsTestChat,
    *,
    agent_id: UUID,
    engine_agent_ref: str,
    scenarios: list[Scenario],
    pause: Pause,
) -> list[list[Turn]]:
    """Each scenario as one conversation with the live agent, its turns in order."""
    out: list[list[Turn]] = []
    first = True
    for scenario in scenarios:
        session: str | None = None
        turns: list[Turn] = []
        for line in scenario.turns:
            if not first:
                await pause()
            first = False
            reply = await send_test_message(
                engine,
                agent_id=agent_id,
                engine_agent_ref=engine_agent_ref,
                message=line,
                session=session,
            )
            session = reply.session or session
            results = reply.tool_results or tuple(TestChatTool(name=n) for n in reply.tools)
            for tool in results:
                # What each action answered, for us: the evidence for a verdict about an
                # action (names and status words only, never the conversation).
                log.info(
                    "agent_tests_tool_used",
                    extra={
                        "agent_id": str(agent_id),
                        "scenario": scenario.key,
                        "tool": tool.name[:40],
                        "ok": tool.ok,
                        "status": tool.status,
                    },
                )
            turns.append(
                Turn(
                    said=line,
                    reply=reply.reply,
                    tools=[tool.name for tool in results],
                    statuses=[tool.status if tool.ok else "error" for tool in results],
                    cut_short=reply.failed_part_way,
                )
            )
        out.append(turns)
    return out


async def agent_in_call_model(tenant_id: UUID, agent_id: UUID, engine: VoiceEngine) -> str | None:
    """The in-call model of the agent under test, by a name that says its maker where one
    can be read: our own model's id, else the engine model's label from its catalogue. None
    for the engine's own default, whose maker is not published."""
    async with tenant_session(tenant_id) as session:
        row = (
            (
                await session.execute(
                    text("SELECT engine_model_id, engine_voice_id FROM agents WHERE id = :aid"),
                    {"aid": agent_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    model = in_call_model(cast(AgentRow, dict(row)), engine=engine)
    if model is None or model_family(model) is not None or not isinstance(engine, HoldsCatalogue):
        return model
    try:
        catalogue = await engine.read_catalogue()
    except (ProblemError, httpx.HTTPError) as unread:
        # The judge then keeps the account's leg: an unread name is an unknown family.
        log.info("agent_tests_model_unread", extra={"error": type(unread).__name__})
        return model
    return next((m.label for m in catalogue.models if m.model_id == model), model)


def judge_entry(judged: Judged | None) -> dict[str, Any]:
    """What the judge itself said about one conversation (None: it gave no verdict)."""
    if judged is None:
        return {"verdict": None, "reason": None, "fix": None}
    return {"verdict": judged.verdict, "reason": judged.reason, "fix": judged.fix}


async def judge_all(
    brief: AgentBrief,
    scenarios: list[Scenario],
    conversations: list[list[Turn]],
    *,
    tenant_id: UUID,
    tenant_leg: TenantModelLeg | None,
    agent_model: str | None = None,
    seed: str = "",
) -> tuple[dict[str, Judged], str, dict[str, dict[str, Any]]]:
    """The AI judge's verdicts, the reason to show where it could not judge, and per
    scenario what the judge itself said, on which model and at which position (kept on
    the result for calibration: the stored verdict may be a hard check's instead)."""
    exhausted = await _allowance_used(tenant_id)
    order = judge_order(len(scenarios), seed=seed)
    texts = [
        conversation_text(scenarios[i], [(t.said, t.reply, t.tools) for t in conversations[i]])
        for i in order
    ]
    leg = judge_leg(tenant_leg, agent_model=agent_model, quota_exhausted=exhausted)
    try:
        answer = await judge_conversations(
            brief,
            texts,
            {s.key for s in scenarios},
            tenant_leg=leg,
            quota_exhausted=exhausted,
        )
    except ProblemError as refused:
        log.info("agent_tests_not_judged", extra={"reason": refused.code})
        return {}, not_judged_reason(refused.code), {}
    await _meter(tenant_id, answer, ASSIST_FEATURE_TEST_JUDGE)
    agent_family = model_family(agent_model)
    judge_family = model_family(answer.model)
    same_family = (
        None if agent_family is None or judge_family is None else agent_family == judge_family
    )
    record = {
        scenarios[i].key: {
            **judge_entry(answer.value.get(scenarios[i].key)),
            "model": answer.model,
            "agent_model": agent_model,
            "same_family": same_family,
            "position": position,
            "of": len(order),
        }
        for position, i in enumerate(order)
    }
    return answer.value, LEFT_OUT_REASON, record


async def _store_saved_results(
    tenant_id: UUID,
    scenarios: list[Scenario],
    conversations: list[list[Turn]],
    knowledge_tool: str | None,
    version: int | None,
) -> None:
    """A saved test that ran here shows its replies on its own row too."""
    async with tenant_session(tenant_id) as session:
        for scenario, turns in zip(scenarios, conversations, strict=True):
            if scenario.source != "saved" or scenario.case_id is None:
                continue
            await session.execute(
                text(
                    "UPDATE agent_test_cases SET last_result = CAST(:result AS jsonb), "
                    "last_error = NULL, last_run_at = now(), last_prompt_version = :version, "
                    "updated_at = now() WHERE id = :id AND status = 'idle'"
                ),
                {
                    "id": UUID(scenario.case_id),
                    "version": version,
                    "result": json.dumps(
                        [
                            {
                                "said": t.said,
                                "reply": t.reply,
                                "looked_up_knowledge": knowledge_tool is not None
                                and knowledge_tool in t.tools,
                                "cut_short": t.cut_short,
                            }
                            for t in turns
                        ]
                    ),
                },
            )


async def run_agent_test_conversations(
    ctx: dict[str, Any], payload: dict[str, Any], *, pause: Pause = _pause
) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE agent_test_runs r SET status = 'running', updated_at = now() "
                    "FROM agents a WHERE r.id = :id AND r.status = 'queued' "
                    "AND a.id = r.agent_id RETURNING r.agent_id, a.engine_agent_ref, "
                    "r.improve_round, r.retest_of, r.prompt_version"
                ),
                {"id": run_id},
            )
        ).first()
    if claimed is None:
        return "not_queued"
    agent_id, engine_agent_ref, round_no, retest_of, version = claimed
    engine = get_engine()
    if not isinstance(engine, RunsTestChat) or engine_agent_ref is None:
        await _finish(tenant_id, run_id, status="failed", results=None, failure="unavailable")
        return "failed"
    try:
        async with tenant_session(tenant_id) as session:
            brief = await load_brief(session, agent_id)
            tenant_leg = await account_assist_leg(session)
            previous = await get_run(session, agent_id, retest_of) if retest_of else None
        retests = _retests(previous.results) if previous is not None else []
        count = max(len(PROBES) + 1, MAX_GENERATED - len(retests))
        fresh, note = await write_scenarios(
            brief,
            tenant_id=tenant_id,
            round_key=f"r{run_id.hex[-6:]}",
            count=count,
            tenant_leg=tenant_leg,
        )
        retested_probes = {s.probe for s in retests if s.probe}
        fresh = [s for s in fresh if s.probe is None or s.probe not in retested_probes]
        saved = await _saved_scenarios(tenant_id, agent_id)
        # Two standing callers for the failure classes of a real call (D-749), ahead of the
        # AI-written ones so the message cap never drops them; a class being retested
        # already runs.
        retested = {s.key for s in retests}
        specimen = [
            s
            for s in specimen_scenarios(
                brief.language, brief.business_type, round_key=f"r{run_id.hex[-6:]}"
            )
            if s.key not in retested
        ]
        scenarios = within_budget(retests + specimen + fresh + saved)
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE agent_test_runs SET scenarios = CAST(:s AS jsonb), "
                    "updated_at = now() WHERE id = :id"
                ),
                {"id": run_id, "s": json.dumps([s.as_dict() for s in scenarios])},
            )
        conversations = await talk(
            engine,
            agent_id=agent_id,
            engine_agent_ref=str(engine_agent_ref),
            scenarios=scenarios,
            pause=pause,
        )
        judged, unjudged_reason, judge_record = await judge_all(
            brief,
            scenarios,
            conversations,
            tenant_id=tenant_id,
            tenant_leg=tenant_leg,
            agent_model=await agent_in_call_model(tenant_id, agent_id, engine),
            seed=run_id.hex,
        )
    except ProblemError as exc:
        log.warning("agent_tests_failed", extra={"run_id": str(run_id), "reason": exc.code})
        await _finish(tenant_id, run_id, status="failed", results=None, failure=exc.code)
        return "failed"
    except Exception:
        log.exception("agent_tests_crashed", extra={"run_id": str(run_id)})
        await _finish(tenant_id, run_id, status="failed", results=None, failure="crashed")
        return "failed"

    before = {str(r.get("key")): r.get("verdict") for r in (previous.results if previous else [])}
    results = [
        {
            **decide(
                scenario,
                turns,
                judged.get(scenario.key),
                language=brief.language,
                unjudged_reason=unjudged_reason,
            ),
            "before": before.get(scenario.key),
            "judge": judge_record.get(scenario.key),
        }
        for scenario, turns in zip(scenarios, conversations, strict=True)
    ]
    await _store_saved_results(
        tenant_id, scenarios, conversations, hosted_agent_limits(engine).knowledge_tool, version
    )
    await _finish(
        tenant_id, run_id, status="done", results=worst_first(results), failure=None, note=note
    )
    async with tenant_session(tenant_id) as session:
        finished = await get_run(session, agent_id, run_id)
        if wants_auto_improvement(finished):
            await queue_improvement(session, tenant_id=tenant_id, run_id=run_id)
    log.info(
        "agent_tests_done",
        extra={"run_id": str(run_id), "scenarios": len(results), "round": round_no},
    )
    return "done"


async def improve_run(
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    *,
    keys: list[str] | None,
) -> dict[str, Any]:
    """The proposal for this run's failures (all of them, or `keys`), stored on the run.

    The base is the autosaved draft when there is one, else the script callers hear: the
    owner reviews changes to what they are editing. Raises the assist refusal (allowance
    used up, no model) and `agent_tests_nothing_to_fix`."""
    async with tenant_session(tenant_id) as session:
        run = await get_run(session, agent_id, run_id)
        failures = needs_improving(run)
        if keys:
            failures = [r for r in failures if str(r.get("key")) in set(keys)]
        if not failures:
            raise ProblemError.business_rule(
                "agent_tests_nothing_to_fix", "Every chosen test passed. There is nothing to fix."
            )
        brief = await load_brief(session, agent_id)
        tenant_leg = await account_assist_leg(session)
        draft = await script_builder.read_draft(session, agent_id)
        loaded = await script_builder.load_agent_script(session, agent_id)
    exhausted = await _allowance_used(tenant_id)
    # A v1 script is reviewed in the v2 steps, exactly as the builder opens it.
    base = upgrade_to_v2(draft.script if draft is not None else loaded.script)
    if base.is_raw:
        # Suggestions are reviewed step by step; a hand-written script has no steps to
        # change, and rewriting it whole would drop the owner's own words.
        raise ProblemError.business_rule(
            "agent_tests_hand_written",
            "Suggested fixes need a script in steps.",
            remediation="Turn the hand-written script into steps in the script builder first.",
        )
    answer = await propose_improvement(
        brief, base, failures, tenant_leg=tenant_leg, quota_exhausted=exhausted
    )
    await _meter(tenant_id, answer, ASSIST_FEATURE_TEST_IMPROVE)
    record = improvement_record(
        answer,
        base=base,
        base_kind="draft" if draft is not None else "live",
        base_saved_at=draft.saved_at if draft is not None else None,
        base_version=loaded.version,
        for_keys=[str(r.get("key")) for r in failures],
    )
    async with tenant_session(tenant_id) as session:
        await store_improvement(session, agent_id=agent_id, run_id=run_id, improvement=record)
    return record


async def improve_agent_test_run(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM agent_test_runs WHERE id = :id"), {"id": run_id}
            )
        ).scalar()
    if agent_id is None:
        return "no_run"
    raw_keys = payload.get("keys")
    keys = [str(k) for k in raw_keys] if isinstance(raw_keys, list) else None
    try:
        await improve_run(tenant_id, agent_id, run_id, keys=keys)
    except ProblemError as refused:
        log.info(
            "agent_tests_improve_refused", extra={"run_id": str(run_id), "reason": refused.code}
        )
        note = (
            _AI_REFUSAL_NOTE.format(why=_AI_REFUSAL[refused.code])
            if refused.code in _AI_REFUSAL
            else " ".join(p for p in (refused.detail, refused.remediation) if p)
        )
        await _improve_failed(tenant_id, agent_id, run_id, note)
        return "skipped"
    except Exception:
        # The screen waits on this run until a proposal or a note arrives, so a crash is
        # written down for the owner as well as logged for us.
        log.exception("agent_tests_improve_crashed", extra={"run_id": str(run_id)})
        await _improve_failed(tenant_id, agent_id, run_id, IMPROVE_FAILED_NOTE)
        return "failed"
    log.info("agent_tests_improved", extra={"run_id": str(run_id)})
    return "proposed"


_AI_REFUSAL_NOTE: Final = "Suggestions could not be worked out, because {why}"


async def _improve_failed(tenant_id: UUID, agent_id: UUID, run_id: UUID, note: str) -> None:
    async with tenant_session(tenant_id) as session:
        await store_improve_failure(session, agent_id=agent_id, run_id=run_id, note=note)


__all__ = [
    "IMPROVE_JOB_NAME",
    "JOB_NAME",
    "PAUSE_S",
    "improve_agent_test_run",
    "improve_run",
    "judge_all",
    "run_agent_test_conversations",
    "talk",
    "write_scenarios",
]
