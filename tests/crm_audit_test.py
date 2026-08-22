"""Audit of the lead/call surfaces, the inbound ingest path and the outbound sync.

Each test here states a property the shipped contract (docs/WEBHOOKS.md, docs/SURFACES
§2) or a module's own docstring already claims, and that the code did not hold.

Scoping note: other suites run against the same database concurrently, so every test
below creates its own organization and asserts only through a tenant-scoped session —
never a global count.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest
from apps.api.crm import service as crm
from apps.api.crm.performance import performance
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ingest.service import normalize_phone
from apps.api.integrations import service as integrations
from sqlalchemy import text
from tests.api_security_test import _client as _auth_client
from tests.api_security_test import _make_tenant
from tests.lead_ingest_test import SECRET as INGEST_SECRET
from tests.lead_ingest_test import _tenant_with_ingest
from tests.outbound_sync_test import SECRET as ENDPOINT_SECRET
from tests.outbound_sync_test import _tenant_with_endpoint

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Audit Clinic",
        slug=f"aud-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _call_row(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str,
    duration_s: int | None = None,
    started_at: str | None = None,
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, duration_s, started_at, created_at, updated_at) VALUES "
                "(:i, :t, :a, :e, 'outbound', '+919876500001', :st, :dur, "
                "CAST(:started AS timestamptz), now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "e": f"aud_{uuid.uuid4().hex[:12]}",
                "st": status,
                "dur": duration_s,
                "started": started_at,
            },
        )


# ------------------------------------------------------------------ performance


async def test_a_voicemail_with_a_duration_is_a_dial_not_a_conversation() -> None:
    """performance.py's own docstring: `no_answer`/`busy`/`failed`/`voicemail` are
    dials, and "counting voicemail as connected is how a competitor demo inflates its
    connect rate". A voicemail that ran for 25 seconds is still a voicemail — the
    answering machine picking up gives it a duration, which is exactly the case the
    duration clause was letting through.
    """
    tenant_id, agent_id = await _org()
    await _call_row(tenant_id, agent_id, status="completed", duration_s=120)
    await _call_row(tenant_id, agent_id, status="voicemail", duration_s=25)
    await _call_row(tenant_id, agent_id, status="failed", duration_s=3)
    await _call_row(tenant_id, agent_id, status="no_answer", duration_s=0)

    async with tenant_session(tenant_id) as session:
        result = await performance(session)

    assert result["funnel"]["calls"] == 4
    assert result["funnel"]["connected"] == 1, "only the real conversation connected"
    assert result["connect_rate_pct"] == 25


async def test_the_ist_histogram_does_not_depend_on_the_database_timezone() -> None:
    """ "Busiest hours are IST" is a promise about the bucket, not about how the server
    happens to be configured. Shifting a `timestamptz` by a fixed interval and then
    EXTRACTing the hour renders it in the SESSION's TimeZone, so the same call lands in
    a different bucket on a database whose timezone is Asia/Kolkata (the plausible
    setting for a Bangalore deployment) than on one set to UTC.
    """
    tenant_id, agent_id = await _org()
    # 05:30Z is 11:00 IST, exactly.
    await _call_row(
        tenant_id, agent_id, status="completed", duration_s=60, started_at="2026-08-11T05:30:00Z"
    )

    async with tenant_session(tenant_id) as session:
        utc = await performance(session)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("SET LOCAL TIME ZONE 'Asia/Kolkata'"))
        kolkata = await performance(session)

    assert utc["busiest_hours_ist"][11] == 1
    assert kolkata["busiest_hours_ist"] == utc["busiest_hours_ist"], (
        "the IST bucket must not move when the database session timezone does"
    )


# ------------------------------------------------------------------ unbounded reads


async def test_the_csv_export_refuses_rather_than_materializing_every_lead() -> None:
    """`export_leads_csv` selected every non-deleted lead with no LIMIT and built the
    whole CSV in memory inside the request. A tenant with 50k leads turns one click
    into a hung worker. A bounded read that says so is the fix; a silent truncation of
    a contact export would be worse than the hang.
    """
    assert hasattr(crm, "MAX_EXPORT_ROWS"), "the export needs a declared cap"

    tenant_id, agent_id = await _org()
    async with tenant_session(tenant_id) as session:
        for _ in range(3):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', "
                    "'webhook', 'new', now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                },
            )

    from apps.api.core.errors import ProblemError

    async with tenant_session(tenant_id) as session:
        ok = await crm.export_leads_csv(session)
        assert len(ok.csv.strip().splitlines()) == 4, "header + three leads"
        assert ok.row_count == 3, "the count the audit row records is the count of LEADS"

    original = crm.MAX_EXPORT_ROWS
    try:
        crm.MAX_EXPORT_ROWS = 2
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as raised:
                await crm.export_leads_csv(session)
    finally:
        crm.MAX_EXPORT_ROWS = original
    assert raised.value.code == "lead_export_too_large"


async def test_list_limits_are_validated_before_they_reach_sql() -> None:
    """`limit` on three list endpoints went straight into `min(limit, N)` and then into
    a SQL LIMIT. A negative value is either a database error surfaced as a 500 or, on
    the attention queue, a silently short list — both from a query string.
    """
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, mapping, "
                "active, created_at, updated_at) VALUES (:i, :t, 'website_form', 's', "
                "CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )

    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _auth_client() as http:
        for path in ("/v1/attention", "/v1/integrations/deliveries", "/v1/lead-sources/activity"):
            response = await http.get(f"{path}?limit=-1", headers=headers)
            assert response.status_code == 422, f"{path} accepted a negative limit"


# ------------------------------------------------------------------ ingest


def test_phone_normalization_returns_e164_or_nothing() -> None:
    """ "Returns None rather than guessing" has a second half: what it DOES return must
    be dialable. Keeping every '+' in the string and length-checking the result let
    `++91…` and `+91+98…` through as phone numbers, and a leading-zero country code
    through as an E.164 that does not exist.
    """
    for raw in (
        "++919876543210",
        "+91+9876543210",
        "+0123456789",
        "+91-98765-4321-0-",
        "9876543210+",
        "12345",
        "5551234567",
        "",
        "+",
    ):
        out = normalize_phone(raw)
        assert out is None or E164.match(out), f"{raw!r} normalized to {out!r}"

    # And the documented happy paths are untouched (docs/WEBHOOKS.md §2.2).
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"


async def test_the_ingested_number_never_lands_in_the_lead_data_blob() -> None:
    """`leads.phone_e164` is the column that holds a lead's number, and it must be the
    ONLY one. With no field mapping configured — a documented, supported setup
    (WEBHOOKS §2.2) — the key the number arrived under survived into `leads.data`, so
    one lead had its number in two places.

    Still a defect after D-436 unmasked the column, for a different and more durable
    reason: `data` is the tenant's declared extraction payload, a duplicate there is an
    undeclared facet value and an unlabelled export cell, and it does not move when the
    column beside it is corrected. One fact, one column.
    """
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(mapping={})
    number = "9876512345"
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": number, "full_name": "Nomap", "mobile": number},
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
    assert response.status_code == 202, response.text

    async with tenant_session(tenant_id) as session:
        stored = (await session.execute(text("SELECT data FROM leads"))).scalar()
        items, _total = await crm.list_leads(session)

    assert number not in str(stored), f"the number is still in leads.data: {stored!r}"
    # ONCE, in `phone_e164`, and nowhere else. `data` is a free-form passthrough
    # (`check_redaction_exposure.ACKNOWLEDGED_PASSTHROUGH`), so a copy hiding in there is
    # a column no schema declared and no reader is keyed on.
    serialized = "".join(item.model_dump_json() for item in items)
    assert serialized.count(f"+91{number}") == 1, "the number appears once, in its own column"


async def test_unmapped_keys_from_a_hostile_sender_are_dropped() -> None:
    """WEBHOOKS §2.2: with a mapping configured, only mapped fields survive."""
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(
        mapping={"phone": "phone_number", "name": "full_name"}
    )
    async with _client() as http:
        await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={
                "phone_number": "9876513456",
                "full_name": "Mapped",
                "evil": {"nested": "payload"},
                "__proto__": "nope",
            },
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
    async with tenant_session(tenant_id) as session:
        stored = (await session.execute(text("SELECT data FROM leads"))).scalar()
    assert "evil" not in (stored or {})
    assert "__proto__" not in (stored or {})


async def test_the_body_hash_dedupe_survives_key_reordering() -> None:
    """WEBHOOKS §2.4: "key order does not matter". A vendor retry that serializes its
    JSON in a different order is the same submission and must not ring twice.
    """
    _tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    first = {"phone_number": "9876514567", "full_name": "Reorder", "budget_lakhs": "45"}
    second = {"budget_lakhs": "45", "full_name": "Reorder", "phone_number": "9876514567"}
    async with _client() as http:
        one = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json=first,
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
        two = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json=second,
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
    assert one.json()["status"] == "accepted"
    assert two.json()["status"] == "duplicate", "reordering the keys is not a new lead"


async def test_a_non_ascii_ingest_secret_is_rejected_not_crashed() -> None:
    """`hmac.compare_digest` raises TypeError when either `str` argument is not ASCII,
    and HTTP header values decode as latin-1 — so one byte in `X-Ingest-Secret` turned
    an unauthenticated 401 into an unhandled 500 from the never-shed surface.

    The bytes below are valid UTF-8 on the wire (`café`) so the request survives the
    middleware stack and the failure under test is this module's own comparison.
    """
    _tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876515678"},
            headers={"X-Ingest-Secret": b"caf\xc3\xa9"},
        )
    assert response.status_code == 401
    assert response.json()["kind"] == "auth"


# ------------------------------------------------------------------ outbound sync


async def test_a_signed_body_is_never_replayed_to_a_redirect_target() -> None:
    """WEBHOOKS §1.5: "Redirects are not followed: we will not chase a signed body to a
    host you did not register." That has to be a property of the request we make, not
    of how the caller happened to build the http client — a 307 re-sends the body AND
    our signature headers to whatever host the Location names.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "crm.example":
            return httpx.Response(307, headers={"Location": "https://evil.example/collect"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        result = await integrations.deliver(
            url="https://crm.example/hook",
            secret=ENDPOINT_SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"phone": "+919876500001"}},
            client=client,
        )

    assert [r.url.host for r in seen] == ["crm.example"], "we followed the redirect"
    assert result.delivered is False
    assert result.status_code == 307, "a 3xx is a failure, not a delivery"


