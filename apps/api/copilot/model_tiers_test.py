"""D-694: the assistant's model tier is decided by a stated, deterministic rule, and a tier
whose model cannot be sold or sent to is handed to the selector as a leg that cannot serve."""

from __future__ import annotations

from typing import get_args

import pytest
from calevate_shared.engine import GoogleDirectModel

from apps.api.copilot import model_tiers
from apps.api.core.settings import get_settings


@pytest.mark.parametrize(
    "question",
    [
        "how many leads came in today?",
        "what does this field mean",
        "mark this lead hot",
        "ఈ రోజు ఎన్ని కాల్స్ వచ్చాయి?",
    ],
)
def test_ordinary_questions_take_the_fast_tier(question: str) -> None:
    assert model_tiers.route_tier(question) == "fast"


@pytest.mark.parametrize(
    "question",
    [
        "find yesterday's missed calls and then mark those leads as contacted",
        "every morning call back the leads we missed",
        "Set up a weekly summary routine",
        "1. make an agent\n2. give it a script",
        "x" * model_tiers.LONG_QUESTION_CHARS,
    ],
)
def test_multi_step_routine_and_long_requests_take_the_planning_tier(question: str) -> None:
    assert model_tiers.route_tier(question) == "planning"


def test_a_background_job_always_plans() -> None:
    assert model_tiers.route_tier("hi", background=True) == "planning"


def test_markers_match_whole_words_only() -> None:
    """`daily` must not fire inside another word, or a fast question pays planning rates."""
    assert model_tiers.route_tier("what is the dailyness of this") == "fast"


def test_the_settings_are_typed_to_the_google_leg() -> None:
    """ "Gemini only at first", held by the type the console validates against."""
    fields = type(get_settings()).model_fields
    for name in ("copilot_fast_model", "copilot_planning_model"):
        assert get_args(fields[name].annotation) == get_args(GoogleDirectModel)
    assert get_settings().copilot_fast_model in get_args(GoogleDirectModel)
    assert get_settings().copilot_azure_fallback is True


def test_an_unofferable_tier_model_is_a_leg_that_does_not_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Price and credential first: an unpriced model that answered would raise on the meter
    after the provider was paid (hard rule 7), so the selector must never be handed one as
    serving."""
    monkeypatch.setattr(model_tiers, "offerable_models", lambda: frozenset())
    leg = model_tiers.tier_leg("fast")
    assert leg.serves_dashboard is False
    assert leg.provider == "google"
    assert leg.account_chose_model is False
    assert leg.blocked_reason
