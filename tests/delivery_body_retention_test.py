"""The delivered CRM body: retained, bounded, tenant-scoped, expired and erasable (D-23).

This slice ADDS a personal-data store. `webhook_deliveries` could previously prove that a
POST happened and nothing about what was in it, so "you sent us the wrong lead" was
unanswerable — and the fix is to keep a copy of the body, which is a lead's name, their
number and every extracted field sitting in a bucket. Everything below exists because
that copy is a liability the moment any one of these properties stops holding:

- **The delivery outranks the copy.** Object storage being down must cost a support
  artifact, never a client's lead.
- **Nothing is retained that an erasure cannot find.** The key names the subject, and an
  event naming no subject is not retained at all.
- **A DPDP erasure actually destroys it** — including an ORPHAN object whose delivery row
  never recorded the reference, which is the case a DB-driven erasure walks straight past.
- **The retention sweep expires it** on the tenant's own `lead` policy, and a store that
  will not answer leaves the reference alone rather than orphaning the object.
- **A neighbouring tenant cannot reach it.** `webhook_deliveries` has no RLS policy; the
  scoping is the `outbound_webhooks` subquery, and only that.
- **It is bounded**, and a truncated copy says so rather than lying by omission.

The object store is a fake, on purpose: local MinIO may not be running, and a suite that
SKIPS is a suite that proves nothing about the exact properties above. The fake answers
like S3 (`ClientError`/`NoSuchKey`, paginated listing, batch delete) and can be made to
fail, which is the half a real MinIO cannot easily be asked for. It lives in
`tests/conftest.py` now — the retention sweep and the DPDP erasure grew arms that delete
RECORDING objects, so it has three callers and a second copy would be where they drift.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service
from apps.workers import outbound_webhooks, retention, storage
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from sqlalchemy import text
from tests.conftest import FakeS3

SECRET = "whsec_delivery_body_secret"
# The agent each fixture tenant was created with — `leads.agent_id` and `calls.agent_id`
# are NOT NULL, and the onboarding flow is what mints one.
_AGENTS: dict[uuid.UUID, uuid.UUID] = {}
ENDPOINT_URL = "https://crm.example/hook?apikey=not-a-thing-we-store"


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Every alert the worker fired, as (stage, code)."""
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        outbound_webhooks,
        "alert",
        lambda stage, code, **kw: fired.append((stage, code)),
    )
    return fired


# --- fixtures ----------------------------------------------------------------------


async def _tenant_with_endpoint(
    *, events: tuple[str, ...] = ("lead.created", "call.completed", "campaign.completed")
) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Body Clinic",
        slug=f"body-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    _AGENTS[tenant_id] = created["agent_id"]
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
                ":events, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": ENDPOINT_URL,
                "secret": SECRET,
                "events": list(events),
            },
        )
    return tenant_id, endpoint_id


