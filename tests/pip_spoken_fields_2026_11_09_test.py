"""Pip filling the Script tab's spoken lines (founder, Rytu Khata, Varsha, 9 Nov 2026).

A whole-script rewrite was refused once for a textbook word in the opening line, repaired,
and written; the panel then showed the refusal as a failure. Pip's field-filling path must
be given the same spoken-line guidance the script writer gets, its refusal must reach the
model with the word to say instead and stay bounded, and each fill step must name its
fields so the panel can tell a refusal a later fill made good from a field left unwritten.
Words are read from the language's own list, never spelled here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import service
from apps.api.copilot.schemas import CopilotAskIn, CopilotFillItem
from apps.api.core.settings import get_settings
from apps.workers import chat
from calevate_shared.spoken_guard import SPOKEN_LINE_RULES, generation_guidance
from calevate_shared.spoken_style import style_for

LANGUAGE = "te-IN"


def _swap() -> tuple[str, str]:
    style = style_for(LANGUAGE)
    assert style is not None and style.word_swaps
    return style.word_swaps[0]


def _script_tab(*, question: str = "Re-adjust Varsha's whole script") -> CopilotAskIn:
    return CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/agents/{id}", "title": "Agent: script", "realm": "client"},
            "question": question,
            "fields": [
                {
                    "id": "script-opening_line",
                    "label": "Opening line",
                    "type": "textarea",
                    "writable": True,
                    "spoken_language": LANGUAGE,
                },
                {
                    "id": "script-stages-0-sounds_like",
                    "label": "Step 1: example line",
                    "type": "textarea",
                    "writable": True,
                    "spoken_language": LANGUAGE,
                },
                {
                    "id": "script-goal",
                    "label": "What a good call achieves",
                    "type": "textarea",
                    "writable": True,
                    "instruction": True,
                },
            ],
        }
    )


def _fill(items: dict[str, str], because: str = "Re-adjust Varsha's whole script") -> str:
    return json.dumps(
        {
            "because": because,
            "items": [{"field_id": key, "value": value} for key, value in items.items()],
        }
    )


# --- (1) the same guidance the script writer gets ----------------------------------------


def test_a_spoken_field_brings_the_writers_own_guidance() -> None:
    """FAILS IF: Pip's spoken fields stop getting `generation_guidance`, the one guide the
    script writer reads (word swaps, punctuation for the voice, written form)."""
    rendered = prompt_module.render_screen(_script_tab())
    guide = generation_guidance(LANGUAGE)
    assert guide and prompt_module.xml_text(guide) in rendered
    assert prompt_module.xml_text(SPOKEN_LINE_RULES) in rendered
    assert rendered.count(f'<spoken_style language="{LANGUAGE}">') == 1


def test_every_word_the_fill_refuses_is_named_up_front(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: a guide that leaves listed words out (a language pack names only its own
    avoid list) lets Pip meet a refused word for the first time in a refusal."""
    monkeypatch.setattr(prompt_module, "generation_guidance", lambda _tag: "Speak simply.")
    rendered = prompt_module.render_screen(_script_tab())
    style = style_for(LANGUAGE)
    assert style is not None
    assert "Speak simply." in rendered
    for formal, _spoken in style.word_swaps:
        assert formal in rendered


def test_a_screen_with_only_instructions_gets_no_spoken_guide() -> None:
    raw = _script_tab().model_dump()
    raw["fields"] = [raw["fields"][2]]
    assert "<spoken_style" not in prompt_module.render_screen(CopilotAskIn.model_validate(raw))


def test_the_guide_rides_the_screen_not_the_cached_prefix() -> None:
    """FAILS IF: the guide moves into the system prompt, whose bytes must not vary by
    screen (`copilot/prompt_budget_test.py`)."""
    messages = service.build_messages(_script_tab(), "", "client")
    assert "<spoken_style" not in str(messages[0]["content"])
    assert SPOKEN_LINE_RULES not in str(messages[0]["content"])
    assert prompt_module.xml_text(SPOKEN_LINE_RULES) in str(messages[-1]["content"])


