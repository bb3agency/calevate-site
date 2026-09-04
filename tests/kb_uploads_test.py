"""Uploads, links and the ingest path (D-532) — the properties that must not regress.

The feature's whole point is that a client can hand their agent a DOCUMENT, so what is
worth testing is not that a row lands: it is the six places this could quietly go wrong.

1. **Tenancy.** `kb_uploads` names an object-storage key that dereferences to another
   business's price list, so hard rule 1's cross-tenant zero-rows test is mandatory here
   and the presigned-URL route makes it sharper than usual.
2. **The door.** A file we cannot read, and a file too large for the engine, are refused
   BEFORE anything is stored — with a sentence that names the next action.
3. **Who is reviewed.** An owner's PDF is live without waiting for us; a staff member's is
   not; and text a MODEL read off a photograph is never approved automatically, whoever
   uploaded it.
4. **What reaches the engine.** A client's PDF goes as the client's own bytes; a link goes
   as an address with no document beside it; everything else goes through the one renderer.
5. **A page that moved.** A re-scrape submits a NEW version for review and leaves the live
   one answering.
6. **Deletion.** The vendor's copy comes down BEFORE our rows go, or neither does.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.kb import service, uploads
from apps.workers import kb_ingest
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

#: A minimal, real PDF: `%PDF-` header, one object, `%%EOF`. Nothing parses it in these
#: tests — a PDF upload is passed through byte for byte — so what matters is that it is
#: bytes with a `.pdf` name, not that it renders.
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


# The object store is `tests/conftest.py`'s `FakeS3` — the suite's ONE fake bucket, asked
# for by name rather than re-implemented here. A second dict-backed S3 in this file would
# be a second answer to "what does the store do when a key is missing", which is exactly
# the divergence the KB path must not be tested against.


def _principal(tenant_id: uuid.UUID, role: str) -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role=role)


async def _upload_pdf(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    name: str = "Price list",
    auto_approve: bool = False,
    data: bytes = PDF,
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            filename="price-list.pdf",
            content_type="application/pdf",
            data=data,
            submitted_by=None,
            auto_approve=auto_approve,
        )


# --- 1. Tenancy (hard rule 1) --------------------------------------------------------


async def test_a_neighbours_upload_rows_are_zero_and_so_are_its_object_keys(
    s3: FakeS3,
) -> None:
    """The mandatory cross-tenant zero-rows test, and the reason it is worth more here.

    Every row of this table names an object-storage key, and one route turns that key into
    a PRESIGNED URL — a bearer credential for the file itself, with no further
    authentication in front of it. So "tenant B counts zero of tenant A's rows" is not a
    formality: it is the only thing between a neighbour and another business's price list.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()
    await _upload_pdf(tenant_a, agent_a)

    async with tenant_session(tenant_b) as session:
        rows = (await session.execute(text("SELECT count(*) FROM kb_uploads"))).scalar()
        keys = (
            await session.execute(
                text("SELECT count(*) FROM kb_uploads WHERE original_key IS NOT NULL")
            )
        ).scalar()
    assert rows == 0
    assert keys == 0

    async with untenanted_session() as session:
        # The ops view sees it — proving the zero above is the POLICY and not an empty table.
        assert (await session.execute(text("SELECT count(*) FROM kb_uploads"))).scalar() >= 1


# --- 2. The door ---------------------------------------------------------------------


def test_a_legacy_word_file_is_told_what_to_save_it_as() -> None:
    """A `.doc` is the file a shop owner actually has. "We cannot read that" is a dead
    end; "save it as .docx and upload it again" is a next step."""
    with pytest.raises(ProblemError) as raised:
        uploads.classify_upload(filename="menu.doc", content_type="application/msword")
    assert raised.value.code == "kb_upload_kind_unsupported"
    assert ".docx" in str(raised.value.remediation)


def test_a_kind_nothing_reads_names_the_kinds_that_work() -> None:
    with pytest.raises(ProblemError) as raised:
        uploads.classify_upload(filename="agent.exe", content_type="application/octet-stream")
    assert ".pdf" in str(raised.value.remediation)


def test_the_extension_decides_and_a_lying_content_type_does_not() -> None:
    """The `Content-Type` a browser sends is a hint we record and never route on."""
    assert uploads.classify_upload(filename="menu.pdf", content_type="text/plain") == "pdf"
    assert uploads.classify_upload(filename="menu.jpg", content_type="application/pdf") == "image"


