"""The archived RAW vendor payload is personal data, and an erasure must reach it.

`storage.archive_payload` keeps the engine's own document for a call — which carries the
caller's phone number and the transcript — and its key used to be
`engine-payloads/{engine}/{YYYY}/{MM}/{DD}/{execution_id}.json`. That key names no tenant
and no subject, so nothing could enumerate one person's copies: a DPDP §12 request could
not delete them, a tenant erasure could not delete them, and no `retention_policies`
category expires them (the enum is `recording|transcript|lead|consent_log`). The only
reason no breach existed was that the function had no caller and the store was empty —
which is the worst kind of safe, because the next slice to wire a debug archive would
have inherited an unerasable personal-data store with nothing telling it so.

D-126 gave the key a `{tenant}/{call}` prefix and added `_erase_engine_payloads` on both
erasure paths. The tests below therefore never assert against a column alone. An erasure
test that passes because the bucket was empty proves nothing, so each one WRITES the
object first, asserts it is really there, erases, and then asserts against `s3.objects` —
the bytes — with the reference checked beside it and never instead of it.

The object store is the `s3` fixture from `tests/conftest.py` (an S3 that lives in a dict
and can be told to fail), reused rather than duplicated for the reason
`recording_erasure_test` gives: a suite that SKIPS when MinIO is absent proves nothing
about the property it exists for.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import deletion_proof, export, tenant_erasure
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import retention, storage
from sqlalchemy import text
from tests.conftest import FakeS3

# What a vendor document actually looks like: the number and the spoken text, which is
# exactly why this store has an erasure duty. Never logged, only written to the fake.
RAW_PAYLOAD = {
    "execution_id": "exec_abc123",
    "from": "+919876500901",
    "to": "+911140000000",
    "transcript": "namaskaram, naaku appointment kavali",
}


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Payload Clinic",
        slug=f"pay-{uuid.uuid4().hex[:8]}",
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
            {"ref": f"pay_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _call_with_archived_payload(
    s3: FakeS3,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    phone: str,
    record_ref: bool = True,
) -> tuple[uuid.UUID, str]:
    """A call whose raw payload is REALLY in the store, written by `archive_payload`.

    Written through the production function rather than by putting bytes at a literal
    key: the erasure enumerates by the prefix `payload_key` produces, so a literal would
    keep passing while proving nothing about the key the archive actually writes.

    `record_ref=False` reproduces the crash window the design cares about — the archive
    is best-effort and the PUT lands before any column records it, so a worker that died
    in between leaves an object no `calls` row names.
    """
    call_id = uuid7()
    execution_id = f"exec_{uuid.uuid4().hex[:16]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, '+911140000000', "
                "now(), now(), 90, now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": execution_id, "phone": phone},
        )
    key = storage.archive_payload(
        tenant_id=tenant_id,
        call_id=call_id,
        engine="fake",
        execution_id=execution_id,
        payload={**RAW_PAYLOAD, "from": phone},
    )
    assert key is not None, "fixture precondition: the archive was written"
    assert key in s3.objects, "fixture precondition: the payload starts in the store"
    if record_ref:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET engine_payload_ref = :k WHERE id = :id"),
                {"k": key, "id": call_id},
            )
    return call_id, key


async def _file_request(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
                "requested_at, created_at) VALUES (:id, :t, :p, :ref, 'all', now(), now())"
            ),
            {"id": request_id, "t": tenant_id, "p": phone, "ref": export.subject_ref(phone)},
        )
    return request_id


async def _ref(tenant_id: uuid.UUID, call_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT engine_payload_ref FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
    return None if value is None else str(value)


async def _proof(tenant_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).first()
    assert row is not None and row[0] is not None, "the request completed and stored a proof"
    return dict(row[0])


# --- the key itself ----------------------------------------------------------------


def test_the_key_names_the_tenant_and_the_call() -> None:
    """The property the whole erasure arm rests on. Asked of the FUNCTION, because what
    matters is the shape of the key it produces, not how the f-string is written."""
    tenant_id, call_id = uuid.uuid4(), uuid.uuid4()
    key = storage.payload_key(
        tenant_id=tenant_id, call_id=call_id, engine="bolna", execution_id="exec-1"
    )

    assert key.startswith(f"engine-payloads/{tenant_id}/{call_id}/"), key
    assert key.startswith(storage.payload_call_prefix(tenant_id=tenant_id, call_id=call_id)), (
        "the prefix the erasure lists must be a prefix of the key the archive writes"
    )


def test_a_hostile_execution_id_cannot_escape_the_call_prefix() -> None:
    """`execution_id` is vendor-controlled. Object keys are opaque byte strings — no
    store resolves `..` — so the worst it can do is nest deeper INSIDE the prefix the
    erasure lists, which is still reached."""
    tenant_id, call_id = uuid.uuid4(), uuid.uuid4()
    key = storage.payload_key(
        tenant_id=tenant_id, call_id=call_id, engine="bolna", execution_id="../../../etc/passwd"
    )

    assert key.startswith(storage.payload_call_prefix(tenant_id=tenant_id, call_id=call_id))


def test_the_call_prefix_stops_at_the_segment_boundary() -> None:
    """The trailing slash, pinned — and pinned honestly.

    It cannot today separate two CALLS: uuids are fixed length, so no call id can be a
    strict prefix of another and dropping the slash would change nothing between them.
    (A first version of this test claimed otherwise and passed while the slash was
    sabotaged away, which is the exact failure this suite exists to refuse.) What the
    slash actually buys is a prefix bounded at the path segment: anything appended to the
    call segment by a future key layout — a `-raw` variant, a per-attempt suffix — is
    OUTSIDE this prefix and would be swept in silently without it, and an erasure whose
    reach quietly widens or narrows with a key change is how the D-126 defect was born.
    """
    tenant_id, call_id = uuid.uuid4(), uuid7()
    prefix = storage.payload_call_prefix(tenant_id=tenant_id, call_id=call_id)

    assert prefix.endswith("/")
    assert not f"engine-payloads/{tenant_id}/{call_id}-raw/x.json".startswith(prefix)


# --- the subject erasure -----------------------------------------------------------


async def test_the_erasure_destroys_the_archived_payload_and_not_only_the_pointer(
    s3: FakeS3,
) -> None:
    """Write it, prove it is there, erase, prove the BYTES are gone."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500901"
    call_id, key = await _call_with_archived_payload(
        s3, tenant_id=tenant_id, agent_id=agent_id, phone=phone
    )
    # The object is really the personal data this test claims it is.
    assert phone in json.loads(s3.objects[key])["from"]

    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request({}, {"tenant_id": tenant_id, "request_id": request_id})

    assert key not in s3.objects, "the archived payload itself must be gone from storage"
    assert await _ref(tenant_id, call_id) is None, "and the reference goes with it"


