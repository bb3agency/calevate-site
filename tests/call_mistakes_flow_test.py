"""Mistakes on real calls, end to end (D-949): the pipeline records them, the owner sees
them on the call and the agent, the operator marks a kind fixed, and a later call that
shows it again is the mistake coming back."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.agents import call_mistakes
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from apps.workers.pipeline import run_post_call_pipeline
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.call_mistakes_test import SRI_ESTATES
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls

BOARD = "/v1/ops/call-mistakes"


async def _operator() -> tuple[uuid.UUID, dict[str, str]]:
    """A superadmin: `ops:manage` is the incident surface's permission."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops Mistakes', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id, {"Authorization": f"Bearer dev:admin:{admin_id}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Mistake Estates",
        slug=f"mst-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _real_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> uuid.UUID:
    """The Sri Estates call, through the whole post-call pipeline."""
    reset_engine_cache()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": execution_id},
        )
    now = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref="unused-direct-run",
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=59),
        ended_at=now,
        duration_s=59,
        from_e164="+911140000000",
        to_e164="+919876500001",
        recording_url=None,
        transcript=[
            TranscriptTurn(call_id=execution_id, idx=t.idx, speaker=t.speaker, text=t.text)  # type: ignore[arg-type]
            for t in SRI_ESTATES
        ],
        cost=None,
        engine="fake",
    )

    async def _get(self: FakeEngine, cid: str) -> ExecutionSnapshot:
        return snapshot

    monkeypatch.setattr(FakeEngine, "get_execution", _get)
    payload = {
        "tenant_id": str(tenant_id),
        "call_id": str(call_id),
        "engine": "fake",
        "execution_id": execution_id,
    }
    await run_post_call_pipeline({}, payload)
    # The pipeline is re-entrant; a re-drive replaces the call's rows, never adds to them.
    await run_post_call_pipeline({}, payload)
    return call_id


async def test_a_real_call_is_checked_and_the_owner_sees_what_went_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _real_call(tenant_id, agent_id, monkeypatch)
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT kind, turn_idx FROM call_mistakes WHERE call_id = :c ORDER BY 2"),
                {"c": call_id},
            )
        ).all()
    # Nothing was on file for the number, so turn 3's "you enquired before" is invented.
    assert [tuple(r) for r in rows] == [
        ("false_history", 3),
        ("said_again", 9),
        ("asked_again", 11),
    ]

    headers = await _org_headers(tenant_id)
    async with _client() as http:
        detail = (await http.get(f"/v1/calls/{call_id}", headers=headers)).json()
        listed = await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)
        missing = await http.get(f"/v1/agents/{uuid7()}/call-mistakes", headers=headers)
    assert [m["kind"] for m in detail["mistakes"]] == ["false_history", "said_again", "asked_again"]
    assert detail["mistakes"][1]["label"] == call_mistakes.LESSONS["said_again"].label
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["window_days"] == call_mistakes.WINDOW_DAYS
    # `platform_mistake_fixes` is platform state another test may already have written, so
    # the state is whichever the fixes on record make it; the next test drives each one.
    assert {(m["kind"], m["calls"]) for m in body["items"]} == {
        ("false_history", 1),
        ("said_again", 1),
        ("asked_again", 1),
    }
    assert {m["state"] for m in body["items"]} <= {"fixing", "fixed", "back"}
    assert body["items"][0]["last_call_id"] == str(call_id)
    assert missing.status_code == 404


async def test_an_earlier_enquiry_is_no_mistake_when_the_number_was_on_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lead for the number that came before the call (here a form enquiry) is prior
    contact, so "you enquired before" is the agent saying what is true."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, data, "
                "schema_version, call_count, is_repeat_caller, created_at, updated_at) VALUES "
                "(:id, :t, :a, '+919876500001', 'webhook', 'new', '{}'::jsonb, 1, 0, false, "
                "now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id},
        )
    call_id = await _real_call(tenant_id, agent_id, monkeypatch)
    async with tenant_session(tenant_id) as session:
        kinds = (
            (
                await session.execute(
                    text("SELECT kind FROM call_mistakes WHERE call_id = :c"), {"c": call_id}
                )
            )
            .scalars()
            .all()
        )
    assert "false_history" not in kinds
    assert {"said_again", "asked_again"} <= set(kinds)


