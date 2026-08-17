"""The archived RAW vendor payload expires on the tenant's own clock (D-179, F-2).

`tests/engine_payload_erasure_test.py` proves the ERASURE reaches this store. That left
the defect this file is about: an erasure is something a data principal has to ASK for,
so before D-179 the only archived vendor documents that ever disappeared belonged to the
handful of people who filed a §12 request. Everyone else's caller number and transcript
sat in `engine-payloads/{tenant}/{call}/…` for ever, because no
`retention_policies.data_category` covered the archive and the bucket lifecycle rule that
notionally did has never been applied to a real bucket (infra/README §5). Retaining
personal data with no period is the DPDP §8(7) breach in its own right — it does not need
anybody to come looking.

`engine_payload` is now a category, `_sweep_engine_payloads` is the arm, and it reuses
`_erase_engine_payloads` rather than growing a fourth object-sweep loop: one definition of
"destroy a call's archived payloads", two callers.

Every test WRITES the object through `storage.archive_payload` and asserts against
`s3.objects` — the bytes — with the reference checked beside it and never instead of it. A
retention test that passes because the bucket was empty proves nothing.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import storage
from apps.workers.retention import sweep_tenant
from scripts.seed import DEFAULT_RETENTION_POLICIES
from sqlalchemy import text
from tests.conftest import FakeS3

PAYLOAD_TTL_DAYS = next(
    policy["ttl_days"]
    for policy in DEFAULT_RETENTION_POLICIES
    if policy["data_category"] == "engine_payload"
)


def _document(phone: str) -> bytes:
    """What a vendor document actually holds, which is why this store has a clock at all."""
    return json.dumps(
        {
            "execution_id": "exec_abc123",
            "from": phone,
            "to": "+911140000000",
            "transcript": "namaskaram, naaku appointment kavali",
        }
    ).encode()


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Payload Retention Clinic",
        slug=f"pyr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"pyr_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _archived_call(
    s3: FakeS3,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    days_ago: int,
    documents: int = 1,
    record_ref: bool = True,
) -> tuple[uuid.UUID, list[str]]:
    """A call that ENDED `days_ago`, with its raw payload(s) really in the store.

    `documents > 1` reproduces the shape the key layout exists for: the engine fires a
    document per status transition, so one call can hold several objects while
    `engine_payload_ref` names exactly one. An arm driven by the column would leave the
    siblings behind.
    """
    call_id = uuid7()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, '+911140000000', "
                ":w, :w, 90, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"pyr_{uuid.uuid4().hex[:12]}",
                "phone": f"+9198761{uuid.uuid4().int % 100000:05d}",
                "w": when,
            },
        )
    keys: list[str] = []
    for index in range(documents):
        key = await storage.archive_payload(
            tenant_id=tenant_id,
            call_id=call_id,
            engine="fake",
            execution_id=f"exec_{uuid.uuid4().hex[:12]}_{index}",
            document=_document("+919876500901"),
        )
        assert key is not None and key in s3.objects, "fixture precondition: object is stored"
        keys.append(key)
    if record_ref:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET engine_payload_ref = :k WHERE id = :i"),
                {"k": keys[0], "i": call_id},
            )
    return call_id, keys


async def _ref(tenant_id: uuid.UUID, call_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT engine_payload_ref FROM calls WHERE id = :i"), {"i": call_id}
            )
        ).scalar()
    return None if value is None else str(value)


# --- the clock ---------------------------------------------------------------------


async def test_a_payload_past_the_ttl_is_destroyed_and_a_younger_one_is_not(
    s3: FakeS3,
) -> None:
    """The whole finding in one test: the bytes go, the reference goes with them, and the
    call that is still inside its period keeps both."""
    tenant_id, agent_id = await _org()
    old_call, old_keys = await _archived_call(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=PAYLOAD_TTL_DAYS + 5
    )
    young_call, young_keys = await _archived_call(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=PAYLOAD_TTL_DAYS - 5
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 1, counts
    assert old_keys[0] not in s3.objects, "the archived vendor document survived its TTL"
    assert await _ref(tenant_id, old_call) is None
    assert young_keys[0] in s3.objects, "a payload inside its retention period was destroyed"
    assert await _ref(tenant_id, young_call) == young_keys[0]


async def test_every_document_of_an_expired_call_goes_not_only_the_one_named(
    s3: FakeS3,
) -> None:
    """Why the arm pages CALLS and hands them to `_erase_engine_payloads` instead of
    sweeping the key column. One call holds several documents and the column names one;
    a key-driven sweep would clear the reference and leave the siblings unreachable —
    which is the D-126 defect the prefix was introduced to remove."""
    tenant_id, agent_id = await _org()
    _, keys = await _archived_call(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=PAYLOAD_TTL_DAYS + 1, documents=3
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 3, counts
    assert not [key for key in keys if key in s3.objects], "a sibling document was left behind"


async def test_a_reference_naming_an_object_that_was_never_written_is_cleared(
    s3: FakeS3,
) -> None:
    """The termination guarantee, as a reachable state rather than a hypothetical.

    `archive_payload` commits `engine_payload_ref` BEFORE the PUT (deliberately — an
    object no column names would be unreachable), so a worker that died in between leaves
    a reference to nothing. `_erase_engine_payloads` returns early on an empty prefix and
    clears no reference, so without the sweep's own clearing statement that row would be
    selected again on every tick, for ever, and the arm would spin its whole budget on it.
    """
    tenant_id, agent_id = await _org()
    call_id, keys = await _archived_call(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=PAYLOAD_TTL_DAYS + 20
    )
    s3.objects.pop(keys[0])  # the PUT that never landed

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 0, "nothing was there to destroy"
    assert await _ref(tenant_id, call_id) is None, (
        "the dangling reference survived — this arm would re-select the row every night"
    )


async def test_an_object_store_outage_defers_this_arm_and_does_not_fail_the_tick(
    s3: FakeS3,
) -> None:
    """The asymmetry with the erasure path, asserted rather than assumed.

    An erasure that cannot reach the store RAISES, because a certificate must not claim a
    destruction that did not happen. A SWEEP owes nobody a document, so a store that will
    not answer stops this arm, leaves every reference pointing at an object that still
    exists, and lets the other categories expire. The next tick starts from the same
    oldest calls.
    """
    tenant_id, agent_id = await _org()
    call_id, keys = await _archived_call(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=PAYLOAD_TTL_DAYS + 2
    )
    s3.fail = True

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 0
    assert counts["deferred"] >= 1, "a deferred arm must say so"
    s3.fail = False
    assert keys[0] in s3.objects
    assert await _ref(tenant_id, call_id) == keys[0], (
        "a reference was cleared over an object that still exists — the object is now "
        "unreachable, which is the one outcome this ordering exists to prevent"
    )

    # And the deferral is a deferral: the next tick finishes the job.
    assert (await sweep_tenant(tenant_id))["engine_payloads"] == 1
    assert keys[0] not in s3.objects


async def test_one_tenants_sweep_reaches_no_other_tenants_payloads(s3: FakeS3) -> None:
    """Hard rule 1 on the new arm. The statement carries no `tenant_id` predicate — RLS
    is the isolation — and the object prefix is built from the tenant the sweep is inside,
    so both halves are asserted here."""
    mine, my_agent = await _org()
    theirs, their_agent = await _org()
    _, my_keys = await _archived_call(
        s3, tenant_id=mine, agent_id=my_agent, days_ago=PAYLOAD_TTL_DAYS + 30
    )
    their_call, their_keys = await _archived_call(
        s3, tenant_id=theirs, agent_id=their_agent, days_ago=PAYLOAD_TTL_DAYS + 30
    )

    counts = await sweep_tenant(mine)

    assert counts["engine_payloads"] == 1, counts
    assert my_keys[0] not in s3.objects
    assert their_keys[0] in s3.objects, "a tenant's sweep destroyed another tenant's payload"
    assert await _ref(theirs, their_call) == their_keys[0]
    # The other direction, so the assertion above cannot be passing on a sweep that did
    # nothing at all.
    assert (await sweep_tenant(theirs))["engine_payloads"] == 1
    assert their_keys[0] not in s3.objects


async def test_the_clock_survives_a_vendor_that_never_dated_the_call(s3: FakeS3) -> None:
    """`calls.ended_at` is vendor-supplied and nullable, and `_call_clock` falls back to
    our own `created_at` plus the metered duration. Without that fallback a call the
    engine never dated would match no predicate — so the archive of exactly those calls
    would be the one thing this arm could never expire."""
    tenant_id, agent_id = await _org()
    call_id, keys = await _archived_call(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=PAYLOAD_TTL_DAYS + 10
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET ended_at = NULL WHERE id = :i"), {"i": call_id}
        )

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 1, counts
    assert keys[0] not in s3.objects
