"""A knowledge gap may be acted on ONCE — and the second act must not leave a draft.

**THE DEFECT.** `dismiss_gap` and `teach_gap` both wrote `UPDATE knowledge_gaps SET
status = ... WHERE id = :id` with no guard on the status they were moving away from, which
BACKEND-PATTERNS §5 forbids for exactly this class of write ("status transitions … get a
central transition table + `INVALID_STATUS_TRANSITION` error"). Losing a flag would have
been the cheap version. What actually happened is worse, and it is what the second test
here pins: `teach_gap` seeds a `pending_approval` KB source through `kb.submit_source`
BEFORE it writes, so a second teach of one gap — a double submit, a client retry, two
colleagues on the same card — put a SECOND draft into the client's review queue while
only the last `kb_source_id` was kept. The first draft was then orphaned: in the queue,
referenced by no gap, and indistinguishable to the reviewer from a source somebody meant
to add.

**WHY `open`-ONLY IS NOT A NARROWING.** The console lists `status: "open"` and nothing
else (`apps/web/src/app/c/[slug]/KnowledgeGaps.tsx`), and both mutations drop the card
from the list the moment they fire, so the only way to reach a closed gap is a repeat of
an act that already succeeded. That is the case this refuses, and the mutation hooks
already restore their snapshot and surface the failure on any error.

The refusal is a 409 `invalid_status_transition` carrying the status that WON, which is
the half a caller can act on: "a knowledge gap cannot go from taught to dismissed" tells
them what happened to the card that vanished; the pre-write status would have said
`open`, which was true when they tried and is a lie by the time they read it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.insights import service
from apps.api.insights.schemas import GapTeachIn
from apps.api.insights.service_test import (
    _call,
    _client_principal,
    _pricing_turns,
    _tenant,
)

pytestmark = pytest.mark.anyio


async def _open_gap() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A tenant, its agent, and one OPEN pricing gap on a real call."""
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_pricing_turns()
    )
    async with tenant_session(tenant_id) as session:
        gap = (await service.list_gaps(session)).items[0]
    return tenant_id, agent_id, gap.id


async def test_a_second_teach_is_refused_and_seeds_no_second_draft() -> None:
    """THE REGRESSION, asserted on the DRAFT COUNT rather than on the status.

    A status assertion would have passed against the bug — the row ended up `taught`
    either way. The orphan in the review queue is the damage, so that is what is counted.
    """
    tenant_id, agent_id, gap_id = await _open_gap()
    principal = _client_principal(tenant_id)

    async with tenant_session(tenant_id) as session:
        taught = await service.teach_gap(
            session,
            gap_id,
            principal=principal,
            payload=GapTeachIn(answer="Consultation is 500 rupees.", create_kb_draft=True),
        )
        assert taught.status == "taught"

    # A separate session, i.e. a separate transaction — the second request. THE REFUSAL
    # IS RAISED **THROUGH** THE SESSION SCOPE, which is what production does and is the
    # half that removes the duplicate: `core/deps.db` yields inside `tenant_session`, so
    # an error that escapes the handler rolls the whole transaction back, draft included.
    # Catching it inside the `async with` would leave the context manager to exit cleanly
    # and COMMIT the orphan — measured, on the first run of this test.
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await service.teach_gap(
                session,
                gap_id,
                principal=principal,
                payload=GapTeachIn(answer="Actually it is 600.", create_kb_draft=True),
            )
    assert raised.value.code == "invalid_status_transition"
    assert raised.value.status == 409
    # The status that WON is the one reported, not the one read before the write.
    assert "taught" in raised.value.detail

    async with tenant_session(tenant_id) as session:
        drafts = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM kb_sources WHERE agent_id = :a "
                        "AND status = 'pending_approval'"
                    ),
                    {"a": agent_id},
                )
            ).scalar_one()
        )
        answer = (
            await session.execute(
                text("SELECT resolution FROM knowledge_gaps WHERE id = :id"), {"id": gap_id}
            )
        ).scalar_one()
    assert drafts == 1, "the refused teach rolled its own draft back — no orphan in the queue"
    assert answer == "Consultation is 500 rupees.", "the winner's answer stands"


async def test_a_dismiss_after_a_teach_is_refused() -> None:
    """The cross transition, which is the one that could leave the row inconsistent: a
    gap resting `dismissed` while `kb_source_id` still pointed at a live draft."""
    tenant_id, _agent_id, gap_id = await _open_gap()
    principal = _client_principal(tenant_id)

    async with tenant_session(tenant_id) as session:
        await service.teach_gap(
            session,
            gap_id,
            principal=principal,
            payload=GapTeachIn(answer="500 rupees.", create_kb_draft=True),
        )
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await service.dismiss_gap(
                session,
                gap_id,
                principal=principal,
                reason="never mind",
            )
    assert raised.value.code == "invalid_status_transition"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, kb_source_id FROM knowledge_gaps WHERE id = :id"),
                {"id": gap_id},
            )
        ).one()
    assert row.status == "taught"
    assert row.kb_source_id is not None, "the draft and the status still agree"


async def test_a_second_dismiss_is_refused() -> None:
    tenant_id, _agent_id, gap_id = await _open_gap()
    principal = _client_principal(tenant_id)

    async with tenant_session(tenant_id) as session:
        await service.dismiss_gap(
            session,
            gap_id,
            principal=principal,
            reason="we do not quote prices on the phone",
        )
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await service.dismiss_gap(
                session,
                gap_id,
                principal=principal,
                reason="again",
            )
    assert raised.value.code == "invalid_status_transition"
    assert "dismissed" in raised.value.detail

    async with tenant_session(tenant_id) as session:
        reason = (
            await session.execute(
                text("SELECT resolution FROM knowledge_gaps WHERE id = :id"), {"id": gap_id}
            )
        ).scalar_one()
    assert reason == "we do not quote prices on the phone", "the first note is not overwritten"
