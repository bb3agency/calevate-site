"""Does the erasure ERASE? Proved by deleting and then looking in every store.

The failure this suite exists to catch cannot be seen by reading the row you just
deleted. `execute_deletion_request` has always nulled `calls.recording_url`, and every
assertion anyone had ever written about a recording checked exactly that column — so the
tests were green, the screen said "deleted", and the audio was still in the bucket. Worse
than still there: the cleared pointer was the only handle anything had on the key, and the
retention sweep selects `WHERE recording_url IS NOT NULL`, so **filing a DPDP erasure made
the recording permanently undeletable.** A caller who never asked to be forgotten had
their audio expire on the tenant's policy; a caller who DID ask had theirs orphaned.

Every test below therefore asserts against the OBJECT STORE — `s3.objects`, the actual
bytes — and never only against the column. Where a column assertion appears it is beside
an object assertion, never instead of one.

The three legal statements the code now encodes, with their sources, because a reviewer
at 3am should not have to take the design on trust:

- **DPDP §12(3)** — a Data Fiduciary "shall erase" on request "unless retention of the
  same is necessary for the specified purpose or for compliance with any law for the time
  being in force". A retention obligation is a reason to DEFER, not to refuse.
- **DPDP §8(7)** — storage limitation: keep personal data no longer than the purpose or a
  legal obligation requires. So the deferral has an end, and holding the audio past it is
  its own breach — which is why a deferred erasure is a scheduled destruction
  (`recording_erasure_holds`) and not a note in a certificate.
- **SECURITY-COMPLIANCE §1's retention floor** — for a recording INSIDE it, whether to
  destroy on request anyway is an open founder decision (§4). Nothing here takes it: no
  under-floor recording is destroyed early, and the pointer clear stays unconditional on
  age, which is what §4 forbids changing first.

The object store is a fake, reusing the `s3` fixture in `tests/conftest.py` rather than
growing a second one: local MinIO may not be running (it is not, on this machine),
and a suite that SKIPS proves nothing about the properties above. It answers like S3 and
can be told to fail, which is the half a real MinIO cannot easily be asked for.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import deletion, deletion_proof, export
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import retention, storage
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import FakeS3, accept_agreements

RECORDING_BYTES = b"RIFF....WAVEfmt not-really-audio"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Erasure Clinic",
        slug=f"eras-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    # The sweep resolves its tenants from `engine_agent_routes` — a call only ever exists
    # for a published agent, and `publish_agent` writes this row in the same transaction.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"eras_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _call_with_recording(
    s3: FakeS3, *, tenant_id: uuid.UUID, agent_id: uuid.UUID, days_ago: int, phone: str
) -> tuple[uuid.UUID, str]:
    """A call whose audio is REALLY in the store, under the key `copy_recording` writes.

    The key is built by `storage.recording_key` rather than typed as a literal: the
    erasure and the sweep both read the key back OUT of the column, so a literal would
    still pass while proving nothing about the shape the pipeline actually writes.
    """
    call_id = uuid7()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    key = storage.recording_key(tenant_id, call_id)
    s3.objects[key] = RECORDING_BYTES
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, "
                "'+911140000000', :w, :w, 90, :key, 'Booked an appointment', :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                # uuid4, NOT a slice of the uuid7 call id: uuid7 is time-ordered, so two
                # calls minted in the same millisecond share their leading hex and would
                # collide on `uq_calls_engine_call_id`.
                "e": f"exec_{uuid.uuid4().hex[:16]}",
                "phone": phone,
                "w": when,
                "key": key,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'naaku appointment kavali', 'naaku appointment kavali', :w, :w)"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "w": when},
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
            {
                "id": request_id,
                "t": tenant_id,
                "p": phone,
                "ref": export.subject_ref(phone),
            },
        )
    return request_id


async def _holds(tenant_id: uuid.UUID) -> list[tuple[str, datetime, datetime | None]]:
    async with tenant_session(tenant_id) as session:
        return [
            (str(row[0]), row[1], row[2])
            for row in (
                await session.execute(
                    text(
                        "SELECT object_key, erase_after, erased_at FROM recording_erasure_holds "
                        "ORDER BY erase_after"
                    )
                )
            ).all()
        ]


async def _proof(tenant_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, object] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT proof, completed_at FROM deletion_requests WHERE id = :r"),
                {"r": request_id},
            )
        ).first()
    assert row is not None
    return None if row[1] is None else dict(row[0])


# --- the retention sweep -----------------------------------------------------------


async def test_the_sweep_destroys_the_audio_and_not_only_the_pointer(s3: FakeS3) -> None:
    """A tenant's recording policy expiring must empty the BUCKET, not just a column.

    Before this, `recordings are kept for 90 days` was true of `calls.recording_url` and
    false of the audio, which sat under the bucket's 2555-day growth ceiling — the one
    SEC-COMP §4 records as unable to follow a per-tenant policy.
    """
    tenant_id, agent_id = await _tenant()
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone="+919876500101"
    )
    assert key in s3.objects, "fixture precondition: the audio starts in the store"

    counts = await retention.sweep_tenant(tenant_id)

    assert key not in s3.objects, "the audio itself must be gone from object storage"
    assert counts["recordings"] == 1
    async with tenant_session(tenant_id) as session:
        pointer = (await session.execute(text("SELECT recording_url FROM calls LIMIT 1"))).scalar()
    assert pointer is None, "and the pointer goes with it"


async def test_a_recording_inside_the_floor_survives_the_sweep(s3: FakeS3) -> None:
    """The floor is a MINIMUM and the sweep clamps to it: young audio is not touched."""
    tenant_id, agent_id = await _tenant()
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone="+919876500102"
    )

    await retention.sweep_tenant(tenant_id)

    assert s3.objects.get(key) == RECORDING_BYTES


async def test_a_store_that_will_not_answer_leaves_the_pointer_alone(s3: FakeS3) -> None:
    """Never a cleared reference to a surviving object — that is an unreachable orphan.

    The whole tick keeps going; only this arm defers, and the next one starts from the
    same oldest rows.
    """
    tenant_id, agent_id = await _tenant()
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone="+919876500103"
    )
    s3.fail = True

    counts = await retention.sweep_tenant(tenant_id)

    assert counts["recordings"] == 0
    assert counts["deferred"] >= 1
    async with tenant_session(tenant_id) as session:
        pointer = (await session.execute(text("SELECT recording_url FROM calls LIMIT 1"))).scalar()
    assert pointer == key, "the reference must still name the object that is still there"

    s3.fail = False
    assert (await retention.sweep_tenant(tenant_id))["recordings"] == 1
    assert key not in s3.objects, "and the next tick finishes the job it deferred"


# --- the erasure -------------------------------------------------------------------


async def test_an_erasure_past_the_floor_destroys_the_audio(s3: FakeS3) -> None:
    """No law requires keeping it, so DPDP §12(3) says erase — and erase means the bytes."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500104"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    assert key not in s3.objects
    assert await _holds(tenant_id) == [], "nothing to defer: the floor had already passed"
    proof = await _proof(tenant_id, request_id)
    assert proof is not None
    scope = proof["scope"]
    assert isinstance(scope, dict)
    assert scope[retention.DESTROYED_COUNT_KEY] == 1
    assert scope[retention.FLOOR_COUNT_KEY] == 0
    assert scope[retention.HOLD_UNTIL_KEY] is None


