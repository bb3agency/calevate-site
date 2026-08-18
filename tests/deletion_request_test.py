"""DPDP erasure REQUEST path — the producer for `execute_deletion_request`
(SEC-COMP §4, FLOWS §9).

`tests/retention_test.py` proves the worker erases and proves it. These prove the half
that was missing: that a real deletion request can be *made*, that making it writes the
row and queues the job together, that asking twice does not erase twice, and that the
answer to "has my data been erased?" is readable afterwards without a support ticket.

They also prove what that answer SAYS. The certificate is the durable artifact — filed,
forwarded, read years later — so the tests that read it assert what it admits as well as
what it claims: the recording audio the pointer-clear did not destroy, and the rule that
stopped it. `tests/erasure_certificate_test.py` covers the document itself, without a
database; these cover it arriving through the surface, built from a row a real worker
wrote.

Every phone number here is randomised. `audit_log` and `outbox_messages` are global
tables that other suites write to concurrently, so every assertion over them is scoped
by this test's own tenant id.
"""

from __future__ import annotations

import json
import logging
import uuid

from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import (
    DELETION_JOB,
    ERASURE_EXCEPTIONS,
    ERASURE_LIMITATIONS,
    FLOOR_OUTCOME,
    request_erasure,
)
from apps.api.compliance.deletion_routes import router as deletion_router
from apps.api.compliance.export import subject_ref
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.retention import REDACTED_MARK, execute_deletion_request
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

BASE = "/v1/compliance/deletion-requests"


def _phone() -> str:
    """A fresh subject per test: seven other suites run against this database."""
    return f"+9198765{uuid.uuid4().int % 100000:05d}"


async def _member(tenant_id: uuid.UUID, role: str) -> str:
    """A dev bearer token for a new member of an EXISTING org, in the given role."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant_id, agent_id, org slug, dev bearer token) for a fresh org with a member."""
    created = await admin_service.create_organization(
        name="Erasure Clinic",
        slug=f"del-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]
    return tenant_id, agent_id, str(slug), await _member(tenant_id, role)


async def _seed_call(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str) -> uuid.UUID:
    """One call with one transcript turn and one lead — enough for the worker to erase."""
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, "
                "'+911140000000', now(), now(), 61, 'recordings/y.wav', 'Booked an appointment', "
                "now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{call_id.hex[:10]}",
                "phone": phone,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'naaku appointment kavali', 'naaku appointment kavali', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :phone, 'Ravi', "
                "'inbound_call', 'new', '{\"intent\": \"book\"}'::jsonb, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id, "phone": phone},
        )
    return call_id


async def _rows(tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    async with tenant_session(tenant_id) as session:
        return [
            (row[0], row[1])
            for row in (
                await session.execute(
                    text("SELECT id, phone_e164 FROM deletion_requests ORDER BY requested_at")
                )
            ).all()
        ]


async def _jobs(tenant_id: uuid.UUID) -> list[dict[str, object]]:
    """Outbox rows this tenant produced for the erasure worker.

    `outbox_messages` is an infra table with no RLS, so the filter is explicit — and
    narrow enough that a concurrent suite's rows can never be counted as ours.
    """
    async with untenanted_session() as session:
        return [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_messages WHERE job = :job "
                        "AND payload->>'tenant_id' = :tid ORDER BY created_at"
                    ),
                    {"job": DELETION_JOB, "tid": str(tenant_id)},
                )
            ).all()
        ]


