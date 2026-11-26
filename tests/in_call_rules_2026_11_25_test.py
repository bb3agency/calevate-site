"""What we send for a call, from the audit of 25 Nov 2026 and the founder's test call of that
night (01:37): rules that contradicted each other across layers, a quote that cut the engine's
prompt cache short, and writer rules that asked Pip for lines the call rules forbid.
"""

from __future__ import annotations

import re

from apps.api.agents.call_rules import SCRIPT_FLOW_RULE
from apps.workers import campaign_script_ask as ask
from apps.workers.script_assist import _SYSTEM_INSTRUCTION
from calevate_shared.call_script import (
    PROCEDURE_LEAD,
    CallScript,
    ConversationStage,
    SpeakingStyle,
    compile_call_script,
)
from calevate_shared.engine import (
    CALLER_NAME_MARK,
    CALLER_NAME_ONLY_MARK,
    CLIENT_SCRIPT_OPEN,
    START_OF_CALL_HEADER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    compose_first_utterance,
    quoted_client_words,
    screen_steps_bullet,
)
from calevate_shared.spoken_style import style_for

_VALUE = re.compile(r"\{\{\s*\w+\s*\}\}")


def _placed(opening: str) -> AgentConfig:
    script = CallScript(
        schema_version=2,
        opening_line=opening,
        stages=[ConversationStage(id="s1", name="Help", instruction="Help them.")],
    )
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Varsha",
        business="Rytu Khata",
        direction="outbound",
        language_primary="te-IN",
        system_prompt=compile_call_script(script),
        opening_line="",
        call_is_recorded=True,
        engine_own_voice_key=False,
    )


# --- the first words quoted under START OF THE CALL ---------------------------------------


def test_a_name_in_the_opening_is_quoted_as_a_mark_not_as_a_per_call_value() -> None:
    """The engine caches the prompt up to the first value it fills per call (D-814, D-835).
    A placed call's opening greets by `{{lead_name}}`, and START OF THE CALL quoted it as
    written, so the cached part ended there, ahead of the client script and every rule."""
    cfg = _placed("Hello {{lead_name}}, this is Varsha from Rytu Khata. Can you talk now?")
    prompt = compose_engine_prompt(cfg)
    start = prompt.index(START_OF_CALL_HEADER)
    first_value = _VALUE.search(prompt)
    assert first_value is not None
    assert first_value.start() > prompt.index(CLIENT_SCRIPT_OPEN) > start
    assert f'"Hello {CALLER_NAME_ONLY_MARK}, this is Varsha' in prompt[start:]


def test_a_name_with_its_title_is_quoted_as_the_title_mark() -> None:
    quoted = quoted_client_words("Namaskaram {{lead_name}} garu, this is Varsha.")
    assert quoted == f"Namaskaram {CALLER_NAME_MARK}, this is Varsha."
    assert quoted_client_words("Hi {{village_name}} folks") == "Hi [village name] folks"


def test_the_read_back_still_finds_the_quote_it_composed() -> None:
    """`agents/verification` reads the quote back with the same function."""
    cfg = _placed("Hello {{lead_name}}, this is Varsha. Can you talk now?")
    assert quoted_client_words(compose_first_utterance(cfg)) in compose_engine_prompt(cfg)


# --- steps: done only when their words show it, invited in new words ----------------------


def test_a_short_word_after_an_action_is_not_taken_as_done() -> None:
    """01:37 call: after "press install, tell me when done" the caller's garbled "And." was
    taken as done. HOW TO SPEAK said '"OK" after one: the next', against the step-by-step
    lead's "only once what they say meets its Wait for, or says done"."""
    assert '"OK" after one' not in VOICE_STYLE_GUIDANCE
    assert "never guess, pick for them or count it done" in VOICE_STYLE_GUIDANCE
    assert 'Only their "done" moves you on;' in PROCEDURE_LEAD


def test_a_reply_that_does_not_show_it_is_answered_by_asking_what_they_see() -> None:
    """01:37 call: a garbled reply got the step line back word for word, and a side question
    was followed by "have you installed it?"."""
    assert "To check, ask what they see." in VOICE_STYLE_GUIDANCE


def test_no_step_ends_on_an_invitation_to_say_when_done() -> None:
    """Every step ended on the same "tell me when it's done" (25 Nov, and again on the Varsha
    call of 26 Nov 2026); a step's turn now ends on the action, in neither bullet."""
    assert 'never "say when done"' in VOICE_STYLE_GUIDANCE
    assert "invite" not in screen_steps_bullet("te-IN")


# --- the client script's own lines and the examples ---------------------------------------


def test_sample_phrases_carry_the_same_cap_as_the_fillers() -> None:
    script = CallScript(
        schema_version=2,
        stages=[ConversationStage(id="s1", name="Help", instruction="Help them.")],
        style=SpeakingStyle(sample_phrases=["One second."]),
    )
    body = compile_call_script(script)
    assert 'Phrases you can use, once a call each: "One second."' in body
    assert "not every turn" not in body


def test_the_english_example_opens_with_its_point_not_a_reaction_and_comma() -> None:
    style = style_for("en-IN")
    assert style is not None
    for exchange in style.prompt_examples:
        for turn in exchange:
            if turn.speaker == "agent":
                first = re.split(r"(?<=[.?!])\s", turn.text)[0]
                assert "," not in first, turn.text


# --- writer rules that mirror an in-call rule ---------------------------------------------


def test_a_written_check_asks_what_they_see() -> None:
    """In call: "To check, ask what they see". On 23 Nov a check closed with "everything is
    right, isn't it?"."""
    guiding = next(kind for kind in ask.CALL_KINDS if kind.name == "guiding")
    assert "asking what they see" in guiding.steps
    assert "check it is done by asking what they see" in SCRIPT_FLOW_RULE


def test_no_writer_rule_asks_for_a_reaction_formal_words_or_a_greeting_step() -> None:
    assert "thanks them for each answer" not in ask.CONCISE_RULE
    assert all("formal" not in tone for tone in ask.TONES.values())
    assert "the greeting" not in ask.FLOW_ASK
    assert "fillers lightly" not in _SYSTEM_INSTRUCTION
    assert "at most once a call each and never to open a line" in _SYSTEM_INSTRUCTION
