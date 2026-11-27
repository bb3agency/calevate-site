"""An inbound line's day and the people it owes a call (W4.1, W4.2, W12.9).

1. The counts are the IST day's real calls: answered, owed a call back, missed; test calls
   and calls still ringing are in none of them, and another account sees none (hard rule 1).
2. The owed list keeps one row per person, drops someone a later call reached or a call
   marked handled, and names a call-back already booked.
3. The line's call-back switch is its own Follow-up, narrowed to the line, read back from
   the live Follow-ups; a missed call to another line does not start it.
4. A new line starts with it on when an agent can place the call, and off when none can.
5. Call logs read the account's own retention periods.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.api.follow_ups import runner, starters
from apps.api.inbound import lines, today
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_lifecycle_test import _tenant

pytestmark = pytest.mark.rls


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _line(tenant_id: UUID, agent_id: UUID, name: str = "Front desk") -> UUID:
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, created_by=None
        )


async def _can_call(tenant_id: UUID, agent_id: UUID) -> None:
    """The agent places calls: both directions, and its own engine agent to ring through."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both', engine_agent_ref = :ref WHERE id = :aid"),
            {"aid": agent_id, "ref": f"fake:{uuid.uuid4().hex}"},
        )


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    line_id: UUID | None,
    *,
    phone: str,
    status: str,
    outcome: str | None = None,
    direction: str = "inbound",
    at: datetime | None = None,
    trial: bool = False,
    handled: bool = False,
) -> UUID:
    call_id = uuid.uuid4()
    when = at or datetime.now(UTC) - timedelta(minutes=5)
    started = when if status == "completed" else None
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "outcome_tag, from_e164, to_e164, started_at, created_at, updated_at, "
                "trial_call, inbound_line_id, follow_up_state) VALUES (:id, :t, :a, :e, :d, :s, "
                ":o, :f, :to, :st, :at, :at, :trial, :lid, :fu)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"today-{uuid.uuid4().hex}",
                "d": direction,
                "s": status,
                "o": outcome,
                "f": phone if direction == "inbound" else "+918000000001",
                "to": "+918000000001" if direction == "inbound" else phone,
                "st": started,
                "at": when,
                "trial": trial,
                "lid": line_id,
                "fu": "resolved" if handled else None,
            },
        )
    return call_id


def _phone() -> str:
    return f"+9190{uuid.uuid4().int % 10**8:08d}"


async def test_todays_counts_are_the_lines_real_calls_and_no_other_accounts() -> None:
    tenant_id, agent_id, token = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    await _call(
        tenant_id, agent_id, line_id, phone=_phone(), status="completed", outcome="answered"
    )
    await _call(
        tenant_id, agent_id, line_id, phone=_phone(), status="completed", outcome="needs_you"
    )
    await _call(
        tenant_id,
        agent_id,
        line_id,
        phone=_phone(),
        status="completed",
        outcome="call_back_booked",
    )
    await _call(tenant_id, agent_id, line_id, phone=_phone(), status="no_answer", outcome="missed")
    await _call(
        tenant_id, agent_id, line_id, phone=_phone(), status="completed", outcome="hung_up_early"
    )
    # Neither a test call, nor one still ringing, nor yesterday's, counts.
    await _call(tenant_id, agent_id, line_id, phone=_phone(), status="no_answer", trial=True)
    await _call(tenant_id, agent_id, line_id, phone=_phone(), status="ringing")
    await _call(
        tenant_id,
        agent_id,
        line_id,
        phone=_phone(),
        status="no_answer",
        at=datetime.now(UTC) - timedelta(days=2),
    )

    async with _client() as http:
        got = await http.get("/v1/inbound-lines/today", headers=_as(token))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["day"] == today.ist_today().isoformat()
    assert body["lines"] == [
        {"line_id": str(line_id), "answered": 4, "call_back": 2, "missed": 1, "waiting": 5}
    ]

    other_tenant, _other_agent, other_token = await _tenant()
    async with _client() as http:
        theirs = await http.get("/v1/inbound-lines/today", headers=_as(other_token))
        peek = await http.get(f"/v1/inbound-lines/{line_id}/callers", headers=_as(other_token))
    assert theirs.json()["lines"] == []
    assert peek.status_code == 404
    async with tenant_session(other_tenant) as session:
        assert (await today.owed(session, line_id))[1] == []


