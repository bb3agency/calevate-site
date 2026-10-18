"""Test conversations that improve the agent (D-724): generated callers, the AI judge with
its hard checks, "Improve my agent" proposals, metering, and the test-chat opt-out.

The model is replaced at `chat.complete` (the seam `script_assist_draft_test` uses) and the
engine by a fake test chat, so no credential or network is involved.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle, test_conversations
from apps.api.agents.script_edits import (
    EditRejectedError,
    ScriptEdit,
    apply_edit,
    apply_edits,
)
from apps.api.agents.test_conversations import (
    PROBES,
    Judged,
    Scenario,
    Turn,
    decide,
    ensure_probes,
    hard_check,
    probe_scenario,
    within_budget,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.test_chat import TestChatTool, TestChatTurn
from apps.api.reliability.engine_actions import (
    ACTION_NAMES,
    CALLBACK,
    OPT_OUT,
    RETIRED_ACTION_NAMES,
)
from apps.workers import agent_test_ai, chat
from apps.workers import agent_test_conversations as worker
from apps.workers.script_assist import UnusableAnswerError
from calevate_shared.call_script import MAX_SCRIPT_STAGES, CallScript, ConversationStage
from sqlalchemy import text
from tests.conftest import accept_agreements

OPT_OUT_TOOL = ACTION_NAMES[OPT_OUT]


@pytest.fixture
def azure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


def _model(answers: list[dict[str, Any]], seen: list[str] | None = None) -> Any:
    """`chat.complete` answering each request with the next JSON, Azure-counted."""

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any) -> Any:
        if seen is not None:
            seen.append(str(messages[-1]["content"]))
        return chat.ChatOutcome(
            content=json.dumps(answers.pop(0)),
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=900, output_tokens=400),
        )

    return _complete


BRIEF = test_conversations.AgentBrief(
    business_name="Raghava Organics",
    business_type="retail",
    direction="inbound",
    language="te-IN",
    register="Neutral spoken Telugu.",
    word_swaps=(("ధర", "price"), ("క్షమించండి", "sorry అండి")),
    steps=(("s1", "Greet", "Greet and ask what they need."),),
    opening_line="నమస్కారం అండి",
    ending="",
    objections=(),
    pinned_facts=(("f1", "1 kg mirchi price", "₹450"),),
    knowledge_titles=("Price list",),
    lead_fields=("Name",),
    hand_over="nobody_on_duty",
    call_backs=True,
    call_is_recorded=True,
    caller_lines=("naa number 9876543210, mirchi undha?",),
)


# --- generation -------------------------------------------------------------------------


async def test_generated_tests_differ_from_the_standard_set_and_always_carry_the_probes(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a generated set can leave out a compliance probe (hard rule 5), or a real
    caller's number reaches the dashboard model (G-2)."""
    seen: list[str] = []
    monkeypatch.setattr(
        chat,
        "complete",
        _model(
            [
                {
                    "scenarios": [
                        {
                            "title": "Asks the mirchi price",
                            "category": "business",
                            "probe": "none",
                            "caller_turns": ["మిర్చి kg ఎంత అండి?", "Delivery ఉందా?"],
                            "expect": "Gives ₹450 from the pinned facts.",
                        },
                        {
                            "title": "Asks if it is a machine",
                            "category": "compliance",
                            "probe": "ai",
                            "caller_turns": ["మీరు robot ఆ?"],
                            "expect": "Says it is an AI.",
                        },
                    ]
                }
            ],
            seen,
        ),
    )
    answer = await agent_test_ai.generate_scenarios(BRIEF, round_key="r1")
    assert answer.capability.provider == "azure" and answer.usage is not None
    scenarios = ensure_probes(answer.value, "te-IN")
    assert {s.probe for s in scenarios if s.probe} == set(PROBES)
    # The AI's own wording of the AI probe is kept; the rest are filled in.
    assert next(s for s in scenarios if s.probe == "ai").turns == ("మీరు robot ఆ?",)
    assert any(len(s.turns) == 2 for s in scenarios)
    assert "9876543210" not in seen[0]


