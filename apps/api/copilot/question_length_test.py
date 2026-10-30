"""A long message to Pip is accepted whole and stored whole (30 Oct 2026: a pasted brief
showed cut mid-word in the person's own bubble once the stored copy replaced it)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.copilot.memory import stored_content
from apps.api.copilot.models import MAX_CONTENT_CHARS, MAX_TURN_CHARS
from apps.api.copilot.schemas import MAX_QUESTION_CHARS, CopilotAskIn

_SCREEN = {"route": "/c/x", "title": "Home", "realm": "client"}


def test_the_stored_turn_holds_whatever_the_ask_route_admits() -> None:
    assert MAX_TURN_CHARS == MAX_QUESTION_CHARS
    assert MAX_QUESTION_CHARS > MAX_CONTENT_CHARS


def test_a_long_question_and_its_replay_are_accepted() -> None:
    long = "word " * (MAX_QUESTION_CHARS // 5)
    payload = CopilotAskIn.model_validate(
        {
            "screen": _SCREEN,
            "question": long[:MAX_QUESTION_CHARS],
            "history": [{"role": "user", "content": long[:MAX_QUESTION_CHARS]}],
        }
    )
    assert len(payload.question) == MAX_QUESTION_CHARS


def test_a_question_past_the_limit_is_refused_not_cut() -> None:
    with pytest.raises(ValidationError):
        CopilotAskIn.model_validate({"screen": _SCREEN, "question": "x" * (MAX_QUESTION_CHARS + 1)})


def test_a_long_question_is_stored_whole() -> None:
    question = ("I'll send it on WhatsApp. " * 300)[: MAX_QUESTION_CHARS - 10].strip()
    assert len(question) > MAX_CONTENT_CHARS
    assert stored_content(question, cap=MAX_TURN_CHARS) == question
