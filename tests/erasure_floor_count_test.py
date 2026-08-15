"""The TRAI-floor collision COUNT, from the erasure job to the filed certificate.

The half that was missing. `execute_deletion_request` has counted the collision between
the DPDP erasure duty (SEC-COMP §4) and the TRAI 90-day recording floor (SEC-COMP §1)
since the previous wave — how many of the recordings this request reached were still
inside the window and therefore could not lawfully be destroyed — and it put that number
on the job's return string and a WARNING and nowhere else. The certificate, which is the
document a client detaches and hands to a data principal, therefore had to say "this
certificate does not state how many", because after the pointer clear the question is
unanswerable: `calls.recording_url` is NULL for every row the request touched, and the
count cannot be reconstructed from the proof.

`tests/erasure_certificate_test.py` proved the renderer was ready for the number and
`tests/retention_conflicts_test.py` proved the worker computed it. Neither could prove
the number ARRIVES, because nothing carried it across. These tests are that crossing,
end to end: worker → `deletion_requests.proof` → `deletion_proof.certificate` → the HTTP
surface a client actually reads.

What is NOT under test here, deliberately: whether clearing the pointer inside the floor
is the right behaviour. SEC-COMP §4 reserves that for the founder and forbids making the
pointer-clear conditional on age until it is decided. Counting the collisions is what
gives whoever decides it a rate to decide against; it changes nothing about what the
erasure does.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import (
    DELETION_JOB,
    FLOOR_COUNT_KEY,
    FLOOR_OUTCOME,
    RECORDING_FLOOR_DAYS,
)
from apps.api.compliance.deletion_proof import certificate
from apps.api.compliance.deletion_routes import router as deletion_router
from apps.api.compliance.export import subject_ref
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import retention
from apps.workers.retention import execute_deletion_request
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import FakeS3

BASE = "/v1/compliance/deletion-requests"

# Model-written prose and caller speech, distinctive enough that a leak into a proof or
# a log line is unmistakable.
SUMMARY = "Caller asked to move her mother's appointment to Thursday"
TRANSCRIPT = "naaku appointment marchali"


def _phone() -> str:
    """A fresh subject per test: several suites share this database."""
    return f"+9198764{uuid.uuid4().int % 100000:05d}"


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{clerk_id}"


async def _org() -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant, agent, slug, bearer) for a fresh org whose agent the engine knows.

    The `engine_agent_routes` row is the bridge `publish_agent` writes in the same
    transaction as `agents.engine_agent_ref`; the retention sweep resolves its worklist
    from it, so a tenant with calls and no route is a shape production cannot produce.
    """
    created = await admin_service.create_organization(
        name="Floor Count Clinic",
        slug=f"efc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"efc_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id, str(slug), await _member(tenant_id)


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    days_ago: int,
    phone: str,
    recorded: bool = True,
) -> uuid.UUID:
    """One completed call, optionally still holding its recording pointer."""
    call_id = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, "
                "'+911140000000', :w, :w, 90, :rec, :s, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"efc_{call_id.hex[:10]}",
                "phone": phone,
                "w": when,
                "rec": "recordings/floor.wav" if recorded else None,
                "s": SUMMARY,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                ":txt, :txt, :w, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "txt": TRANSCRIPT, "w": when},
        )
    return call_id


async def _file_request(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
                "requested_at, created_at) VALUES (:i, :t, :p, :r, 'all', now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone, "r": subject_ref(phone)},
        )
    return request_id


async def _proof(tenant_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :i"), {"i": request_id}
            )
        ).first()
    assert row is not None and row[0] is not None, "the erasure wrote no proof at all"
    document: dict[str, Any] = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return document


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(deletion_router)
    return application


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _floor_entry(document: dict[str, Any]) -> dict[str, Any]:
    entries = [e for e in document["not_erased"] if e["outcome"] == FLOOR_OUTCOME]
    assert len(entries) == 1, "the recording floor is one named exception, not a footnote"
    entry: dict[str, Any] = entries[0]
    return entry


# ------------------------------------------------------ the key both halves agreed on


def test_the_worker_and_the_api_spell_the_proof_key_the_same_way() -> None:
    """Duplicated rather than imported, for the reason `RECORDING_FLOOR_DAYS` is: the
    worker must not pull the API's compliance package (and its outbox producer) in to
    name a JSON key, and the API must not import a worker module to read one. A shared
    string in two files is only safe while something asserts it is the same string."""
    assert retention.FLOOR_COUNT_KEY == FLOOR_COUNT_KEY
    assert retention.RECORDING_FLOOR_DAYS == RECORDING_FLOOR_DAYS


