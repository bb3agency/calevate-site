"""The D-943 compliance pack over HTTP, and the desk's refusals the pure suite does not reach.

`compliance_pack_test` drives the services; this file drives the routes a client's screen
calls — the rights desk, the promo check, a campaign's call purpose, the short notice and a
lead source's consent basis — through the real app, so the role checks, the response
shapes and the audit rows are what is tested.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents import script_builder
from apps.api.compliance import a2p_filing, rights_desk
from apps.api.compliance.export import subject_ref
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.ingest import service as ingest_service
from apps.api.main import app
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.a2p_filing_test import _authorised, _operator, _status
from tests.outbound_consent_policy_test import _fresh_phone, _tenant

pytestmark = pytest.mark.rls

DESK = "/v1/compliance/rights-requests"
_OFFER = "Hello! We have a special Diwali offer, 20% off, today only."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _audit_actions(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text("SELECT action FROM audit_log WHERE tenant_id = :t ORDER BY created_at"),
            {"t": tenant_id},
        )
        return [str(row[0]) for row in rows]


# --- the rights desk -------------------------------------------------------------------


async def test_the_desk_logs_lists_and_closes_a_request_over_http() -> None:
    tenant_id, _agent = await _tenant("d943-desk-http")
    headers = await _org_headers(tenant_id)
    asked = datetime.now(UTC) - timedelta(days=80)
    async with _client() as http:
        logged = await http.post(
            DESK,
            headers=headers,
            json={
                "kind": "access",
                "channel": "email",
                "phone": _fresh_phone(),
                "received_at": asked.isoformat(),
            },
        )
        assert logged.status_code == 201, logged.text
        request = logged.json()
        assert request["days_left"] == 9
        assert request["due_soon"] is True
        assert request["overdue"] is False

        desk = (await http.get(DESK, headers=headers)).json()
        assert [item["id"] for item in desk["items"]] == [request["id"]]
        assert (desk["open"], desk["due_soon"], desk["overdue"]) == (1, 1, 0)
        assert desk["response_days"] == 90

        closed = await http.post(
            f"{DESK}/{request['id']}/close",
            headers=headers,
            json={"status": "answered", "outcome": "exported"},
        )
        assert closed.status_code == 200, closed.text
        body = closed.json()
        assert body["status"] == "answered"
        # A closed request has no clock.
        assert (body["days_left"], body["due_soon"], body["overdue"]) == (None, False, False)
    assert await _audit_actions(tenant_id) == [
        "dpdp.rights_request_logged",
        "dpdp.rights_request_closed",
    ]


async def test_an_erasure_closed_over_http_names_its_certificate() -> None:
    tenant_id, _agent = await _tenant("d943-desk-erase-http")
    headers = await _org_headers(tenant_id)
    phone = _fresh_phone()
    deletion_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, "
                "requested_at, created_at) VALUES (:id, :t, :p, :ref, now(), now())"
            ),
            {"id": deletion_id, "t": tenant_id, "p": phone, "ref": subject_ref(phone)},
        )
    async with _client() as http:
        request = (
            await http.post(
                DESK, headers=headers, json={"kind": "erasure", "channel": "phone", "phone": phone}
            )
        ).json()
        unknown = await http.post(
            f"{DESK}/{request['id']}/close",
            headers=headers,
            json={"status": "answered", "outcome": "erased", "deletion_request_id": str(uuid7())},
        )
        assert unknown.status_code == 404
        closed = await http.post(
            f"{DESK}/{request['id']}/close",
            headers=headers,
            json={
                "status": "answered",
                "outcome": "erased",
                "deletion_request_id": str(deletion_id),
            },
        )
    assert closed.status_code == 200, closed.text
    assert closed.json()["deletion_request_id"] == str(deletion_id)


async def _log(tenant_id: uuid.UUID, **over: object) -> rights_desk.RightsRequest:
    kwargs: dict[str, object] = {
        "kind": "access",
        "channel": "email",
        "phone_e164": _fresh_phone(),
        "received_at": None,
        "created_by": None,
        **over,
    }
    async with tenant_session(tenant_id) as session:
        logged = await rights_desk.log_request(session, tenant_id=tenant_id, **kwargs)  # type: ignore[arg-type]
        await session.commit()
    return logged


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"kind": "complaint"}, "rights_unknown_kind"),
        ({"channel": "fax"}, "rights_unknown_channel"),
        ({"received_at": datetime.now(UTC) - timedelta(days=400)}, "rights_received_too_old"),
    ],
)
async def test_the_desk_refuses_what_it_does_not_log(over: dict[str, object], code: str) -> None:
    tenant_id, _agent = await _tenant("d943-desk-refuse")
    with pytest.raises(ProblemError) as refused:
        await _log(tenant_id, **over)
    assert refused.value.code == code


async def test_a_date_without_a_zone_is_read_as_utc() -> None:
    tenant_id, _agent = await _tenant("d943-desk-naive")
    asked = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
    logged = await _log(tenant_id, received_at=asked)
    assert logged.received_at == asked.replace(tzinfo=UTC)


async def test_only_an_erasure_carries_an_erasure_certificate() -> None:
    tenant_id, _agent = await _tenant("d943-desk-link")
    request = await _log(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await rights_desk.close_request(
                session,
                request_id=request.id,
                status="answered",
                outcome="exported",
                deletion_request_id=uuid7(),
                closed_by=None,
            )
    assert refused.value.code == "rights_erasure_link_unexpected"


# --- the promo check and the call purpose ----------------------------------------------


async def test_any_wording_is_checked_over_http() -> None:
    tenant_id, _agent = await _tenant("d943-promo-http")
    headers = await _org_headers(tenant_id)
    async with _client() as http:
        response = await http.post(
            "/v1/compliance/promo-check",
            headers=headers,
            json={"parts": [{"where": "Opening", "wording": _OFFER, "kind": "opening"}]},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "promotional"
    assert body["blocks_launch"] is True
    assert {f["where"] for f in body["findings"]} == {"Opening"}
    assert all(f["why"] for f in body["findings"])


async def test_an_agents_check_reads_the_draft_being_edited() -> None:
    tenant_id, agent_id = await _tenant("d943-promo-draft")
    headers = await _org_headers(tenant_id)
    path = f"/v1/compliance/promo-check/agents/{agent_id}"
    async with _client() as http:
        saved = (await http.get(path, headers=headers)).json()
        assert saved["reading"] == "saved"
        async with tenant_session(tenant_id) as session:
            await script_builder.save_draft(session, agent_id, CallScript(opening_line=_OFFER))
            await session.commit()
        drafted = (await http.get(path, headers=headers)).json()
    assert drafted["reading"] == "draft"
    assert drafted["places_calls"] is True
    assert drafted["report"]["verdict"] == "promotional"


async def test_a_campaigns_purpose_and_live_script_over_http() -> None:
    from tests.campaigns_test import _ready_campaign
    from tests.compliance_pack_test import _put_live

    tenant_id, agent_id, campaign_id = await _ready_campaign(classification="service", series="160")
    headers = await _org_headers(tenant_id)
    path = f"/v1/compliance/call-purpose/campaigns/{campaign_id}"
    async with _client() as http:
        clean = (await http.get(path, headers=headers)).json()
        assert clean["blocks_launch"] is False
        assert clean["agent_id"] == str(agent_id)
        await _put_live(tenant_id, agent_id, {"opening_line": _OFFER})
        offered = (await http.get(path, headers=headers)).json()
        missing = await http.get(
            f"/v1/compliance/call-purpose/campaigns/{uuid7()}", headers=headers
        )
    assert offered["purpose"]["purpose"] != "promotional"
    assert offered["report"]["verdict"] == "promotional"
    assert offered["blocks_launch"] is True
    assert missing.status_code == 404


# --- the short notice --------------------------------------------------------------------


async def test_the_short_notice_over_http_says_callers_are_remembered_when_they_are() -> None:
    from tests.caller_notice_test import _publish, _remember_callers
    from tests.caller_notice_test import _tenant as _notice_tenant

    tenant_id, agent_id, slug, token = await _notice_tenant()
    await _publish(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    path = "/v1/compliance/caller-notice/short"
    async with _client() as http:
        before = (await http.get(path, params={"language": "en"}, headers=headers)).json()
        await _remember_callers(tenant_id, agent_id)
        after = await http.get(path, params={"language": "te"}, headers=headers)
    assert "kept so we know it if you call again" not in before["notice_markdown"]
    assert after.status_code == 200, after.text
    assert after.json()["language"] == "te"
    assert "మీరు మళ్ళీ కాల్ చేసినప్పుడు" in after.json()["notice_markdown"]
    assert after.json()["disclaimer"]


# --- a lead source's consent basis -------------------------------------------------------


async def test_a_lead_sources_consent_basis_is_set_once_and_audited_once() -> None:
    tenant_id, _agent = await _tenant("d943-basis")
    headers = await _org_headers(tenant_id)
    webhook_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, mapping, "
                "active, created_at, updated_at) VALUES (:i, :t, 'website_form', 's', "
                "CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"i": webhook_id, "t": tenant_id},
        )
    path = f"/v1/lead-sources/{webhook_id}/consent-basis"
    async with _client() as http:
        for _ in range(2):
            response = await http.put(path, headers=headers, json={"consent_basis": "application"})
            assert response.status_code == 200, response.text
            assert response.json()["consent_basis"] == "application"
        missing = await http.put(
            f"/v1/lead-sources/{uuid.uuid4()}/consent-basis",
            headers=headers,
            json={"consent_basis": "inquiry"},
        )
    assert missing.status_code == 404
    assert (await _audit_actions(tenant_id)).count("lead_source.consent_basis_changed") == 1


async def test_setting_the_basis_returns_what_it_was() -> None:
    tenant_id, _agent = await _tenant("d943-basis-svc")
    webhook_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, mapping, "
                "active, created_at, updated_at) VALUES (:i, :t, 'website_form', 's', "
                "CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"i": webhook_id, "t": tenant_id},
        )
        first = await ingest_service.set_source_consent_basis(
            session, webhook_id=webhook_id, consent_basis="application"
        )
        second = await ingest_service.set_source_consent_basis(
            session, webhook_id=webhook_id, consent_basis="inquiry"
        )
        await session.rollback()
    assert (first, second) == ("inquiry", "application")


# --- the calling-number filing -----------------------------------------------------------


async def test_a_number_listed_twice_in_one_filing_is_filed_once() -> None:
    tenant_id, _agent, numbers = await _authorised("a2p-file-twice")
    admin_id, _headers = await _operator()
    async with tenant_session(tenant_id) as session:
        _row, filed = await a2p_filing.record_filing(
            session,
            tenant_id=tenant_id,
            numbers=[numbers[0], numbers[0]],
            filed_on=datetime(2026, 11, 1, tzinfo=UTC).date(),
            filing_reference="OAP-ACK-TWICE",
            recorded_by_admin_id=admin_id,
        )
    assert list(filed) == [numbers[0]]
    assert numbers[0] not in (await _status(tenant_id)).unfiled
