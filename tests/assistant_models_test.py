"""D-786: Pip's models follow Google's October catalogue.

A Google project that never used Gemini 2.5 gets 404 on it, and `gemini-3.5-flash` was
withdrawn, so the assistant's defaults moved to Gemini 3 models a new project can call.
Those stay refused on calls (thinking cannot be switched off) and are offered only to the
assistant, through the same key-and-attested-price gate as everything else (hard rule 7).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any, get_args

import pytest
from apps.api.agents import assist_leg, llm_models
from apps.api.billing import rates
from apps.api.copilot import model_tiers, service
from apps.api.core import platform_config
from apps.api.core.settings import get_settings
from apps.workers import chat, document_ocr, gemini_native
from calevate_shared.config import Settings
from calevate_shared.document_ingest import OcrUnavailableError
from calevate_shared.engine import (
    COPILOT_FAST_MODEL_DEFAULT,
    COPILOT_PLANNING_MODEL_DEFAULT,
    DOCUMENT_OCR_MODEL,
    GEMINI_RETIRED_LLMS,
    LLM_MODEL_NAMES,
    LLM_MODELS,
    OFF_CALL_LLM_MODELS,
    SELECTABLE_LLM_MODELS,
    GoogleDirectModel,
    keeps_default_temperature,
)
from calevate_shared.model_lifecycle import MODEL_LIFECYCLE
from pydantic import ValidationError

#: Read back from the retired set rather than spelled: `sarvam_model_identifier_test` keeps
#: Google ids in `engine.py` and the lifecycle registry alone.
WITHDRAWN = next(m for m in GEMINI_RETIRED_LLMS if m.startswith("gemini-3"))
DEFAULTS = (COPILOT_FAST_MODEL_DEFAULT, COPILOT_PLANNING_MODEL_DEFAULT)
#: A model that can switch thinking off, so Pip still sends it a temperature.
GEMINI_25_FLASH_LITE = "gemini-2.5-flash-lite"


@pytest.fixture
def google_key_and_prices() -> Iterator[set[str]]:
    """A deployment holding a Google key; the yielded set is the models given a price."""
    priced: set[str] = set()
    llm_models.install_llm_credential_reader(lambda: frozenset({"google"}))
    rates.install_llm_price_attestations(
        lambda: {
            model: rates.LlmPriceAttestation(
                model=model,
                input_usd_per_mtok=LLM_MODELS[model].price.input_usd_per_mtok,
                output_usd_per_mtok=LLM_MODELS[model].price.output_usd_per_mtok,
                read_on=date(2026, 10, 15),
                attested_by="test",
                source="test invoice",
            )
            for model in priced
        }
    )
    yield priced
    llm_models.install_llm_credential_reader(None)
    rates.install_llm_price_attestations(None)


def test_the_withdrawn_model_is_gone_from_every_list() -> None:
    assert WITHDRAWN not in LLM_MODEL_NAMES
    assert WITHDRAWN not in LLM_MODELS
    assert WITHDRAWN not in get_args(GoogleDirectModel)
    assert WITHDRAWN not in MODEL_LIFECYCLE


@pytest.mark.parametrize("field", ["copilot_fast_model", "copilot_planning_model"])
def test_the_console_refuses_the_withdrawn_model(field: str) -> None:
    with pytest.raises(ValidationError):
        platform_config.validate_value(field, WITHDRAWN)


def test_a_stored_withdrawn_model_is_ignored_and_alarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row an operator saved before the id was withdrawn: the default runs instead of a
    404, and the operator is told which setting to re-save."""
    raised: list[tuple[str, dict[str, Any]]] = []

    def _alert(stage: str, code: str, **fields: Any) -> None:
        raised.append((code, fields))

    monkeypatch.setattr(platform_config, "alert", _alert)
    resolved = platform_config._resolve({"copilot_fast_model": WITHDRAWN}, environ={})

    assert "copilot_fast_model" not in resolved
    ((code, fields),) = raised
    assert code == "platform_config_row_invalid"
    assert fields["config_key"] == "copilot_fast_model"
    assert "copilot_fast_model" in fields["detail"]
    assert WITHDRAWN not in fields["detail"]


def test_the_defaults_are_assistant_models_and_stay_refused_on_calls() -> None:
    assert Settings.model_fields["copilot_fast_model"].default == COPILOT_FAST_MODEL_DEFAULT
    assert Settings.model_fields["copilot_planning_model"].default == (
        COPILOT_PLANNING_MODEL_DEFAULT
    )
    for model in DEFAULTS:
        assert model in OFF_CALL_LLM_MODELS
        assert model not in SELECTABLE_LLM_MODELS
        assert LLM_MODELS[model].off_call_only
        entry = MODEL_LIFECYCLE[model]
        assert entry.access_restriction is None
        assert entry.retirement_stance in ("dated", "none-announced")
        assert entry.retirement.verified


def test_the_25_models_stay_selectable_and_carry_googles_restriction() -> None:
    """D-786 records the restriction and moves nothing on the 2.5 entries; the in-call
    default left them (D-817, `own_model_call_cache_test`)."""
    for model in (GEMINI_25_FLASH_LITE, "gemini-2.5-flash"):
        assert model in SELECTABLE_LLM_MODELS
        restriction = MODEL_LIFECYCLE[model].access_restriction
        assert restriction and "actively used them in the past" in restriction


def test_off_call_only_needs_a_model_that_is_not_selectable() -> None:
    spec = LLM_MODELS[COPILOT_FAST_MODEL_DEFAULT]
    with pytest.raises(ValueError, match="selectable and off_call_only"):
        type(spec)(
            model=spec.model,
            provider=spec.provider,
            price=spec.price,
            traps=spec.traps,
            selectable=True,
            withdrawn_reason=None,
            off_call_only=True,
        )


