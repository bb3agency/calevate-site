"""The owner's own steps are the script's steps (25 Nov 2026).

The founder asked Pip to rewrite the Rytu Khata campaign script to eleven steps he laid out,
each with its outcome and its ways out. The writer imposed its own plan instead: the main
task's old install steps, Login twice, call back and end call as steps, an outcome about the
phone type, and five of his steps missing. For any business:

1. The plan is read from the owner's words, folded onto one line or not, and a request that
   lays out no steps (prose, or a numbered list of changes) yields none.
2. Each departure is named: a step missing, duplicated, out of order or not the owner's, an
   outcome missing, an owner's way out missing or one they did not name, an end point
   written as a step. A script that keeps the plan has none.
3. The writer sends a departing draft back with the mismatch and keeps one that matches; the
   trade's step plan is not given beside the owner's.
4. A campaign whose request lays out the steps is written whole, not as an edit of the old
   script, and the ask shows the owner's steps instead of the main task's items.

The model is never called: the provider is faked one layer below the ladder.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.owner_plan import (
    name_key,
    owner_plan,
    plan_block,
    plan_problems,
    with_owner_plan,
)
from apps.api.agents.script_structure import renumbered
from apps.api.campaigns import workspace
from apps.api.core import provider_health
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers import campaign_script, chat, script_assist
from apps.workers import script_proposal as proposal_worker
from apps.workers.campaign_script_ask import PLAN_HEAD, campaign_change
from apps.workers.extraction import TenantModelLeg
from apps.workers.script_assist import ScriptBrief
from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    StageBranch,
    StepOutcome,
)
from scripts import eval_script_writer as ev
from tests.campaign_script_writer_2026_11_15_test import LINT, _answer, _campaign

GOOGLE_LEG = TenantModelLeg(model="gemini-3.1-flash-lite", provider="google", serves_dashboard=True)

RYTU = ev.load_cases(["rytu_khata_owner_steps"])[0]

#: A small plan of another trade, so nothing here is fitted to one business.
DELIVERY = (
    "Write it warmly. Steps, in this order:\n"
    "1. Welcome back: say we are calling about their order and ask if now suits. "
    "Outcome: They agreed to talk.\n"
    "   - Busy now: offer a call back.\n"
    '   - Not a customer: go to "Wrong person".\n'
    "2. Delivery day: ask which day suits them for the delivery. Outcome: They chose a "
    "delivery day.\n"
    "   - No day suits: offer a call back.\n"
    "3. Close: thank them and end the call. Outcome: The call is finished.\n"
    "Wrong person: say sorry for the trouble. Then: end the call."
)


def _stage(
    sid: str,
    name: str,
    step: int,
    *,
    branches: Sequence[tuple[str, str]] = (),
    otherwise: str = "",
    instruction: str = "Help them with this step.",
) -> ConversationStage:
    return ConversationStage(
        id=sid,
        name=name,
        step=step,
        instruction=instruction,
        sounds_like="Shall we go on?",
        branches=[StageBranch(when=when, target=target) for when, target in branches],
        otherwise=otherwise,
    )


def _kept_delivery() -> CallScript:
    return CallScript(
        schema_version=2,
        stages=[
            _stage(
                "s1",
                "Welcome back",
                1,
                branches=[("They are busy now", "call_back"), ("Not a customer", "s2")],
                otherwise="s3",
            ),
            _stage("s2", "Wrong person", 1, branches=[("They heard the apology", "end")]),
            _stage("s3", "Delivery day", 2, branches=[("No day suits them", "call_back")]),
            _stage("s4", "Close", 3, instruction="Thank them and end the call.", otherwise="end"),
        ],
        step_outcomes=[
            StepOutcome(step=1, outcome="They agreed to talk."),
            StepOutcome(step=2, outcome="They chose a delivery day."),
            StepOutcome(step=3, outcome="The call is finished."),
        ],
    )


# --- 1. reading the plan ---------------------------------------------------------------------


@pytest.mark.parametrize("folded", [False, True])
def test_the_owners_steps_are_read_with_their_outcomes_branches_and_side_step(
    folded: bool,
) -> None:
    """FAILS IF: a step, its outcome, a way out or the named side step is lost, or the list
    is read only when it keeps its line breaks (Pip folds the request onto one line)."""
    text = " ".join(RYTU.instruction.split()) if folded else RYTU.instruction
    plan = owner_plan(text)
    assert plan is not None
    assert [s.name for s in plan.steps] == [
        "Introduction",
        "App on the home screen",
        "Login",
        "Language",
        "My Farms",
        "First expense",
        "First sale",
        "Dashboard",
        "Close",
        "Not registered",
    ]
    first, home = plan.steps[0], plan.steps[1]
    assert first.outcome == "They agreed to talk now."
    assert [(b.when, b.goes_to) for b in first.branches] == [
        ("Busy now", "call_back"),
        ("Not interested", "end"),
        ("Says they never registered", "Not registered"),
    ]
    assert [(b.when, b.goes_to) for b in home.branches] == [
        ("Already has it", "Login"),
        ("Cannot open the website", "call_back"),
    ]
    side = plan.steps[-1]
    assert side.number is None and "registered with us earlier" in side.instruction
    assert [(b.when, b.goes_to) for b in side.branches] == [
        ("Yes", "App on the home screen"),
        ("No", "end"),
    ]
    # The rules after the plan are not a step.
    assert plan.named("Rules") is None


@pytest.mark.parametrize(
    "text",
    [
        "Make it warmer and shorter. Ask about their order first.",
        "1. Change the opening: make it shorter 2. Login: say it slower",
        "1. Install the app. 2. Set the language. 3. Add a farm.",
    ],
)
def test_a_request_that_lays_out_no_steps_has_no_plan(text: str) -> None:
    """FAILS IF: prose, a numbered list of changes, or a main task's unnamed items are read
    as the owner's steps, which would make every such request a whole rewrite."""
    assert owner_plan(text) is None


