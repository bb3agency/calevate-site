"""The platform's voice-behaviour layer reaches every agent's prompt.

`docs/PROMPT-GUIDE.md` §2 specifies a `[STYLE]` block on every agent — short spoken turns,
no markdown, digit-by-digit phone numbers, confirm captured values back, mirror the
caller's language — and for a long time NO CODE EMITTED IT: the seed and recompile paths
spliced only `[IDENTITY]` and `[T0 FACTS]`, and a raw-override script bypassed the
structured compiler entirely, so the model reached the phone with the compliance floor, the
client's words, and nothing about how to sound like a person on a call. These tests pin that
the guidance is now injected by `compose_engine_prompt` — the one place every agent passes
through — and, critically, that adding it did not disturb the truthful-answer floor, whose
POSITION (last, overriding) is load-bearing and covered by `prompt_fence_test.py`.

What they do NOT claim: that a model obeys the guidance. A test can only assert the prompt we
hand the engine says the right things in the right places; adherence is the model's, and the
engine-side dynamics (turn-taking, endpointing) are a separate, measured concern.
"""

from __future__ import annotations

from calevate_shared.engine import (
    CLIENT_SCRIPT_OPEN,
    PLATFORM_RULES_PREAMBLE,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    ModelConfig,
    carries_truthful_answer_floor,
    compose_engine_prompt,
)


def _config(script: str, *, opening: str = "Idi AI assistant.") -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic",
        direction="inbound",
        system_prompt=script,
        opening_line=opening,
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            tts_voice="bulbul:v3",
        ),
    )


def test_every_agent_prompt_carries_the_voice_style_layer() -> None:
    """A normal script, a raw-override-shaped script, and an empty script all get it —
    because the block is injected in `compose_engine_prompt`, not in the structured
    compiler that a raw override skips."""
    for script in (
        "You are the receptionist for Sunrise Clinic. Book appointments.",
        "RAW: just answer questions about our shop.",
        "",
    ):
        prompt = compose_engine_prompt(_config(script))
        assert VOICE_STYLE_GUIDANCE in prompt


def test_the_style_layer_frames_the_script_and_never_overrides_the_floor() -> None:
    """Position is the design. The style block sits AFTER the platform preamble and BEFORE
    the client script — so it frames how the model reads the script — and strictly before
    the truthful-answer floor, which alone holds the overriding last position. A style rule
    that drifted past the floor would be guidance sitting where the one inviolable rule must
    be, which `prompt_fence_test.py` forbids and this pins from the other side."""
    prompt = compose_engine_prompt(_config("Book appointments for the clinic."))
    preamble_at = prompt.index(PLATFORM_RULES_PREAMBLE)
    style_at = prompt.index(VOICE_STYLE_GUIDANCE)
    script_fence_at = prompt.index(CLIENT_SCRIPT_OPEN)
    floor_at = prompt.index(TRUTHFUL_ANSWER_MARKER)
    assert preamble_at < style_at < script_fence_at < floor_at
    # The floor is untouched by this addition — the regression that would matter most.
    assert carries_truthful_answer_floor(prompt)


def test_the_style_layer_states_the_directives_the_guide_specifies() -> None:
    """The concrete instructions from `docs/PROMPT-GUIDE.md` sections 2-5 that make an agent sound
    like a person on a phone. Pinned as substrings so a well-meaning reword that quietly
    drops one — 'no markdown', the digit-by-digit rule, the confirm-back habit that
    extraction accuracy depends on — fails the build rather than the next live call."""
    block = VOICE_STYLE_GUIDANCE.lower()
    assert "markdown" in block
    assert "one digit at a time" in block
    assert "read back" in block
    assert "telugu" in block
    assert "repeat it" in block