async def test_an_erasure_inside_the_floor_schedules_the_audio_instead_of_orphaning_it(
    s3: FakeS3,
) -> None:
    """THE REGRESSION THIS WHOLE SLICE IS ABOUT.

    The pointer is cleared at any age (unchanged — SEC-COMP §4 forbids making it
    conditional), the young audio is NOT destroyed early (also unchanged), and the thing
    that IS new is that the key survives the pointer clear on a row that names the day the
    bytes go. Assert all three, because dropping any one of them recreates the defect:
    without the hold the object is unreachable forever, and with an early destruction we
    would have taken a decision reserved to the founder.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500105"
    call_id, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    assert s3.objects.get(key) == RECORDING_BYTES, "under-floor audio is not destroyed early"
    async with tenant_session(tenant_id) as session:
        pointer = (
            await session.execute(
                text("SELECT recording_url FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
    assert pointer is None, "the pointer clear stays unconditional on age"

    holds = await _holds(tenant_id)
    assert len(holds) == 1, "the key must survive the pointer clear, or nothing can ever delete it"
    held_key, erase_after, erased_at = holds[0]
    assert held_key == key
    assert erased_at is None
    # 90 days from the CALL's clock, not from now: the call was 10 days old, so ~80 to go.
    remaining = (erase_after - datetime.now(UTC)).days
    assert 78 <= remaining <= 81, f"scheduled for the end of the floor, not {remaining}d out"


async def test_the_scheduled_destruction_actually_happens(s3: FakeS3) -> None:
    """A schedule nobody executes is the same defect wearing a date.

    The clock is moved on the HOLD ROW rather than by waiting: the sweep's predicate is
    `erase_after <= now()`, so a row dated in the past is exactly the state the ninetieth
    day produces.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500106"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert key in s3.objects

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE recording_erasure_holds SET erase_after = now() - interval '1 minute'")
        )

    counts = await retention.sweep_tenant(tenant_id)

    assert key not in s3.objects, "the deferred erasure must complete on its own"
    assert counts["recording_holds"] == 1
    holds = await _holds(tenant_id)
    assert holds[0][2] is not None, "and the row records when the bytes actually went"


