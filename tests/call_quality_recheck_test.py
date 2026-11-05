"""Stored findings from checks since narrowed are read again (D-970): the owner's list loses
"I will try." as a question to answer and the number read again on request as a mistake,
and keeps what is still true."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.insights.detection import RedactedTurn
from apps.api.insights.service import record_call_gaps
from apps.workers.call_quality_recheck import recheck_call_quality
from arq import Retry
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tests.call_mistakes_test import RYTU_KHATA_NUMBER, SRI_ESTATES
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Recheck Khata",
        slug=f"rck-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, turns: list[tuple[str, str]]
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        for idx, (speaker, words) in enumerate(turns):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "created_at, updated_at) VALUES (:id, :t, :c, :i, :s, :x, now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "c": call_id, "i": idx, "s": speaker, "x": words},
            )
    return call_id


async def _store_old_gap(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, call_id: uuid.UUID, question: str, answer: str
) -> None:
    """A gap as the detector before D-970 stored it."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO knowledge_gap_occurrences (id, tenant_id, agent_id, call_id, "
                "topic_key, topic_label, question_redacted, answer_redacted, signal, "
                "hit_count, created_at, updated_at) VALUES (:id, :t, :a, :c, 'general', "
                "'General question', :q, :x, 'deferred_channel', 1, now(), now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "c": call_id,
                "q": question,
                "x": answer,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_gaps (id, tenant_id, agent_id, topic_key, topic_label, "
                "status, occurrence_count, call_count, example_question_redacted, "
                "example_answer_redacted, top_signal, first_seen_at, last_seen_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, 'general', 'General question', 'open', 1, 1, "
                ":q, :x, 'deferred_channel', now(), now(), now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "q": question, "x": answer},
        )


async def _mistake(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, call_id: uuid.UUID, kind: str
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, turn_idx, "
                "call_started_at) VALUES (:id, :t, :a, :c, :k, 1, :s)"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "c": call_id,
                "k": kind,
                "s": datetime.now(UTC),
            },
        )


async def test_false_findings_go_and_true_ones_stay() -> None:
    tenant_id, agent_id = await _tenant()
    number_call = await _call(tenant_id, agent_id, [(t.speaker, t.text) for t in RYTU_KHATA_NUMBER])
    looped_call = await _call(tenant_id, agent_id, [(t.speaker, t.text) for t in SRI_ESTATES])
    await _store_old_gap(
        tenant_id, agent_id, number_call, "I will try.", "Message us on WhatsApp if you need help."
    )
    priced = await _call(
        tenant_id,
        agent_id,
        [("caller", "How much is the yearly plan?"), ("agent", "I'll send the price on WhatsApp.")],
    )
    await record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=priced,
        turns=[
            RedactedTurn("caller", "How much is the yearly plan?"),
            RedactedTurn("agent", "I'll send the price on WhatsApp."),
        ],
    )
    await _mistake(tenant_id, agent_id, number_call, "said_again")
    await _mistake(tenant_id, agent_id, looped_call, "said_again")

    assert await recheck_call_quality({}, {"tenant_id": str(tenant_id)}) == "done"
    # A redelivery finds nothing left to remove.
    assert await recheck_call_quality({}, {"tenant_id": str(tenant_id)}) == "done"

    async with tenant_session(tenant_id) as session:
        gaps = (await session.execute(text("SELECT topic_key FROM knowledge_gaps"))).scalars().all()
        mistakes = (
            (
                await session.execute(
                    text("SELECT call_id FROM call_mistakes WHERE kind = 'said_again'")
                )
            )
            .scalars()
            .all()
        )
    assert gaps == ["pricing"]
    assert mistakes == [looped_call]


async def test_a_database_blip_asks_for_another_try_and_the_last_try_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L5-10: arq retries only `Retry`, so a lock timeout used to end the job on its first
    try. The last try raises, and the outbox's unconsumed sweep puts the message back."""
    from apps.workers import call_quality_recheck

    async def _blip(_session: object) -> int:
        raise OperationalError("SELECT ...", {}, Exception("lock timeout"))

    monkeypatch.setattr(call_quality_recheck, "recheck_open_gaps", _blip)
    payload = {"tenant_id": str(uuid.uuid4())}
    with pytest.raises(Retry):
        await recheck_call_quality({"job_try": 1}, payload)
    with pytest.raises(OperationalError):
        await recheck_call_quality({"job_try": WORKER_MAX_TRIES}, payload)


async def test_the_recheck_reads_mistakes_in_the_agents_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L5-19: the pipeline passes the agent's language and the recheck passed none, so a
    language-dependent kind added to `RECHECKED_KINDS` would be judged differently."""
    from apps.api.agents import call_mistakes

    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, [(t.speaker, t.text) for t in RYTU_KHATA_NUMBER])
    await _mistake(tenant_id, agent_id, call_id, "said_again")
    seen: list[str] = []
    real = call_mistakes.mistakes_in

    def _spy(*args: object, language: str, **kwargs: object) -> object:
        seen.append(language)
        return real(*args, language=language, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(call_mistakes, "mistakes_in", _spy)
    await call_mistakes.recheck_call_mistakes(tenant_id)
    assert seen == ["te-IN"]
