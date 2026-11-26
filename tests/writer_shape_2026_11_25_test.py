"""Pip's script writers, fixed at the root after the script and call of 25 Nov 2026.

The script Pip wrote for an app-install campaign asked five details in step 1 (three of them
judgements of the call, one the name the opening had just used), gave each step a "way out"
that was only the next step's name, put "they do not remember registering" as a step after
the close, dropped the main task's screen-by-screen install for each phone, had the agent
"note" what the caller enters in the app, and started the call's work with no reason for the
call. Every fixture here is an English stand-in with that shape, for a neutral business
("ShopBook"), never the campaign's own words. The model is never called.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_heal, script_lint
from apps.api.agents.script_builder import job_details
from apps.api.agents.script_checks import mistake_findings, run, texts
from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    script_problems,
    unasked_details,
)
from apps.api.agents.script_shape import (
    coverage_problems,
    echo_branches,
    main_task_items,
    named_way_problems,
    piled_problems,
    structure_problems,
    trailing_problems,
    uncovered_items,
)
from apps.api.agents.script_structure import collected, settled, without_judged_asks
from apps.workers import campaign_script
from apps.workers import campaign_script_ask as ask
from apps.workers.script_assist import ScriptBrief, _script_from_model_json
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    CallScript,
    ConversationStage,
    StageBranch,
)
from calevate_shared.extraction import whole_call_detail
from calevate_shared.lead_fields import core_fields

MAIN_TASK = (
    "Existing customers registered on the ShopBook web app. Help them install it as an app.\n"
    "1. Find out if it is installed as an app; explain why installing is better.\n"
    "2. Help them install it on Android or iPhone, screen by screen; help them set the "
    "language.\n"
    "3. Confirm it is installed; open the dashboard; explain that shops are set up first in "
    "My Shops.\n"
    "4. Set up their shops.\n"
    "5. Enter expenses.\n"
    "6. Then enter sales, and show how the dashboard summarises them."
)
OPENING = "Hello {{lead_name}}, this is Asha from ShopBook. Is now a good time to talk?"
CORE = core_fields(
    {
        "name": "Caller Name",
        "preferred_time": "Call Back Time",
        "other_number": "Alternative Number",
    }
)
STORED = [
    {"key": "campaign_goal_met", "label": "Campaign Goal Met", "type": "text"},
    {"key": "technical_comfort", "label": "Technical Comfort Level", "type": "text"},
    {"key": "usage_interest", "label": "Primary Usage Interest", "type": "text"},
    {"key": "customer_name", "label": "Customer Name", "type": "text"},
    {"key": "contact_no", "label": "Alternative contact number", "type": "text"},
    {"key": "phone_type", "label": "Phone Type", "type": "text"},
    {"key": "shop_count", "label": "Number of shops", "type": "text"},
]
PILED = [
    "Caller Name",
    "Campaign Goal Met",
    "Technical Comfort Level",
    "Primary Usage Interest",
    "Alternative Number",
]


def _stage(sid: str, name: str, instruction: str = "Help them.", **extra: Any) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": name, "instruction": instruction, **extra}
    )


def _way(when: str, target: str) -> dict[str, str]:
    return {"when": when, "target": target}


def _evidence() -> CallScript:
    """The 25 Nov 2026 script's shape (`SCRIPT-2026-11-25.md`), in English."""
    return CallScript(
        schema_version=2,
        opening_line=OPENING,
        stages=[
            _stage(
                "s1",
                "Check installation",
                "Ask them to check for the ShopBook icon. Collect the caller name and the "
                "other details.",
                sounds_like="Is the ShopBook icon on your home screen? What is your name?",
                collect=PILED,
                branches=[
                    _way("Busy now", CALL_BACK),
                    _way("Not interested", END_OF_CALL),
                    _way("Already done", "s2"),
                ],
            ),
            _stage(
                "s2",
                "Login",
                "Ask them to log in.",
                branches=[_way("Add Shops", "s3"), _way("They cannot", CALL_BACK)],
            ),
            _stage(
                "s3",
                "Add Shops",
                "Ask them to add their shops in My Shops.",
                sounds_like="Tell me the shop details and I'll note them.",
                branches=[_way("Enter Expenses", "s4")],
            ),
            _stage("s4", "Enter Expenses", branches=[_way("Enter Sales", "s5")]),
            _stage("s5", "Enter Sales", branches=[_way("Dashboard", "s6")]),
            _stage("s6", "Dashboard", branches=[_way("Finalise the call", "s7")]),
            _stage(
                "s7",
                "Finalise the call",
                "Thank them and close.",
                branches=[_way("Not registered", "s-not-registered")],
            ),
            _stage(
                "s-not-registered",
                "Not registered",
                "Explain they have registered and offer to help.",
                branches=[_way("Yes", "s1")],
            ),
        ],
    )


