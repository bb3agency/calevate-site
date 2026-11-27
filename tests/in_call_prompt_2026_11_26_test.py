"""What an agent is told and given to say, from the Varsha call of 26 Nov 2026 (16:03, Telugu,
a guided app setup): a stock reaction opening every reply, every step ending "tell me when it
is done", a confused "after what should I tell you?" taken as done, the opening's "is now a
good time / shall we help" asked again, and an English "Hmm... I see" on a Telugu call.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents.call_handling import CallSettings
from apps.api.agents.service import _call_settings_fields, filler_lines_for
from apps.api.engine.thinnest import ThinnestEngine, acknowledgements_on
from calevate_shared.call_script import (
    DONE_WHEN_LEAD,
    PROCEDURE_LEAD,
    SOUNDS_LIKE_LEAD,
    SOUNDS_LIKE_TONE_LEAD,
    CallScript,
    ConversationStage,
    ProcedureStep,
    compile_call_script,
)
from calevate_shared.engine import (
    OPENING_CONTINUES_RULE,
    VOICE_STYLE_GUIDANCE,
    compose_engine_prompt,
)
from calevate_shared.spoken_style import (
    FILLERS_LEAD,
    LISTENING_USE,
    listening_lines,
    register_guidance,
    style_for,
    thinking_lines,
)
from tests.thinnest_engine_test import _cfg

# --- the step-by-step list -------------------------------------------------------------------


def test_a_step_ends_on_the_action_and_only_their_word_moves_on() -> None:
    assert PROCEDURE_LEAD.startswith("One action a turn, never two together")
    assert "Never ask them to tell you when it is done or whether it worked." in PROCEDURE_LEAD
    assert 'A bare "OK" to it is not done' in PROCEDURE_LEAD
    assert "Asked what to do? That action again, shorter." in PROCEDURE_LEAD
    assert "Stuck? Help." in PROCEDURE_LEAD
    assert "invite them to say when done" not in PROCEDURE_LEAD


def _guided(sounds_like: str, *, steps: bool) -> CallScript:
    procedure = (
        [
            ProcedureStep(action="Ask them to open the app.", wait_for="they say it is open"),
            ProcedureStep(action="Ask them to tap Register."),
        ]
        if steps
        else []
    )
    return CallScript(
        schema_version=2,
        stages=[
            ConversationStage(
                id="s1",
                name="Setup",
                instruction="Help them set up the app.",
                sounds_like=sounds_like,
                procedure=procedure,
            )
        ],
    )


def test_a_section_with_steps_offers_its_line_for_tone_only() -> None:
    """The line summarises every action; quoted as "It sounds like" it was said whole."""
    line = "Open the app, tap Register and tell me when done."
    with_steps = compile_call_script(_guided(line, steps=True))
    assert f'{SOUNDS_LIKE_TONE_LEAD} "{line}"' in with_steps
    assert SOUNDS_LIKE_LEAD not in with_steps
    without = compile_call_script(_guided(line, steps=False))
    assert f'{SOUNDS_LIKE_LEAD} "{line}"' in without
    # Never longer, so no stored section passes its 600-character cap.
    assert len(SOUNDS_LIKE_TONE_LEAD) <= len(SOUNDS_LIKE_LEAD)


def test_a_steps_check_is_a_criterion_not_a_line_to_say() -> None:
    compiled = compile_call_script(_guided("", steps=True))
    assert f"1. Ask them to open the app. {DONE_WHEN_LEAD} they say it is open" in compiled
    assert "Wait for:" not in compiled
    assert "2. Ask them to tap Register.\n" in f"{compiled}\n"


def test_the_example_call_is_never_framed_as_lines_to_copy() -> None:
    from calevate_shared.call_script import EXAMPLE_LEAD, ExampleLine

    script = _guided("", steps=False).model_copy(
        update={
            "example_exchange": [
                ExampleLine(speaker="caller", text="Hello?"),
                ExampleLine(speaker="agent", text="Open the app."),
            ]
        }
    )
    compiled = compile_call_script(script)
    assert EXAMPLE_LEAD in compiled
    assert "Copy the style" not in compiled
    assert "how turns open or end" in EXAMPLE_LEAD


# --- HOW TO SPEAK and the opening ------------------------------------------------------------


def test_how_to_speak_says_one_action_then_stop_and_the_same_step_on_what() -> None:
    assert '- Steps? One action a turn, then stop; never "say when done"' in (VOICE_STYLE_GUIDANCE)
    assert 'A bare "OK" is not done.' in VOICE_STYLE_GUIDANCE
    assert 'Asked to repeat, or "what?" to a step? Say it shorter.' in (VOICE_STYLE_GUIDANCE)
    assert "inviting them in new words to say when done" not in VOICE_STYLE_GUIDANCE


def test_how_to_speak_says_turns_begin_and_end_differently() -> None:
    assert "A reaction only if it fits, often none, never to open or twice a call;" in (
        VOICE_STYLE_GUIDANCE
    )
    assert "no two replies start or end alike." in VOICE_STYLE_GUIDANCE


def test_a_yes_to_the_opening_is_never_asked_or_offered_again() -> None:
    assert "go on with why you call or your first step." in (OPENING_CONTINUES_RULE)
    assert "ask if now suits or offer help? Done: do the rest." in OPENING_CONTINUES_RULE


# --- no reaction words in the prompt ---------------------------------------------------------


@pytest.mark.parametrize("tag", ["te-IN", "hi-IN", "en-IN"])
def test_the_register_line_names_no_filler(tag: str) -> None:
    """D-894: a word named in the prompt comes back more often."""
    style = style_for(tag)
    guidance = register_guidance(tag)
    assert style is not None and guidance is not None
    assert FILLERS_LEAD not in guidance
    # English prose may use an English filler as a word; the native lists are the check.
    for filler in style.fillers if tag != "en-IN" else ():
        assert f" {filler.text}," not in guidance and f" {filler.text}." not in guidance


def test_a_telugu_prompt_carries_no_filler_list() -> None:
    prompt = compose_engine_prompt(_cfg(language_primary="te-IN", system_prompt="Help them."))
    assert "--- SPOKEN REGISTER ---" in prompt
    assert FILLERS_LEAD not in prompt


# --- what the engine is given to say ---------------------------------------------------------


def _voice(**update: Any) -> dict[str, Any]:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(**update))
    voice: dict[str, Any] = body["voice"]
    return voice


def _fields(own: tuple[str, ...] | None, languages: tuple[str, ...]) -> tuple[str, ...]:
    row = {"call_settings": CallSettings(filler_lines=own)}
    lines: tuple[str, ...] = _call_settings_fields(row, languages=languages)["filler_lines"]  # type: ignore[arg-type]
    return lines


@pytest.mark.parametrize("tag", ["te-IN", "hi-IN"])
def test_a_telugu_or_hindi_agent_always_has_a_line_in_its_own_script(tag: str) -> None:
    ours = thinking_lines((tag,))
    assert ours, tag
    assert _fields(None, (tag,)) == ours
    # A client's English line alone would leave every call in the language to the engine's
    # own filler: ours joins it.
    assert _fields(("One moment",), (tag,)) == ("One moment", *ours)
    # A client line already in the language's script is enough.
    assert _fields((ours[0], "One moment"), (tag,)) == (ours[0], "One moment")


def test_english_keeps_the_engines_own_english_line() -> None:
    assert thinking_lines(("en-IN",)) == ()
    assert _fields(None, ("en-IN",)) == ()
    assert _fields(("One moment",), ("en-IN",)) == ("One moment",)


def test_a_full_list_of_client_lines_makes_room_for_ours() -> None:
    from apps.api.agents.models import FILLER_LINES_MAX

    own = tuple(f"Line {i}" for i in range(FILLER_LINES_MAX))
    lines = filler_lines_for(own, ("te-IN", "hi-IN"))
    assert len(lines) == FILLER_LINES_MAX
    assert set(thinking_lines(("te-IN", "hi-IN"))) <= set(lines)
    assert lines[:2] == own[:2]


@pytest.mark.parametrize(
    ("primary", "extra"), [("te-IN", ()), ("hi-IN", ()), ("te-IN", ("en-IN",))]
)
def test_under_ear_a_non_english_agent_names_its_own_listening_words(
    primary: str, extra: tuple[str, ...]
) -> None:
    """Empty, the engine picks "a short word in the caller's own language", and on the Varsha
    call (Ear, list empty) a Telugu caller written in Latin letters heard English."""
    ours = listening_lines(primary)
    assert ours, primary
    voice = _voice(
        language_primary=primary,
        languages_extra=list(extra),
        acknowledgements=True,
        turn_detection="ear",
    )
    assert voice["acknowledgements"] is True
    assert voice["acknowledgementWords"] == list(ours)
    assert all(LISTENING_USE in f.use.lower() for f in _fillers(primary) if f.text in ours)


def _fillers(tag: str) -> tuple[Any, ...]:
    style = style_for(tag)
    assert style is not None
    return tuple(style.fillers)


def test_an_english_agent_keeps_the_engines_own_word() -> None:
    voice = _voice(language_primary="en-IN", acknowledgements=True, turn_detection="ear")
    assert (voice["acknowledgements"], voice["acknowledgementWords"]) == (True, [])


def test_a_language_with_no_listening_word_waits_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine import thinnest

    monkeypatch.setattr(thinnest, "listening_lines", lambda tag: ())
    cfg = _cfg(language_primary="te-IN", acknowledgements=True, turn_detection="ear")
    assert acknowledgements_on(cfg) is False
    assert acknowledgements_on(cfg.model_copy(update={"language_primary": "en-IN"})) is True


def test_the_console_switch_off_is_off_for_every_agent() -> None:
    voice = _voice(language_primary="te-IN", acknowledgements=False, turn_detection="ear")
    assert voice["acknowledgements"] is False
    assert acknowledgements_on(_cfg(language_primary="en-IN", acknowledgements=False)) is False


@pytest.mark.parametrize("tag", ["te-IN", "hi-IN", "en-IN"])
def test_the_thinking_payload_per_language(tag: str) -> None:
    ours = list(thinking_lines((tag,)))
    voice = _voice(language_primary=tag, filler_lines=tuple(ours))
    assert voice["thinking"] is True
    assert voice["thinkingLines"] == ours
    assert voice["thinkingAtTurnEnd"] is False
