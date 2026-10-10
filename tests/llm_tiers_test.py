"""A client chooses a TIER and the server resolves it to a model (D-680, under D-679).

What is pinned here, without a database:

1. Every catalogue model has a tier, and the price classes are the ones the surcharge rule
   implies — Standard is exactly the set the plan surcharge never applies to.
2. A tier is offered exactly when the model it resolves to is offerable; the client sentence
   is the client's, and an unavailable tier is refused in tier words.
3. The surcharge follows the RESOLVED model, through the same predicate billing uses.
4. A stored model reads as the tier pointed at it, else as its price class; re-choosing the
   tier an account already reads as keeps its model.
5. The engine catalogue's opaque ids round-trip, and models show their own names.
"""

from __future__ import annotations

import pytest
from apps.api.agents import llm_tiers
from apps.api.agents.llm_models import CLIENT_UNAVAILABLE_REASON
from apps.api.agents.llm_tiers import (
    LLM_TIER_DESCRIPTIONS,
    LLM_TIER_LABELS,
    LLM_TIERS,
    available_tiers,
    client_model_label,
    client_model_labels,
    cost_tier,
    engine_model_for_token,
    engine_model_labels,
    engine_model_token,
    resolve_tier_choice,
    tier_model,
    tier_of_model,
)
from apps.api.billing.rates import BASE_RATE_LLM_MODEL, is_surchargeable_llm_model
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue
from calevate_shared.config import Settings
from calevate_shared.engine import LLM_MODELS, PLATFORM_DEFAULT_LLM_MODEL


def _offer(monkeypatch: pytest.MonkeyPatch, *models: str) -> None:
    """Make exactly `models` offerable, through the two seams `llm_tiers` reads."""
    offered = frozenset(models)
    monkeypatch.setattr(llm_tiers, "offerable_models", lambda: offered)

    def _reason(model: str, *, audience: str = "operator") -> str | None:
        if model in offered:
            return None
        return CLIENT_UNAVAILABLE_REASON if audience == "client" else "operator ground"

    monkeypatch.setattr(llm_tiers, "unofferable_reason", _reason)


def _point(monkeypatch: pytest.MonkeyPatch, **tiers: str) -> None:
    for tier, model in tiers.items():
        monkeypatch.setattr(get_settings(), f"llm_tier_{tier}_model", model, raising=False)


# --- 1. the vocabulary ---------------------------------------------------------------------


def test_the_tiers_are_three_cheapest_first_with_words_for_each() -> None:
    assert LLM_TIERS == ("standard", "plus", "pro")
    assert set(LLM_TIER_LABELS) == set(LLM_TIER_DESCRIPTIONS) == set(LLM_TIERS)


def test_every_catalogue_model_has_a_price_class() -> None:
    assert {model: cost_tier(model) for model in LLM_MODELS} == {
        "gpt-4o-mini": "standard",
        "gpt-4.1-mini": "plus",
        "gpt-5.4-mini": "pro",
        "gpt-5.6-luna": "plus",
        "gemini-2.5-flash": "plus",
        "gemini-2.5-flash-lite": "standard",
        "gemini-3.1-flash-lite": "plus",
        "gemini-3.5-flash": "pro",
    }


def test_standard_is_exactly_the_set_no_surcharge_applies_to() -> None:
    for model in LLM_MODELS:
        assert (cost_tier(model) == "standard") == (not is_surchargeable_llm_model(model)), model


def test_the_shipped_mapping_is_the_cost_ladder_with_the_platform_default_at_the_bottom() -> None:
    defaults = Settings.model_fields
    assert defaults["llm_tier_standard_model"].default == PLATFORM_DEFAULT_LLM_MODEL
    assert defaults["llm_tier_plus_model"].default == "gpt-4.1-mini"
    assert defaults["llm_tier_pro_model"].default == "gpt-5.4-mini"
    # Each shipped tier lands in its own price class, so a fresh choice reads back as itself.
    for tier in LLM_TIERS:
        model = str(Settings.model_fields[f"llm_tier_{tier}_model"].default)
        assert cost_tier(model) == tier, (tier, model)
    # The base the plan rate is struck at reads as Standard, never as an upgrade.
    assert cost_tier(BASE_RATE_LLM_MODEL) == "standard"


def test_the_platform_default_is_the_default_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    _offer(monkeypatch)
    monkeypatch.setattr(get_settings(), "platform_llm_model", PLATFORM_DEFAULT_LLM_MODEL)
    defaults = [option.tier for option in available_tiers() if option.is_platform_default]
    assert defaults == ["standard"]


# --- 2. offerability --------------------------------------------------------------------------


def test_a_tier_is_offered_exactly_when_its_model_is(monkeypatch: pytest.MonkeyPatch) -> None:
    _point(monkeypatch, standard="gpt-4o-mini", plus="gpt-4.1-mini", pro="gpt-5.4-mini")
    _offer(monkeypatch, "gpt-4o-mini", "gpt-5.4-mini")
    rows = {option.tier: option for option in available_tiers(audience="client")}
    assert rows["standard"].is_available and rows["pro"].is_available
    assert not rows["plus"].is_available
    assert rows["plus"].unavailable_reason == CLIENT_UNAVAILABLE_REASON