# --- 1. what a call asks -----------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["Campaign Goal Met", "Technical Comfort Level", "Primary Usage Interest", "Lead Sentiment"],
)
def test_a_judgement_of_the_call_or_the_person_is_never_asked(label: str) -> None:
    """FAILS IF: a goal met, a comfort or an interest level is still a detail a step asks."""
    assert whole_call_detail("", label)


@pytest.mark.parametrize("label", ["Satisfaction level", "Phone Type", "Shop name", "Rating"])
def test_what_the_person_states_is_still_asked(label: str) -> None:
    assert not whole_call_detail("", label)


def test_the_job_asks_neither_judgements_nor_what_the_call_already_has() -> None:
    """FAILS IF: a judged detail, a second name or a second phone number reaches the writer
    or the compiled call as a detail to ask."""
    details = job_details(STORED, CORE)
    assert details.labels() == (
        "Caller Name",
        "Phone Type",
        "Number of shops",
        "Call Back Time",
        "Alternative Number",
    )
    assert details.name == "Caller Name"


def test_a_placed_call_never_places_the_name_in_a_step() -> None:
    """FAILS IF: a campaign's writer is told to ask the name of the contact it dialled."""
    placed = job_details(STORED, CORE).placed()
    assert "Caller Name" not in placed.labels()
    assert placed.call_back == ("Call Back Time", "Alternative Number")


def test_a_step_line_asking_a_name_the_opening_used_is_a_finding() -> None:
    """FAILS IF: step 1 may ask "what is your name?" after the opening greeted them by it."""
    found = mistake_findings(_evidence(), LintContext(), "reasked_name")
    assert any(f.startswith("stages.0.sounds_like: asks for the name") for f in found)
    nameless = _evidence().model_copy(update={"opening_line": "Hello, is now a good time?"})
    assert mistake_findings(nameless, LintContext(), "reasked_name") == []


def test_judged_details_and_misplaced_call_back_ones_leave_the_step() -> None:
    """FAILS IF: a step keeps collecting a judged detail or another number outside the
    call-back path, and so asks them of everyone."""
    script = _evidence()
    ids = {stage.id for stage in script.stages}
    details = job_details(STORED, CORE).placed()
    mended = collected(without_judged_asks(script, ids), details.labels(), ids, details.call_back)
    assert mended.stages[0].collect == []
    assert piled_problems(mended, details.call_back) == []
    timed = _stage(
        "t", "Later", "Ask when they would like us to call back.", collect=["Alternative Number"]
    )
    later = script.model_copy(update={"stages": [timed]})
    kept = collected(later, details.labels(), {"t"}, details.call_back)
    assert kept.stages[0].collect == ["Alternative Number"]


def test_five_details_in_one_step_is_a_finding() -> None:
    found = piled_problems(_evidence())
    assert len(found) == 1 and found[0].startswith("stages.0.collect: asks for 5 details")


def test_call_back_details_are_asked_on_the_call_back_path() -> None:
    """FAILS IF: a script with a way out to the call back is told it asks no call-back time."""
    labels = ("Call Back Time", "Alternative Number")
    assert unasked_details(_evidence(), labels, labels) == []
    assert "Call Back Time" in unasked_details(_evidence(), labels)