def test_the_budget_keeps_every_probe_and_drops_the_overflow() -> None:
    long = [
        Scenario(key=f"g{i}", title="t", category="business", turns=("a", "b", "c", "d"), expect="")
        for i in range(10)
    ]
    kept = within_budget([probe_scenario(p, "te-IN") for p in PROBES] + long)
    assert {s.probe for s in kept if s.probe} == set(PROBES)
    assert sum(len(s.turns) for s in kept) <= test_conversations.MAX_MESSAGES


# --- judging ---------------------------------------------------------------------------


def _turn(reply: str, *tools: str, status: str | None = None) -> Turn:
    return Turn(
        said="x",
        reply=reply,
        tools=list(tools),
        statuses=[status if t == OPT_OUT_TOOL else None for t in tools],
    )


def test_a_price_from_a_pinned_fact_passes_without_a_lookup() -> None:
    """The founder's first defect: ₹450 came from the pinned facts and was marked "did not
    look anything up". With no lookup rule left, the judge decides."""
    scenario = Scenario(key="k", title="Price", category="business", turns=("ఎంత?",), expect="")
    result = decide(
        scenario,
        # In English words, as a shop says it: "₹450", "1 kg" (D-739) and "నాలుగు వందల
        # యాభై రూపాయలు" (D-749) fail the speech check.
        [_turn("ఒక కిలో మిర్చి four fifty rupees అండి.")],
        Judged(verdict="passed", reason="Matches the pinned fact."),
        language="te-IN",
        unjudged_reason="n/a",
    )
    assert result["verdict"] == "passed"


def test_stop_calling_without_the_opt_out_action_fails_whatever_the_judge_says() -> None:
    scenario = probe_scenario("stop_calling", "te-IN")
    result = decide(
        scenario,
        [_turn("website form లో fill చేయండి.")],
        Judged(verdict="passed", reason="ok"),
        language="te-IN",
        unjudged_reason="",
    )
    assert result["verdict"] == "failed" and result["fix"] == "platform"
    assert result["owner"] == "platform"
    # The step taken but nothing written: a test chat has no number to write (D-748), and
    # the rule is decided in code whatever an AI judge said (D-823); the result says what
    # the test cannot show.
    for status in ("caller_not_matched", None, "error"):
        taken = decide(
            scenario,
            [_turn("సరే అండి, మళ్ళీ call చేయము.", OPT_OUT_TOOL, status=status)],
            Judged(verdict="failed", reason="It did not say they were removed.", fix="style"),
            language="te-IN",
            unjudged_reason="",
        )
        assert taken["verdict"] == "passed" and taken["owner"] is None
        assert taken["limit"] == test_conversations.OPT_OUT_TEST_LIMIT
    recorded = decide(
        scenario,
        [_turn("మీ number తీసేశాం అండి.", OPT_OUT_TOOL, status="recorded_in_test")],
        Judged(verdict="passed", reason="ok"),
        language="te-IN",
        unjudged_reason="",
    )
    assert recorded["verdict"] == "passed"


def test_textbook_words_from_the_spoken_style_list_fail_whatever_the_judge_says() -> None:
    scenario = Scenario(key="k", title="Thanks", category="business", turns=("ok",), expect="")
    result = decide(
        scenario,
        [_turn("క్షమించండి, ధర చెప్తాను. ధన్యవాదాలు.")],
        Judged(verdict="passed", reason="Fine."),
        language="te-IN",
        unjudged_reason="",
    )
    # A hard fail since D-739, with the spoken word to use in the reason.
    assert result["verdict"] == "failed" and result["fix"] == "style"
    assert "sorry అండి" in result["reason"]
    assert {"క్షమించండి", "ధర", "ధన్యవాదాలు"} <= set(result["formal_words"])


