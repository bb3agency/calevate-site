"""The Sarvam standby: what it declines, how it asks, and what it says when it runs out.

30 Oct 2026: Pip answered a full script rewrite on the standby, the standby spent its whole
token ceiling and the person read "please ask for something narrower".
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from apps.api.copilot import service
from apps.api.copilot.model_tiers import LONG_QUESTION_CHARS
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.core.settings import get_settings
from apps.workers import chat

pytestmark = pytest.mark.anyio


@pytest.fixture
def standby_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Azure, no Gemini: the standby answers first."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", None, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


def _ask(question: str) -> CopilotAskIn:
    return CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/agents/1", "title": "Agent", "realm": "client"},
            "question": question,
        }
    )


def _record(monkeypatch: pytest.MonkeyPatch, outcome: chat.ChatOutcome) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def _complete(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> chat.ChatOutcome:
        sent.append(kwargs)
        return outcome

    monkeypatch.setattr(chat, "complete", _complete)
    return sent


async def _texts(payload: CopilotAskIn) -> list[str]:
    return [e.text async for e in service.run_copilot(payload) if e.text]


@pytest.mark.parametrize(
    "question",
    [
        "Rewrite my script so it sounds friendlier",
        "please change the opening line of the script",
        "Hi Pip, can you update the agent's greeting?",
        "Context first. " * (LONG_QUESTION_CHARS // 15) + "Then replace the second step.",
    ],
)
async def test_a_change_request_is_declined_without_calling_the_standby(
    standby_only: None, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    sent = _record(monkeypatch, chat.ChatOutcome(content="never used"))
    texts = await _texts(_ask(question))
    assert sent == []
    assert texts == [service.standby_change_refusal(question)]
    assert "Nothing was changed." in texts[0]


def test_the_refusal_names_scripts_only_when_the_request_does() -> None:
    assert service.standby_change_refusal("rewrite my script").startswith(
        "I can't change scripts right now"
    )
    assert service.standby_change_refusal("add a lead").startswith(
        "I can't change anything right now"
    )


@pytest.mark.parametrize(
    "question",
    ["How do I change my script?", "set the opening time", "What is a campaign?"],
)
def test_questions_are_not_change_requests(question: str) -> None:
    assert service.asks_for_a_change(question) is False


async def test_the_standby_asks_with_reasoning_off(
    standby_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sarvam reasons by default and bills the trace as completion tokens inside
    `max_tokens`; the answer is read from `content` only."""
    sent = _record(monkeypatch, chat.ChatOutcome(content="Nine.", finish_reason="stop"))
    assert await _texts(_ask("When do we open?")) == ["Nine."]
    assert sent[-1]["reasoning_effort"] == "off"
    assert sent[-1]["max_tokens"] == service.MAX_ANSWER_TOKENS


async def test_a_standby_that_runs_out_says_so_without_blaming_the_question(
    standby_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(monkeypatch, chat.ChatOutcome(content="", finish_reason="length"))
    texts = await _texts(_ask("Explain how campaigns work"))
    assert texts == [service.STANDBY_TRUNCATED_MESSAGE]
    assert "narrower" not in texts[0]
