"""The prompt size the own-model cost floor is struck at (D-764, `billing/own_model_prompt`).

The floor's model half used `REFERENCE_CALL`'s 900-token prompt, which every composed engine
prompt exceeds. These pin the replacement: measured calls past the sample bar, else the
largest published prompt, else the engine's prompt ceiling; the floor rising with the prompt;
one rounding; and the cache the routes read.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from apps.api.agents.prompt_size import publish_config
from apps.api.billing import own_model_prompt as omp
from apps.api.billing import rates
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import own_model_key
from calevate_shared.engine import compose_engine_prompt
from sqlalchemy import text
from tests.thinnest_publish_limits_test import _agent_with_script, _thinnest

MODEL = "gemini-2.5-flash-lite"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


# --- characters to tokens -----------------------------------------------------------------


def test_ascii_counts_at_googles_four_characters_and_other_script_at_one_each() -> None:
    assert omp.prompt_tokens_of("abcd" * 10) == 10
    assert omp.prompt_tokens_of("abcde") == 2  # rounded up
    telugu = "నమస్కారం"
    assert omp.prompt_tokens_of(telugu) == len(telugu)
    assert omp.prompt_tokens_of("abcd" + telugu) == 1 + len(telugu)


def test_the_ceiling_is_the_engines_prompt_box_every_character_a_token() -> None:
    assert omp.CEILING_PROMPT_CHARS == 20_000
    assert omp.CEILING_PROMPT_TOKENS == 20_000
    assert omp.CEILING_BASIS.source == "ceiling"
    assert "no prompt size computed" in omp.CEILING_BASIS.label


# --- the measured inversion ---------------------------------------------------------------


def test_a_call_priced_back_at_its_effective_prompt_reproduces_its_input() -> None:
    prompt = 6_150
    turns = 5 * rates.REFERENCE_CALL["turns_per_minute"]
    measured_input = prompt * turns + rates.REFERENCE_CALL["turn_tokens"] * turns * (turns - 1) // 2
    assert omp.effective_prompt_tokens(measured_input, Decimal(300)) == prompt


def test_an_effective_prompt_is_never_negative() -> None:
    assert omp.effective_prompt_tokens(10, Decimal(600)) == 0


# --- which source wins --------------------------------------------------------------------


def test_twenty_measured_calls_set_the_size_at_their_p95() -> None:
    measured = [Decimal(n * 100) for n in range(1, 21)]
    basis = omp.basis_from(measured, [9_000], computed_at=NOW)
    # nearest rank: ceil(0.95 * 20) = 19th of 20
    assert (basis.source, basis.prompt_tokens, basis.calls) == ("measured", 1_900, 20)
    assert basis.label.startswith("1,900 prompt tokens: p95 of 20 own-model calls")


def test_a_fractional_p95_rounds_up_to_a_whole_token() -> None:
    basis = omp.basis_from([Decimal("1500.2")] * 20, [], computed_at=NOW)
    assert basis.prompt_tokens == 1_501


def test_below_the_bar_the_largest_published_prompt_wins() -> None:
    basis = omp.basis_from([Decimal(99_999)] * 19, [4_000, 7_250], computed_at=NOW)
    assert (basis.source, basis.prompt_tokens, basis.agents) == ("published", 7_250, 2)
    assert "19 of 20 own-model calls measured" in basis.label


def test_a_measured_size_of_zero_does_not_stand() -> None:
    basis = omp.basis_from([Decimal(0)] * 20, [3_000], computed_at=NOW)
    assert (basis.source, basis.prompt_tokens) == ("published", 3_000)


def test_with_no_agent_and_no_call_the_ceiling_stands_never_900() -> None:
    basis = omp.basis_from([], [], computed_at=NOW)
    assert (basis.source, basis.prompt_tokens) == ("ceiling", omp.CEILING_PROMPT_TOKENS)
    assert "no live agent or own-model call yet" in basis.label


# --- the floor ----------------------------------------------------------------------------


def test_the_floor_rises_with_the_prompt_and_defaults_to_the_ceiling() -> None:
    small = rates.own_model_floor_inr_per_min(MODEL, prompt_tokens=2_000)
    large = rates.own_model_floor_inr_per_min(MODEL, prompt_tokens=8_000)
    assert small < large < rates.own_model_floor_inr_per_min(MODEL)
    assert rates.own_model_floor_inr_per_min(MODEL) == rates.own_model_floor_inr_per_min(
        MODEL, prompt_tokens=omp.CEILING_PROMPT_TOKENS
    )
    # The published §10.1 figure is unchanged: it is still the 900-token reference call.
    assert rates.llm_cost_inr_per_minute(5, model=MODEL) == rates.own_model_floor_inr_per_min(
        MODEL, prompt_tokens=rates.REFERENCE_CALL["prompt_tokens"]
    )


def test_the_floor_is_exact_arithmetic_rounded_once() -> None:
    price = rates.llm_reference_inr_per_ktok(MODEL)
    prompt, minutes = 6_150, rates.OWN_MODEL_FLOOR_CALL_MINUTES
    turns = minutes * rates.REFERENCE_CALL["turns_per_minute"]
    tokens_in = prompt * turns + rates.REFERENCE_CALL["turn_tokens"] * turns * (turns - 1) // 2
    tokens_out = rates.REFERENCE_CALL["output_tokens_per_turn"] * turns
    exact = (tokens_in * price["in"] + tokens_out * price["out"]) / 1000 / minutes
    floor = rates.own_model_floor_inr_per_min(MODEL, prompt_tokens=prompt)
    assert floor == exact.quantize(rates.MONEY_Q, rounding=rates.ROUNDING)
    assert floor.as_tuple().exponent == -4


def test_the_cost_floors_add_the_model_half_at_the_basis_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_own_model", True)
    clear_band = rates.THINNEST_CLEAR_COST_FLOOR_BY_BAND["premium"]
    clear = rates.cost_floor_inr_per_min(
        "clear", engine="thinnest", clear_band="premium", own_model_prompt_tokens=3_000
    )
    assert clear == clear_band + rates.own_model_floor_inr_per_min(
        get_settings().thinnest_own_model_default, prompt_tokens=3_000
    )
    assert clear < rates.cost_floor_inr_per_min("clear", engine="thinnest", clear_band="premium")


# --- the cache the routes read ------------------------------------------------------------


async def test_a_refreshed_basis_is_what_the_routes_read(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = omp.PromptBasis(6_150, "published", 3, 2, NOW)

    async def computed(engine: Any) -> omp.PromptBasis:
        return stored

    monkeypatch.setattr(omp, "compute_prompt_basis", computed)
    await omp.refresh_prompt_basis(_thinnest())
    assert await get_redis().ttl("calevate:own_model_prompt_basis") > 0
    assert await omp.current_prompt_basis() == stored
    assert await omp.floor_prompt_basis() is None  # switched off: no model half
    monkeypatch.setattr(get_settings(), "thinnest_own_model", True)
    assert omp.tokens_of(await omp.floor_prompt_basis()) == 6_150
    await get_redis().delete("calevate:own_model_prompt_basis")
    assert await omp.current_prompt_basis() == omp.CEILING_BASIS


async def test_the_hourly_sweep_refreshes_the_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    refreshed: list[Any] = []

    async def refresh(engine: Any) -> omp.PromptBasis:
        refreshed.append(engine)
        return omp.CEILING_BASIS

    async def no_workspaces() -> list[Any]:
        return []

    engine = _thinnest()
    monkeypatch.setattr(own_model_key, "_runs_own_model", lambda: engine)
    monkeypatch.setattr(own_model_key, "get_engine", lambda: engine)
    monkeypatch.setattr(own_model_key, "own_model_workspaces", no_workspaces)
    monkeypatch.setattr(own_model_key, "refresh_prompt_basis", refresh)
    result = await own_model_key.sweep_own_model_workspaces({})
    assert refreshed == [engine]
    assert result.endswith("prompt=ceiling")


# --- one tenant's rows --------------------------------------------------------------------


async def test_a_tenant_yields_its_live_agents_prompts_and_its_own_model_calls() -> None:
    tenant_id, agent_id = await _agent_with_script("[BUSINESS]\nశ్రీ Organics\n\n[GOAL]\nBook.")
    engine = _thinnest()
    prompt = 6_150
    turns = 5 * rates.REFERENCE_CALL["turns_per_minute"]
    measured_input = prompt * turns + rates.REFERENCE_CALL["turn_tokens"] * turns * (turns - 1) // 2
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live' WHERE id = :a"), {"a": agent_id}
        )
        for seconds, own_model in ((300, True), (300, False), (30, True)):
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500002', 'completed', now(), now())"
                ),
                {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex}"},
            )
            meta = json.dumps(
                {"own_model": MODEL, "llm_input_tokens": measured_input} if own_model else {}
            )
            for unit, qty in (
                ("telephony_s", seconds),
                ("llm_ktok_in", Decimal(measured_input) / 1000),
            ):
                await session.execute(
                    text(
                        "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                        "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                        ":u, :q, NULL, now(), CAST(:m AS jsonb), now())"
                    ),
                    {"i": uuid7(), "t": tenant_id, "c": call_id, "u": unit, "q": qty, "m": meta},
                )
        sample = await omp.sample_tenant(session, tenant_id=tenant_id, engine=engine)
        cfg = await publish_config(session, tenant_id=tenant_id, agent_id=agent_id, engine=engine)
    # Only the own-model call of at least a minute is measured.
    assert sample.measured == [Decimal(prompt)]
    assert sample.published == [omp.prompt_tokens_of(compose_engine_prompt(cfg))]
    assert sample.published[0] > rates.REFERENCE_CALL["prompt_tokens"]