def test_an_unpriced_default_falls_to_the_disclosed_fallback_rather_than_the_wire(
    google_key_and_prices: set[str],
) -> None:
    """Hard rule 7: with the key but no attested price, the tier is a leg that does not
    serve, naming the price as the ground, and nothing reaches Google."""
    monkey_settings = get_settings()
    assert monkey_settings.copilot_fast_model == COPILOT_FAST_MODEL_DEFAULT
    leg = model_tiers.tier_leg("fast")
    assert leg.serves_dashboard is False
    assert leg.blocked_reason == llm_models.NO_ATTESTED_PRICE_REASON
    with pytest.raises(ValueError):
        rates.llm_inr_per_ktok(COPILOT_FAST_MODEL_DEFAULT)


def test_an_attested_default_is_offered_to_the_assistant_and_not_to_calls(
    google_key_and_prices: set[str],
) -> None:
    google_key_and_prices.update(DEFAULTS)
    offered = llm_models.off_call_offerable_models()
    for model in DEFAULTS:
        assert model in offered
        assert model not in llm_models.offerable_models()
        assert llm_models.unofferable_reason(model, off_call=True) is None
        assert llm_models.unofferable_reason(model) == LLM_MODELS[model].withdrawn_reason
        priced = rates.llm_inr_per_ktok(model)
        assert isinstance(priced["in"], Decimal) and priced["in"] > 0


def test_the_catalogue_price_never_bills_on_its_own() -> None:
    """The new rows carry Google's published price as a REFERENCE only."""
    for model in OFF_CALL_LLM_MODELS - SELECTABLE_LLM_MODELS:
        assert LLM_MODELS[model].price.evidence.verified is False
        assert rates.llm_price_is_billable(model) is False


# --- temperature on Gemini 3 (Google: keep the default 1.0) -----------------------------


def _leg(model: str) -> chat.ChatLeg:
    return chat.ChatLeg(url="https://x.invalid/v1", api_key="k", wire_model=model, dialect="google")


def test_pip_sends_no_temperature_to_a_gemini_3_model_and_keeps_it_elsewhere() -> None:
    """Google 'strongly recommend[s] keeping the temperature parameter at its default value
    of 1.0' on Gemini 3 (ai.google.dev/gemini-api/docs/gemini-3, updated 2026-10-09)."""
    for model in DEFAULTS:
        assert keeps_default_temperature(model)
        assert service.answer_temperature(_leg(model)) is None
    assert service.answer_temperature(_leg(GEMINI_25_FLASH_LITE)) == (service.ANSWER_TEMPERATURE)
    assert service.answer_temperature(_leg("an-azure-deployment")) == service.ANSWER_TEMPERATURE


@pytest.mark.parametrize("model", [COPILOT_FAST_MODEL_DEFAULT, GEMINI_25_FLASH_LITE])
def test_both_pip_paths_carry_the_models_temperature(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    seen: dict[str, Any] = {}

    def _capture(name: str) -> Any:
        def _stream(*args: Any, **kwargs: Any) -> Any:
            seen[name] = kwargs.get("temperature", "absent")
            return None

        return _stream

    monkeypatch.setattr(chat, "stream", _capture("compat"))
    monkeypatch.setattr(gemini_native, "stream", _capture("native"))
    service.streamed_turn(_leg(model), [], [])
    service.native_turn(_leg(model), [], [])
    expected = None if keeps_default_temperature(model) else service.ANSWER_TEMPERATURE
    assert seen == {"compat": expected, "native": expected}


def test_a_gemini_3_native_request_has_no_temperature_in_its_config() -> None:
    body = gemini_native.request_body(
        [{"role": "user", "content": "hi"}], tools=None, temperature=None, max_tokens=10
    )
    assert "temperature" not in body.get("generationConfig", {})


# --- the dashboard assists' Google leg ---------------------------------------------------


def test_the_dashboard_google_leg_runs_the_fast_model_only_when_priced(
    google_key_and_prices: set[str],
) -> None:
    """Script assist, the agent-test generator and judge called Google with the account's
    2.5 id; they now run Pip's fast model, under the same key-and-price rule."""
    unpriced = assist_leg.google_assist_leg()
    assert unpriced.model == COPILOT_FAST_MODEL_DEFAULT
    assert unpriced.serves_dashboard is False
    assert unpriced.blocked_reason == llm_models.NO_ATTESTED_PRICE_REASON

    google_key_and_prices.add(COPILOT_FAST_MODEL_DEFAULT)
    priced = assist_leg.google_assist_leg()
    assert priced.model == COPILOT_FAST_MODEL_DEFAULT
    assert priced.account_chose_model is False


# --- photo reading -------------------------------------------------------------------------


def test_photo_reading_runs_a_model_a_new_project_can_call() -> None:
    assert DOCUMENT_OCR_MODEL in OFF_CALL_LLM_MODELS
    assert DOCUMENT_OCR_MODEL not in SELECTABLE_LLM_MODELS
    assert MODEL_LIFECYCLE[DOCUMENT_OCR_MODEL].access_restriction is None


def test_photo_reading_refuses_plainly_until_its_price_is_attested(
    google_key_and_prices: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "gemini_api_key", "g-test", raising=False)
    llm_models.install_dashboard_data_use_reader(lambda: frozenset({"google"}))
    try:
        with pytest.raises(OcrUnavailableError) as refused:
            document_ocr.ocr_leg()
        assert refused.value.reason == llm_models.NO_ATTESTED_PRICE_REASON

        google_key_and_prices.add(DOCUMENT_OCR_MODEL)
        assert document_ocr.ocr_leg().wire_model == DOCUMENT_OCR_MODEL
    finally:
        llm_models.install_dashboard_data_use_reader(None)
