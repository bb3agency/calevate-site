"""F-10: a campaign can be archived, restored and deleted, by its client or by an operator.

One service (`campaigns/archive`) behind the client's buttons, the operator's endpoint and
Pip, so every door keeps the same rules: archive anything (a running campaign is paused,
never left running), restore to what archive left (never running), delete only a draft that
never dialled. An archived campaign is never dialled. An operator's archive tells the client
in the app, by email and, only where the owner opted in, on WhatsApp.

Concurrency: every case creates its own run-unique tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.campaigns import service as campaigns_service
from apps.api.campaigns.archive_admin_routes import archive_confirmation, delete_confirmation
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import campaign_archive_notice as notice
from apps.workers.whatsapp import Destination, SendResult, SendStatus
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _agent(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        return UUID(str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()))


async def _campaign(tenant_id: UUID, *, status: str = "draft", name: str = "Renewals") -> UUID:
    agent_id = await _agent(tenant_id)
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "concurrency, launched_at, created_at, updated_at) VALUES (:id, :t, :a, :n, "
                "'service', :s, 1, :launched, now(), now())"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": agent_id,
                "n": name,
                "s": status,
                "launched": None if status == "draft" else datetime.now(UTC),
            },
        )
    return campaign_id


async def _a_call_on(tenant_id: UUID, campaign_id: UUID) -> None:
    agent_id = await _agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, engine_call_id, "
                "direction, status, created_at, updated_at) VALUES (:id, :t, :a, :c, :e, "
                "'outbound', 'completed', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "c": campaign_id, "e": f"e-{uuid7()}"},
        )


async def _row(tenant_id: UUID, campaign_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT status, archived_at, archived_by_realm, archive_reason "
                    "FROM campaigns WHERE id = :id"
                ),
                {"id": campaign_id},
            )
        ).first()


async def _audits(tenant_id: UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :t ORDER BY created_at, id"),
                {"t": tenant_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


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


def _code(response: Any) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


# --- the client's buttons --------------------------------------------------------------


async def test_a_client_archives_a_running_campaign_which_pauses_and_leaves_the_list() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, status="running")
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        archived = await http.post(f"/v1/campaigns/{campaign_id}/archive", headers=headers)
        again = await http.post(f"/v1/campaigns/{campaign_id}/archive", headers=headers)
        listed = await http.get("/v1/campaigns/page", headers=headers)
        shelf = await http.get("/v1/campaigns/page?archived=true", headers=headers)
        resumed = await http.post(f"/v1/campaigns/{campaign_id}/resume", headers=headers)

    assert archived.status_code == 200, archived.text
    assert archived.json() == {"changed": True, "status": "paused"}
    assert again.json()["changed"] is False, "a second press is the same request"
    assert [i["id"] for i in listed.json()["items"]] == []
    assert listed.json()["archived_total"] == 1
    assert [i["id"] for i in shelf.json()["items"]] == [str(campaign_id)]
    assert resumed.status_code == 409 and _code(resumed) == "campaign_archived"
    row = await _row(tenant_id, campaign_id)
    assert (row[0], row[2]) == ("paused", "client") and row[1] is not None
    assert (await _audits(tenant_id)).count("campaign.archived") == 1


async def test_restore_brings_it_back_paused_never_running() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, status="running")
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        await http.post(f"/v1/campaigns/{campaign_id}/archive", headers=headers)
        restored = await http.post(f"/v1/campaigns/{campaign_id}/restore", headers=headers)
    assert restored.json() == {"changed": True, "status": "paused"}
    row = await _row(tenant_id, campaign_id)
    assert row[0] == "paused" and row[1] is None and row[2] is None
    assert "campaign.restored" in await _audits(tenant_id)


async def test_a_draft_that_never_dialled_is_deleted_and_one_that_did_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    fresh = await _campaign(tenant_id, name="Fresh")
    dialled = await _campaign(tenant_id, name="Dialled")
    await _a_call_on(tenant_id, dialled)
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        gone = await http.delete(f"/v1/campaigns/{fresh}", headers=headers)
        kept = await http.delete(f"/v1/campaigns/{dialled}", headers=headers)
    assert gone.json() == {"outcome": "deleted"}
    assert await _row(tenant_id, fresh) is None
    assert kept.status_code == 409 and _code(kept) == "campaign_has_history"
    assert (await _row(tenant_id, dialled))[0] == "draft", "refused means untouched"


async def test_another_tenant_cannot_archive_or_restore_this_campaign() -> None:
    owner, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(owner)
    _other, _slug2, other_token = await _make_tenant()
    headers = {"Authorization": f"Bearer {other_token}"}
    async with _client() as http:
        archived = await http.post(f"/v1/campaigns/{campaign_id}/archive", headers=headers)
        deleted = await http.delete(f"/v1/campaigns/{campaign_id}", headers=headers)
    assert archived.status_code == 404 and deleted.status_code == 404
    assert (await _row(owner, campaign_id))[1] is None


# --- never dialled -----------------------------------------------------------------------


async def test_the_dispatch_tick_never_claims_an_archived_campaign() -> None:
    """Even a row that says running (a state the service never leaves, written here by hand)
    is skipped while archived: the dispatcher's claim asks `archived_at IS NULL`."""
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, status="running")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET archived_at = now(), archived_by_realm = 'client' "
                "WHERE id = :id"
            ),
            {"id": campaign_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, status, "
                "attempts, created_at, updated_at) VALUES (:i, :t, :c, '+919800000001', "
                "'pending', 0, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": campaign_id},
        )
    from apps.workers import campaign_dispatch

    async with tenant_session(tenant_id) as session:
        budget = (
            await session.execute(campaign_dispatch._TENANT_BUDGET_SQL, {"tid": tenant_id})
        ).first()
    listed = [c["id"] for c in (budget[1] or [])] if budget else []
    assert str(campaign_id) not in listed
    async with tenant_session(tenant_id) as session:
        blockers = await campaigns_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert "campaign_archived" in {b.rule for b in blockers}