def _app() -> FastAPI:
    """`main.py` mounts this router; mounting it alone here keeps a failure pointed at
    this surface, and keeps the `permission_meta` boot contract honest either way. (This
    used to say the router was deliberately NOT mounted — it was already false, and
    `deletion_routes.py` corrected the same sentence in its own docstring.)"""
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(deletion_router)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def test_one_request_writes_one_row_and_queues_exactly_one_job() -> None:
    """The gap this closes: a row with no job is a promise nobody kept, and a job with
    no row is untraceable. They commit together or not at all."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        response = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["completed_at"] is None
    assert body["proof"] is None
    assert body["already_open"] is False
    assert body["subject_ref"] == subject_ref(phone)

    rows = await _rows(tenant_id)
    assert len(rows) == 1, "exactly one deletion_requests row"
    assert str(rows[0][0]) == body["request_id"]

    jobs = await _jobs(tenant_id)
    assert len(jobs) == 1, "exactly one queued erasure"
    assert jobs[0] == {"tenant_id": str(tenant_id), "request_id": body["request_id"]}


async def test_the_queued_payload_is_the_one_the_worker_already_expects() -> None:
    """The producer and the consumer have to agree, and nothing else in the repo made
    them meet. Feed the outbox payload straight to the worker and check it erases."""
    phone = _phone()
    tenant_id, agent_id, _slug, _token = await _tenant()
    call_id = await _seed_call(tenant_id, agent_id, phone=phone)

    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)

    payload = (await _jobs(tenant_id))[0]
    result = await execute_deletion_request({}, payload)
    assert "erased" in result

    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text("SELECT from_e164, recording_url, summary FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).first()
        turn = (
            await session.execute(
                text("SELECT text_redacted FROM transcript_turns WHERE call_id = :c"),
                {"c": call_id},
            )
        ).scalar()
        proof, completed_at = (
            await session.execute(
                text("SELECT proof, completed_at FROM deletion_requests WHERE id = :i"),
                {"i": record.id},
            )
        ).first() or (None, None)

    assert call is not None and call[0] is None and call[1] is None and call[2] is None
    assert turn == REDACTED_MARK
    assert completed_at is not None
    document = proof if isinstance(proof, dict) else json.loads(str(proof))
    assert document["subject_hash"] == subject_ref(phone), (
        "the request path and the proof must name the same subject, or nothing lines up"
    )


async def test_asking_twice_does_not_queue_a_second_erasure() -> None:
    """The idempotency key is (tenant, subject) restricted to OPEN requests: while an
    erasure is pending, a second ask returns the first request rather than duplicating
    it. A support agent who clicks twice must not queue two erasures."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        first = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        second = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))

    assert first.status_code == 201
    # 200, not 409: the caller's intent — "erase this person" — is already satisfied,
    # so an error would tell a support agent something went wrong when nothing did.
    assert second.status_code == 200, second.text
    assert second.json()["request_id"] == first.json()["request_id"]
    assert second.json()["already_open"] is True

    assert len(await _rows(tenant_id)) == 1, "the second ask wrote no second row"
    assert len(await _jobs(tenant_id)) == 1, "the second ask queued no second erasure"


async def test_a_completed_request_does_not_block_a_fresh_one() -> None:
    """The key is deliberately scoped to OPEN requests. Erasure is not terminal for a
    phone number — the same person can call again next month and generate new personal
    data — so a completed certificate must not make the next DPDP request unanswerable.
    """
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        first = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        assert first.status_code == 201
        await execute_deletion_request({}, (await _jobs(tenant_id))[0])

        second = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))

    assert second.status_code == 201
    assert second.json()["request_id"] != first.json()["request_id"]
    assert second.json()["already_open"] is False
    assert len(await _jobs(tenant_id)) == 2


