"""A number moves into its client's own ThinnestAI workspace, keeping its digits, instead of
being released and bought again (`POST /phone-numbers/{number}/move`, docs.thinnest.ai
api-reference/phone-numbers/move-phone-number, read 11 Oct 2026): it arrives answered by
nobody and is re-attached; a refusal is told plainly; a number on a call is tried again.
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import engine_numbers
from apps.api.campaigns.number_pricing import record_attested_price_inr
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.workers import number_moves
from sqlalchemy import text
from tests.workspace_support import give_own_workspace

WORKSPACE_HEADER = "Thinnest-Workspace"


async def _admin() -> uuid.UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _client_with_agent() -> tuple[uuid.UUID, uuid.UUID, str]:
    created = await admin_service.create_organization(
        name="Moving Numbers",
        slug=f"mv-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET engine = 'thinnest', engine_agent_ref = :r, status = 'live', "
                "direction = 'inbound' WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    return tenant_id, agent_id, ref


class MovingVendor:
    """Numbers per workspace, and the move between them."""

    def __init__(self) -> None:
        #: workspace (None = developer) -> number -> row
        self.held: dict[str | None, dict[str, dict[str, Any]]] = {None: {}}
        self.moves: list[tuple[str | None, str, str]] = []
        self.refuse: str | None = None
        self.on_call_times = 0

    def hold(self, number: str, workspace: str | None = None) -> None:
        self.held.setdefault(workspace, {})[number] = {
            "number": number,
            "source": "rented",
            "agent": "ag_old",
            "callingAgent": None,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        ws = request.headers.get(WORKSPACE_HEADER)
        path = request.url.path.removeprefix("/api/v1/phone-numbers/")
        if path.endswith("/move"):
            number = path.removesuffix("/move")
            target = json.loads(request.content)["toWorkspace"]
            if self.on_call_times:
                self.on_call_times -= 1
                return httpx.Response(
                    409, json={"error": "On a call.", "code": "number_on_live_call"}
                )
            if self.refuse:
                return httpx.Response(409, json={"error": "No.", "code": self.refuse})
            row = self.held.get(ws, {}).pop(number, None)
            if row is None:
                return httpx.Response(404, json={"error": "Not found.", "code": "not_found"})
            row.update(agent=None, callingAgent=None)
            self.held.setdefault(target, {})[number] = row
            self.moves.append((ws, number, target))
            return httpx.Response(
                200,
                json={
                    "number": number,
                    "source": "rented",
                    "from": ws or "org_dev",
                    "to": target,
                    "paidThrough": "2026-10",
                },
            )
        row = self.held.get(ws, {}).get(path)
        if row is None:
            return httpx.Response(404, json={"error": "Not found.", "code": "not_found"})
        if request.method == "PATCH":
            row.update(json.loads(request.content))
        return httpx.Response(200, json=row)


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Iterator[MovingVendor]:
    fake = MovingVendor()
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
    try:
        yield fake
    finally:
        set_thinnest_numbers(None)


async def _platform_held_number(
    vendor: MovingVendor,
) -> tuple[uuid.UUID, uuid.UUID, str, str, str]:
    """A client whose agent lives in its own workspace, and a number recorded for it that
    is still held in the platform account."""
    tenant_id, agent_id, ref = await _client_with_agent()
    workspace = await give_own_workspace(tenant_id, business_status="accepted", can_rent=True)
    scoped = f"{ref}@{workspace}"
    number = f"9180{secrets.randbelow(10**8):08d}"
    vendor.hold(number)
    number_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": scoped, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, agent_id, provider, "
                "direction, engine_number_ref, engine_owned, created_at, updated_at) VALUES "
                "(:id, :tid, :e164, 'standard', :aid, 'thinnest', 'inbound', :ref, true, "
                "now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "e164": f"+{number}",
                "aid": agent_id,
                "ref": number,
            },
        )
    return tenant_id, number_id, number, workspace, scoped


async def _held_ref(tenant_id: uuid.UUID, number_id: uuid.UUID) -> tuple[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_number_ref, client_inr_per_month FROM phone_numbers "
                    "WHERE id = :id"
                ),
                {"id": number_id},
            )
        ).one()
    return str(row[0]), row[1]


async def test_a_platform_held_number_moves_keeps_its_digits_and_answers_the_agent(
    vendor: MovingVendor,
) -> None:
    admin_id = await _admin()
    async with untenanted_session() as session:
        await record_attested_price_inr(
            session, inr_per_month=Decimal("499.00"), source="test", attested_by=admin_id
        )
    tenant_id, number_id, number, workspace, scoped = await _platform_held_number(vendor)
    async with tenant_session(tenant_id) as session:
        moved = await engine_numbers.move_into_client_workspace(
            session, tenant_id=tenant_id, number_id=number_id
        )
    assert moved == f"{number}@{workspace}"
    assert vendor.moves == [(None, number, workspace)]
    ref, price = await _held_ref(tenant_id, number_id)
    assert ref == moved and price == Decimal("499.00")
    # It arrived answered by nobody and is pointed at the client's agent again.
    assert vendor.held[workspace][number]["agent"] == scoped.split("@")[0]


async def test_a_number_already_in_the_clients_workspace_is_left_alone(
    vendor: MovingVendor,
) -> None:
    tenant_id, number_id, number, workspace, _scoped = await _platform_held_number(vendor)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET engine_number_ref = :r WHERE id = :id"),
            {"r": f"{number}@{workspace}", "id": number_id},
        )
        assert (
            await engine_numbers.move_into_client_workspace(
                session, tenant_id=tenant_id, number_id=number_id
            )
            == f"{number}@{workspace}"
        )
    assert vendor.moves == []


async def test_unapproved_business_details_are_refused_in_plain_words(
    vendor: MovingVendor,
) -> None:
    vendor.refuse = "number_move_needs_business_details"
    tenant_id, number_id, number, _workspace, _scoped = await _platform_held_number(vendor)
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await engine_numbers.move_into_client_workspace(
                session, tenant_id=tenant_id, number_id=number_id
            )
    assert refused.value.code == "engine_number_move_needs_business_details"
    assert (await _held_ref(tenant_id, number_id))[0] == number


async def test_a_number_on_a_call_is_tried_again_and_then_moves(
    vendor: MovingVendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[int] = []

    async def queue(_tenant: uuid.UUID, _number: uuid.UUID, *, attempt: int) -> None:
        queued.append(attempt)

    monkeypatch.setattr(number_moves, "queue_number_move", queue)
    vendor.on_call_times = 1
    tenant_id, number_id, number, workspace, _scoped = await _platform_held_number(vendor)
    payload = {"tenant_id": str(tenant_id), "number_id": str(number_id), "attempt": 1}
    assert await number_moves.move_engine_number({}, payload) == "deferred"
    assert queued == [2]
    assert await number_moves.move_engine_number({}, {**payload, "attempt": 2}) == "moved"
    assert (await _held_ref(tenant_id, number_id))[0] == f"{number}@{workspace}"


async def test_a_move_that_never_clears_alarms_once_its_attempts_run_out(
    vendor: MovingVendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(number_moves, "alert", lambda _stage, code, **_kw: raised.append(code))
    vendor.on_call_times = 99
    tenant_id, number_id, _number, _workspace, _scoped = await _platform_held_number(vendor)
    payload = {
        "tenant_id": str(tenant_id),
        "number_id": str(number_id),
        "attempt": engine_numbers.MOVE_ATTEMPTS,
    }
    assert await number_moves.move_engine_number({}, payload) == "failed"
    assert raised == ["engine_number_move_failed"]


async def test_the_shared_trial_number_never_moves(
    vendor: MovingVendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, number_id, number, _workspace, _scoped = await _platform_held_number(vendor)
    monkeypatch.setattr(get_settings(), "trial_caller_number", f"+{number}")
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await engine_numbers.move_into_client_workspace(
                session, tenant_id=tenant_id, number_id=number_id
            )
    assert refused.value.code == "engine_number_is_trial_number"
    assert vendor.moves == []