# --- the operator, and the client being told ---------------------------------------------


async def _outbox(tenant_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid ORDER BY created_at, id"
                ),
                {"job": notice.NOTICE_JOB, "tid": str(tenant_id)},
            )
        ).all()
    return [row[0] for row in rows]


async def test_an_operator_archive_needs_a_reason_and_confirmation_and_queues_a_notice() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, status="running", name="Diwali follow-up")
    token = await _admin()
    path = f"/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/archive"
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        unconfirmed = await http.post(path, headers=headers, json={"reason": "Complaints"})
        no_reason = await http.post(
            path,
            headers={**headers, "X-Confirm-Action": archive_confirmation(campaign_id)},
            json={"reason": ""},
        )
        done = await http.post(
            path,
            headers={**headers, "X-Confirm-Action": archive_confirmation(campaign_id)},
            json={"reason": "Several people asked not to be called"},
        )
    assert unconfirmed.status_code in (403, 428), unconfirmed.text
    assert no_reason.status_code == 422
    assert done.status_code == 200, done.text
    assert done.json() == {"changed": True, "status": "paused", "client_notified": True}
    row = await _row(tenant_id, campaign_id)
    assert (row[2], row[3]) == ("admin", "Several people asked not to be called")
    queued = await _outbox(tenant_id)
    assert len(queued) == 1
    assert queued[0]["campaign"] == "Diwali follow-up" and queued[0]["event"] == "archived"
    assert "campaign.archived" in await _audits(tenant_id)


async def test_an_operator_cannot_delete_a_campaign_that_dialled() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(tenant_id)
    await _a_call_on(tenant_id, campaign_id)
    token = await _admin()
    async with _client() as http:
        refused = await http.request(
            "DELETE",
            f"/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": delete_confirmation(campaign_id),
            },
            json={"reason": "Test list"},
        )
    assert refused.status_code == 409 and _code(refused) == "campaign_has_history"
    assert await _outbox(tenant_id) == [], "nothing happened, so nobody is told"


class _Mail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, **kwargs: Any) -> bool:
        self.sent.append(kwargs)
        return True


class _WhatsApp:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, message: Any) -> SendResult:
        self.sent.append(message)
        return SendResult(SendStatus.DELIVERED)


@pytest.mark.parametrize("opted_in", [True, False])
async def test_the_client_is_told_in_the_app_by_email_and_on_whatsapp_only_if_opted_in(
    monkeypatch: pytest.MonkeyPatch, opted_in: bool
) -> None:
    tenant_id, slug, _token = await _make_tenant()
    mail, chat = _Mail(), _WhatsApp()
    monkeypatch.setattr(notice, "get_transport", lambda _purpose=None: mail)
    monkeypatch.setattr(notice, "get_whatsapp_transport", lambda: chat)
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)

    async def _destination(_session: Any, _tenant: Any) -> Destination:
        return Destination(
            to_e164="+919800000099", opt_in_at=datetime.now(UTC) if opted_in else None
        )

    monkeypatch.setattr(notice, "resolve_destination", _destination)
    outcome = await notice.notify_campaign_archived(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "event": "archived",
            "campaign": "Diwali follow-up",
            "reason": "Several people asked not to be called",
            "slug": slug,
        },
    )
    assert outcome == "sent"
    assert mail.sent and "Diwali follow-up" in mail.sent[0]["subject"]
    assert "Several people asked not to be called" in mail.sent[0]["body"]
    assert len(chat.sent) == (1 if opted_in else 0), "never on WhatsApp without an opt-in"
    async with untenanted_session() as session:
        posted = (
            await session.execute(
                text(
                    "SELECT message FROM platform_announcements WHERE target_tenant_id = :t "
                    "AND audience = 'tenant'"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert len(posted) == 1 and "Diwali follow-up" in posted[0][0]
