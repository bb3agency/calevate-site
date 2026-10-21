"""The healer forwards a broken agent's numbers to the client's own phone (D-743), forwarded
calls are costed at the plan they were admitted at (D-835), and an in-call action from an
unexpected address is served with one alarm.

ThinnestAI's number forward (`PATCH /phone-numbers/{number} {forwardTo}`) rings the phone
before any agent speaks and works whether or not the agent answers (docs.thinnest.ai
channels/phone-numbers "Forwarding a whole line", read 11 Oct 2026). It is billed every
connected second at the attached agent's plan, Standard with none attached, and nothing on a
brought number (snapshots/2026-10-19/pages/api-reference/calls/get-call.md:1249-1254).

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
    CARRIER_RATE_KEY,
    FORWARD_WITHOUT_AGENT_RATE_KEY,
    attest_engine_minute_price,
    engine_minute_cost,
)
from apps.api.campaigns import engine_numbers
from apps.api.core.settings import get_settings
from apps.api.crm.service import get_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.api.worker import engine_actions
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
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
    # A forward is never recorded and its recording route answers 404
    # (snapshots/2026-10-19/pages/channels/phone-numbers.md:577-579), so it is not fetched.
    assert engine.recording_source(snap) is None
    assert engine.recording_source(plain) is not None


async def _attest(at: datetime, prices: dict[str, str]) -> None:
    actor = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": actor},
        )
        for key, inr in prices.items():
            await attest_engine_minute_price(
                session,
                engine="thinnest",
                rate_key=key,
                inr_per_min=Decimal(inr),
                effective_from=at,
                source_note="test",
                actor_id=actor,
            )


async def _forwarded_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, rate_key: str | None, owned: bool | None
) -> uuid.UUID:
    """An inbound call to one of the client's numbers, the agent's route stamped with
    `rate_key` (none when None), the number recorded rented or brought (none when None)."""
    call_id = uuid7()
    ours = f"+9140{uuid.uuid4().int % 100_000_000:08d}"
    async with tenant_session(tenant_id) as session:
        if rate_key is not None:
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, engine_rate_key, created_at, updated_at) VALUES "
                    "('thinnest', :r, :t, :a, true, :k, now(), now())"
                ),
                {"r": f"fwd_{call_id.hex}", "t": tenant_id, "a": agent_id, "k": rate_key},
            )
        if owned is not None:
            await session.execute(
                text(
                    "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, engine_owned, "
                    "created_at, updated_at) VALUES (:id, :t, :a, :e, :o, now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": ours, "o": owned},
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, forwarded_to_phone, created_at, updated_at) VALUES "
                "(:id, :t, :a, :eid, 'inbound', :to, 'completed', true, now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "eid": f"fwd_{call_id}", "to": ours},
        )
    return call_id


async def _cost(tenant_id: uuid.UUID, call_id: uuid.UUID, at: datetime, seconds: int) -> Any:
    async with tenant_session(tenant_id) as session:
        return await engine_minute_cost(
            session,
            engine="thinnest",
            tenant_id=tenant_id,
            call_id=call_id,
            seconds=Decimal(seconds),
            at=at,
            forwarded=True,
        )


async def test_a_forward_on_a_rented_number_costs_the_attached_agents_plan() -> None:
    """A forward is billed every connected second at the plan it was admitted at: the voice
    plan of the agent attached to the number, or Standard when none is; it is not the
    carrier's fee (snapshots/2026-10-19/pages/api-reference/calls/get-call.md:1249-1254)."""
    at = datetime(2002, 1, 2, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    await _attest(at, {"premium": "2.50", "standard": "2.00", CARRIER_RATE_KEY: "0.38"})
    tenant_id, agent_id = await _seed_tenant(f"fwdcost_{uuid.uuid4().hex[:10]}")

    attached = await _cost(
        tenant_id,
        await _forwarded_call(tenant_id, agent_id, rate_key="premium", owned=True),
        at,
        61,
    )
    assert attached.rate_key == "premium" and attached.inr_per_min == Decimal("2.50")
    assert attached.billed_minutes == Decimal("1.5")
    fee = Decimal(1) + attached.topup_fee
    assert attached.cost.total_inr == (Decimal("3.75") * fee).quantize(Decimal("0.0001"))

    bare_tenant, bare_agent = await _seed_tenant(f"fwdbare_{uuid.uuid4().hex[:10]}")
    no_route = await _cost(
        bare_tenant,
        await _forwarded_call(bare_tenant, bare_agent, rate_key=None, owned=None),
        at,
        30,
    )
    assert no_route.rate_key == FORWARD_WITHOUT_AGENT_RATE_KEY == "standard"
    assert no_route.inr_per_min == Decimal("2.00")
    assert no_route.client_rate_key == "platform"


async def test_a_forward_on_a_brought_number_costs_nothing() -> None:
    """On a number the client brought nothing is charged; `billedSeconds` is null
    (get-call.md:1252-1254, update-phone-number.md:654-657)."""
    at = datetime(2002, 1, 3, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    await _attest(at, {"premium": "2.50"})
    tenant_id, agent_id = await _seed_tenant(f"fwdfree_{uuid.uuid4().hex[:10]}")
    call_id = await _forwarded_call(tenant_id, agent_id, rate_key="premium", owned=False)
    priced = await _cost(tenant_id, call_id, at, 90)
    assert priced.priced and priced.inr_per_min == Decimal(0)
    assert priced.cost.total_inr == Decimal(0) and priced.cost.platform_inr == Decimal(0)
    assert priced.billed_minutes == Decimal("1.5") and priced.client_rate_key == "premium"


@pytest.mark.parametrize(
    ("rate_key", "inr", "owned"),
    [
        ("byok_voice", "1.50", True),
        ("byok_llm_voice", "1.00", True),
        ("byok_voice", "1.50", False),
        ("byok_llm_voice", "1.00", False),
    ],
)
async def test_a_forward_on_an_own_key_agent_costs_its_key_sets_flat_price(
    rate_key: str, inr: str, owned: bool
) -> None:
    """A forward on an agent running on our own keys is billed at its key set's flat price,
    ₹1.00 for `llm_voice` and ₹1.50 for `voice`, although no key is used (ThinnestAI's email
    of 21 Oct 2026, §21.0, correcting D-835). On a brought number too: that case is open with
    the vendor, and the higher figure keeps the cost floor safe (D-847)."""
    at = datetime(2002, 1, 4, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    await _attest(at, {rate_key: inr})
    tenant_id, agent_id = await _seed_tenant(f"fwdown_{uuid.uuid4().hex[:10]}")
    call_id = await _forwarded_call(tenant_id, agent_id, rate_key=rate_key, owned=owned)
    priced = await _cost(tenant_id, call_id, at, 60)
    assert priced.rate_key == rate_key and priced.inr_per_min == Decimal(inr)
    fee = Decimal(1) + priced.topup_fee
    assert priced.cost.total_inr == (Decimal(inr) * fee).quantize(Decimal("0.0001"))


async def test_a_forwarded_call_is_marked_on_its_row_and_shown_as_forwarded() -> None:
    """The row says the call was forwarded, a later event that does not name the forward
    keeps the mark, and the call page reads it to say why there is no recording."""
    tenant_id, agent_id = await _seed_tenant(f"fwdrow_{uuid.uuid4().hex[:10]}")
    now = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"fwd_{uuid.uuid4().hex}",
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=40),
        ended_at=now,
        duration_s=40,
        forwarded=True,
    )
    call_id = await pipeline._upsert_call(tenant_id, agent_id, snapshot, None)
    later = snapshot.model_copy(update={"forwarded": False})
    assert await pipeline._upsert_call(tenant_id, agent_id, later, None) == call_id
    async with tenant_session(tenant_id) as session:
        detail = await get_call(session, call_id)
    assert detail.forwarded_to_phone is True and detail.has_recording is False


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
