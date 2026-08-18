"""Who may take a client's unmasked contact list out of the building.

Every list surface masks phone numbers to the last two digits (hard rule 6). The CSV
export is the deliberate exception — a masked contact export is useless, and the data is
the client's own — so the whole safety argument rests on two things the redaction
guardrail's allowlist asserts about it: that it is ROLE-GATED and that it is AUDITED.

It was gated on `leads:read`, which `staff` holds. The gate was "any logged-in
employee", and the exemption was describing a control that did not exist.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from apps.api.core.rbac import ROLE_PERMISSIONS
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

EXPORT = "/v1/leads/export.csv"


async def _tenant_with_member(role: str) -> tuple[uuid.UUID, str, str, str]:
    """(tenant_id, slug, token, phone) — one org, one member in `role`, one lead."""
    created = await admin_service.create_organization(
        name="Export Motors",
        slug=f"exp-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"

    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :phone, 'Ravi', "
                "'inbound_call', 'new', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "aid": agent_id, "phone": phone},
        )
    return tenant_id, str(slug), f"dev:client:{user_id}", phone


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_staff_cannot_export_a_clients_unmasked_contact_list() -> None:
    _tenant_id, slug, token, phone = await _tenant_with_member("staff")

    async with _client() as http:
        response = await http.get(
            EXPORT, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 403, "a staff account walked out with full numbers"
    assert response.json()["kind"] == "permission"
    assert phone not in response.text


async def test_an_owner_can_export_and_the_export_is_recorded() -> None:
    """The other half: the gate must not be so tight that the feature is gone. An
    export that leaves no audit row is the version of this endpoint that should not
    exist — the masking is waived BECAUSE the taking is recorded."""
    tenant_id, slug, token, phone = await _tenant_with_member("owner")

    async with _client() as http:
        response = await http.get(
            EXPORT, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert phone in response.text, "a masked export would be useless — that is the point"

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type FROM audit_log WHERE action = 'leads.export' "
                    "AND tenant_id = :t ORDER BY at DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None, "an unmasked export must leave a record of who took it"
    assert (row[0], row[1]) == ("user", "lead_export")


def test_the_export_permission_is_one_no_staff_role_holds() -> None:
    """Stated as a property of the registry, not of today's role table: if someone later
    grants `calls:read_raw` to `staff`, this fails here rather than in an incident."""
    assert "calls:read_raw" not in ROLE_PERMISSIONS["staff"]
    assert "calls:read_raw" not in ROLE_PERMISSIONS["operator"]
    assert "calls:read_raw" in ROLE_PERMISSIONS["owner"]
