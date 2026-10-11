"""The healer forwards a broken agent's numbers to the client's own phone (D-743), forwarded
minutes are costed at the standard rate, and an in-call action from an unexpected address is
served with one alarm.

ThinnestAI's number forward (`PATCH /phone-numbers/{number} {forwardTo}`) rings the phone
before any agent speaks and works whether or not the agent answers; it is billed per
connected minute at the standard voice rate (docs.thinnest.ai channels/phone-numbers
"Forwarding a whole line", read 11 Oct 2026).

SHARED DATABASE DISCIPLINE: every row is minted here and every assertion is scoped to it.
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents import service as agents_service
from apps.api.billing.engine_minutes import (
    FORWARDED_RATE_KEY,
    attest_engine_minute_price,
    engine_minute_cost,
)
from apps.api.campaigns import engine_numbers
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.api.worker import engine_actions
from sqlalchemy import text
from starlette.requests import Request
from tests.smoke_pipeline_test import _seed_tenant

FALLBACK = "+919812345678"


class Numbers:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.refuse: str | None = None
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def hold(self, number: str) -> None:
        self.rows[number] = {
            "number": number,
            "source": "rented",
            "agent": None,
            "callingAgent": None,
            "forwardTo": None,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        number = request.url.path.removeprefix("/api/v1/phone-numbers/")
        row = self.rows[number]
        if request.method == "PATCH":
            body = json.loads(request.content)
            self.patches.append((number, body))
            if self.refuse and body.get("forwardTo"):
                return httpx.Response(409, json={"error": "No.", "code": self.refuse})
            row.update(body)
        return httpx.Response(200, json=row)


@pytest.fixture
def numbers(monkeypatch: pytest.MonkeyPatch) -> Iterator[Numbers]:
    fake = Numbers()
    set_thinnest_numbers(
        ThinnestNumbers(
            api_key="ta_live_test",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handler),
                base_url="https://app.thinnest.ai/api/v1",
            ),
        )
    )
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    monkeypatch.setattr(get_settings(), "trial_caller_number", None)
    yield fake
    set_thinnest_numbers(None)


@dataclass
class _Caps:
    records_audio: bool = True

    def has(self, name: str) -> bool:
        return name == "script_override"


@dataclass
class _PausingEngine:
    capabilities: _Caps = field(default_factory=_Caps)
    paused: list[str] = field(default_factory=list)

    async def override_call_script(self, ref: str, **_: Any) -> None:
        self.paused.append(ref)


async def _agent_with_number(numbers: Numbers) -> tuple[uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fwd_{uuid.uuid4().hex[:10]}")
    number = f"9180{secrets.randbelow(10**8):08d}"
    numbers.hold(number)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET engine = 'thinnest', engine_agent_ref = :r, status = 'live', "
                "direction = 'inbound' WHERE id = :a"
            ),
            {"r": f"ag_{uuid.uuid4()}", "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, agent_id, provider, "
                "direction, engine_number_ref, engine_owned, created_at, updated_at) VALUES "
                "(:id, :tid, :e164, 'standard', :aid, 'thinnest', 'inbound', :ref, true, "
                "now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "e164": f"+{number}",
                "aid": agent_id,
                "ref": number,
            },
        )
    return tenant_id, agent_id, number


async def test_a_broken_line_is_paused_and_its_number_forwarded_then_cleared(
    numbers: Numbers,
) -> None:
    tenant_id, agent_id, number = await _agent_with_number(numbers)
    engine = _PausingEngine()
    async with tenant_session(tenant_id) as session:
        held = await agents_service.apply_healer_silence(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, forward_to=FALLBACK
        )
    assert held == "forwarded"
    assert len(engine.paused) == 1
    assert numbers.rows[number]["forwardTo"] == FALLBACK
    # A second hold (a republish re-applying it) sends nothing new.
    async with tenant_session(tenant_id) as session:
        await engine_numbers.forward_agent_numbers(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=FALLBACK
        )
    assert len(numbers.patches) == 1
    async with tenant_session(tenant_id) as session:
        cleared = await engine_numbers.clear_agent_forwards(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
    assert cleared == 1 and numbers.rows[number]["forwardTo"] is None


async def test_a_refused_forward_alarms_and_the_line_stays_paused(
    numbers: Numbers, monkeypatch: pytest.MonkeyPatch
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(engine_numbers, "alert", lambda _s, code, **_k: raised.append(code))
    numbers.refuse = "forward_destination_not_allowed"
    tenant_id, agent_id, number = await _agent_with_number(numbers)
    engine = _PausingEngine()
    async with tenant_session(tenant_id) as session:
        held = await agents_service.apply_healer_silence(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, forward_to="+919000000001"
        )
    assert held == "paused" and engine.paused
    assert raised == ["healer_forward_refused"]
    assert numbers.rows[number]["forwardTo"] is None


def test_a_forwarded_call_object_is_read_as_forwarded() -> None:
    engine = ThinnestEngine(api_key="ta_x")
    snap = engine.snapshot_from_delivery(
        {"data": {"id": "out_1", "status": "completed", "forwardedTo": "+919812345678"}}
    )
    plain = engine.snapshot_from_delivery({"data": {"id": "out_2", "status": "completed"}})
    assert snap.forwarded and not plain.forwarded


async def test_a_forwarded_minute_costs_the_standard_rate_and_keeps_the_clients_rung() -> None:
    actor = uuid.uuid4()
    at = datetime(2002, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": actor},
        )
        for key, inr in (("platform", "2.50"), (FORWARDED_RATE_KEY, "2.00")):
            await attest_engine_minute_price(
                session,
                engine="thinnest",
                rate_key=key,
                inr_per_min=Decimal(inr),
                effective_from=at,
                source_note="test",
                actor_id=actor,
            )
    tenant_id, _agent = await _seed_tenant(f"fwdcost_{uuid.uuid4().hex[:10]}")
    async with tenant_session(tenant_id) as session:
        priced = await engine_minute_cost(
            session,
            engine="thinnest",
            tenant_id=tenant_id,
            call_id=uuid7(),
            seconds=Decimal(60),
            at=at,
            forwarded=True,
        )
    assert priced.rate_key == FORWARDED_RATE_KEY and priced.inr_per_min == Decimal("2.00")
    assert priced.client_rate_key == "platform"


# --- the soft source-address check -------------------------------------------------------


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("10.0.0.1", 1)})


def test_an_unexpected_source_is_served_and_alarmed_once_a_known_one_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(engine_actions, "alert", lambda _s, code, **_k: raised.append(code))
    route = engine_actions.ActionRoute(tenant_id=uuid.uuid4(), agent_id=uuid.uuid4())
    monkeypatch.setattr(engine_actions, "client_request_ip", lambda _r: "34.47.220.98")
    engine_actions.note_action_source(_request(), route)
    assert raised == []
    monkeypatch.setattr(engine_actions, "client_request_ip", lambda _r: "203.0.113.9")
    engine_actions.note_action_source(_request(), route)
    assert raised == ["engine_action_source_unexpected"]
    # An address the edge cannot vouch for is not compared.
    monkeypatch.setattr(engine_actions, "client_request_ip", lambda _r: None)
    engine_actions.note_action_source(_request(), route)
    assert raised == ["engine_action_source_unexpected"]


def test_the_list_comes_from_the_live_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    raised: list[str] = []
    monkeypatch.setattr(engine_actions, "alert", lambda _s, code, **_k: raised.append(code))
    monkeypatch.setattr(get_settings(), "thinnest_action_source_ips", "34.47.220.98, 203.0.113.9")
    monkeypatch.setattr(engine_actions, "client_request_ip", lambda _r: "203.0.113.9")
    route = engine_actions.ActionRoute(tenant_id=uuid.uuid4(), agent_id=uuid.uuid4())
    engine_actions.note_action_source(_request(), route)
    assert raised == []