async def test_a_fixed_mistake_that_comes_back_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(call_mistakes, "alert", lambda stage, code, **kw: raised.append((code, kw)))
    tenant_id, agent_id = await _tenant()
    admin_id, admin = await _operator()
    # Fixed ten minutes ago, so a call placed now started after the fix. Written as the
    # route writes it, back-dated; the route itself is driven on another kind below.
    fixed_at = datetime.now(UTC) - timedelta(minutes=10)
    before_fix = fixed_at - timedelta(minutes=10)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO platform_mistake_fixes (id, kind, note, fixed_by, fixed_at) "
                "VALUES (:id, 'said_again', 'HOW TO SPEAK reworded', :by, :at)"
            ),
            {"id": uuid7(), "by": admin_id, "at": fixed_at},
        )
    async with _client() as http:
        fixed = await http.post(
            f"{BOARD}/opened_again/fixed", headers=admin, json={"note": "START rule reworded"}
        )
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["kind"] == "opened_again"
        unknown = await http.post(f"{BOARD}/no_such_kind/fixed", headers=admin, json={"note": "x"})
        blank = await http.post(f"{BOARD}/opened_again/fixed", headers=admin, json={"note": "   "})
    assert unknown.status_code == 404
    assert blank.status_code in (400, 422)

    # A call placed before the fix and read after it is not the mistake coming back.
    old_call = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'completed', :s, now(), now())"
            ),
            {
                "id": old_call,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex}",
                "s": before_fix,
            },
        )
    back = await call_mistakes.record_call_mistakes(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=old_call,
        call_started_at=before_fix,
        found={"said_again": 3},
    )
    assert back == []
    assert raised == []

    await _real_call(tenant_id, agent_id, monkeypatch)
    assert {kw["reason"] for code, kw in raised if code == "call_mistake_back"} == {"said_again"}
    # A kind with no fix on record is raised as new, once for the account.
    assert {code for code, _kw in raised} <= {"call_mistake_back", "call_mistake_new"}
    assert "said_again" not in {kw["reason"] for code, kw in raised if code == "call_mistake_new"}

    headers = await _org_headers(tenant_id)
    async with _client() as http:
        items = (await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)).json()[
            "items"
        ]
        board = (await http.get(BOARD, headers=admin)).json()
    said = next(m for m in items if m["kind"] == "said_again")
    assert (said["state"], said["calls"], said["calls_since_fix"]) == ("back", 2, 1)
    # Still happening comes first.
    assert items[0]["kind"] == "said_again"
    row = next(m for m in board["items"] if m["kind"] == "said_again")
    assert row["state"] == "back"
    assert row["fix_note"] == "HOW TO SPEAK reworded"
    assert row["fixed_by"] == "Ops Mistakes"
    assert row["calls_since_fix"] >= 1 and row["accounts_30d"] >= 1
    assert {m["kind"] for m in board["items"]} == set(call_mistakes.LESSONS)


async def test_the_board_and_the_fix_are_the_operators_only() -> None:
    tenant_id, _agent = await _tenant()
    headers = await _org_headers(tenant_id)
    async with _client() as http:
        read = await http.get(BOARD, headers=headers)
        write = await http.post(f"{BOARD}/said_again/fixed", headers=headers, json={"note": "x"})
    assert read.status_code in (401, 403)
    assert write.status_code in (401, 403)


async def test_a_fix_is_audited() -> None:
    _admin_id, admin = await _operator()
    async with _client() as http:
        await http.post(f"{BOARD}/third_person/fixed", headers=admin, json={"note": "Tool note"})
    from apps.api.db.session import admin_session

    async with admin_session() as session:
        found = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'ops.call_mistake_fixed' "
                    "AND object_id = 'third_person'"
                )
            )
        ).scalar_one()
    assert found >= 1


async def test_another_account_sees_none_of_the_mistakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 1: FORCEd RLS; another tenant reads zero rows and cannot write one."""
    owner, agent_id = await _tenant()
    stranger, _b = await _tenant()
    call_id = await _real_call(owner, agent_id, monkeypatch)
    async with tenant_session(stranger) as session:
        seen = (await session.execute(text("SELECT count(*) FROM call_mistakes"))).scalar_one()
        assert seen == 0
        with pytest.raises(Exception):  # noqa: B017 — the policy's WITH CHECK refuses it
            await session.execute(
                text(
                    "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, "
                    "turn_idx, call_started_at) VALUES (:id, :t, :a, :c, 'said_again', 1, now())"
                ),
                {"id": uuid7(), "t": owner, "a": agent_id, "c": call_id},
            )


async def test_a_kind_never_fixed_is_raised_once_per_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client reads "our team has been told" (D-970): the first call showing a kind with
    no fix on record is how the team is told, and later calls do not raise it again."""
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(call_mistakes, "alert", lambda stage, code, **kw: raised.append((code, kw)))
    tenant_id, agent_id = await _tenant()
    calls = [uuid7(), uuid7()]
    async with tenant_session(tenant_id) as session:
        for call_id in calls:
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                    "'outbound', 'completed', now(), now(), now())"
                ),
                {
                    "id": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exec_{uuid.uuid4().hex[:12]}",
                },
            )
    # The second call, and a re-drive of the first, find it already seen on the account.
    for call_id in (*calls, calls[0]):
        await call_mistakes.record_call_mistakes(
            tenant_id=tenant_id,
            agent_id=agent_id,
            call_id=call_id,
            call_started_at=datetime.now(UTC),
            found={"wrong_language": 2},
        )
    assert [(code, kw["reason"]) for code, kw in raised] == [("call_mistake_new", "wrong_language")]


async def test_the_board_names_the_rule_and_the_latest_call() -> None:
    _admin_id, admin = await _operator()
    async with _client() as http:
        board = (await http.get(BOARD, headers=admin)).json()
    rows = {row["kind"]: row for row in board["items"]}
    assert rows["goodbye_while_asking"]["rule"].startswith("HOW TO SPEAK")
    assert rows["third_person"]["rule"] == ""
    seen = [row for row in board["items"] if row["last_call_id"]]
    assert all(row["last_client_slug"] for row in seen)
