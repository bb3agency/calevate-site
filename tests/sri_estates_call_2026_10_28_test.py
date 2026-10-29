"""The founder's Sri Estates call of 28 Oct 2026, 02:00 IST (D-912).

Outbound, Telugu, agent "Anjali", made after D-910 was deployed. Five platform faults: asked
who it was, the agent said who and why and asked "can we talk now?" again; it offered "two
BHK or three BHK?" for a count; it took "టీవీహెచ్కే", which names neither, as three BHK; asked
to speak slowly, it promised to; and it closed with four details read back, a promise and a
question in one turn. Each line below is the agent's as the call had it.
"""

from __future__ import annotations

from typing import Any

from apps.api.agents.test_conversations import Turn
from apps.api.agents.turn_checks import (
    SOUND_KINDS,
    conversation_problems,
    turn_problems,
)
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    OPENING_CONTINUES_RULE,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
)

OPENING = "నమస్కారం అండి, Sri Estates నుంచి call చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"
WHO = Turn(
    "Tell me who.",
    "నేను Sri Estates నుంచి AI అసిస్టెంట్ ని అండి. మీరు ఇందాక మా వెబ్‌సైట్‌లో ప్రాపర్టీ గురించి "
    "ఎంక్వైరీ చేశారు కదా, దానికి సంబంధించి మీకు సహాయం చేయడానికి కాల్ చేశాను. ఇప్పుడు మాట్లాడొచ్చా?",
)
STILL_LOOKING = Turn("Ah, tell me.", "మీరు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా చూస్తున్నారా అండి?")
SLOWLY = Turn(
    "చూస్తున్నాను, మీరు కొంచెం చిన్నగా మాట్లాడతారా? మీరు మాట్లాడేది నాకు అంతగా అర్థం అవ్వట్లేదు.",
    "సారీ అండి, ఇక నుంచి నెమ్మదిగా మాట్లాడతాను. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?",
)
BHK = Turn(
    "నేను గుంటూరులో చూస్తున్నాను అండి.",
    "మంచిది అండి, గుంటూరులో చూస్తున్నారు కదా. మీకు ఎన్ని బెడ్ రూమ్స్ అంటే ఇష్టం, అంటే టూ బి హెచ్ కె నా లేక త్రీ బి హెచ్ కె నా?",
)
PICKED = Turn("టీవీహెచ్కే.", "సరే అండి, త్రీ బి హెచ్ కె. మీ బడ్జెట్ దాదాపు ఎంతలో చూస్తున్నారు?")
BUDGET = Turn("ఒక 2 క్రోర్స్ అండి.", "రెండు కోట్లు అండి. సరే, మీరు ఎప్పటిలోపు ప్రాపర్టీ తీసుకోవాలని ప్లాన్ చేస్తున్నారు?")
WHEN = Turn(
    "ఇంకొక వన్ మంత్ లో.",
    "మంచిది అండి, వన్ మంత్ లో ప్లాన్ చేస్తున్నారు కదా. మా ప్రాజెక్ట్ చూడటానికి మీకు ఈ వీకెండ్ లో "
    "శనివారం కుదురుతుందా, లేక ఆదివారం కుదురుతుందా అండి?",
)
UNCLEAR = Turn(
    "సాంబె సాంబె.",
    "క్షమించండి అండి, సరిగ్గా అర్థం కాలేదు. శనివారం కుదురుతుందా, లేక ఆదివారం కుదురుతుందా అండి?",
)
RECAP = Turn(
    "సాటర్డే అండి, సాటర్డే వస్తాను.",
    "సరే అండి, సాటర్డే కి ఫిక్స్ చేద్దాం. మీరు త్రీ బి హెచ్ కె కోసం గుంటూరులో చూస్తున్నారు, బడ్జెట్ "
    "రెండు కోట్లు, వన్ మంత్ లో ప్లాన్ చేస్తున్నారు, సాటర్డే సైట్ విజిట్ కి వస్తున్నారు. ఇవన్నీ మా టీమ్ "
    "కి చెప్తాను, వాళ్ళు మీకు కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా మీకు కావాలా అండి?",
)
GOODBYE = Turn("ఇంకేం లేదు అంతే.", "సరే అండి, థాంక్స్ అండి. ఉంటాను మరి.")
CALL = (WHO, STILL_LOOKING, SLOWLY, BHK, PICKED, BUDGET, WHEN, UNCLEAR, RECAP, GOODBYE)


def _anjali(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Anjali",
        "business": "Sri Estates",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": "Call people who enquired about a property.",
        "opening_line": OPENING,
        "call_is_recorded": True,
        "facts_in_knowledge": True,
        "knowledge_tool": "search_knowledge",
    }
    return AgentConfig(**{**fields, **over})


def _kinds(reply: str, said: str = "") -> set[str]:
    return {p.kind for p in turn_problems(reply, caller_said=said, language="te-IN")}


def _call_kinds(turns: tuple[Turn, ...] | list[Turn], opening: str = OPENING) -> list[str]:
    known = "మీరు మా వెబ్‌సైట్‌లో ఎంక్వైరీ చేశారు"
    return [p.kind for p in conversation_problems(list(turns), opening=opening, known=known)]


