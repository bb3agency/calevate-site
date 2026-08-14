"""Knowledge-base content: what nothing expires, and what the certificate now admits.

Migration `842ba923796d` created `kb_sources`/`kb_documents` and stated, in prose that
`apps/api/kb/models.py`, `apps/api/kb/service.py`, DATA-MODEL §7 and BUILD-LOG §18 all
repeat: provider-side ids live in `kb_documents.meta`, "which is also what lets a DPDP
erasure prove it removed both copies."

No erasure removes either copy. Nothing in the repository has ever deleted a
`kb_documents` row: publishing a new version flips the old `kb_sources` row to
`archived`/`is_active = false` and leaves its chunks intact (`kb/service.publish_source`),
`retention_policies.data_category` admits only `recording|transcript|lead|consent_log`
(DATA-MODEL §9, enforced by a DB CHECK) so no TTL reaches the table, and
`execute_deletion_request` never names it. A client's uploaded knowledge — FAQs, price
lists, staff names, contact numbers — is therefore kept indefinitely, in our database and
on the engine's copy of every version we ever published.

**These tests do not fix that, and deliberately.** SECURITY-COMPLIANCE and DATA-MODEL
specify NOTHING for knowledge-base content: §4's retention row names recordings,
transcripts and leads; its erasure row enumerates "calls/turns/extractions/leads/
recordings"; DATA-MODEL §9 pins the category list at four. Adding a fifth category is a
DPA commitment and a documented-enum change, which is a founder/docs decision recorded
against ROADMAP §6 — not something a wave picks because the gap is annoying. So what is
here is the gap made EXECUTABLE (so it cannot be lost again) plus the one thing that was
squarely wrong and is now fixed: the certificate handed to a data principal said nothing
about knowledge-base content at all, which is the overclaim SEC-COMP §4 exists to
prevent. It says so now.

The day a `kb` retention category is decided, three of these tests are what fails, and
each names the decision it is waiting for.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import ERASURE_EXCEPTIONS, ERASURE_LIMITATIONS, KB_OUTCOME
from apps.api.compliance.deletion_proof import certificate
from apps.api.compliance.export import subject_ref
from apps.api.compliance.models import DATA_CATEGORIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.retention import apply_retention, execute_deletion_request, sweep_tenant
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

DATA_MODEL = Path(__file__).resolve().parents[1] / "docs" / "DATA-MODEL.md"
SEC_COMP = Path(__file__).resolve().parents[1] / "docs" / "SECURITY-COMPLIANCE.md"

# What a real clinic uploads. Every one of these strings is personal data about a
# third party, and none of it is a call record — which is exactly why no arm of the
# retention sweep and no part of the erasure path can see it.
KB_BODY = (
    "Dr Sunitha Rao consults Monday to Friday. For emergencies call the duty desk on "
    "+919000012345. Consultation fee 700 rupees. Ask for Lakshmi at reception."
)
KB_STAFF_NAME = "Sunitha Rao"
KB_STAFF_PHONE = "+919000012345"


def _phone() -> str:
    return f"+9198762{uuid.uuid4().int % 100000:05d}"


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with the shipped retention defaults and an agent the engine knows."""
    created = await admin_service.create_organization(
        name="KB Retention Clinic",
        slug=f"kbr-{uuid.uuid4().hex[:8]}",
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
            {"ref": f"kbr_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _kb_version(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    version: int,
    days_ago: int,
    active: bool,
    body: str = KB_BODY,
    engine_kb_ref: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """One knowledge source at one version, with its single chunk. Returns (source, doc).

    Written directly rather than through `kb/service.submit_source` so the row can be
    AGED: the point under test is what happens to knowledge that has been superseded for
    years, and the service always writes `now()`.
    """
    source_id, document_id = uuid.uuid4(), uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    meta = json.dumps({"engine_kb_ref": engine_kb_ref}) if engine_kb_ref else None
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, version, "
                "approved_at, published_at, is_active, created_at, updated_at) VALUES "
                "(:id, :t, :a, 'text', 'Clinic FAQ', :status, :v, :w, :w, :active, :w, :w)"
            ),
            {
                "id": source_id,
                "t": tenant_id,
                "a": agent_id,
                "status": "approved" if active else "archived",
                "v": version,
                "w": when,
                "active": active,
            },
        )
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, title, content, meta, "
                "created_at, updated_at) VALUES (:id, :t, :s, 0, 'Clinic FAQ', :body, "
                "CAST(:meta AS jsonb), :w, :w)"
            ),
            {
                "id": document_id,
                "t": tenant_id,
                "s": source_id,
                "body": body,
                "meta": meta,
                "w": when,
            },
        )
    return source_id, document_id