def test_the_rule_checks_are_decided_in_code_and_never_by_the_judge() -> None:
    """FAILS IF: an AI judge can pass or fail a rule the platform owns (D-823), or a rule
    failure reaches the improver rather than us."""
    said_ai = decide(
        probe_scenario("ai", "te-IN"),
        [_turn("నేను AI assistant ని అండి.")],
        Judged(verdict="failed", reason="judged", fix="style"),
        language="te-IN",
        unjudged_reason="Not checked.",
    )
    assert said_ai["verdict"] == "passed" and said_ai["owner"] is None
    dodged = decide(
        probe_scenario("ai", "te-IN"),
        [_turn("మీకు ఏం కావాలి అండి?")],
        Judged(verdict="passed", reason="judged"),
        language="te-IN",
        unjudged_reason="Not checked.",
    )
    assert dodged["verdict"] == "failed" and dodged["owner"] == "platform"
    recording = decide(
        probe_scenario("recording", "te-IN"),
        [_turn("అవును అండి, call record అవుతుంది.")],
        None,
        language="te-IN",
        unjudged_reason="Not checked.",
    )
    assert recording["verdict"] == "passed"
    retired = next(iter(RETIRED_ACTION_NAMES))
    assert hard_check(probe_scenario("person", "te-IN"), [_turn("x", retired)]).verdict == "failed"


def test_asking_for_a_person_is_a_setting_when_nobody_can_be_put_through() -> None:
    """FAILS IF: the person check expects a hand-over the account cannot make. With nobody
    to put a caller through to, the result names the setting and why, and is neither a pass
    nor a failure of the agent; with someone on duty, the test says what it cannot show."""
    person = probe_scenario("person", "te-IN")
    turns = [_turn("ఇప్పుడు ఎవరూ అందుబాటులో లేరు అండి.")]
    off = decide(
        person,
        turns,
        None,
        language="te-IN",
        unjudged_reason="",
        rules=test_conversations.RuleContext(hand_over="off", hand_over_reason="disabled"),
    )
    assert off["verdict"] == "unjudged" and off["owner"] == "setting"
    assert off["setting"]["area"] == "handover"
    assert "switched off" in off["setting"]["reason"]
    on_duty = decide(
        person,
        turns,
        None,
        language="te-IN",
        unjudged_reason="",
        rules=test_conversations.RuleContext(hand_over="someone_on_duty"),
    )
    assert on_duty["verdict"] == "unjudged" and on_duty["owner"] is None
    assert on_duty["limit"] == test_conversations.HAND_OVER_TEST_LIMIT


def test_a_call_back_step_on_an_account_that_cannot_keep_one_is_ours() -> None:
    scenario = Scenario(key="k", title="Later", category="objection", turns=("x",), expect="")
    result = decide(
        scenario,
        [_turn("సరే అండి.", ACTION_NAMES[CALLBACK])],
        Judged(verdict="passed", reason="fine"),
        language="te-IN",
        unjudged_reason="",
        rules=test_conversations.RuleContext(call_backs=False),
    )
    assert result["verdict"] == "failed" and result["owner"] == "platform"


def test_a_platform_failure_while_agreements_wait_points_at_the_agreements() -> None:
    result = decide(
        probe_scenario("ai", "te-IN"),
        [_turn("మీకు ఏం కావాలి అండి?")],
        None,
        language="te-IN",
        unjudged_reason="",
        rules=test_conversations.RuleContext(agreements_waiting=True),
    )
    assert result["owner"] == "setting" and result["setting"]["area"] == "agreements"


def test_the_judges_answer_is_held_to_the_run_and_the_vocabulary() -> None:
    judged = agent_test_ai.judgements_from_model(
        {
            "results": [
                {
                    "key": "a",
                    "verdict": "needs_fix",
                    "reason": "Too formal.",
                    "fix": "style",
                    "step_id": "",
                    "formal_words": ["ధన్యవాదాలు"],
                },
                {
                    "key": "zzz",
                    "verdict": "failed",
                    "reason": "x",
                    "fix": "none",
                    "step_id": "",
                    "formal_words": [],
                },
                {
                    "key": "b",
                    "verdict": "maybe",
                    "reason": "x",
                    "fix": "none",
                    "step_id": "",
                    "formal_words": [],
                },
            ]
        },
        {"a", "b"},
    )
    assert judged is not None and set(judged) == {"a"}
    assert judged["a"].fix == "style" and judged["a"].formal_words == ("ధన్యవాదాలు",)


# --- improving -------------------------------------------------------------------------

