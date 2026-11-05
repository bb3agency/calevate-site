"""The script writer after the founder's Rytu Khata call of 6 Nov 2026 (agent Varsha).

The Pip-written script asked what the app was used for before helping install it and how the
caller liked it seconds after, gave an "explain" step a line deferring to the team, said the
same description three times, and opened "<greeting> <title>," with no name on a call placed
without one. Asked to drop steps, the edit writer kept them as "Not needed." with empty lines.
Lines here are English: the checks are language-free or read the English instructions.
"""

from __future__ import annotations

import json

import httpx
import pytest
from apps.api.agents.call_rules import OPENING_LINE_RULE, writer_rules
from apps.api.agents.script_lint import (
    NAME_FIELD,
    CapabilityManifest,
    LintContext,
    flow_problems,
    name_segment_problem,
    order_problems,
    placeholder_instruction,
    repeated_line_problems,
    script_problems,
    spoken_line_problems,
)
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.workers.opening_line import PLACED_TASK
from apps.workers.script_assist import (
    EDIT_INSTRUCTION,
    UnusableAnswerError,
    drafted_script,
    edited_script,
)
from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    ProcedureStep,
    StageBranch,
    fill_spoken_line,
)
from calevate_shared.engine import CallContext


def _stage(
    sid: str, name: str, instruction: str, line: str = "", **kw: object
) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, sounds_like=line, **kw)  # type: ignore[arg-type]


# The shape of Varsha's script, in English.
CHECK = _stage(
    "s2",
    "Check installation",
    "Explain the app, then ask if they installed it.",
    "Is the app on your phone?",
)
USAGE = _stage(
    "s3", "Purpose of usage", "Ask what they are using the app for.", "What do you use it for?"
)
INSTALL = _stage(
    "s4",
    "Installation support",
    "Help them install the app from the browser.",
    "Shall we install it now?",
    procedure=[ProcedureStep(action="Open the browser.", wait_for="it is open")],
)
SATISFIED = _stage(
    "s5", "Satisfaction level", "Ask how satisfied they are with the app.", "How do you find it?"
)
CLOSE = _stage("s8", "Close", "Thank them and say goodbye.", "Thanks, goodbye.")


def _script(*stages: ConversationStage, **kw: object) -> CallScript:
    return CallScript(schema_version=2, stages=list(stages), **kw)  # type: ignore[arg-type]


# --- 1. order: nothing asked before, or right after, the caller sets it up -------------------


def test_usage_asked_before_the_install_step_is_found() -> None:
    problems = order_problems(_script(CHECK, USAGE, INSTALL, CLOSE))
    assert len(problems) == 1
    assert problems[0].startswith("stages.1.instruction:") and "before step 3" in problems[0]


def test_satisfaction_asked_right_after_the_install_step_is_found() -> None:
    problems = order_problems(_script(CHECK, INSTALL, SATISFIED, CLOSE))
    assert len(problems) == 1 and "right after step 2" in problems[0]


def test_experience_questions_only_on_the_way_for_callers_who_had_it_pass() -> None:
    check = CHECK.model_copy(
        update={"branches": [StageBranch(when="they already have the app", target="s5")]}
    )
    install = INSTALL.model_copy(update={"otherwise": "s8"})
    satisfied = SATISFIED.model_copy(update={"otherwise": "s8"})
    assert order_problems(_script(check, install, satisfied, CLOSE)) == []


def test_explaining_usage_after_install_is_not_an_experience_question() -> None:
    explain = _stage(
        "s7",
        "Say one thing",
        "Explain one feature at a time, or answer their questions about usage.",
        "First, add a crop.",
    )
    assert order_problems(_script(CHECK, INSTALL, explain, CLOSE)) == []


def test_the_writer_is_told_the_order_and_line_rules() -> None:
    rules = writer_rules()
    for words in (
        "nothing is asked before what it depends on has happened",
        "sounds_like does what that stage's instruction says",
        "Each thing is explained in one stage only",
        "never kept with a placeholder instruction",
    ):
        assert words in rules
    assert rules in EDIT_INSTRUCTION


# --- 3. the same explanation twice ------------------------------------------------------------


def test_a_line_that_repeats_an_earlier_one_is_found_in_any_letters() -> None:
    first = _stage(
        "a", "Explain", "Explain the app.", "日 月 火 水 木 金, it keeps your farm costs"
    )
    again = _stage(
        "b", "How to use", "Answer how to use it.", "日 月 火 水 木 金, it keeps your farm costs?"
    )
    problems = repeated_line_problems(_script(first, again, CLOSE))
    assert len(problems) == 1 and problems[0].startswith(
        "stages.1.sounds_like: says nearly what Step 1"
    )