async def test_the_status_of_a_request_is_readable_and_carries_the_proof() -> None:
    """ "Has my data been erased?" has to be answerable without a support ticket, and
    the certificate the worker writes is the thing that answers it."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        created = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        request_id = created.json()["request_id"]

        pending = await http.get(f"{BASE}/{request_id}", headers=_headers(token, slug))
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending"
        assert pending.json()["proof"] is None

        await execute_deletion_request({}, (await _jobs(tenant_id))[0])

        done = await http.get(f"{BASE}/{request_id}", headers=_headers(token, slug))

    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["proof"]["subject_hash"] == subject_ref(phone)
    assert body["proof"]["engine_deletion"] == "unconfirmed_pending_vendor_api"

    # What the erasure cannot do is stated, not hidden.
    assert body["limitations"] == list(ERASURE_LIMITATIONS)
    stated = " ".join(body["limitations"]).lower()
    assert "90" in stated and "recording" in stated, (
        "the TRAI recording floor must be visible to whoever hands this to the subject"
    )
    assert "consent_ledger" in stated

    # And stated INSIDE the certificate, not only beside it. The envelope is not what
    # gets filed — the proof is, and a proof that lists what it cleared while staying
    # silent about the audio that survived is the overclaim SEC-COMP §4 warns about.
    proof = body["proof"]
    assert proof["limitations"] == body["limitations"], (
        "the filed document and the response must not say different things"
    )
    assert proof["erased"], "the certificate still says what it destroyed"
    floor = [entry for entry in proof["not_erased"] if entry["outcome"] == FLOOR_OUTCOME]
    assert len(floor) == 1, "the recording floor is a named exception, not a footnote"
    assert "90" in floor[0]["authority"] and "§1" in floor[0]["authority"]
    assert floor[0]["count"] == 1, (
        "the seeded call is minutes old, so its recording was inside the 90-day floor "
        "when the erasure ran — the certificate states how many rather than disclaiming "
        "a number the job now stores in the proof"
    )
    assert "1 of those recordings" in floor[0]["why"]


async def test_the_certificate_says_what_the_stored_row_alone_cannot() -> None:
    """Where the durable row ends and the document begins, pinned end to end.

    `execute_deletion_request` clears `calls.recording_url` — the POINTER — at any age,
    and records exactly that: "recording pointer and summary cleared". True, and still
    misleading on its own, because the audio it pointed at is held under the TRAI
    90-day floor and this request did not delete it (SEC-COMP §1 against §4). The row
    is a record of facts; the certificate is what a client hands to a data principal,
    and it has to state the limits of those facts in words the reader can act on.

    Both halves are asserted here so the seam is visible: what the worker stored, what
    the API certifies, and the one field that must be identical in both.
    """
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        created = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        request_id = created.json()["request_id"]
        await execute_deletion_request({}, (await _jobs(tenant_id))[0])
        status = await http.get(f"{BASE}/{request_id}", headers=_headers(token, slug))

    async with tenant_session(tenant_id) as session:
        raw = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :i"), {"i": request_id}
            )
        ).scalar()
    stored = raw if isinstance(raw, dict) else json.loads(str(raw))

    # The row, as the worker leaves it: the pointer is reported cleared, and nothing in
    # it mentions the audio surviving. This is the gap, asserted rather than described.
    assert "recording pointer" in stored["actions"]["calls"]
    assert "not_erased" not in stored and "limitations" not in stored

    # The certificate, built from that row, states both halves.
    certificate = status.json()["proof"]
    assert certificate["subject_hash"] == stored["subject_hash"] == subject_ref(phone), (
        "the row and the document must name the same subject, or nothing lines up"
    )
    assert any("recording" in line.lower() for line in certificate["erased"])
    audio = [entry for entry in certificate["not_erased"] if entry["outcome"] == FLOOR_OUTCOME]
    assert len(audio) == 1
    # The PROPERTY, not the phrasing. This pinned the literal words "still existing"
    # until D-115 rewrote the sentence to say what actually happens now: the bytes are
    # held under a named retention obligation and destroyed on a stated date. A test that
    # pins prose blocks the prose from improving, and this file's subject is whether a
    # non-engineer is correctly informed — so assert that the sentence still tells them
    # the audio persists and when it goes.
    why = audio[0]["why"]
    assert "destroyed on" in why, (
        "a non-engineer must come away knowing the audio still exists and when it goes; "
        f"the certificate said: {why}"
    )
    assert "lifecycle" not in audio[0]["why"].lower(), (
        "SEC-COMP §4: no per-tenant mechanism deletes recording bytes, so the "
        "certificate must not hand the subject a deletion date derived from one"
    )


async def test_no_response_on_this_surface_carries_the_subjects_number() -> None:
    """The request record keeps the number so the worker can find the subject. Nothing
    that leaves the API does — a status page is read by more people than the request."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)
    national = phone.lstrip("+")[-10:]

    async with _client(_app()) as http:
        created = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        request_id = created.json()["request_id"]
        await execute_deletion_request({}, (await _jobs(tenant_id))[0])
        status = await http.get(f"{BASE}/{request_id}", headers=_headers(token, slug))

    for response in (created, status):
        assert national not in response.text
        assert phone not in response.text
    assert subject_ref(phone) in status.text

    # The certificate ALONE, which is the part that gets detached and filed. It grew a
    # limitations block; none of that prose may reintroduce the number, and the subject
    # is still named by the same hash the subject-access export files under — that
    # equality is how an auditor lines one person's two rights up (hard rule 6).
    filed = json.dumps(status.json()["proof"], ensure_ascii=False)
    assert national not in filed and phone not in filed
    assert status.json()["proof"]["subject_hash"] == subject_ref(phone)

    # The queued job carries no number either — the worker resolves it from the row.
    assert national not in json.dumps(await _jobs(tenant_id))