CURRENT = CallScript(
    schema_version=2,
    stages=[ConversationStage(id="s1", name="Greet", instruction="Greet the caller.")],
)


def _edit(op: str, **fields: str) -> dict[str, str]:
    return {
        "op": op,
        "step_id": "",
        "part": "",
        "name": "",
        "objection": "",
        "text": "",
        "because": "k1",
        "why": "Because.",
        **fields,
    }


def test_a_proposal_is_small_edits_each_checked_on_its_own() -> None:
    """FAILS IF: the improver's answer is a whole script again, or one bad edit throws the
    good ones away (D-823). Each edit is applied alone; one that does not fit is dropped."""
    proposal = agent_test_ai.proposal_from_model(
        {
            "edits": [
                _edit("set_step", step_id="s1", text="Greet them and ask what they need."),
                _edit("set_step", step_id="nope", text="x"),
                _edit("set_objection", objection="Not interested", text="సరే అండి, thanks."),
                _edit("set_step", step_id="s1", text="A second change to the same step."),
                _edit("add_step", step_id="s1", name="Price", text="Give the pinned price."),
                _edit("set_part", part="ending", text="Thank them and say goodbye."),
            ],
            "facts": [
                {
                    "action": "add",
                    "fact_id": "",
                    "question": "Delivery to Kukatpally?",
                    "answer": "",
                    "because": "k2",
                    "why": "Callers ask it.",
                },
                {
                    "action": "fix",
                    "fact_id": "unknown",
                    "question": "Price?",
                    "answer": "₹1",
                    "because": "k2",
                    "why": "x",
                },
            ],
        },
        current=CURRENT,
        keys={"k1", "k2"},
        fact_ids={"f1"},
    )
    assert proposal is not None
    assert [e["op"] for e in proposal["edits"]] == [
        "set_step",
        "set_objection",
        "add_step",
        "set_part",
    ]
    assert proposal["dropped"] == 2
    step = proposal["edits"][0]
    assert step["label"] == "Step “Greet”" and step["before"] == "Greet the caller."
    assert proposal["facts"] == [
        {
            "action": "add",
            "fact_id": None,
            "question": "Delivery to Kukatpally?",
            "answer": "",
            "because": "k2",
            "why": "Callers ask it.",
        }
    ]
    # The kept edits are applied to the owner's copy by the same function, one by one.
    edits = [ScriptEdit.of(e) for e in proposal["edits"]]
    script, applied, rejected = apply_edits(CURRENT, [edits[0], edits[2]])
    assert applied == ["e1", "e5"] and rejected == []
    assert [s.id for s in script.stages] == ["s1", "s2"]
    assert script.stages[0].instruction == "Greet them and ask what they need."
    assert script.objections == []


def test_an_answer_whose_every_edit_is_unusable_is_sent_back_once_with_why() -> None:
    """Every edit broken: refused with the fields and rules, so the ladder repairs once
    (`script_assist.ask_json`). An empty answer is an honest "nothing here", not a refusal."""
    with pytest.raises(UnusableAnswerError) as refused:
        agent_test_ai.proposal_from_model(
            {"edits": [_edit("set_step", step_id="BAD", text="x")], "facts": []},
            current=CURRENT,
            keys=set(),
            fact_ids=set(),
        )
    assert "edits.0.step_id: unknown_step" in refused.value.problems
    empty = agent_test_ai.proposal_from_model(
        {"edits": [], "facts": []}, current=CURRENT, keys=set(), fact_ids=set()
    )
    assert empty == {"edits": [], "dropped": 0, "facts": []}


def test_a_new_step_stops_at_the_step_limit() -> None:
    full = CallScript(
        schema_version=2,
        stages=[
            ConversationStage(id=f"s{i}", name=f"Step {i}", instruction="Do it.")
            for i in range(1, MAX_SCRIPT_STAGES + 1)
        ],
    )
    edit = ScriptEdit(id="e1", op="add_step", name="One more", text="Do more.")
    with pytest.raises(EditRejectedError) as refused:
        apply_edit(full, edit)
    assert (refused.value.field, refused.value.rule) == ("op", "too_many_steps")