async def _document(tenant_id: uuid.UUID, document_id: uuid.UUID) -> tuple[Any, ...] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT content, meta, updated_at FROM kb_documents WHERE id = :i"),
                {"i": document_id},
            )
        ).first()
    return tuple(row) if row is not None else None


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, "
                "'+911140000000', now(), now(), 60, 'recordings/kb.wav', 'Asked about fees', "
                "now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"kbr_{call_id.hex[:10]}",
                "phone": phone,
            },
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


def _kb_entry(document: dict[str, Any]) -> dict[str, Any]:
    entries = [e for e in document["not_erased"] if e["outcome"] == KB_OUTCOME]
    assert len(entries) == 1, "exactly one register entry speaks for knowledge-base content"
    entry: dict[str, Any] = entries[0]
    return entry


# ================================================== 1. NO CATEGORY COVERS KB CONTENT


def test_the_retention_categories_are_the_four_the_data_model_enumerates() -> None:
    """The premise of everything below, pinned against the authoritative doc rather than
    against itself. DATA-MODEL §9 writes the category list out in full; a fifth appearing
    in code without the doc (or the reverse) is the drift this catches."""
    assert DATA_CATEGORIES == ("recording", "transcript", "lead", "consent_log")
    documented = DATA_MODEL.read_text(encoding="utf-8")
    assert "data_category ENUM[recording,transcript,lead,consent_log]" in documented, (
        "DATA-MODEL §9 no longer enumerates the same categories the code enforces"
    )


def test_neither_document_specifies_a_retention_period_for_knowledge_base_content() -> None:
    """Why this gap is REPORTED and not closed here.

    SEC-COMP §4's retention row names recordings, transcripts and leads and stops. Its
    erasure row enumerates the tables an erasure walks, and the knowledge base is not one
    of them. Choosing a TTL for a client's uploaded knowledge is a promise in the DPA, so
    it is a founder decision with a ROADMAP §6 entry — and this test is what fails the
    day it is taken, pointing the next engineer at the two places that must change with
    the code.
    """
    retention_row = "retention_policies per category with TTL enforcement job"
    erasure_row = "locate by phone across calls/turns/extractions/leads/recordings"
    document = SEC_COMP.read_text(encoding="utf-8")
    assert retention_row in document and erasure_row in document, (
        "SEC-COMP §4's rows have been rewritten — re-read them before trusting this file"
    )
    section = document.split(retention_row)[1].split("## 5.")[0]
    for absent in ("knowledge base", "knowledge_base", "kb_documents", "kb_sources"):
        assert absent not in section.lower(), (
            f"SEC-COMP §4 now says something about {absent!r}: the KB retention gap has "
            "been decided, and this file plus retention_policies must follow it"
        )


async def test_the_database_refuses_a_knowledge_base_retention_policy() -> None:
    """The CHECK constraint, not just the tuple. A tenant (or a well-meaning script)
    cannot opt knowledge-base content into the sweep by inserting a row: the category
    does not exist, so the promise cannot be made without a migration."""
    tenant_id, _ = await _org()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                    "action, created_at) VALUES (:i, :t, 'kb', 365, 'delete', now())"
                ),
                {"i": uuid.uuid4(), "t": tenant_id},
            )


# ============================================ 2. WHAT THAT MEANS FOR THE ACTUAL ROWS


async def test_a_superseded_knowledge_version_survives_every_sweep_at_any_age() -> None:
    """The defect in one row. Publishing v2 archives v1 (`is_active = false`,
    `status = 'archived'`) and leaves its chunks untouched, and no TTL reaches them — so
    a four-year-old draft that nobody can see on any screen still holds the staff names
    and numbers it was written with.

    Both versions are asserted: the live one must obviously survive, and the point is
    that the superseded one is indistinguishable from it to every retention mechanism we
    have.
    """
    tenant_id, agent_id = await _org()
    _, old = await _kb_version(tenant_id, agent_id, version=1, days_ago=1500, active=False)
    _, live = await _kb_version(tenant_id, agent_id, version=2, days_ago=1, active=True)

    counts = await sweep_tenant(tenant_id)

    superseded = await _document(tenant_id, old)
    assert superseded is not None and superseded[0] == KB_BODY, (
        "a superseded knowledge version was aged out — if that is now intended, this "
        "file and DATA-MODEL §9 are what record the decision"
    )
    current = await _document(tenant_id, live)
    assert current is not None and current[0] == KB_BODY
    # And the sweep does not silently pretend otherwise: nothing it counted was a KB row.
    assert set(counts) == {
        "recordings",
        "transcripts",
        "summaries",
        "leads",
        "extractions",
        # Delivered webhook bodies (D-23), on the `lead` clock. Listed here for the same
        # reason as the rest: this assertion is "every category the sweep counts, and no
        # knowledge-base row among them", so a new arm has to be named rather than
        # tolerated.
        "delivery_bodies",
        "deferred",
    }, counts


