"""Pushed lead sources (D-942): IndiaMART, the property portals and LeadSquared.

The properties held here:

- a portal push authenticates by the `token` in its URL (it cannot set our header), and
  only the receiver written for it accepts one;
- every verified push is answered 200, refusals included, because IndiaMART switches the
  push off after 48 hours of non-200 answers;
- a retry of the same enquiry, even with changed envelope text, is ONE lead and one dial;
- a portal enquiry is the person's own written inquiry: it is dialled and leaves a
  `portal_enquiry` grant that expires seven days after the enquiry, while a bought lead,
  a catalogue view or an enquiry older than seven days lands and is never dialled;
- LeadSquared's do-not-call flag is honoured, and LeadSquared echoing our own write back is
  not a second call;
- the LeadSquared destination writes Lead.Capture with the keys in the query string only,
  and tells a permanent refusal from a transient one.

The IndiaMART fixture follows the field list on help.indiamart.com's Push API page (read 30
Oct 2026); the LeadSquared ones follow apidocs.leadsquared.com/capture-lead and the
lead-create trigger shape on help.leadsquared.com.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.actions import credentials as creds
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.ingest import portals
from apps.api.ingest.routes import PUSH_UNREADABLE_REASON, SECRET_HEADER
from apps.api.integrations import leadsquared as lsq
from apps.api.integrations import service as integrations_service
from apps.api.main import app
from apps.workers import leadsquared_sync
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import (
    accept_agreements,
    arm_agent_for_outbound,
    create_org_with_receptionist,
    fund_wallet,
)

SECRET = "portal-push-secret-for-tests"
# The gate's clock is pinned to 11:00 IST so the calling window is open; the seven-day
# window runs on the real clock, so enquiry times are written relative to it.
NOW = datetime(2026, 8, 11, 5, 30, tzinfo=UTC)


def _ist_text(instant: datetime) -> str:
    """An IndiaMART `QUERY_TIME`: IST wall clock, no offset."""
    return (instant + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


def _whole_second(instant: datetime) -> datetime:
    return instant.replace(microsecond=0)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.api.compliance.service.ist_now", lambda: NOW + timedelta(hours=5, minutes=30)
    )


def _indiamart(
    *,
    query_id: str = "2795678901",
    query_type: str = "W",
    mobile: str = "+91-9876501234",
    name: str = "Ravi Kumar",
    query_time: str | None = None,
    status: str = "Lead sent successfully",
) -> dict[str, Any]:
    query_time = query_time or _ist_text(datetime.now(UTC) - timedelta(minutes=2))
    return {
        "CODE": 200,
        "STATUS": status,
        "RESPONSE": {
            "UNIQUE_QUERY_ID": query_id,
            "QUERY_TYPE": query_type,
            "QUERY_TIME": query_time,
            "SENDER_NAME": name,
            "SENDER_MOBILE": mobile,
            "SENDER_EMAIL": "ravi@example.com",
            "SUBJECT": "Requirement for 2BHK",
            "SENDER_COMPANY": "",
            "SENDER_CITY": "Hyderabad",
            "SENDER_STATE": "Telangana",
            "SENDER_COUNTRY_ISO": "IN",
            "QUERY_PRODUCT_NAME": "2BHK Apartment Gachibowli",
            "QUERY_MESSAGE": "Please share price and site visit timings.",
            "QUERY_MCAT_NAME": "Residential Apartments",
            "CALL_DURATION": "",
            "RECEIVER_MOBILE": "",
        },
    }


def _leadsquared(*, phone: str = "+91-9876505555", do_not_call: str = "0") -> dict[str, Any]:
    lead = {
        "ProspectID": f"{uuid.uuid4()}",
        "FirstName": "Anitha",
        "LastName": "Reddy",
        "EmailAddress": "anitha@example.com",
        "Phone": phone,
        "Mobile": "",
        "DoNotCall": do_not_call,
        "Source": "Website",
    }
    return {"After": dict(lead), "Current": dict(lead)}


async def _tenant_with_source(source: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant_id, agent_id, webhook_id): a live outbound agent and one pushed source with
    its preset mapping."""
    reset_engine_cache()
    created = await create_org_with_receptionist(
        name="Portal Estates",
        slug=f"prt-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await accept_agreements(uuid.UUID(str(tenant_id)))
    await fund_wallet(uuid.UUID(str(tenant_id)))
    webhook_id = uuid.uuid4()
    ref = f"fakeagent_prt_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, agent_id, "
                "mapping, active, created_at, updated_at) VALUES (:i, :t, :src, :s, :a, "
                "CAST(:m AS jsonb), true, now(), now())"
            ),
            {
                "i": webhook_id,
                "t": tenant_id,
                "src": source,
                "s": SECRET,
                "a": agent_id,
                "m": json.dumps(portals.preset_mapping(source)),
            },
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    await arm_agent_for_outbound(tenant_id, agent_id)
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)), webhook_id


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _push(webhook_id: uuid.UUID, body: Any, **kwargs: Any) -> httpx.Response:
    params = kwargs.pop("params", {"token": SECRET})
    async with _client() as http:
        if isinstance(body, str):
            return await http.post(
                f"/hooks/v1/ingest/push/{webhook_id}",
                content=body,
                params=params,
                headers={"content-type": "application/x-www-form-urlencoded"},
                **kwargs,
            )
        return await http.post(
            f"/hooks/v1/ingest/push/{webhook_id}", json=body, params=params, **kwargs
        )


