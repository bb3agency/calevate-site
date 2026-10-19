"""The dashboard carries the free-trial panel (D-787).

The dashboard's trial card renders from `GET /v1/dashboard` rather than from a second read
of `GET /v1/trial` after it, so both routes must answer the same panel from the same
builder — an account on a trial and one that is not.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.billing.trials import start_trial
from apps.api.core.rbac import ROLE_PERMISSIONS
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from tests.api_security_test import _make_tenant

pytestmark = [pytest.mark.rls]


async def _reads(token: str, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        dashboard = await http.get("/v1/dashboard", headers=headers)
        panel = await http.get("/v1/trial", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert panel.status_code == 200, panel.text
    return dashboard.json(), panel.json()


async def test_an_account_on_a_trial_reads_its_panel_with_the_dashboard() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None, free_minutes=30)
    dashboard, panel = await _reads(token, slug)
    assert dashboard["trial"]["on_trial"] is True
    assert dashboard["trial"]["free_minutes"] == 30
    assert dashboard["trial"] == panel


async def test_an_account_not_on_a_trial_says_so_on_the_dashboard() -> None:
    _, slug, token = await _make_tenant()
    dashboard, panel = await _reads(token, slug)
    assert dashboard["trial"] == panel
    assert dashboard["trial"]["on_trial"] is False


async def test_a_member_who_may_not_read_the_account_gets_no_trial_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card is what `GET /v1/trial` answers, so a role holding `calls:read` without
    `org:read` reads the dashboard and not the card. No shipped role is shaped that way
    today, so one is made for the test by withholding `org:read` from staff."""
    tenant_id, slug, token = await _make_tenant(role="staff")
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
    monkeypatch.setitem(
        ROLE_PERMISSIONS, "staff", ROLE_PERMISSIONS["staff"] - frozenset({"org:read"})
    )
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        dashboard = await http.get("/v1/dashboard", headers=headers)
        panel = await http.get("/v1/trial", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["trial"] is None
    assert panel.status_code == 403