async def test_an_erasure_does_not_reach_knowledge_base_content_or_its_provider_handle() -> None:
    """The claim in migration `842ba923796d`, tested rather than believed.

    The subject's own number is put INTO the knowledge base here — the worst case the
    claim would have to cover, and one a client can produce by pasting a caller's
    callback number into an FAQ. The erasure runs, clears the call and the lead, and
    leaves the knowledge base exactly as it was: same content, same
    `meta.engine_kb_ref`, same `updated_at`. Both copies survive — ours and the engine's,
    which that handle addresses.
    """
    phone = _phone()
    tenant_id, agent_id = await _org()
    body = f"{KB_BODY} Callback for Mr Ravi: {phone}."
    _, document_id = await _kb_version(
        tenant_id, agent_id, version=1, days_ago=30, active=True, body=body, engine_kb_ref="rag_77"
    )
    before = await _document(tenant_id, document_id)
    await _call(tenant_id, agent_id, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    after = await _document(tenant_id, document_id)
    assert after == before, "the erasure changed knowledge-base content — decide it first"
    assert after is not None and phone in str(after[0]), (
        "the subject's number is still in the knowledge base after their erasure ran"
    )
    assert after[1] == {"engine_kb_ref": "rag_77"}, (
        "the provider handle the migration calls the proof of both copies is untouched"
    )


# ================================== 3. SO THE CERTIFICATE HAS TO SAY SO (this is fixed)


async def test_the_certificate_admits_the_knowledge_base_was_not_searched() -> None:
    """The half that WAS wrong and is now fixed.

    The certificate is the artifact a client detaches and hands to a data principal. It
    listed what was cleared and every exception the erasure knew about — and said nothing
    about the knowledge base, so a reader would conclude, reasonably, that everything we
    hold about them had been searched. It had not been.
    """
    phone = _phone()
    tenant_id, agent_id = await _org()
    await _kb_version(tenant_id, agent_id, version=1, days_ago=10, active=True)
    await _call(tenant_id, agent_id, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :i"), {"i": request_id}
            )
        ).scalar()
    document = certificate(stored if isinstance(stored, dict) else json.loads(str(stored)))
    assert document is not None

    entry = _kb_entry(document)
    said = f"{entry['what']} {entry['why']} {entry['authority']}".lower()
    assert "knowledge base" in said
    # A non-engineer must come away knowing two things: it was not searched, and nothing
    # expires it either.
    assert "not searched" in said or "neither searched" in said
    assert "indefinitely" in said or "no retention" in said
    assert "§4" in entry["authority"], "the reader needs the section by name"
    # Never claimed as erased.
    assert not any("knowledge" in line.lower() for line in document["erased"])


def test_the_knowledge_base_entry_is_part_of_the_one_register_not_a_second_list() -> None:
    """`ERASURE_LIMITATIONS` (prose) and `ERASURE_EXCEPTIONS` (structured) are paired by
    index, and the pairing is the only thing stopping one from being widened while the
    other stays narrow. A new entry has to land in both."""
    assert len(ERASURE_LIMITATIONS) == len(ERASURE_EXCEPTIONS)
    kb = [e for e in ERASURE_EXCEPTIONS if e.outcome == KB_OUTCOME]
    assert len(kb) == 1
    prose = ERASURE_LIMITATIONS[ERASURE_EXCEPTIONS.index(kb[0])]
    assert kb[0].keyword.lower() in prose.lower()
    assert "knowledge base" in prose.lower()


# =========================================================== 4. HARD RULE 6, THROUGHOUT


async def test_no_knowledge_base_content_reaches_the_logs_or_the_proof(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ids and counts only. Both jobs run over a tenant holding knowledge with staff
    names and a contact number in it; neither may emit a word of it, and neither may put
    it in a certificate that is then filed and forwarded."""
    phone = _phone()
    tenant_id, agent_id = await _org()
    await _kb_version(tenant_id, agent_id, version=1, days_ago=1500, active=False)
    await _kb_version(tenant_id, agent_id, version=2, days_ago=2, active=True)
    await _call(tenant_id, agent_id, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    with caplog.at_level(logging.DEBUG):
        await apply_retention({})
        await execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    emitted = "\n".join(
        record.getMessage() for record in caplog.records if not record.name.startswith("sqlalchemy")
    )
    assert "retention_sweep" in emitted and "deletion_executed" in emitted, (
        "neither job logged at all — this test would then be vacuous"
    )
    for secret in (KB_STAFF_NAME, KB_STAFF_PHONE, KB_BODY):
        assert secret not in emitted, f"{secret!r} reached the log stream"
    assert not re.search(r"\+?9\d{9,}", emitted), emitted

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :i"), {"i": request_id}
            )
        ).scalar()
    filed = json.dumps(certificate(stored if isinstance(stored, dict) else json.loads(str(stored))))
    for secret in (KB_STAFF_NAME, KB_STAFF_PHONE, phone):
        assert secret not in filed, f"{secret!r} reached the certificate"