async def test_a_file_over_the_vendors_ceiling_is_refused_before_a_byte_is_stored(
    s3: FakeS3,
) -> None:
    """The engine refuses a document over 20 MB, so we refuse it while the client still has
    the file in front of them — and, critically, before it is in the bucket. Accepting it
    and failing in a worker would leave bytes nobody asked for under a lifecycle rule."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    with pytest.raises(ProblemError) as raised:
        await _upload_pdf(tenant_id, agent_id, data=b"x" * (uploads.MAX_UPLOAD_BYTES + 1))
    assert raised.value.code == "kb_upload_too_large"
    assert raised.value.status == 413
    assert s3.objects == {}, "an oversized upload reached the bucket"


# --- 3. Who is reviewed --------------------------------------------------------------


def test_only_the_owner_self_approves_and_never_an_impersonating_operator() -> None:
    """The founder's rule, and the two clauses that keep it from widening.

    A STAFF member is reviewed even in an account whose owner switched staff curation on —
    that switch grants SUBMISSION and explicitly not approval — and an operator inside a
    view-as session cannot approve anything under a client's name (D-22).
    """
    tenant_id = uuid.uuid4()
    assert uploads.may_self_approve(_principal(tenant_id, "owner")) is True
    assert uploads.may_self_approve(_principal(tenant_id, "staff")) is False

    impersonating = Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="operator",
        impersonating=True,
    )
    assert uploads.may_self_approve(impersonating) is False


async def test_an_owners_pdf_is_approved_on_arrival_and_a_staff_members_waits(
    s3: FakeS3,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    owners = await _upload_pdf(tenant_id, agent_id, name="Owner list", auto_approve=True)
    staffs = await _upload_pdf(tenant_id, agent_id, name="Staff list", auto_approve=False)

    assert owners["review_state"] == "approved"
    assert staffs["review_state"] == "pending_approval"
    async with tenant_session(tenant_id) as session:
        approved_at = (
            await session.execute(
                text("SELECT approved_at FROM kb_sources WHERE id = :s"),
                {"s": owners["source_id"]},
            )
        ).scalar()
    assert approved_at is not None, "an auto-approval that records no approval is not one"


async def test_a_document_awaiting_its_text_cannot_be_approved_yet(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Not yet" and "you may not" are different answers, and a client who is told the
    first one reloads instead of filing a ticket."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Scanned menu",
            filename="menu.jpg",
            content_type="image/jpeg",
            data=b"\xff\xd8\xff\xe0 not really a jpeg",
            submitted_by=None,
            auto_approve=True,
        )
        assert row["review_state"] == "pending_approval", (
            "a photograph was approved before anybody had read what was on it"
        )
        with pytest.raises(ProblemError) as raised:
            await uploads.confirm_upload(
                session,
                tenant_id=tenant_id,
                upload_id=uuid.UUID(str(row["id"])),
                principal=_principal(tenant_id, "owner"),
            )
    assert raised.value.code == "kb_upload_not_ready"


# --- 4. What reaches the engine ------------------------------------------------------


async def test_publishing_an_uploaded_pdf_sends_the_clients_own_bytes(
    s3: FakeS3,
) -> None:
    """NOT a re-rendering of it. The artefact a human reviewed IS the document, and the
    only way to keep that true is to upload exactly what they read."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = await _upload_pdf(tenant_id, agent_id, auto_approve=True)

    async with tenant_session(tenant_id) as session:
        await service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(row["source_id"]))
        )

    attached = get_engine()._kb  # type: ignore[attr-defined]
    sent = [source for sources in attached.values() for source in sources]
    assert any(source.document == PDF for source in sent), (
        "the engine was handed something other than the bytes the client uploaded"
    )