async def _leads(tenant_id: uuid.UUID) -> list[tuple[str, str | None, dict[str, Any]]]:
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text("SELECT phone_e164, name, data FROM leads"))).all()
    return [(str(r[0]), r[1], dict(r[2] or {})) for r in rows]


async def _blocked_rules(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT payload->>'rule' FROM lead_events WHERE payload->>'kind' = 'blocked'")
            )
        ).all()
    return [str(r[0]) for r in rows]


async def _grants(tenant_id: uuid.UUID) -> list[tuple[datetime, datetime, dict[str, Any]]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT captured_at, expires_at, evidence FROM consent_ledger "
                    "WHERE consent_source = 'portal_enquiry' AND status = 'granted'"
                )
            )
        ).all()
    return [(r[0], r[1], dict(r[2])) for r in rows]


async def _inbox(webhook_id: uuid.UUID, tenant_id: uuid.UUID) -> list[tuple[str, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status, last_error FROM webhook_inbox_events WHERE provider = :p "
                    "ORDER BY created_at"
                ),
                {"p": f"ingest:{webhook_id}"},
            )
        ).all()
    return [(str(r[0]), r[1]) for r in rows]


# --- shapes, without a database ----------------------------------------------------


def test_the_indiamart_envelope_is_unwrapped_and_its_placeholder_name_dropped() -> None:
    [record] = portals.records("indiamart", _indiamart(name="IndiaMART Buyer"))
    assert record["UNIQUE_QUERY_ID"] == "2795678901"
    cleaned = portals.without_placeholder_name("indiamart", record, "SENDER_NAME")
    assert "SENDER_NAME" not in cleaned, "the agent must never greet 'IndiaMART Buyer'"
    assert portals.records("indiamart", {"CODE": 200}) == []
    assert portals.records("indiamart", "not a body") == []


def test_leadsquared_reads_current_and_falls_back_to_after() -> None:
    body = _leadsquared()
    assert portals.records("leadsquared", body)[0]["FirstName"] == "Anitha"
    only_after = {"After": body["After"]}
    assert portals.records("leadsquared", only_after)[0]["Phone"] == "+91-9876505555"


def test_a_naive_query_time_is_read_as_ist_which_can_only_shorten_the_window() -> None:
    assert portals.enquiry_instant("2026-08-11 11:00:00") == NOW
    assert portals.enquiry_instant("2026-08-11T11:00:00+05:30") == NOW
    assert portals.enquiry_instant("yesterday") is None
    ground = portals.EnquiryGround("indiamart", "1", "W", NOW + timedelta(days=3))
    assert ground.expires_at(received_at=NOW, window=timedelta(days=7)) == NOW + timedelta(
        days=7
    ), "a sender's fast clock must not lengthen the window"


@pytest.mark.parametrize(
    ("query_type", "callable_"),
    [("W", True), ("P", True), ("WA", True), ("B", False), ("BIZ", False), (None, False)],
)
def test_only_an_enquiry_sent_to_the_seller_is_a_ground_to_call(
    query_type: str | None, callable_: bool
) -> None:
    assert portals.EnquiryGround("indiamart", "1", query_type, None).is_enquiry() is callable_


def test_property_portals_have_no_type_field_and_every_record_is_an_enquiry() -> None:
    for source in ("99acres", "magicbricks", "housing"):
        assert portals.EnquiryGround(source, None, None, None).is_enquiry()
    assert portals.enquiry_ground("leadsquared", {"enquiry_id": "x"}) is None


