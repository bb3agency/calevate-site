"""The post-call pipeline over calls that have NOTHING in them, and over stale webhooks.

Three questions this file measures rather than assumes.

**1. What does a silent call cost?** Voicemail, an immediate hangup, a ring the vendor
still reports `completed`, a caller who never speaks — on an outbound campaign these are
not the rare case, they are most of the dials. `_post_call_stages` runs the full pipeline
for every one of them because a `completed` execution is `billable_ready`, and the
extraction stage used to hand an EMPTY STRING to a provider that charges per token
(`billing/rates.SARVAM_LLM_INR_PER_MTOK`) to ask what was said in a silence. Measured
before the fix: one provider round trip per silent call, forever. The row still has to
land — `EXTRACTION_OWED_SQL` says an agent with schema fields is owed one, and a call that
wrote none is a call `report_stalled_pipeline` alarms on and the poller re-drives — so the
fix is a deterministic verdict, not a skipped stage.

**2. Is "no words" the same as "no turns"?** No. An STT that hears only noise returns
turns with empty `text`, and `_persist_transcript` joined those into `"agent: \\ncaller: "`
— a page of speaker labels, non-empty, and therefore a paid round trip that the
no-transcript guard alone does not catch.

**3. Can a stale webhook reopen a finished call?** `_upsert_call_row`'s conflict clause is
the only thing standing between a late `ringing` delivery and a completed call going back
to in-flight. It spelled the terminal set as a SQL literal while `TERMINAL_STATUSES` sat
imported at the top of the same module, so the guard and the constant were free to drift.
The parametrisation below is the measurement: it passes today and fails the day a sixth
terminal status is added to `calevate_shared.events` without this statement learning it.

Scope discipline: every test builds its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers import extraction as extraction_module
from apps.workers import pipeline, storage
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TERMINAL_STATUSES, TranscriptTurn
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

RUN = uuid.uuid4().hex[:12]


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bucket is an environment concern; the same substitution the smoke test makes."""

    async def _fake_copy(
        *, source_url: str, tenant_id: UUID, call_id: UUID, leg: str = "call"
    ) -> str:
        # `leg` NAMES WHICH OF A CALL'S TWO RECORDINGS (D-533): a call handed to a
        # person has a second one, and the two must not land on one key. Defaulted so
        # this stub reads the way the pipeline calls it for an ordinary call.
        return (
            storage.recording_key(tenant_id, call_id)
            if leg == "call"
            else storage.transfer_recording_key(tenant_id, call_id)
        )

    monkeypatch.setattr(pipeline, "copy_recording", _fake_copy)


class _CountingExtractor:
    """A provider that records every round trip asked of it and answers nothing.

    Counting `extract_call` would measure the wrong thing — the guard is inside it, and
    what costs money is the call to `runner.run`.
    """

    model_name = "counting-spy"

    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def run(self, spec: Any, transcript: str) -> dict[str, Any]:
        self.inputs.append(transcript)
        return {}


async def _staged(label: str) -> tuple[UUID, str, UUID]:
    """A fresh tenant with one ingested inbound call. The pipeline has NOT run."""
    reset_engine_cache()
    agent_ref = f"silent_{label}_{RUN}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_silent_{label}_{RUN}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )

    async def _swallow(job: str, *args: Any, **kwargs: Any) -> str:
        return "queued"

    real = pipeline.enqueue
    pipeline.enqueue = _swallow  # type: ignore[assignment]
    try:
        await pipeline.ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
        )
    finally:
        pipeline.enqueue = real  # type: ignore[assignment]

    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    return tenant_id, execution_id, UUID(str(call_id))


def _pin_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot: ExecutionSnapshot) -> None:
    class _Pinned:
        name = "fake"

        async def get_execution(self, execution: str) -> ExecutionSnapshot:
            return snapshot

    monkeypatch.setattr(pipeline, "get_engine", lambda: _Pinned())


async def _run(tenant_id: UUID, call_id: UUID, execution_id: str) -> str:
    return await pipeline.run_post_call_pipeline(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )


async def _extraction_row(tenant_id: UUID, call_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT ce.data, ce.valid, ce.errors, c.summary, c.outcome_tag "
                    "FROM call_extractions ce JOIN calls c ON c.id = ce.call_id "
                    "WHERE ce.call_id = :c"
                ),
                {"c": call_id},
            )
        ).first()


# --- 1. a call with nothing said on it ----------------------------------------