# --- a whole run, metered, and its RLS -------------------------------------------------


class _FakeChat:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def test_chat(
        self, ref: str, message: str, *, session: str | None = None
    ) -> TestChatTurn:
        self.sent.append(message)
        if "number" in message or "call చేయకండి" in message:
            return TestChatTurn(
                session="vr_1",
                reply="సరే అండి, మీ number తీసేశాం.",
                tools=(OPT_OUT_TOOL,),
                tool_results=(TestChatTool(name=OPT_OUT_TOOL, status="recorded_in_test"),),
            )
        return TestChatTurn(
            session="vr_1", reply="నేను AI assistant ని అండి. Calls record అవుతాయి.", tools=()
        )


async def _agent() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Raghava Organics",
        slug=f"tests-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Front desk",
            direction="inbound",
            language_primary="te-IN",
        )
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_test' WHERE id = :id"), {"id": agent_id}
        )
    return tenant_id, agent_id


async def test_a_run_writes_talks_judges_meters_and_retests(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _agent()
    fake = _FakeChat()
    monkeypatch.setattr(test_conversations, "get_engine", lambda: fake)
    monkeypatch.setattr(worker, "get_engine", lambda: fake)
    monkeypatch.setattr(
        worker,
        "hosted_agent_limits",
        lambda engine: type("L", (), {"knowledge_tool": "search_knowledge"})(),
    )
    # The standing specimen callers (D-749) rotate on the run's random id, and this fake
    # agent gives one fixed reply, which a specimen like "asks to repeat" rightly fails. They
    # have their own tests (`tests/specimen_call_test.py`); this one pins the loop.
    monkeypatch.setattr(worker, "specimen_scenarios", lambda *args, **kwargs: [])

    async def _in_call_model(*args: Any) -> str:
        return "GPT-OSS 120B"

    monkeypatch.setattr(worker, "agent_in_call_model", _in_call_model)
    generated = {
        "scenarios": [
            {
                "title": "Asks the price",
                "category": "business",
                "probe": "none",
                "caller_turns": ["మిర్చి kg ఎంత?"],
                "expect": "Gives the pinned price.",
            },
        ]
    }

    def _verdicts(keys: list[str], failing: str | None) -> dict[str, Any]:
        return {
            "results": [
                {
                    "key": k,
                    "verdict": "failed" if k == failing else "passed",
                    "reason": "Because.",
                    "fix": "knowledge" if k == failing else "none",
                    "step_id": "",
                    "formal_words": [],
                }
                for k in keys
            ]
        }

    async def _no_pause() -> None:
        return None

    async with tenant_session(tenant_id) as session:
        run = await test_conversations.request_run(
            session, tenant_id=tenant_id, agent_id=agent_id, requested_by=None, auto_improve=True
        )
    round_key = f"r{run.id.hex[-6:]}"
    answers = [generated]
    monkeypatch.setattr(chat, "complete", _model(answers))

    # The judge needs the keys the run will hold, so it is answered from the request.
    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any) -> Any:
        content = str(messages[-1]["content"])
        if "Conversations to check" in content:
            keys = [
                line[1 : line.index("]")] for line in content.splitlines() if line.startswith("[")
            ]
            body = _verdicts(keys, failing=f"{round_key}_1")
        else:
            body = answers.pop(0)
        return chat.ChatOutcome(
            content=json.dumps(body),
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=900, output_tokens=400),
        )

    monkeypatch.setattr(chat, "complete", _complete)
    outbox: list[str] = []

    async def _enqueue(session: Any, *, job: str, payload: dict[str, Any], **_: Any) -> None:
        outbox.append(job)

    monkeypatch.setattr(test_conversations, "enqueue_outbox", _enqueue)
    outcome = await worker.run_agent_test_conversations(
        {}, {"tenant_id": str(tenant_id), "run_id": str(run.id)}, pause=_no_pause
    )
    assert outcome == "done"
    async with tenant_session(tenant_id) as session:
        done = await test_conversations.get_run(session, agent_id, run.id)
        features = set(
            (
                await session.execute(
                    text("SELECT DISTINCT meta->>'feature' FROM usage_events WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalars()
        )
    assert done.status == "done"
    assert {r["probe"] for r in done.results if r.get("probe")} == set(PROBES)
    assert done.results[0]["verdict"] == "failed"  # failures first
    judged = [r for r in done.results if r["verdict"] != "unjudged"]
    assert done.score == (len(judged) - 1, len(judged)), done.results
    # Hand-over is off on this agent: asking for a person is a setting, not a failure.
    person = next(r for r in done.results if r.get("probe") == "person")
    assert person["verdict"] == "unjudged" and person["owner"] == "setting"
    assert {"agent_test_generate", "agent_test_judge"} <= features
    # The rule checks never reach the judge (D-823). What the judge itself said about the
    # rest is kept beside the stored verdict, for calibration: the model it ran on, that it
    # shares the agent's family (no other leg is configured here), and where in its request
    # each conversation sat.
    assert all(r["judge"] is None for r in done.results if r.get("probe"))
    records = [r["judge"] for r in done.results if r.get("judge")]
    assert {j["model"] for j in records} == {get_settings().azure_openai_model}
    assert all(j["same_family"] is True for j in records)
    assert sorted(j["position"] for j in records) == list(range(len(records)))
    failed = done.results[0]
    assert failed["judge"]["verdict"] == "failed" and failed["judge"]["reason"] == "Because."
    assert failed["owner"] == "knowledge"
    # Auto-improve was asked for and a test the knowledge owns failed: the proposal is queued.
    assert outbox == [test_conversations.IMPROVE_JOB]

    # "Test again" with nothing changed is refused: the same failures would come back.
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as same:
            await test_conversations.request_run(
                session, tenant_id=tenant_id, agent_id=agent_id, requested_by=None, retest_of=run.id
            )
    assert same.value.code == "agent_tests_nothing_changed"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET handoff_enabled = true WHERE id = :id"), {"id": agent_id}
        )
    # Something changed, so "Test again" re-asks the failure word for word and shows before
    # and after.
    async with tenant_session(tenant_id) as session:
        again = await test_conversations.request_run(
            session, tenant_id=tenant_id, agent_id=agent_id, requested_by=None, retest_of=run.id
        )
    assert again.improve_round == 2
    answers.append(generated)
    round_key = f"r{again.id.hex[-6:]}"
    fake.sent.clear()
    await worker.run_agent_test_conversations(
        {}, {"tenant_id": str(tenant_id), "run_id": str(again.id)}, pause=_no_pause
    )
    async with tenant_session(tenant_id) as session:
        second = await test_conversations.get_run(session, agent_id, again.id)
    retested = next(r for r in second.results if r["source"] == "retest")
    assert retested["before"] == "failed"
    assert "మిర్చి kg ఎంత?" in fake.sent


async def _failed_run(tenant_id: uuid.UUID, agent_id: uuid.UUID, results: list[Any]) -> uuid.UUID:
    run_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, results, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'done', CAST(:r AS jsonb), "
                "now(), now())"
            ),
            {"id": run_id, "t": tenant_id, "a": agent_id, "r": json.dumps(results)},
        )
    return run_id