# --- 2. ways out that are only the next step's name ---------------------------------------


def test_a_way_out_that_only_names_the_next_step_is_an_echo() -> None:
    found = {(i, j) for i, j in echo_branches(_evidence())}
    assert found == {(1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)}


def test_settled_drops_echo_ways_and_keeps_real_ones() -> None:
    """FAILS IF: "when: Add Shops -> Add Shops" survives what every Pip script goes through."""
    out = settled(_evidence(), LintContext())
    assert echo_branches(out) == []
    assert [b.when for b in out.stages[0].branches] == [
        "Busy now",
        "Not interested",
        "Already done",
    ]
    assert [b.when for b in out.stages[1].branches] == ["They cannot"]


def test_a_name_that_chooses_between_scenarios_stays() -> None:
    script = CallScript(
        schema_version=2,
        stages=[
            _stage("a", "Ask phone", step=1, branches=[_way("Android", "b"), _way("iPhone", "c")]),
            _stage("b", "Android", step=2),
            _stage("c", "iPhone", step=2),
        ],
    )
    assert echo_branches(script) == []


def test_the_writer_never_drafts_an_echo_way_out() -> None:
    """FAILS IF: a drafted `next` to the step after it becomes a way out named by that step."""
    raw = {
        "stages": [
            {"name": "Login", "instruction": "Ask them to log in.", "next": [2]},
            {"name": "Add Shops", "instruction": "Ask them to add shops.", "next": [3]},
            {"name": "Finalise the call", "instruction": "Thank them and close.", "next": [0]},
        ]
    }
    script = _script_from_model_json(raw)
    assert echo_branches(script) == []
    assert [b.target for b in script.stages[0].branches] == []


def test_the_repair_of_a_live_script_drops_echo_ways_and_judged_asks_by_code() -> None:
    mended = script_heal.wired_ways_out(_evidence(), LintContext())
    assert echo_branches(mended) == []
    assert mended.stages[0].collect == ["Caller Name", "Alternative Number"]


# --- 3. a case after the close -------------------------------------------------------------


def test_a_step_after_the_close_is_a_finding() -> None:
    found = trailing_problems(_evidence())
    assert len(found) == 1 and found[0].startswith('stages.7: "Not registered" comes after')


def test_the_case_as_a_scenario_of_step_one_passes() -> None:
    """The fix the restructure pass is asked for: the case is a scenario of step 1, reached by
    a way out of it, and the close is last."""
    stages = _evidence().stages
    case = stages[7].model_copy(update={"branches": []})
    remembered = StageBranch(when="They do not remember registering", target="s-not-registered")
    first = stages[0].model_copy(update={"branches": [*stages[0].branches, remembered]})
    fixed = _evidence().model_copy(update={"stages": [first, case, *stages[1:7]]})
    assert trailing_problems(fixed) == []


# --- 4. the main task's items ----------------------------------------------------------------


def test_the_main_tasks_items_are_read_in_order() -> None:
    items = main_task_items(MAIN_TASK)
    assert len(items) == 6 and items[1].startswith("Help them install it on Android")
    assert main_task_items("Tell them it costs 99. Then book a visit.") == []
    assert main_task_items("- Install the app\n- Set the language") == [
        "Install the app",
        "Set the language",
    ]


def test_a_dropped_screen_by_screen_install_is_found() -> None:
    """FAILS IF: the main task's install on each phone, screen by screen, and the language can
    be compressed to "press install" without a finding."""
    missing = uncovered_items(_evidence(), MAIN_TASK)
    assert any(item.startswith("Help them install it on Android") for item in missing)
    assert coverage_problems(_evidence(), MAIN_TASK)