async def test_a_call_with_no_transcript_buys_no_provider_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Voicemail, immediate hangup, ring-no-answer the vendor calls `completed`.

    The extraction row still lands, because `EXTRACTION_OWED_SQL` says this agent is owed
    one and a call without it is re-driven forever. What must not happen is paying a
    provider to read a silence.
    """
    tenant_id, execution_id, call_id = await _staged("none")
    real = await get_engine().get_execution(execution_id)
    _pin_snapshot(monkeypatch, real.model_copy(update={"transcript": [], "recording_url": None}))
    spy = _CountingExtractor()
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: spy)

    assert await _run(tenant_id, call_id, execution_id) == "ok"

    assert spy.inputs == [], "a model was asked what was said in a call with no transcript"
    row = await _extraction_row(tenant_id, call_id)
    assert row is not None, "the extraction row is owed even when there is nothing to extract"
    assert row[0] == {}, "nothing was said, so nothing may be captured"
    # THE SCHEMA'S OWN VERDICT ON AN EMPTY OBJECT, which is what a perfectly behaved
    # model handed a silence would have produced. `CLINIC_SCHEMA` marks nothing required,
    # so "nothing captured" is valid; a schema with a required field would land the same
    # row with that field's error on it, and either way no provider was paid for it.
    assert row[1] is True
    assert "_model" not in (row[2] or {}), (
        "not a provider failure: a re-drive would ask the same unanswerable question, and "
        "`_settled_extraction` refuses to reuse a row carrying `_model`"
    )
    assert row[3] is None, "no words means no summary, not an invented one"
    assert row[4] == "dropped", "a call in which nobody spoke resolved nothing"


async def test_a_transcript_of_blank_turns_is_a_silence_not_a_page_of_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An STT that heard only noise returns turns whose `text` is empty.

    The rows are still written — the engine reported them and their `start_ms` is real —
    but they are not lines of the extractor's input, because `"agent: "` with nothing
    after it is not evidence of anything.
    """
    tenant_id, execution_id, call_id = await _staged("blank")
    real = await get_engine().get_execution(execution_id)
    blank = [
        TranscriptTurn(call_id=execution_id, idx=0, speaker="agent", text="", start_ms=0),
        TranscriptTurn(call_id=execution_id, idx=1, speaker="caller", text="   ", start_ms=900),
    ]
    _pin_snapshot(monkeypatch, real.model_copy(update={"transcript": blank}))
    spy = _CountingExtractor()
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: spy)

    assert await _run(tenant_id, call_id, execution_id) == "ok"

    assert spy.inputs == [], f"a model was paid to read speaker labels: {spy.inputs!r}"
    async with tenant_session(tenant_id) as session:
        turns = (
            await session.execute(
                text("SELECT count(*) FROM transcript_turns WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
    assert turns == 2, "the turns the engine reported are still ours to store"
    row = await _extraction_row(tenant_id, call_id)
    assert row is not None and row[0] == {}


async def test_a_re_drive_of_a_silent_call_stays_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reuse guard has to hold for the deterministic verdict too.

    `_settled_extraction` refuses to reuse a row whose `errors` carry `_model`. A silent
    call's row must therefore NOT be filed as a provider failure, or every poller
    re-drive would re-enter the stage — which, once a provider is configured, is a paid
    round trip per re-drive per silent call.
    """
    tenant_id, execution_id, call_id = await _staged("redrive")
    real = await get_engine().get_execution(execution_id)
    _pin_snapshot(monkeypatch, real.model_copy(update={"transcript": []}))
    spy = _CountingExtractor()
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: spy)

    assert await _run(tenant_id, call_id, execution_id) == "ok"
    assert await _run(tenant_id, call_id, execution_id) == "ok"

    assert spy.inputs == []
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM call_extractions WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
    assert count == 1, "one call has one extraction however many times the pipeline runs"


# --- 2. a stale webhook against a finished call --------------------------------


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATUSES))
async def test_a_late_non_terminal_webhook_cannot_reopen_a_finished_call(
    terminal: str,
) -> None:
    """Every member of `TERMINAL_STATUSES`, not the five somebody typed into the SQL.

    This is the whole point of the parametrisation: the conflict clause and the constant
    are one fact, and a sixth terminal status that reaches `calevate_shared.events`
    without reaching this statement would let a stale `ringing` delivery put a finished
    call back in flight — silently, on the one statement that owns the call row's status.
    """
    reset_engine_cache()
    agent_ref = f"reopen_{terminal}_{RUN}"
    tenant_id, agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_reopen_{terminal}_{RUN}"

    def _snapshot(status: str) -> ExecutionSnapshot:
        return ExecutionSnapshot(
            engine_call_id=execution_id,
            engine_agent_ref=agent_ref,
            direction="inbound",
            status=status,  # type: ignore[arg-type]
            raw_status=status,
            terminal=status in TERMINAL_STATUSES,
            billable_ready=status == "completed",
            started_at=None,
            ended_at=None,
            duration_s=None,
            from_e164="+919812345678",
            to_e164="+911140000000",
            recording_url=None,
            transcript=[],
            cost=None,
            engine="fake",
        )

    call_id = await pipeline._upsert_call(tenant_id, agent_id, _snapshot(terminal), agent_ref)
    # The stale delivery: an earlier transition of the same call, arriving after the end.
    again = await pipeline._upsert_call(tenant_id, agent_id, _snapshot("ringing"), agent_ref)

    assert again == call_id, "one execution is one call row"
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar()
    assert status == terminal, (
        f"a late `ringing` webhook reopened a call already recorded `{terminal}` — the "
        "conflict clause and TERMINAL_STATUSES have drifted"
    )
