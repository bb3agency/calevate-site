"""Actions are checked against the calling system's documented rules before they are sent.

The vendor's 400 for a broken rule reaches a client only as "the voice platform could not
complete this operation", so the rules are applied here first, in words.
"""

from __future__ import annotations

import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.thinnest_actions import (
    ActionDefinition,
    ActionParam,
    action_problems,
    assert_action_acceptable,
)
from apps.api.reliability import engine_actions


@pytest.fixture
def public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_ACTIONS_BASE_URL", "https://api.calevate.tech")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _action(**overrides: object) -> ActionDefinition:
    fields: dict[str, object] = {
        "name": "book_visit",
        "description": "Call this when the caller wants to book a visit.",
        "url": "https://api.calevate.tech/v1/actions/thinnest/client?agent=ag_1",
        "parameters": (ActionParam("visit_time", "The time they asked for.", True),),
    }
    fields.update(overrides)
    return ActionDefinition(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("agent_ref", ["ag_f469b456", "ag_f469b456@org_3fKq9TzQ1mN8vB2xR7cLpA"])
def test_the_platform_actions_meet_every_rule(public_base: None, agent_ref: str) -> None:
    for definition in engine_actions.definitions("thinnest", agent_ref):
        assert action_problems(definition) == [], definition.name


def test_a_sound_action_passes() -> None:
    assert action_problems(_action()) == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"name": "Book Visit"}, "its name"),
        ({"name": "bk"}, "its name"),
        ({"description": "book"}, "its description"),
        ({"url": "http://api.calevate.tech/x"}, "https://"),
        ({"parameters": (ActionParam("at", "The time.", True),)}, "the value 'at'"),
        ({"parameters": (ActionParam("visit_time", "  ", True),)}, "needs a description"),
        (
            {"parameters": tuple(ActionParam(f"value_{i}", "A value.", False) for i in range(21))},
            "at most 20",
        ),
        ({"url": "https://x.example/{{phone}}"}, "'{{phone}}' has no value"),
        ({"url": "https://x.example/{{call.secret}}"}, "not something the call can fill"),
        ({"speak_before": "a" * 201}, "at most 200"),
    ],
)
def test_each_broken_rule_is_named(overrides: dict[str, object], fragment: str) -> None:
    problems = action_problems(_action(**overrides))
    assert any(fragment in p for p in problems), problems


def test_a_broken_action_is_refused_in_words_before_any_request() -> None:
    with pytest.raises(ProblemError) as refused:
        assert_action_acceptable(_action(name="Book Visit"))
    assert refused.value.code == "engine_action_invalid"
    assert "'Book Visit'" in refused.value.detail