def test_the_prompt_carries_each_fix_and_keeps_the_locked_text() -> None:
    prompt = compose_engine_prompt(_anjali())
    assert VOICE_STYLE_GUIDANCE in prompt
    # F1: an outbound agent now has the who-is-calling rule, ending on its first question.
    assert OPENING_CONTINUES_RULE in prompt
    assert "Asked who or why? Say both in one line, then stop and wait." in prompt
    for clause in (
        # F2: no options for a count, not even as examples after an open question.
        "never for counts or amounts, not even as examples.",
        # F3: an answer that fits no option is asked again.
        "- Unclear? Ask again; never pick for them.",
        # F4: no promise to slow down.
        "Too fast or hard to follow? Sorry once, no promise, go on where you were, shorter.",
        # F5: one line for the close.
        "- Close: what happens next in one line, no recap, anything else, then one goodbye",
    ):
        assert clause in prompt, clause
    assert CONFIDENTIALITY_MARKER in prompt and TRUTHFUL_ANSWER_MARKER in prompt
    assert prompt.index(CONFIDENTIALITY_MARKER) < prompt.index(TRUTHFUL_ANSWER_MARKER)


def test_the_opening_asked_again_after_who_is_this_is_noted() -> None:
    assert "opened_again" in _call_kinds([WHO])
    # Later in the call too, where the first-reply check does not look.
    assert "opened_again" in _call_kinds([STILL_LOOKING, WHO])
    # In a language the phrase list does not hold, by the opening's own question.
    tamil = "இப்போது பேசலாமா?"
    later = Turn("யார்?", f"நான் Sri Estates இலிருந்து பேசுகிறேன். {tamil}")
    assert "opened_again" in _call_kinds([STILL_LOOKING, later], opening=f"வணக்கம். {tamil}")
    assert "opened_again" in SOUND_KINDS
    # Going on to the first question is right, and "anything else?" at the close is no
    # second opening.
    answered = Turn(WHO.said, "నేను Sri Estates నుంచి AI అసిస్టెంట్ ని అండి. ఇంకా చూస్తున్నారా అండి?")
    assert "opened_again" not in _call_kinds([answered, GOODBYE])


def test_two_or_three_bhk_offered_for_a_count_is_noted() -> None:
    assert "offered_numbers" in _kinds(BHK.reply, BHK.said)
    assert "offered_numbers" in _kinds("టూ బీహెచ్కే కావాలా, త్రీ బీహెచ్కే కావాలా అండి?")
    assert "offered_numbers" in _kinds("Two BHK or three BHK?")
    assert "offered_numbers" in SOUND_KINDS
    # An open question, a choice of times or days, and a check of the caller's own figure
    # are all right.
    assert "offered_numbers" not in _kinds("ఎన్ని బీహెచ్కే కావాలి అండి?")
    assert "offered_numbers" not in _kinds(UNCLEAR.reply, UNCLEAR.said)
    assert "offered_numbers" not in _kinds("ఆరు గంటలకా, ఏడు గంటలకా అండి?")
    assert "offered_numbers" not in _kinds("వన్ క్రోర్ నా, టూ క్రోర్స్ నా?", "వన్ టూ క్రోర్స్.")


def test_an_answer_that_names_no_option_taken_as_one_is_noted() -> None:
    assert "picked_for_them" in _call_kinds([BHK, PICKED])
    assert "picked_for_them" in SOUND_KINDS
    # Asking again is right; so is taking an answer that named the number.
    asked = Turn(PICKED.said, "సారీ అండి, ఎన్ని బీహెచ్కే అన్నారు?")
    assert "picked_for_them" not in _call_kinds([BHK, asked])
    named = Turn("త్రీ బీహెచ్కే.", PICKED.reply)
    assert "picked_for_them" not in _call_kinds([BHK, named])


def test_a_promise_to_speak_slowly_is_noted() -> None:
    assert "promised_pace" in _kinds(SLOWLY.reply, SLOWLY.said)
    assert "promised_pace" in _kinds("Sorry, I'll speak more slowly. Which area?")
    assert "promised_pace" in SOUND_KINDS
    assert "promised_pace" not in _kinds("సారీ అండి. ఏ ఏరియాలో చూస్తున్నారు?", SLOWLY.said)


def test_the_four_detail_recap_at_the_close_is_too_long() -> None:
    assert "too_long" in _kinds(RECAP.reply, RECAP.said)
    assert "too_long" not in _kinds("సాటర్డే అండి, టీమ్ కాల్ చేసి కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా కావాలా అండి?", RECAP.said)


def test_the_whole_call_shows_each_fault_and_nothing_it_did_right() -> None:
    kinds = set(_call_kinds(CALL))
    for line in CALL:
        kinds |= _kinds(line.reply, line.said)
    assert {"opened_again", "offered_numbers", "picked_for_them", "promised_pace"} <= kinds
    assert "too_long" in kinds
    # Asking again after "సాంబె సాంబె" is what it should do, not a repeat to note.
    assert "asked_again" not in kinds
