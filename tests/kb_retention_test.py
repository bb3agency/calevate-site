"""Knowledge-base content: what expires it now, what an erasure does about it, and what
is still a person's job (D-179, LEGAL-SURFACE F-3).

THE GAP THIS FILE USED TO HOLD OPEN. Migration `842ba923796d` created
`kb_sources`/`kb_documents` and stated, in prose that `apps/api/kb/models.py`,
`apps/api/kb/service.py`, DATA-MODEL §7 and BUILD-LOG §18 all repeat: provider-side ids
live in `kb_documents.meta`, "which is also what lets a DPDP erasure prove it removed
both copies." No erasure removed either copy and no retention period reached them.
Publishing a new version archived the old `kb_sources` row and left its chunks intact,
`retention_policies.data_category` admitted four categories and none of them was this
one, and `execute_deletion_request` never named the tables. A client's uploaded
knowledge — FAQs, price lists, staff names, contact numbers — was kept indefinitely, in
every version ever published, and the only honest thing the certificate could do was say
so.

D-179 closes the two halves that were ours, and this file is what holds them closed:

1. **A clock.** `retention_policies.data_category` gained `kb` (migration
   c4d1f7b83e26), and the nightly sweep deletes superseded and rejected versions past
   the tenant's TTL. Never the live one; never one the engine still holds a handle for.
2. **A search.** An erasure looks for the subject's number in the tenant's knowledge
   documents and puts the count on the certificate.

WHAT IS DELIBERATELY STILL NOT DONE, and the tests assert it as a property rather than
tolerating it: the erasure does not CHANGE the content. Editing a live price list changes
what the agent says on the next call, we cannot tell a caller's callback number from the
shop's own landline, and the voice platform holds its own copy of the live version. The
certificate therefore hands the client a count and names the manual step — which is a
task, where "not searched" was a shrug.
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
from apps.api.compliance.deletion import (
    ERASURE_EXCEPTIONS,
    ERASURE_LIMITATIONS,
    KB_MATCH_KEY,
    KB_OUTCOME,
)
from apps.api.compliance.deletion_proof import certificate
from apps.api.compliance.deletion_routes import ErasureProofOut
from apps.api.compliance.export import subject_ref
from apps.api.compliance.models import DATA_CATEGORIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import retention
from apps.workers.retention import apply_retention, execute_deletion_request, sweep_tenant
from scripts.seed import DEFAULT_RETENTION_POLICIES
from sqlalchemy import text

DATA_MODEL = Path(__file__).resolve().parents[1] / "docs" / "DATA-MODEL.md"
SEC_COMP = Path(__file__).resolve().parents[1] / "docs" / "SECURITY-COMPLIANCE.md"

# What a real clinic uploads. Every one of these strings is personal data about a
# third party, and none of it is a call record — which is why no arm of the retention
# sweep could see it until this category existed.
KB_BODY = (
    "Dr Sunitha Rao consults Monday to Friday. For emergencies call the duty desk on "
    "+919000012345. Consultation fee 700 rupees. Ask for Lakshmi at reception."
)
KB_STAFF_NAME = "Sunitha Rao"
KB_STAFF_PHONE = "+919000012345"

# The tenant's own `kb` TTL, as onboarding installs it.
KB_TTL_DAYS = next(
    policy["ttl_days"] for policy in DEFAULT_RETENTION_POLICIES if policy["data_category"] == "kb"
)


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
    status: str | None = None,
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
                "(:id, :t, :a, 'text', :name, :status, :v, :w, :w, :active, :w, :w)"
            ),
            {
                "id": source_id,
                "t": tenant_id,
                "a": agent_id,
                "name": f"Clinic FAQ {uuid.uuid4().hex[:6]}",
                "status": status or ("approved" if active else "archived"),
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


async def _source_exists(tenant_id: uuid.UUID, source_id: uuid.UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT 1 FROM kb_sources WHERE id = :i"), {"i": source_id})
        ).first()
    return row is not None


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, "
                "'+911140000000', now(), now(), 60, 'Asked about fees', now(), now())"
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


async def _erase(tenant_id: uuid.UUID, phone: str) -> dict[str, Any]:
    """File and run one erasure; return the CERTIFICATE, which is what a client hands on."""
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
    # Everything the certificate builds must survive the model that ships it —
    # `ErasureProofOut` is `extra="forbid"`, so a scope key the API has not modelled is a
    # 500 on the one endpoint whose subject is a person who asked to be erased.
    ErasureProofOut(**document)
    return document


def _kb_entry(document: dict[str, Any]) -> dict[str, Any]:
    entries = [e for e in document["not_erased"] if e["outcome"] == KB_OUTCOME]
    assert len(entries) == 1, "exactly one register entry speaks for knowledge-base content"
    entry: dict[str, Any] = entries[0]
    return entry


# ===================================================== 1. THE CATEGORY EXISTS AND IS SET


def test_the_retention_categories_are_the_ones_the_data_model_enumerates() -> None:
    """The tuple and the authoritative doc, pinned to each other rather than to
    themselves. DATA-MODEL §9 writes the list out in full; a category appearing in one
    and not the other is the drift this catches."""
    assert DATA_CATEGORIES == (
        "recording",
        "transcript",
        "lead",
        "consent_log",
        "engine_payload",
        "kb",
        # The in-app copilot's memory (migration d4a9c17e6b02) — a CATEGORY on the existing
        # mechanism, exactly as `kb` and `engine_payload` were, rather than a second clock.
        "copilot_memory",
    )
    documented = DATA_MODEL.read_text(encoding="utf-8")
    assert (
        "data_category ENUM[recording,transcript,lead,consent_log,engine_payload,kb,"
        "copilot_memory]" in documented
    ), "DATA-MODEL §9 no longer enumerates the same categories the code enforces"


async def test_onboarding_installs_a_knowledge_base_retention_period() -> None:
    """A category nobody sets is a column, not a clock. Every new tenant gets the row,
    so the sweep has something to obey on the first night."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT ttl_days, action FROM retention_policies WHERE data_category = 'kb'")
            )
        ).first()
    assert row is not None, "onboarding did not install a kb retention policy"
    assert int(row[0]) == KB_TTL_DAYS