async def test_the_raw_phone_opt_in_is_per_endpoint_and_masked_by_default() -> None:
    """WEBHOOKS §1.2 and the delivery runbook both say the raw number is a per-endpoint
    opt-in "recorded in your endpoint config". Masking was applied once by the caller
    before the fan-out, so every endpoint got the same payload: the opt-in could not be
    honoured, and — worse — a caller that forgot to mask would put a raw number in the
    outbox row of an endpoint that never asked for one.
    """
    tenant_id, masked_endpoint = await _tenant_with_endpoint()
    opted_in = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, "
                ":s, :events, CAST(:m AS jsonb), true, now(), now())"
            ),
            {
                "id": opted_in,
                "tid": tenant_id,
                "url": "https://raw.example/hook",
                "s": ENDPOINT_SECRET,
                "events": ["lead.created"],
                "m": '{"include_raw_phone": true}',
            },
        )
        fanned = await integrations.enqueue_event(
            session,
            tenant_id=tenant_id,
            event="lead.created",
            data={"lead_id": str(uuid7()), "phone": "+919876516789", "name": "Priya"},
        )
    assert fanned == 2

    async with untenanted_session() as session:
        rows = dict(
            (
                await session.execute(
                    text(
                        "SELECT payload->>'endpoint_id', payload->'data'->>'phone' "
                        "FROM outbox_messages WHERE job = 'deliver_outbound_webhook' "
                        "AND payload->>'tenant_id' = :t"
                    ),
                    {"t": str(tenant_id)},
                )
            ).all()
        )

    assert rows[str(masked_endpoint)] == "[redacted]", "masked unless the endpoint opted in"
    assert rows[str(opted_in)] == "+919876516789", "the opt-in is a real opt-in"


