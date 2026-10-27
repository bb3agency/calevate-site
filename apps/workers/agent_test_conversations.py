"""Runs one queued set of test conversations, and prepares the "Improve my agent" proposal
(`apps/api/agents/test_conversations.py` describes the loop, D-724, D-823).

`run_agent_test_conversations`: one try of a run, `trial_results.TRIALS` tries per run, each
its own job queued by the try before it (outbox, same transaction), so every try fits the
worker's job timeout. The first try fixes the run's test set: "Test again" copies the
earlier run's tests exactly; otherwise a new version, real calls first (questions from real
calls, saved tests, the standing specimen callers), with AI-written practice callers only
when the owner asked. Each try talks to the live agent through the engine's test chat with a
pause between messages, decides the rule checks in code and judges the rest with the AI. The
last try aggregates every try into the results, worst first, each with its owner. Anything
on our side (a failed platform rule, or replies that sounded wrong) raises
`agent_test_platform_rule_failed`. One attempt per try: a try that cannot finish marks the
run failed with a machine code and the owner may start another.

`improve_agent_test_run`: the proposal for the failures the script or the knowledge owns,
small edits the owner keeps one by one. It never changes the script and never puts anything
live, and every round ends with a stop reason (`test_conversations.ImproveStop`).

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
from dataclasses import replace
from typing import Any, Final, cast
from uuid import UUID

import httpx
from calevate_shared.call_script import upgrade_to_v2
from calevate_shared.engine import VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_builder, trial_results
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.service import AgentRow, in_call_model
from apps.api.agents.specimen_scenarios import specimen_scenarios
from apps.api.agents.test_conversations import (
    ASSIST_FEATURE_TEST_GENERATE,
    ASSIST_FEATURE_TEST_IMPROVE,
    ASSIST_FEATURE_TEST_JUDGE,
    AUTO_STOP_NOTES,
    ENOUGH_REAL_CALLS,
    FEW_GENERATED,
    IMPROVE_JOB,
    MAX_GENERATED,
    MAX_SAVED,
    MAX_TURNS,
    NOTHING_FOR_THE_SCRIPT,
    PROBES,
    RUN_JOB,
    TEST_CHAT,
    TEST_CHAT_CALL,
    AgentBrief,
    ImproveStop,
    Judged,
    Scenario,
    TestChannel,
    TestRun,
    Turn,
    WrongTests,
    auto_improve_stop,
    compose_set,
    decide,
    failing,
    get_run,
    load_brief,
    needs_improving,
    probe_scenario,
    queue_improvement,
    queue_try,
    real_call_scenarios,
    recent_runs,
    standard_scenarios,
    store_improve_stop,
    store_improvement,
    waiting_update,
    wants_auto_improvement,
    wrong_tests,
)
from apps.api.agents.test_window import send_test_message
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HoldsCatalogue
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.test_chat import RunsTestChat, TestChatMode, TestChatTool
from apps.workers.agent_test_ai import (
    conversation_text,
    generate_scenarios,
    improve_request,
    improvement_record,
    input_hash,
    judge_conversations,
    judge_leg,
    judge_order,
    model_family,
    propose_improvement,
    safe_line,
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
    "assist_answer_unusable": (
        "the AI's answer came back incomplete. Test again; if it keeps happening, contact us."
    ),
}
_AI_REFUSAL_OTHER: Final = "AI help was not available. Test again in a few minutes."


def not_written_note(code: str) -> str:
    """The run's note when the practice callers the owner asked for could not be written."""
    why = _AI_REFUSAL.get(code, _AI_REFUSAL_OTHER)
    return f"No practice callers were written this time, because {why}"


def not_judged_reason(code: str) -> str:
    """A result's reason when no AI could check it."""
    why = _AI_REFUSAL.get(code, _AI_REFUSAL_OTHER)
    return f"Not checked, because {why} Read the reply yourself."


#: A result the AI checker answered for the others but not for this one.
LEFT_OUT_REASON: Final = (
    "Not checked: the AI checker gave no verdict on this one. Read the reply yourself."
)


#: The fallback when the improve job fails on something that is not an AI refusal: our
#: fault, alarmed as `agent_test_improve_crashed`.
IMPROVE_FAILED_NOTE: Final = (
    "Suggestions could not be worked out this time. That is on our side and we're fixing "
    "it. Try again in a few minutes."
)

#: The note on a run whose tests came from real calls alone.
FROM_REAL_CALLS_NOTE: Final = (
    "These tests come from your real calls, so no practice callers were written this time."
)

