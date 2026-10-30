"""The Model prices card speaks to an operator: which feature waits on a price, and why a
model is withheld, in one plain sentence each (30 Oct 2026)."""

from __future__ import annotations

import pytest
from apps.api.core.settings import get_settings
from apps.api.ops.model_price_routes import _withheld_line, model_uses
from apps.api.ops.model_pricing import ModelOfferability
from calevate_shared.engine import DOCUMENT_OCR_MODEL, LLM_MODELS


def _offer(model: str) -> ModelOfferability:
    spec = LLM_MODELS[model]
    return ModelOfferability(
        model=model,
        provider=spec.provider,
        credential_installed=True,
        price_attested=False,
        reference_verified=False,
        withheld_reason=spec.withdrawn_reason if not spec.selectable else None,
        off_call_only=spec.off_call_only,
    )


def test_the_pip_models_and_the_photo_reader_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "copilot_fast_model", "gemini-3.1-flash-lite", raising=False)
    monkeypatch.setattr(settings, "copilot_planning_model", "gemini-3.5-flash-lite", raising=False)
    assert model_uses("gemini-3.1-flash-lite") == ["pip"]
    assert model_uses(DOCUMENT_OCR_MODEL) == ["pip", "photo_reading"]
    assert model_uses("gpt-4o-mini") == []


def test_a_model_refused_on_calls_reads_as_one_operator_sentence() -> None:
    offer = _offer(DOCUMENT_OCR_MODEL)
    line = _withheld_line(offer, ["pip", "photo_reading"])
    assert line == (
        "Not used on calls: this model can go silent mid-call. Pip and photo reading can use it."
    )
    # The engineering ground stays in the catalogue.
    assert offer.withheld_reason and "ai.google.dev" in offer.withheld_reason
    assert _withheld_line(_offer("gemini-3.8-flash"), []) == (
        "Not used on calls: this model can go silent mid-call. Pip can use it."
    )


def test_every_withheld_line_is_plain() -> None:
    for model in LLM_MODELS:
        line = _withheld_line(_offer(model), model_uses(model))
        if line is None:
            continue
        assert "_" not in line and "`" not in line and "/" not in line, line
        assert len(line) < 120, line