def test_names_compare_without_case_spacing_or_a_step_prefix() -> None:
    assert name_key("Log in") == name_key("Login") == name_key("Step 3: LOGIN")
    assert name_key("App on home screen") != name_key("App on the home screen")


# --- 2. what departs from it ---------------------------------------------------------------


def test_the_25_nov_canvas_is_named_on_every_departure() -> None:
    """FAILS IF: any defect of the production rewrite passes: the wrong order, Login twice,
    call back and end call as steps, steps the owner never asked for, the owner's missing
    steps, or the owner's ways out it lacks."""
    script = ev.load_recorded(RYTU).script
    found = plan_problems(script, owner_plan(RYTU.instruction))
    text = "\n".join(found)
    for missing in ("App on the home screen", "Language", "My Farms", "First sale", "Dashboard"):
        assert f'"{missing}" is missing' in text
    assert 'the owner\'s step "Not registered" is missing' in text
    assert '"Login" is written as 2 steps' in text
    for end_point in ("Call back", "End call"):
        assert f'"{end_point}" is written as a step of its own' in text
    for extra in ("Android install", "iPhone install", "Enter Expense", "Finalise the call"):
        assert f'"{extra}" is a step the owner did not ask for' in text
    # A scenario of one of the owner's steps is the writer's to add.
    assert '"Password issues" is a step' not in text
    # The recorded file is scored as the eval reads it.
    assert ev.owner_plan_kept(ev.load_recorded(RYTU), RYTU) == found


def test_a_script_that_keeps_the_plan_has_no_departure() -> None:
    assert plan_problems(_kept_delivery(), owner_plan(DELIVERY)) == []


def test_code_mends_keep_a_side_step_and_the_step_after_it_apart() -> None:
    """FAILS IF: the step a step goes on to by default, after a side step placed between them,
    is renumbered into the same step as the side step, which reorders the owner's steps."""
    mended = renumbered(_kept_delivery())
    assert [s.step for s in mended.stages] == [1, 1, 2, 3]
    assert plan_problems(mended, owner_plan(DELIVERY)) == []


def test_reordered_dropped_duplicated_and_extra_ways_out_are_each_named() -> None:
    plan = owner_plan(DELIVERY)
    kept = _kept_delivery()
    s1, s2, s3, s4 = kept.stages

    reordered = kept.model_copy(
        update={
            "stages": [
                s1,
                s2,
                s4.model_copy(update={"step": 2}),
                s3.model_copy(update={"step": 3, "otherwise": "end"}),
            ]
        }
    )
    assert any("not in the owner's order" in p for p in plan_problems(reordered, plan))

    dropped = kept.model_copy(update={"stages": [s1.model_copy(update={"branches": []}), s3, s4]})
    found = plan_problems(dropped, plan)
    assert any('"Wrong person" is missing' in p for p in found)
    assert any('way out "Busy now" going to call_back' in p for p in found)

    twice = kept.model_copy(
        update={"stages": [s1, s2, s3, s3.model_copy(update={"id": "s5", "step": 3}), s4]}
    )
    assert any('"Delivery day" is written as 2 steps' in p for p in plan_problems(twice, plan))

    # The owner gave step 2 only a call back; an end of the writer's own is not theirs.
    extra = kept.model_copy(
        update={
            "stages": [
                s1,
                s2,
                s3.model_copy(
                    update={"branches": [*s3.branches, StageBranch(when="Not keen", target="end")]}
                ),
                s4,
            ]
        }
    )
    assert any("which the owner did not give step" in p for p in plan_problems(extra, plan))


