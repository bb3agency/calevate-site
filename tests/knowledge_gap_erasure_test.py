"""The caller's words in the knowledge-gap tables are reachable by erasure and by the clock.

**THE HOLE THESE TESTS PIN.** A DPDP erasure does not DELETE a call — it scrubs it in
place and keeps the row, because the call is billing evidence. So the
`ON DELETE CASCADE` on `knowledge_gap_occurrences.call_id` reads like protection and is
not: nothing is ever deleted, so it never fires. The gap detector copies the caller's
question and the agent's deflection out of `transcript_turns.text_redacted` at detection
time, and `knowledge_gaps` keeps a SECOND copy in its example columns with no `call_id`
on it at all. Neither table appeared in any erasure path, nor in
`retention.DERIVED_COPIES`. After an erasure the gap card on the client's dashboard was
the LAST surviving record of what that caller said.

**REDACTED IS NOT ERASED**, and the column names invite exactly that mistake. Redaction
removes identifiers from a sentence; it does not remove the sentence. That is why these
tests assert on the caller's WORDS and not on a phone number.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import tenant_session
from apps.api.insights import service
from apps.api.insights.detection import RedactedTurn
from apps.api.insights.service_test import _call, _tenant
from apps.workers.retention import REDACTED_MARK
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: The sentence under test. Survives redaction intact — it names no identifier — which is
#: the whole point: this is the caller's own words, and it is what has to disappear.
CALLER_WORDS = "Do you do IVF, my wife and I have been trying for six years?"
AGENT_WORDS = "I don't know about that, I'll have someone WhatsApp you."


def _turns() -> list[RedactedTurn]:
    return [
        RedactedTurn(speaker="caller", text=CALLER_WORDS),
        RedactedTurn(speaker="agent", text=AGENT_WORDS),
    ]


async def _gap_text(tenant_id: uuid.UUID) -> str:
    """Every quote column of both tables, concatenated — one haystack to search."""
    async with tenant_session(tenant_id) as session:
        occ = (
            await session.execute(
                text("SELECT question_redacted, answer_redacted FROM knowledge_gap_occurrences")
            )
        ).all()
        agg = (
            await session.execute(
                text(
                    "SELECT example_question_redacted, example_answer_redacted FROM knowledge_gaps"
                )
            )
        ).all()
    return " ".join(str(cell) for row in [*occ, *agg] for cell in row)


async def _seed_gap(started_at: datetime) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, started_at)
    await service.record_call_gaps(
        tenant_id=tenant_id, agent_id=agent_id, call_id=call_id, turns=_turns()
    )
    return tenant_id, agent_id, call_id


async def test_the_callers_words_are_on_file_before_any_erasure() -> None:
    """The premise. Without this the tests below could pass on an empty table."""
    tenant_id, _, _ = await _seed_gap(datetime.now(UTC))
    assert CALLER_WORDS in await _gap_text(tenant_id), "premise: the detector stored the quote"


async def test_erasure_removes_the_callers_words_from_both_gap_tables() -> None:
    """THE REGRESSION. Both copies go — the per-call occurrence and the aggregate example.

    Asserted on the SENTENCE, not on a row count: the defect was never a missing row, it
    was a surviving sentence, and a count assertion would have passed against the bug.
    """
    tenant_id, _, call_id = await _seed_gap(datetime.now(UTC))

    async with tenant_session(tenant_id) as session:
        scrubbed = await service.scrub_quotes_for_calls(
            session, call_ids=[call_id], mark=REDACTED_MARK
        )
    assert scrubbed == 1

    haystack = await _gap_text(tenant_id)
    assert CALLER_WORDS not in haystack, "the caller's question survived the erasure"
    assert AGENT_WORDS not in haystack, "the agent's answer to them survived the erasure"


async def test_the_counts_survive_because_they_are_not_the_callers_data() -> None:
    """Scrubbed, not deleted — and this is the clause that says why.

    Deleting the occurrence would move the CLIENT's analytics as a side effect of a
    stranger's erasure request: "12 callers asked about parking" silently becoming 11.
    The count is not the caller's data; the sentence is. So the row and its counts stay.
    """
    tenant_id, _, call_id = await _seed_gap(datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        await service.scrub_quotes_for_calls(session, call_ids=[call_id], mark=REDACTED_MARK)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT occurrence_count, call_count FROM knowledge_gaps"))
        ).first()
    assert row is not None, "the aggregate row was deleted — the client lost a real count"
    assert row[0] >= 1 and row[1] == 1


async def test_scrubbing_twice_reports_the_work_once() -> None:
    """Idempotent, for `call_extractions`' reason: a re-run of an erasure must not report
    a second, larger count for work the first one already did. The proof certificate
    carries this number."""
    tenant_id, _, call_id = await _seed_gap(datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        first = await service.scrub_quotes_for_calls(
            session, call_ids=[call_id], mark=REDACTED_MARK
        )
    async with tenant_session(tenant_id) as session:
        second = await service.scrub_quotes_for_calls(
            session, call_ids=[call_id], mark=REDACTED_MARK
        )
    assert (first, second) == (1, 0)


async def test_another_callers_quote_is_left_alone() -> None:
    """The scrub is keyed on the erased subject's calls and must not widen.

    A gap topic two callers hit is one aggregate row. Erasing one of them must remove
    THEIR sentence and leave the other's — otherwise one erasure request quietly empties
    a client's dashboard.
    """
    tenant_id, agent_id, erased_call = await _seed_gap(datetime.now(UTC))
    other_words = "Do you have evening appointments on Saturdays?"
    other_call = await _call(tenant_id, agent_id, datetime.now(UTC) + timedelta(minutes=5))
    await service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=other_call,
        turns=[
            RedactedTurn(speaker="caller", text=other_words),
            RedactedTurn(speaker="agent", text=AGENT_WORDS),
        ],
    )

    async with tenant_session(tenant_id) as session:
        await service.scrub_quotes_for_calls(session, call_ids=[erased_call], mark=REDACTED_MARK)

    haystack = await _gap_text(tenant_id)
    assert CALLER_WORDS not in haystack, "the erased caller's words survived"
    assert other_words in haystack, "an unrelated caller's words were erased too"


async def test_the_aggregate_example_is_re_derived_from_what_survives() -> None:
    """The aggregate has no `call_id`, so it cannot be scrubbed by key — it is RECOMPUTED.

    The case that needs it: TWO calls on the SAME topic, and the erased one is the newer,
    so it is the one supplying the aggregate's example. A scrub that only marked the
    occurrence would leave the erased sentence sitting in the example columns, where the
    dashboard renders it. The recompute must re-pick from what survives.

    Same caller question on both calls, so the detector groups them under one topic —
    that grouping is the whole point of the test, and an earlier version of it asserted
    on two DIFFERENT questions, which silently produced two aggregates and proved
    nothing. The AGENT's answers differ, which is what makes the surviving one nameable.
    """
    tenant_id, agent_id = await _tenant()
    question = "How much does the IVF package cost?"
    older_answer = "I am not sure, let me check with the doctor."
    newer_answer = "I don't have that price, I'll WhatsApp it to you."

    older_call = await _call(tenant_id, agent_id, datetime.now(UTC) - timedelta(hours=2))
    await service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=older_call,
        turns=[
            RedactedTurn(speaker="caller", text=question),
            RedactedTurn(speaker="agent", text=older_answer),
        ],
    )
    newer_call = await _call(tenant_id, agent_id, datetime.now(UTC))
    await service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=newer_call,
        turns=[
            RedactedTurn(speaker="caller", text=question),
            RedactedTurn(speaker="agent", text=newer_answer),
        ],
    )

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT example_answer_redacted FROM knowledge_gaps"))
        ).all()
    assert len(rows) == 1, "premise: one topic, one aggregate"
    assert str(rows[0][0]) == newer_answer, "premise: the newest call supplies the example"

    async with tenant_session(tenant_id) as session:
        await service.scrub_quotes_for_calls(session, call_ids=[newer_call], mark=REDACTED_MARK)

    async with tenant_session(tenant_id) as session:
        example = str(
            (
                await session.execute(text("SELECT example_answer_redacted FROM knowledge_gaps"))
            ).scalar()
        )
    assert newer_answer not in example, "the aggregate kept the erased call's sentence"
    assert example == older_answer, (
        "the aggregate was not re-derived from the surviving occurrence — it should show "
        "the older call's answer, not the marker"
    )
