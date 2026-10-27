"""D-893 lane L6: the account routes a page and Pip share.

* `PATCH /v1/integrations/endpoints/{id}` changes events and opt-ins, never the address;
* `PATCH /v1/lead-sources/{id}` points a source at another agent;
* `PUT /v1/billing/wallet/low-balance-alert` sets the client's own warning line, which the
  wallet read, the ledger's crossing and the attention queue then use;
* `GET /v1/call-lines` shows the client its lines.

Every test mints its own tenant.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
from apps.api.billing import service as billing_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    if confirm is not None:
        headers["X-Confirm-Action"] = f"{confirm}:{slug}"
    return headers


def _code(response: httpx.Response) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _audit_actions(tenant_id: uuid.UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :t ORDER BY at"),
                {"t": str(tenant_id)},
            )
        ).all()
    return [str(r[0]) for r in rows]


# --- endpoints ----------------------------------------------------------------------------


async def _endpoint(http: httpx.AsyncClient, slug: str, token: str) -> str:
    created = await http.post(
        "/v1/integrations/endpoints",
        json={"url": "https://crm.example.com/hooks/calevate", "events": ["lead.created"]},
        headers=_headers(slug, token, "create_endpoint"),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_an_endpoint_edit_changes_events_and_opt_ins_and_is_audited() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _endpoint(http, slug, token)
        change = {"events": ["lead.created", "call.completed"], "include_transcript": True}
        uncoded = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}", json=change, headers=_headers(slug, token)
        )
        unchanged = await http.get("/v1/integrations/endpoints", headers=_headers(slug, token))
        edited = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json=change,
            headers=_headers(slug, token, "endpoint_opt_in"),
        )
    # Switching a transcript on starts call content leaving the account: the emailed code.
    assert uncoded.status_code == 403, uncoded.text
    assert _code(uncoded) == "step_up_required"
    assert unchanged.json()[0]["include_transcript"] is False, "a refusal rolls the edit back"
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert sorted(body["events"]) == ["call.completed", "lead.created"]
    assert body["include_transcript"] is True
    assert body["url"] == "https://crm.example.com/hooks/calevate"
    assert "integration_endpoint.updated" in await _audit_actions(tenant_id)


async def test_events_and_switching_off_need_no_code() -> None:
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _endpoint(http, slug, token)
        url = f"/v1/integrations/endpoints/{endpoint_id}"
        opened = await http.patch(
            url,
            json={"events": ["call.completed"], "include_transcript": True},
            headers=_headers(slug, token, "endpoint_opt_in"),
        )
        events_only = await http.patch(
            url,
            json={"events": ["call.completed", "lead.created"], "include_transcript": True},
            headers=_headers(slug, token),
        )
        closed = await http.patch(
            url, json={"events": ["call.completed"]}, headers=_headers(slug, token)
        )
    assert opened.status_code == 200, opened.text
    assert events_only.status_code == 200, events_only.text
    assert closed.status_code == 200, closed.text
    assert closed.json()["include_transcript"] is False


async def test_an_endpoint_edit_refuses_the_address_and_the_lone_raw_switch() -> None:
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _endpoint(http, slug, token)
        moved = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.created"], "url": "https://elsewhere.example.com/x"},
            headers=_headers(slug, token),
        )
        raw = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.created"], "include_raw_transcript": True},
            headers=_headers(slug, token),
        )
        ready = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["call.recording_ready"]},
            headers=_headers(slug, token),
        )
    assert moved.status_code == 422
    assert raw.status_code == 422
    assert _code(raw) == "raw_transcript_requires_transcript"
    assert _code(ready) == "recording_ready_requires_recording_url"


async def test_a_switched_off_or_foreign_endpoint_is_not_edited() -> None:
    _tenant_id, slug, token = await _make_tenant()
    _other_id, other_slug, other_token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _endpoint(http, slug, token)
        foreign = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.updated"]},
            headers=_headers(other_slug, other_token),
        )
        off = await http.delete(
            f"/v1/integrations/endpoints/{endpoint_id}", headers=_headers(slug, token)
        )
        assert off.status_code == 204
        after_off = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.updated"]},
            headers=_headers(slug, token),
        )
    assert foreign.status_code == 404
    assert after_off.status_code == 422
    assert _code(after_off) == "endpoint_inactive"


async def test_staff_may_not_edit_an_endpoint() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _endpoint(http, slug, token)
    staff = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": staff, "e": f"{staff}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'staff', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": staff},
        )
    async with _client() as http:
        refused = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.updated"]},
            headers=_headers(slug, f"dev:client:{staff}"),
        )
    assert refused.status_code == 403


# --- lead sources --------------------------------------------------------------------------


async def test_a_lead_source_is_pointed_at_another_agent_or_none() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    async with _client() as http:
        created = await http.post(
            "/v1/lead-sources",
            json={"source": "website_form", "mapping": {"phone": "phone"}},
            headers=_headers(slug, token),
        )
        assert created.status_code == 201, created.text
        source_id = created.json()["id"]
        pointed = await http.patch(
            f"/v1/lead-sources/{source_id}",
            json={"agent_id": str(agent_id)},
            headers=_headers(slug, token),
        )
        cleared = await http.patch(
            f"/v1/lead-sources/{source_id}", json={"agent_id": None}, headers=_headers(slug, token)
        )
        foreign = await http.patch(
            f"/v1/lead-sources/{source_id}",
            json={"agent_id": str(uuid.uuid4())},
            headers=_headers(slug, token),
        )
    assert pointed.status_code == 200, pointed.text
    assert pointed.json()["agent_id"] == str(agent_id)
    assert cleared.json()["agent_id"] is None
    assert foreign.status_code == 404
    assert (await _audit_actions(tenant_id)).count("lead_source.agent_changed") == 2


# --- the low-balance line ------------------------------------------------------------------


async def test_the_low_balance_line_is_the_clients_once_chosen() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        before = await http.get("/v1/billing/wallet", headers=_headers(slug, token))
        chosen = await http.put(
            "/v1/billing/wallet/low-balance-alert",
            json={"threshold_inr": "750.00"},
            headers=_headers(slug, token),
        )
        after = await http.get("/v1/billing/wallet", headers=_headers(slug, token))
        float_refused = await http.put(
            "/v1/billing/wallet/low-balance-alert",
            json={"threshold_inr": 750.5},
            headers=_headers(slug, token),
        )
        cleared = await http.put(
            "/v1/billing/wallet/low-balance-alert",
            json={"threshold_inr": None},
            headers=_headers(slug, token),
        )
    assert before.json()["low_balance_threshold_inr"] == "200.00"
    assert before.json()["low_balance_alert_chosen"] is False
    assert chosen.status_code == 200, chosen.text
    assert chosen.json() == {"threshold_inr": "750.00", "chosen": True}
    assert after.json()["low_balance_threshold_inr"] == "750.00"
    assert after.json()["low_balance_alert_chosen"] is True
    assert float_refused.status_code == 422
    assert cleared.json() == {"threshold_inr": "200.00", "chosen": False}
    assert "billing.low_balance_alert.set" in await _audit_actions(tenant_id)


async def test_the_ledger_warns_at_the_clients_line_and_zero_stops_the_low_warning() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await billing_service.set_low_balance_line(
            session, tenant_id=tenant_id, threshold_inr=Decimal("1000")
        )
        assert (
            billing_service.crossed_downwards(Decimal("1200"), Decimal("900"), Decimal("1000"))
            == billing_service.WALLET_LEVEL_LOW
        )
        assert await billing_service.low_balance_line(session, tenant_id=tenant_id) == Decimal(
            "1000.00"
        )
        await billing_service.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("1200"), reason="topup", ref="t-1"
        )
        balance = await billing_service.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("-300"), reason="usage", ref="u-1"
        )
        assert balance.is_low is True
        await billing_service.set_low_balance_line(
            session, tenant_id=tenant_id, threshold_inr=Decimal("0")
        )
        assert (await billing_service.get_balance(session, tenant_id=tenant_id)).is_low is False
    assert billing_service.crossed_downwards(Decimal("10"), Decimal("5"), Decimal("0")) is None
    assert billing_service.crossed_downwards(Decimal("10"), Decimal("-5"), Decimal("0")) == (
        billing_service.WALLET_LEVEL_EMPTY
    )


async def test_staff_may_not_move_the_low_balance_line() -> None:
    tenant_id, slug, _token = await _make_tenant()
    staff = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": staff, "e": f"{staff}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'staff', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": staff},
        )
    async with _client() as http:
        refused = await http.put(
            "/v1/billing/wallet/low-balance-alert",
            json={"threshold_inr": "500.00"},
            headers=_headers(slug, f"dev:client:{staff}"),
        )
    assert refused.status_code == 403


# --- call lines -------------------------------------------------------------------------------


async def test_a_client_reads_its_own_call_lines() -> None:
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        lines = await http.get("/v1/call-lines", headers=_headers(slug, token))
    assert lines.status_code == 200, lines.text
    body = lines.json()
    assert body["call_lines"] >= 1
    assert body["in_progress"] == 0
    assert isinstance(body["on_trial"], bool)