async def test_the_request_is_audited_and_the_audit_names_the_subject_by_hash(caplog) -> None:  # type: ignore[no-untyped-def]
    """An erasure request is a data-subject event `audit_log` exists to make answerable
    later. It is filed under the SAME `subject_ref` as the subject-access export, so an
    auditor can line the two rights up for one person — without either row becoming a
    searchable index of who exercised them (hard rule 6)."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=phone)

    with caplog.at_level(logging.INFO):
        async with _client(_app()) as http:
            response = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
    assert response.status_code == 201
    request_id = response.json()["request_id"]

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_id, object_type, actor_type, tenant_id FROM audit_log "
                    "WHERE action = 'dpdp.deletion_requested' AND tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert row is not None, "an unaudited erasure request is a rule-5 violation"
    assert row[0] == subject_ref(phone)
    assert row[1] == "data_subject"
    assert row[2] == "user"
    assert str(row[3]) == str(tenant_id)

    national = phone.lstrip("+")[-10:]
    assert national not in str(row[0])

    # The summary rides the log stream (audit_log has no summary column).
    summaries = [record for record in caplog.records if record.getMessage() == "audit"]
    assert summaries, "write_audit emits the summary it was given"
    emitted = json.dumps(
        {key: str(value) for key, value in summaries[-1].__dict__.items()}, default=str
    )
    assert national not in emitted
    assert phone.lstrip("+") not in emitted
    assert subject_ref(phone) in emitted
    assert request_id in emitted

    # And no application log line anywhere in this request carried the number.
    assert all(national not in record.getMessage() for record in caplog.records)


async def test_a_caller_without_the_permission_cannot_request_an_erasure() -> None:
    """Erasure is irreversible, so filing sits behind `org:manage` — owner-only in the
    client realm. Deleting the client's records is not a shift-worker decision."""
    phone = _phone()
    tenant_id, agent_id, slug, token = await _tenant(role="staff")
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        forbidden = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        anonymous = await http.post(BASE, json={"phone": phone})

    assert forbidden.status_code == 403, forbidden.text
    assert anonymous.status_code == 401, anonymous.text
    assert await _rows(tenant_id) == []
    assert await _jobs(tenant_id) == []


async def test_staff_may_answer_has_it_been_done_without_being_able_to_do_it() -> None:
    """The read is deliberately looser than the write (`org:read` vs `org:manage`): the
    status response carries no personal data, and "has this been done?" is the question
    whoever answers the phone gets asked."""
    phone = _phone()
    tenant_id, agent_id, slug, owner_token = await _tenant(role="owner")
    staff_token = await _member(tenant_id, "staff")
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        created = await http.post(BASE, json={"phone": phone}, headers=_headers(owner_token, slug))
        request_id = created.json()["request_id"]
        read = await http.get(f"{BASE}/{request_id}", headers=_headers(staff_token, slug))
        blocked = await http.post(
            BASE, json={"phone": _phone()}, headers=_headers(staff_token, slug)
        )

    assert created.status_code == 201
    assert read.status_code == 200, read.text
    assert read.json()["subject_ref"] == subject_ref(phone)
    assert blocked.status_code == 403, "reading a status is not authority to file one"