NOT_INTERESTED = {
    "key": "k1",
    "title": "Not interested",
    "verdict": "needs_fix",
    "reason": "It pushed.",
    "fix": "objection",
    "conversation": [],
}


async def test_improving_needs_a_failure_and_the_allowance(
    azure: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _agent()
    run_id = await _failed_run(
        tenant_id, agent_id, [{"key": "k1", "title": "Price", "verdict": "passed"}]
    )
    with pytest.raises(ProblemError) as nothing:
        await worker.improve_run(tenant_id, agent_id, run_id, keys=None)
    assert nothing.value.code == "agent_tests_nothing_to_fix"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agent_test_runs SET results = CAST(:r AS jsonb) WHERE id = :id"),
            {"id": run_id, "r": json.dumps([NOT_INTERESTED])},
        )
    monkeypatch.setattr(
        chat,
        "complete",
        _model(
            [
                {
                    "edits": [_edit("set_objection", objection="Not interested", text="సరే అండి.")],
                    "facts": [],
                }
            ]
        ),
    )
    stop, record = await worker.improve_run(tenant_id, agent_id, run_id, keys=["k1"])
    assert stop == "completed" and record is not None
    assert record["edits"][0]["because"] == "k1"
    assert record["edits"][0]["after"] == "సరే అండి."
    async with tenant_session(tenant_id) as session:
        stored = await test_conversations.get_run(session, agent_id, run_id)
        improve_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM usage_events WHERE tenant_id = :t "
                    "AND meta->>'feature' = 'agent_test_improve'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert stored.improvement is not None and stored.improvement["for_keys"] == ["k1"]
    assert stored.improve_stop == "completed"
    assert improve_rows > 0

    # At the allowance ceiling the paid leg is not used: the platform's own standby model
    # answers (absorbed, `meter_assist`'s standby branch), so the client's allowance does not
    # move. The routes refuse before this point (`require_ai_assist`). A new run's failure
    # is a new question, so it is asked.
    second = await _failed_run(
        tenant_id, agent_id, [{**NOT_INTERESTED, "key": "k2", "reason": "It argued."}]
    )

    async def _used_up(_tenant: uuid.UUID) -> bool:
        return True

    legs: list[str] = []
    standby_answer: dict[str, Any] = {"edits": [], "facts": []}

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any) -> Any:
        legs.append(leg.dialect)
        return chat.ChatOutcome(content=json.dumps(standby_answer), finish_reason="stop")

    monkeypatch.setattr(worker, "_allowance_used", _used_up)
    monkeypatch.setattr(chat, "complete", _complete)
    stop, _ = await worker.improve_run(tenant_id, agent_id, second, keys=None)
    assert legs == ["sarvam"]
    # Nothing found is said plainly and recorded as the round's stop reason.
    assert stop == "no_change"
    async with tenant_session(tenant_id) as session:
        after = (
            await session.execute(
                text(
                    "SELECT count(*) FROM usage_events WHERE tenant_id = :t "
                    "AND meta->>'feature' = 'agent_test_improve'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
        stopped = await test_conversations.get_run(session, agent_id, second)
    assert after == improve_rows
    assert stopped.improve_stop == "no_change" and stopped.improve_note == worker.NO_EDITS_NOTE

    # The same question again, with nothing changed, is never asked again.
    legs.clear()
    stop, _ = await worker.improve_run(tenant_id, agent_id, second, keys=None)
    assert stop == "no_change" and legs == []
    async with tenant_session(tenant_id) as session:
        again = await test_conversations.get_run(session, agent_id, second)
    assert again.improve_note == worker.SAME_INPUT_NOTE


async def test_a_platform_or_setting_failure_is_never_sent_to_the_improver(
    azure: None,
) -> None:
    tenant_id, agent_id = await _agent()
    run_id = await _failed_run(
        tenant_id,
        agent_id,
        [
            {"key": "probe_ai", "title": "AI", "verdict": "failed", "fix": "platform"},
            {"key": "probe_person", "title": "Person", "verdict": "needs_fix", "owner": "setting"},
        ],
    )
    with pytest.raises(ProblemError) as refused:
        await worker.improve_run(tenant_id, agent_id, run_id, keys=None)
    assert refused.value.code == "agent_tests_nothing_fixable_by_script"
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as asked:
            await test_conversations.request_improvement(
                session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, keys=None
            )
    assert asked.value.code == "agent_tests_nothing_fixable_by_script"


@pytest.mark.rls
async def test_a_neighbours_run_cannot_be_read_or_improved() -> None:
    tenant_a, agent_a = await _agent()
    tenant_b, _ = await _agent()
    async with tenant_session(tenant_a) as session:
        run = await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, created_at, "
                "updated_at) VALUES (:id, :t, :a, 'done', now(), now()) RETURNING id"
            ),
            {"id": uuid.uuid4(), "t": tenant_a, "a": agent_a},
        )
        run_id = run.scalar_one()
    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError):
            await test_conversations.get_run(session, agent_a, run_id)
        assert await test_conversations.recent_runs(session, agent_a) == []