def test_an_empty_outcome_is_named_and_the_owners_outcome_and_name_are_kept_by_code() -> None:
    """FAILS IF: a step the owner gave an outcome reaches the canvas with none, or a model's
    paraphrase of the owner's step name or outcome is kept."""
    plan = owner_plan(DELIVERY)
    kept = _kept_delivery()
    bare = kept.model_copy(
        update={
            "stages": [
                kept.stages[0].model_copy(update={"name": "WELCOME BACK"}),
                *kept.stages[1:],
            ],
            "step_outcomes": [StepOutcome(step=1, outcome="Phone type confirmed.")],
        }
    )
    assert any("has no outcome" in p for p in plan_problems(bare, plan))
    pinned = with_owner_plan(bare, plan)
    assert pinned.stages[0].name == "Welcome back"
    assert [(o.step, o.outcome) for o in pinned.step_outcomes] == [
        (1, "They agreed to talk."),
        (2, "They chose a delivery day."),
        (3, "The call is finished."),
    ]
    assert plan_problems(pinned, plan) == []


def test_the_ask_shows_the_owners_steps_in_place_of_the_main_tasks_items() -> None:
    """FAILS IF: the main task's numbered items (the old plan) are still listed as the steps
    to cover when the owner laid out their own."""
    plan = owner_plan(RYTU.instruction)
    assert plan is not None
    change = campaign_change(
        RYTU.main_task, "", "", edit=False, instruction=RYTU.instruction, plan=plan
    )
    assert PLAN_HEAD in change and plan_block(plan) in change
    assert "THE MAIN TASK'S ITEMS" not in change
    without = campaign_change(RYTU.main_task, "", "", edit=False)
    assert "THE MAIN TASK'S ITEMS" in without and PLAN_HEAD not in without