def test_an_unavailable_tier_is_refused_in_tier_words(monkeypatch: pytest.MonkeyPatch) -> None:
    _point(monkeypatch, standard="gpt-4o-mini", plus="gpt-4.1-mini", pro="gpt-5.4-mini")
    _offer(monkeypatch, "gpt-4o-mini")
    with pytest.raises(ProblemError) as refused:
        resolve_tier_choice("plus", current_model=None, field="llm_tier")
    problem = refused.value
    assert problem.code == "llm_tier_not_available"
    text = f"{problem.title} {problem.detail} {problem.remediation}"
    assert "Plus" in text and "Standard" in text
    for model in LLM_MODELS:
        assert model not in text


def test_a_tier_resolves_to_the_model_it_points_at(monkeypatch: pytest.MonkeyPatch) -> None:
    _point(monkeypatch, plus="gemini-2.5-flash")
    _offer(monkeypatch, "gemini-2.5-flash")
    assert tier_model("plus") == "gemini-2.5-flash"
    assert resolve_tier_choice("plus", current_model=None, field="f") == "gemini-2.5-flash"
    assert resolve_tier_choice(None, current_model="gpt-4.1-mini", field="f") is None


# --- 3. the surcharge follows the resolved model ---------------------------------------------


def test_the_surcharge_flag_is_the_resolved_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _point(monkeypatch, standard="gpt-4o-mini", plus="gpt-4.1-mini", pro="gpt-5.4-mini")
    _offer(monkeypatch)
    for option in available_tiers():
        assert option.is_surcharged == is_surchargeable_llm_model(option.model)
    # Point Standard at an upgrade, and Standard carries the surcharge — the tier word does
    # not decide money, the model does.
    _point(monkeypatch, standard="gpt-4.1-mini")
    standard = next(o for o in available_tiers() if o.tier == "standard")
    assert standard.is_surcharged is True


# --- 4. legacy choices --------------------------------------------------------------------------


def test_a_stored_model_reads_as_the_tier_pointed_at_it_else_its_price_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point(
        monkeypatch, standard="gemini-2.5-flash-lite", plus="gemini-2.5-flash", pro="gpt-5.4-mini"
    )
    # Pointed at: the tier wins.
    assert tier_of_model("gemini-2.5-flash") == "plus"
    # Pointed at by nobody: the price class answers.
    assert tier_of_model("gpt-4o-mini") == "standard"
    assert tier_of_model("gpt-4.1-mini") == "plus"
    # An operator pointing a tier outside the model's class: the pointer wins for display.
    _point(monkeypatch, standard="gpt-4.1-mini")
    assert tier_of_model("gpt-4.1-mini") == "standard"
    assert tier_of_model(None) is None
    assert tier_of_model("not-a-model") is None


def test_re_choosing_the_tier_an_account_reads_as_keeps_its_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point(monkeypatch, plus="gemini-2.5-flash")
    # The legacy model is NOT offerable any more and is still kept: the save is a no-op.
    _offer(monkeypatch, "gemini-2.5-flash")
    kept = resolve_tier_choice("plus", current_model="gpt-4.1-mini", field="f")
    assert kept == "gpt-4.1-mini"
    moved = resolve_tier_choice("plus", current_model="gpt-4o-mini", field="f")
    assert moved == "gemini-2.5-flash"


def test_client_labels_name_tiers_once_each(monkeypatch: pytest.MonkeyPatch) -> None:
    _point(monkeypatch, standard="gemini-2.5-flash-lite", plus="gpt-4.1-mini", pro="gpt-5.4-mini")
    assert client_model_labels(["gpt-4.1-mini", "gemini-2.5-flash", "gpt-5.4-mini"]) == [
        "Plus",
        "Pro",
    ]
    assert client_model_label("sarvam-m") == "Custom"
    assert client_model_label("sarvam-m", unclassified="Calevate") == "Calevate"


# --- 5. the engine catalogue -----------------------------------------------------------------


def test_engine_tokens_are_opaque_stable_and_round_trip() -> None:
    models = [
        CatalogueModel(model_id="prana-voice", label="P", call_capable=True, plan_allows=True),
        CatalogueModel(model_id="gpt-5-mini", label="G", call_capable=True, plan_allows=True),
    ]
    catalogue = EngineCatalogue(models=models, complete=True)
    token = engine_model_token("gpt-5-mini")
    assert token == engine_model_token("gpt-5-mini")
    assert token.startswith("m_") and "gpt" not in token
    assert engine_model_for_token(catalogue, token) == "gpt-5-mini"
    assert engine_model_for_token(catalogue, engine_model_token("gone")) is None


def test_engine_models_show_their_own_name_with_our_tier_where_known() -> None:
    models = [
        CatalogueModel(model_id="a", label="Vendor A", call_capable=True, plan_allows=True),
        CatalogueModel(
            model_id="b", label="Vendor B", call_capable=True, plan_allows=True, tier="pro"
        ),
        CatalogueModel(model_id="c", label="Vendor C", call_capable=True, plan_allows=True),
    ]
    assert engine_model_labels(models) == {
        "a": "Vendor A",
        "b": "Vendor B · Pro",
        "c": "Vendor C",
    }
