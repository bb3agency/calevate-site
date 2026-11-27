"""The rebuilt script writer (DESIGN §3, 26 Nov 2026): the plan by code, each step written by
its own small request, one applier, one check seam, and every caller through
`write_script`. The model is a fake: English placeholders only, never hand-written Telugu or
Hindi (the call language here is English)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from apps.api.agents import test_fixes
from apps.api.agents.owner_plan import owner_plan
from apps.api.agents.script_plan import (
    BUSY_WAY_OUT,
    EXAMPLE_LIMITS,
    NOT_FOR_THEM_WAY_OUT,
    outline_problems,
    plan_from_owner,
    plan_from_playbook,
    plan_from_script,
    skeleton,
    with_base_ids,
)
from apps.api.agents.trade_playbooks import OPENING_STEP_TITLES
from apps.workers import campaign_script, script_writer, step_writer
from apps.workers.extraction import AssistCapability
from apps.workers.opening_line import WrittenOpening
from apps.workers.script_assist import JsonAnswer, ScriptBrief, UnusableAnswerError
from apps.workers.script_context import ScriptContext
from apps.workers.script_writer import OutcomesAsk, WriteRequest, write_script
from apps.workers.step_writer import StepAsk, parsed_step, step_request
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    CallScript,
    ConversationStage,
    StageBranch,
    StepExamples,
)
from calevate_shared.opening_notices import SaidNotices

LANG = "en-IN"
CAP = AssistCapability(available=True)

OWNER_STEPS = (
    "Steps, in this order: "
    "1. Install: Help them install the app. Outcome: The farmer says the app is installed. "
    "- Cannot install: offer a call back. "
    "2. Login: Help them log in with their number. Outcome: The farmer says they are logged in. "
    '- Not registered: go to "Register". '
    "3. Close: Thank them and end the call. Outcome: The farmer has no more questions. "
    "Register: Help them register first. - Registered: go to Login."
)


def _context(**changes: Any) -> ScriptContext:
    base = ScriptContext(
        tenant_id=uuid4(),
        kind="campaign",
        holder_id=uuid4(),
        agent_id=uuid4(),
        brief=ScriptBrief(
            business_name="Acme Farms",
            agent_name="Asha",
            direction="outbound",
            language=LANG,
        ),
        main_task="Help farmers install the Acme app and log in.",
        saved=None,
        asked_from=None,
        words=(("Guide", "Open the Play Store. Search Acme. Tap Install. Then open Acme."),),
    )
    return replace(base, **changes)


def _stage(sid: str, name: str, step: int, **kw: Any) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=f"Do {name}.", step=step, **kw)


def _script() -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line="Hello {{lead_name}}, this is Asha from Acme Farms about the app; is now ok?",
        stages=[
            _stage(
                "install",
                "Install",
                1,
                branches=[StageBranch(when="They are busy", target=CALL_BACK)],
                examples={LANG: StepExamples(turns=["Open the Play Store.", "Find Acme.", "x"])},
            ),
            _stage("login", "Login", 2),
            _stage("close", "Close", 3),
        ],
    )


# --- the fake model ------------------------------------------------------------------------

_STEP_NAME = re.compile(r'THIS STEP: "([^"]+)"')


def _good(name: str, first: bool = False) -> dict[str, Any]:
    tag = name.casefold()[::-1]
    return {
        "instruction": f"Guide the person through {name}.",
        "procedure": [{"action": f"Have them start {name}", "wait_for": "They say it opened"}],
        "examples": {
            LANG: {
                # Placeholder words made from the step's name, the name said once: no two
                # steps' lines open, end or read alike, and none gives two actions.
                "turns": [f"{tag} {name}", f"{tag}a {name}", f"{tag}b {name}"],
                "confused": f"{tag}c {name}",
                "stuck": f"{tag}d {name}",
                "busy": "When would suit you better?" if first else "",
            }
        },
        "qa": [],
    }


class FakeModel:
    """Answers each step request from `answer(name, request)`; records every request."""

    def __init__(self, answer: Callable[[str, str], dict[str, Any]] | None = None) -> None:
        self.requests: list[str] = []
        self.answer = answer or (lambda name, _req: _good(name))

    async def __call__(self, description: str, instruction: str, **kw: Any) -> JsonAnswer[Any]:
        self.requests.append(description)
        if instruction == step_writer.STEP_INSTRUCTION:
            found = _STEP_NAME.search(description)
            assert found is not None
            raw = self.answer(found.group(1), description)
        elif instruction == step_writer.FRAME_INSTRUCTION:
            raw = {
                "identity": "Helps farmers set up the Acme app.",
                "goal": "The farmer uses the app.",
                "business_line": "Acme Farms makes a farm app.",
                "outbound_purpose": "We call to help set up the app.",
                "ending": "Thank them and say goodbye.",
                "objections": [],
            }
        elif instruction == step_writer.PARTS_INSTRUCTION:
            raw = {"parts": [{"path": "goal", "text": "The farmer finishes set up."}]}
        else:
            raw = {"steps": []}
        return JsonAnswer(value=kw["parse"](raw), capability=CAP, model="fake")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    model = FakeModel()
    monkeypatch.setattr(step_writer, "ask_json", model)
    monkeypatch.setattr(script_writer, "ask_json", model)

    async def opening(brief: ScriptBrief, **kw: Any) -> JsonAnswer[WrittenOpening]:
        line = "Hello {{lead_name}}, this is Asha from Acme Farms about the app; can we talk?"
        return JsonAnswer(
            value=WrittenOpening(line=line, said=SaidNotices()), capability=CAP, model="fake"
        )

    monkeypatch.setattr(script_writer, "write_opening", opening)
    return model


# --- the plan ------------------------------------------------------------------------------


def test_owner_plan_becomes_the_structure_with_side_steps_and_required_ways() -> None:
    plan = owner_plan(OWNER_STEPS)
    assert plan is not None
    built = plan_from_owner(plan, placed=True)
    assert [s.name for s in built.steps] == ["Install", "Login", "Close", "Register"]
    register = built.step(built.keys[3])
    # Reached from Login, so a scenario of the step after it (`OwnerPlan.side_home`).
    assert register is not None and register.side and register.number == 3
    first = built.steps[0]
    assert {w.to for w in first.ways_out} >= {CALL_BACK, END_OF_CALL}
    assert any(w.when == NOT_FOR_THEM_WAY_OUT for w in first.ways_out)
    # The owner's own call back is in its last-resort form; "busy" was added once only.
    assert sum(w.when == BUSY_WAY_OUT for w in first.ways_out) == 0
    assert all(s.owners for s in built.steps)


def test_a_step_that_is_only_an_end_point_is_never_a_step() -> None:
    plan = owner_plan(
        "1. Ask: Ask if they want it. Outcome: They say yes or no. - No: go to Call back. "
        "2. Call back: Offer a call back. Outcome: A time is agreed."
    )
    assert plan is not None
    built = plan_from_owner(plan)
    assert [s.name for s in built.steps] == ["Ask"]
    assert built.steps[0].ways_out[0].to == CALL_BACK


def test_playbook_for_a_placed_call_never_redoes_the_opening() -> None:
    plan = plan_from_playbook("custom", placed=True)
    assert not {s.name for s in plan.steps} & OPENING_STEP_TITLES
    assert plan.steps[0].ways_out  # busy and not interested, by code


def test_outline_that_redoes_the_opening_is_refused() -> None:
    plan = plan_from_owner(
        owner_plan(
            "1. Good time: Ask if now is a good time. Outcome: They can talk. "
            "2. Close: Thank them. Outcome: Done."
        )  # type: ignore[arg-type]
    )
    assert any("good time" in p for p in outline_problems(plan))


def test_skeleton_and_plan_from_script_round_trip() -> None:
    script = _script()
    again = skeleton(plan_from_script(script), script)
    assert [s.id for s in again.stages] == ["install", "login", "close"]
    assert again.stages[0].branches == script.stages[0].branches
    assert again.opening_line == script.opening_line


def test_a_rewrite_keeps_the_base_step_ids_by_name() -> None:
    plan = owner_plan(OWNER_STEPS)
    assert plan is not None
    kept = with_base_ids(plan_from_owner(plan), _script())
    assert kept.keys[:2] == ("install", "login")


# --- the step request and its parse -------------------------------------------------------


def test_one_step_request_is_small_and_holds_only_what_that_step_needs() -> None:
    context = _context(words=(("Doc", "Login screen. " * 4000),))
    plan = plan_from_script(_script())
    ask = StepAsk(
        brief=context.written_brief(),
        plan=plan,
        step=plan.steps[1],
        languages=(LANG,),
        opening=_script().opening_line,
        main_task=context.main_task,
        sources=context.grounding,
    )
    text = step_request(ask)
    assert len(text) + len(step_writer.STEP_INSTRUCTION) < 5_000
    assert 'THIS STEP: "Login"' in text and "already said" in text
    assert 'The step before: "Install"' in text
    # The step after is named so this one leaves its job to it (27 Nov 2026: the
    # Introduction pitched what the next step was for).
    assert '(leave it to that step): "Close": Do Close.' in text
    last = step_request(replace(ask, step=plan.steps[2]))
    assert "The step after" not in last


def test_the_parse_refuses_a_non_english_instruction_and_too_few_turns() -> None:
    raw = _good("Login")
    raw["examples"][LANG]["turns"] = ["Only one."]
    with pytest.raises(UnusableAnswerError, match="turns"):
        parsed_step(raw, languages=(LANG,), first=False, close=False)
    raw = _good("Login")
    raw["instruction"] = "".join(chr(0x0C15 + i) for i in range(4))  # Indic letters, not words
    with pytest.raises(UnusableAnswerError, match="English"):
        parsed_step(raw, languages=(LANG,), first=False, close=False)


def test_busy_is_kept_only_on_the_first_step() -> None:
    raw = _good("Login", first=True)
    assert parsed_step(raw, languages=(LANG,), first=False, close=False).examples[LANG].busy == ""
    assert parsed_step(raw, languages=(LANG,), first=True, close=False).examples[LANG].busy


# --- write_script, per mode ---------------------------------------------------------------


async def test_whole_writes_every_step_from_the_owner_plan(fake: FakeModel) -> None:
    context = _context(instruction=OWNER_STEPS)
    result = await write_script(WriteRequest("whole", context))
    names = [s.name for s in result.script.stages]
    assert names == ["Install", "Login", "Close", "Register"]
    assert all(s.examples.get(LANG) and s.examples[LANG].turns for s in result.script.stages)
    assert all(not s.sounds_like for s in result.script.stages)
    assert result.script.opening_line  # written by the opening writer
    assert result.plan is not None and result.plan.source == "owner"
    step_requests = [r for r in fake.requests if "THIS STEP" in r]
    assert len(step_requests) == 4
    assert max(len(r) for r in step_requests) < 4_000


async def test_a_failing_step_is_rewritten_alone_with_its_problems(fake: FakeModel) -> None:
    seen: dict[str, int] = {}

    def answer(name: str, request: str) -> dict[str, Any]:
        seen[name] = seen.get(name, 0) + 1
        raw = _good(name)
        if name == "Login" and seen[name] == 1:
            raw["examples"][LANG]["turns"][0] = "Very good. Start Login on your phone now."
        return raw

    fake.answer = answer
    result = await write_script(WriteRequest("whole", _context(instruction=OWNER_STEPS)))
    assert seen["Login"] == 2
    assert all(n == 1 for k, n in seen.items() if k != "Login")
    again = [r for r in fake.requests if 'THIS STEP: "Login"' in r][-1]
    assert "failed these checks" in again and "reaction" in again
    login = next(s for s in result.script.stages if s.name == "Login")
    assert not login.examples[LANG].turns[0].startswith("Very good")


async def test_steps_mode_rewrites_only_the_named_step(fake: FakeModel) -> None:
    base = _script()
    result = await write_script(
        WriteRequest("steps", _context(), base=base, step_ids=("login",), notes={"login": "x"})
    )
    assert result.script.stages[0] == base.stages[0]
    assert result.script.stages[2] == base.stages[2]
    assert result.script.stages[1].examples[LANG].turns


async def test_examples_only_keeps_the_instruction_word_for_word(fake: FakeModel) -> None:
    base = _script()
    result = await write_script(
        WriteRequest(
            "steps",
            _context(),
            base=base,
            step_ids=("login",),
            fields=campaign_script.EXAMPLES_ONLY,
        )
    )
    login = result.script.stages[1]
    assert login.instruction == base.stages[1].instruction
    assert login.procedure == base.stages[1].procedure
    assert login.examples[LANG].turns


async def test_lines_mode_takes_only_the_fields_at_the_paths(fake: FakeModel) -> None:
    base = _script().model_copy(update={"goal": "Old goal."})
    problems = ("stages.1.instruction: is vague", "goal: says too little")
    result = await write_script(
        WriteRequest("lines", _context(), base=base, problems=problems, check=lambda _s: [])
    )
    assert result.script.stages[1].instruction == "Guide the person through Login."
    assert result.script.stages[1].examples == base.stages[1].examples
    assert result.script.stages[0] == base.stages[0]
    assert result.script.goal == "The farmer finishes set up."


async def test_a_repair_is_written_with_the_holders_full_context(fake: FakeModel) -> None:
    """The repair-context defect (01 §1, `_repair_draft`): a repair now carries the main task,
    the sources, the call direction, the opening and the language."""
    await write_script(
        WriteRequest(
            "lines",
            _context(),
            base=_script(),
            problems=("stages.0.instruction: is vague",),
            check=lambda _s: [],
        )
    )
    request = next(r for r in fake.requests if "THIS STEP" in r)
    assert "install the Acme app" in request
    assert "The agent places this call." in request
    assert "already said" in request and LANG in request
    assert "Play Store" in request  # a source passage about the step


async def test_outcomes_mode_runs_the_outcomes_request(fake: FakeModel) -> None:
    ask = OutcomesAsk(
        request="the outcomes request",
        instruction="outcomes",
        parse=lambda raw: "parsed",
        salvage=lambda raw: None,
        azure_format={"type": "json_object"},
        max_tokens=100,
    )
    result = await write_script(WriteRequest("outcomes", _context(), base=_script(), outcomes=ask))
    assert result.value.value == "parsed"
    assert fake.requests == ["the outcomes request"]


async def test_opening_mode_writes_the_opening(fake: FakeModel) -> None:
    result = await write_script(WriteRequest("opening", _context(), base=_script()))
    assert result.script.opening_line.endswith("can we talk?")
    assert result.script.stages == _script().stages


async def test_nothing_written_is_a_refusal_with_its_spends(
    fake: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.errors import ProblemError

    async def refuse(*_a: Any, **_k: Any) -> Any:
        raise ProblemError.business_rule("assist_quota_exhausted", "Used up.")

    monkeypatch.setattr(step_writer, "ask_json", refuse)
    with pytest.raises(script_writer.WriteRefusedError) as raised:
        await write_script(WriteRequest("steps", _context(), base=_script(), step_ids=("login",)))
    assert raised.value.refused.code == "assist_quota_exhausted"
    assert len(raised.value.spends) == 1


# --- the callers ---------------------------------------------------------------------------


def test_the_holder_writer_maps_each_ask_to_one_mode() -> None:
    base = _script()
    started = time.monotonic()
    assert campaign_script.write_request(_context(), started).mode == "whole"
    edit = campaign_script.write_request(_context(asked_from=base), started)
    assert edit.mode == "whole" and edit.base == base
    rewrite = campaign_script.write_request(_context(asked_from=base, rewrite=True), started)
    assert rewrite.base is None
    step = campaign_script.write_request(
        _context(asked_from=base, part="Step “Login”", part_language="English"), started
    )
    assert (step.mode, step.step_ids) == ("steps", ("login",))
    examples = campaign_script.write_request(
        _context(asked_from=base, part="Step “Login”", part_language="English", want="examples"),
        started,
    )
    assert examples.fields == campaign_script.EXAMPLES_ONLY
    opening = campaign_script.write_request(
        _context(asked_from=base, part="The opening line", part_language="English"), started
    )
    assert opening.mode == "opening"
    flow = campaign_script.write_request(
        _context(asked_from=base, part="flow", part_language="English"), started
    )
    assert flow.mode == "whole" and flow.outline


def test_one_lint_context_carries_the_holders_language_details_and_direction() -> None:
    from apps.api.agents.script_builder import JobDetails
    from calevate_shared.call_script import CollectField

    context = _context(
        details=JobDetails(asked=(CollectField(label="Crop"),), judged=("Mood",)),
        brief=replace(_context().brief, language="hi-IN"),
    )
    lint = context.lint()
    assert lint.language == "hi-IN"
    assert lint.collect == ("Crop",) and lint.judged == ("Mood",)
    assert lint.places_calls is True
    assert "install the Acme app" in lint.facts


def test_languages_and_limits() -> None:
    context = _context(extra_languages=("hi-IN", LANG))
    assert context.languages == (LANG, "hi-IN")
    # A call whose main language is not English gets no English examples; Hindi stays.
    telugu = replace(context, brief=replace(context.brief, language="te-IN"))
    assert replace(telugu, extra_languages=(LANG, "hi-IN")).languages == ("te-IN", "hi-IN")
    assert _context(part="Step “Login”").languages == (LANG,)
    assert context.limits == EXAMPLE_LIMITS
    assert EXAMPLE_LIMITS.turns_min == step_writer.MIN_TURNS


def test_practice_test_fixes_name_the_steps_the_writer_writes() -> None:
    base = _script()
    edits = [
        {"op": "set_step", "step_id": "login", "text": "Ask for the number they registered."},
        {"op": "set_part", "part": "opening_line", "text": "Hi"},
    ]
    script, notes = test_fixes.fixed_steps(base, edits)
    assert notes == {"login": "Ask for the number they registered."}
    assert script.opening_line == base.opening_line


def test_the_step_answer_schema_names_every_call_language() -> None:
    schema = step_writer.step_format((LANG, "hi-IN"))
    props = schema["json_schema"]["schema"]["properties"]  # type: ignore[index]
    assert set(props["examples"]["properties"]) == {LANG, "hi-IN"}
    json.dumps(schema)


def test_a_long_instruction_is_cut_to_fit_the_step_detail_with_its_examples_pointer() -> None:
    from calevate_shared.call_script import STAGE_DETAIL_MAX

    words = step_writer.StepWords(
        instruction=("Guide them gently through the whole thing. " * 20)[:STAGE_DETAIL_MAX],
        examples={LANG: StepExamples(turns=["Open it.", "Tap it.", "Find it."])},
    )
    stage = script_writer.stage_with(_script().stages[1], words)
    assert stage.examples[LANG].turns
    assert len(stage.instruction) < STAGE_DETAIL_MAX