def test_different_lines_pass() -> None:
    assert repeated_line_problems(_script(CHECK, INSTALL, CLOSE)) == []


# --- 4. an opening with no name --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "values", "spoken"),
    [
        (
            "Hello {{lead_name}} sir, this is Asha from Acme. Can we talk now?",
            {},
            "Hello, this is Asha from Acme. Can we talk now?",
        ),
        (
            "Hello {{lead_name}} sir, this is Asha.",
            {"lead_name": "Ravi"},
            "Hello Ravi sir, this is Asha.",
        ),
        ("Hello {{lead_name}}, this is Asha.", {"lead_name": None}, "Hello, this is Asha."),
        ("{{lead_name}} sir, good morning.", {}, "good morning."),
        ("Hi {{lead_name}}! Asha here.", {"lead_name": "  "}, "Hi! Asha here."),
        # Two words before the break: only the field goes, never the speaker's own words.
        ("Your order {{order_id}} is ready, {{lead_name}}.", {}, "Your order is ready."),
        ("Hello {{lead_name}} we are calling about it.", {}, "Hello we are calling about it."),
    ],
)
def test_an_unfilled_name_goes_with_its_title(
    text: str, values: dict[str, str | None], spoken: str
) -> None:
    assert fill_spoken_line(text, values) == spoken


async def test_the_dial_with_no_name_leaves_no_title_alone() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"id": "out_1", "status": "ringing"})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )
    ctx = CallContext(
        lead_name=None, opening="Hello {{lead_name}} sir, Asha from Acme. Can we talk now?"
    )
    await engine.start_outbound_call("ag_1", "+919876543210", ctx)
    assert json.loads(seen[-1].content)["purpose"] == "Hello, Asha from Acme. Can we talk now?"


def test_a_placed_opening_must_read_without_the_name() -> None:
    assert (
        name_segment_problem(
            "opening_line", f"Hello {NAME_FIELD} sir, Asha here. Talk now?", placed=True
        )
        is None
    )
    assert (
        name_segment_problem(
            "opening_line", f"Hello {NAME_FIELD}, Asha here. Talk now?", placed=True
        )
        is None
    )
    # A title not followed by a break, a name inside a question, a name deep in a sentence.
    for text in (
        f"Hello {NAME_FIELD} sir Asha here, talk now?",
        f"Am I speaking with {NAME_FIELD}?",
        f"This is Asha calling for {NAME_FIELD}, talk now?",
    ):
        assert name_segment_problem("opening_line", text, placed=True) is not None, text


def test_an_answered_opening_takes_no_title_after_the_name() -> None:
    assert (
        name_segment_problem("opening_line", f"Hello {NAME_FIELD}, how can I help?", placed=False)
        is None
    )
    assert (
        name_segment_problem(
            "opening_line", f"Hello {NAME_FIELD} sir, how can I help?", placed=False
        )
        is not None
    )


def test_the_lint_reads_the_direction_for_which_rule_holds() -> None:
    line = f"Hello {NAME_FIELD} sir, Asha from Acme. Can we talk now?"
    placed = LintContext(manifest=CapabilityManifest(direction="outbound"))
    answered = LintContext(manifest=CapabilityManifest(direction="both"))
    assert not any(NAME_FIELD in p for p in spoken_line_problems("opening_line", line, placed))
    assert any(NAME_FIELD in p for p in spoken_line_problems("opening_line", line, answered))
    # A "both" agent's placed-call opening keeps its title.
    assert not any(
        NAME_FIELD in p for p in spoken_line_problems("outbound_opening_line", line, answered)
    )


def test_every_opening_writer_is_told_where_the_name_goes() -> None:
    assert "then its title if the language uses one, then a comma" in OPENING_LINE_RULE
    assert "then its title if the language uses one, then a comma" in PLACED_TASK


# --- the edit writer: delete, rename, move; never a blanked step ----------------------------

OWNERS = _script(
    CHECK.model_copy(update={"otherwise": "s3"}),
    USAGE.model_copy(update={"otherwise": "s4"}),
    INSTALL.model_copy(
        update={"otherwise": "s5", "branches": [StageBranch(when="they ask", target="s3")]}
    ),
    SATISFIED.model_copy(update={"otherwise": "s8"}),
    CLOSE,
)


def _answer(*stages: ConversationStage) -> dict[str, object]:
    return {"stages": [s.model_dump(mode="json") for s in stages]}


def test_deleting_two_steps_leaves_them_out_and_the_ways_to_them_go() -> None:
    stages = [s for s in OWNERS.stages if s.id not in {"s3", "s5"}]
    edited = edited_script(_answer(*stages), OWNERS, lint=LintContext())
    assert edited is not None
    assert [s.id for s in edited.stages] == ["s2", "s4", "s8"]
    check, install, _ = edited.stages
    # As the Script tab's own delete: a way to a deleted step goes, `otherwise` falls to next.
    assert check.otherwise == "" and install.otherwise == "" and install.branches == []


