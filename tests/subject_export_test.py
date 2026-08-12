"""DPDP subject access / portability export (SEC-COMP §4).

The erasure tests next door prove data goes away. These prove the other half of the
same obligation: that we can say what we hold about one person, completely, without
handing over anybody else's data in the process — and that saying it is recorded.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence

from apps.api.admin import service as admin_service
from apps.api.compliance.export import REDACTION_PENDING, build_subject_export, subject_ref
from apps.api.compliance.export_routes import router as export_router
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# An Aadhaar-shaped string planted in the RAW transcript column, with its redacted twin
# in `text_redacted`. If either form of the raw string ever reaches the export, the
# redaction boundary has been crossed.
RAW_AADHAAR = "4321 8765 1234"
REDACTED_AADHAAR = "[aadhaar ••••]"


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant_id, agent_id, org slug, dev bearer token) for a fresh org with a member."""
    created = await admin_service.create_organization(
        name="Export Clinic",
        slug=f"exp-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]

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
    return tenant_id, agent_id, str(slug), f"dev:client:{clerk_id}"


async def _seed_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    phone: str,
    summary: str | None = None,
    recording: str | None = None,
    turns: Sequence[tuple[int, str, str, str | None]] = (),
) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "outcome_tag, created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', "
                "'completed', :phone, '+911140000000', now(), now(), 74, :rec, :summary, "
                "'resolved', now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{call_id.hex[:12]}",
                "phone": phone,
                "rec": recording,
                "summary": summary,
            },
        )
        for idx, speaker, raw, redacted in turns:
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, :idx, :spk, "
                    ":raw, :red, now(), now())"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": tenant_id,
                    "c": call_id,
                    "idx": idx,
                    "spk": speaker,
                    "raw": raw,
                    "red": redacted,
                },
            )
    return call_id


async def _seed_lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str) -> uuid.UUID:
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, call_count, created_at, updated_at) VALUES (:i, :t, :a, :phone, 'Ravi', "
                "'inbound_call', 'hot', '{\"intent\": \"book\"}'::jsonb, 2, now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "phone": phone},
        )
    return lead_id


def _dumps(document: dict[str, object]) -> str:
    """`ensure_ascii=False` so the mask characters stay themselves: an escaped `\\u2022`
    would make an "is the redacted form present?" assertion silently unfalsifiable."""
    return json.dumps(document, ensure_ascii=False)


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _app() -> FastAPI:
    """The router is deliberately NOT mounted in `main.py` yet, so the HTTP-level test
    mounts it here. That also keeps the boot-assertion contract honest: if the route
    ever loses its `permission_meta`, mounting it anywhere starts failing."""
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(export_router)
    return application


async def test_the_export_carries_the_lead_the_calls_and_the_transcript() -> None:
    """The whole point: one number in, everything we hold about that person out."""
    phone = "+919876511001"
    tenant_id, agent_id, _slug, _token = await _tenant()
    lead_id = await _seed_lead(tenant_id, agent_id, phone=phone)
    first = await _seed_call(
        tenant_id,
        agent_id,
        phone=phone,
        summary="Caller booked an appointment.",
        recording="recordings/a.wav",
        turns=[
            (0, "agent", "Namaskaram, idi AI assistant.", "Namaskaram, idi AI assistant."),
            (1, "caller", "Naaku appointment kavali", "Naaku appointment kavali"),
        ],
    )
    second = await _seed_call(
        tenant_id, agent_id, phone=phone, turns=[(0, "caller", "Confirm cheyandi", None)]
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, captured_at, evidence, created_at) VALUES (:i, :t, :c, :p, 'recording', "
                "'granted', now(), '{\"span\": \"turn 1\"}'::jsonb, now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": first, "p": phone},
        )
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)

    assert document["phone_e164"] == phone, "the subject's own number is not masked from them"
    assert document["generated_at"]
    assert document["lead"] is not None
    assert document["lead"]["id"] == str(lead_id)
    assert document["lead"]["name"] == "Ravi"
    assert document["lead"]["data"] == {"intent": "book"}

    assert {call["call_id"] for call in document["calls"]} == {str(first), str(second)}
    by_id = {call["call_id"]: call for call in document["calls"]}
    assert by_id[str(first)]["summary"] == "Caller booked an appointment."
    assert by_id[str(first)]["duration_s"] == 74
    assert by_id[str(first)]["outcome_tag"] == "resolved"
    # A boolean, never a link — the recording is fetched through the audited endpoint.
    assert by_id[str(first)]["recording_available"] is True
    assert by_id[str(second)]["recording_available"] is False
    assert "recording_url" not in _dumps(document)

    turns = {entry["call_id"]: entry["turns"] for entry in document["transcripts"]}
    assert [turn["idx"] for turn in turns[str(first)]] == [0, 1]
    assert turns[str(first)][1]["speaker"] == "caller"
    assert turns[str(first)][1]["text"] == "Naaku appointment kavali"
    # A turn the redaction pass has not reached yet is named as such, never released raw.
    assert turns[str(second)][0]["text"] == REDACTION_PENDING

    assert len(document["consent"]) == 1
    assert document["consent"][0]["status"] == "granted"
    assert document["consent"][0]["call_id"] == str(first)
    # The consent EVIDENCE is a raw transcript span; the subject is told it exists.
    assert document["consent"][0]["evidence_recorded"] is True
    assert "span" not in _dumps(document)

    assert document["counts"] == {
        "leads": 1,
        "calls": 2,
        "transcript_turns": 3,
        "consent_records": 1,
        "recordings_available": 1,
    }


