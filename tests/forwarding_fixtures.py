"""Shared set-up for the forwarding tests (D-746): a client with a Calevate number, a fake
engine that places test legs, and the switches that keep the test off the network."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import engine_numbers
from apps.api.core.context import Principal
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.forwarding_test import ForwardingLegReport
from apps.api.forwarding import service, testing
from sqlalchemy import text

TRIAL_NUMBER = "+918000000501"
SECOND_NUMBER = "+918000000502"
CALEVATE_NUMBER_PREFIX = "+9180000"


async def make_client(prefix: str = "fwd") -> tuple[UUID, UUID, str]:
    created = await admin_service.create_organization(
        name="Forwarding Business",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"])), str(created["slug"])


async def give_calevate_number(tenant_id: UUID, agent_id: UUID) -> tuple[UUID, str]:
    number_id = uuid.uuid4()
    e164 = f"+9180{uuid.uuid4().int % 10**8:08d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "direction, engine_owned, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'standard', 'pending', 'inbound', true, now(), now())"
            ),
            {"id": number_id, "t": tenant_id, "a": agent_id, "e": e164},
        )
    return number_id, e164


def owner(tenant_id: UUID) -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")


def random_mobile() -> str:
    return f"+919{uuid.uuid4().int % 10**9:09d}"


async def add_line(
    tenant_id: UUID,
    *,
    number: str | None = None,
    mode: str = "conditional",
    ring_seconds: int = 20,
    line_kind: str = "mobile",
) -> service.LineView:
    async with tenant_session(tenant_id) as session:
        return await service.create_line(
            session,
            principal=owner(tenant_id),
            tenant_id=tenant_id,
            number=number or random_mobile(),
            line_kind=line_kind,
            carrier="airtel",
            mode=mode,
            ring_seconds=ring_seconds,
            calevate_number_id=None,
            attest=True,
            ip=None,
        )


@dataclass
class FakeForwarding:
    placed: list[tuple[str, str, str]] = field(default_factory=list)
    hung: list[str] = field(default_factory=list)
    reports: dict[str, ForwardingLegReport] = field(default_factory=dict)
    refuse_leg: int | None = None
    refuse_all: bool = False

    async def converge_forwarding_test_agent(self, leg: int) -> str:
        return f"fwd-agent-{leg}"

    async def place_forwarding_test_call(
        self, *, agent_ref: str, from_e164: str, to_e164: str, reference: str
    ) -> str:
        from apps.api.core.errors import ProblemError

        if self.refuse_all or (
            self.refuse_leg is not None and agent_ref.endswith(str(self.refuse_leg))
        ):
            raise ProblemError.business_rule("engine_call_refused", "refused", remediation="x")
        self.placed.append((agent_ref, from_e164, to_e164))
        return f"out_{reference}"

    async def read_forwarding_leg(self, handle: str) -> ForwardingLegReport:
        return self.reports.get(handle, ForwardingLegReport(ended=True, answered=True, seconds=20))

    async def hang_up_forwarding_leg(self, handle: str) -> None:
        self.hung.append(handle)


@dataclass
class Rig:
    engine: FakeForwarding
    enqueued: list[tuple[str, dict[str, Any]]]
    lent: list[tuple[str, str]]


@pytest.fixture(name="rig")
async def rig_fixture(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    engine = FakeForwarding()
    enqueued: list[tuple[str, dict[str, Any]]] = []
    lent: list[tuple[str, str]] = []
    monkeypatch.setattr(get_settings(), "trial_caller_number", TRIAL_NUMBER)
    monkeypatch.setattr(get_settings(), "forwarding_test_second_number", SECOND_NUMBER)
    monkeypatch.setattr(testing, "get_engine", lambda: engine)
    monkeypatch.setattr(testing, "forwarding_calls_ready", lambda: True)
    # Inside the test window, whatever the clock says.
    monkeypatch.setattr(
        testing, "ist_wall_clock", lambda _now: datetime(2026, 10, 11, 11, 0, tzinfo=UTC)
    )

    async def _enqueue(job: str, payload: dict[str, Any], **_: Any) -> str:
        enqueued.append((job, payload))
        return job

    async def _lend(number: str, agent_ref: str) -> bool:
        lent.append((number, agent_ref))
        return True

    monkeypatch.setattr(testing, "enqueue", _enqueue)
    monkeypatch.setattr(engine_numbers, "lend_platform_line", _lend)
    yield Rig(engine=engine, enqueued=enqueued, lent=lent)
    # The legs share the platform's one trial line: end any this test left live.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE forwarding_test_legs SET status = 'ended' "
                "WHERE status IN ('placing', 'live')"
            )
        )
