"""An action and "is it done?" in one turn (the founder's Telugu campaign call of 24 Nov 2026,
12:15): "enter your number and password and log in. Have you logged in?", before the person
could do it, on six steps of the call.

The English lines are stand-ins for the call's turns; the Telugu ones are the call's own
transcript, quoted only as what the checks must detect.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from apps.api.agents import script_heal
from apps.api.agents.call_mistakes import LESSONS, mistakes_in
from apps.api.agents.call_rules import SCRIPT_FLOW_RULE, writer_rules
from apps.api.agents.mistake_lints import mistake_findings, script_mistakes
from apps.api.agents.script_lint import LintContext
from apps.api.agents.turn_checks import SOUND_KINDS, asks_done_too_soon, turn_problems
from apps.api.core.settings import get_settings
from apps.workers import script_heal as heal_job
from calevate_shared.call_script import (
    PROCEDURE_LEAD,
    CallScript,
    ConversationStage,
    ProcedureStep,
)
from calevate_shared.engine import VOICE_STYLE_GUIDANCE, AgentConfig, compose_engine_prompt
from tests.script_heal_2026_11_24_test import (
    OPENING,
    _account,
    _line,
    _payload,
    _queue,
    _row,
    _writer,
)

KIND = "asked_done_too_soon"

#: English stand-ins of the call's turns, numbered as the call page numbers them.
EN_TURNS = {
    10: "Now type rytukhata dot com in the address bar and search. Did the site open?",
    12: "Now tap the three-dot menu at the top right. Did it open?",
    18: "Now tap the Rytu Khata icon to open the app, has it opened?",
    20: "Now choose Telugu in the app. Have you chosen it?",
    22: "Now enter your registered mobile number and password and log in. Have you logged in?",
    24: "Now tap the My Farms button at the bottom of the app. Did that screen come up?",
}

#: The call's own turns that gave an action and asked whether it was done.
TE_TURNS = {
    10: "సరే అండి, ఇప్పుడు అడ్రస్ బార్‌లో రైతుఖాతా డాట్ కామ్ అని టైప్ చేసి వెతకండి. సైట్ ఓపెన్ అయిందా అండి?",
    12: "సరే అండి, ఇప్పుడు పైన కుడివైపున ఉన్న మూడు చుక్కల మెనూని నొక్కండి. అది ఓపెన్ అయిందా అండి?",
    18: "చాలా సంతోషం అండి. ఇప్పుడు ఆ రైతుఖాతా ఐకాన్ మీద నొక్కి యాప్ ఓపెన్ చేయండి, ఓపెన్ అయిందా అండి?",
    20: "సరే అండి, ఇప్పుడు యాప్ లో తెలుగు భాషను ఎంచుకోండి. ఎంచుకున్నారా అండి?",
    22: ("సరే అండి, ఇప్పుడు మీ రిజిస్టర్డ్ మొబైల్ నంబర్ మరియు పాస్వర్డ్ ఎంటర్ చేసి లాగిన్ అవ్వండి. లాగిన్ అయ్యారా అండి?"),
    24: "సరే అండి, ఇప్పుడు యాప్ కింద ఉన్న మై ఫార్మ్స్ బటన్ నొక్కండి. ఆ స్క్రీన్ వచ్చిందా అండి?",
}

#: The call's turns that are right or wrong in other ways, never this way: "is now a good
#: time?" again (4), "Android or iPhone?" (6), an action and "tell me once it is open" (8, 14),
#: and "have a look" after a retry (16).
TE_CLEAN = {
    4: (
        "మీరు మా రైతుఖాతా యాప్లో రిజిస్టర్ చేసుకున్నారు కదా, "
        "దాన్ని మీ ఫోన్లో యాప్లా పెట్టడానికి ఒక ఐదు నిమిషాలు సాయం చేద్దామని ఫోన్ చేశాను, "
        "ఇప్పుడు మాట్లాడటానికి మీకు వీలుందా అండి?"
    ),
    6: "సరే అండి, ఇప్పుడు మీ ఫోన్ ఆండ్రాయిడ్ ఆ, ఐఫోన్ ఆ అండి?",
    8: "సరే అండి, ఇప్పుడు మీ ఫోన్లో క్రోమ్ బ్రౌజర్ ఓపెన్ చేయండి. ఓపెన్ చేశాక నాకు చెప్పండి అండి.",
    14: "సరే అండి, ఇప్పుడు అందులో యాడ్ టు హోమ్ స్క్రీన్ అనే ఆప్షన్ కనిపిస్తుంది, దాన్ని ఎంచుకోండి. అది అయ్యాక చెప్పండి అండి.",
    16: (
        "పర్వాలేదు అండి, మళ్ళీ ఒకసారి ప్రయత్నిద్దాం. "
        "పైన కుడివైపున ఉన్న మూడు చుక్కల మెనూని నొక్కిన తర్వాత, "
        "కిందకు స్క్రోల్ చేస్తే మీకు యాడ్ టు హోమ్ స్క్రీన్ అనే ఆప్షన్ కనిపిస్తుంది, "
        "ఒకసారి చూడండి అండి?"
    ),
}

#: Turn 8 as the founder quoted it ("open Chrome. Tell me once it opens") asks nothing, so it is
#: not this kind; it asks to be told, which is `asks_when_done` (26 Nov 2026).
INVITES = (
    "Now open the Chrome browser on your phone. Tell me once it is open.",
    "Now tap the three-dot menu at the top right. Take your time, tell me when it opens.",
)

NOT_ABOUT_DONE = (
    "Is your phone Android or iPhone?",
    "Now open your phone's settings. Is your phone Android or iPhone?",
    "Now open the app. Which language do you want?",
    "You registered on our app last week. Is now a good time to talk?",
)


def _kinds(reply: str, language: str = "en-IN") -> set[str]:
    return {p.kind for p in turn_problems(reply, language=language)}


# --- the call review ----------------------------------------------------------------------


@pytest.mark.parametrize("turn", sorted(EN_TURNS))
def test_each_english_stand_in_is_flagged(turn: int) -> None:
    assert KIND in _kinds(EN_TURNS[turn])


@pytest.mark.parametrize("turn", sorted(TE_TURNS))
def test_each_telugu_turn_of_the_call_is_flagged(turn: int) -> None:
    assert asks_done_too_soon(TE_TURNS[turn]) is not None
    assert KIND in _kinds(TE_TURNS[turn], "te-IN")


@pytest.mark.parametrize("turn", sorted(TE_CLEAN))
def test_the_calls_other_turns_are_not(turn: int) -> None:
    assert asks_done_too_soon(TE_CLEAN[turn]) is None


@pytest.mark.parametrize("reply", INVITES + NOT_ABOUT_DONE)
def test_an_invitation_or_a_question_about_something_else_is_not_flagged(reply: str) -> None:
    assert asks_done_too_soon(reply) is None
    assert KIND not in _kinds(reply)


def test_the_flag_quotes_the_question() -> None:
    found = asks_done_too_soon(EN_TURNS[22])
    assert found == "Have you logged in?"
    reason = next(p.reason for p in turn_problems(EN_TURNS[22]) if p.kind == KIND)
    assert "Have you logged in?" in reason and "say when it is done" in reason


@dataclass(frozen=True)
class _T:
    idx: int
    speaker: str
    text: str


def test_the_call_page_names_it_at_the_first_turn() -> None:
    call = [
        _T(1, "agent", "Hello, this is Asha from Rytu Khata. Can we talk now?"),
        _T(2, "caller", "Yes, go on."),
        _T(3, "agent", "Is your phone Android or iPhone?"),
        _T(4, "caller", "Android."),
        _T(5, "agent", EN_TURNS[12]),
        _T(6, "caller", "Yes, it opened."),
    ]
    assert mistakes_in(call, language="en-IN")[KIND] == 5
    assert KIND in SOUND_KINDS
    assert LESSONS[KIND].label and "say when it is done" in LESSONS[KIND].instead


# --- the script check and the healer -------------------------------------------------------


def _stage(sid: str, line: str, **extra: object) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid, "instruction": "Help them.", "sounds_like": line, **extra}
    )


def _script(*stages: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, opening_line=OPENING, stages=list(stages))


def _paths(script: CallScript) -> list[str]:
    return [f.partition(": ")[0] for f in mistake_findings(script, LintContext(), KIND)]


def test_the_script_line_a_step_list_action_and_a_telugu_line_are_traced() -> None:
    script = _script(
        _stage(
            "install",
            EN_TURNS[22],
            scripts={"te-IN": TE_TURNS[12]},
            procedure=[
                ProcedureStep(action="Tap the three-dot menu. Did it open?", wait_for="It opened"),
                ProcedureStep(action="Tap Add to Home screen. Tell me when the icon shows."),
            ],
        )
    )
    assert _paths(script) == [
        "stages.0.sounds_like",
        "stages.0.scripts.te-IN",
        "stages.0.procedure.0.action",
    ]
    finding = mistake_findings(script, LintContext(), KIND)[0]
    assert "end the line on the action itself" in finding


def test_the_opening_is_never_named() -> None:
    script = CallScript(
        schema_version=2,
        opening_line="Hello, please open the app now. Has it opened?",
        stages=[_stage("s1", "Which language do you want?")],
    )
    assert _paths(script) == []


def test_the_healer_repairs_it_and_the_repaired_line_is_clean() -> None:
    faulted = _script(_stage("s1", EN_TURNS[22]), _stage("close", "Thank you, goodbye."))
    assert any(
        f.startswith("stages.0.sounds_like: gives an action")
        for f in script_heal.heal_findings(faulted, LintContext())
    )
    assert KIND in script_heal.mistake_kinds(faulted, LintContext())
    repaired = _script(
        _stage(
            "s1",
            "Now enter your registered mobile number.",
        ),
        _stage("close", "Thank you, goodbye."),
    )
    assert _paths(repaired) == []
    assert not any("whether it is done" in f for f in script_mistakes(repaired, LintContext()))


async def test_the_repair_pass_rewrites_the_line_into_the_action_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    invited = "Now tap the three-dot menu at the top right."
    faulted = _script(_stage("menu", EN_TURNS[12]), _stage("close", "Thank you, goodbye."))
    fixed = _script(_stage("menu", invited), _stage("close", "Thank you, goodbye."))
    tenant_id, agent_id = await _account("done")
    line_id = await _line(tenant_id, agent_id, faulted)
    seen = _writer(monkeypatch, fixed)
    await _queue(tenant_id, "line", line_id)

    outcome = await heal_job.repair_holder_script({}, _payload(tenant_id, "line", line_id))

    assert outcome == "repaired"
    assert "stages.0.sounds_like" in seen["changes"][0]
    assert "end the line on the action itself" in seen["changes"][0]
    row = await _row(tenant_id, "inbound_lines", line_id)
    assert CallScript.model_validate(row.script).stages[0].sounds_like == invited
    assert KIND in row.script_heal_fixed


# --- the in-call rule and the writer -------------------------------------------------------


def test_every_agent_is_told_never_to_ask_if_done() -> None:
    """The invitation this test once pinned went too (Varsha call of 26 Nov 2026): a step's turn
    ends on the action."""
    assert 'never "say when done", never "done?"' in VOICE_STYLE_GUIDANCE
    assert "One action a turn, then stop;" in PROCEDURE_LEAD
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        direction="outbound",
        language_primary="te-IN",
        system_prompt="",
        opening_line="",
        call_is_recorded=True,
    )
    assert 'never "done?"' in compose_engine_prompt(cfg)


def test_the_script_writer_is_told_the_same() -> None:
    assert "nor whether it is done before they have had time to do it" in SCRIPT_FLOW_RULE
    assert SCRIPT_FLOW_RULE in writer_rules()