def test_a_rename_and_a_move_are_kept_as_asked() -> None:
    renamed = OWNERS.stages[3].model_copy(update={"name": "How it is going"})
    order = [OWNERS.stages[0], OWNERS.stages[2], OWNERS.stages[1], renamed, OWNERS.stages[4]]
    edited = edited_script(_answer(*order), OWNERS)
    assert edited is not None
    assert [s.id for s in edited.stages] == ["s2", "s4", "s3", "s5", "s8"]
    assert edited.stages[3].name == "How it is going"


def test_a_change_that_deletes_nothing_keeps_every_step() -> None:
    changed = OWNERS.stages[0].model_copy(update={"sounds_like": "Is the app on your phone yet?"})
    edited = edited_script(_answer(changed, *OWNERS.stages[1:]), OWNERS, lint=LintContext())
    assert edited is not None and [s.id for s in edited.stages] == [s.id for s in OWNERS.stages]


BLANKED = [
    *OWNERS.stages[:2],
    *(
        s.model_copy(update={"instruction": "Not used.", "sounds_like": ""})
        for s in OWNERS.stages[2:]
    ),
]


def test_steps_blanked_with_a_placeholder_go_back_for_the_repair() -> None:
    with pytest.raises(UnusableAnswerError) as refused:
        edited_script(_answer(*BLANKED), OWNERS, lint=LintContext())
    said = str(refused.value)
    assert 'stages.2.instruction: says only "Not used."' in said
    assert "stages.4.instruction" in said and "this is the close" in said


def test_after_the_repair_blanked_steps_are_removed_and_the_close_is_the_owners() -> None:
    edited = edited_script(_answer(*BLANKED), OWNERS, lint=LintContext(), lenient=True)
    assert edited is not None
    assert [s.id for s in edited.stages] == ["s2", "s3", "s8"]
    assert edited.stages[-1] == CLOSE
    assert edited.stages[1].otherwise == ""


def test_the_close_taken_out_goes_back_for_the_repair() -> None:
    with pytest.raises(UnusableAnswerError, match="the close"):
        edited_script(_answer(*OWNERS.stages[:-1]), OWNERS, lint=LintContext())


def test_a_kept_step_with_its_line_emptied_goes_back() -> None:
    emptied = OWNERS.stages[0].model_copy(update={"sounds_like": ""})
    with pytest.raises(UnusableAnswerError, match=r"stages\.0\.sounds_like: is empty"):
        edited_script(_answer(emptied, *OWNERS.stages[1:]), OWNERS, lint=LintContext())


def test_an_order_problem_the_owner_already_had_is_not_the_models() -> None:
    # OWNERS asks usage before install; a change elsewhere is not refused for it.
    assert order_problems(OWNERS)
    changed = OWNERS.stages[-1].model_copy(update={"sounds_like": "Thank you, goodbye."})
    assert (
        edited_script(_answer(*OWNERS.stages[:-1], changed), OWNERS, lint=LintContext()) is not None
    )


def test_a_new_draft_leaves_out_a_step_written_as_a_placeholder() -> None:
    raw = {
        "opening_line": "Hello, can we talk now?",
        "stages": [
            {
                "name": "Greet",
                "instruction": "Greet them.",
                "sounds_like": "Hello there, all good?",
            },
            {"name": "Ask", "instruction": "N/A", "sounds_like": ""},
            {
                "name": "Close",
                "instruction": "Thank them and say goodbye.",
                "sounds_like": "Thanks, bye.",
            },
        ],
    }
    script = drafted_script(raw, language="en-IN")
    assert [s.name for s in script.stages] == ["Greet", "Close"]


# --- the readiness card reads the same checks ------------------------------------------------


def test_placeholder_words_and_other_letters() -> None:
    for text in (
        "Not needed.",
        "N/A",
        "-",
        "  ",
        "Not used",
        "This step is not required.",
        "Removed",
    ):
        assert placeholder_instruction(text), text
    for text in ("Ask what they need.", "Skip to the close if they are busy.", "δοκιμή"):
        assert not placeholder_instruction(text), text


def test_the_published_script_shows_the_shape_problems() -> None:
    script = _script(
        CHECK, USAGE, INSTALL, SATISFIED.model_copy(update={"instruction": "Not needed."}), CLOSE
    )
    found = script_problems(script, LintContext())
    assert set(flow_problems(script)) <= set(found)
    assert any(p.startswith("stages.3.instruction: says only") for p in found)