async def test_an_event_without_a_phone_does_not_grow_one() -> None:
    """`call.completed` carries a summary and no phone. Redacting at the fan-out must
    not invent a `phone: [redacted]` key that the published payload schema never had.
    """
    tenant_id, endpoint_id = await _tenant_with_endpoint(events=("call.completed",))
    async with tenant_session(tenant_id) as session:
        await integrations.enqueue_event(
            session,
            tenant_id=tenant_id,
            event="call.completed",
            data={"call_id": str(uuid7()), "summary": "They booked a slot.", "duration_s": 61},
        )
    async with untenanted_session() as session:
        payload: dict[str, Any] = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'deliver_outbound_webhook' "
                    "AND payload->>'endpoint_id' = :e"
                ),
                {"e": str(endpoint_id)},
            )
        ).scalar()
    assert "phone" not in payload["data"]
    assert payload["data"]["summary"] == "They booked a slot."


# ------------------------------------------------------------------ raw transcript


async def test_a_failed_raw_transcript_read_leaves_no_audit_row_behind() -> None:
    """Hard rule 5's "in the same transaction" cuts both ways: the audit row commits
    with the read, so a read that never happened must not leave a record claiming it
    did. This is the test that would fail the day the audit write moves to its own
    session or to a fire-and-forget task.
    """
    _tenant_id, slug, token = await _make_tenant(role="owner")
    missing = uuid.uuid4()
    async with _auth_client() as http:
        response = await http.get(
            f"/v1/calls/{missing}/transcript/raw",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 404

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'transcript.read_raw' "
                    "AND object_id = :cid"
                ),
                {"cid": str(missing)},
            )
        ).scalar()
    assert audited == 0, "the audit row rolled back with the failed read"
