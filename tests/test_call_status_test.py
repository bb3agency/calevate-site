"""Following a test call from the dashboard card (D-885): the placed call's id and the number
it rings from, today's test calls, and one call's live status read from the engine while our
row is silent. Tenant isolation is the route's: another account's call is not found."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import test_call_reads, trial_calls
from apps.api.campaigns import engine_numbers
from apps.api.compliance import service as compliance_service
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.crm import live_calls
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from calevate_shared.engine import ExecutionSnapshot
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.first_run_test import _owner
from tests.trial_test_calls_test import TRIAL_NUMBER, _trial_tenant

pytestmark = [pytest.mark.rls]


@pytest.fixture
async def placing(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[UUID]]:
    tenants: list[UUID] = []
    monkeypatch.setattr(trial_calls, "trial_calling_ready", lambda: True)
    monkeypatch.setattr(get_settings(), "trial_caller_number", TRIAL_NUMBER)
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: True)

    async def _lend(agent_ref: str) -> bool:
        return True

    monkeypatch.setattr(engine_numbers, "lend_trial_line", _lend)
    yield tenants
    # The trial line is platform-wide: end every test call placed here.
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET status = 'completed' WHERE tenant_id = :t AND trial_call"),
                {"t": tenant_id},
            )


_INSERTED: list[tuple[UUID, UUID]] = []


@pytest.fixture(autouse=True)
async def _end_inserted_calls() -> AsyncIterator[None]:
    """A live trial row holds the platform's one trial line, so every one written here is
    ended afterwards or a later test finds the line busy."""
    yield
    while _INSERTED:
        tenant_id, call_id = _INSERTED.pop()
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET status = 'completed' WHERE id = :id"), {"id": call_id}
            )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    status: str,
    test: bool = True,
    handle: str | None = None,
    placed: datetime | None = None,
) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "trial_call, status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'outbound', '+919876543210', :test, :status, :at, :at)"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": handle or f"out_{uuid.uuid4().hex}",
                "test": test,
                "status": status,
                "at": placed or datetime.now(UTC),
            },
        )
    _INSERTED.append((tenant_id, call_id))
    return call_id


class _Engine:
    def __init__(self, snapshot: ExecutionSnapshot | None = None, fail: bool = False) -> None:
        self.snapshot = snapshot
        self.fail = fail
        self.asked: list[str] = []

    async def get_execution(self, handle: str) -> ExecutionSnapshot:
        self.asked.append(handle)
        if self.fail or self.snapshot is None:
            raise ProblemError(kind="dependency", code="engine_rejected", title="no", detail="no")
        return self.snapshot


def _snapshot(status: Any, *, terminal: bool = False, **kwargs: Any) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id="out_x",
        status=status,
        raw_status=status,
        terminal=terminal,
        billable_ready=False,
        **kwargs,
    )


# --- placing ----------------------------------------------------------------------------


async def test_a_placed_test_call_names_our_call_and_the_number_it_rings_from(
    placing: list[UUID],
) -> None:
    tenant_id, agent_id = await _trial_tenant()
    placing.append(tenant_id)
    principal = Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
    key = str(uuid.uuid4())
    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=key,
        )
    assert placed.status == "queued"
    assert placed.caller_number == TRIAL_NUMBER
    assert placed.call_id is not None
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT trial_call FROM calls WHERE id = :id"), {"id": placed.call_id}
            )
        ).one()
    assert row[0] is True, "the id is the test call's own row"
    async with tenant_session(tenant_id) as session:
        followed = await test_call_reads.read_test_call(
            session, tenant_id=tenant_id, call_id=placed.call_id
        )
    assert followed.caller_number == TRIAL_NUMBER, "the row says where it rings from while it rings"
    async with tenant_session(tenant_id) as session:
        again = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=key,
        )
    assert again == placed, "a replay answers with the same id and number"


def test_an_answer_stored_before_the_id_existed_still_replays() -> None:
    old = {"status": "queued", "call_handle": "out_1", "blocked_reason": None, "blocked_rule": None}
    replayed = trial_calls.TrialCallResult.from_payload(old)
    assert replayed.status == "queued" and replayed.call_id is None
    assert replayed.caller_number is None


# --- the list -----------------------------------------------------------------------------


async def test_todays_test_calls_are_listed_newest_first_and_nothing_else() -> None:
    tenant_id, agent_id = await _trial_tenant()
    other_tenant, other_agent = await _trial_tenant()
    now = datetime.now(UTC)
    await _call(tenant_id, agent_id, status="completed", placed=now - timedelta(days=2))
    await _call(tenant_id, agent_id, status="completed", test=False, placed=now)
    for minutes in (40, 30, 20, 10):
        await _call(
            tenant_id, agent_id, status="no_answer", placed=now - timedelta(minutes=minutes)
        )
    newest = await _call(tenant_id, agent_id, status="queued", placed=now - timedelta(minutes=1))
    await _call(other_tenant, other_agent, status="completed", placed=now)

    headers = await _owner(tenant_id)
    async with _client() as http:
        listed = await http.get("/v1/trial/calls", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) == test_call_reads.RECENT_TEST_CALLS
    assert body[0]["id"] == str(newest), "a call still ringing comes first"
    assert body[0]["agent_name"] == "Test caller"
    assert all(UUID(row["agent_id"]) == agent_id for row in body)
    assert "to_e164" not in body[0] and "caller_e164" not in body[0]


# --- one call ----------------------------------------------------------------------------


async def test_another_accounts_test_call_and_an_ordinary_call_are_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_calls, "get_engine", lambda: _Engine())
    tenant_id, agent_id = await _trial_tenant()
    other_tenant, other_agent = await _trial_tenant()
    theirs = await _call(other_tenant, other_agent, status="completed")
    ordinary = await _call(tenant_id, agent_id, status="completed", test=False)
    headers = await _owner(tenant_id)
    async with _client() as http:
        for call_id in (theirs, ordinary):
            answer = await http.get(f"/v1/trial/calls/{call_id}", headers=headers)
            assert answer.status_code == 404, answer.text


async def test_a_live_row_reads_the_engines_status(monkeypatch: pytest.MonkeyPatch) -> None:
    started = datetime.now(UTC) - timedelta(seconds=20)
    engine = _Engine(_snapshot("in_progress", started_at=started))
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)
    tenant_id, agent_id = await _trial_tenant()
    handle = f"out_live_{uuid.uuid4().hex}"
    call_id = await _call(tenant_id, agent_id, status="queued", handle=handle)
    async with tenant_session(tenant_id) as session:
        out = await test_call_reads.read_test_call(session, tenant_id=tenant_id, call_id=call_id)
    assert engine.asked == [handle]
    assert out.status == "in_progress" and out.status_source == "engine"
    assert out.started_at == started


async def test_an_ended_call_the_row_has_not_heard_of_yet_takes_the_engines_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine(_snapshot("busy", terminal=True, duration_s=0))
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)
    tenant_id, agent_id = await _trial_tenant()
    call_id = await _call(tenant_id, agent_id, status="queued")
    async with tenant_session(tenant_id) as session:
        out = await test_call_reads.read_test_call(session, tenant_id=tenant_id, call_id=call_id)
    assert out.status == "busy" and out.duration_s == 0


@pytest.mark.parametrize(
    ("status", "handle", "age"),
    [
        ("completed", None, timedelta(0)),
        ("queued", "local:", timedelta(0)),
        ("queued", None, timedelta(hours=3)),
    ],
    ids=["ended", "dial-unconfirmed", "past-the-live-horizon"],
)
async def test_the_engine_is_asked_only_about_a_young_confirmed_live_call(
    monkeypatch: pytest.MonkeyPatch, status: str, handle: str | None, age: timedelta
) -> None:
    engine = _Engine(_snapshot("ringing"))
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)
    tenant_id, agent_id = await _trial_tenant()
    unique = f"{handle}{uuid.uuid4().hex}" if handle else None
    call_id = await _call(
        tenant_id, agent_id, status=status, handle=unique, placed=datetime.now(UTC) - age
    )
    async with tenant_session(tenant_id) as session:
        out = await test_call_reads.read_test_call(session, tenant_id=tenant_id, call_id=call_id)
    assert engine.asked == []
    assert out.status == status and out.status_source == "call"


async def test_an_engine_that_cannot_answer_leaves_the_rows_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine(fail=True)
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)
    tenant_id, agent_id = await _trial_tenant()
    call_id = await _call(tenant_id, agent_id, status="queued")
    headers = await _owner(tenant_id)
    async with _client() as http:
        answer = await http.get(f"/v1/trial/calls/{call_id}", headers=headers)
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "queued"
    assert answer.json()["status_source"] == "call"
    assert len(engine.asked) == 1
