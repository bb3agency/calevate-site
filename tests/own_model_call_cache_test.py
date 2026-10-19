"""Calls on our own Google key run Gemini 3.1 Flash-Lite and price cache hits at the cached
rung (D-817).

Every test here fails at c47d0d7e: the in-call default was `gemini-2.5-flash-lite`, which
our Google project answers 404 on; Gemini 3 was refused on the own-model leg along with every
other call path; a 2.5 model passed the own-model gate whatever Google's access limit; the
own-model floor raised for a model outside the reference card; and a call's cached input was
priced as ordinary input with no unit to hold it.

Vendor facts: ThinnestAI asks a Gemini 3 model to think less on calls
(`thinnest-findings/mirror/snapshots/2026-10-18/pages/api-reference/bring-your-own-keys.md:
167-169`); `usage.cachedInputTokens` is "How many of `inputTokens` the provider served from
its cache" and `inputTokens` includes them (`.../calls/get-call.md:1189-1207`). Prices at
`PLANNING_USD_INR` = 95 for 3.1 Flash-Lite's $0.25 / $1.50 / $0.025 per million
(ai.google.dev/gemini-api/docs/pricing, updated 2026-10-16): input ₹0.0238 per thousand,
output ₹0.1425 per thousand, cached ₹0.0238 per ten thousand.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from apps.api.agents import llm_models, own_model
from apps.api.billing import own_model_prompt as omp
from apps.api.billing import rates
from apps.api.billing.models import CLIENT_BILLED_UNIT_TYPES, LLM_CACHED_UNIT_TYPE, UNIT_TYPES
from apps.api.core.errors import ProblemError
from apps.api.core.logging import redact_mapping
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import pipeline
from calevate_shared.config import Settings
from calevate_shared.engine import (
    GOOGLE_DIRECT_MODELS,
    LLM_MODELS,
    OWN_MODEL_CALL_LLM_MODELS,
    SELECTABLE_LLM_MODELS,
    THINNEST_OWN_MODEL_DEFAULT,
)
from calevate_shared.events import CallLlmUsage
from calevate_shared.model_lifecycle import MODEL_LIFECYCLE
from sqlalchemy import text
from tests.thinnest_publish_limits_test import _agent_with_script, _thinnest

FLASH_LITE_3 = "gemini-3.1-flash-lite"
FLASH_LITE_25 = "gemini-2.5-flash-lite"
TENANT = uuid7()


def _attestation(model: str, cached: Decimal | None) -> rates.LlmPriceAttestation:
    price = LLM_MODELS[model].price
    return rates.LlmPriceAttestation(
        model=model,
        input_usd_per_mtok=price.input_usd_per_mtok,
        output_usd_per_mtok=price.output_usd_per_mtok,
        read_on=date(2026, 10, 18),
        attested_by="founder",
        source="ai.google.dev/gemini-api/docs/pricing, updated 2026-10-16",
        cached_input_usd_per_mtok=cached,
    )


@pytest.fixture
def google_key_and_prices() -> Iterator[None]:
    """A deployment holding our Google key, every Google model priced, 3.1 with its rung."""
    llm_models.install_llm_credential_reader(lambda: frozenset({"google"}))
    rates.install_llm_price_attestations(
        lambda: {
            model: _attestation(model, Decimal("0.025") if model == FLASH_LITE_3 else None)
            for model in GOOGLE_DIRECT_MODELS
        }
    )
    yield
    rates.install_llm_price_attestations(None)
    llm_models.install_llm_credential_reader(None)


@pytest.fixture
def priced_without_rung() -> Iterator[None]:
    rates.install_llm_price_attestations(lambda: {FLASH_LITE_3: _attestation(FLASH_LITE_3, None)})
    yield
    rates.install_llm_price_attestations(None)


# --- the default and who may run it ---------------------------------------------------------


def test_the_in_call_default_is_31_flash_lite_on_the_own_model_leg_only() -> None:
    assert THINNEST_OWN_MODEL_DEFAULT == FLASH_LITE_3
    assert Settings.model_fields["thinnest_own_model_default"].default == FLASH_LITE_3
    assert FLASH_LITE_3 in OWN_MODEL_CALL_LLM_MODELS
    assert LLM_MODELS[FLASH_LITE_3].own_model_call
    # Still refused where our code would run a call, and still no client's to pick.
    assert FLASH_LITE_3 not in SELECTABLE_LLM_MODELS
    assert MODEL_LIFECYCLE[FLASH_LITE_3].access_restriction is None
    # The other Gemini 3 models are not let onto calls by this change.
    assert {m for m in OWN_MODEL_CALL_LLM_MODELS if m.startswith("gemini-3")} == {FLASH_LITE_3}


def test_only_a_google_model_withheld_from_calls_may_carry_the_own_model_flag() -> None:
    spec = LLM_MODELS[FLASH_LITE_3]
    selectable = LLM_MODELS[FLASH_LITE_25]
    with pytest.raises(ValueError, match="own_model_call and selectable"):
        type(selectable)(
            model=selectable.model,
            provider=selectable.provider,
            price=selectable.price,
            traps=selectable.traps,
            selectable=True,
            withdrawn_reason=None,
            own_model_call=True,
        )
    with pytest.raises(ValueError, match="not a Google model"):
        type(spec)(
            model=spec.model,
            provider="openai",
            price=spec.price,
            traps=spec.traps,
            selectable=False,
            withdrawn_reason=spec.withdrawn_reason,
            own_model_call=True,
        )


def test_the_own_model_leg_runs_31_and_refuses_the_25_models_google_limits(
    google_key_and_prices: None,
) -> None:
    offered = llm_models.own_model_offerable_models()
    assert FLASH_LITE_3 in offered
    for model in GOOGLE_DIRECT_MODELS:
        if MODEL_LIFECYCLE[model].access_restriction:
            assert model not in offered
            assert (
                llm_models.unofferable_reason(model, own_model_call=True)
                == llm_models.ACCESS_RESTRICTED_REASON
            )
    assert own_model.offerable_own_models() == tuple(sorted(offered))
    # Every other path is as it was: 3.1 is not offered where a client's model is chosen,
    # and the 2.5 models still are.
    assert FLASH_LITE_3 not in llm_models.offerable_models()
    assert FLASH_LITE_25 in llm_models.offerable_models()


def test_the_own_model_leg_still_needs_the_key_and_the_price() -> None:
    llm_models.install_llm_credential_reader(lambda: frozenset())
    try:
        assert llm_models.unofferable_reason(FLASH_LITE_3, own_model_call=True) == (
            llm_models.NO_CREDENTIAL_REASON
        )
    finally:
        llm_models.install_llm_credential_reader(None)


async def test_the_console_refuses_saving_a_25_default_and_names_why(
    google_key_and_prices: None,
) -> None:
    await own_model.assert_own_model_default_offerable(FLASH_LITE_3)
    with pytest.raises(ProblemError) as refused:
        await own_model.assert_own_model_default_offerable(FLASH_LITE_25)
    assert refused.value.code == own_model.OWN_MODEL_NOT_OFFERED
    assert "no longer available to new users" in (refused.value.detail or "")


async def test_a_stored_25_default_reads_not_ready_and_no_call_is_placed_on_it(
    google_key_and_prices: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _attested(_session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return frozenset({"byok_llm_voice"})

    async def _workspaces() -> list[Any]:
        return []

    async def _developer(_session: Any) -> Any:
        from datetime import UTC, datetime

        from apps.api.tenancy.engine_workspace import DeveloperOwnModelRecord

        return DeveloperOwnModelRecord(datetime.now(UTC), datetime.now(UTC), None)

    monkeypatch.setattr(own_model, "attested_rate_keys", _attested)
    monkeypatch.setattr(own_model, "own_model_workspaces", _workspaces)
    monkeypatch.setattr(own_model, "read_developer_own_model", _developer)
    monkeypatch.setattr(own_model, "dashboard_data_use_attested", lambda: {"google"})
    monkeypatch.setattr(get_settings(), "gemini_api_key", "AIza-test")
    monkeypatch.setattr(get_settings(), "thinnest_own_model_default", THINNEST_OWN_MODEL_DEFAULT)

    ready = await own_model.own_model_readiness(object(), engine="thinnest")  # type: ignore[arg-type]
    assert ready.default_model == FLASH_LITE_3 and ready.ready

    monkeypatch.setattr(get_settings(), "thinnest_own_model_default", FLASH_LITE_25)
    stale = await own_model.own_model_readiness(object(), engine="thinnest")  # type: ignore[arg-type]
    assert not stale.ready and not stale.default_offerable
    assert stale.default_reason == llm_models.ACCESS_RESTRICTED_REASON
    assert any(FLASH_LITE_25 in step for step in stale.missing())
    with pytest.raises(ProblemError) as refused:
        await own_model.assert_own_model_ready(object(), True)  # type: ignore[arg-type]
    assert refused.value.code == own_model.OWN_MODEL_NOT_READY
    # The publish seam: an agent with no model of its own would run the stored default, and
    # it is refused rather than published onto a model that 404s.
    assert own_model.own_model_for(None) == FLASH_LITE_25
    with pytest.raises(ProblemError) as publish:
        own_model.refuse_unofferable_own_model(own_model.own_model_for(None))
    assert publish.value.code == own_model.OWN_MODEL_NOT_OFFERED


def test_the_own_model_floor_prices_31_at_its_list_price() -> None:
    price = rates.own_model_reference_inr_per_ktok(FLASH_LITE_3)
    assert price == {"in": Decimal("0.0238"), "out": Decimal("0.1425")}
    assert rates.own_model_reference_inr_per_ktok(FLASH_LITE_25) == (
        rates.llm_reference_inr_per_ktok(FLASH_LITE_25)
    )
    floor = rates.own_model_floor_inr_per_min(FLASH_LITE_3, prompt_tokens=6_000)
    assert floor > rates.own_model_floor_inr_per_min(FLASH_LITE_25, prompt_tokens=6_000)
    # The reference card itself stays the choosable set.
    assert FLASH_LITE_3 not in rates.PRICED_LLM_MODELS


# --- the ledger -----------------------------------------------------------------------------


def test_the_cached_call_unit_is_a_call_cost_unit() -> None:
    assert LLM_CACHED_UNIT_TYPE == "llm_10ktok_cached_in"
    assert LLM_CACHED_UNIT_TYPE in CLIENT_BILLED_UNIT_TYPES
    assert UNIT_TYPES.count(LLM_CACHED_UNIT_TYPE) == 1


def _cost(rows: list[tuple[str, Decimal, Decimal | None]]) -> Decimal:
    return sum((qty * (price or 0) for _, qty, price in rows), Decimal("0"))


def test_a_reported_cache_hit_with_a_rung_is_its_own_row(google_key_and_prices: None) -> None:
    rows = pipeline._own_model_rows(
        FLASH_LITE_3,
        CallLlmUsage(input_tokens=16_000, output_tokens=100, cached_input_tokens=12_000),
        tenant_id=TENANT,
        call_id=uuid7(),
    )
    assert rows == [
        ("llm_ktok_in", Decimal("4"), Decimal("0.0238")),
        ("llm_ktok_out", Decimal("0.1"), Decimal("0.1425")),
        (LLM_CACHED_UNIT_TYPE, Decimal("1.2"), Decimal("0.0238")),
    ]
    # 4 x 0.0238 + 0.1 x 0.1425 + 1.2 x 0.0238, against 0.39505 at the full input rate.
    assert _cost(rows) == Decimal("0.13801")


def test_a_hit_count_above_the_input_is_held_to_the_input(google_key_and_prices: None) -> None:
    rows = pipeline._own_model_rows(
        FLASH_LITE_3,
        CallLlmUsage(input_tokens=5_000, output_tokens=0, cached_input_tokens=9_000),
        tenant_id=TENANT,
        call_id=uuid7(),
    )
    assert rows[0][1] == Decimal("0") and rows[2][1] == Decimal("0.5")


@pytest.mark.parametrize("cached", [None, 0])
def test_no_reported_hit_prices_every_input_token_in_full(
    google_key_and_prices: None, cached: int | None
) -> None:
    rows = pipeline._own_model_rows(
        FLASH_LITE_3,
        CallLlmUsage(input_tokens=16_000, output_tokens=100, cached_input_tokens=cached),
        tenant_id=TENANT,
        call_id=uuid7(),
    )
    assert [unit for unit, _, _ in rows] == ["llm_ktok_in", "llm_ktok_out"]
    assert _cost(rows) == Decimal("0.39505")


def test_no_attested_rung_prices_every_input_token_in_full(priced_without_rung: None) -> None:
    rows = pipeline._own_model_rows(
        FLASH_LITE_3,
        CallLlmUsage(input_tokens=16_000, output_tokens=100, cached_input_tokens=12_000),
        tenant_id=TENANT,
        call_id=uuid7(),
    )
    assert len(rows) == 2 and _cost(rows) == Decimal("0.39505")


def test_the_calls_counts_are_logged_past_the_redactor(
    google_key_and_prices: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    class _Log:
        def info(self, event: str, *, extra: dict[str, Any]) -> None:
            seen.append((event, extra))

    monkeypatch.setattr(pipeline, "log", _Log())
    call_id = uuid7()
    pipeline._own_model_rows(
        FLASH_LITE_3,
        CallLlmUsage(input_tokens=6_000, output_tokens=80, cached_input_tokens=4_000),
        tenant_id=TENANT,
        call_id=call_id,
    )
    ((event, extra),) = seen
    assert event == "own_model_call_metered"
    logged = redact_mapping(dict(extra))
    assert logged["input_count"] == 6_000 and logged["cached_input_count"] == 4_000
    assert logged["output_count"] == 80 and logged["call_id"] == str(call_id)


async def test_the_ledger_takes_the_cached_row_and_the_floor_samples_the_call_once() -> None:
    """The CHECK admits the unit (migration c8a3f5e19b62), and the prompt-size sample reads
    the call's whole input from the `llm_ktok_in` row's meta, cache hits included."""
    tenant_id, agent_id = await _agent_with_script("[BUSINESS]\nశ్రీ Organics\n\n[GOAL]\nBook.")
    prompt = 6_150
    turns = 5 * rates.REFERENCE_CALL["turns_per_minute"]
    measured_input = prompt * turns + rates.REFERENCE_CALL["turn_tokens"] * turns * (turns - 1) // 2
    cached = measured_input // 2
    call_id = uuid7()
    meta = json.dumps(
        {
            "own_model": FLASH_LITE_3,
            "llm_input_tokens": measured_input,
            "llm_cached_input_tokens": cached,
        }
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500002', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{call_id.hex}"},
        )
        for unit, qty, cost in (
            ("telephony_s", Decimal(300), None),
            ("llm_ktok_in", Decimal(measured_input - cached) / 1000, Decimal("0.0238")),
            (LLM_CACHED_UNIT_TYPE, Decimal(cached) / 10_000, Decimal("0.0238")),
        ):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                    ":u, :q, :p, now(), CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit,
                    "q": qty,
                    "p": cost,
                    "m": meta,
                },
            )
        sample = await omp.sample_tenant(session, tenant_id=tenant_id, engine=_thinnest())
        hit_rate = (
            await session.execute(
                text(
                    "SELECT sum((meta->>'llm_cached_input_tokens')::numeric) "
                    "/ sum((meta->>'llm_input_tokens')::numeric) FROM usage_events "
                    "WHERE unit_type = 'llm_ktok_in' AND meta->>'own_model' IS NOT NULL "
                    "AND meta->>'llm_cached_input_tokens' IS NOT NULL"
                )
            )
        ).scalar_one()
    assert sample.measured == [Decimal(prompt)]
    assert hit_rate == Decimal(cached) / Decimal(measured_input)
