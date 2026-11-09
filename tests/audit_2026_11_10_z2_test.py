"""Backend audit round 5, lane Z2 (outbound), 10 Nov 2026.

Z2-01: a dial in flight when the big red switch is thrown, or when its number is
suppressed, is a `local:` placeholder until `_confirm_dial` stamps the vendor's handle, and
both recalls scan only stamped dials. `dispatch_call` now asks again once the handle is
committed and hands the dial to the recall that missed it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.agents import service as agents_service
from apps.api.compliance import dnc
from apps.api.compliance.dnc_recall import DNC_RECALL_JOB
from apps.api.compliance.service import check_dispatch
from apps.api.core import loadshed
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.api.ingest.service import normalize_phone
from apps.api.ops import halt as halt_switch
from apps.workers import dnc_recall
from calevate_shared.engine import CallContext, RecallOutcome
from sqlalchemy import text

# Settles the `queued` rows these dials leave, as in the file the fixture comes from.
from tests.dial_intent_confirm_test import (
    _TENANTS,
    _dialable_tenant,
    _settle_what_this_module_started,  # noqa: F401
)
from tests.dnc_national_dialling_form_test import _dialable_tenant as _armed_tenant


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture
async def _release_halt() -> AsyncIterator[None]:
    yield
    await loadshed.set_platform_status(outbound_halted=False, actor_id=None)


def _dial_that_meanwhile(action: Any, handle: str) -> Any:
    """An engine whose `POST /calls` round trip is where something else happens."""

    async def start_outbound_call(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        await action()
        return handle

    return start_outbound_call


async def _recall_rows(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": DNC_RECALL_JOB, "tid": str(tenant_id)},
            )
        ).all()
    return [dict(r[0]) for r in rows]


class _StopEngine:
    name = "fake"

    def __init__(self) -> None:
        self.stopped: list[str] = []

    def holds_credentials(self) -> bool:
        return True

    async def end_call(self, call_id: str) -> RecallOutcome:
        self.stopped.append(call_id)
        return RecallOutcome.PREVENTED


async def test_a_number_suppressed_while_its_dial_was_in_flight_is_recalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suppression lands, and its own recall scans, during the `POST /calls` round
    trip: the row is still `local:` so that scan cannot see it. After the dial returns,
    the dial must still reach the DNC recall and be stopped."""
    tenant_id, agent_id = await _dialable_tenant()
    # The route a publish writes: the recall's scan walks the tenants that have one.
    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) SELECT 'fake', engine_agent_ref, tenant_id, "
                "id, true, now(), now() FROM agents WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    phone = "+919876771001"
    handle = f"fakecall_z2dnc_{uuid.uuid4().hex[:12]}"

    async def suppress() -> None:
        # The entry as `add_to_dnc` writes it, with its recall already run and gone: the
        # outbox row it queued is not written here, so only a later enqueue can be found.
        async with tenant_session(tenant_id) as s:
            await s.execute(
                text(
                    "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, "
                    "added_at, created_at) VALUES (gen_random_uuid(), :tid, :p, 'tenant', "
                    "'call_optout', now(), now())"
                ),
                {"tid": tenant_id, "p": phone},
            )

    monkeypatch.setattr(FakeEngine, "start_outbound_call", _dial_that_meanwhile(suppress, handle))
    async with tenant_session(tenant_id) as session:
        returned = await agents_service.dispatch_call(
            session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=phone
        )
    assert returned == handle

    recalls = await _recall_rows(tenant_id)
    assert [r["phones"] for r in recalls] == [[phone]], recalls

    engine = _StopEngine()
    monkeypatch.setattr(dnc_recall, "get_engine", lambda: engine)
    monkeypatch.setattr(dnc_recall, "alert", lambda *a, **kw: None)
    await dnc_recall.recall_dials_for_dnc({}, recalls[0])
    assert engine.stopped == [handle], "the dial to a suppressed number was left ringing"


async def test_a_halt_thrown_while_a_dial_was_in_flight_recalls_it(
    monkeypatch: pytest.MonkeyPatch, _release_halt: None
) -> None:
    """The big red switch is thrown, and its one-shot recall has scanned, while this dial
    was a placeholder. The dial must ask for the recall again once it has a handle."""
    tenant_id, agent_id = await _dialable_tenant()
    handle = f"fakecall_z2halt_{uuid.uuid4().hex[:12]}"
    queued: list[str] = []
    monkeypatch.setattr(halt_switch, "enqueue", lambda job: _note(queued, job))

    async def halt() -> None:
        await loadshed.set_platform_status(
            outbound_halted=True, halt_reason="z2 test", actor_id=None
        )

    monkeypatch.setattr(FakeEngine, "start_outbound_call", _dial_that_meanwhile(halt, handle))
    async with tenant_session(tenant_id) as session:
        await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164="+919876771002",
        )
    assert queued == [halt_switch.DIAL_RECALL_JOB], (
        "a dial accepted after the halt was never handed to its recall"
    )


async def test_an_ordinary_dial_asks_for_no_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _dialable_tenant()
    queued: list[str] = []
    monkeypatch.setattr(halt_switch, "enqueue", lambda job: _note(queued, job))
    async with tenant_session(tenant_id) as session:
        await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164="+919876771003",
        )
    assert queued == []
    assert await _recall_rows(tenant_id) == []


async def _note(into: list[str], job: str) -> None:
    into.append(job)


__all__ = ["_TENANTS"]


# --- Z2-02: `+91 (0) …`, country code and trunk prefix together --------------


def test_a_number_written_with_country_code_and_trunk_prefix_is_the_same_number() -> None:
    assert normalize_phone("+91 (0) 98765 43210") == "+919876543210"
    assert normalize_phone("+91-0-9876543210") == "+919876543210"
    assert normalize_phone("91 0 98765 43210") == "+919876543210"
    # Without the `+`, a 0 after 91 in front of a shape that is not a mobile stays unreadable.
    assert normalize_phone("91 0 58765 43210") is None


async def test_a_suppression_typed_with_the_trunk_prefix_stops_the_real_number() -> None:
    tenant_id, agent_id = await _armed_tenant()
    ten = "9" + f"{uuid.uuid4().int % 10**9:09d}"
    e164 = "+91" + ten
    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(
            session,
            tenant_id=tenant_id,
            raw_numbers=[f"+91 (0) {ten[:5]} {ten[5:]}"],
            source="manual",
        )
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=e164
        )
    assert decision.rule == "dnc", decision