async def test_one_tenants_erasure_request_is_invisible_to_another(caplog) -> None:  # type: ignore[no-untyped-def]
    """Two clients can hold data about the same person. Each one's erasure request is
    theirs alone — RLS does the isolating and this proves the surface does not undo it
    (hard rule 1)."""
    phone = _phone()
    tenant_a, agent_a, slug_a, token_a = await _tenant()
    _tenant_b, _agent_b, slug_b, token_b = await _tenant()
    await _seed_call(tenant_a, agent_a, phone=phone)

    with caplog.at_level(logging.INFO):
        async with _client(_app()) as http:
            created = await http.post(
                BASE, json={"phone": phone}, headers=_headers(token_a, slug_a)
            )
            request_id = created.json()["request_id"]
            leaked = await http.get(f"{BASE}/{request_id}", headers=_headers(token_b, slug_b))
            own = await http.get(f"{BASE}/{request_id}", headers=_headers(token_a, slug_a))

    assert created.status_code == 201
    assert leaked.status_code == 404, "another tenant's request must not be readable"
    assert own.status_code == 200


async def test_a_number_we_hold_nothing_about_still_gets_a_request_and_a_certificate() -> None:
    """A client cannot know in advance whether they hold anything, and DPDP does not let
    them answer "we found nothing" without looking. The request is accepted, executed,
    and produces an empty-but-valid proof."""
    phone = _phone()
    tenant_id, _agent_id, slug, token = await _tenant()

    async with _client(_app()) as http:
        created = await http.post(BASE, json={"phone": phone}, headers=_headers(token, slug))
        assert created.status_code == 201
        await execute_deletion_request({}, (await _jobs(tenant_id))[0])
        status = await http.get(
            f"{BASE}/{created.json()['request_id']}", headers=_headers(token, slug)
        )

    assert status.json()["status"] == "completed"
    proof = status.json()["proof"]
    assert proof["scope"]["calls"] == []
    assert proof["scope"]["leads"] == []
    assert proof["erased"] == [
        "No call record held this number.",
        "No CRM lead held this number.",
    ]

    # "We found nothing" is the answer most likely to be filed as "nothing about you
    # remains", and it is exactly where an unqualified certificate misleads: a consent
    # ledger entry, a DNC suppression or a recording can exist for a number no call row
    # matched. The empty certificate states its limits in full, like every other one.
    assert proof["limitations"] == list(ERASURE_LIMITATIONS)
    assert [entry["outcome"] for entry in proof["not_erased"]] == [
        exception.outcome for exception in ERASURE_EXCEPTIONS
    ]


