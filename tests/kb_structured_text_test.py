"""A Markdown guide is read as titled sections of plain sentences, and what it tells the agent
to do on the call is kept apart from the facts it holds (`kb/structured_text.py`).

The fixture `tests/fixtures/voice_agent_guide.md` is shaped like a real client's guide:
headings, bold, a link, a separator, a table, numbered steps, a quote, a bold line standing
in for a heading, and a section that is pure call behaviour.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from apps.api.agents import script_proposals
from apps.api.agents.hot_facts import candidates_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run.documents import INSTRUCTIONS_LEAD, document_words
from apps.api.kb import service as kb_service
from apps.api.kb import uploads
from apps.api.kb.service import MAX_CHUNK_CHARS, LiveChunk, chunk_groups
from apps.api.kb.structured_text import (
    PARSER_VERSION,
    Group,
    is_instruction,
    looks_like_markdown,
    read_markdown,
)
from apps.workers import kb_ingest
from sqlalchemy import text
from tests.conftest import FakeS3, create_org_with_receptionist
from tests.first_run_test import _tenant

GUIDE = (Path(__file__).parent / "fixtures" / "voice_agent_guide.md").read_text(encoding="utf-8")
#: Markup that must never reach a chunk, the engine or the owner's screen.
MARKUP = re.compile(r"\*\*|^#{1,6}\s|^\s*>|^-{3,}$|\]\(|\|", re.MULTILINE)


def _texts(groups: list[Group]) -> list[str]:
    return [g.text for g in groups]


# ------------------------------------------------------------------ parsing


def test_the_guide_reads_as_titled_sections_with_no_markup() -> None:
    reading = read_markdown(GUIDE)
    for chunk in _texts(reading.facts) + _texts(reading.instructions):
        assert not MARKUP.search(chunk), chunk
    assert _texts(reading.facts) == [
        "Key details:\n"
        "App address: www.example-ledger.in\n"
        "Support (WhatsApp): +91 90000 00000\n"
        "Price: The app is free. There is no charge for the first year.",
        "Installing on Android:\n"
        "1. Open the Play Store.\n"
        "2. Search for Example Ledger.\n"
        "3. Tap Install and wait for it to finish.",
        "The Play Store question — this will come up in almost every call:\n"
        "The app is only on the Play Store and the App Store. It is not on any other site.",
        "Opening hours:\n"
        "Our support team answers on WhatsApp from 9 am to 6 pm, Monday to Saturday.",
    ]


def test_a_heading_alone_and_a_separator_are_never_a_chunk() -> None:
    reading = read_markdown(GUIDE)
    chunks = _texts(reading.facts) + _texts(reading.instructions)
    assert not any("Calling registered customers" in c for c in chunks), "the H1 is a title"
    assert all("\n" in c for c in chunks), "every chunk has a body under its title"


def test_numbered_steps_stay_together_in_order() -> None:
    android = next(g for g in read_markdown(GUIDE).facts if g.section == "Installing on Android")
    assert android.lines == (
        "1. Open the Play Store.",
        "2. Search for Example Ledger.",
        "3. Tap Install and wait for it to finish.",
    )


def test_a_table_row_is_one_sentence_from_its_header_cells() -> None:
    speak = next(
        g for g in read_markdown(GUIDE).instructions if g.section == "How the agent should speak"
    )
    assert "Say this: phone. Not this: handset. Why: nobody says handset." in speak.lines
    assert "Say this: app. Not this: application software. Why: too long." in speak.lines


def test_a_link_keeps_its_words_and_its_address_once() -> None:
    reading = read_markdown("# A\n\nSee [our price list](https://example.in/prices) today.\n")
    assert reading.facts[0].lines == ("See our price list (https://example.in/prices) today.",)
    same = read_markdown("# A\n\nVisit [www.example.in](https://www.example.in/).\n")
    assert same.facts[0].lines == ("Visit www.example.in.",)


def test_a_quote_is_kept_as_plain_text() -> None:
    speak = next(
        g for g in read_markdown(GUIDE).instructions if g.section == "How the agent should speak"
    )
    assert '"Hello, I am calling from Example Ledger about your new account."' in speak.lines


# ------------------------------------------------------------------ instructions vs facts


def test_call_behaviour_is_split_from_facts() -> None:
    reading = read_markdown(GUIDE)
    assert _texts(reading.instructions) == [
        "Key details:\nLanguage of the call: English",
        "How the agent should speak:\n"
        "Say who you are, why you are calling, and ask whether now is a good time. "
        "Keep it under twenty seconds.\n"
        'If the customer\'s name is known, use it once at the start — "Hello [name]".\n'
        "Do not explain the whole dashboard on this call.\n"
        "Say this: phone. Not this: handset. Why: nobody says handset.\n"
        "Say this: app. Not this: application software. Why: too long.\n"
        '"Hello, I am calling from Example Ledger about your new account."',
        "If he says he is busy:\nAsk when to call back, note the time, thank him and end the call.",
    ]


def test_steps_told_to_the_caller_are_facts_and_steps_for_the_agent_are_not() -> None:
    assert not is_instruction("Open the Play Store.")
    assert not is_instruction("If you pay by UPI there is no fee.")
    assert not is_instruction("Address: 12 Main Road, Guntur")
    assert not is_instruction("Offer valid till Diwali.")
    assert is_instruction("Ask him to open the Play Store.")
    assert is_instruction("If the farmer is already logged in, skip the sign-in step.")
    assert is_instruction("Never read out the whole list.")


def test_plain_text_is_not_mistaken_for_markdown() -> None:
    assert not looks_like_markdown("Rice 50 kg - Rs 2,400\nWheat 50 kg - Rs 2,100\n")
    assert not looks_like_markdown("Call us on **9876543210** any time.")
    assert looks_like_markdown(GUIDE)


def test_a_long_section_is_cut_under_the_cap_and_every_piece_keeps_its_title() -> None:
    lines = tuple(f"Item {n}: a fairly long description of this product line." for n in range(40))
    pieces = chunk_groups([Group("Price list", lines, "fact")])
    assert len(pieces) > 1
    assert all(len(p.content) <= MAX_CHUNK_CHARS for p in pieces)
    assert all(p.content.startswith("Price list:\n") for p in pieces)
    body = "\n".join(p.content.removeprefix("Price list:\n") for p in pieces)
    assert body == "\n".join(lines), "nothing is lost or reordered"


def test_a_section_is_one_known_fact_whose_lines_read_as_separate_statements() -> None:
    chunk = chunk_groups(read_markdown(GUIDE).facts)[0]
    live = LiveChunk(source="g", content=chunk.content, gloss=None, written_at=datetime.now(UTC))
    found = candidates_of([], [live])
    assert [c.text for c in found] == [
        "Key details: App address: www.example-ledger.in. Support (WhatsApp): +91 90000 00000. "
        "Price: The app is free. There is no charge for the first year."
    ]


# ------------------------------------------------------------------ storage and re-reading


async def _md_upload(tenant_id: uuid.UUID, data: bytes) -> tuple[uuid.UUID, uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        made = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=None,
            filename="guide.md",
            content_type="text/markdown",
            data=data,
            submitted_by=None,
            auto_approve=True,
        )
    return uuid.UUID(str(made["id"])), uuid.UUID(str(made["source_id"]))


async def test_stored_chunks_are_clean_and_instructions_wait_on_the_upload(s3: FakeS3) -> None:
    tenant_id = await _tenant()
    upload_id, source_id = await _md_upload(tenant_id, GUIDE.encode())
    async with tenant_session(tenant_id) as session:
        stored = await kb_service.store_document_text(
            session, tenant_id=tenant_id, source_id=source_id, body=GUIDE, structured=True
        )
        rows = (
            await session.execute(
                text("SELECT content, meta FROM kb_documents WHERE source_id = :s ORDER BY idx"),
                {"s": source_id},
            )
        ).all()
        held = (await uploads.get_upload(session, upload_id))["call_instructions"]
        words = await document_words(session, upload_id)
    assert stored.chunks == 4 and stored.instructions == 3
    assert [r[1]["section"] for r in rows] == [
        "Key details",
        "Installing on Android",
        "The Play Store question — this will come up in almost every call",
        "Opening hours",
    ]
    assert not any(MARKUP.search(str(r[0])) for r in rows)
    assert not any("Say who you are" in str(r[0]) for r in rows), "behaviour is not knowledge"
    assert [h["section"] for h in held] == [
        "Key details",
        "How the agent should speak",
        "If he says he is busy",
    ]
    # The script writer reads the facts AND the call behaviour.
    assert INSTRUCTIONS_LEAD in words and "ask whether now is a good time" in words


async def test_a_file_of_only_instructions_stores_no_knowledge(s3: FakeS3) -> None:
    tenant_id = await _tenant()
    body = "# How the agent should speak\n\nSay who you are.\n\nAsk if now is a good time.\n"
    _, source_id = await _md_upload(tenant_id, body.encode())
    async with tenant_session(tenant_id) as session:
        stored = await kb_service.store_document_text(
            session, tenant_id=tenant_id, source_id=source_id, body=body, structured=True
        )
    assert (stored.chunks, stored.instructions) == (0, 1)


async def test_a_live_guide_read_the_old_way_is_read_again_as_a_new_version(s3: FakeS3) -> None:
    tenant_id = await _tenant()
    upload_id, source_id = await _md_upload(tenant_id, GUIDE.encode())
    async with tenant_session(tenant_id) as session:
        # How the file was held before: raw Markdown, approved and live.
        await kb_service.store_extracted_text(
            session, tenant_id=tenant_id, source_id=source_id, body=GUIDE
        )
        await session.execute(
            text(
                "UPDATE kb_sources SET status = 'approved', approved_at = now(), "
                "is_active = true WHERE id = :s"
            ),
            {"s": source_id},
        )
        stale = (
            (
                await session.execute(
                    text(kb_ingest._STALE_PARSE_SQL), {"version": PARSER_VERSION, "limit": 10}
                )
            )
            .scalars()
            .all()
        )
    assert upload_id in [uuid.UUID(str(u)) for u in stale]

    assert await kb_ingest.reparse_kb_upload(tenant_id=tenant_id, upload_id=upload_id) == (
        "new_version"
    )
    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text(
                    "SELECT s.version, u.id, u.original_key, u.text_parser FROM kb_sources s "
                    "JOIN kb_uploads u ON u.source_id = s.id WHERE s.name = 'guide.md' "
                    "ORDER BY s.version"
                )
            )
        ).all()
        stale = (
            (
                await session.execute(
                    text(kb_ingest._STALE_PARSE_SQL), {"version": PARSER_VERSION, "limit": 10}
                )
            )
            .scalars()
            .all()
        )
    async with untenanted_session() as session:
        queued = (
            (
                await session.execute(
                    text(
                        "SELECT payload->>'source_id' FROM outbox_messages "
                        "WHERE job = 'ingest_kb_source' AND payload->>'tenant_id' = :t"
                    ),
                    {"t": str(tenant_id)},
                )
            )
            .scalars()
            .all()
        )
    assert [v[0] for v in versions] == [1, 2]
    assert versions[0][3] == PARSER_VERSION, "the old upload is stamped so it is offered once"
    assert s3.objects[str(versions[1][2])] == GUIDE.encode(), "the new version has its own copy"
    assert len(set(queued) - {str(source_id)}) == 1, "the new version is queued to be read"
    assert stale == []
    # Offered again (a retried job): already read by this version, so nothing more happens.
    assert await kb_ingest.reparse_kb_upload(tenant_id=tenant_id, upload_id=upload_id) == (
        "current"
    )


async def test_a_plain_text_upload_is_stamped_and_left_alone(s3: FakeS3) -> None:
    tenant_id = await _tenant()
    body = "Rice 50 kg - Rs 2,400\nWheat 50 kg - Rs 2,100\n"
    async with tenant_session(tenant_id) as session:
        made = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=None,
            filename="prices.txt",
            content_type="text/plain",
            data=body.encode(),
            submitted_by=None,
            auto_approve=True,
        )
    assert (
        await kb_ingest.reparse_kb_upload(tenant_id=tenant_id, upload_id=uuid.UUID(str(made["id"])))
        == "unchanged"
    )


async def test_using_the_instructions_queues_a_script_suggestion_from_the_file(
    s3: FakeS3,
) -> None:
    created = await create_org_with_receptionist(
        name="Ledger Shop",
        slug=f"guide-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    upload_id, source_id = await _md_upload(tenant_id, GUIDE.encode())
    async with tenant_session(tenant_id) as session:
        await kb_service.store_document_text(
            session, tenant_id=tenant_id, source_id=source_id, body=GUIDE, structured=True
        )
        asked = await uploads.use_call_instructions(
            session, tenant_id=tenant_id, upload_id=upload_id, name="guide.md", agent_id=agent_id
        )
        proposal = await script_proposals.read_proposal(session, agent_id)
    assert (asked.agents, asked.skipped) == (1, 0)
    assert proposal is not None and proposal.mode == script_proposals.KNOWLEDGE_MODE
    assert proposal.documents == [upload_id], "written from this file, for the owner to review"
    assert proposal.status == "drafting", "a suggestion only: nothing is applied to the agent"