#: An improve round whose input was already answered: the same tests, failing the same
#: way, on the same script and facts. The model is not asked again (founder, D-823).
SAME_INPUT_NOTE: Final = (
    "These failures, on this script and these facts, already had suggestions worked out, "
    "so they were not worked out again. Keep a suggestion or change the script or a fact, "
    "then test again."
)

#: An improve round that found nothing in the script or the facts to change.
NO_EDITS_NOTE: Final = (
    "No change to the script or your facts would fix these tests. Each result says why it "
    "failed and who can fix it."
)

Pause = Callable[[], Awaitable[None]]


async def _pause() -> None:
    await asyncio.sleep(PAUSE_S)


async def _meter(tenant_id: UUID, answer: JsonAnswer[Any], feature: str) -> None:
    """A completed AI step is money spent: recorded in its own transaction (crm/assist §4),
    with any paid leg that answered unusably in front of it."""
    async with tenant_session(tenant_id) as session:
        await _meter_in(session, tenant_id, answer, feature)


async def _meter_in(
    session: AsyncSession, tenant_id: UUID, answer: JsonAnswer[Any], feature: str
) -> None:
    """`_meter` in the caller's transaction, for a step that stores what it paid for."""
    await crm_assist.meter_earlier(
        session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
    )
    await crm_assist.meter_assist(
        session,
        tenant_id=tenant_id,
        ref=new_assist_ref(),
        result=answer,
        feature=feature,
        model=answer.model,
    )


