"""Invisible characters in submitted knowledge, refused at the one door.

**WHY THIS IS AN APPROVAL-GATE TEST AND NOT A VALIDATION TEST.** The gate FLOWS §7 rests on
is a person reading a preview and deciding that these words may be said to the public on
the client's behalf. A character that makes the preview and the published text say
different things does not weaken that gate, it removes it — the reviewer approves one
sentence and the agent speaks another, and every downstream consumer (the [T0 FACTS] block,
the engine document, the copilot's quotation of it) reads the logical order the reviewer
never saw. The named attack is Trojan Source (Boucher & Anderson 2021, CVE-2021-42574).

Reproduced before it was closed: a body containing `U+202E` was accepted, chunked, and
returned by `preview` with the override intact. `kb/pdf_render.py` happened to refuse it at
publish — the Telugu font's cmap has no glyph for it — which is a real backstop with the
wrong diagnosis ("the font cannot render this") and holds only for engines that ingest a
document. And a `\\x00`, which is invisible in the same way, was not refused anywhere: it
reached the INSERT and died there as `psycopg.DataError`, i.e. a 500 with a crash alert for
a submission we should simply have refused by name.
"""

from __future__ import annotations

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

#: One per refused GROUP, named rather than swept up in a loop over the constant — a test
#: that iterates the very set it is testing passes whatever that set becomes.
_BODIES = {
    # The Trojan Source override: a reviewer reads "Refunds are never given", the agent is
    # told the opposite ordering.
    "bidi_override": "Refunds are ‮never‬ given within thirty days of purchase.",
    "bidi_isolate": "We are ⁦open⁩ on Sunday mornings for walk-in patients.",
    "nul": "A consultation costs 500 rupees.\x00 Card payment is accepted.",
    "vertical_tab": "We are open\x0b every weekday from nine in the morning.",
    "zero_width_space": "A consul​tation costs 500 rupees at this clinic.",
    "byte_order_mark": "﻿Valet parking is free for patients of the clinic.",
}


@pytest.mark.parametrize("kind", sorted(_BODIES))
async def test_an_invisible_character_is_refused_by_name(kind: str) -> None:
    """422 with the codepoint named, and NOTHING written — not a source, not a chunk."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refusal:
            await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Refunds",
                body=_BODIES[kind],
            )
        assert refusal.value.code == "kb_invisible_characters"
        assert refusal.value.status == 422
        # The codepoints are named — the only actionable half — and the client's own prose
        # is not echoed back into a log or an error body (hard rule 6).
        assert "U+" in (refusal.value.detail or "")
        rows = (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert rows == 0, "a refused submission still wrote a version somebody has to review"


async def test_a_source_name_is_checked_too() -> None:
    """The name is not decoration: it is the label a citation carries and the prefix the
    compiled T0 line is built from, so an override there reorders a line the same way."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refusal:
            await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Fees ‮2026",
                body="A consultation costs 500 rupees at this clinic.",
            )
    assert refusal.value.code == "kb_invisible_characters"


async def test_telugu_conjunct_joiners_are_still_accepted() -> None:
    """**THE GUARD MUST NOT REFUSE CORRECTLY SPELLED TELUGU.**

    `U+200C ZERO WIDTH NON-JOINER` and `U+200D ZERO WIDTH JOINER` are orthography in every
    Indic script — they decide whether a conjunct forms — and this product is Telugu-first.
    A refusal list that swept up "all zero-width characters" would reject the language it
    exists to serve, which is why they are excluded by name and pinned here.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    body = "సన్‌రైజ్ క్లినిక్ ఆదివారం ఉదయం 9 గంటల నుండి తెరిచి ఉంటుంది."
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Hours", body=body
        )
        chunks = await kb_service.preview(session, submitted["id"])
    assert "‌" in chunks[0]["content"]