def _receiver(monkeypatch: pytest.MonkeyPatch, *, status_code: int = 200) -> list[httpx.Request]:
    """Point the real `service.deliver` at a mock transport, keeping its body building.

    The transport is replaced, not the function: the stored artifact is supposed to be
    what the transport put on the wire, so a test that stubbed `deliver` would be
    asserting its own fixture back.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json={"ok": True})

    real = service.deliver

    async def routed(**kwargs: Any) -> service.DeliveryResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await real(**{**kwargs, "client": client})

    monkeypatch.setattr(service, "deliver", routed)
    return seen


async def _run_delivery(
    tenant_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    *,
    event: str = "lead.created",
    data: dict[str, Any] | None = None,
    delivery_id: uuid.UUID | None = None,
    attempt: int = 1,
) -> tuple[uuid.UUID, str]:
    delivery_id = delivery_id or uuid7()
    outcome = await deliver_outbound_webhook(
        {"job_try": attempt},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": event,
            "data": data if data is not None else {"lead_id": str(uuid7()), "name": "Priya"},
            "delivery_id": str(delivery_id),
        },
    )
    return delivery_id, outcome


async def _payload_ref(tenant_id: uuid.UUID, delivery_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text(
                    "SELECT payload_ref FROM webhook_deliveries WHERE id = :id "
                    "AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
                ),
                {"id": delivery_id},
            )
        ).scalar()
    return str(ref) if ref else None


# --- what gets kept ----------------------------------------------------------------


async def test_the_stored_body_is_exactly_what_went_on_the_wire(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the artifact: not a reconstruction, the bytes the receiver got."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    seen = _receiver(monkeypatch)
    lead_id = str(uuid7())

    delivery_id, outcome = await _run_delivery(
        tenant_id, endpoint_id, data={"lead_id": lead_id, "name": "Priya", "phone": "+919876500001"}
    )

    assert outcome == "delivered 200"
    ref = await _payload_ref(tenant_id, delivery_id)
    assert ref is not None, "the delivery row points at the body"
    document = json.loads(s3.objects[ref])
    assert document["body"] == seen[0].content.decode()
    assert document["truncated"] is False
    assert document["subject_type"] == "lead" and document["subject_id"] == lead_id
    assert document["delivery_id"] == str(delivery_id)


async def test_the_stored_object_carries_no_secret_and_no_endpoint_url(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retained body is read by support. The signing secret is not part of "what we
    sent", and a client's webhook URL routinely carries a token in its query string."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)

    delivery_id, _ = await _run_delivery(tenant_id, endpoint_id)

    ref = await _payload_ref(tenant_id, delivery_id)
    assert ref is not None
    blob = s3.objects[ref].decode()
    assert SECRET not in blob
    assert "apikey" not in blob and ENDPOINT_URL not in blob
    # And not in the key either — the key is what a delivery row exposes.
    assert SECRET not in ref


async def test_an_event_naming_no_subject_is_not_retained_at_all(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule that keeps this store erasable: if we cannot say whose data it is, we do
    not keep it. `campaign.completed` carries campaign aggregates and no person."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)

    delivery_id, outcome = await _run_delivery(
        tenant_id, endpoint_id, event="campaign.completed", data={"campaign_id": str(uuid7())}
    )

    assert outcome == "delivered 200", "the delivery itself is unaffected"
    assert await _payload_ref(tenant_id, delivery_id) is None
    assert s3.objects == {}, "an object no data principal could ever be matched to"


async def test_a_failed_delivery_still_records_what_we_tried_to_send(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deliveries anyone investigates are the failed ones. A body kept only on 2xx
    would be missing exactly when it is asked for."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch, status_code=404)

    delivery_id, outcome = await _run_delivery(tenant_id, endpoint_id)

    assert outcome.startswith("rejected")
    ref = await _payload_ref(tenant_id, delivery_id)
    assert ref is not None and ref in s3.objects


async def test_a_large_body_is_capped_and_says_that_it_was(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One client's 4MB payload must not become a silent storage bill — and the copy has
    to admit it is partial, or it is a forensic record that lies."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)
    huge = "x" * (storage.MAX_RETAINED_BODY_BYTES * 3)

    delivery_id, _ = await _run_delivery(
        tenant_id, endpoint_id, data={"lead_id": str(uuid7()), "notes": huge}
    )

    ref = await _payload_ref(tenant_id, delivery_id)
    assert ref is not None
    document = json.loads(s3.objects[ref])
    assert document["truncated"] is True
    assert len(document["body"].encode()) <= storage.MAX_RETAINED_BODY_BYTES
    assert document["original_bytes"] > storage.MAX_RETAINED_BODY_BYTES
    # The whole object stays small; the cap is about STORAGE, not about the body field.
    assert len(s3.objects[ref]) < storage.MAX_RETAINED_BODY_BYTES * 2


def test_truncation_never_produces_an_unparseable_record() -> None:
    """The cap slices UTF-8 BYTES. A body cut mid-character must still round-trip as
    JSON, because the document is the record and an unreadable record is no record."""
    document, original, truncated = storage.build_delivery_body_document(
        delivery_id=uuid7(),
        endpoint_id=uuid7(),
        event="lead.created",
        subject_type="lead",
        subject_id=str(uuid7()),
        # Telugu: every character is 3 bytes, so the cap lands inside one of them.
        body="ప" * storage.MAX_RETAINED_BODY_BYTES,
    )
    assert truncated and original == storage.MAX_RETAINED_BODY_BYTES * 3
    parsed = json.loads(document)
    assert parsed["truncated"] is True
    assert len(parsed["body"].encode()) <= storage.MAX_RETAINED_BODY_BYTES


# --- storage failure must not cost a delivery --------------------------------------


async def test_object_storage_being_down_does_not_stop_the_delivery(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str]]
) -> None:
    """The job exists to deliver. A support artifact is not allowed to fail a lead."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    seen = _receiver(monkeypatch)
    s3.fail = True

    delivery_id, outcome = await _run_delivery(tenant_id, endpoint_id)

    assert outcome == "delivered 200", "the client's CRM was told"
    assert len(seen) == 1, "and told exactly once"
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, payload_ref FROM webhook_deliveries WHERE id = :id"),
                {"id": delivery_id},
            )
        ).first()
    assert row is not None and row[0] == "delivered"
    assert row[1] is None, "no reference to an object that was never written"
    assert ("WORKER_DELIVERY", "delivery_body_not_retained") in alerts, (
        "the absence is visible to an operator rather than looking like a delivery from "
        "before bodies were kept"
    )


