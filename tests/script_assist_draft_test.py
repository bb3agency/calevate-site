"""The script draft's spend valve: `_DRAFT_MAX_TOKENS` on the wire, and what a hit means.

The provider is replaced at `chat.complete` — the same seam `copilot/loop_test.py` uses,
one layer below the leg — so the request kwargs asserted here are the ones the real legs
send. No credential, no network: the keys are monkeypatched settings values.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.workers import chat, script_assist
from apps.workers.script_assist import _DRAFT_MAX_TOKENS, _draft_via_azure, _draft_via_sarvam

_DRAFT_JSON = json.dumps({"opening_line": "Namaste.", "steps": ["Ask the need."], "faqs": []})


@pytest.fixture
def both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


def _scripted_complete(
    monkeypatch: pytest.MonkeyPatch, outcome: chat.ChatOutcome
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _complete(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> chat.ChatOutcome:
        calls.append({"leg": leg, "kwargs": kwargs})
        return outcome

    monkeypatch.setattr(chat, "complete", _complete)
    return calls


async def test_both_draft_legs_request_the_output_ceiling(
    both_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`max_tokens` travels on the Azure AND Sarvam draft requests — the spend valve.

    FAILS IF: the cap stops reaching `chat.complete` on either leg. Without it a runaway
    generation is bounded by nothing but the leg timeout, i.e. paid output tokens for as
    long as the model keeps talking. (`max_tokens` is a verified body key on both dialects
    — `workers/chat.py::_request_body`.)
    """
    calls = _scripted_complete(
        monkeypatch, chat.ChatOutcome(content=_DRAFT_JSON, finish_reason="stop")
    )
    assert await _draft_via_azure("a clinic in Guntur") is not None
    assert await _draft_via_sarvam("a clinic in Guntur") is not None
    assert len(calls) == 2
    assert all(call["kwargs"]["max_tokens"] == _DRAFT_MAX_TOKENS for call in calls)


async def test_a_truncated_draft_is_no_draft_on_either_leg(
    both_keys: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`finish_reason == "length"` means the JSON was cut off mid-generation.

    Parsing it would either fail into an inexplicable empty editor or — worse — yield a
    balanced PREFIX that reads as a short draft (`ExtractionTruncatedError`'s argument,
    on this surface). "No draft" is the honest answer, said in a log line an operator can
    grep. FAILS IF: a truncated answer starts being parsed as if it were complete.
    """
    _scripted_complete(monkeypatch, chat.ChatOutcome(content=_DRAFT_JSON, finish_reason="length"))
    with caplog.at_level("WARNING"):
        assert await _draft_via_azure("a clinic in Guntur") is None
        assert await _draft_via_sarvam("a clinic in Guntur") is None
    truncations = [r for r in caplog.records if r.message == "script_assist_draft_truncated"]
    assert len(truncations) == 2


async def test_draft_script_falls_back_when_the_azure_draft_is_truncated(
    both_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated Azure draft is 'Azure could not answer': the disclosed Sarvam leg gets
    its chance, exactly as it does for any other non-answer, rather than the person seeing
    an empty editor while a second model stood ready."""
    outcomes = [
        chat.ChatOutcome(content=_DRAFT_JSON, finish_reason="length"),  # Azure: truncated
        chat.ChatOutcome(content=_DRAFT_JSON, finish_reason="stop"),  # Sarvam: fine
    ]

    async def _complete(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> chat.ChatOutcome:
        return outcomes.pop(0)

    monkeypatch.setattr(chat, "complete", _complete)
    draft = await script_assist.draft_script("a clinic in Guntur")
    assert draft.script.opening_line == "Namaste."
    # The answer is a substitution and says so (D-127 G-6).
    assert draft.capability.provider == "sarvam"
    assert draft.capability.disclosure is not None
