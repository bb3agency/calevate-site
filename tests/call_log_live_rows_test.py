"""Live calls in the call log (D-886): a call has its row from the dial, the log lists it
first while it runs, and `GET /v1/calls/live` says where each one stands, asking the engine
only about an outbound call still running. Another account's call is never answered."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.crm import live_calls
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.first_run_test import _owner
from tests.test_call_status_test import (
    _INSERTED,
    _call,
    _client,
    _end_inserted_calls,  # noqa: F401  (autouse: ends every live row written here)
    _Engine,
    _snapshot,
)
from tests.trial_test_calls_test import _trial_tenant

pytestmark = [pytest.mark.rls]


async def _ended(tenant_id: UUID, agent_id: UUID, *, started: datetime) -> UUID:
    call_id = await _call(tenant_id, agent_id, status="completed", test=False)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET started_at = :at, duration_s = 40 WHERE id = :id"),
            {"at": started, "id": call_id},
        )
    return call_id


async def _inbound_live(tenant_id: UUID, agent_id: UUID) -> UUID:
    """The row an in-call action writes for an inbound call (`worker/engine_actions`)."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'inbound', '+919876500000', 'in_progress', now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"in_{call_id.hex}"},
        )
    _INSERTED.append((tenant_id, call_id))
    return call_id


async def test_a_call_being_dialled_heads_the_log_and_a_silent_old_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_calls, "get_engine", lambda: _Engine())
    tenant_id, agent_id = await _trial_tenant()
    now = datetime.now(UTC)
    stale = await _call(tenant_id, agent_id, status="queued", placed=now - timedelta(hours=3))
    dialling = await _call(tenant_id, agent_id, status="queued", placed=now - timedelta(minutes=2))
    newer = await _ended(tenant_id, agent_id, started=now - timedelta(seconds=30))
    headers = await _owner(tenant_id)
    async with _client() as http:
        listed = await http.get("/v1/calls", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()}
    order = [row["id"] for row in listed.json()]
    assert order[0] == str(dialling), "a call still running comes first"
    assert order.index(str(newer)) < order.index(str(stale))
    assert rows[str(dialling)]["live_state"] == "live"
    assert rows[str(stale)]["live_state"] == "unreported"
    assert rows[str(newer)]["live_state"] is None


async def test_a_dated_view_holds_a_call_that_has_not_connected_yet() -> None:
    tenant_id, agent_id = await _trial_tenant()
    dialling = await _call(tenant_id, agent_id, status="queued")
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    headers = await _owner(tenant_id)
    async with _client() as http:
        dated = await http.get("/v1/calls", params={"since": since}, headers=headers)
        without_tests = await http.get("/v1/calls", params={"test_calls": "false"}, headers=headers)
    assert str(dialling) in [row["id"] for row in dated.json()]
    assert str(dialling) not in [row["id"] for row in without_tests.json()], (
        "Include test calls still decides whether a live test call is listed"
    )


async def test_the_live_read_asks_the_engine_once_per_running_outbound_call_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime.now(UTC) - timedelta(seconds=12)
    engine = _Engine(_snapshot("in_progress", started_at=started))
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)
    tenant_id, agent_id = await _trial_tenant()
    other_tenant, other_agent = await _trial_tenant()
    running = await _call(tenant_id, agent_id, status="queued", handle=f"out_{uuid7().hex}")
    ended = await _ended(tenant_id, agent_id, started=started)
    unconfirmed = await _call(tenant_id, agent_id, status="queued", handle=f"local:{uuid7()}")
    inbound = await _inbound_live(tenant_id, agent_id)
    theirs = await _call(other_tenant, other_agent, status="queued")
    ids = [running, ended, unconfirmed, inbound, theirs]
    headers = await _owner(tenant_id)
    async with _client() as http:
        answer = await http.get(
            "/v1/calls/live", params=[("ids", str(i)) for i in ids], headers=headers
        )
    assert answer.status_code == 200, answer.text
    body = {row["id"]: row for row in answer.json()}
    assert str(theirs) not in body, "another account's call is not answered"
    assert len(engine.asked) == 1, "one engine read, for the running outbound call only"
    assert body[str(running)]["status"] == "in_progress"
    assert body[str(running)]["status_source"] == "engine"
    assert body[str(running)]["live_state"] == "live"
    assert body[str(running)]["started_at"] is not None
    assert body[str(ended)]["live_state"] is None
    assert body[str(ended)]["status_source"] == "call"
    assert body[str(unconfirmed)] == {
        **body[str(unconfirmed)],
        "status": "queued",
        "status_source": "call",
        "live_state": "live",
    }
    assert body[str(inbound)]["status"] == "in_progress"
    assert body[str(inbound)]["status_source"] == "call"


async def test_an_end_the_engine_has_heard_first_reads_as_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        live_calls, "get_engine", lambda: _Engine(_snapshot("no_answer", terminal=True))
    )
    tenant_id, agent_id = await _trial_tenant()
    call_id = await _call(tenant_id, agent_id, status="queued")
    async with tenant_session(tenant_id) as session:
        [out] = await live_calls.read_live_calls(session, [call_id])
    assert out.status == "no_answer" and out.live_state is None


async def test_an_engine_that_cannot_answer_leaves_the_row_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine(fail=True)
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)
    tenant_id, agent_id = await _trial_tenant()
    call_id = await _call(tenant_id, agent_id, status="queued")
    async with tenant_session(tenant_id) as session:
        [out] = await live_calls.read_live_calls(session, [call_id])
    assert engine.asked and out.status == "queued" and out.live_state == "live"


async def test_the_live_read_takes_at_most_one_page_of_ids() -> None:
    tenant_id, _agent = await _trial_tenant()
    headers = await _owner(tenant_id)
    too_many = [("ids", str(uuid7())) for _ in range(live_calls.MAX_LIVE_IDS + 1)]
    async with _client() as http:
        answer = await http.get("/v1/calls/live", params=too_many, headers=headers)
        none = await http.get("/v1/calls/live", headers=headers)
    assert answer.status_code == 422
    assert none.status_code == 422