@pytest.mark.parametrize(
    ("value", "flag"),
    [
        ("1", True),
        ("true", True),
        (True, True),
        ("0", False),
        ("", False),
        (None, False),
        (0, False),
    ],
)
def test_the_crm_do_not_call_flag(value: object, flag: bool) -> None:
    assert portals.marked_do_not_call({portals.DO_NOT_CALL_KEY: value}) is flag


# --- the receiver -------------------------------------------------------------------


async def test_an_indiamart_enquiry_is_a_lead_a_call_and_a_seven_day_grant() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    enquired = _whole_second(datetime.now(UTC) - timedelta(minutes=2))
    response = await _push(webhook_id, _indiamart(query_time=_ist_text(enquired)))
    assert response.status_code == 200, response.text
    assert response.json() == {"received": 1, "accepted": 1, "duplicate": 0, "refused": 0}

    [(phone, name, data)] = await _leads(tenant_id)
    assert phone == "+919876501234"
    assert name == "Ravi Kumar"
    assert data["product"] == "2BHK Apartment Gachibowli"
    assert data["city"] == "Hyderabad"
    assert await _blocked_rules(tenant_id) == []

    [(captured, expires, evidence)] = await _grants(tenant_id)
    assert expires == enquired + timedelta(days=7), "the window runs from the enquiry"
    assert captured >= enquired
    assert evidence["enquiry_id"] == "2795678901"
    assert evidence["enquiry_type"] == "W"
    assert evidence["lead_source_id"] == str(webhook_id)


async def test_a_retry_with_changed_envelope_text_is_one_lead() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    first = await _push(webhook_id, _indiamart())
    again = await _push(webhook_id, _indiamart(status="Retry 2"))
    assert first.json()["accepted"] == 1
    assert again.status_code == 200, again.text
    assert again.json()["duplicate"] == 1
    assert len(await _leads(tenant_id)) == 1
    assert len(await _grants(tenant_id)) == 1


async def test_the_token_is_the_credential_and_the_header_works_too() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    wrong = await _push(webhook_id, _indiamart(), params={"token": "nope"})
    missing = await _push(webhook_id, _indiamart(), params={})
    assert wrong.status_code == 401
    assert missing.status_code == 401
    assert await _leads(tenant_id) == []
    by_header = await _push(webhook_id, _indiamart(), params={}, headers={SECRET_HEADER: SECRET})
    assert by_header.status_code == 200, by_header.text


async def test_a_pushed_source_has_no_door_on_the_header_receiver() -> None:
    _, _, webhook_id = await _tenant_with_source("indiamart")
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json=_indiamart(),
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 404


async def test_one_accounts_token_does_not_open_another_accounts_source() -> None:
    tenant_a, _, _ = await _tenant_with_source("indiamart")
    tenant_b, _, webhook_b = await _tenant_with_source("indiamart")
    async with tenant_session(tenant_b) as session:
        await session.execute(
            text("UPDATE inbound_webhooks SET secret_ref = 'b-only-secret' WHERE id = :i"),
            {"i": webhook_b},
        )
    refused = await _push(webhook_b, _indiamart())
    assert refused.status_code == 401
    assert await _leads(tenant_a) == [] and await _leads(tenant_b) == []


@pytest.mark.parametrize("query_type", ["B", "BIZ"])
async def test_a_bought_lead_or_catalogue_view_lands_and_is_never_dialled(query_type: str) -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    response = await _push(webhook_id, _indiamart(query_type=query_type))
    assert response.json()["accepted"] == 1
    assert len(await _leads(tenant_id)) == 1
    assert await _blocked_rules(tenant_id) == [portals.NOT_AN_ENQUIRY_RULE]
    assert await _grants(tenant_id) == []


async def test_an_enquiry_older_than_seven_days_is_not_dialled() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    stale = _ist_text(datetime.now(UTC) - timedelta(days=7, minutes=5))
    response = await _push(webhook_id, _indiamart(query_time=stale))
    assert response.json()["accepted"] == 1
    assert await _blocked_rules(tenant_id) == [portals.ENQUIRY_WINDOW_RULE]
    assert await _grants(tenant_id) == []


async def test_a_lead_with_no_number_is_acked_and_recorded_not_retried() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    response = await _push(webhook_id, _indiamart(mobile=""))
    assert response.status_code == 200, response.text
    assert response.json()["refused"] == 1
    assert await _leads(tenant_id) == []
    assert await _inbox(webhook_id, tenant_id) == [("failed", "ingest_no_phone")]