async def test_publishing_a_link_sends_the_address_and_no_document(
    s3: FakeS3,
) -> None:
    """The engine scrapes the page itself, so there is nothing of ours to upload — and
    sending both would be refused by the adapter, because the vendor's route takes one or
    the other."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Opening hours",
            url="https://example.com/hours",
            submitted_by=None,
            auto_approve=True,
        )
        await service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(row["source_id"]))
        )

    attached = get_engine()._kb  # type: ignore[attr-defined]
    sent = [source for sources in attached.values() for source in sources]
    link = [source for source in sent if source.source_url]
    assert link, "the link never reached the engine"
    assert link[0].source_url == "https://example.com/hours"
    assert link[0].document is None, "a scraped page must not also carry a document"


async def test_a_link_to_an_address_we_will_not_fetch_is_refused_at_submission() -> None:
    """A client-supplied URL is fetched by US as well as by the vendor — the re-scrape
    sweep reads the page — so it is an SSRF surface and goes through the one gate."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await uploads.create_link(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Metadata",
                url="http://169.254.169.254/latest/meta-data/",
                submitted_by=None,
                auto_approve=False,
            )
    assert raised.value.code == "kb_link_refused"


# --- 5. A page that moved ------------------------------------------------------------


def test_the_page_digest_ignores_what_changes_on_every_request() -> None:
    """A re-render, a rotated token in a form or a changed asset hash is not new knowledge.
    A digest that moved on those would submit a version for review daily, which trains a
    client to approve without reading — a worse outcome than not noticing at all."""
    first = kb_ingest.page_digest(
        b"<html><head><style>.a{color:red}</style></head><body>  Chai  50\n</body></html>"
    )
    second = kb_ingest.page_digest(
        b"<html><head><style>.a{color:blue}</style></head><body>Chai 50</body>"
        b"<script>t('nonce-2')</script></html>"
    )
    assert first == second
    assert first != kb_ingest.page_digest(b"<html><body>Chai 60</body></html>")


async def test_a_changed_page_becomes_a_new_version_for_review_and_the_live_one_serves(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The founder's decision, and the answer to "what happens to the old knowledge base".

    Nothing happens to it here: a changed page submits a NEW version, `pending_approval`,
    and the live one keeps answering until a human approves the new one. Only then does
    `publish_source` attach the new vendor object and withdraw the old — attach first, so
    there is no window in which the agent knows nothing.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Opening hours",
            url="https://example.com/hours",
            submitted_by=None,
            auto_approve=True,
        )
        await service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(row["source_id"]))
        )

    async def _page(_url: str) -> bytes:
        return b"<html><body>Open 9 to 9 now</body></html>"

    monkeypatch.setattr(kb_ingest, "_fetch_page", _page)
    changed = await kb_ingest._recheck_link(
        upload_id=uuid.UUID(str(row["id"])),
        tenant_id=tenant_id,
        agent_id=agent_id,
        url="https://example.com/hours",
        known_digest="a-digest-from-the-last-reading",
        name="Opening hours",
    )
    assert changed is True

    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text(
                    "SELECT version, status, is_active FROM kb_sources "
                    "WHERE agent_id = :a AND name = 'Opening hours' ORDER BY version"
                ),
                {"a": agent_id},
            )
        ).all()
    assert [(v[0], v[1], v[2]) for v in versions] == [
        (1, "approved", True),
        (2, "pending_approval", False),
    ], "the live version stopped serving, or the new one did not arrive for review"


# --- 6. Deletion ---------------------------------------------------------------------


async def test_removing_an_upload_withdraws_the_vendors_copy_and_then_the_bytes(
    s3: FakeS3,
) -> None:
    """Order, and it is not negotiable: the engine's copy comes down first, because
    deleting our rows first destroys the only record of how that copy is addressed — a
    document that still answers a client's callers and that nothing of ours can find."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = await _upload_pdf(tenant_id, agent_id, auto_approve=True)
    async with tenant_session(tenant_id) as session:
        await service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(row["source_id"]))
        )
    assert s3.objects, "the upload never reached the bucket"

    async with tenant_session(tenant_id) as session:
        await uploads.remove_upload(
            session, tenant_id=tenant_id, upload_id=uuid.UUID(str(row["id"]))
        )

    async with tenant_session(tenant_id) as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE id = :s"), {"s": row["source_id"]}
            )
        ).scalar() == 0
        assert (
            await session.execute(
                text("SELECT count(*) FROM kb_uploads WHERE id = :u"), {"u": row["id"]}
            )
        ).scalar() == 0
    async with untenanted_session() as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM engine_kb_routes WHERE source_id = :s"),
                {"s": row["source_id"]},
            )
        ).scalar() == 0, "a claim on a vendor object outlived the object"
    assert s3.objects == {}, "the client's document is still in the bucket"