async def test_the_owed_list_is_one_row_per_person_still_waiting() -> None:
    tenant_id, agent_id, token = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    now = datetime.now(UTC)
    twice = _phone()
    await _call(
        tenant_id, agent_id, line_id, phone=twice, status="no_answer", at=now - timedelta(hours=2)
    )
    latest = await _call(
        tenant_id, agent_id, line_id, phone=twice, status="busy", at=now - timedelta(hours=1)
    )
    asked = _phone()
    asked_call = await _call(
        tenant_id, agent_id, line_id, phone=asked, status="completed", outcome="needs_you"
    )
    # Reached since: we rang them and they talked.
    reached = _phone()
    await _call(
        tenant_id, agent_id, line_id, phone=reached, status="no_answer", at=now - timedelta(hours=3)
    )
    await _call(
        tenant_id,
        agent_id,
        None,
        phone=reached,
        status="completed",
        outcome="answered",
        direction="outbound",
        at=now - timedelta(hours=2),
    )
    handled = _phone()
    await _call(tenant_id, agent_id, line_id, phone=handled, status="no_answer", handled=True)
    answered = _phone()
    await _call(
        tenant_id, agent_id, line_id, phone=answered, status="completed", outcome="answered"
    )
    booked_at = now + timedelta(hours=4)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO scheduled_callbacks (id, tenant_id, agent_id, source_call_id, "
                "source_execution_id, phone_e164, requested_at, booked_at, status) VALUES "
                "(:id, :t, :a, :c, :x, :p, :r, now(), 'scheduled')"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "c": asked_call,
                "x": f"today-test:{uuid.uuid4().hex}",
                "p": asked,
                "r": booked_at,
            },
        )

    async with _client() as http:
        got = await http.get(f"/v1/inbound-lines/{line_id}/callers", headers=_as(token))
    assert got.status_code == 200, got.text
    rows = {r["phone_e164"]: r for r in got.json()["callers"]}
    assert set(rows) == {twice, asked}
    assert rows[twice]["call_id"] == str(latest)
    assert rows[twice]["reason"] == "not_answered"
    assert rows[twice]["tries"] == 2
    assert rows[twice]["call_back_at"] is None
    assert rows[asked]["reason"] == "asked"
    assert datetime.fromisoformat(rows[asked]["call_back_at"]) == booked_at


async def test_the_switch_is_the_lines_own_follow_up_and_reads_back() -> None:
    tenant_id, agent_id, token = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    other_line = await _line(tenant_id, agent_id, name="Second desk")
    async with _client() as http:
        cannot = await http.get(f"/v1/inbound-lines/{line_id}/missed-call-back", headers=_as(token))
        refused = await http.put(
            f"/v1/inbound-lines/{line_id}/missed-call-back", json={"on": True}, headers=_as(token)
        )
    assert cannot.json()["state"] == "cannot"
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("/line_call_back_no_caller")

    await _can_call(tenant_id, agent_id)
    async with _client() as http:
        on = await http.put(
            f"/v1/inbound-lines/{line_id}/missed-call-back", json={"on": True}, headers=_as(token)
        )
        again = await http.put(
            f"/v1/inbound-lines/{line_id}/missed-call-back", json={"on": True}, headers=_as(token)
        )
    assert on.status_code == 200, on.text
    assert on.json()["state"] == "on"
    assert again.json()["follow_up_id"] == on.json()["follow_up_id"]

    async with tenant_session(tenant_id) as session:
        live = await runner.live_follow_ups(session, "call_ended")
        assert [f.id for f in live] == [UUID(on.json()["follow_up_id"])]
        trigger = live[0].trigger
        assert getattr(trigger, "inbound_line_ids", None) == [line_id]
        # A missed call to the other line does not start it; one to this line does.
        elsewhere = await _call(
            tenant_id, agent_id, other_line, phone=_phone(), status="no_answer", outcome="missed"
        )
        assert await runner.start_for_call(session, tenant_id=tenant_id, call_id=elsewhere) == []
        here = await _call(
            tenant_id, agent_id, line_id, phone=_phone(), status="no_answer", outcome="missed"
        )
        assert len(await runner.start_for_call(session, tenant_id=tenant_id, call_id=here)) == 1

    async with _client() as http:
        off = await http.put(
            f"/v1/inbound-lines/{line_id}/missed-call-back", json={"on": False}, headers=_as(token)
        )
        back = await http.put(
            f"/v1/inbound-lines/{line_id}/missed-call-back", json={"on": True}, headers=_as(token)
        )
    assert off.json()["state"] == "off"
    assert back.json()["state"] == "on"
    assert back.json()["follow_up_id"] == on.json()["follow_up_id"]


async def test_an_account_wide_follow_up_covers_the_line_and_is_left_alone() -> None:
    tenant_id, agent_id, _token = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    await _can_call(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        account = next(
            s for s in await starters.for_account(session) if s.key == "missed_call_callback"
        )
        from apps.api.follow_ups import service

        row = await service.create(
            session,
            tenant_id=tenant_id,
            name=account.name,
            trigger=account.trigger,
            steps=account.steps,
            settings=account.settings,
            starter=account.key,
            user_id=None,
        )
        await service.publish(
            session, row.id, tenant_id=tenant_id, expected_updated_at=row.updated_at, user_id=None
        )
        state = await starters.line_call_back(session, line_id)
        assert state.state == "covered"
        assert state.covered_by == row.id
        await starters.set_line_call_back(
            session, tenant_id=tenant_id, line_id=line_id, on=False, user_id=None
        )
        assert (await service.get(session, row.id)).status == "live"


async def test_a_new_line_starts_with_the_call_back_on_when_an_agent_can_call() -> None:
    tenant_id, agent_id, _token = await _tenant()
    first = await _line(tenant_id, agent_id)
    await _can_call(tenant_id, agent_id)
    second = await _line(tenant_id, agent_id, name="Evening desk")
    async with tenant_session(tenant_id) as session:
        assert (await starters.line_call_back(session, first)).state == "off"
        assert (await starters.line_call_back(session, second)).state == "on"


async def test_call_logs_read_the_accounts_own_retention_periods() -> None:
    tenant_id, _agent_id, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE retention_policies SET ttl_days = 120 WHERE data_category = 'recording'")
        )
    async with _client() as http:
        got = await http.get("/v1/calls/kept", headers=_as(token))
    assert got.status_code == 200, got.text
    assert got.json()["recording_days"] == 120
    assert got.json()["transcript_days"] == 365
