"""The post-call pipeline detects knowledge gaps, over REDACTED turns, exactly once.

This is the worker-path test: it drives `run_post_call_pipeline` with a fake engine whose
transcript contains a deflection, and asserts (a) a gap lands, (b) the stored quote is
redacted — a phone number the caller spoke is masked, proving the stage reads
`text_redacted` and not the raw turn — and (c) a re-drive does not double-count.

WHY IT LIVES HERE AND NOT BESIDE THE WORKER IT DRIVES. It was written as
`apps/workers/knowledge_gaps_test.py`, and that placement broke the engine-isolation
contract (hard rule 2): a module inside `apps.workers` may not import a vendor ADAPTER
module, and `apps.api.engine.fake` is one. The contract is not about the word "engine" —
workers legitimately need one — it is about the adapter being the only way a vendor
payload shape can leak upward, so the rule holds even for the fake and even in a test.
Two sibling tests (`redaction_test.py`, `transport_test.py`) stay co-located precisely
because they never import an adapter. Driving a pipeline end to end does, which is why
this belongs with the 67 other tests under `tests/` that do the same — `tests` is not one
of import-linter's `root_packages`, so the boundary it guards is not one this file
crosses. Moving it was the fix; an exemption would have been a hole in hard rule 2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.pipeline import run_post_call_pipeline
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from sqlalchemy import text

# A caller who reads out a number while asking a pricing question, and an agent that
# deflects. The number MUST NOT survive into the stored quote.
_TURNS = (
    ("caller", "My number is +919876543210 — how much is the consultation fee?"),
    ("agent", "I don't know the price, I'll WhatsApp you the details."),
)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Worker Gaps",
        slug=f"wgap-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


def _snapshot(execution_id: str) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref="unused-direct-run",
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=60),
        ended_at=now,
        duration_s=60,
        from_e164="+919876543210",
        to_e164="+911140000000",
        recording_url=None,
        transcript=[
            TranscriptTurn(call_id=execution_id, idx=i, speaker=speaker, text=t)  # type: ignore[arg-type]
            for i, (speaker, t) in enumerate(_TURNS)
        ],
        cost=None,
        engine="fake",
    )


async def _seed_call(tenant_id: uuid.UUID, agent_id: uuid.UUID, execution_id: str) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :ecid, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "ecid": execution_id},
        )
    return call_id


async def test_the_pipeline_records_a_redacted_knowledge_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    call_id = await _seed_call(tenant_id, agent_id, execution_id)

    snapshot = _snapshot(execution_id)

    async def _get(self: FakeEngine, cid: str) -> ExecutionSnapshot:
        return snapshot

    monkeypatch.setattr(FakeEngine, "get_execution", _get)

    payload = {
        "tenant_id": str(tenant_id),
        "call_id": str(call_id),
        "engine": "fake",
        "execution_id": execution_id,
    }
    await run_post_call_pipeline({}, payload)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT topic_key, top_signal, occurrence_count, call_count, "
                    "  example_question_redacted, example_answer_redacted "
                    "FROM knowledge_gaps"
                )
            )
        ).one()
    assert row.topic_key == "pricing"
    assert row.top_signal == "dont_know"
    assert row.occurrence_count == 1
    assert row.call_count == 1
    # The redaction guarantee, end to end: the number the caller spoke is gone.
    assert "9876543210" not in row.example_question_redacted
    assert "WhatsApp" in row.example_answer_redacted

    # A re-drive (the pipeline is re-entrant) must not double-count.
    await run_post_call_pipeline({}, payload)
    async with tenant_session(tenant_id) as session:
        occ = (
            await session.execute(
                text("SELECT count(*) FROM knowledge_gap_occurrences WHERE call_id = :c"),
                {"c": call_id},
            )
        ).scalar()
        agg = (await session.execute(text("SELECT occurrence_count FROM knowledge_gaps"))).scalar()
    assert occ == 1
    assert agg == 1