async def test_a_hold_that_is_not_due_is_left_alone(s3: FakeS3) -> None:
    """The sweep must not be a slow way of taking the reserved decision."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500107"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    counts = await retention.sweep_tenant(tenant_id)

    assert counts["recording_holds"] == 0
    assert s3.objects.get(key) == RECORDING_BYTES


async def test_a_hold_survives_the_tenant_losing_its_recording_policy(s3: FakeS3) -> None:
    """A DPDP obligation must not become conditional on a retention SETTING.

    Swept outside the policy loop for exactly this: a client who deletes or never had a
    `recording` policy row still owes the destruction they were told would happen.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500108"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM retention_policies WHERE data_category = 'recording'")
        )
        await session.execute(
            text("UPDATE recording_erasure_holds SET erase_after = now() - interval '1 minute'")
        )

    assert (await retention.sweep_tenant(tenant_id))["recording_holds"] == 1
    assert key not in s3.objects


async def test_a_storage_outage_aborts_the_erasure_rather_than_certifying_it(
    s3: FakeS3,
) -> None:
    """Loud and retried beats quiet and false.

    The transaction rolls back whole: no proof, no `completed_at`, no hold row and no
    cleared pointer — so the retry redoes the entire erasure rather than resuming a
    half-erased subject.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500109"
    call_id, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    s3.fail = True

    with pytest.raises(storage.StorageUnavailableError):
        await retention.execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    assert await _proof(tenant_id, request_id) is None, "no certificate for a deletion not done"
    assert await _holds(tenant_id) == []
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT recording_url, from_e164 FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).first()
    assert row is not None
    assert row[0] == key, "nothing was erased, so nothing pretends to have been"
    assert row[1] == phone

    s3.fail = False
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert key not in s3.objects
    assert await _proof(tenant_id, request_id) is not None


async def test_re_running_a_completed_erasure_changes_nothing(s3: FakeS3) -> None:
    """Idempotent, including the new arm: no second destruction, no duplicate hold."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500110"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    payload = {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    await retention.execute_deletion_request({}, payload)
    first = await _holds(tenant_id)

    assert await retention.execute_deletion_request({}, payload) == "already_completed"

    assert await _holds(tenant_id) == first
    assert s3.objects.get(key) == RECORDING_BYTES


# --- everywhere else the person's data reached --------------------------------------


async def test_after_an_erasure_the_subject_is_absent_from_every_store_that_may_lose_them(
    s3: FakeS3,
) -> None:
    """Follow ONE subject all the way, and check each store separately.

    The point of enumerating them here rather than asserting a summary count is that a
    single missed store is exactly what a count hides. Both directions are asserted: what
    must be gone, and — in the next test — what must NOT be.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500111"
    call_id, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone=phone
    )
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', 'inbound_call', "
                "'new', '{\"callback\": \"+919876500111\"}'::jsonb, now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": phone},
        )
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "created_at, updated_at) VALUES (:i, :t, :c, 1, "
                '\'{"name": "Ravi", "phone": "+919876500111"}\'::jsonb, now(), now())'
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
    request_id = await _file_request(tenant_id, phone)

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text("SELECT from_e164, to_e164, recording_url, summary FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).first()
        turns = [
            row[0]
            for row in (
                await session.execute(
                    text("SELECT text, text_redacted FROM transcript_turns WHERE call_id = :c"),
                    {"c": call_id},
                )
            ).all()
        ]
        extraction = (
            await session.execute(
                text("SELECT data FROM call_extractions WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
        lead = (
            await session.execute(
                text("SELECT phone_e164, name, data FROM leads WHERE id = :i"), {"i": lead_id}
            )
        ).first()
        remaining_number = (
            await session.execute(
                text("SELECT phone_e164 FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar()

    assert call == (None, None, None, None), "the call keeps nothing that names a person"
    assert turns and all(turn == retention.REDACTED_MARK for turn in turns)
    assert extraction == {}, "the derived CRM copy of the transcript goes too"
    assert lead is not None
    assert not lead[0].startswith(phone[:6]) and lead[1] is None and lead[2] == {}
    assert remaining_number is None, "the request record is not the last copy of the number"
    assert key not in s3.objects, "and the audio is not in the bucket"

    # The document a data principal would be handed next must agree with all of that.
    async with tenant_session(tenant_id) as session:
        document = await export.build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)
    assert document["counts"] == {
        "leads": 0,
        "calls": 0,
        "transcript_turns": 0,
        "consent_records": 0,
        "recordings_available": 0,
    }


async def test_the_erasure_does_not_touch_what_must_survive(s3: FakeS3) -> None:
    """The other half of the obligation, and the one an over-eager fix would break.

    `consent_ledger` is the append-only proof that the calls were lawful — destroying it
    would remove the evidence that the processing was permitted, not reduce what is known
    about the person — and `usage_events` is an append-only billing ledger (hard rule 4).
    Both keep the number, and the certificate says so out loud.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500112"
    call_id, _ = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone=phone
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, captured_at, created_at) VALUES (:i, :t, :c, :p, 'recording', "
                "'granted', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "p": phone},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'platform_min', "
                "1.5, 2.6250, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
    request_id = await _file_request(tenant_id, phone)

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        consent = (
            await session.execute(
                text("SELECT phone_e164, status FROM consent_ledger WHERE call_id = :c"),
                {"c": call_id},
            )
        ).first()
        billed = (
            await session.execute(
                text("SELECT qty FROM usage_events WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
        duration = (
            await session.execute(
                text("SELECT duration_s FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()

    assert consent == (phone, "granted"), "the evidence that the call was lawful survives"
    assert billed is not None, "a closed billing period is not silently rewritten"
    assert duration == 90, "the call survives as a countable shell"

    proof = await _proof(tenant_id, request_id)
    assert proof is not None
    actions = proof["actions"]
    assert isinstance(actions, dict)
    assert "retained" in actions["consent_ledger"] and "retained" in actions["usage_events"]


async def test_the_retention_sweep_never_expires_the_consent_ledger(s3: FakeS3) -> None:
    """`consent_log` is a category in the table so the policy is EXPLICIT, not so a timer
    can eat the ledger (hard rule 4)."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500113"
    call_id, _ = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=4000, phone=phone
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, captured_at, created_at) VALUES (:i, :t, :c, :p, 'recording', "
                "'granted', now() - interval '4000 days', now() - interval '4000 days')"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "p": phone},
        )
        await session.execute(
            text("UPDATE retention_policies SET ttl_days = 1 WHERE data_category = 'consent_log'")
        )

    await retention.sweep_tenant(tenant_id)

    async with tenant_session(tenant_id) as session:
        survivor = (
            await session.execute(
                text("SELECT phone_e164 FROM consent_ledger WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
    assert survivor == phone


# --- the certificate ---------------------------------------------------------------


async def test_the_certificate_states_the_destruction_and_the_date(s3: FakeS3) -> None:
    """A data principal gets a date, not "treat the audio as still existing"."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500114"
    await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=200, phone=phone
    )
    await _call_with_recording(s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=5, phone=phone)
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    document = deletion_proof.certificate(await _proof(tenant_id, request_id))

    assert document is not None
    scope = document["scope"]
    assert isinstance(scope, dict)
    assert scope[deletion.DESTROYED_COUNT_KEY] == 1
    assert scope[deletion.FLOOR_COUNT_KEY] == 1
    assert isinstance(scope[deletion.HOLD_UNTIL_KEY], str)
    erased = document["erased"]
    assert isinstance(erased, list)
    assert any("audio was destroyed" in line for line in erased)
    recording_entry = next(
        entry
        for entry in document["not_erased"]  # type: ignore[union-attr]
        if entry["outcome"] == deletion.FLOOR_OUTCOME
    )
    assert "The last of them is destroyed on" in recording_entry["why"]
    assert str(scope[deletion.HOLD_UNTIL_KEY]) in recording_entry["why"]


def test_a_proof_written_before_any_of_this_still_renders_and_does_not_claim_zero() -> None:
    """Hard rule 4: old proofs are not back-filled, so the certificate must say what it
    does not know rather than certify a `0` nobody recorded."""
    document = deletion_proof.certificate(
        {
            "subject_hash": "a" * 32,
            "executed_at": "2026-01-01T00:00:00+00:00",
            "scope": {"calls": ["h1"], "leads": [], "transcript_turns_erased": 3},
            "actions": {"calls": "phone numbers, recording pointer and summary cleared"},
            "engine_deletion": "unconfirmed_pending_vendor_api",
        }
    )

    assert document is not None
    scope = document["scope"]
    assert isinstance(scope, dict)
    assert scope[deletion.DESTROYED_COUNT_KEY] is None
    assert scope[deletion.HOLD_UNTIL_KEY] is None
    erased = document["erased"]
    assert isinstance(erased, list)
    assert not any("audio was destroyed" in line for line in erased)
    recording_entry = next(
        entry
        for entry in document["not_erased"]  # type: ignore[union-attr]
        if entry["outcome"] == deletion.FLOOR_OUTCOME
    )
    assert "does not state how many" in recording_entry["why"]


def test_a_proof_that_counted_the_collision_but_had_no_schedule_says_so() -> None:
    """The middle state: a count with no date must not borrow the wording of one with."""
    document = deletion_proof.certificate(
        {
            "subject_hash": "b" * 32,
            "executed_at": "2026-02-01T00:00:00+00:00",
            "scope": {"calls": ["h1"], "leads": [], deletion.FLOOR_COUNT_KEY: 2},
            "actions": {},
            "engine_deletion": "unconfirmed_pending_vendor_api",
        }
    )

    assert document is not None
    recording_entry = next(
        entry
        for entry in document["not_erased"]  # type: ignore[union-attr]
        if entry["outcome"] == deletion.FLOOR_OUTCOME
    )
    assert "does not state a destruction date" in recording_entry["why"]
    assert "The last of them is destroyed on" not in recording_entry["why"]


def test_the_two_packages_spell_the_proof_keys_the_same() -> None:
    """They are duplicated rather than imported (a worker must not import the API's
    compliance package to name a JSON key), so the pin is a test."""
    assert deletion.DESTROYED_COUNT_KEY == retention.DESTROYED_COUNT_KEY
    assert deletion.HOLD_UNTIL_KEY == retention.HOLD_UNTIL_KEY
    assert deletion.FLOOR_COUNT_KEY == retention.FLOOR_COUNT_KEY
    assert deletion.RECORDING_FLOOR_DAYS == retention.RECORDING_FLOOR_DAYS


async def test_the_stored_proof_carries_no_phone_number(s3: FakeS3) -> None:
    """Hard rule 6, over the whole document rather than over the fields we remembered."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500115"
    await _call_with_recording(s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone)
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    proof = await _proof(tenant_id, request_id)
    assert phone not in json.dumps(proof)
    assert phone.lstrip("+") not in json.dumps(proof)


# --- the subject-access answer ------------------------------------------------------


async def test_the_access_export_does_not_answer_nothing_while_audio_is_still_held(
    s3: FakeS3,
) -> None:
    """§11 access AFTER §12 erasure, and the reason it cannot be answered off `calls`.

    An erasure nulls `from_e164`, `to_e164` and `deletion_requests.phone_e164` in the same
    breath, so afterwards NOTHING in the database can be matched to the person by their
    number: every other query in the export returns empty and the document says, in
    effect, "we hold nothing about you". While an under-floor recording is sitting on a
    scheduled destruction that is false. `subject_ref` — the hash that deliberately
    survives (D-44) — is the only handle left, and the erasure summary is keyed on it.

    An earlier version of this test asserted a query it had typed out ITSELF instead of
    calling `build_subject_export`, which is how it stayed green over a fix that could
    never fire: the LEFT JOIN it was pretending to check hung off `calls`, and an erased
    call matches no phone predicate, so the join could not reach a single row the export
    selects. A sabotage run caught it. It calls the real function now.
    """
    tenant_id, agent_id = await _tenant()
    phone = "+919876500116"
    await _call_with_recording(s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone)
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        document = await export.build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)

    assert document["calls"] == [], "the erasure really did clear every column"
    erasure = document["erasure"]
    assert isinstance(erasure, dict), "so the document must not stop there"
    assert erasure["completed_at"] is not None
    assert erasure["recordings_pending_destruction"] == 1
    assert erasure["recordings_destroyed_by"] is not None


async def test_the_export_says_nothing_about_an_erasure_nobody_asked_for(s3: FakeS3) -> None:
    """`null` and "an erasure with nothing outstanding" are different answers.

    A subject who has never asked must not be handed a document implying they did, and a
    subject whose erasure is finished down to the bytes must not be told one is pending.
    """
    tenant_id, agent_id = await _tenant()
    untouched = "+919876500117"
    await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=3, phone=untouched
    )
    async with tenant_session(tenant_id) as session:
        document = await export.build_subject_export(
            session, tenant_id=tenant_id, phone_e164=untouched
        )
    calls = document["calls"]
    assert isinstance(calls, list)
    assert calls[0]["recording_available"] is True
    assert document["erasure"] is None

    # And now one whose erasure destroyed everything it found: an object gone, no hold.
    finished = "+919876500119"
    await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=300, phone=finished
    )
    request_id = await _file_request(tenant_id, finished)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    async with tenant_session(tenant_id) as session:
        document = await export.build_subject_export(
            session, tenant_id=tenant_id, phone_e164=finished
        )
    erasure = document["erasure"]
    assert isinstance(erasure, dict)
    assert erasure["recordings_pending_destruction"] == 0
    assert erasure["recordings_destroyed_by"] is None


async def test_a_completed_hold_stops_being_reported_as_outstanding(s3: FakeS3) -> None:
    """Once the bytes are gone the honest answer is again "nothing is pending" — an export
    that kept counting honoured holds would tell a data principal we are still holding
    audio we destroyed."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500120"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE recording_erasure_holds SET erase_after = now() - interval '1 minute'")
        )
    await retention.sweep_tenant(tenant_id)
    assert key not in s3.objects

    async with tenant_session(tenant_id) as session:
        document = await export.build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)
    erasure = document["erasure"]
    assert isinstance(erasure, dict)
    assert erasure["recordings_pending_destruction"] == 0
    assert erasure["recordings_destroyed_by"] is None


# --- the table itself ---------------------------------------------------------------


async def test_a_neighbouring_tenant_sees_zero_holds(s3: FakeS3) -> None:
    """Hard rule 1, the mandatory cross-tenant zero-rows test for a new tenant table."""
    tenant_id, agent_id = await _tenant()
    phone = "+919876500118"
    _, key = await _call_with_recording(
        s3, tenant_id=tenant_id, agent_id=agent_id, days_ago=10, phone=phone
    )
    request_id = await _file_request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert len(await _holds(tenant_id)) == 1

    neighbour, _ = await _tenant()
    assert await _holds(neighbour) == []

    async with untenanted_session() as session:
        blind = (
            await session.execute(text("SELECT count(*) FROM recording_erasure_holds"))
        ).scalar()
    assert blind == 0, "and a session with no tenant GUC is fail-closed, not permissive"
    assert key in s3.objects


async def test_the_hold_table_is_not_an_append_only_ledger() -> None:
    """It is a worklist with a completion mark. Adding it to `APPEND_ONLY_TABLES` would
    make the sweep unable to record that it had done the work."""
    from apps.api.db.registry import APPEND_ONLY_TABLES

    assert "recording_erasure_holds" not in APPEND_ONLY_TABLES


# --- retention policies, enforced at WRITE time --------------------------------------


async def test_a_tenant_cannot_be_given_a_recording_ttl_below_the_floor() -> None:
    """The floor is a DB CHECK, so it holds against any writer — not only against the
    sweep, which is where a check is already too late to matter."""
    tenant_id, _ = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                    "action, created_at) VALUES (:i, :t, 'recording', 89, 'delete', now())"
                ),
                {"i": uuid7(), "t": tenant_id},
            )


async def test_a_zero_day_ttl_is_refused_by_the_database() -> None:
    """`ttl_days = 0` makes every row of the category expired the instant it is written,
    so the next tick would empty a live client's CRM."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM retention_policies WHERE data_category = 'lead'"))
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                    "action, created_at) VALUES (:i, :t, 'lead', 0, 'anonymize', now())"
                ),
                {"i": uuid7(), "t": tenant_id},
            )


async def test_a_second_policy_for_the_same_category_is_refused() -> None:
    """Two rows for one category is not a duplicate, it is an ambiguity: `sweep_tenant`
    applies both and the shorter TTL silently wins over the one the client agreed to."""
    tenant_id, _ = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                    "action, created_at) VALUES (:i, :t, 'lead', 30, 'anonymize', now())"
                ),
                {"i": uuid7(), "t": tenant_id},
            )


async def test_the_seeded_defaults_are_the_ones_a_new_tenant_actually_gets() -> None:
    """The onboarding flow and `scripts.seed.DEFAULT_RETENTION_POLICIES` are two places
    that must agree, and the DPA quotes a third (SEC-COMP §4, whose numbers differ — an
    open founder decision recorded there and pinned by
    `tests/dpdp_known_gaps_test.py`)."""
    from scripts.seed import DEFAULT_RETENTION_POLICIES

    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        rows = {
            str(row[0]): (int(row[1]), str(row[2]))
            for row in (
                await session.execute(
                    text("SELECT data_category, ttl_days, action FROM retention_policies")
                )
            ).all()
        }
    assert rows == {
        str(policy["data_category"]): (int(policy["ttl_days"]), str(policy["action"]))
        for policy in DEFAULT_RETENTION_POLICIES
    }
    assert rows["recording"][0] >= retention.RECORDING_FLOOR_DAYS