def test_device_scenarios_of_one_step_cover_the_install() -> None:
    script = CallScript(
        schema_version=2,
        stages=[
            _stage(
                "a", "Check installed", "Ask whether the app is installed and why it helps.", step=1
            ),
            _stage(
                "b",
                "Install on Android",
                "Walk them through installing on Android screen by screen, then set the language.",
                step=2,
            ),
            _stage(
                "c",
                "Install on iPhone",
                "Walk them through installing on iPhone screen by screen, then set the language.",
                step=2,
            ),
            _stage(
                "d",
                "Confirm",
                "Confirm it is installed and open the dashboard; explain My Shops.",
                step=3,
            ),
            _stage("e", "Set up shops", "Ask them to set up their shops.", step=4),
            _stage("f", "Expenses", "Ask them to enter expenses.", step=5),
            _stage("g", "Sales", "Ask them to enter sales and show the dashboard summary.", step=6),
            _stage("h", "Finalise the call", "Thank them and close.", step=7),
        ],
    )
    assert uncovered_items(script, MAIN_TASK) == []


# --- 5. lines ------------------------------------------------------------------------------


def test_the_agent_noting_what_the_caller_enters_is_a_finding() -> None:
    found = texts(run(_evidence(), ids=["caller_action_claimed"]))
    assert any(f.startswith("stages.2.sounds_like: says the agent will note") for f in found)


def test_several_actions_in_one_line_is_a_finding() -> None:
    script = CallScript(
        schema_version=2,
        stages=[_stage("a", "Install", sounds_like="Open the site and tap install.")],
    )
    assert texts(run(script, ids=["several_actions"])) == [
        "stages.0.sounds_like: gives more than one thing to do in one turn; say only the next "
        "action, in a few words, and stop, so they do it before the next one."
    ]


def test_the_repairs_hear_the_line_findings() -> None:
    """FAILS IF: the write's repair rounds or the live-script repair do not see them."""
    found = script_heal.heal_findings(_evidence(), LintContext())
    assert any("says the agent will note" in f for f in found)


# --- 6. the writer's rules, the review and the restructure pass --------------------------


def test_the_asks_carry_the_rules() -> None:
    assert ask.SHAPE_RULE in ask.CAMPAIGN_ASK and ask.SHAPE_RULE in ask.LINE_ASK
    assert ask.PURPOSE_RULE in ask.CAMPAIGN_ASK and ask.PURPOSE_RULE not in ask.LINE_ASK
    assert ask.LINE_FIRST_RULE in ask.LINE_ASK
    assert "never asked" in ask.DETAILS_RULE
    assert "way out of the step where it arises" in ask.REFINE_TAIL


def test_the_change_names_the_main_tasks_items() -> None:
    change = ask.campaign_change(MAIN_TASK, "", "", edit=False)
    assert ask.ITEMS_HEAD in change and "6. Then enter sales" in change


def test_the_review_judges_the_purpose_and_its_findings_reach_the_lines() -> None:
    """FAILS IF: a first step that starts work without saying why the call is made is not a
    finding the repair rewrites, in any call language."""
    script = _evidence()
    keys = ["stages.s1"]
    review = ask.parsed_review(
        {
            "notes": [{"part": "stages.s1", "why": "Checks the app."}],
            "claims": [],
            "problems": [
                {"part": "stages.s1", "kind": "no_purpose", "detail": "starts with the icon"}
            ],
        },
        keys,
    )
    assert review is not None
    found = campaign_script.review_findings(review, script)
    assert any(
        n.finding.startswith("stages.0.sounds_like: starts the call's work without saying why")
        for n in found.noted
    )
    assert "no_purpose" in ask.REVIEW_INSTRUCTION and "purpose_repeated" in ask.WEAK_PROBLEMS
    request = ask.review_request([], "MAIN TASK:\nx", OPENING)
    assert request.endswith(f"THE OPENING LINE THE CALL STARTS WITH: {OPENING}")


def _inputs(base: CallScript | None = None) -> Any:
    return campaign_script._Inputs(
        agent_id=__import__("uuid").uuid4(),
        main_task=MAIN_TASK,
        base=base,
        notes="",
        words=[],
        context=ScriptBrief(),
        tenant_leg=None,
        quota_exhausted=False,
        details=job_details(STORED, CORE).placed(),
    )