async def test_a_body_that_is_not_a_lead_is_acked_and_recorded() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("indiamart")
    response = await _push(webhook_id, "hello=world")
    assert response.status_code == 200, response.text
    assert response.json()["refused"] == 1
    assert await _inbox(webhook_id, tenant_id) == [("failed", PUSH_UNREADABLE_REASON)]


async def test_a_99acres_form_post_with_the_preset_mapping_is_a_call() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("99acres")
    body = "name=Sita&phone=9876502222&email=s%40example.com&project=Kokapet+Towers&lead_id=A1"
    response = await _push(webhook_id, body)
    assert response.json()["accepted"] == 1, response.text
    [(phone, name, data)] = await _leads(tenant_id)
    assert (phone, name, data["project"]) == ("+919876502222", "Sita", "Kokapet Towers")
    [(captured, expires, evidence)] = await _grants(tenant_id)
    assert expires == captured + timedelta(days=7), "no enquiry time: it runs from receipt"
    assert evidence["enquiry_id"] == "A1"


async def test_leadsquared_do_not_call_is_honoured() -> None:
    tenant_id, _, webhook_id = await _tenant_with_source("leadsquared")
    response = await _push(webhook_id, _leadsquared(do_not_call="1"))
    assert response.json()["accepted"] == 1, response.text
    assert await _blocked_rules(tenant_id) == [portals.CRM_DO_NOT_CALL_RULE]
    assert await _grants(tenant_id) == [], "a CRM lead is the client's assertion, not an enquiry"


async def _lead_from_another_source(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str, *, sent_to_leadsquared: bool
) -> None:
    """A lead that came from elsewhere, told to the account's LeadSquared destination
    through the real fan-out when `sent_to_leadsquared`."""
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:id, :t, :a, :p, 'Kiran', 'webhook', "
                "'new', '{}'::jsonb, now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "p": phone},
        )
        if sent_to_leadsquared:
            await session.execute(
                text(
                    "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                    "mapping, active, created_at, updated_at) VALUES (:id, :t, 'leadsquared', "
                    "'https://api-in21.leadsquared.com', 'x', ARRAY['lead.created'], "
                    "'{}'::jsonb, true, now(), now())"
                ),
                {"id": uuid.uuid4(), "t": tenant_id},
            )
            await integrations_service.enqueue_event(
                session,
                tenant_id=tenant_id,
                event="lead.created",
                data={"lead_id": str(lead_id), "phone": phone, "name": "Kiran"},
            )


async def test_leadsquared_echoing_our_own_write_is_not_a_second_call() -> None:
    tenant_id, agent_id, webhook_id = await _tenant_with_source("leadsquared")
    await _lead_from_another_source(tenant_id, agent_id, "+919876507777", sent_to_leadsquared=True)
    echo = await _push(webhook_id, _leadsquared(phone="9876507777"))
    assert echo.json()["duplicate"] == 1, echo.text
    assert len(await _leads(tenant_id)) == 1


@pytest.mark.parametrize(
    ("status", "consumed"),
    [("published", True), ("failed", False)],
    ids=["delivered", "dead_lettered"],
)
async def test_the_echo_is_recognised_after_our_write_has_left_the_queue(
    status: str, consumed: bool
) -> None:
    """LeadSquared's webhook can arrive after our delivery finished: the outbox row is then
    `published` with `consumed_at` set, or `failed` and replayable, never `pending`."""
    tenant_id, agent_id, webhook_id = await _tenant_with_source("leadsquared")
    await _lead_from_another_source(tenant_id, agent_id, "+919876507799", sent_to_leadsquared=True)
    async with tenant_session(tenant_id) as session:
        moved = await session.execute(
            text(
                "UPDATE outbox_messages SET status = :s, "
                "consumed_at = CASE WHEN :c THEN now() END, updated_at = now() "
                "WHERE payload->>'tenant_id' = :t AND job = :job"
            ),
            {
                "s": status,
                "c": consumed,
                "t": str(tenant_id),
                "job": integrations_service.OUTBOUND_WEBHOOK_JOB,
            },
        )
        assert moved.rowcount == 1
    echo = await _push(webhook_id, _leadsquared(phone="9876507799"))
    assert echo.json()["duplicate"] == 1, echo.text


