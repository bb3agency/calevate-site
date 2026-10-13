"""How many calls one client may have at once (founder decision F7, 12 Oct 2026).

Calevate's default (2 paying, 1 on a free trial) and an operator's choice; the paying client's
own workspace is sent the value when provisioned and when it changes, read back, and repaired
by the daily sweep; a free trial's cap is held by our dial gate, which counts the client's own
calls in progress and no one else's.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.billing.trials import start_trial
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy.call_lines import (
    CALL_LINES_BUSY_RULE,
    CALL_LINES_SYNC_JOB,
    call_lines_blocker,
    read_call_lines,
    set_call_lines,
)
from apps.api.tenancy.call_lines_routes import call_lines_confirmation, router
from apps.workers import engine_workspaces
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.call_handling_test import _operator, _tenant

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


async def _on_trial(tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)


async def _sync_jobs(tenant_id: uuid.UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'tenant_id' = :tid"
                    ),
                    {"job": CALL_LINES_SYNC_JOB, "tid": str(tenant_id)},
                )
            ).scalar_one()
        )


@pytest.fixture
def on_thinnest(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "engine", "thinnest")


# --- the value -----------------------------------------------------------------------


async def test_the_default_is_two_paying_and_one_on_a_trial() -> None:
    paying, _a, _h = await _tenant()
    trial, _b, _i = await _tenant()
    await _on_trial(trial)
    async with tenant_session(paying) as session:
        lines = await read_call_lines(session, tenant_id=paying)
    assert (lines.lines, lines.chosen, lines.source, lines.on_trial) == (2, None, "platform", False)
    async with tenant_session(trial) as session:
        lines = await read_call_lines(session, tenant_id=trial)
    assert (lines.lines, lines.on_trial) == (1, True)


async def test_the_column_holds_its_range() -> None:
    tenant_id, _agent, _h = await _tenant()
    for bad in (0, 51):
        with pytest.raises(IntegrityError):
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text("UPDATE organizations SET call_lines = :n WHERE id = :id"),
                    {"n": bad, "id": tenant_id},
                )


async def test_an_operator_sets_it_and_the_workspace_is_owed_it(on_thinnest: None) -> None:
    tenant_id, _agent, _h = await _tenant()
    headers = await _operator()
    async with _client() as client:
        first = await client.get(f"/v1/admin/organizations/{tenant_id}/call-lines", headers=headers)
        unconfirmed = await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": 4},
        )
        assert unconfirmed.status_code == 403, unconfirmed.text
        assert unconfirmed.json()["type"].endswith("/step_up_required")
        headers = {**headers, "X-Confirm-Action": call_lines_confirmation(tenant_id)}
        assert first.status_code == 200, first.text
        assert first.json()["call_lines"] == 2 and first.json()["source"] == "platform"
        assert first.json()["paid_default"] == 2 and first.json()["trial_default"] == 1

        set_ = await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": 4},
        )
        assert set_.status_code == 200, set_.text
        assert set_.json()["call_lines"] == 4 and set_.json()["source"] == "organization"
        assert await _sync_jobs(tenant_id) == 1
        # The same value again moves nothing and owes nothing.
        await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": 4},
        )
        assert await _sync_jobs(tenant_id) == 1
        # Back to the default, which is a different number: owed again.
        cleared = await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": None},
        )
        assert cleared.json()["call_lines"] == 2
        assert await _sync_jobs(tenant_id) == 2

        bad = await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": 0},
        )
        assert bad.status_code == 422
        assert bad.headers["content-type"].startswith("application/problem+json")
        assert bad.json()["type"].endswith("/call_lines_out_of_range")


async def test_an_organization_that_does_not_exist_is_a_404_not_the_default() -> None:
    headers = await _operator()
    async with _client() as client:
        response = await client.get(
            f"/v1/admin/organizations/{uuid.uuid4()}/call-lines", headers=headers
        )
    assert response.status_code == 404, response.text


async def test_a_client_cannot_reach_the_operators_door() -> None:
    tenant_id, _agent, headers = await _tenant()
    async with _client() as client:
        response = await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": 9},
        )
    assert response.status_code in (401, 403)
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT call_lines FROM organizations WHERE id = :id"), {"id": tenant_id}
            )
        ).scalar()
    assert held is None


async def test_one_clients_value_is_invisible_to_another() -> None:
    a, _x, _h = await _tenant()
    b, _y, _i = await _tenant()
    async with tenant_session(a) as session:
        await set_call_lines(session, tenant_id=a, lines=7)
    async with tenant_session(b) as session:
        seen = (
            await session.execute(
                text("SELECT call_lines FROM organizations WHERE id = :id"), {"id": a}
            )
        ).all()
    assert seen == []


# --- a paying client's own workspace ---------------------------------------------------


class _Customers:
    def __init__(self, held: int | None) -> None:
        self.held = held
        self.sent: list[tuple[str, int]] = []

    async def read_customer_call_lines(self, workspace_id: str) -> int | None:
        return self.held

    async def set_customer_call_lines(self, workspace_id: str, lines: int) -> int:
        self.sent.append((workspace_id, lines))
        self.held = lines
        return lines


async def _with_workspace(tenant_id: uuid.UUID) -> str:
    workspace = f"org_{uuid.uuid4().hex[:20]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_engine_workspaces (id, tenant_id, engine, external_ref, "
                "workspace_id, status, created_at, updated_at) VALUES (:id, :tid, 'thinnest', "
                ":ref, :ws, 'active', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "ref": f"calevate-{tenant_id}", "ws": workspace},
        )
    return workspace


async def test_the_job_sends_the_value_to_the_clients_own_workspace(
    on_thinnest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent, _h = await _tenant()
    customers = _Customers(held=None)
    monkeypatch.setattr(engine_workspaces, "thinnest_customers", lambda: customers)
    payload: dict[str, Any] = {"tenant_id": str(tenant_id)}
    # No workspace yet: nothing to send (a trial's cap is the dial gate's).
    assert await engine_workspaces.sync_engine_call_lines({}, payload) == "no_workspace"
    workspace = await _with_workspace(tenant_id)
    assert await engine_workspaces.sync_engine_call_lines({}, payload) == "set"
    assert customers.sent == [(workspace, 2)]
    async with tenant_session(tenant_id) as session:
        await set_call_lines(session, tenant_id=tenant_id, lines=3)
    await engine_workspaces.sync_engine_call_lines({}, payload)
    assert customers.sent[-1] == (workspace, 3)


async def test_the_sweep_repairs_a_value_changed_in_the_vendors_console(
    on_thinnest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent, _h = await _tenant()
    workspace = await _with_workspace(tenant_id)
    customers = _Customers(held=2)
    monkeypatch.setattr(engine_workspaces, "thinnest_customers", lambda: customers)
    assert await engine_workspaces._call_lines_leg(tenant_id, workspace, repair=True) == "in_step"
    assert customers.sent == []
    customers.held = 10
    assert await engine_workspaces._call_lines_leg(tenant_id, workspace, repair=True) == "repaired"
    assert customers.sent == [(workspace, 2)]


async def test_a_new_workspace_is_owed_its_call_lines(on_thinnest: None) -> None:
    tenant_id, _agent, _h = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_engine_workspaces (id, tenant_id, engine, external_ref, "
                "status, created_at, updated_at) VALUES (:id, :tid, 'thinnest', :ref, "
                "'pending', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "ref": f"calevate-{tenant_id}"},
        )
    await engine_workspaces._activate(tenant_id, f"org_{uuid.uuid4().hex[:20]}")
    assert await _sync_jobs(tenant_id) == 1


# --- a free trial: our dial gate -------------------------------------------------------


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID, status: str) -> None:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "trial_call, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                ":s, true, now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"out_{call_id.hex}",
                "s": status,
            },
        )


async def test_a_trial_with_a_call_in_progress_is_refused_another() -> None:
    tenant_id, agent_id, _h = await _tenant()
    other, other_agent, _i = await _tenant()
    await _on_trial(tenant_id)
    await _on_trial(other)
    async with tenant_session(tenant_id) as session:
        assert await call_lines_blocker(session, tenant_id=tenant_id) is None
    await _call(tenant_id, agent_id, "completed")
    # Another client's call holds none of this client's lines.
    await _call(other, other_agent, "in_progress")
    async with tenant_session(tenant_id) as session:
        assert await call_lines_blocker(session, tenant_id=tenant_id) is None
    await _call(tenant_id, agent_id, "ringing")
    async with tenant_session(tenant_id) as session:
        busy = await call_lines_blocker(session, tenant_id=tenant_id)
    assert busy is not None
    rule, reason = busy
    assert rule == CALL_LINES_BUSY_RULE
    assert reason == (
        "This account can have 1 call at once, and that many are in progress. "
        "Try again when a call ends."
    )
    # An operator raising the cap lets the second one through.
    async with tenant_session(tenant_id) as session:
        await set_call_lines(session, tenant_id=tenant_id, lines=2)
        assert await call_lines_blocker(session, tenant_id=tenant_id) is None


async def test_the_gate_refuses_a_test_call_with_the_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """`check_dispatch(trial_call=True)` refuses with `call_lines_busy`, after the account's
    own refusals and before the hours."""
    from apps.api.compliance import service as compliance

    tenant_id, agent_id, _h = await _tenant()
    await _on_trial(tenant_id)

    async def _no_account_refusals(*_a: Any, **_k: Any) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr(compliance, "account_dial_blockers", _no_account_refusals)
    monkeypatch.setattr(compliance, "truthful_answer_drift_blocker", _no_refusal)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'both' WHERE id = :aid"),
            {"aid": agent_id},
        )
    await _call(tenant_id, agent_id, "in_progress")
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876500001",
            trial_call=True,
        )
    assert decision.allowed is False
    assert decision.rule == CALL_LINES_BUSY_RULE


async def _no_refusal(*_a: Any, **_k: Any) -> None:
    return None


async def test_a_paying_clients_dial_is_not_counted_here() -> None:
    tenant_id, agent_id, _h = await _tenant()
    await _call(tenant_id, agent_id, "in_progress")
    await _call(tenant_id, agent_id, "in_progress")
    await _call(tenant_id, agent_id, "in_progress")
    async with tenant_session(tenant_id) as session:
        assert await call_lines_blocker(session, tenant_id=tenant_id) is None
