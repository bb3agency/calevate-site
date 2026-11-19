"""Rehearsing a guided call (D-904): a paying owner's test call from their own number runs as
long as the agent's own cap (at most 15 minutes), and a saved test may hold 20 caller lines."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import pytest
from apps.api.agents.paid_test_calls import own_number_call_seconds
from apps.api.core.settings import get_settings
from apps.api.teach.models import MAX_CASE_LINES
from apps.workers import agent_test_cases


def test_an_own_number_test_call_follows_the_agents_cap_up_to_fifteen_minutes() -> None:
    shared = get_settings().trial_call_max_seconds
    assert get_settings().own_number_test_max_seconds == 900
    assert own_number_call_seconds(600) == 600
    assert own_number_call_seconds(1200) == 900
    assert own_number_call_seconds(60) == shared, "never shorter than the shared line's"
    assert own_number_call_seconds(None) >= shared


def test_the_own_number_ceiling_is_the_console_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "own_number_test_max_seconds", 600)
    assert own_number_call_seconds(1200) == 600
    # Never below the shared line's, even when the ceiling is set under it.
    monkeypatch.setattr(settings, "own_number_test_max_seconds", 60)
    assert own_number_call_seconds(1200) == settings.trial_call_max_seconds


def test_a_saved_test_holds_twenty_lines() -> None:
    assert MAX_CASE_LINES == 20


async def test_a_long_test_stops_at_its_budget_and_keeps_what_it_reached(monkeypatch: Any) -> None:
    sent: list[str] = []

    class _Turn:
        reply = "ok"
        session = "s"
        tools: tuple[str, ...] = ()
        failed_part_way = False

    async def _send(engine: Any, **kwargs: Any) -> _Turn:
        sent.append(kwargs["message"])
        return _Turn()

    async def _pause() -> None:
        return None

    monkeypatch.setattr(agent_test_cases, "send_test_message", _send)
    turns = await agent_test_cases.run_case_lines(
        object(),  # type: ignore[arg-type]
        "ref",
        ["one", "two"],
        agent_id=uuid4(),
        knowledge_tool=None,
        pause=_pause,
        stop_at=time.monotonic() - 1,
    )
    assert turns == [] and sent == []
    turns = await agent_test_cases.run_case_lines(
        object(),  # type: ignore[arg-type]
        "ref",
        ["one", "two"],
        agent_id=uuid4(),
        knowledge_tool=None,
        pause=_pause,
    )
    assert [t["said"] for t in turns] == ["one", "two"]