# --- (2) the refusal reaches the model, mendable and bounded ----------------------------


def test_a_textbook_word_is_refused_with_the_word_to_say_and_its_fields_named() -> None:
    formal, spoken = _swap()
    with pytest.raises(service.FillRefusedError) as refused:
        service.validate_fill(
            _script_tab(),
            _fill({"script-opening_line": f"{formal}?", "script-stages-0-sounds_like": "?"}),
        )
    (reason,) = refused.value.reasons
    assert reason.startswith("`script-opening_line` is a line callers hear")
    assert spoken.strip("()") in reason
    assert refused.value.field_ids == ("script-opening_line", "script-stages-0-sounds_like")
    (plain,) = refused.value.plain
    assert plain.startswith("Opening line used words callers do not say")


def test_a_refused_fill_names_only_the_screens_own_fields() -> None:
    formal, _spoken = _swap()
    with pytest.raises(service.FillRefusedError) as refused:
        service.validate_fill(_script_tab(), _fill({"script-opening_line": formal, "made-up": "x"}))
    assert refused.value.field_ids == ("script-opening_line",)


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)


def _turn(call_id: str, arguments: str) -> list[chat.StreamEvent]:
    call = chat.ToolCall(id=call_id, name="set_fields", arguments=arguments)
    return [
        chat.StreamEvent(
            outcome=chat.ChatOutcome(content="", tool_calls=(call,), finish_reason="tool_calls")
        )
    ]


def _scripted(
    monkeypatch: pytest.MonkeyPatch, turns: Sequence[list[chat.StreamEvent]]
) -> list[list[dict[str, Any]]]:
    sent: list[list[dict[str, Any]]] = []
    remaining = list(turns)

    def _stream(leg: chat.ChatLeg, messages: Sequence[Any], **_: Any) -> AsyncIterator[Any]:
        sent.append([dict(message) for message in messages])
        events = remaining.pop(0) if remaining else []

        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            for event in events:
                yield event

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    return sent


async def test_the_repair_is_told_the_word_to_say_and_both_steps_name_their_fields(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    formal, spoken = _swap()
    both = ("script-opening_line", "script-stages-0-sounds_like")
    sent = _scripted(
        monkeypatch,
        [
            _turn("call-a", _fill(dict(zip(both, (f"{formal}?", "?"), strict=True)))),
            _turn("call-b", _fill(dict(zip(both, ("?", "?"), strict=True)), because="fixed")),
        ],
    )
    events = [event async for event in service.run_copilot(_script_tab())]
    assert len(sent) == 2
    told = str(sent[1][-1]["content"])
    assert "NOTHING was written" in told and spoken.strip("()") in told
    steps = [event.step for event in events if event.step is not None]
    assert [(s.id, s.status, s.field_ids) for s in steps] == [
        ("call-a", "refused", list(both)),
        ("call-b", "done", list(both)),
    ]
    assert [e.fill for e in events if e.fill] == [
        tuple(CopilotFillItem(field_id=field_id, value="?") for field_id in both)
    ]


async def test_a_model_that_keeps_the_textbook_word_stops_at_the_turn_cap(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a refusal the model never mends loops past `MAX_TURNS`."""
    formal, _spoken = _swap()
    refused = _fill({"script-opening_line": f"{formal}?"})
    sent = _scripted(
        monkeypatch, [_turn(f"call-{n}", refused) for n in range(service.MAX_TURNS + 2)]
    )
    events = [event async for event in service.run_copilot(_script_tab())]
    assert len(sent) == service.MAX_TURNS
    assert not [e.fill for e in events if e.fill]
    said = "".join(e.text for e in events if e.text)
    assert "Opening line used words callers do not say" in said
