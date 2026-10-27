"""Gemini is the assistant's main model (founder, 27 Oct 2026, "Our main model is gemini").

Production had no Azure leg, the Gemini key and the Sarvam key installed, and Pip answered
on the Sarvam standby with nothing telling an operator why. The ladder now hands every
account whose own leg cannot serve the platform's Gemini leg first; Azure stays an optional
rung when configured; Sarvam is the disclosed last resort, and a Gemini leg that cannot
serve raises `assistant_gemini_unavailable` naming what to record.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from apps.api.agents import assist_leg
from apps.api.agents.llm_models import (
    NO_DATA_USE_ATTESTATION_REASON,
    install_dashboard_data_use_reader,
)
from apps.api.core.settings import get_settings
from apps.workers.extraction import (
    AZURE_PROVIDER,
    GOOGLE_PROVIDER,
    SARVAM_PROVIDER,
    assist_capability,
)

pytestmark = pytest.mark.anyio


class _Row:
    def __init__(self, model: str | None) -> None:
        self._model = model

    def first(self) -> tuple[str | None] | None:
        return None if self._model is None else (self._model,)


class _Session:
    """One organizations row: the account's chosen model, or none (a new account)."""

    def __init__(self, model: str | None) -> None:
        self._model = model

    async def execute(self, *_: Any, **__: Any) -> _Row:
        return _Row(self._model)


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Gemini key and Sarvam key, no Azure; the assistant's Gemini model priced and offered.
    Returns the alarms raised."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_resource", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", None, raising=False)
    monkeypatch.setattr(
        assist_leg, "off_call_offerable_models", lambda: frozenset({settings.copilot_fast_model})
    )
    alarms: list[dict[str, Any]] = []
    monkeypatch.setattr(
        assist_leg,
        "alert",
        lambda stage, code, **kw: alarms.append({"stage": stage, "code": code, **kw}),
    )
    install_dashboard_data_use_reader(None)
    yield alarms
    install_dashboard_data_use_reader(None)


def _attest_google() -> None:
    install_dashboard_data_use_reader(lambda: frozenset({GOOGLE_PROVIDER}))


@pytest.mark.parametrize("chosen", [None, "gpt-5.4-mini"])
async def test_gemini_answers_for_any_account_once_attested(
    production: list[dict[str, Any]], chosen: str | None
) -> None:
    """A new account (no model chosen) and an account on a model the dashboard cannot use
    both get the platform's Gemini leg, before any Azure or Sarvam rung."""
    _attest_google()
    leg = await assist_leg.account_assist_leg(cast(Any, _Session(chosen)))
    assert leg.provider == GOOGLE_PROVIDER and leg.serves_dashboard
    assert leg.model == get_settings().copilot_fast_model
    assert assist_capability(tenant_leg=leg).provider == GOOGLE_PROVIDER
    assert production == []


async def test_without_the_attestation_sarvam_answers_and_an_operator_is_told_what_to_record(
    production: list[dict[str, Any]],
) -> None:
    leg = await assist_leg.account_assist_leg(cast(Any, _Session(None)))
    assert leg.serves_dashboard is False
    assert leg.blocked_reason == NO_DATA_USE_ATTESTATION_REASON
    capability = assist_capability(tenant_leg=leg)
    assert capability.provider == SARVAM_PROVIDER and capability.disclosure
    assert [a["code"] for a in production] == [assist_leg.GEMINI_UNAVAILABLE_ALARM]
    assert "Admin → Ops → Dashboard data use" in production[0]["detail"]


async def test_azure_answers_only_when_configured_and_gemini_cannot(
    production: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = await assist_leg.account_assist_leg(cast(Any, _Session(None)))
    assert assist_capability(tenant_leg=blocked).provider == SARVAM_PROVIDER

    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    assert assist_capability(tenant_leg=blocked).provider == AZURE_PROVIDER

    # With Gemini serving, Azure being configured changes nothing.
    _attest_google()
    serving = await assist_leg.account_assist_leg(cast(Any, _Session(None)))
    assert assist_capability(tenant_leg=serving).provider == GOOGLE_PROVIDER
