"""The Rytu Khata guided set-up call of 26 Nov 2026 (~16:03 IST, agent Varsha).

Every reply opened with a stock reaction that rotated ("సరే అండి." / "చాలా మంచిది అండి." /
"చాలా సంతోషం అండి."), every reply ended by asking the farmer to say when the step was done,
one turn gave the next action after "once it opens", and the first step asked again whether
to help set up the app, which the opening had already asked. The founder: no human talks
like this.

The Telugu lines are the call's own, quoted only as what the checks must detect; the English
lines are stand-ins for the same turns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from apps.api.agents.call_mistakes import LESSONS, mistakes_in
from apps.api.agents.call_rules import (
    SCRIPT_FLOW_RULE,
    opening_redone_line_problems,
    said_line_problem,
    writer_rules,
)
from apps.api.agents.script_checks import SCRIPT_FIXABLE_KINDS, mistake_findings
from apps.api.agents.script_lint import (
    LintContext,
    asks_when_done,
    flow_problems,
    script_problems,
    stacked_line,
)
from apps.api.agents.test_conversations import Turn
from apps.api.agents.turn_checks import (
    SOUND_KINDS,
    STOCK_OPENER_REPLIES,
    conversation_problems,
    opener,
    turn_problems,
)
from apps.workers.step_writer import OPENING_NOTE, STEP_INSTRUCTION
from calevate_shared.call_script import CallScript, ConversationStage, ProcedureStep

#: The turn that gave two steps and then asked to be told.
STACKED = (
    "అది ఓపెన్ అయ్యాక, స్క్రీన్ పైన ఉన్న యాడ్ టు హోమ్ స్క్రీన్ అనే ఆప్షన్ నొక్కితే, "
    "రైతుఖాతా ఐకాన్ మీ ఫోన్ హోమ్ స్క్రీన్ మీద వస్తుంది అండి. అది వచ్చాక నాకు చెప్తారా?"
)
#: The two endings every reply rotated between.
ENDS_ASKING = "అది వచ్చాక నాకు చెప్తారా?"
ENDS_TELLING = "అది ఓపెన్ అయ్యాక నాకు చెప్పండి."
#: The three reactions every reply rotated between.
REACTIONS = ("సరే అండి.", "చాలా మంచిది అండి.", "చాలా సంతోషం అండి.")
#: One action and nothing after it: what a line of a guided step is now.
ONE_ACTION = "ఇప్పుడు క్రోమ్ బ్రౌజర్ ఓపెన్ చేయండి."

OPENING = "Hello {{lead_name}}, this is Varsha from Rytu Khata. Shall we set up the app now?"


def _stage(sid: str, line: str, **extra: object) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid, "instruction": "Help them.", "sounds_like": line, **extra}
    )


def _script(*stages: ConversationStage, opening: str = OPENING) -> CallScript:
    return CallScript(schema_version=2, outbound_opening_line=opening, stages=list(stages))


def _paths(problems: list[str], marker: str) -> list[str]:
    return [p.partition(": ")[0] for p in problems if marker in p]


# --- the lines ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "tail"),
    [
        (STACKED, ENDS_ASKING),
        (ENDS_TELLING, ENDS_TELLING),
        ("Tap Add to Home screen. Tell me once the icon shows.", "Tell me once the icon shows."),
        ("Now log in, and let me know when you are in.", None),
        ("ऐप खोलिए। खुलने के बाद मुझे बताइए।", "खुलने के बाद मुझे बताइए।"),
    ],
)
def test_a_line_ending_on_a_request_to_be_told_is_found(line: str, tail: str | None) -> None:
    found = asks_when_done(line)
    assert found is not None
    assert tail is None or found == tail


@pytest.mark.parametrize(
    "line",
    [
        ONE_ACTION,
        "Now tap Add to Home screen.",
        "Tell me when you would like to visit.",
        "What is your name? Please tell me.",
    ],
)
def test_one_action_or_an_ordinary_question_is_not(line: str) -> None:
    assert asks_when_done(line) is None
    assert not stacked_line(line)


def test_the_two_step_turn_is_several_actions() -> None:
    assert stacked_line(STACKED)
    assert stacked_line("Once it opens, tap Add to Home screen.")
    assert stacked_line("Open Chrome and type rytukhata dot com.")


def test_a_three_word_reaction_is_read_as_the_opener() -> None:
    assert opener("చాలా మంచిది అండి. ఇప్పుడు లాగిన్ అవ్వండి.") == "చాలా మంచిది అండి"
    assert opener("సరే అండి, ఏ ఏరియా?") == "సరే అండి"


# --- the script checks -----------------------------------------------------------------------


def test_the_script_check_names_the_request_the_shared_ending_and_the_two_steps() -> None:
    script = _script(
        _stage("install", STACKED),
        _stage("open", f"ఇప్పుడు ఆ రైతుఖాతా ఐకాన్ మీద నొక్కి యాప్ ఓపెన్ చేయండి. {ENDS_ASKING}"),
        _stage("login", ENDS_TELLING),
        _stage("close", "Thank you, goodbye."),
    )
    found = flow_problems(script)
    assert _paths(found, "ends by asking them to say when it is done") == [
        "stages.0.sounds_like",
        "stages.1.sounds_like",
        "stages.2.sounds_like",
    ]
    assert "stages.1.sounds_like" in _paths(found, "ends with the same words")
    assert "stages.0.sounds_like" in _paths(found, "more than one thing to do")
    # The writer's refusal check and the readiness card read the same findings.
    assert set(found) <= set(script_problems(script, LintContext()))


def test_small_steps_and_sample_phrases_are_read_too() -> None:
    script = _script(
        _stage(
            "install",
            ONE_ACTION,
            procedure=[
                ProcedureStep(action="Tap the three dots, then choose Add to Home screen."),
                ProcedureStep(action="Tap Add. Tell me once the icon shows."),
            ],
        )
    )
    script.style.sample_phrases.append(ENDS_TELLING)
    found = flow_problems(script)
    assert _paths(found, "more than one thing to do") == ["stages.0.procedure.0.action"]
    assert _paths(found, "ends by asking them to say when it is done") == [
        "stages.0.procedure.1.action",
        "style.sample_phrases.0",
    ]


def test_a_guided_step_of_one_action_each_passes() -> None:
    script = _script(
        _stage("install", ONE_ACTION),
        _stage("menu", "Now tap the three dots at the top right."),
        _stage("close", "Thank you, goodbye."),
    )
    found = flow_problems(script)
    for marker in ("say when it is done", "same words", "more than one thing"):
        assert _paths(found, marker) == []


@pytest.mark.parametrize("reaction", REACTIONS)
def test_every_rotating_reaction_is_sent_back_by_the_writer_check(reaction: str) -> None:
    problem = said_line_problem("stages.1.sounds_like", f"{reaction} {ONE_ACTION}")
    assert problem is not None and "opens with the reaction" in problem


def test_the_first_step_offering_again_what_the_opening_offered_is_found() -> None:
    script = _script(
        _stage("start", "Can I help you set up the Rytu Khata app now?"),
        _stage("expense", "Shall we add your first expense in the app?"),
    )
    assert _paths(opening_redone_line_problems(script), "asks again") == ["stages.0.sounds_like"]
    telugu = _script(
        _stage("start", "మీ ఫోన్లో యాప్ సెటప్ చేయమంటారా?"),
        opening="మీ ఫోన్లో యాప్ సెటప్ చేద్దామా?",
    )
    assert _paths(opening_redone_line_problems(telugu), "asks again") == ["stages.0.sounds_like"]


def test_each_new_kind_traces_to_the_script_line() -> None:
    assert {"asks_when_done", "several_actions"} <= SCRIPT_FIXABLE_KINDS
    script = _script(_stage("install", STACKED))
    for kind in ("asks_when_done", "several_actions"):
        assert mistake_findings(script, LintContext(), kind)


# --- the call review ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _T:
    idx: int
    speaker: str
    text: str


def test_a_real_call_names_the_request_and_the_two_steps() -> None:
    call = [
        _T(1, "agent", OPENING),
        _T(2, "caller", "Yes."),
        _T(3, "agent", "Now open the Chrome browser on your phone. Tell me once it is open."),
        _T(4, "caller", "It is open."),
        _T(5, "agent", "Once it opens, tap the three dots at the top right."),
        _T(6, "caller", "Done."),
    ]
    found = mistakes_in(call, language="en-IN")
    assert found["asks_when_done"] == 3
    assert found["several_actions"] == 5
    for kind in ("asks_when_done", "several_actions"):
        assert kind in SOUND_KINDS
        assert LESSONS[kind].label and LESSONS[kind].instead


def test_the_telugu_turn_is_named_in_a_reply() -> None:
    kinds = {p.kind for p in turn_problems(STACKED, language="te-IN")}
    assert {"asks_when_done", "several_actions"} <= kinds


def test_rotating_reactions_are_a_stock_opener() -> None:
    replies = [
        Turn("Yes.", f"{REACTIONS[0]} {ONE_ACTION}"),
        Turn("Opened.", f"{REACTIONS[1]} {ENDS_TELLING}"),
        Turn("Done.", f"{REACTIONS[2]} {STACKED}"),
    ]
    found = [p for p in conversation_problems(replies) if p.kind == "same_opening"]
    assert found and f"opened {STOCK_OPENER_REPLIES} replies" in found[0].reason


# --- the writers are told ------------------------------------------------------------------------


def test_the_writers_are_told_one_action_then_stop() -> None:
    assert "The agent says one action, then stops" in SCRIPT_FLOW_RULE
    assert "no line asks them to tell you when it is done" in SCRIPT_FLOW_RULE
    assert "gives its first action only, in a few words" in SCRIPT_FLOW_RULE
    assert "open or end with the same words" in SCRIPT_FLOW_RULE
    assert "none opens with a reaction" in SCRIPT_FLOW_RULE
    assert "whether to go ahead with what the opening offered" in SCRIPT_FLOW_RULE
    assert SCRIPT_FLOW_RULE in writer_rules()
    # The step writer, which writes every step's words (`workers/step_writer`).
    assert "first action only and asks nothing" in STEP_INSTRUCTION
    assert "never a question the agent asks" in STEP_INSTRUCTION
    assert "their yes to the opening is the go-ahead" in OPENING_NOTE


# --- a confused caller is asking, not done --------------------------------------------------------


@pytest.mark.parametrize("said", ["ఏమయ్యాక చెప్పాలి", "Emayyaaka cheppaali", "कैसे करना है"])
def test_a_confused_line_with_no_question_mark_is_a_question_never_a_done(said: str) -> None:
    from apps.api.agents.turn_checks import asks_question, caller_says_done
    from scripts.call_sim import scorecard as sc

    assert asks_question(said)
    assert not caller_says_done(said)
    assert not sc.done_signal(said)


def test_moving_on_after_a_confused_line_is_moving_on() -> None:
    from scripts.call_sim import scorecard as sc

    turns = [
        Turn("Yes.", "Now tap the install button at the top."),
        Turn("Emayyaaka cheppaali", "Now open the app and log in with your number."),
    ]
    assert sc.moved_on_unclear(turns) == 1


def test_a_done_without_a_question_is_still_a_done() -> None:
    from apps.api.agents.turn_checks import caller_says_done

    assert caller_says_done("Did it.")
    assert caller_says_done("అయింది")