async def test_a_sibling_archive_no_column_names_is_erased_too(s3: FakeS3) -> None:
    """One call can hold SEVERAL archived documents — the engine fires a payload per
    status transition — and `engine_payload_ref` holds one key. The delete is driven by
    the prefix listing, so the ones no column names die with the one that is named.

    This is also the crash window: PUT lands, the process dies before the reference moves.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500902"
    call_id, named = await _call_with_archived_payload(
        s3, tenant_id=tenant_id, agent_id=agent_id, phone=phone
    )
    unnamed = storage.archive_payload(
        tenant_id=tenant_id,
        call_id=call_id,
        engine="fake",
        execution_id=f"exec_{uuid.uuid4().hex[:16]}",
        payload={**RAW_PAYLOAD, "from": phone},
    )
    assert unnamed is not None and unnamed in s3.objects and unnamed != named

    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request({}, {"tenant_id": tenant_id, "request_id": request_id})

    assert named not in s3.objects
    assert unnamed not in s3.objects, "a prefix walk is exactly what an unnamed copy needs"


async def test_an_erasure_with_no_archive_never_touches_object_storage(s3: FakeS3) -> None:
    """The gate, and it is an availability property rather than an optimisation: a DPDP
    erasure for a subject with nothing archived must not fail because the object store is
    down. `_erase_delivery_bodies` makes the same argument for the same reason.

    Sound because `archive_payload` requires the reference to be committed BEFORE the
    object is PUT: a reference with no object costs one wasted listing, an object with no
    reference cannot happen in that order.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500906"
    await _call_with_archived_payload(
        s3, tenant_id=tenant_id, agent_id=agent_id, phone=phone, record_ref=False
    )
    request_id = await _file_request(tenant_id, phone)
    s3.fail = True

    result = await retention.execute_deletion_request(
        {}, {"tenant_id": tenant_id, "request_id": request_id}
    )

    assert "payloads=0" in result, "no reference, no listing, no dependency on the store"


