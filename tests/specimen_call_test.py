"""The specimen call of 11 Oct 2026, replayed through the checks that must catch it (D-749).

A Raghava Organics outbound call in Telugu showed failure classes that can happen to any
business in any language: "done" with no action behind it, the call's own number asked for,
part of a number taken as all of it, goodbye while the caller was still asking, a whole turn
repeated when the caller asked to hear it again, a product described from nothing, a price in
native number words and digits, a Korean letter mid-Telugu, and actions written as text
(`docs/evidence/specimen-call-raghava-2026-10-11.md`). The caller's number is replaced by a
made-up prefix. Each class must be caught by a hard check, and the replies a good agent gives
must pass.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from apps.api.agents.specimen_scenarios import (
    CLASSES,
    PER_RUN,
    all_specimen_scenarios,
    specimen_scenarios,
)
from apps.api.agents.test_conversations import (
    MAX_LINE_CHARS,
    MAX_TURNS,
    Scenario,
    Turn,
    hard_check,
    speech_problems,
)
from apps.api.agents.turn_checks import (
    PLATFORM_KINDS,
    claims_done,
    conversation_problems,
    turn_problems,
)
from apps.api.engine import thinnest
from apps.api.engine.thinnest import ThinnestEngine
from apps.workers import pipeline
from apps.workers.moments import derive_moments
from calevate_shared.engine import (
    ACTION_CLAIM_RULE,
    CALL_NUMBER_RULE,
    CANNOT_HELP_HEADER,
    CLIENT_SCRIPT_CLOSE,
    CONFIDENTIALITY_MARKER,
    AgentConfig,
    ExecutionSnapshot,
    compose_engine_prompt,
)
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import MODEL_MOMENT_KINDS, MOMENT_KINDS
from tests.thinnest_engine_test import _cfg


@dataclass(frozen=True)
class Ex:
    said: str
    reply: str
    tools: list[str] = field(default_factory=list)


#: The call, caller line then the agent's reply. "987" stands in for the caller's digits.
SPECIMEN: tuple[Ex, ...] = (
    Ex(
        "చెప్పండి.",
        "మేము సహజంగా పెంచిన పచ్చి మిర్చి, మిర్చి పొడి, ఇంకా ఇతర ఆర్గానిక్ ఆహారాలు అమ్ముతాం.మీరు "
        "సాధారణంగా whole chilli, powder, లేదా రెండింటి ఏది ఎక్కువగా కొనుగోలు చేస్తారు, మరియు "
        "నెలకు సుమారు ఎంత కావాలి?",
    ),
    Ex(
        "ఆ అలా మళ్ళా చెప్పండి.",
        "మేము సహజంగా పెంచిన పచ్చి మిర్చి, మిర్చి పొడి, ఇంకా ఇతర ఆర్గానిక్ ఆహారాలు అమ్ముతాం.మీరు "
        "సాధారణంగా whole chilli, powder, లేదా రెండింటి ఏది ఎక్కువగా కొనుగోలు చేస్తారు, మరియు "
        "నెలకు సుమారు ఎంత కావాలి?",
    ),
    Ex(
        "రెండోది ఏంటి?",
        "మిర్చి పొడి అంటే పచ్చి మిర్చిని ఎండబెట్టి, నూరి 만든 పౌడర్. మీరు powder కూడా కావాలనుకుంటున్నారా?",
    ),
    Ex(
        "మిర్చి పొడి అంటే ఎండు మిర్చిని పౌడర్ చేసేది",
        "అవునండి, powder ఎండ మిర్చి పౌడర్. మీరు powder ఎంత కావాలి, ఉదాహరణకి ఒక కిలో లేదా రెండు?"
        "మీకు powder ఎంత కావాలి?[cut off before finishing]మీకు powder ఎంత కావాలి?",
    ),
    Ex(
        "పావుడరా నెలకు ఒక కేజీ పట్టింది.",
        "సరే అండి, మీరు powder నెలకు ఒక కేజీ కావాలి. మీరు డెలివరీ కోరుకుంటున్నారా, లేక మీరు స్వయంగా తీసుకెళ్తారా?",
    ),
    Ex("డెలివరీ కావాలి.", "డెలివరీ కోసం మీ ప్రాంతం ఏది?(Waiting for user response)"),
    Ex(
        "గుంటూరు",
        "గుంటూరు ప్రాంతానికి డెలివరీ చేయగలం. 1 కిలో మిర్చి పొడి ధర ఆరు నూరు రూపాయలు. మీరు ఈ "
        "నెలకు ఒక కేజీ powder ఆర్డర్ చేసుకుంటున్నాం, సరే?సరే అండి, మీరు ఆర్డర్ "
        "నిర్ధారించాలనుకుంటున్నారా?",
    ),
    Ex(
        "అవును.",
        "సరే అండి, మీ ఆర్డర్ నమోదు చేసాం. మీరు ఫోన్ నంబర్ లేదా ఇమెయిల్ ఇవ్వగలరా, తద్వారా డెలివరీ వివరాలు పంపగలం?",
    ),
    Ex("సరే.", "మీరు ఫోన్ నంబర్ లేదా ఇమెయిల్ ఇవ్వగలరా?"),
    Ex("ఫోన్ నెంబర్ 987.", "thanks అండి, details సేవ్ చేసాం. మీకు ఇంకేమైనా సహాయం కావాలా?"),
    Ex(
        "ఫోన్ నెంబర్ పూర్తిగా తీసుకోలేదుగా",
        "క్షమించండి, పూర్తి ఫోన్ నంబర్ ఇవ్వగలరా, దయచేసి?[awaiting response]",
    ),
    Ex(
        "మరి ఇందాకే",
        "ఇంకేమైనా అవసరమైతే చెప్పండి. లేకపోతే, thanks అండి, goodbye! [call hang_up]",
    ),
    Ex("మరి ఇందాక ఎందుకు నైన్ డబల్ ఫోర్ అనంగానే", "thanks అండి, goodbye! [hang_up]"),
    Ex(
        "987 అనంగానే ఆపేశారు.",
        "క్షమించండి, దయచేసి పూర్తి ఫోన్ నంబర్ చెప్పగలరా, ఉదాహరణకు ఎనిమిది అంకెలు లేదా ఎక్కువ?",
    ),
    Ex("చెబుతున్నా వినండి ఒక మాట.", "సరే, పూర్తి ఫోన్ నంబర్ ఇవ్వండి, దయచేసి.[hang_up]"),
    Ex("987", "thanks అండి, goodbye! [hang_up]"),
)


def _turn_kinds() -> set[str]:
    return {
        p.kind
        for ex in SPECIMEN
        for p in turn_problems(ex.reply, caller_said=ex.said, language="te-IN")
    }


def _conversation_kinds(exchanges: tuple[Ex, ...] | list[Ex], **kw: bool) -> list[str]:
    return [p.kind for p in conversation_problems(exchanges, **kw)]


# --- every class of the specimen is caught ------------------------------------------------


def test_every_reply_level_class_of_the_specimen_is_caught() -> None:
    kinds = _turn_kinds()
    for kind in (
        "brackets",  # [cut off before finishing], (Waiting for user response), [hang_up]
        "foreign_script",  # the Korean syllable
        "spoken_number",  # ఆరు నూరు రూపాయలు and 1 కిలో
        "formal_words",  # కొనుగోలు, మరియు, సుమారు, సహజంగా, ఆహారాలు, నమోదు …
        "repeated_question",
        "too_long",
    ):
        assert kind in kinds, kind


def test_every_conversation_level_class_of_the_specimen_is_caught() -> None:
    kinds = _conversation_kinds(SPECIMEN)
    assert kinds == [
        "repeated_turn",
        "unconfirmed_action",
        "asked_known_number",
        "partial_number",
        "goodbye_while_asking",
    ]
    assert {"unconfirmed_action", "asked_known_number", "partial_number"} <= PLATFORM_KINDS


def test_the_new_formal_words_of_the_specimen_are_listed() -> None:
    reply = " ".join(SPECIMEN[i].reply for i in (0, 4, 5, 6, 7))
    words = {p.reason for p in turn_problems(reply, language="te-IN")}
    text = " ".join(words)
    for formal in ("సహజంగా", "నిర్ధారించాలనుకుంటున్నారా", "తద్వారా", "స్వయంగా", "ప్రాంతం"):
        assert formal in text, formal


def test_the_specimen_fails_the_test_loop_as_a_platform_problem() -> None:
    turns = [Turn(said=ex.said, reply=ex.reply) for ex in SPECIMEN]
    scenario = Scenario(key="x", title="x", category="edge", turns=(), expect="")
    check = hard_check(scenario, turns, language="te-IN")
    assert check.verdict == "failed" and check.fix == "platform"
    kinds = {p.kind for p in speech_problems(turns, language="te-IN")}
    assert {"unconfirmed_action", "partial_number", "goodbye_while_asking"} <= kinds


# --- and what a good agent says passes ---------------------------------------------------


def test_an_honest_next_step_and_the_same_number_pass() -> None:
    good = [
        Ex("అవును.", "సరే అండి, team confirm చేసి మీకు call చేస్తారు. ఇదే నంబర్ కి details పంపమంటారా?"),
        Ex("సరే.", "సరే అండి, thanks. ఇంకేమైనా కావాలా?"),
        Ex("ఏమీ లేదు, thanks.", "సరే అండి, thanks, bye!"),
    ]
    assert _conversation_kinds(good) == []
    for ex in good:
        assert claims_done(ex.reply) is False


def test_a_claim_after_a_connected_action_ran_passes() -> None:
    booked = [
        Ex("Book it for Saturday.", "Done, I've booked you for Saturday at five.", ["book_slot"])
    ]
    assert _conversation_kinds(booked) == []
    looked_up = [Ex("Book it.", "I've booked it.", ["search_knowledge"])]
    assert _conversation_kinds(looked_up) == ["unconfirmed_action"]


def test_a_number_taken_in_small_groups_and_read_back_passes() -> None:
    groups = [
        Ex("Use my other number.", "Sure, what is it? Tell me a few digits at a time."),
        Ex("98765", "Nine eight seven six five, and the rest?"),
        Ex("43210", "Nine eight seven six five, four three two one zero. Is that right?"),
        Ex("Yes.", "Thanks, I have it. Anything else?"),
    ]
    assert _conversation_kinds(groups) == []
    # The same number cut short is caught.
    short = [groups[0], Ex("98765", "Thanks, I have it. Anything else?")]
    assert _conversation_kinds(short) == ["partial_number"]


def test_asking_for_a_number_is_right_when_the_caller_wants_another_or_it_was_hidden() -> None:
    other = [Ex("Send it to a different number.", "Sure, what's the number?")]
    assert _conversation_kinds(other) == []
    hidden = [Ex("Please call me back.", "Of course. What's your phone number?")]
    assert _conversation_kinds(hidden) == ["asked_known_number"]
    assert _conversation_kinds(hidden, number_known=False) == []


def test_goodbye_after_the_caller_closes_passes_and_mid_question_fails() -> None:
    assert _conversation_kinds([Ex("No, that's all, thanks.", "Thank you, goodbye!")]) == []
    assert _conversation_kinds([Ex("లేదు అండి.", "సరే అండి, bye!")]) == []
    assert _conversation_kinds([Ex("But why did you stop me?", "Thanks, goodbye!")]) == [
        "goodbye_while_asking"
    ]


def test_a_simpler_repeat_passes() -> None:
    first = Ex("What do you sell?", "We sell whole chilli and chilli powder. Which do you want?")
    again = Ex("Say that again?", "Whole chilli or powder?")
    assert _conversation_kinds([first, again]) == []


@pytest.mark.parametrize(
    ("reply", "language", "kind"),
    [
        ("ఆరు వందల రూపాయలు అండి.", "te-IN", "spoken_number"),
        ("छह सौ रुपये है जी।", "hi-IN", "spoken_number"),
        ("2 किलो ले लीजिए।", "hi-IN", "spoken_number"),
        ("ఇది 맛있는 powder.", "te-IN", "foreign_script"),
        ("यह అది है।", "hi-IN", "foreign_script"),
        ("It is good. Привет.", "en-IN", "foreign_script"),
    ],
)
def test_reply_level_classes_in_three_languages(reply: str, language: str, kind: str) -> None:
    assert kind in {p.kind for p in turn_problems(reply, language=language)}


@pytest.mark.parametrize(
    "reply",
    [
        "Six hundred rupees a kg.",
        "six hundred rupees అండి.",
        # A whole reply in Hindi is a language switch, not a stray letter.
        "हमारे पास है जी, six hundred rupees.",
        # A danda after Telugu is punctuation, not Hindi.
        "నమస్కారం అండి।",
    ],
)
def test_the_english_way_and_plain_punctuation_pass(reply: str) -> None:
    kinds = {p.kind for p in turn_problems(reply, language="te-IN")}
    assert "spoken_number" not in kinds
    assert "foreign_script" not in kinds


@pytest.mark.parametrize(
    "text",
    [
        "Your order has been placed.",
        "I've saved your details.",
        "మీ ఆర్డర్ నమోదు చేసాం.",
        "details సేవ్ చేశాం.",
        "మీకు message పంపాను.",
        "आपका order बुक कर दिया है।",
        "details भेज दिए हैं।",
    ],
)
def test_done_claims_in_three_languages(text: str) -> None:
    assert claims_done(text)


@pytest.mark.parametrize(
    "text",
    [
        "I'll note this and our team will confirm.",
        "మీ details note చేసుకుంటాను, team confirm చేస్తారు.",
        "details పంపగలం.",
        "मैं note कर लेती हूँ, team confirm करेगी।",
    ],
)
def test_honest_future_wording_is_not_a_claim(text: str) -> None:
    assert not claims_done(text)


# --- standing scenarios ----------------------------------------------------------------


@pytest.mark.parametrize("language", ["te-IN", "hi-IN", "en-IN"])
@pytest.mark.parametrize("business_type", ["retail", "local_services", "clinic", "custom"])
def test_every_class_is_a_caller_for_every_business_and_language(
    language: str, business_type: str
) -> None:
    scenarios = all_specimen_scenarios(language, business_type)
    assert [s.key for s in scenarios] == [c.key for c in CLASSES]
    for scenario in scenarios:
        assert 1 <= len(scenario.turns) <= MAX_TURNS
        assert all(0 < len(t) <= MAX_LINE_CHARS for t in scenario.turns)
        assert scenario.source == "standard" and scenario.expect


def test_the_clinic_lines_reach_only_a_clinic() -> None:
    clinic = {s.key: s.turns for s in all_specimen_scenarios("en-IN", "clinic")}
    shop = {s.key: s.turns for s in all_specimen_scenarios("en-IN", "retail")}
    assert "doctor" in clinic["specimen_done_without_action"][0]
    assert all("doctor" not in " ".join(turns) for turns in shop.values())


def test_runs_rotate_through_every_class() -> None:
    seen: set[str] = set()
    for n in range(60):
        picked = specimen_scenarios("te-IN", "retail", round_key=f"r{n:06x}")
        assert len(picked) == PER_RUN and len({s.key for s in picked}) == PER_RUN
        seen |= {s.key for s in picked}
    assert seen == {c.key for c in CLASSES}


# --- the platform prompt ---------------------------------------------------------------


def _config(**kw: object) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        direction="outbound",
        language_primary="te-IN",
        system_prompt="Collect their name and phone number, then take the order.",
        opening_line="",
        **kw,  # type: ignore[arg-type]
    )


def test_the_new_rules_come_after_the_client_script_and_before_confidentiality() -> None:
    prompt = compose_engine_prompt(_config())
    fence = prompt.index(CLIENT_SCRIPT_CLOSE)
    secret = prompt.index(CONFIDENTIALITY_MARKER)
    for rule in (CANNOT_HELP_HEADER, ACTION_CLAIM_RULE, CALL_NUMBER_RULE):
        assert fence < prompt.index(rule) < secret, rule


# --- ending the call on ThinnestAI -----------------------------------------------------


def test_every_agent_releases_the_line_when_it_ends_the_call() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    body = engine._agent_body(_cfg())
    assert body["voice"]["endCallOnFinish"] is True
    held = {**body, "voice": {**body["voice"], "endCallOnFinish": False}}
    assert thinnest._settings_drift(body, held) == ["end_call_on_finish"]
    assert thinnest._settings_drift(body, body) == []


# --- after the call: the owner sees the claim ------------------------------------------


def _transcript(*lines: tuple[str, str]) -> list[TranscriptTurn]:
    return [
        TranscriptTurn(call_id="c", idx=i, speaker=speaker, text=text, start_ms=i * 5000)  # type: ignore[arg-type]
        for i, (speaker, text) in enumerate(lines)
    ]


def test_the_claim_moment_is_derived_and_never_suggested_by_the_model() -> None:
    assert MOMENT_KINDS["claimed_not_done"][0] == "attention"
    assert "claimed_not_done" not in MODEL_MOMENT_KINDS
    turns = _transcript(("caller", "అవును."), ("agent", "సరే అండి, మీ ఆర్డర్ నమోదు చేసాం."))
    moments = derive_moments(
        turns=turns, extraction={}, field_labels={}, claimed_not_done_turn_idx=1
    )
    assert [m["kind"] for m in moments] == ["claimed_not_done"]
    assert moments[0]["label"] == "Agent said it was done, but no action ran"
    assert (
        derive_moments(
            turns=turns, extraction={}, field_labels={}, claimed_not_done_turn_idx=1, unheard={1}
        )
        == []
    )


def _snapshot(turns: list[TranscriptTurn]) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    return ExecutionSnapshot(
        engine_call_id=f"conv_{uuid.uuid4().hex[:10]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now,
        ended_at=now,
        transcript=turns,
    )


async def test_a_claim_with_no_action_on_the_call_is_found() -> None:
    turns = _transcript(
        ("caller", "Yes, go ahead."),
        ("agent", "Your order has been placed."),
        ("caller", "Okay."),
    )
    tenant = uuid.uuid4()
    found = await pipeline._claim_without_action(
        tenant, uuid.uuid4(), _snapshot(turns), acted=False
    )
    assert found == 1
    assert (
        await pipeline._claim_without_action(tenant, uuid.uuid4(), _snapshot(turns), acted=True)
        is None
    )
    honest = _transcript(("agent", "I'll note it and the team will confirm."))
    assert (
        await pipeline._claim_without_action(tenant, uuid.uuid4(), _snapshot(honest), acted=False)
        is None
    )
