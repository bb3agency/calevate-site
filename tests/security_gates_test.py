"""The step-up gates and view-as refusals the 11 Oct 2026 security pass added.

D-731 — operator writes that now take step-up. Each is asked twice: with no
`X-Confirm-Action` it is refused `step_up_required` before any work (a `dev:` token, which
the freshness half waives locally), and with the right header but a second factor older
than the window it is refused `reauthentication_required` (a real admin cookie). Every
body below is VALID, so the refusal cannot be a 422 that happened to come first.

D-730 — client actions that take a code typed for them: exports, integration credentials
and outbound endpoints. With a real client cookie and no code they are refused; with a
code recorded for exactly that action they pass the gate; the code is spent once.

D-730 — what a view-as session may not do: buy or give up a number, add or change an
outbound endpoint, store or change an integration credential. Refused
`impersonation_not_available_here`, the way a top-up is.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from apps.api.admin import service as admin_service
from apps.api.authn.cookies import cookie_name
from apps.api.authn.sessions import issue_session
from apps.api.authn.stepup import REAUTH_MAX_AGE, record_action_proof
from apps.api.db.session import credential_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.impersonation_grant_test import view_as_headers

ADMIN_COOKIE = cookie_name("admin", secure=False)
CLIENT_COOKIE = cookie_name("client", secure=False)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest_asyncio.fixture
async def superadmin() -> AsyncIterator[uuid.UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Gate Probe', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    try:
        yield admin_id
    finally:
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = :s"), {"s": admin_id}
            )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})


async def _stale_admin_cookie(admin_id: uuid.UUID) -> str:
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=admin_id, now=at)
        await session.execute(
            text("UPDATE auth_sessions SET mfa_verified_at = :when WHERE id = :id"),
            {"when": at - REAUTH_MAX_AGE - timedelta(minutes=5), "id": issued.session_id},
        )
    return issued.token


async def _org() -> dict[str, Any]:
    return await admin_service.create_organization(
        name="Gate Clinic",
        slug=f"gt-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


def _admin_gates(t: str) -> list[tuple[str, str, dict[str, Any] | None, str]]:
    """(method, path, valid body, confirmation) for every D-731 operator write."""
    u, n, c, a = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return [
        (
            "POST",
            "/v1/admin/tenants",
            {
                "name": "Gate Probe Clinic",
                "vertical_template": "clinic",
                "owner": {"email": f"owner-{uuid.uuid4().hex[:6]}@example.com"},
            },
            "create_tenant",
        ),
        (
            "POST",
            f"/v1/admin/tenants/{t}/invitations",
            {"email": "invitee@example.com", "role": "staff"},
            f"invite_member:{t}",
        ),
        (
            "PATCH",
            f"/v1/admin/tenants/{t}/members/{u}",
            {"role": "owner", "expected_role": "staff"},
            f"change_member_role:{t}:{u}",
        ),
        (
            "POST",
            f"/v1/admin/tenants/{t}/numbers",
            {"e164": "+918000000003", "series": "standard", "provider": "plivo"},
            f"provision_number:{t}",
        ),
        ("POST", f"/v1/admin/tenants/{t}/kyc", {"status": "submitted"}, f"record_kyc:{t}"),
        (
            "PUT",
            f"/v1/admin/tenants/{t}/feature-flags/some_flag",
            {"enabled": True, "reason": "testing the gate"},
            f"set_feature_flag:{t}:some_flag",
        ),
        (
            "PUT",
            f"/v1/admin/tenants/{t}/platform-fee/waiver",
            {"reason": "founding client"},
            f"waive_platform_fee:{t}",
        ),
        (
            "POST",
            f"/v1/admin/tenants/{t}/platform-fee/{c}/payments",
            {"reference": "UTR123456"},
            f"record_fee_payment:{t}:{c}",
        ),
        (
            "POST",
            f"/v1/admin/tenants/{t}/credits",
            {"amount_inr": "500", "payment_ref": "UTR-GATE-1"},
            f"record_payment:{t}",
        ),
        (
            "POST",
            f"/v1/admin/tenants/{t}/trial/end",
            {"outcome": "converted", "reason": "they signed up"},
            f"end_trial:{t}:converted",
        ),
        ("POST", "/v1/admin/payments/reconcile", None, "reconcile_payments"),
        (
            "POST",
            f"/v1/admin/numbers/tenants/{t}/buy",
            {"e164": "+918000000001", "monthly_price_usd": "1.00"},
            f"buy_number:{t}",
        ),
        ("POST", f"/v1/admin/numbers/tenants/{t}/{n}/release", None, f"release_number:{t}:{n}"),
        (
            "POST",
            f"/v1/admin/engine-workspaces/tenants/{t}/provision",
            None,
            f"provision_workspace:{t}",
        ),
        (
            "POST",
            f"/v1/admin/engine-workspaces/tenants/{t}/offboard",
            None,
            f"offboard_workspace:{t}",
        ),
        (
            "POST",
            f"/v1/admin/engine-workspaces/tenants/{t}/numbers/purchase",
            {"number": "+918000000002", "request_key": "gate-probe-key"},
            f"buy_number:{t}",
        ),
        (
            "POST",
            f"/v1/admin/engine-workspaces/tenants/{t}/numbers/{n}/release",
            {"confirm": True},
            f"release_number:{t}:{n}",
        ),
        ("POST", f"/v1/admin/copilot/actions/{a}/undo", None, f"undo_copilot_action:{a}"),
        (
            "POST",
            f"/v1/admin/engine-workspaces/tenants/{t}/numbers/{n}/move",
            None,
            f"move_number:{t}:{n}",
        ),
        ("POST", "/v1/ops/trial-number/line", None, "set_up_trial_line"),
        (
            "PUT",
            f"/v1/admin/organizations/{t}/call-lines",
            {"call_lines": 3},
            f"set_call_lines:{t}",
        ),
        (
            "PUT",
            f"/v1/admin/organizations/{t}/llm-defaults",
            {"default_llm_model": None},
            f"set_llm_default:{t}",
        ),
    ]


GATE_COUNT = 22


def test_the_gate_list_is_the_one_this_file_claims() -> None:
    assert len(_admin_gates(str(uuid.uuid4()))) == GATE_COUNT


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(GATE_COUNT))
async def test_an_operator_write_without_the_confirmation_is_refused(index: int) -> None:
    org = await _org()
    method, path, body, _confirm = _admin_gates(str(org["id"]))[index]
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Gate Probe', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    async with _client() as http:
        response = await http.request(
            method, path, headers={"Authorization": f"Bearer dev:admin:{admin_id}"}, json=body
        )
    assert response.status_code == 403, f"{method} {path}: {response.text}"
    assert response.json()["type"].endswith("/step_up_required"), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(GATE_COUNT))
async def test_an_operator_write_on_a_stale_second_factor_is_refused(
    index: int, superadmin: uuid.UUID
) -> None:
    org = await _org()
    method, path, body, confirm = _admin_gates(str(org["id"]))[index]
    cookie = await _stale_admin_cookie(superadmin)
    async with _client() as http:
        response = await http.request(
            method,
            path,
            headers={"X-Confirm-Action": confirm},
            cookies={ADMIN_COOKIE: cookie},
            json=body,
        )
    assert response.status_code == 403, f"{method} {path}: {response.text}"
    assert response.json()["type"].endswith("/reauthentication_required"), response.text


# ═══════════════ D-730: client actions that take a code typed for them ═══════════════


async def _client_cookie(token: str) -> tuple[uuid.UUID, str]:
    user_id = uuid.UUID(token.rsplit(":", 1)[1])
    async with credential_session() as session:
        issued = await issue_session(session, realm="client", subject_id=user_id)
    return user_id, issued.token


def _client_gates(slug: str) -> list[tuple[str, str, dict[str, Any] | None, str]]:
    return [
        ("GET", "/v1/calls/export.csv", None, f"export_calls:{slug}"),
        ("GET", "/v1/leads/export.csv", None, f"export_leads:{slug}"),
        ("POST", "/v1/leads/export.csv", {}, f"export_leads:{slug}"),
        (
            "POST",
            "/v1/integrations/credentials",
            {"kind": "razorpay", "label": "Payments", "secret": "s3cret-value-1234"},
            f"create_credential:{slug}",
        ),
        (
            "POST",
            "/v1/integrations/endpoints",
            {"url": "https://hooks.example.com/leads", "events": ["lead.created"]},
            f"create_endpoint:{slug}",
        ),
        # D-746: adding a published number, testing it (a real call) and the save-our-number
        # switch. The test route answers 404 for an unknown line only after the code.
        (
            "POST",
            "/v1/forwarding/lines",
            {
                "number": "98765 43210",
                "line_kind": "mobile",
                "carrier": "airtel",
                "mode": "conditional",
                "ring_seconds": 20,
                "attest": True,
            },
            f"add_forwarded_number:{slug}",
        ),
        ("POST", f"/v1/forwarding/lines/{uuid.uuid4()}/tests", {}, f"forwarding_test:{slug}"),
        ("PUT", "/v1/forwarding/save-number", {"enabled": True}, f"save_number_message:{slug}"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(8))
async def test_a_client_action_needs_a_code_typed_for_it(index: int) -> None:
    _tenant_id, slug, token = await _make_tenant()
    user_id, cookie = await _client_cookie(token)
    method, path, body, action = _client_gates(slug)[index]
    headers = {"X-Org-Slug": slug, "X-Confirm-Action": action}

    async with _client() as http:
        refused = await http.request(
            method, path, headers=headers, cookies={CLIENT_COOKIE: cookie}, json=body
        )
        await record_action_proof(realm="client", subject_id=user_id, action=action)
        passed = await http.request(
            method, path, headers=headers, cookies={CLIENT_COOKIE: cookie}, json=body
        )
        spent = await http.request(
            method, path, headers=headers, cookies={CLIENT_COOKIE: cookie}, json=body
        )

    assert refused.status_code == 403, refused.text
    assert refused.json()["type"].endswith("/reauthentication_required")
    assert f'"action": "{action}"' in refused.json()["remediation"]
    assert passed.status_code not in (401, 403), f"{method} {path}: {passed.text}"
    assert spent.status_code == 403, "a code opens one request, not a session"


@pytest.mark.asyncio
async def test_a_code_for_one_action_does_not_open_another() -> None:
    _tenant_id, slug, token = await _make_tenant()
    user_id, cookie = await _client_cookie(token)
    await record_action_proof(realm="client", subject_id=user_id, action=f"export_leads:{slug}")
    async with _client() as http:
        response = await http.get(
            "/v1/calls/export.csv",
            headers={"X-Org-Slug": slug, "X-Confirm-Action": f"export_calls:{slug}"},
            cookies={CLIENT_COOKIE: cookie},
        )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_the_client_step_up_verify_records_the_action_proof() -> None:
    """The client realm's own `/step-up/verify`, end to end: the code answered for an
    action is what the export then spends."""
    from apps.api.authn import otp
    from apps.api.authn import service as authn_service

    _tenant_id, slug, token = await _make_tenant()
    user_id, cookie = await _client_cookie(token)
    action = f"export_calls:{slug}"
    async with credential_session() as session:
        code = (
            await otp.issue_challenge(
                session, purpose=authn_service.STEP_UP, realm="client", subject_id=user_id
            )
        ).code
    async with _client() as http:
        verified = await http.post(
            "/v1/auth/client/step-up/verify",
            cookies={CLIENT_COOKIE: cookie},
            json={"code": code, "action": action},
        )
        exported = await http.get(
            "/v1/calls/export.csv",
            headers={"X-Org-Slug": slug, "X-Confirm-Action": action},
            cookies={CLIENT_COOKIE: cookie},
        )
    assert verified.status_code == 200, verified.text
    assert exported.status_code == 200, exported.text


# ═══════════════ D-730: what a view-as session may not do ═══════════════


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/numbers/own/purchase"),
        ("POST", f"/v1/numbers/own/{uuid.uuid4()}/release"),
        ("POST", "/v1/numbers/purchase"),
        ("POST", "/v1/integrations/endpoints"),
        ("POST", "/v1/integrations/endpoints/sheets"),
        ("DELETE", f"/v1/integrations/endpoints/{uuid.uuid4()}"),
        ("POST", "/v1/integrations/credentials"),
        ("POST", f"/v1/integrations/credentials/{uuid.uuid4()}/rotate"),
        ("DELETE", f"/v1/integrations/credentials/{uuid.uuid4()}"),
        # D-746: confirming a number is the business's own, and placing the test call.
        ("POST", "/v1/forwarding/lines"),
        ("POST", f"/v1/forwarding/lines/{uuid.uuid4()}/tests"),
    ],
)
async def test_view_as_cannot_buy_numbers_or_change_endpoints_or_credentials(
    method: str, path: str
) -> None:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'View As', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    org = await _org()
    async with _client() as http:
        headers = await view_as_headers(http, f"dev:admin:{admin_id}", str(org["slug"]))
        response = await http.request(method, path, headers=headers, json={})
    assert response.status_code == 403, f"{method} {path}: {response.text}"
    body = response.json()
    assert body["type"].endswith("/impersonation_not_available_here"), body
    assert body["remediation"]