async def test_a_retry_that_cannot_store_does_not_wipe_the_body_it_already_had(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str]]
) -> None:
    """`COALESCE` on the reference. Best-effort storage may only ever GAIN a reference.

    Both attempts run at the LAST rung of the ladder (`MAX_ATTEMPTS`), so the job records
    and returns instead of raising `arq.Retry` — the ladder itself is
    `outbound_sync_test`'s subject, not this file's.
    """
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch, status_code=500)
    delivery_id = uuid7()

    await _run_delivery(
        tenant_id, endpoint_id, delivery_id=delivery_id, attempt=service.MAX_ATTEMPTS
    )
    first = await _payload_ref(tenant_id, delivery_id)
    assert first is not None

    s3.fail = True
    await deliver_outbound_webhook(
        {"job_try": service.MAX_ATTEMPTS},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": str(uuid7())},
            "delivery_id": str(delivery_id),
        },
    )

    assert await _payload_ref(tenant_id, delivery_id) == first


# --- tenancy -----------------------------------------------------------------------


async def test_a_neighbouring_tenant_cannot_reach_the_body_or_its_key(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`webhook_deliveries` carries NO RLS policy (engine webhooks arrive before a tenant
    is resolved), so the `outbound_webhooks` subquery is the entire tenant boundary here.
    A key is enough to fetch the object, so leaking the key IS leaking the body."""
    tenant_a, endpoint_a = await _tenant_with_endpoint()
    tenant_b, _ = await _tenant_with_endpoint()
    _receiver(monkeypatch)

    delivery_id, _ = await _run_delivery(tenant_a, endpoint_a)

    async with tenant_session(tenant_a) as session:
        ref, event_type = await service.delivery_body_ref(session, delivery_id)
    assert ref is not None and event_type == "lead.created"

    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as refused:
            await service.delivery_body_ref(session, delivery_id)
    # 404, not 403: another tenant's delivery is indistinguishable from one that never
    # existed, which is the answer `ProblemError.not_found` documents as deliberate.
    assert refused.value.status == 404

    # And the key itself is tenant-prefixed, so a leaked one is visible as a crossing.
    assert ref.startswith(f"{storage.DELIVERY_BODY_PREFIX}/{tenant_a}/")
    assert str(tenant_b) not in ref


# --- retention ---------------------------------------------------------------------


async def _age_delivery(tenant_id: uuid.UUID, delivery_id: uuid.UUID, *, days: int) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE webhook_deliveries SET created_at = :when WHERE id = :id "
                "AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
            ),
            {"id": delivery_id, "when": datetime.now(UTC) - timedelta(days=days)},
        )


async def _lead_policy(tenant_id: uuid.UUID, *, ttl_days: int) -> None:
    """Shorten the tenant's OWN `lead` policy rather than adding a second one.

    Onboarding already wrote the row (`scripts/seed.DEFAULT_RETENTION_POLICIES`, lead =
    1095 days), and a second row for one category would make the probe return two and
    the sweep run its arm twice — a test artefact that would hide a real double-sweep.
    """
    # A TENANT session: `retention_policies` is RLS'd and `untenanted_session` is
    # fail-closed, so an admin-shaped write here would silently match zero rows.
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text("UPDATE retention_policies SET ttl_days = :ttl WHERE data_category = 'lead'"),
            {"ttl": ttl_days},
        )
        assert result.rowcount == 1, "onboarding is supposed to give every tenant one"


async def test_the_sweep_deletes_a_body_past_its_tenants_lead_policy(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retained body expires on the CLIENT's own agreed clock, not on a constant
    somebody typed into the sweep."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)
    await _lead_policy(tenant_id, ttl_days=30)

    old, _ = await _run_delivery(tenant_id, endpoint_id)
    fresh, _ = await _run_delivery(tenant_id, endpoint_id)
    old_ref = await _payload_ref(tenant_id, old)
    fresh_ref = await _payload_ref(tenant_id, fresh)
    await _age_delivery(tenant_id, old, days=31)

    counts = await retention.sweep_tenant(tenant_id)

    assert counts["delivery_bodies"] == 1
    assert old_ref not in s3.objects, "the bytes are gone, not just the pointer"
    assert await _payload_ref(tenant_id, old) is None
    assert fresh_ref in s3.objects, "a body inside the policy is untouched"
    assert await _payload_ref(tenant_id, fresh) == fresh_ref


async def test_the_sweep_leaves_the_reference_alone_when_the_store_will_not_answer(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clearing a reference to an object we failed to delete would ORPHAN it — a lead's
    name and number in a bucket that no query, no erasure and no later sweep can name."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)
    await _lead_policy(tenant_id, ttl_days=30)
    delivery_id, _ = await _run_delivery(tenant_id, endpoint_id)
    ref = await _payload_ref(tenant_id, delivery_id)
    await _age_delivery(tenant_id, delivery_id, days=31)

    s3.fail = True
    counts = await retention.sweep_tenant(tenant_id)
    assert counts["delivery_bodies"] == 0
    assert await _payload_ref(tenant_id, delivery_id) == ref, "still reachable"

    # And the next tick, with the store back, finishes the job.
    s3.fail = False
    counts = await retention.sweep_tenant(tenant_id)
    assert counts["delivery_bodies"] == 1
    assert ref not in s3.objects
    assert await _payload_ref(tenant_id, delivery_id) is None


async def test_one_tenants_sweep_cannot_delete_another_tenants_body(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep runs per tenant against a table with no RLS. If its scoping subquery
    ever goes, the nightly job becomes a cross-tenant delete."""
    tenant_a, endpoint_a = await _tenant_with_endpoint()
    tenant_b, endpoint_b = await _tenant_with_endpoint()
    _receiver(monkeypatch)
    await _lead_policy(tenant_a, ttl_days=30)
    await _lead_policy(tenant_b, ttl_days=30)

    a_delivery, _ = await _run_delivery(tenant_a, endpoint_a)
    b_delivery, _ = await _run_delivery(tenant_b, endpoint_b)
    b_ref = await _payload_ref(tenant_b, b_delivery)
    await _age_delivery(tenant_a, a_delivery, days=31)
    await _age_delivery(tenant_b, b_delivery, days=31)

    counts = await retention.sweep_tenant(tenant_a)

    assert counts["delivery_bodies"] == 1, "only its own"
    assert b_ref in s3.objects
    assert await _payload_ref(tenant_b, b_delivery) == b_ref


# --- DPDP erasure ------------------------------------------------------------------


async def _erasure_fixture(
    tenant_id: uuid.UUID, phone: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A lead and a call for one number, plus the deletion request naming it."""
    lead_id, call_id, request_id = uuid7(), uuid7(), uuid7()
    agent_id = _AGENTS[tenant_id]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :phone, 'Priya', "
                "'inbound_call', 'new', now(), now())"
            ),
            {"id": lead_id, "tid": tenant_id, "aid": agent_id, "phone": phone},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, "
                "direction, status, from_e164, to_e164, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :lid, :eid, 'inbound', 'completed', :phone, "
                "'+911140000000', now(), now())"
            ),
            {
                "id": call_id,
                "eid": f"dbr_{call_id.hex[:12]}",
                "tid": tenant_id,
                "aid": agent_id,
                "lid": lead_id,
                "phone": phone,
            },
        )
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
                "requested_at, created_at) VALUES (:id, :tid, :phone, :ref, 'all', now(), now())"
            ),
            {
                "id": request_id,
                "tid": tenant_id,
                "phone": phone,
                "ref": retention._hash(phone),
            },
        )
    return lead_id, call_id, request_id


async def test_an_erasure_destroys_the_delivered_bodies_for_that_person(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The obligation this whole design turns on. A body the erasure cannot reach is a
    copy of the person we just certified as removed."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)
    phone = "+919876511111"
    lead_id, call_id, request_id = await _erasure_fixture(tenant_id, phone)

    subject_lead, _ = await _run_delivery(
        tenant_id, endpoint_id, data={"lead_id": str(lead_id), "name": "Priya"}
    )
    subject_call, _ = await _run_delivery(
        tenant_id,
        endpoint_id,
        event="call.completed",
        data={"call_id": str(call_id), "lead_id": str(lead_id), "summary": "asked about fees"},
    )
    # Somebody else's lead, delivered through the same endpoint.
    other, _ = await _run_delivery(tenant_id, endpoint_id, data={"lead_id": str(uuid7())})
    other_ref = await _payload_ref(tenant_id, other)

    outcome = await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    assert "bodies=2" in outcome
    assert s3.objects.keys() == {other_ref}, "theirs and only theirs"
    assert await _payload_ref(tenant_id, subject_lead) is None
    assert await _payload_ref(tenant_id, subject_call) is None
    assert await _payload_ref(tenant_id, other) == other_ref

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :id"), {"id": request_id}
            )
        ).scalar()
    assert "2 delivered CRM payload(s)" in proof["actions"]["webhook_deliveries"]


async def test_an_erasure_reaches_an_object_whose_delivery_row_never_recorded_it(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ORPHAN CASE, and the reason the erasure enumerates the object store instead of
    the `payload_ref` column: the worker writes the object BEFORE it records the
    reference, so a crash in between leaves an object no row points at. A DB-driven
    erasure walks straight past it and certifies a deletion that did not happen."""
    tenant_id, _ = await _tenant_with_endpoint()
    phone = "+919876522222"
    lead_id, _call_id, request_id = await _erasure_fixture(tenant_id, phone)

    orphan = storage.delivery_body_key(
        tenant_id=tenant_id, subject_type="lead", subject_id=str(lead_id), delivery_id=uuid7()
    )
    storage.store_delivery_body(
        key=orphan,
        delivery_id=uuid7(),
        endpoint_id=uuid7(),
        event="lead.created",
        subject_type="lead",
        subject_id=str(lead_id),
        body='{"name":"Priya"}',
    )
    assert orphan in s3.objects

    outcome = await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    assert "bodies=1" in outcome
    assert orphan not in s3.objects


async def test_an_erasure_refuses_to_complete_while_the_store_is_unreachable(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A certificate that says "erased" over a copy we could not even look for is worse
    than one that has not been issued. The job retries; nothing is half-done."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    _receiver(monkeypatch)
    phone = "+919876533333"
    lead_id, _call_id, request_id = await _erasure_fixture(tenant_id, phone)
    await _run_delivery(tenant_id, endpoint_id, data={"lead_id": str(lead_id)})

    s3.fail = True
    with pytest.raises(storage.StorageUnavailableError):
        await retention.execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT completed_at, phone_e164 FROM deletion_requests WHERE id = :id"),
                {"id": request_id},
            )
        ).first()
        lead_phone = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :id"), {"id": lead_id}
            )
        ).scalar()
    assert row is not None and row[0] is None, "not completed, so the retry may redo it"
    assert row[1] == phone, "the worker keeps its handle on the subject"
    assert lead_phone == phone, "the whole erasure rolled back — no half-erased person"

    # And with the store back, the same request completes.
    s3.fail = False
    outcome = await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert "bodies=1" in outcome