async def _meter_refused(tenant_id: UUID, refused: ProblemError, feature: str) -> None:
    """A refused AI step whose paid leg answered still owes the ledger that spend."""
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_refusal(
            session, tenant_id=tenant_id, refusal=refused, feature=feature
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
                "results = CAST(:results AS jsonb), error_code = :code, "
                "note = coalesce(:note, note), "
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


async def write_practice_callers(
    brief: AgentBrief,
    *,
    tenant_id: UUID,
    round_key: str,
    tenant_leg: TenantModelLeg | None,
) -> tuple[list[Scenario], str | None]:
    """`FEW_GENERATED` AI-written practice callers the owner asked for, and the run's note.
    An agent with enough real calls is tested on them alone and nothing is written (or
    charged). The rule checks keep our own wording (`probe_scenario`), so every version of
    the set asks them alike: any the writer reworded are dropped."""
    if brief.real_calls >= ENOUGH_REAL_CALLS:
        return [], FROM_REAL_CALLS_NOTE
    exhausted = await _allowance_used(tenant_id)
    try:
        answer = await generate_scenarios(
            brief,
            round_key=round_key,
            count=MAX_GENERATED,
            tenant_leg=tenant_leg,
            quota_exhausted=exhausted,
        )
    except ProblemError as refused:
        log.info("agent_tests_no_practice", extra={"reason": refused.code})
        await _meter_refused(tenant_id, refused, ASSIST_FEATURE_TEST_GENERATE)
        return [], not_written_note(refused.code)
    await _meter(tenant_id, answer, ASSIST_FEATURE_TEST_GENERATE)
    callers = [s for s in answer.value if s.probe is None][:FEW_GENERATED]
    return callers, answer.capability.disclosure


async def new_test_set(
    brief: AgentBrief,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    wrong: WrongTests,
    practice: bool,
    earlier: list[dict[str, Any]],
    round_key: str,
    tenant_leg: TenantModelLeg | None,
) -> tuple[list[Scenario], str | None]:
    """A new version of the agent's test set (`test_conversations.compose_set`) and the
    run's note. Practice callers are written only when the owner asked (`practice`); without
    that, the ones the previous set (`earlier`) held are kept, so adding a saved test does
    not silently drop them."""
    language = brief.language
    note: str | None = None
    if practice:
        written, note = await write_practice_callers(
            brief, tenant_id=tenant_id, round_key=round_key, tenant_leg=tenant_leg
        )
    else:
        # No note: nobody asked for practice callers, so saying none were written is noise.
        written = [s for s in (Scenario.of(raw) for raw in earlier) if s.source == "generated"]
    few_calls = brief.real_calls < ENOUGH_REAL_CALLS
    scenarios = compose_set(
        probes=[probe_scenario(p, language) for p in PROBES],
        real=[
            replace(s, turns=tuple(safe_line(t) for t in s.turns))
            for s in real_call_scenarios(brief, skip=wrong.keys)
        ],
        saved=[s for s in await _saved_scenarios(tenant_id, agent_id) if wrong.keeps(s)],
        practice=[s for s in written if wrong.keeps(s)],
        specimen=[
            s
            for s in specimen_scenarios(language, brief.business_type, round_key=round_key)
            if wrong.keeps(s)
        ],
        standard=[
            s
            for s in (standard_scenarios(language, brief.direction) if few_calls else [])
            if s.probe is None and wrong.keeps(s)
        ],
    )
    return scenarios, note


async def talk(
    engine: RunsTestChat,
    *,
    agent_id: UUID,
    engine_agent_ref: str,
    scenarios: list[Scenario],
    pause: Pause,
    modes: set[TestChatMode | None] | None = None,
) -> list[list[Turn]]:
    """Each scenario as one conversation with the live agent, its turns in order. `modes`
    collects the mode each turn ran in (`TestChatTurn.mode`)."""
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
            if modes is not None:
                modes.add(reply.mode)
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


def run_channel(modes: set[TestChatMode | None], *, run_id: UUID) -> TestChannel:
    """The channel a try's results are filed under, from the modes its turns ran in (D-847).
    Call mode asked for and not confirmed is filed as call mode, what was asked: the vendor
    states every call-mode answer includes `mode`, so an unconfirmed one is logged for us."""
    if None in modes or len(modes) > 1:
        log.warning(
            "agent_tests_mode_unconfirmed",
            extra={"run_id": str(run_id), "modes": ",".join(sorted(str(m) for m in modes))},
        )
    return TEST_CHAT_CALL if modes - {"chat"} else TEST_CHAT


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
    the result for calibration: the stored verdict may be a hard check's instead).

    The rule checks (`PROBES`) are decided in code and never sent to the judge; a run with
    nothing else asks it nothing."""
    pairs = [(s, c) for s, c in zip(scenarios, conversations, strict=True) if s.probe is None]
    if not pairs:
        return {}, LEFT_OUT_REASON, {}
    scenarios = [s for s, _c in pairs]
    conversations = [c for _s, c in pairs]
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
        await _meter_refused(tenant_id, refused, ASSIST_FEATURE_TEST_JUDGE)
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


def _jsonb_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value or [])


async def _first_try_set(
    brief: AgentBrief,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    wrong: WrongTests,
    practice: bool,
    previous: TestRun | None,
    earlier: list[dict[str, Any]],
    tenant_leg: TenantModelLeg | None,
) -> list[Scenario]:
    """The run's test set, saved on the run with its note before anything is asked: "Test
    again" (`previous`) asks exactly the tests that run asked; otherwise a new version."""
    if previous is not None:
        scenarios = [Scenario.of(raw) for raw in previous.scenarios]
        note = None
    else:
        scenarios, note = await new_test_set(
            brief,
            tenant_id=tenant_id,
            agent_id=agent_id,
            wrong=wrong,
            practice=practice,
            earlier=earlier,
            round_key=f"r{run_id.hex[-6:]}",
            tenant_leg=tenant_leg,
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_test_runs SET scenarios = CAST(:s AS jsonb), note = :note, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": run_id, "s": json.dumps([s.as_dict() for s in scenarios]), "note": note},
        )
    return scenarios


async def _claim_try(tenant_id: UUID, run_id: UUID, trial: int) -> Any:
    """Take try `trial` of the run, or None when it is not this try's turn: the run is not
    waiting for it (another worker has it, a try failed, or the run was given up as
    stalled). Compare-and-swap on `trial_started`, so a redelivered job runs nothing twice."""
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "UPDATE agent_test_runs r SET status = 'running', trial_started = :t, "
                    "updated_at = now() FROM agents a WHERE r.id = :id AND a.id = r.agent_id "
                    "AND r.trial_started = :t - 1 AND r.trials_done = :t - 1 AND r.trials >= :t "
                    "AND r.status = CASE WHEN :t = 1 THEN 'queued' ELSE 'running' END "
                    "RETURNING r.agent_id, a.engine_agent_ref, r.improve_round, r.retest_of, "
                    "r.prompt_version, r.trials, r.practice_callers, r.scenarios"
                ),
                {"id": run_id, "t": trial},
            )
        ).first()