async def test_transcripts_are_the_redacted_view_never_the_raw_text() -> None:
    """A subject access request entitles the subject to THEIR data. A transcript can
    carry a third party's, so the export reads `text_redacted` — hard rule 5's
    redacted-by-default is reinforced here, not relaxed, because this is the response
    that leaves the client's screen and travels to an outsider."""
    phone = "+919876511002"
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _seed_call(
        tenant_id,
        agent_id,
        phone=phone,
        summary=f"Caller read out {RAW_AADHAAR} and asked us to call +919000012345 instead.",
        turns=[
            (0, "caller", f"naa aadhaar {RAW_AADHAAR}", f"naa aadhaar {REDACTED_AADHAAR}"),
            (1, "agent", "Thank you.", "Thank you."),
        ],
    )
    async with tenant_session(tenant_id) as session:
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)

    serialized = _dumps(document)
    assert RAW_AADHAAR not in serialized, "the raw transcript column must never ship"
    assert RAW_AADHAAR.replace(" ", "") not in serialized
    assert REDACTED_AADHAAR in serialized, "the redacted view IS what the subject gets"

    # The summary is model-written prose with no schema constraining it, so any OTHER
    # phone-shaped run is masked on the way out. The subject's own number is not.
    assert "+919000012345" not in serialized
    assert "9000012345" not in serialized
    assert document["phone_e164"] == phone


async def test_a_number_we_hold_nothing_about_gets_an_empty_but_valid_document() -> None:
    """ "We hold no data about you" is a complete and legally meaningful answer. A 404
    would say the request failed, which is a different and untrue statement."""
    tenant_id, _agent_id, _slug, _token = await _tenant()
    unknown = "+919876511003"
    async with tenant_session(tenant_id) as session:
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=unknown)

    assert document["phone_e164"] == unknown
    assert document["generated_at"]
    assert document["lead"] is None
    assert document["calls"] == []
    assert document["transcripts"] == []
    assert document["consent"] == []
    assert document["counts"] == {
        "leads": 0,
        "calls": 0,
        "transcript_turns": 0,
        "consent_records": 0,
        "recordings_available": 0,
    }


async def test_one_tenants_export_never_reaches_another_tenants_calls() -> None:
    """The same person may have called two of our clients. Each client's export is
    theirs alone — RLS does the isolating, and this proves the export does not undo it
    (hard rule 1)."""
    phone = "+919876511004"
    tenant_a, agent_a, _slug_a, _token_a = await _tenant()
    tenant_b, agent_b, _slug_b, _token_b = await _tenant()
    call_a = await _seed_call(tenant_a, agent_a, phone=phone, summary="A's conversation.")
    await _seed_lead(tenant_a, agent_a, phone=phone)
    call_b = await _seed_call(tenant_b, agent_b, phone=phone, summary="B's conversation.")

    async with tenant_session(tenant_b) as session:
        document = await build_subject_export(session, tenant_id=tenant_b, phone_e164=phone)

    ids = {call["call_id"] for call in document["calls"]}
    assert ids == {str(call_b)}
    assert str(call_a) not in _dumps(document)
    assert "A's conversation." not in _dumps(document)
    # A's lead row is A's alone, even though the phone number matches.
    assert document["lead"] is None
    assert document["counts"]["calls"] == 1


async def test_the_export_is_audited_and_the_audit_names_no_phone_number(caplog) -> None:  # type: ignore[no-untyped-def]
    """An export of one person's personal data is exactly the event `audit_log` exists
    to make answerable later. The subject is identified by a hash: the audit trail must
    not become a searchable index of everyone who exercised a right (hard rule 6)."""
    # `audit_log` is the one table here that is NOT tenant-scoped and NOT truncated
    # between runs, so a fixed number would match yesterday's row by its own hash.
    phone = f"+9198765{uuid.uuid4().int % 100000:05d}"
    tenant_id, agent_id, slug, token = await _tenant(role="owner")
    await _seed_lead(tenant_id, agent_id, phone=phone)
    await _seed_call(tenant_id, agent_id, phone=phone, turns=[(0, "caller", "Hello", "Hello")])

    with caplog.at_level(logging.INFO):
        async with _client(_app()) as http:
            response = await http.post(
                "/v1/compliance/subject-export",
                json={"phone": phone},
                headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
            )
    assert response.status_code == 200
    assert response.json()["counts"]["calls"] == 1

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_id, object_type, actor_type, tenant_id FROM audit_log "
                    "WHERE action = 'dpdp.subject_export' AND tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert row is not None, "an unaudited export of personal data is a rule-5 violation"
    assert row[0] == subject_ref(phone)
    assert row[1] == "data_subject"
    assert row[2] == "user"
    assert str(row[3]) == str(tenant_id)

    digits = phone.lstrip("+")
    national = digits[-10:]
    assert national not in str(row[0]), "the audit row identifies the subject by hash"

    # The summary rides the log stream (audit_log has no summary column), so that is
    # where it has to be checked.
    summaries = [record for record in caplog.records if record.getMessage() == "audit"]
    assert summaries, "write_audit emits the summary it was given"
    emitted = json.dumps(
        {key: str(value) for key, value in summaries[-1].__dict__.items()}, default=str
    )
    assert national not in emitted
    assert digits not in emitted
    assert subject_ref(phone) in emitted