async def test_the_list_returns_this_accounts_requests_newest_first_and_no_numbers() -> None:
    """The index that makes a filed request survive closing the tab.

    Two things are asserted together on purpose: that the list is complete and ordered,
    and that it carries no phone number ANYWHERE in the body. A list is the one read on
    this surface that returns many subjects at once, so it is where the number would leak
    in bulk — every number this account has been asked to erase, in one response.
    """
    older, newer = _phone(), _phone()
    tenant_id, agent_id, slug, token = await _tenant()
    await _seed_call(tenant_id, agent_id, phone=older)

    async with _client(_app()) as http:
        first = await http.post(BASE, json={"phone": older}, headers=_headers(token, slug))
        second = await http.post(BASE, json={"phone": newer}, headers=_headers(token, slug))
        listed = await http.get(BASE, headers=_headers(token, slug))

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [row["request_id"] for row in rows] == [
        second.json()["request_id"],
        first.json()["request_id"],
    ], "newest first — the request a client is chasing is the one they just filed"

    assert rows[1]["subject_ref"] == subject_ref(older)
    assert rows[0]["status"] == "pending"
    assert rows[0]["completed_at"] is None
    assert rows[0]["has_certificate"] is False

    # Hard rule 6, on the response as a whole rather than field by field: a number added
    # to this shape by a later edit fails here whatever it is called.
    body = listed.text
    for phone in (older, newer):
        assert phone.lstrip("+") not in body
        assert phone[-10:] not in body
    assert "phone" not in body, "not even an empty or masked phone field belongs on an index"

    # The certificate is per request, never on the index — an index that carried every
    # proof on the account would make the cheapest read the largest.
    assert "proof" not in rows[0]

    async with _client(_app()) as http:
        await execute_deletion_request({}, (await _jobs(tenant_id))[0])
        after = await http.get(BASE, headers=_headers(token, slug))

    filed_id = first.json()["request_id"]
    done = next(row for row in after.json() if row["request_id"] == filed_id)
    assert done["status"] == "completed"
    assert done["completed_at"] is not None
    # `has_certificate` rather than `proof is None` reversed: "completed with no proof
    # recorded" is a real state the screen must be able to warn about, and a list that
    # inferred the certificate from the status would hide exactly that case.
    assert done["has_certificate"] is True


async def test_one_tenants_deletion_request_list_is_empty_to_another() -> None:
    """RLS cross-tenant zero rows (hard rule 1). The single-request read already answers
    404 across tenants; a LIST fails differently and worse — it would hand back another
    client's whole register of erasure obligations without anyone asking for an id.
    """
    phone = _phone()
    tenant_a, agent_a, slug_a, token_a = await _tenant()
    _tenant_b, _agent_b, slug_b, token_b = await _tenant()
    await _seed_call(tenant_a, agent_a, phone=phone)

    async with _client(_app()) as http:
        filed = await http.post(BASE, json={"phone": phone}, headers=_headers(token_a, slug_a))
        theirs = await http.get(BASE, headers=_headers(token_a, slug_a))
        others = await http.get(BASE, headers=_headers(token_b, slug_b))

    assert filed.status_code == 201
    assert [row["request_id"] for row in theirs.json()] == [filed.json()["request_id"]]
    assert others.json() == [], "another tenant's erasure register must read as empty"


async def test_listing_needs_a_session_and_only_the_read_permission() -> None:
    """Same split as the single read: `org:read` to see the register, `org:manage` to add
    to it. A staff member answering "where is that erasure up to?" needs the first and
    must not have the second."""
    tenant_id, agent_id, slug, owner_token = await _tenant(role="owner")
    staff_token = await _member(tenant_id, "staff")
    phone = _phone()
    await _seed_call(tenant_id, agent_id, phone=phone)

    async with _client(_app()) as http:
        await http.post(BASE, json={"phone": phone}, headers=_headers(owner_token, slug))
        staff = await http.get(BASE, headers=_headers(staff_token, slug))
        anonymous = await http.get(BASE)

    assert staff.status_code == 200, staff.text
    assert len(staff.json()) == 1
    assert anonymous.status_code == 401


async def test_an_unknown_request_id_is_a_404_not_a_500() -> None:
    _tenant_id, _agent_id, slug, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.get(f"{BASE}/{uuid.uuid4()}", headers=_headers(token, slug))
    assert response.status_code == 404
    assert response.json()["kind"] == "not_found"


async def test_a_malformed_number_is_refused_before_anything_is_queued() -> None:
    """Same E.164 gate as the subject-access export: a number we cannot dial is a number
    we cannot match, and an erasure that silently matches nothing is worse than a 422."""
    tenant_id, _agent_id, slug, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.post(
            BASE, json={"phone": "98765 43210"}, headers=_headers(token, slug)
        )
    assert response.status_code == 422
    assert await _rows(tenant_id) == []
    assert await _jobs(tenant_id) == []