async def _store_try(
    tenant_id: UUID, run_id: UUID, trial: int, trials: int, decided: list[dict[str, Any]]
) -> list[list[dict[str, Any]]] | None:
    """Record one try and, in the same transaction, queue the next (outbox); every try so
    far, or None when the run moved on without this one (given up as stalled)."""
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "UPDATE agent_test_runs SET trials_done = :t, updated_at = now(), "
                    "trial_results = coalesce(trial_results, '[]'::jsonb) "
                    "|| jsonb_build_array(CAST(:try AS jsonb)) "
                    "WHERE id = :id AND status = 'running' AND trial_started = :t "
                    "AND trials_done = :t - 1 RETURNING trial_results"
                ),
                {"id": run_id, "t": trial, "try": json.dumps(decided)},
            )
        ).first()
        if stored is None:
            return None
        if trial < trials:
            await queue_try(session, tenant_id=tenant_id, run_id=run_id, trial=trial + 1)
    raw = stored[0]
    return list(json.loads(raw) if isinstance(raw, str) else raw)


async def run_agent_test_conversations(
    ctx: dict[str, Any], payload: dict[str, Any], *, pause: Pause = _pause
) -> str:
    """One try of a run (`payload["trial"]`, 1 when absent). The first try makes or copies
    the run's test set; the last aggregates every try into the results."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    trial = int(payload.get("trial") or 1)
    claimed = await _claim_try(tenant_id, run_id, trial)
    if claimed is None:
        return "not_queued"
    agent_id, engine_agent_ref, round_no, retest_of, version, trials, practice, stored = claimed
    engine = get_engine()
    if not isinstance(engine, RunsTestChat) or engine_agent_ref is None:
        await _finish(tenant_id, run_id, status="failed", results=None, failure="unavailable")
        return "failed"
    try:
        async with tenant_session(tenant_id) as session:
            brief = await load_brief(session, agent_id)
            tenant_leg = await account_assist_leg(session)
            wrong = await wrong_tests(session, agent_id)
            agreements_waiting = await waiting_update(session, tenant_id, agent_id) is not None
            previous = await get_run(session, agent_id, retest_of) if retest_of else None
            earlier = await recent_runs(session, agent_id) if trial == 1 and not retest_of else []
        if trial == 1:
            scenarios = await _first_try_set(
                brief,
                tenant_id=tenant_id,
                agent_id=agent_id,
                run_id=run_id,
                wrong=wrong,
                practice=bool(practice),
                previous=previous,
                earlier=earlier[0].scenarios if earlier else [],
                tenant_leg=tenant_leg,
            )
        else:
            scenarios = [Scenario.of(raw) for raw in _jsonb_list(stored)]
        # A test the owner marked wrong since the set was made is not asked again; a rule
        # check always is (`WrongTests.keeps`).
        scenarios = [s for s in scenarios if wrong.keeps(s)]
        modes: set[TestChatMode | None] = set()
        conversations = await talk(
            engine,
            agent_id=agent_id,
            engine_agent_ref=str(engine_agent_ref),
            scenarios=scenarios,
            pause=pause,
            modes=modes,
        )
        channel = run_channel(modes, run_id=run_id)
        judged, unjudged_reason, judge_record = await judge_all(
            brief,
            scenarios,
            conversations,
            tenant_id=tenant_id,
            tenant_leg=tenant_leg,
            agent_model=await agent_in_call_model(tenant_id, agent_id, engine),
            seed=f"{run_id.hex}{trial}",
        )
    except ProblemError as exc:
        log.warning("agent_tests_failed", extra={"run_id": str(run_id), "reason": exc.code})
        await _finish(tenant_id, run_id, status="failed", results=None, failure=exc.code)
        return "failed"
    except Exception:
        log.exception("agent_tests_crashed", extra={"run_id": str(run_id)})
        await _finish(tenant_id, run_id, status="failed", results=None, failure="crashed")
        return "failed"

    rules = brief.rules(agreements_waiting=agreements_waiting)
    decided = [
        {
            **decide(
                scenario,
                turns,
                judged.get(scenario.key),
                language=brief.language,
                unjudged_reason=unjudged_reason,
                rules=rules,
                channel=channel,
            ),
            "judge": judge_record.get(scenario.key),
        }
        for scenario, turns in zip(scenarios, conversations, strict=True)
    ]
    if trial == 1:
        await _store_saved_results(
            tenant_id, scenarios, conversations, hosted_agent_limits(engine).knowledge_tool, version
        )
    tries = await _store_try(tenant_id, run_id, trial, int(trials), decided)
    if tries is None:
        return "not_queued"
    if trial < int(trials):
        log.info("agent_tests_try_done", extra={"run_id": str(run_id), "try": trial})
        return "try_done"
    results = trial_results.aggregate_run(tries)
    await _finish(
        tenant_id,
        run_id,
        status="done",
        results=trial_results.worst_first(results),
        failure=None,
        note=None,
    )
    _alarm_platform_failures(results, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id)
    async with tenant_session(tenant_id) as session:
        finished = await get_run(session, agent_id, run_id)
        if wants_auto_improvement(finished):
            await queue_improvement(session, tenant_id=tenant_id, run_id=run_id)
        else:
            stop = auto_improve_stop(finished)
            if stop is not None:
                await store_improve_stop(
                    session, agent_id=agent_id, run_id=run_id, stop=stop, note=AUTO_STOP_NOTES[stop]
                )
    log.info(
        "agent_tests_done",
        extra={"run_id": str(run_id), "scenarios": len(results), "round": round_no},
    )
    return "done"


#: The alarm when a run's failure is ours to fix (`runbooks/alarm-index.md`).
PLATFORM_FAILURE_CODE: Final = "agent_test_platform_rule_failed"


def _alarm_platform_failures(
    results: list[dict[str, Any]], *, tenant_id: UUID, agent_id: UUID, run_id: UUID
) -> None:
    """One alarm per run that found something the platform owns: a test that failed on a
    rule our prompt or action should have kept, or replies that sounded wrong in a way only
    the platform prompt and the register layer can change (`turn_checks.SOUND_KINDS`). The
    owner is told "we're fixing this", so somebody here has to be told too; the detail
    carries the count per kind, so the register layer is fixed from totals, not anecdotes."""
    ours = [r for r in results if trial_results.standing(r) == "ours"]
    sounds = trial_results.sound_counts(results)
    if not ours and not sounds:
        return
    parts = []
    if ours:
        checks = sorted({str(r.get("probe") or r.get("fix") or "shape") for r in ours})
        parts.append(f"{len(ours)} test(s) failed on a rule the platform owns: {', '.join(checks)}")
    if sounds:
        parts.append(
            "tests per way it sounded wrong: " + ", ".join(f"{k}={n}" for k, n in sounds.items())
        )
    alert(
        "CORE_LOGIC",
        PLATFORM_FAILURE_CODE,
        detail="; ".join(parts),
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        run_id=str(run_id),
    )


async def _answered_before(tenant_id: UUID, agent_id: UUID, request_hash: str) -> bool:
    """Has the improver already been asked exactly this, for this agent?"""
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT 1 FROM agent_test_runs WHERE agent_id = :aid "
                    "AND improvement->>'input_hash' = :hash LIMIT 1"
                ),
                {"aid": agent_id, "hash": request_hash},
            )
        ).first() is not None


async def improve_run(
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    *,
    keys: list[str] | None,
) -> tuple[ImproveStop, dict[str, Any] | None]:
    """The proposal for this run's failures the script or the knowledge owns (all of them,
    or `keys`), stored on the run, and why the round stopped.

    The base is the autosaved draft when there is one, else the script callers hear: the
    owner reviews changes to what they are editing. A request identical to one already
    answered for this agent is not asked again (`no_change`), and an answer with no edits
    and no facts says so (`no_change`). Raises the assist refusal (allowance used up, no
    model), `agent_tests_nothing_to_fix` and `agent_tests_nothing_fixable_by_script`."""
    async with tenant_session(tenant_id) as session:
        run = await get_run(session, agent_id, run_id)
        chosen = failing(run)
        if keys:
            chosen = [r for r in chosen if str(r.get("key")) in set(keys)]
        if not chosen:
            raise ProblemError.business_rule(
                "agent_tests_nothing_to_fix", "Every chosen test passed. There is nothing to fix."
            )
        failures = [r for r in chosen if r in needs_improving(run)]
        if not failures:
            raise ProblemError.business_rule(
                "agent_tests_nothing_fixable_by_script", NOTHING_FOR_THE_SCRIPT
            )
        brief = await load_brief(session, agent_id)
        tenant_leg = await account_assist_leg(session)
        draft = await script_builder.read_draft(session, agent_id)
        loaded = await script_builder.load_agent_script(session, agent_id)
    # A v1 script is reviewed in the v2 steps, exactly as the builder opens it.
    base = upgrade_to_v2(draft.script if draft is not None else loaded.script)
    if base.is_raw:
        # Suggestions are edits to steps and parts; a hand-written script has none.
        raise ProblemError.business_rule(
            "agent_tests_hand_written",
            "Suggested fixes need a script in steps.",
            remediation="Turn the hand-written script into steps in the script builder first.",
        )
    request_hash = input_hash(improve_request(brief, base, failures))
    if await _answered_before(tenant_id, agent_id, request_hash):
        async with tenant_session(tenant_id) as session:
            await store_improve_stop(
                session, agent_id=agent_id, run_id=run_id, stop="no_change", note=SAME_INPUT_NOTE
            )
        return "no_change", None
    exhausted = await _allowance_used(tenant_id)
    answer = await propose_improvement(
        brief, base, failures, tenant_leg=tenant_leg, quota_exhausted=exhausted
    )
    record = improvement_record(
        answer,
        base=base,
        base_kind="draft" if draft is not None else "live",
        base_saved_at=draft.saved_at if draft is not None else None,
        base_version=loaded.version,
        for_keys=[str(r.get("key")) for r in failures],
        request_hash=request_hash,
    )
    found = bool(record.get("edits") or record.get("facts"))
    stop: ImproveStop = "completed" if found else "no_change"
    # Charged in the transaction that stores the answer: committed alone, a job stopped
    # before the store re-runs, finds no stored `input_hash` and is charged again.
    async with tenant_session(tenant_id) as session:
        await store_improvement(
            session,
            agent_id=agent_id,
            run_id=run_id,
            improvement=record,
            stop=stop,
            note=None if found else NO_EDITS_NOTE,
        )
        await _meter_in(session, tenant_id, answer, ASSIST_FEATURE_TEST_IMPROVE)
    return stop, record


#: The stop reason a refused improve round records, by the refusal's code; any other is
#: `failed`.
_REFUSAL_STOPS: Final[dict[str, ImproveStop]] = {
    "assist_quota_exhausted": "budget",
    "agent_tests_nothing_fixable_by_script": "nothing_fixable_by_script",
    "agent_tests_nothing_to_fix": "no_change",
}

#: The alarm when the improve job itself crashed: our fault, and the owner is told so.
IMPROVE_CRASHED_CODE: Final = "agent_test_improve_crashed"


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
        stop, _record = await improve_run(tenant_id, agent_id, run_id, keys=keys)
    except ProblemError as refused:
        log.info(
            "agent_tests_improve_refused", extra={"run_id": str(run_id), "reason": refused.code}
        )
        await _meter_refused(tenant_id, refused, ASSIST_FEATURE_TEST_IMPROVE)
        note = (
            _AI_REFUSAL_NOTE.format(why=_AI_REFUSAL[refused.code])
            if refused.code in _AI_REFUSAL
            else " ".join(p for p in (refused.detail, refused.remediation) if p)
        )
        await _improve_stopped(
            tenant_id, agent_id, run_id, _REFUSAL_STOPS.get(refused.code, "failed"), note
        )
        return "skipped"
    except Exception:
        # The screen waits on this run until a proposal or a note arrives, so a crash is
        # written down for the owner as well as raised for us.
        log.exception("agent_tests_improve_crashed", extra={"run_id": str(run_id)})
        alert(
            "WORKER_TERMINAL",
            IMPROVE_CRASHED_CODE,
            detail="the improve job for a test run raised; the owner was told to try again",
            tenant_id=str(tenant_id),
            run_id=str(run_id),
        )
        await _improve_stopped(tenant_id, agent_id, run_id, "failed", IMPROVE_FAILED_NOTE)
        return "failed"
    log.info("agent_tests_improved", extra={"run_id": str(run_id), "stop": stop})
    return stop


_AI_REFUSAL_NOTE: Final = "Suggestions could not be worked out, because {why}"


async def _improve_stopped(
    tenant_id: UUID, agent_id: UUID, run_id: UUID, stop: ImproveStop, note: str
) -> None:
    async with tenant_session(tenant_id) as session:
        await store_improve_stop(session, agent_id=agent_id, run_id=run_id, stop=stop, note=note)


__all__ = [
    "FROM_REAL_CALLS_NOTE",
    "IMPROVE_CRASHED_CODE",
    "IMPROVE_FAILED_NOTE",
    "IMPROVE_JOB_NAME",
    "JOB_NAME",
    "NO_EDITS_NOTE",
    "PAUSE_S",
    "PLATFORM_FAILURE_CODE",
    "SAME_INPUT_NOTE",
    "improve_agent_test_run",
    "improve_run",
    "judge_all",
    "new_test_set",
    "run_agent_test_conversations",
    "talk",
    "write_practice_callers",
]