async def test_a_script_built_wrong_gets_one_whole_script_pass_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: details piled in a step, a case after the close or a dropped task reach the
    owner without one whole-script pass asked to fix them."""
    calls: list[dict[str, Any]] = []
    fixed = CallScript(schema_version=2, stages=[_stage("h", "Finalise the call")])

    async def write(_brief: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(script=fixed)

    monkeypatch.setattr(campaign_script, "draft_script", write)
    found = campaign_script.built_wrong(_inputs(), _evidence())
    assert any("comes after the close" in p for p in found)
    assert any("no step covers it" in p for p in found)
    script, spent = await campaign_script._restructured(
        _inputs(), ScriptBrief(), _evidence(), time.monotonic(), ask=ask.CAMPAIGN_ASK,
        documents="", owners="",
    )  # fmt: skip
    assert script is fixed and len(spent) == 1
    change = calls[0]["change"]
    assert ask.RESTRUCTURE_TAIL in change and "comes after the close" in change
    assert calls[0]["edit_of"] == _evidence()


async def test_a_well_built_script_spends_no_restructure_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def write(_brief: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no pass is needed")

    monkeypatch.setattr(campaign_script, "draft_script", write)
    clean = CallScript(schema_version=2, stages=[_stage("h", "Finalise the call")])
    inputs = _inputs()
    inputs = campaign_script.replace(inputs, main_task="Tell them about the new menu.")
    script, spent = await campaign_script._restructured(
        inputs, ScriptBrief(), clean, time.monotonic(), ask=ask.CAMPAIGN_ASK, documents="",
        owners="",
    )  # fmt: skip
    assert script is clean and spent == []


def test_what_is_still_built_wrong_is_a_warning_the_owner_reads() -> None:
    left = campaign_script.built_wrong_left(_inputs(), _evidence())
    assert any(item.part == "stages.s-not-registered" for item in left)
    assert all(item.unfixed for item in left)
    # The owner's own script, already built so, is theirs: no warning for what they had.
    assert campaign_script.built_wrong_left(_inputs(base=_evidence()), _evidence()) == []
    assert structure_problems(_evidence().model_copy(update={"raw_override": "x"})) == []


def test_a_jump_whose_condition_is_only_the_steps_name_is_a_finding() -> None:
    """A way out to a later step named only by that step is no caller state (research §C
    "Branches"); one choosing between scenarios of the next step stays."""
    script = CallScript(
        schema_version=2,
        stages=[
            _stage("a", "Login", branches=[_way("Dashboard", "c")]),
            _stage("b", "Add Shops"),
            _stage("c", "Dashboard"),
        ],
    )
    assert named_way_problems(script) == [
        'stages.0.branches: the way out to "Dashboard" has only that step\'s name as its '
        "condition; say what the person says or has done that leads there."
    ]


def test_a_steps_line_in_a_call_language_is_held_to_the_line_checks() -> None:
    """FAILS IF: a promise the account cannot keep, written in a step's per-language line
    (`ConversationStage.scripts`, which the in-call model copies), passes the script check."""
    stage = _stage("a", "Bill", scripts={"en-IN": "I will send you the bill on WhatsApp."})
    script = CallScript(schema_version=2, stages=[stage])
    found = script_problems(script, LintContext(manifest=CapabilityManifest()))
    assert any(f.startswith("stages.0.scripts.en-IN: promises") for f in found)


def test_the_shape_checks_answer_to_the_scorers_names() -> None:
    """The script-writer scorer reads `script_lint.<check>_problems` by name."""
    script = _evidence()
    assert script_lint.steps_after_close_problems(script) == trailing_problems(script)
    assert script_lint.fake_branch_problems(script)
    assert len(script_lint.judged_field_asked_problems(script)) == 3
    assert script_lint.known_value_asked_problems(script)
    assert script_lint.agent_claims_caller_action_problems(script)
    two = CallScript(
        schema_version=2,
        stages=[_stage("a", "Ask", sounds_like="Open the app and press Login. Is it open? Done?")],
    )
    assert script_lint.multi_question_line_problems(two)
    assert script_lint.multi_action_line_problems(two)