# --- 3. the writer -------------------------------------------------------------------------


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    for name in ("azure_openai_resource", "azure_openai_api_key", "azure_openai_deployment"):
        monkeypatch.setattr(settings, name, None, raising=False)

    async def _quiet(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(provider_health, "note_failure", _quiet)
    monkeypatch.setattr(provider_health, "note_success", _quiet)


def _answers(monkeypatch: pytest.MonkeyPatch, google: list[dict[str, Any]]) -> list[str]:
    """Fake the provider one layer below the ladder; each Gemini request's user text."""
    asked: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        asked.append(messages[-1]["content"])
        return chat.ChatOutcome(
            content=json.dumps(google[min(len(asked), len(google)) - 1]),
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(chat, "complete", _complete)
    return asked


_LINES = {
    "Welcome back": "Your order is packed and ready.",
    "Wrong person": "Sorry for the trouble.",
    "Delivery day": "Which day suits you for the delivery?",
    "Close": "Thank you, have a good day.",
    "Call back": "When can we call you back?",
}


def _draft(rows: Sequence[tuple[str, int, list[dict[str, str]]]]) -> dict[str, Any]:
    """A whole-draft answer in the model's shape, one stage per (name, step, ways_out)."""
    return {
        "business_line": "We deliver groceries to homes.",
        "identity": "Calls customers about their grocery delivery.",
        "goal": "Agree a delivery day.",
        "outbound_purpose": "",
        "opening_line": "Hello, this is the grocery shop.",
        "tone": "warm, short sentences",
        "address_form": "by name",
        "code_mix": "light",
        "sample_phrases": [],
        "pronunciations": [],
        "stages": [
            {
                "name": name,
                "step": step,
                "instruction": "Thank them and end the call."
                if name == "Close"
                else f"Do the {name.lower()} step.",
                "sounds_like": _LINES[name],
                "exit_when": "",
                "ways_out": ways,
                **({"next": [0]} if name == "Close" else {}),
            }
            for name, step, ways in rows
        ],
        "step_outcomes": [{"step": 1, "outcome": "Done."}],
        "objections": [],
        "ending": "Thank them and end the call.",
        "quick_facts": [],
        "example_exchange": [],
    }


_KEPT_ROWS: list[tuple[str, int, list[dict[str, str]]]] = [
    (
        "Welcome back",
        1,
        [{"when": "They are busy now", "to": "call_back"}, {"when": "Not a customer", "to": "2"}],
    ),
    ("Wrong person", 1, [{"when": "They heard the apology", "to": "end"}]),
    ("Delivery day", 2, [{"when": "No day suits them", "to": "call_back"}]),
    ("Close", 3, []),
]
_DEPARTING_ROWS: list[tuple[str, int, list[dict[str, str]]]] = [
    ("Welcome back", 1, [{"when": "They are busy now", "to": "4"}]),
    ("Close", 2, []),
    ("Delivery day", 3, [{"when": "No day suits them", "to": "4"}]),
    ("Call back", 4, []),
]


async def test_a_departing_draft_is_sent_back_with_the_mismatch_and_a_kept_one_is_kept(
    gemini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a draft that reorders, drops or adds to the owner's steps, or makes call back
    a step, reaches the owner without being sent back naming each departure; or a draft that
    keeps the plan is refused; or the trade's step plan is put beside the owner's."""
    asked = _answers(monkeypatch, [_draft(_DEPARTING_ROWS), _draft(_KEPT_ROWS)])
    plan = owner_plan(DELIVERY)
    draft = await script_assist.draft_script(
        ScriptBrief(language="en-IN", business_type="retail", owner_plan=plan),
        tenant_leg=GOOGLE_LEG,
    )
    assert len(asked) == 2
    assert "Step plan for this kind of business" not in asked[0]
    repair = asked[1]
    assert "not in the owner's order" in repair
    assert '"Wrong person" is missing' in repair
    assert '"Call back" is written as a step of its own' in repair
    script = draft.script
    assert [stage.name for stage in script.stages] == [
        "Welcome back",
        "Wrong person",
        "Delivery day",
        "Close",
    ]
    assert not any(stage.name == "Call back" for stage in script.stages)
    assert [o.outcome for o in script.step_outcomes] == [
        "They agreed to talk.",
        "They chose a delivery day.",
        "The call is finished.",
    ]
    assert plan_problems(script, plan) == []


async def test_without_an_owners_plan_the_trades_step_plan_is_still_given(
    gemini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answers(monkeypatch, [_draft(_KEPT_ROWS)])
    # Whether this answer passes without the plan's outcomes is beside the point.
    with contextlib.suppress(ProblemError):
        await script_assist.draft_script(
            ScriptBrief(language="en-IN", business_type="retail"), tenant_leg=GOOGLE_LEG
        )
    assert "Step plan for" in asked[0]


# --- 4. the campaign job -------------------------------------------------------------------


@pytest.mark.rls
async def test_a_request_with_the_owners_steps_is_written_whole_from_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a campaign whose request lays out the steps is written as an edit of its old
    script (whose steps an edit keeps and puts back), or the writer is not given the plan."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    old = CallScript(
        schema_version=2,
        stages=[
            ConversationStage(id="login", name="Login", instruction="Ask them to log in."),
            ConversationStage(id="close", name="Close", instruction="Thank them."),
        ],
    )
    tenant_id, campaign_id = await _campaign(old)
    async with tenant_session(tenant_id) as session:
        requested = await workspace.request_proposal(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            requested_by=None,
            ask={"instruction": " ".join(DELIVERY.split())},
        )
    calls: list[dict[str, Any]] = []

    async def write(brief: Any, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        return _answer(_kept_delivery())

    async def lint_context(*_args: Any, **_kwargs: Any) -> Any:
        return LINT

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript, **_kw: Any) -> Any:
        return script, []

    async def quiet(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "lint_context_for", lint_context)
    monkeypatch.setattr(proposal_worker, "_opening_repaired", openings)
    monkeypatch.setattr(campaign_script.crm_assist, "meter_assist", quiet)
    monkeypatch.setattr(campaign_script.crm_assist, "meter_earlier", quiet)
    payload = {
        "tenant_id": str(tenant_id),
        "campaign_id": str(campaign_id),
        "proposal_id": str(requested.id),
    }
    assert await campaign_script.draft_campaign_script({}, payload) == "ready"
    first = calls[0]
    assert "edit_of" not in first
    assert first["brief"].owner_plan == owner_plan(DELIVERY)
    assert PLAN_HEAD in first["brief"].description
    assert "Keep anything already in the script" not in first["brief"].description
    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
    assert space.proposal is not None and space.proposal.script is not None
    # The review still lists the change against the script it was asked from.
    assert space.proposal.base_script == old
    assert [s.name for s in space.proposal.script.stages] == [
        "Welcome back",
        "Wrong person",
        "Delivery day",
        "Close",
    ]
    assert not [p for p in space.proposal.left_out if "owner" in p.rule]