async def test_another_tenants_archive_is_untouched(s3: FakeS3) -> None:
    """The tenant segment is not decoration: one client's erasure may not reach another's
    bucket contents even when the calls share a caller."""
    phone = "+919876500903"
    mine_tenant, mine_agent = await _tenant()
    theirs_tenant, theirs_agent = await _tenant()
    _, mine = await _call_with_archived_payload(
        s3, tenant_id=mine_tenant, agent_id=mine_agent, phone=phone
    )
    _, theirs = await _call_with_archived_payload(
        s3, tenant_id=theirs_tenant, agent_id=theirs_agent, phone=phone
    )

    request_id = await _file_request(mine_tenant, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": mine_tenant, "request_id": request_id}
    )

    assert mine not in s3.objects
    assert theirs in s3.objects, "a cross-tenant delete would be the worse defect"


async def test_a_store_that_will_not_answer_aborts_the_erasure(s3: FakeS3) -> None:
    """Loud and retried beats quiet and false: no certificate may claim a destruction
    over a store we could not even list."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500904"
    call_id, key = await _call_with_archived_payload(
        s3, tenant_id=tenant_id, agent_id=agent_id, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    s3.fail = True

    with pytest.raises(storage.StorageUnavailableError):
        await retention.execute_deletion_request(
            {}, {"tenant_id": tenant_id, "request_id": request_id}
        )

    assert s3.objects.get(key) is not None, "nothing was deleted"
    assert await _ref(tenant_id, call_id) == key, "and no pointer was cleared ahead of the bytes"
    async with tenant_session(tenant_id) as session:
        completed = (
            await session.execute(
                text("SELECT completed_at FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar()
    assert completed is None, "the request stays open for the arq retry"

    # And the retry finishes the job it refused to fake.
    s3.fail = False
    await retention.execute_deletion_request({}, {"tenant_id": tenant_id, "request_id": request_id})
    assert key not in s3.objects


async def test_the_certificate_states_what_happened_to_the_archive(s3: FakeS3) -> None:
    """A store the erasure reaches must be reported by the document the data principal
    reads. `actions` is the half of the proof that passes through verbatim."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500905"
    await _call_with_archived_payload(s3, tenant_id=tenant_id, agent_id=agent_id, phone=phone)

    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request({}, {"tenant_id": tenant_id, "request_id": request_id})

    sentence = str((await _proof(tenant_id, request_id))["actions"]["engine_payloads"])  # type: ignore[index]
    assert sentence.startswith("1 archived raw engine payload(s) deleted"), sentence

    rendered = deletion_proof.certificate(await _proof(tenant_id, request_id))
    assert rendered is not None
    assert rendered["actions"]["engine_payloads"] == sentence, (
        "the certificate must carry the statement, not just the stored row"
    )


# --- the tenant erasure ------------------------------------------------------------


async def test_the_tenant_erasure_destroys_every_archived_payload(s3: FakeS3) -> None:
    """End of engagement: every subject at once, and the same statements per call."""
    tenant_id, agent_id = await _tenant()
    keys = [
        (
            await _call_with_archived_payload(
                s3, tenant_id=tenant_id, agent_id=agent_id, phone=f"+91987650100{n}"
            )
        )[1]
        for n in range(3)
    ]
    assert all(key in s3.objects for key in keys)

    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', updated_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )
    await retention.execute_tenant_erasure({}, {"tenant_id": tenant_id, "request_id": request_id})

    assert [key for key in keys if key in s3.objects] == [], "every archive must be gone"
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar()
    proof = dict(stored)
    assert proof["scope"]["engine_payloads_erased"] == 3  # type: ignore[index]
    rendered = tenant_erasure.certificate(proof)
    assert rendered is not None
    assert rendered["actions"]["engine_payloads"].startswith("3 archived raw engine payload(s)")