# --------------------------------------------------------- the durable half: the proof


async def test_the_stored_proof_records_how_many_recordings_were_inside_the_floor(
    s3: FakeS3,
) -> None:
    """The count has to be written where it survives the process that computed it.

    Two calls for one subject: one 10 days old (inside the floor, its audio may not
    lawfully be destroyed) and one 400 days old (outside it, and already past the
    tenant's 90-day recording TTL). The erasure clears both pointers — behaviour
    unchanged — and the proof now says ONE of them was a collision. A count of 2 would
    mean the age predicate was dropped; a missing key means the number still dies with
    the job.
    """
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    await _call(tenant_id, agent_id, days_ago=10, phone=phone)
    await _call(tenant_id, agent_id, days_ago=400, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    result = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    proof = await _proof(tenant_id, request_id)
    assert proof["scope"][FLOOR_COUNT_KEY] == 1, proof["scope"]
    assert len(proof["scope"]["calls"]) == 2, "both calls were still in scope"
    # The job's own report is unchanged — the log stream keeps working for whoever is
    # already watching it.
    assert "floor_recordings=1" in result


async def test_none_inside_the_floor_is_recorded_as_zero_not_as_absent(s3: FakeS3) -> None:
    """ "Absent is not zero" is the certificate's rule, and it cuts both ways: now that
    the job records the number, zero is a claim we CAN make and must make. A subject
    whose only recording is older than the floor gets "None of those recordings were
    inside the window", not "this certificate does not state how many"."""
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    await _call(tenant_id, agent_id, days_ago=400, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    proof = await _proof(tenant_id, request_id)
    assert proof["scope"][FLOOR_COUNT_KEY] == 0
    assert FLOOR_COUNT_KEY in proof["scope"], "zero must be recorded, not omitted"


async def test_an_erasure_that_matched_nothing_still_states_the_count() -> None:
    """The empty case. A client cannot know in advance whether they hold anything, and
    "we found no calls, so no recording was inside the window" is a complete answer they
    are entitled to give in writing — not a gap in the document."""
    phone = _phone()
    tenant_id, _, _, _ = await _org()
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    proof = await _proof(tenant_id, request_id)
    assert proof["scope"]["calls"] == []
    assert proof["scope"][FLOOR_COUNT_KEY] == 0


async def test_a_call_whose_pointer_was_already_gone_is_not_counted_as_a_collision() -> None:
    """The count is about AUDIO this request could not destroy, so a call that held no
    recording pointer when the erasure ran is not one — whether the sweep took it, an
    earlier erasure did, or the engine never sent one. Counting calls instead of
    recordings would inflate every certificate and make the rate useless to whoever has
    to decide §1 against §4."""
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    await _call(tenant_id, agent_id, days_ago=5, phone=phone, recorded=False)
    await _call(tenant_id, agent_id, days_ago=5, phone=phone, recorded=True)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    proof = await _proof(tenant_id, request_id)
    assert len(proof["scope"]["calls"]) == 2
    assert proof["scope"][FLOOR_COUNT_KEY] == 1


async def test_the_count_never_exceeds_the_calls_the_proof_names(s3: FakeS3) -> None:
    """A cheap internal-consistency check on the filed document: the collisions are a
    subset of the calls in scope. A reader who can only see the certificate has no other
    way to sanity-check the number."""
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    for days in (1, 45, 89, 91, 500):
        await _call(tenant_id, agent_id, days_ago=days, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    scope = (await _proof(tenant_id, request_id))["scope"]
    assert scope[FLOOR_COUNT_KEY] == 3, "1, 45 and 89 days old are inside the 90-day floor"
    assert scope[FLOOR_COUNT_KEY] <= len(scope["calls"])


# ------------------------------------------------------- the crossing: the certificate


async def test_the_count_reaches_the_certificate_a_client_actually_reads() -> None:
    """End to end, through the surface. The document that leaves the building must carry
    the number, in the machine-readable field a regulator tabulates AND in the sentence a
    data principal reads — and it must stop saying it does not know."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _org()
    await _call(tenant_id, agent_id, days_ago=3, phone=phone)
    await _call(tenant_id, agent_id, days_ago=20, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.get(f"{BASE}/{request_id}", headers=_headers(token, slug))

    assert response.status_code == 200, response.text
    document = response.json()["proof"]
    assert document["scope"][FLOOR_COUNT_KEY] == 2
    entry = _floor_entry(document)
    assert entry["count"] == 2
    assert "2 of those recordings" in entry["why"]
    assert "does not state how many" not in entry["why"], (
        "the certificate still disclaims a number it now has"
    )
    assert str(RECORDING_FLOOR_DAYS) in entry["why"]


async def test_the_certificate_says_none_rather_than_going_silent(s3: FakeS3) -> None:
    """The zero path through the same surface. "None of those recordings were inside the
    window" is a stronger statement than silence and it is now supportable."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _org()
    await _call(tenant_id, agent_id, days_ago=365, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        document = (await http.get(f"{BASE}/{request_id}", headers=_headers(token, slug))).json()[
            "proof"
        ]

    entry = _floor_entry(document)
    assert entry["count"] == 0
    assert "None of those recordings" in entry["why"]


def test_a_proof_written_before_this_change_still_certifies_honestly() -> None:
    """The renderer stays backward-compatible over durable rows. Every erasure completed
    before today has a proof with no such key, and those certificates must keep saying
    the number is not stated rather than acquiring a zero nobody counted (hard rule 4:
    the stored proof is never back-filled)."""
    legacy = {
        "subject_hash": "0" * 32,
        "executed_at": "2026-07-01T00:00:00+00:00",
        "scope": {
            "calls": ["a" * 32],
            "leads": [],
            "transcript_turns_erased": 2,
            "call_extractions_erased": 0,
        },
        "actions": {"calls": "phone numbers, recording pointer and summary cleared"},
        "engine_deletion": "unconfirmed_pending_vendor_api",
    }
    document = certificate(legacy)
    assert document is not None
    assert document["scope"][FLOOR_COUNT_KEY] is None
    assert "does not state how many" in _floor_entry(document)["why"]


# ----------------------------------------------------------------- it changes nothing


async def test_the_pointer_still_goes_at_every_age() -> None:
    """SEC-COMP §4 forbids making the pointer-clear conditional on age before the open
    decision is taken. Counting is a measurement, not a policy change, and this is the
    test that catches a "while we are here" refusal creeping in with it."""
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=1, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT recording_url, from_e164, summary FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).first()
    assert row is not None and tuple(row) == (None, None, None)


async def test_re_running_an_erasure_does_not_rewrite_the_count() -> None:
    """Idempotency, now that the proof carries one more fact. A re-run of a completed
    request returns `already_completed` before it reads anything, so the second run
    cannot replace a proof written when the recordings existed with a weaker one written
    after the pointers are already NULL — which is exactly what it would compute."""
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    await _call(tenant_id, agent_id, days_ago=7, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    first = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    before = await _proof(tenant_id, request_id)
    second = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    assert "floor_recordings=1" in first
    assert second == "already_completed"
    assert (await _proof(tenant_id, request_id)) == before
    assert before["scope"][FLOOR_COUNT_KEY] == 1


async def test_the_count_carries_no_number_into_the_proof_or_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6, re-checked over the one field that is new. A count is a count; the
    proof and the log stream may carry ids and counts and nothing else."""
    phone = _phone()
    tenant_id, agent_id, _, _ = await _org()
    await _call(tenant_id, agent_id, days_ago=4, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    with caplog.at_level(logging.DEBUG):
        await execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    filed = json.dumps(await _proof(tenant_id, request_id))
    assert phone not in filed and phone.lstrip("+")[-10:] not in filed
    emitted = "\n".join(
        record.getMessage() + " " + str(record.__dict__.get("recordings", ""))
        for record in caplog.records
        if not record.name.startswith("sqlalchemy")
    )
    for secret in (phone, TRANSCRIPT, SUMMARY):
        assert secret not in emitted, f"{secret!r} reached the log stream"
    assert not re.search(r"\+?9\d{9,}", emitted), emitted


async def test_the_job_name_the_outbox_publishes_is_still_the_one_that_runs() -> None:
    """A guard on the seam this change sits behind: the producer names the ARQ function
    by string, so a rename would silently stop every erasure — and every proof, count
    included — without failing anything that reads the certificate."""
    assert execute_deletion_request.__name__ == DELETION_JOB
