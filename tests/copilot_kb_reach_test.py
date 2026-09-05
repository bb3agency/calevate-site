"""WHAT OF A CLIENT'S KNOWLEDGE BASE THE COPILOT CAN ACTUALLY READ — the founder's
question, answered by driving it rather than by reading the code.

*"copilot should be able to access that client's KB which is stored on the VPS."*

`copilot/tools.py::_search_knowledge` reads through `retrieval/service.look_up`, whose two
tiers are the compiled T0 block (`prompt_versions.compiled_t0_context`, built by
`agents/t0.py` from `kb.service.active_knowledge`) and — when `retrieval_provider` is
`pgvector` — `kb_chunks`. **BOTH are built from `kb_documents`**: T0 by
`active_knowledge`'s join, T3 by `kb/service._PROJECT_SQL`'s. So the one question that
decides reachability is whether a source has `kb_documents` rows, and the D-534 ingest lane
answers it differently by KIND:

* a `.txt`/`.csv`/`.docx`/`.xlsx` upload and a photograph are read into TEXT by the
  conversion lane (`workers/kb_ingest._extract` → `kb_service.store_extracted_text`), so
  they have chunks and are reachable;
* a **PDF** and a **scraped link** are NOT (`ingest_kb_source`: `if kind not in ("pdf",
  "url")`). That is deliberate and is argued where it is written — a PDF *is* the document
  the engine is handed, so what a reviewer opens is byte-for-byte what the agent answers
  from, and a link is scraped by the engine itself. Neither leaves us any text.

The consequence for the copilot was not deliberate, and it is what these tests pin: those
two kinds are live, published, working knowledge that the agent CAN answer from on a call
and the dashboard assistant cannot see at all. The remedy is not to widen the tool —
inventing text for a PDF would change what goes into the agent's PROMPT, which is a voice
path decision and not this one's — it is that the tool must SAY SO instead of telling a
client to add a price list they have already uploaded.
"""

from __future__ import annotations

import json
import uuid

from apps.api.copilot.tools import ToolContext, run_read_tool
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb import uploads
from apps.workers import kb_ingest
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_uploads_test import PDF
from tests.kb_workflow_test import _tenant_with_published_agent


async def _ask(tenant_id: uuid.UUID, question: str) -> str:
    """The tool through its REAL entry point, exactly as `service._run_read_tools` calls it."""
    return await run_read_tool(
        "search_knowledge",
        json.dumps({"question": question}),
        context=ToolContext(tenant_id=tenant_id, role="owner"),
    )


async def _ingest(tenant_id: uuid.UUID, source_id: uuid.UUID, *, may_self_approve: bool) -> str:
    """The outbox job, run as the worker runs it — extraction, approval, publish."""
    return await kb_ingest.ingest_kb_source(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "source_id": str(source_id),
            "may_self_approve": may_self_approve,
        },
    )


async def _document_count(tenant_id: uuid.UUID, source_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM kb_documents WHERE source_id = :s"),
                    {"s": source_id},
                )
            ).scalar()
            or 0
        )


async def _upload_text(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, name: str, body: str, auto_approve: bool
) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        return await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            filename=f"{name.lower().replace(' ', '-')}.txt",
            content_type="text/plain",
            data=body.encode(),
            submitted_by=None,
            auto_approve=auto_approve,
        )


async def test_an_uploaded_document_is_reachable_by_the_copilot_once_it_is_published(
    s3: FakeS3,
) -> None:
    """THE HEADLINE, PROVEN END TO END. A client uploads a file, it goes through the gate,
    and the assistant can then answer a question out of it — no separate index, no second
    approval, no copy of the KB anywhere else.

    Driven the whole way: `create_upload` writes the object and the source version,
    `ingest_kb_source` is the OUTBOX JOB (extract → chunk → approve → publish), and the
    question goes through `run_read_tool` rather than the executor, so the permission
    check, the tenant session and the retrieval port are all on the path.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = await _upload_text(
        tenant_id,
        agent_id,
        name="Refund policy",
        body="Refunds are given within fourteen days of purchase, with the receipt.",
        auto_approve=True,
    )
    await _ingest(tenant_id, uuid.UUID(str(row["source_id"])), may_self_approve=True)

    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(
                text("SELECT is_active, status FROM kb_sources WHERE id = :s"),
                {"s": row["source_id"]},
            )
        ).first()
    assert live is not None and live[0] is True, "the upload never went live"

    answer = await _ask(tenant_id, "how long do customers have to ask for a refund")
    assert "fourteen days" in answer, (
        "an approved, published upload was invisible to the copilot's knowledge tool"
    )
    assert "published facts" in answer, "the passage reached the model with no provenance"


async def test_an_unapproved_upload_is_not_reachable_and_the_client_is_told_why(
    s3: FakeS3,
) -> None:
    """THE OTHER HALF OF THE GATE, and the one that must never fail open. A staff member's
    upload waits for approval, so it is not in the compiled block and the tool cannot quote
    it — and the sentence the model gets says the source EXISTS and is waiting on us, which
    is a different remedy from "add it"."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = await _upload_text(
        tenant_id,
        agent_id,
        name="Draft pricing",
        body="A deep clean costs nine hundred rupees.",
        auto_approve=False,
    )
    await _ingest(tenant_id, uuid.UUID(str(row["source_id"])), may_self_approve=False)

    answer = await _ask(tenant_id, "what does a deep clean cost")
    assert "nine hundred" not in answer, "an UNAPPROVED draft was readable by the copilot"
    assert "waiting for approval" in answer or "NONE of them" in answer


async def test_a_published_pdf_is_live_knowledge_the_copilot_cannot_read(
    s3: FakeS3,
) -> None:
    """A PDF and a scraped link are LIVE knowledge the copilot cannot read.

    Not a bug in the tool and not one to fix by widening it: `kb_uploads.document_key`
    points at the client's own bytes precisely so the reviewer's artefact and the agent's
    are the same object, and the engine scrapes a link itself. Neither leaves `kb_documents`
    a row, so neither tier of the retrieval port has anything to match.

    What WOULD be a defect is the answer the client gets. `_NOTHING_PUBLISHED` tells them to
    add it under Knowledge — about a price list they uploaded this morning.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Tariff card",
            filename="tariff.pdf",
            content_type="application/pdf",
            data=PDF,
            submitted_by=None,
            auto_approve=True,
        )
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(row["source_id"]))
        )
    assert await _document_count(tenant_id, uuid.UUID(str(row["source_id"]))) == 0

    answer = await _ask(tenant_id, "what is on the tariff card")
    assert "Tariff card" in answer, (
        "the tool did not name the published source whose text it cannot read"
    )
    # …and it must not send the client to do work they have already done.
    assert "already live" in answer