async def test_a_new_leadsquared_lead_for_a_number_we_never_sent_it_is_ingested() -> None:
    """A recent lead from another source that we never wrote to LeadSquared is not an echo:
    the client entered this person in their CRM themselves."""
    tenant_id, agent_id, webhook_id = await _tenant_with_source("leadsquared")
    await _lead_from_another_source(tenant_id, agent_id, "+919876507788", sent_to_leadsquared=False)
    pushed = await _push(webhook_id, _leadsquared(phone="9876507788"))
    assert pushed.json()["accepted"] == 1, pushed.text


async def test_created_push_source_gets_its_preset_and_a_token_address() -> None:
    _, slug, token = await _make_tenant()
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        created = await http.post(
            "/v1/lead-sources", json={"source": "indiamart", "mapping": {}}, headers=headers
        )
        assert created.status_code == 201, created.text
        body = created.json()
        listed = await http.get("/v1/lead-sources", headers=headers)
    assert body["ingest_path"] == f"/hooks/v1/ingest/push/{body['id']}"
    assert body["push_path"] == f"{body['ingest_path']}?token={body['secret']}"
    [row] = listed.json()["items"]
    assert row["mapping"] == portals.preset_mapping("indiamart")
    assert body["secret"] not in json.dumps(listed.json()), "the list never re-serves it"


async def test_a_header_source_has_no_push_address() -> None:
    _, slug, token = await _make_tenant()
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        created = await http.post(
            "/v1/lead-sources", json={"source": "website_form", "mapping": {}}, headers=headers
        )
    assert created.json()["push_path"] is None


# --- LeadSquared, outbound ----------------------------------------------------------


async def _lsq_context(
    *, fields: dict[str, str] | None = None
) -> tuple[uuid.UUID, dict[str, Any], uuid.UUID]:
    created = await create_org_with_receptionist(
        name="LSQ Estates",
        slug=f"lsq-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        credential = await creds.create_credential(
            session,
            tenant_id=tenant_id,
            kind=lsq.KIND,
            label="LeadSquared",
            secret=lsq.seal_keys("u$access-key", "secret-key-value"),
            non_secret={"api_host": "api-in21.leadsquared.com"},
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:id, :t, :a, '+919876509999', 'Kiran', "
                "'webhook', 'new', '{}'::jsonb, now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": created["agent_id"]},
        )
    endpoint = {
        "secret": str(credential.id),
        "mapping": {"api_host": "api-in21.leadsquared.com", "fields": fields or {}},
        "kind": lsq.KIND,
    }
    return tenant_id, endpoint, lead_id


def _recorder(status: int, body: Any) -> tuple[list[httpx.Request], httpx.AsyncClient]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return seen, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_new_lead_is_captured_with_keys_only_in_the_query() -> None:
    tenant_id, endpoint, lead_id = await _lsq_context()
    seen, client = _recorder(
        200, {"Status": "Success", "Message": {"Id": "p1", "RelatedId": None, "IsCreated": True}}
    )
    result = await leadsquared_sync.push_event(
        endpoint=endpoint,
        tenant_id=tenant_id,
        event="lead.created",
        # The fan-out masks the number for an endpoint that did not opt in; the transport
        # reads it from the lead instead of from the outbox row.
        data={"lead_id": str(lead_id), "phone": "[redacted]", "name": "Kiran"},
        client=client,
    )
    assert result.delivered, result.error
    [request] = seen
    assert request.url.host == "api-in21.leadsquared.com"
    assert request.url.path == lsq.CAPTURE_PATH
    assert request.url.params["accessKey"] == "u$access-key"
    assert request.url.params["secretKey"] == "secret-key-value"
    sent = json.loads(request.content)
    assert {"Attribute": "Phone", "Value": "+91-9876509999"} in sent
    assert {"Attribute": "FirstName", "Value": "Kiran"} in sent
    assert {"Attribute": "SearchBy", "Value": "Phone"} in sent
    assert "secret-key-value" not in request.content.decode()


async def test_a_call_result_fills_the_fields_the_client_named() -> None:
    tenant_id, endpoint, lead_id = await _lsq_context(fields={"mx_Call_Outcome": "outcome"})
    seen, client = _recorder(200, {"Status": "Success", "Message": {"Id": "p1"}})
    result = await leadsquared_sync.push_event(
        endpoint=endpoint,
        tenant_id=tenant_id,
        event="call.completed",
        data={"call_id": str(uuid.uuid4()), "lead_id": str(lead_id), "outcome": "interested"},
        client=client,
    )
    assert result.delivered
    sent = json.loads(seen[0].content)
    assert {"Attribute": "mx_Call_Outcome", "Value": "interested"} in sent
    assert {"Attribute": "Phone", "Value": "+91-9876509999"} in sent


