"""Outbound dials start at most `Settings.carrier_cps` per second, platform-wide.

The carrier refuses calls started above the account's CPS with a 429
(`vobiz-findings/mirror/pages/faq/cps.md:13-16`). `carrier_pacing.await_dial_slot` is the
gate both dial loops take immediately before `dispatch_call`; these tests hold its spacing
against real Redis, its fail-open and timeout edges, and that a campaign tick's dials are
actually spaced by it.

Run: uv run python -m pytest -q tests/carrier_dispatch_pacing_test.py
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.workers import callbacks as callbacks_worker
from apps.workers import campaign_dispatch, carrier_pacing
from apps.workers.carrier_pacing import (
    DialPacingTimeoutError,
    await_dial_slot,
    slot_interval_ms,
)
from sqlalchemy import text
from tests.callback_dispatch_test import _book, _dialable_tenant, _row
from tests.dispatch_budget_test import _dlt_rows, _launched_campaign, _tenant


@pytest.fixture
def paced(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Pacing on, at 10 CPS, under a key no other test process shares."""
    prefix = f"calevate:test:dial_slot:{uuid.uuid4().hex}"
    monkeypatch.setattr(carrier_pacing, "PACING_KEY_PREFIX", prefix)
    monkeypatch.setattr(carrier_pacing, "pacing_applies", lambda: True)
    monkeypatch.setenv("CARRIER_CPS", "10")
    get_settings.cache_clear()
    yield f"{prefix}:{get_settings().carrier}"
    get_settings.cache_clear()


def test_the_gap_is_rounded_up_so_the_rate_is_never_exceeded() -> None:
    assert slot_interval_ms(1) == 1000
    assert slot_interval_ms(3) == 334
    assert slot_interval_ms(50) == 20


async def test_consecutive_dials_are_spaced_by_one_over_cps(paced: str) -> None:
    starts: list[float] = []
    for _ in range(4):
        await await_dial_slot()
        starts.append(time.monotonic())
    gaps = [b - a for a, b in pairwise(starts)]
    # 10 CPS is a 100 ms gap; Redis expires keys to the millisecond, so allow a hair under.
    assert all(gap >= 0.095 for gap in gaps), gaps
    assert starts[-1] - starts[0] >= 0.29


async def test_pacing_is_off_when_the_engine_does_not_dial_through_our_carrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(carrier_pacing, "pacing_applies", lambda: False)

    def _no_redis() -> Any:
        raise AssertionError("an unpaced engine must not touch Redis")

    monkeypatch.setattr(carrier_pacing, "get_redis", _no_redis)
    assert await await_dial_slot() == 0.0


def test_only_the_owned_runtime_is_paced(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Caps:
        agent_hosting = "owned_runtime"

    class _Engine:
        capabilities = _Caps()

    monkeypatch.setattr(carrier_pacing, "get_engine", lambda: _Engine())
    assert carrier_pacing.pacing_applies() is True
    _Caps.agent_hosting = "control_plane"
    assert carrier_pacing.pacing_applies() is False


async def test_a_held_slot_past_the_wait_budget_gives_the_dial_back(
    monkeypatch: pytest.MonkeyPatch, paced: str
) -> None:
    monkeypatch.setattr(carrier_pacing, "MAX_PACING_WAIT_S", 0.2)
    await get_redis().set(paced, "someone-else", px=5_000)
    try:
        with pytest.raises(DialPacingTimeoutError):
            await await_dial_slot()
    finally:
        await get_redis().delete(paced)


async def test_a_slot_key_with_no_ttl_cannot_block_for_ever(paced: str) -> None:
    await get_redis().set(paced, "stuck")
    try:
        waited = await await_dial_slot()
    finally:
        await get_redis().delete(paced)
    assert waited < 1.0


async def test_a_redis_outage_fails_open(monkeypatch: pytest.MonkeyPatch, paced: str) -> None:
    class _Down:
        async def set(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("redis down")

    monkeypatch.setattr(carrier_pacing, "get_redis", lambda: _Down())
    assert await await_dial_slot() == 0.0


# ------------------------------------------------------------------ a real tick


@pytest.fixture
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def test_a_campaign_ticks_dials_are_spaced_by_the_carrier_cps(
    monkeypatch: pytest.MonkeyPatch, paced: str, _daytime: None
) -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    phones = tuple(f"+9198765{uuid.uuid4().int % 10**5:05d}" for _ in range(3))
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Paced", phones=phones, slider=3
    )
    dial_starts: list[float] = []

    async def _dial(session: Any, **kwargs: Any) -> None:
        dial_starts.append(time.monotonic())

    monkeypatch.setattr(campaign_dispatch, "dispatch_call", _dial)
    try:
        result = await campaign_dispatch._dispatch_for_campaign(tenant_id, campaign_id, 3, {})
    finally:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE campaigns SET status = 'cancelled', updated_at = now() WHERE id = :c"),
                {"c": campaign_id},
            )

    assert result["dialled"] == 3
    gaps = [b - a for a, b in pairwise(dial_starts)]
    assert all(gap >= 0.095 for gap in gaps), gaps


async def test_a_paced_out_contact_goes_back_on_the_ladder_unspent(
    monkeypatch: pytest.MonkeyPatch, paced: str, _daytime: None
) -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id,
        agent_id,
        number_id,
        template_id,
        name="Paced out",
        phones=(f"+9198764{uuid.uuid4().int % 10**5:05d}",),
        slider=1,
    )

    async def _timeout() -> float:
        raise DialPacingTimeoutError

    async def _never(session: Any, **kwargs: Any) -> None:
        raise AssertionError("a paced-out contact must not be dialled")

    monkeypatch.setattr(campaign_dispatch, "await_dial_slot", _timeout)
    monkeypatch.setattr(campaign_dispatch, "dispatch_call", _never)
    try:
        result = await campaign_dispatch._dispatch_for_campaign(tenant_id, campaign_id, 1, {})
        async with tenant_session(tenant_id) as session:
            status, attempts = (
                await session.execute(
                    text("SELECT status, attempts FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            ).one()
    finally:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE campaigns SET status = 'cancelled', updated_at = now() WHERE id = :c"),
                {"c": campaign_id},
            )

    assert result == {"dialled": 0, "blocked": 1, "exhausted": 0}
    assert (status, attempts) == ("pending", 0)


async def test_a_paced_out_call_back_is_deferred_not_spent(
    monkeypatch: pytest.MonkeyPatch, _daytime: None
) -> None:
    reset_engine_cache()
    tenant_id, agent_id = await _dialable_tenant()
    callback_id = await _book(tenant_id, agent_id)

    async def _timeout() -> float:
        raise DialPacingTimeoutError

    async def _never(session: Any, **kwargs: Any) -> None:
        raise AssertionError("a paced-out call-back must not be dialled")

    monkeypatch.setattr(callbacks_worker, "await_dial_slot", _timeout)
    monkeypatch.setattr(callbacks_worker, "dispatch_call", _never)

    outcome = await callbacks_worker.dispatch_due_callbacks(tenant_id, slots=5)

    assert outcome["dialled"] == 0 and outcome["blocked"] == 1
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "scheduled"
    assert row["last_refusal_rule"] == carrier_pacing.PACING_RULE
    assert row["attempts"] == 0
