"""The carrier account's simultaneous-call limit, held at the dial gate (D-663).

The account carries `Settings.carrier_concurrency` lines, inbound and outbound together, and
Vobiz refuses a dial over the limit with `429` (`vobiz-findings/mirror/pages/call/
make-call.md:134`). These tests pin the three halves of holding it: the pool arithmetic
(three lines leave two for outbound), the database count of lines in use in both directions,
and the refusal a dial gets when the pool is full or the carrier itself says it is.

Run: uv run python -m pytest -q tests/carrier_line_cap_test.py
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.service import carrier_lines_in_use, dial_was_not_placed
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import carrier_pacing, reset_engine_cache, vendor_http
from apps.api.engine.carrier_pacing import (
    LINES_BUSY_RULE,
    LIVE_LINE_HORIZON,
    RING_LINE_HORIZON,
    inbound_line_reserve,
    lines_busy,
    outbound_line_pool,
    pacing_timed_out,
)
from apps.api.engine.vendor_http import is_line_limit, vendor_request
from sqlalchemy import text
from tests.callback_dispatch_test import _dialable_tenant

pytestmark = pytest.mark.anyio

_TENANTS: list[uuid.UUID] = []


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CARRIER_CONCURRENCY", "3")
    monkeypatch.delenv("INBOUND_RESERVED_LINES", raising=False)
    monkeypatch.setenv("INBOUND_RESERVE_RATIO", "0.3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the arithmetic ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("concurrency", "reserved_lines", "reserve"),
    [
        # Unset: the automatic share, never rounded up by a float.
        (3, None, 1),
        (5, None, 2),
        (10, None, 3),
        (1, None, 1),
        # A count: taken as typed, never zero, never more than the account has.
        (5, 2, 2),
        (5, 1, 1),
        (3, 9, 3),
    ],
)
def test_the_inbound_reserve_is_never_zero_and_never_rounds_up_a_float(
    concurrency: int, reserved_lines: int | None, reserve: int
) -> None:
    assert inbound_line_reserve(concurrency, reserved_lines, 0.3) == reserve


def test_a_typed_count_sets_the_outbound_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARRIER_CONCURRENCY", "5")
    monkeypatch.setenv("INBOUND_RESERVED_LINES", "1")
    get_settings.cache_clear()
    try:
        assert outbound_line_pool() == 4
    finally:
        get_settings.cache_clear()


def test_three_lines_leave_two_for_outbound(lines: None) -> None:
    assert outbound_line_pool() == 2


def test_a_one_line_account_has_no_outbound_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARRIER_CONCURRENCY", "1")
    get_settings.cache_clear()
    try:
        assert outbound_line_pool() == 0
    finally:
        get_settings.cache_clear()


def test_both_refusals_prove_no_line_was_seized() -> None:
    for refusal in (lines_busy(), pacing_timed_out()):
        assert refusal.kind == "transient"
        assert dial_was_not_placed(refusal) is True
    assert lines_busy().code == LINES_BUSY_RULE


# --- the carrier's own 429 ---------------------------------------------------------


def _throttled(limit_type: str | None) -> httpx.Response:
    details: dict[str, Any] = {"retryAfter": 0}
    if limit_type is not None:
        details["limitType"] = limit_type
    return httpx.Response(
        429, json={"status": "error", "error": {"code": "RATE_LIMIT_EXCEEDED", "details": details}}
    )


def test_only_the_per_second_limit_is_not_a_line_limit() -> None:
    assert is_line_limit("cps") is False
    assert is_line_limit(None) is False
    assert is_line_limit("concurrency") is True
    assert is_line_limit("concurrent_calls") is True


async def test_a_429_over_the_line_limit_is_refused_at_once_as_lines_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return _throttled("concurrency")

    async def _no_sleep(_: float) -> None:
        raise AssertionError("a line limit must not be waited out inside the ladder")

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _no_sleep)
    async with httpx.AsyncClient(
        base_url="https://carrier.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ProblemError) as raised:
            await vendor_request(client, "POST", "/Call/", engine="vobiz", route="/Call/", json={})
    assert raised.value.code == LINES_BUSY_RULE
    assert dial_was_not_placed(raised.value) is True
    assert len(sent) == 1


async def test_a_429_over_the_per_second_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [_throttled("cps"), httpx.Response(200, json={"request_uuid": "vz-1"})]

    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)
    async with httpx.AsyncClient(
        base_url="https://carrier.test", transport=httpx.MockTransport(lambda _: answers.pop(0))
    ) as client:
        body = await vendor_request(
            client, "POST", "/Call/", engine="vobiz", route="/Call/", json={}
        )
    assert body == {"request_uuid": "vz-1"}


# --- the count, against the database ---------------------------------------------------


@pytest.fixture
async def _settle_rows() -> AsyncIterator[None]:
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    "WHERE status IN ('queued', 'ringing', 'in_progress')"
                )
            )
    _TENANTS.clear()


async def _routed_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = uuid7(), uuid7()
    _TENANTS.append(tenant_id)
    ref = f"lines-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Line Motors', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": ref},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, 'Lines', "
                "'both', 'Idi AI assistant.', 'Idi AI assistant.', 'This call is being "
                "recorded.', 'I keep a short note of what you ask about.', 'live', 'pipecat', "
                ":ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": ref},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('pipecat', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    direction: str,
    status: str,
    carrier: str | None,
    age: timedelta = timedelta(0),
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "carrier, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, :dir, :st, "
                ":carrier, now() - :age, now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"lines:{uuid.uuid4().hex}",
                "dir": direction,
                "st": status,
                "carrier": carrier,
                "age": age,
            },
        )


async def test_lines_in_use_count_both_directions_and_age_out(_settle_rows: None) -> None:
    before = await carrier_lines_in_use(carrier="vobiz")
    tenant_id, agent_id = await _routed_tenant()
    counted = [
        {"direction": "outbound", "status": "queued", "carrier": "vobiz"},
        {"direction": "outbound", "status": "ringing", "carrier": "vobiz"},
        {"direction": "inbound", "status": "in_progress", "carrier": "vobiz"},
        # The worker writes an inbound row before any callback names its carrier.
        {"direction": "inbound", "status": "in_progress", "carrier": None},
    ]
    not_counted = [
        {"direction": "outbound", "status": "queued", "carrier": "plivo"},
        {"direction": "outbound", "status": "in_progress", "carrier": None},
        {"direction": "outbound", "status": "completed", "carrier": "vobiz"},
        {
            "direction": "outbound",
            "status": "queued",
            "carrier": "vobiz",
            "age": RING_LINE_HORIZON + timedelta(minutes=1),
        },
        {
            "direction": "inbound",
            "status": "in_progress",
            "carrier": "vobiz",
            "age": LIVE_LINE_HORIZON + timedelta(minutes=1),
        },
    ]
    for row in counted + not_counted:
        await _call(tenant_id, agent_id, **row)

    assert await carrier_lines_in_use(carrier="vobiz") - before == len(counted)


async def test_the_count_leaves_the_callers_tenant_as_it_found_it(_settle_rows: None) -> None:
    tenant_id, _ = await _routed_tenant()
    async with tenant_session(tenant_id) as session:
        await agents_service._count_carrier_lines(session, carrier="vobiz")
        scoped = (
            await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
        ).scalar_one()
    assert scoped == str(tenant_id)


async def test_a_full_pool_refuses_the_dial_before_its_row_exists(
    monkeypatch: pytest.MonkeyPatch, lines: None
) -> None:
    async def _full(*_: Any, **__: Any) -> int:
        return 2

    monkeypatch.setattr(agents_service, "_count_carrier_lines", _full)
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await agents_service._hold_carrier_line(session, carrier="vobiz")
    assert raised.value.code == LINES_BUSY_RULE

    async def _one_free(*_: Any, **__: Any) -> int:
        return 1

    monkeypatch.setattr(agents_service, "_count_carrier_lines", _one_free)
    async with untenanted_session() as session:
        await agents_service._hold_carrier_line(session, carrier="vobiz")


async def test_dispatch_call_holds_the_carrier_line_before_writing_its_row(
    monkeypatch: pytest.MonkeyPatch, lines: None
) -> None:
    """The line check is wired into the one outbound entry point: a full carrier pool
    refuses the dial with nothing written, so no `queued` row holds a line for an hour."""
    reset_engine_cache()
    tenant_id, agent_id = await _dialable_tenant()

    async def _slot() -> float:
        return 0.0

    async def _full(*_: Any, **__: Any) -> int:
        return 2

    monkeypatch.setattr(agents_service, "outbound_carrier", lambda: "vobiz")
    monkeypatch.setattr(agents_service, "await_dial_slot", _slot)
    monkeypatch.setattr(agents_service, "_count_carrier_lines", _full)
    phone = f"+9198766{uuid.uuid4().int % 10**5:05d}"
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await agents_service.dispatch_call(
                session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=phone
            )
    assert raised.value.code == LINES_BUSY_RULE
    assert dial_was_not_placed(raised.value) is True
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE to_e164 = :p"), {"p": phone}
            )
        ).scalar_one()
    assert rows == 0


def test_the_horizons_follow_the_ring_timeout_and_the_call_cap() -> None:
    from apps.api.agents.models import CALL_CAP_MAX_S
    from apps.api.engine.carrier import RING_TIMEOUT_S

    assert timedelta(seconds=RING_TIMEOUT_S) < RING_LINE_HORIZON
    assert timedelta(seconds=CALL_CAP_MAX_S) < LIVE_LINE_HORIZON
    assert carrier_pacing.CARRIER_LINES_LOCK_KEY < 2**63
