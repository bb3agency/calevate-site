"""Every new account starts its free trial at birth with no agent, and an operator's trial
replaces that one (founder, 22 Oct 2026, D-853).

Both creation motions are driven over HTTP on the real app: the operator's wizard
(`POST /v1/admin/tenants`) and, for the replacement, the operator's trial route followed by
the client's own `GET /v1/trial`.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.trial_routes import start_trial_confirmation
from apps.api.billing.trials import REPLACED_REASON, TRIAL_STOPPED, read_trial
from apps.api.compliance.trial_access import read_trial_access, restricting_trial
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def _invited_account(token: str) -> dict[str, Any]:
    slug = f"newacct-{uuid.uuid4().hex[:8]}"
    async with _client() as http:
        response = await http.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}", "X-Confirm-Action": "create_tenant"},
            json={
                "name": "Vennela Real Estate",
                "slug": slug,
                "vertical_template": "real_estate",
                "owner": {"email": f"owner-{uuid.uuid4().hex[:8]}@example.com"},
            },
        )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _owner_token(tenant_id: UUID) -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"o-{user_id.hex[:8]}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'owner', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "u": user_id},
        )
    return f"dev:client:{user_id}"


def test_the_code_defaults_are_seven_days_and_fifteen_minutes() -> None:
    """The founder's terms (22 Oct 2026). A live console row overrides these on a deployment."""
    assert Settings.model_fields["self_serve_trial_days"].default == 7
    assert Settings.model_fields["self_serve_trial_free_minutes"].default == 15


async def test_an_invited_account_starts_its_trial_and_has_no_agent() -> None:
    settings = get_settings()
    created = await _invited_account(await _admin())
    tenant_id = UUID(created["id"])
    assert "agent_id" not in created and "extraction_schema_id" not in created

    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
        restricted = await restricting_trial(session, tenant_id=tenant_id)
        agents = (
            await session.execute(
                text("SELECT count(*) FROM agents WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'trial.started'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert trial is not None and trial.status == "active"
    assert trial.days == settings.self_serve_trial_days
    assert trial.free_minutes == settings.self_serve_trial_free_minutes
    assert trial.started_by is None, "nobody chose these terms"
    assert restricted is not None, "an unpaid new account is a test-calls-only trial"
    assert agents == 0
    assert audited == 1


async def test_an_operators_trial_replaces_the_one_the_account_started_with() -> None:
    admin = await _admin()
    created = await _invited_account(admin)
    tenant_id = UUID(created["id"])
    async with tenant_session(tenant_id) as session:
        automatic = await read_trial(session, tenant_id=tenant_id)
    assert automatic is not None
    # A test call made under the automatic trial: the replacement counts from its own start.
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, direction, status, "
                    "language_primary, disclosure_line, ai_disclosure_line, "
                    "recording_notice_line, caller_memory_notice_line, created_at, updated_at) "
                    "SELECT :id, :t, 'x', 'outbound', 'draft', 'te-IN', 'd', 'd', 'd', 'd', "
                    "now(), now() RETURNING id"
                ),
                {"id": uuid7(), "t": tenant_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "trial_call, status, duration_s, created_at, updated_at) VALUES (:id, :t, :a, "
                ":e, 'outbound', '+919876543210', true, 'completed', 600, now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": f"out_{uuid.uuid4().hex}"},
        )

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial",
            headers={
                "Authorization": f"Bearer {admin}",
                "X-Confirm-Action": start_trial_confirmation(tenant_id, 20),
            },
            json={"days": 20, "reason": "Founder promised twenty days.", "free_minutes": 100},
        )
        assert posted.status_code == 201, posted.text
        owner = await _owner_token(tenant_id)
        panel = await http.get(
            "/v1/trial",
            headers={"Authorization": f"Bearer {owner}", "X-Org-Slug": created["slug"]},
        )
    assert panel.status_code == 200, panel.text
    body = panel.json()
    assert body["on_trial"] is True
    assert body["days_remaining"] == 20
    assert body["free_minutes"] == 100
    assert body["minutes_left"] == 100, "minutes count from the operator's trial, not before"

    async with tenant_session(tenant_id) as session:
        access = await read_trial_access(session, tenant_id=tenant_id)
        old = (
            await session.execute(
                text("SELECT status, ended_reason, erase_after FROM tenant_trials WHERE id = :id"),
                {"id": automatic.id},
            )
        ).one()
        active = (
            await session.execute(
                text(
                    "SELECT count(*) FROM tenant_trials WHERE tenant_id = :t AND status = 'active'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
        started = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'trial.started'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert access is not None and access.trial.free_minutes == 100
    assert access.minutes_left == 100 and access.blocker is None
    assert old.status == TRIAL_STOPPED and old.ended_reason == REPLACED_REASON
    assert old.erase_after is None, "a replaced trial schedules no erasure"
    assert active == 1
    assert started == 2, "the automatic trial and the operator's, each audited"
