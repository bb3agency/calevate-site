"""The stall check heard only on bare acknowledgements, whole-word sign-offs, a campaign
opening said as taught, and the opening's room and held-back message counted exactly."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from apps.api.agents import live_apply, turn_checks
from apps.api.agents import service as agents_service
from apps.api.agents.call_mistakes import mistakes_in
from apps.api.agents.engine_limits import (
    OPENING_TOO_LONG,
    OpeningTooLongError,
    greeting_budget,
    refuse_over_engine_limits,
)
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.agents.script_lint import LintContext
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared import call_words
from calevate_shared.call_script import (
    PRONOUNCE_LEAD,
    CallScript,
    ConversationStage,
    compile_call_script,
)
from calevate_shared.engine import AgentConfig, DisclosurePosture, notice_fields


@pytest.fixture
def _file_alone() -> Any:
    call_words.install(None)
    yield
    call_words.install(None)


# --- a stall is a bare acknowledgement after a line that asked nothing ---------------------


@pytest.mark.parametrize(
    "reply", ["OK, no problem.", "Sure sir.", "Okay, that's fine.", "Thank you so much."]
)
def test_an_acknowledgement_alone_is_only_a_reaction(reply: str) -> None:
    assert turn_checks.only_reaction(reply)


@pytest.mark.parametrize(
    "reply", ["Please share your pincode.", "It is free.", "Yes, on Sunday.", "Ten rupees."]
)
def test_a_short_line_that_carries_something_is_not_only_a_reaction(reply: str) -> None:
    assert not turn_checks.only_reaction(reply)


def _hindi_question() -> str:
    """A Hindi yes/no question without a "?", from the words the file already holds."""
    kya = next(
        w
        for w in call_words.words("turn_checks._FILLER")
        if turn_checks._HI_QUESTION.search(f"{w} it is open")
    )
    return f"{kya} it is open on Sunday"


@pytest.mark.parametrize(
    ("said", "reply"),
    [
        ("Is it open on Sunday", "Yes."),
        ("Tell me the price", "Sure."),
        ("Send the photo please", "OK."),
        ("Give me the address", "Sure."),
    ],
)
def test_a_short_answer_to_a_question_or_a_request_is_not_stalled(said: str, reply: str) -> None:
    assert not turn_checks.stalled(said, reply, "What else?", language="en-IN")


def test_a_short_answer_to_a_question_read_by_its_words_is_not_stalled() -> None:
    assert not turn_checks.stalled(_hindi_question(), "Yes.", "What else?", language="en-IN")


def test_a_bare_reaction_to_a_statement_is_still_stalled_in_english() -> None:
    said = "I have not used it at all so far."
    assert turn_checks.stalled(said, "OK, no problem.", "So what is it?", language="en-IN")
    assert turn_checks.stalled(said, "OK, no problem.", "So what is it?")


@pytest.mark.usefixtures("_file_alone")
def test_a_bare_telugu_reaction_is_stalled_and_one_after_a_wait_is_not() -> None:
    """FAILS IF: the shipped Telugu words stop hearing "సరేనండి, పర్వాలేదు." as only a
    reaction, or hear one that carries something, or miss a caller asking to wait."""
    assert turn_checks.hears_stalls("te-IN")
    said = "నేను ఇంకా వాడలేదు."
    assert turn_checks.only_reaction("సరేనండి, పర్వాలేదు.")
    assert turn_checks.only_reaction("మంచిదండి.")
    assert not turn_checks.only_reaction("సరేనండి, మీ పిన్‌కోడ్ చెప్పండి.")
    assert turn_checks.stalled(said, "సరేనండి.", "ఇప్పుడు ఏం చేయాలి?", language="te-IN")
    wait = "ఒక్క నిమిషం ఆగండి, చూసి చెప్తాను."
    assert turn_checks._ASKS_TO_WAIT.search(wait)
    assert not turn_checks.stalled(wait, "సరేనండి.", "ఇప్పుడు ఏం చేయాలి?", language="te-IN")


@pytest.mark.usefixtures("_file_alone")
def test_telugu_enough_and_stay_are_heard_only_in_their_narrow_forms() -> None:
    """FAILS IF: "చాలు" ending an order reads as a goodbye, or "ఉండండి" meaning "be" reads
    as a caller asking to wait."""
    assert turn_checks.caller_signs_off("చాలండి.")
    assert turn_checks.caller_signs_off("సరే, ఇక చాలు.")
    assert turn_checks.caller_signs_off("ఇంకేం వద్దండి.")
    assert not turn_checks.caller_signs_off("రెండు కిలోలు చాలు.")
    assert turn_checks._ASKS_TO_WAIT.search("కొంచెం ఉండండి, చూస్తాను.")
    assert not turn_checks._ASKS_TO_WAIT.search("జాగ్రత్తగా ఉండండి.")


@pytest.mark.parametrize("language", ["hi-IN", "ta-IN"])
def test_no_stall_is_noted_in_a_language_without_its_words(language: str) -> None:
    said = "I have not used it at all so far."
    assert not turn_checks.hears_stalls(language)
    assert not turn_checks.stalled(said, "OK, no problem.", "So what is it?", language=language)
    turns = [
        _Turn(0, "caller", said),
        _Turn(1, "agent", "OK, no problem."),
        _Turn(2, "caller", "So what is it?"),
        _Turn(3, "agent", "It keeps your accounts. Shall I show you how?"),
    ]
    assert "stalled" not in mistakes_in(turns, language=language)


@pytest.mark.usefixtures("_file_alone")
def test_a_language_is_heard_once_the_founder_lists_both_word_lists() -> None:
    shipped = call_words.shipped()["turn_checks.stall_words"]
    half = {**shipped, "te": {"acknowledgements": ["zzq"], "waits": []}}
    call_words.install({"turn_checks.stall_words": half})
    assert not turn_checks.hears_stalls("te-IN")
    both = {**shipped, "te": {"acknowledgements": ["zzq"], "waits": ["qqz zzw"]}}
    call_words.install({"turn_checks.stall_words": both})
    assert turn_checks.hears_stalls("te-IN")
    assert turn_checks.only_reaction("Zzq.")
    assert turn_checks._ASKS_TO_WAIT.search("ok qqz  zzw")
    assert not turn_checks._ASKS_TO_WAIT.search("ok xqqz zzw")


def test_the_editor_accepts_the_shipped_stall_words() -> None:
    assert (
        call_words.problems(
            "turn_checks.stall_words", call_words.shipped()["turn_checks.stall_words"]
        )
        == []
    )


class _Turn:
    def __init__(self, idx: int, speaker: str, text: str) -> None:
        self.idx, self.speaker, self.text = idx, speaker, text


# --- a script step that asks for something is not a bare reaction ---------------------------


def _stage(sid: str, line: str) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid, "instruction": "Help them.", "sounds_like": line}
    )


def test_a_request_step_is_not_flagged_as_only_a_reaction() -> None:
    script = CallScript(
        schema_version=2,
        opening_line="Hello, can we talk now?",
        stages=[
            _stage("s1", "Which area?"),
            _stage("s2", "Please share your pincode."),
            _stage("s3", "Thank you."),
        ],
    )
    assert mistake_findings(script, LintContext(), "stalled") == []


# --- a sign-off is heard as a whole word -----------------------------------------------------


def _indic_sign_offs() -> tuple[str, str]:
    """The Telugu 'bye' and 'that is all' the file lists, read from it."""
    plain = [
        word
        for word in call_words.say("turn_checks._CALLER_SIGNS_OFF").split("|")
        if not word.isascii() and not set(word) & set("\\()?^$*+ ")
    ]
    bye, ante = plain[0], plain[1]
    assert not bye.isascii() and not ante.isascii()
    return bye, ante


def test_an_indian_language_sign_off_is_heard_only_as_a_whole_word() -> None:
    bye, ante = _indic_sign_offs()
    assert turn_checks.caller_signs_off(f"{ante}.")
    assert turn_checks.caller_signs_off(f"ok {bye}")
    assert turn_checks.caller_signs_off(f"{bye}-{bye}")
    assert not turn_checks.caller_signs_off(f"{ante}{bye}")


def test_an_english_sign_off_still_closes() -> None:
    assert turn_checks.caller_signs_off("That's all, thanks.")
    assert turn_checks.caller_signs_off("OK bye-bye")
    assert not turn_checks.caller_signs_off("Is that all?")


# --- a campaign's own opening is said as the owner taught it -------------------------------


def _row(**extra: object) -> agents_service.AgentRow:
    return cast(
        agents_service.AgentRow,
        {
            "name": "Asha",
            "business_name": "Sri Shop",
            "prompt": f'{PRONOUNCE_LEAD}Asha as "Aasha"',
            "language_primary": "te-IN",
            "direction": "outbound",
            "ai_disclosure_line": "Idi Sri Shop AI assistant Asha.",
            "ai_disclosure_enabled": False,
            "recording_notice_line": "Ee call record avutundi.",
            "recording_notice_enabled": False,
            "caller_memory_notice_line": "",
            "caller_memory_enabled": False,
            **extra,
        },
    )


def test_a_campaign_opening_says_the_taught_names() -> None:
    words = agents_service.campaign_first_words(
        _row(), "Asha here. Can we talk now?", call_is_recorded=True
    )
    assert "Aasha here" in words and "Asha here" not in words


def test_a_campaign_opening_keeps_its_reason_after_the_introduction() -> None:
    row = _row(ai_disclosure_enabled=True)
    words = agents_service.campaign_first_words(
        row, "Calling from Sri Shop about your order. Can we talk now?", call_is_recorded=True
    )
    assert "about your order" in words
    named = agents_service.campaign_first_words(
        row, "Asha here. Can we talk now?", call_is_recorded=True
    )
    assert "Asha here" not in named and "Aasha here" not in named


# --- the opening's room is exact and a held-back opening names how far over -----------------

AI = "Idi Raghava Organics AI assistant."
RECORDING = "Ee call record avutundi."


def _cfg(posture: DisclosurePosture, opening: str) -> AgentConfig:
    return AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Receptionist",
        direction="inbound",
        system_prompt=compile_call_script(CallScript(opening_line=opening), collect=[]),
        **notice_fields(posture, call_is_recorded=True),
    )


@pytest.mark.parametrize("ai", [True, False])
def test_the_room_is_exact_for_an_opening_that_ends_on_its_mark(ai: bool) -> None:
    engine = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    posture = DisclosurePosture(
        ai_disclosure_line=AI,
        ai_disclosure_enabled=ai,
        recording_notice_line=RECORDING,
        recording_notice_enabled=True,
        caller_memory_notice_line="",
        caller_memory_enabled=False,
    )
    budget = greeting_budget(
        engine, posture=posture, opening="", direction="inbound", language="te-IN"
    )
    assert budget is not None
    fits = "a" * (budget.opening_room - 1) + "."
    refuse_over_engine_limits(engine, _cfg(posture, fits))
    with pytest.raises(OpeningTooLongError) as refused:
        refuse_over_engine_limits(engine, _cfg(posture, f"a{fits}"))
    assert refused.value.code == OPENING_TOO_LONG
    assert refused.value.length - refused.value.cap == 1


def test_a_held_back_opening_names_the_characters_over() -> None:
    exc = OpeningTooLongError(length=212, cap=200, title="t", detail="d", remediation="r")
    detail = live_apply.failure_detail(exc)
    assert detail == {"total_chars": 212, "limit_chars": 200, "over_chars": 12}
    held = live_apply.held_back_from({"code": OPENING_TOO_LONG, **detail}, None)
    assert "12 characters too long" in held.message and "opening line" in held.message
    assert held.message != live_apply.HELD_BACK_GENERIC


def test_a_held_back_opening_without_counts_still_says_to_shorten_it() -> None:
    held = live_apply.held_back_from({"code": OPENING_TOO_LONG}, None)
    assert held.message == live_apply.HELD_BACK_MESSAGES[OPENING_TOO_LONG]
    assert "Shorten the opening line" in held.message