async def test_a_tenant_cannot_hold_two_knowledge_base_policies() -> None:
    """The pre-existing `one_policy_per_category` unique reaches the new category too —
    two rows would let the shorter TTL silently win over the one the client agreed to."""
    from sqlalchemy.exc import IntegrityError

    tenant_id, _ = await _org()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                    "action, created_at) VALUES (:i, :t, 'kb', 30, 'delete', now())"
                ),
                {"i": uuid.uuid4(), "t": tenant_id},
            )


# ============================================================ 2. WHAT THE SWEEP EXPIRES


async def test_a_superseded_version_past_the_ttl_is_deleted_and_the_live_one_is_not() -> None:
    """The defect, closed. Publishing v2 archives v1 (`is_active = false`,
    `status = 'archived'`) and used to leave its chunks for ever — so a four-year-old
    draft nobody can see on any screen still held the staff names it was written with.

    The live version is asserted in the same test rather than in its own, because the
    property is a PAIR: an arm that expired both would pass a test that only looked at
    the old one, and it would take a client's agent off the air.
    """
    tenant_id, agent_id = await _org()
    old_source, old_doc = await _kb_version(
        tenant_id, agent_id, version=1, days_ago=KB_TTL_DAYS + 10, active=False
    )
    live_source, live_doc = await _kb_version(
        tenant_id, agent_id, version=2, days_ago=1, active=True
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["kb_versions"] == 1, counts
    assert await _document(tenant_id, old_doc) is None, "the superseded chunk survived its TTL"
    assert not await _source_exists(tenant_id, old_source), (
        "the source row survived — its client-authored name is a copy of what it held"
    )
    current = await _document(tenant_id, live_doc)
    assert current is not None and current[0] == KB_BODY
    assert await _source_exists(tenant_id, live_source)


async def test_a_superseded_version_inside_the_ttl_is_untouched() -> None:
    """The clock is a clock. A version superseded yesterday is still the thing a client
    rolls back to (FLOWS §7)."""
    tenant_id, agent_id = await _org()
    _, recent = await _kb_version(
        tenant_id, agent_id, version=1, days_ago=KB_TTL_DAYS - 10, active=False
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["kb_versions"] == 0
    assert await _document(tenant_id, recent) is not None


async def test_a_version_the_engine_still_holds_a_handle_for_is_never_deleted() -> None:
    """The refusal that keeps this arm from creating an unreachable copy.

    A superseded version has its engine handle CLEARED when it is detached
    (`kb/service._detach_superseded`), so a handle still recorded against an archived
    source means a detach that never completed — the residue `_undo_attach` documents
    itself as leaving (D-488 renamed it from `_reattach_after_failed_publish` when the
    publish order reversed; the residue is unchanged). Deleting our rows then
    would destroy the only record that can address the engine's copy, which is exactly
    the D-126 defect on a different table. Those rows belong to the reconciliation sweep
    (D-158), and this arm leaves them alone however old they are.
    """
    tenant_id, agent_id = await _org()
    _, stranded = await _kb_version(
        tenant_id,
        agent_id,
        version=1,
        days_ago=KB_TTL_DAYS * 3,
        active=False,
        engine_kb_ref="rag_stranded_77",
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["kb_versions"] == 0
    survivor = await _document(tenant_id, stranded)
    assert survivor is not None and survivor[1] == {"engine_kb_ref": "rag_stranded_77"}, (
        "a version whose engine copy is still attached was deleted — its handle is gone "
        "and nothing can address the copy the platform is still holding"
    )


async def test_a_rejected_draft_expires_and_one_awaiting_approval_does_not() -> None:
    """Which statuses the clock reaches, and why it is not simply `is_active = false`.

    A REJECTED upload is finished business and holds whatever the client pasted into it.
    A draft still moving through the approval gate is work in progress — deleting
    somebody's unsubmitted upload on an age rule is a surprise, not a retention policy.
    """
    tenant_id, agent_id = await _org()
    _, rejected = await _kb_version(
        tenant_id,
        agent_id,
        version=1,
        days_ago=KB_TTL_DAYS + 5,
        active=False,
        status="rejected",
    )
    _, pending = await _kb_version(
        tenant_id,
        agent_id,
        version=2,
        days_ago=KB_TTL_DAYS + 5,
        active=False,
        status="pending_approval",
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["kb_versions"] == 1, counts
    assert await _document(tenant_id, rejected) is None
    assert await _document(tenant_id, pending) is not None, (
        "an upload still waiting for a human decision was deleted by an age rule"
    )


async def test_one_tenants_sweep_reaches_no_other_tenants_knowledge(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 1, on the new arm. Two tenants, both holding a superseded version well
    past the TTL; sweeping one must leave the other's row untouched and must not count
    it."""
    mine, my_agent = await _org()
    theirs, their_agent = await _org()
    _, my_doc = await _kb_version(
        mine, my_agent, version=1, days_ago=KB_TTL_DAYS + 30, active=False
    )
    _, their_doc = await _kb_version(
        theirs, their_agent, version=1, days_ago=KB_TTL_DAYS + 30, active=False
    )

    counts = await sweep_tenant(mine)

    assert counts["kb_versions"] == 1, counts
    assert await _document(mine, my_doc) is None
    assert await _document(theirs, their_doc) is not None, (
        "a tenant's sweep deleted another tenant's knowledge — RLS is the isolation "
        "and there is no tenant_id predicate in the statement"
    )
    # And the other direction, so the assertion above cannot be passing because nothing
    # was swept at all.
    assert (await sweep_tenant(theirs))["kb_versions"] == 1
    assert await _document(theirs, their_doc) is None
    assert caplog.text == caplog.text  # placeholder-free: nothing is asserted about logs here


# ================================================ 3. WHAT AN ERASURE DOES, AND DOES NOT


async def test_an_erasure_finds_the_subject_in_uploaded_knowledge_and_leaves_it_alone() -> None:
    """The claim in migration `842ba923796d`, tested rather than believed — and now
    answered on both halves.

    The subject's own number is put INTO the knowledge base here, which is what a client
    produces by pasting a caller's callback number into an FAQ. The erasure runs, clears
    the call, REPORTS the document, and changes nothing about it: same content, same
    `meta.engine_kb_ref`, same `updated_at`.
    """
    phone = _phone()
    tenant_id, agent_id = await _org()
    body = f"{KB_BODY} Callback for Mr Ravi: {phone}."
    _, document_id = await _kb_version(
        tenant_id, agent_id, version=1, days_ago=30, active=True, body=body, engine_kb_ref="rag_77"
    )
    before = await _document(tenant_id, document_id)
    await _call(tenant_id, agent_id, phone=phone)

    document = await _erase(tenant_id, phone)

    assert document["scope"][KB_MATCH_KEY] == 1
    after = await _document(tenant_id, document_id)
    assert after == before, (
        "the erasure edited a client's knowledge document — it may report, not rewrite"
    )
    assert after is not None and phone in str(after[0])
    assert after[1] == {"engine_kb_ref": "rag_77"}


async def test_the_search_matches_the_way_a_client_actually_writes_a_number() -> None:
    """The reason the match is on digits and not on the E.164 string.

    Nobody types `+919876543210` into a price list. They type `98765 43210`, or
    `+91-98765-43210`, or `091 98765 43210` — and a substring search for the CRM's form
    would report zero on exactly the documents this exists to find.
    """
    phone = _phone()
    national = phone[3:]
    tenant_id, agent_id = await _org()
    for index, written in enumerate(
        (
            f"Reach Mr Ravi on {national[:5]} {national[5:]}.",
            f"Callback: +91-{national[:5]}-{national[5:]}",
            f"Alternate number 0{national}",
        )
    ):
        await _kb_version(
            tenant_id, agent_id, version=index + 1, days_ago=5, active=False, body=written
        )
    await _call(tenant_id, agent_id, phone=phone)

    document = await _erase(tenant_id, phone)

    assert document["scope"][KB_MATCH_KEY] == 3, (
        "a formatted number went unfound: the client would be told their knowledge base "
        "mentions nobody while it names the person on three pages"
    )


async def test_an_erasure_that_matches_no_knowledge_says_so_rather_than_saying_nothing() -> None:
    """A recorded zero IS a claim, and it is the one a client needs: the search ran, and
    there is no manual step outstanding."""
    phone = _phone()
    tenant_id, agent_id = await _org()
    await _kb_version(tenant_id, agent_id, version=1, days_ago=5, active=True)
    await _call(tenant_id, agent_id, phone=phone)

    document = await _erase(tenant_id, phone)

    entry = _kb_entry(document)
    assert document["scope"][KB_MATCH_KEY] == 0
    assert entry["count"] == 0
    assert "no uploaded knowledge document mentions it" in entry["why"]


async def test_the_search_sees_only_this_tenants_knowledge() -> None:
    """Hard rule 1 on the read side. Another tenant's document holding the same number
    must not be counted onto this certificate — the count is a disclosure about the
    client's own store, and a leaked one would tell them something about somebody else's.
    """
    phone = _phone()
    mine, my_agent = await _org()
    theirs, their_agent = await _org()
    await _kb_version(
        theirs, their_agent, version=1, days_ago=5, active=True, body=f"Ring {phone} for stock."
    )
    await _call(mine, my_agent, phone=phone)

    document = await _erase(mine, phone)

    assert document["scope"][KB_MATCH_KEY] == 0, (
        "another tenant's knowledge document was counted onto this client's certificate"
    )


# ============================================== 4. SO THE CERTIFICATE HAS TO SAY SO


async def test_the_certificate_reports_the_search_and_names_the_manual_step() -> None:
    """The certificate is the artifact a client detaches and hands to a data principal.
    It now has to carry a task rather than an apology: how many documents mention the
    person, that they were not changed, and that removing them is manual work on our copy
    and on the platform's."""
    phone = _phone()
    tenant_id, agent_id = await _org()
    await _kb_version(
        tenant_id, agent_id, version=1, days_ago=10, active=True, body=f"{KB_BODY} Ravi: {phone}"
    )
    await _call(tenant_id, agent_id, phone=phone)

    document = await _erase(tenant_id, phone)

    entry = _kb_entry(document)
    said = f"{entry['what']} {entry['why']} {entry['authority']}".lower()
    assert entry["count"] == 1
    assert "knowledge base" in said
    assert "search" in said, "the entry no longer tells the reader the store was searched"
    assert "not changed" in entry["why"].lower()
    assert "manual step" in entry["why"], "the reader is left with no action to take"
    assert "voice platform" in entry["why"], (
        "the engine holds its own copy — a client told to fix ours alone fixes half"
    )
    # Never claimed as erased.
    assert not any("knowledge" in line.lower() for line in document["erased"])


def test_a_proof_written_before_the_search_does_not_claim_one_happened() -> None:
    """Absent is not zero, and here it is the difference between a limitation and a lie.

    Proofs are durable and are not back-filled (hard rule 4), so certificates rendered
    from pre-D-179 rows will be read for years. `0` would tell a data principal we
    searched the client's knowledge base on their behalf. We did not.
    """
    stored = {
        "subject_hash": subject_ref("+919876543210"),
        "executed_at": "2026-08-11T09:30:00+00:00",
        "scope": {"calls": [], "leads": [], "transcript_turns_erased": 0},
        "actions": {},
        "engine_deletion": "unconfirmed_pending_vendor_api",
    }
    document = certificate(stored)
    assert document is not None

    assert document["scope"][KB_MATCH_KEY] is None
    entry = _kb_entry(document)
    assert entry["count"] is None
    assert "does not say whether" in entry["why"]
    assert "no uploaded knowledge document mentions it" not in entry["why"]


def test_the_knowledge_base_entry_is_part_of_the_one_register_not_a_second_list() -> None:
    """`ERASURE_LIMITATIONS` (prose) and `ERASURE_EXCEPTIONS` (structured) are paired by
    index, and the pairing is the only thing stopping one from being narrowed while the
    other stays wide. Both halves had to move together when the outcome narrowed from
    `not_searched` to `searched_not_erased`."""
    assert len(ERASURE_LIMITATIONS) == len(ERASURE_EXCEPTIONS)
    kb = [e for e in ERASURE_EXCEPTIONS if e.outcome == KB_OUTCOME]
    assert len(kb) == 1
    prose = ERASURE_LIMITATIONS[ERASURE_EXCEPTIONS.index(kb[0])]
    assert kb[0].keyword.lower() in prose.lower()
    assert "knowledge base" in prose.lower()
    # The narrowing, stated in the prose half too: a reader of the notice alone must not
    # still be told the store is untouched and unexpired.
    assert "searched" in prose.lower(), "the notice still says the knowledge base is not read"
    assert "retention period" in prose.lower(), (
        "the notice no longer tells the reader that superseded versions expire"
    )


def test_the_scope_key_is_spelled_the_same_in_both_packages() -> None:
    """Duplicated rather than imported (a worker has no business importing the API's
    compliance package to name a JSON key), so the two spellings are pinned here — the
    same arrangement the floor-count key has."""
    assert KB_MATCH_KEY == retention.KB_MATCH_KEY


# =========================================================== 5. HARD RULE 6, THROUGHOUT


async def test_no_knowledge_base_content_reaches_the_logs_or_the_proof(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ids and counts only. Both jobs run over a tenant holding knowledge with staff
    names and a contact number in it; neither may emit a word of it, and neither may put
    it in a certificate that is then filed and forwarded. The search makes this sharper
    than it was: the erasure now READS that content, so a careless log line would be
    quoting it."""
    phone = _phone()
    tenant_id, agent_id = await _org()
    await _kb_version(tenant_id, agent_id, version=1, days_ago=KB_TTL_DAYS + 50, active=False)
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