@pytest.mark.parametrize(
    ("status", "body", "error", "transient"),
    [
        (401, {"Status": "Error"}, lsq.AUTH_FAILED_REASON, False),
        (400, {"Status": "Error"}, lsq.REJECTED_REASON, None),
        (200, {"Status": "Error"}, lsq.REJECTED_REASON, False),
        (429, {}, "HTTP 429", None),
        (503, {}, "HTTP 503", None),
    ],
)
async def test_refusals_are_told_apart(
    status: int, body: Any, error: str, transient: bool | None
) -> None:
    tenant_id, endpoint, lead_id = await _lsq_context()
    _, client = _recorder(status, body)
    result = await leadsquared_sync.push_event(
        endpoint=endpoint,
        tenant_id=tenant_id,
        event="lead.created",
        data={"lead_id": str(lead_id), "name": "Kiran"},
        client=client,
    )
    assert not result.delivered
    assert result.error == error
    assert result.transient is transient


async def test_no_keys_or_an_unlisted_host_sends_nothing() -> None:
    tenant_id, endpoint, lead_id = await _lsq_context()
    seen, client = _recorder(200, {"Status": "Success"})
    for broken in (
        {**endpoint, "secret": str(uuid.uuid4())},
        {**endpoint, "mapping": {"api_host": "evil.example.com"}},
    ):
        result = await leadsquared_sync.push_event(
            endpoint=broken,
            tenant_id=tenant_id,
            event="lead.created",
            data={"lead_id": str(lead_id)},
            client=client,
        )
        assert result.error == lsq.NO_CREDENTIAL_REASON
        assert result.transient is False
    assert seen == []


async def test_another_accounts_credential_is_not_usable() -> None:
    _, endpoint, lead_id = await _lsq_context()
    other_tenant, _, _ = await _lsq_context()
    seen, client = _recorder(200, {"Status": "Success"})
    result = await leadsquared_sync.push_event(
        endpoint=endpoint,
        tenant_id=other_tenant,
        event="lead.created",
        data={"lead_id": str(lead_id)},
        client=client,
    )
    assert result.error == lsq.NO_CREDENTIAL_REASON
    assert seen == []


def test_the_host_must_be_one_leadsquared_publishes() -> None:
    assert lsq.host_of("https://api-in21.leadsquared.com/v2/") == "api-in21.leadsquared.com"
    assert lsq.host_of("API-IN22.leadsquared.com") == "api-in22.leadsquared.com"
    assert lsq.host_of("api-in21.leadsquared.com.evil.example") is None
    assert lsq.host_of("https://169.254.169.254/") is None


async def test_the_leadsquared_destination_is_created_sealed_and_validated() -> None:
    tenant_id, slug, token = await _make_tenant()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Org-Slug": slug,
        "X-Confirm-Action": f"create_endpoint:{slug}",
    }
    body = {
        "api_host": "https://api-in21.leadsquared.com/v2/",
        "access_key": "u$access-key",
        "secret_key": "secret-key-value",
        "events": ["lead.created", "call.completed"],
        "fields": {"mx_Call_Outcome": "outcome"},
    }
    async with _client() as http:
        bad_host = await http.post(
            "/v1/integrations/endpoints/leadsquared",
            json={**body, "api_host": "crm.example.com"},
            headers=headers,
        )
        no_field = await http.post(
            "/v1/integrations/endpoints/leadsquared",
            json={**body, "fields": {}},
            headers=headers,
        )
        created = await http.post(
            "/v1/integrations/endpoints/leadsquared", json=body, headers=headers
        )
        listed = await http.get("/v1/integrations/credentials", headers=headers)
    assert bad_host.status_code == 422, bad_host.text
    assert bad_host.json()["type"].rsplit("/", 1)[-1] == "leadsquared_host_unknown"
    assert no_field.json()["type"].rsplit("/", 1)[-1] == "leadsquared_call_needs_a_field"
    assert created.status_code == 201, created.text
    assert created.json()["api_host"] == "api-in21.leadsquared.com"
    text_listed = json.dumps(listed.json())
    assert "u$access-key" not in text_listed and "secret-key-value" not in text_listed
    async with tenant_session(tenant_id) as session:
        kind, events = (
            await session.execute(
                text("SELECT kind, events FROM outbound_webhooks WHERE id = :i"),
                {"i": uuid.UUID(created.json()["id"])},
            )
        ).one()
    assert kind == "leadsquared"
    assert set(events) == {"lead.created", "call.completed"}
