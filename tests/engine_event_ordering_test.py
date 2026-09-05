"""The vendor's events, out of order and at once.

`tests/ingest_ordering_test.py` is about the order of OUR OWN steps — the fast-path key
before the commit, the inbox row closed before the job was queued. This file is about the
order the ENGINE delivers in, which is a different thing and not under our control:

- Bolna fires one webhook per status change with no ordering guarantee and no retry
  (D-31, TRD §5), so `completed` can arrive before `in-progress`;
- the reconciliation poller enqueues its own ingest for the same execution under a
  DIFFERENT job id (`...:reconcile`), so a poller re-drive and a webhook-driven ingest
  can genuinely run at the same time on two workers.

Both are real vendor/deployment behaviours rather than hypotheticals, and both land on
code whose correctness is stated in terms of "the fetch is the truth": every ingest
re-reads the execution rather than believing the payload that woke it. This file asserts
that the claim survives contact with the disorder, and — the part that matters — that a
late or duplicated transition can never move MONEY, because `usage_events` is
append-only and a second charge is not removable by an UPDATE (hard rule 4).

Concurrency here is real concurrency: `asyncio.gather` on two coroutines that each open
their own transaction, and an `asyncio.Barrier` where two deliveries have to be released
on the same tick. The negative control for that class of test — remove the guard, watch
the same harness go red — lives in `tests/postcall_concurrency_test.py`, which is where
this repo's races cost money.

Hard rule 6: the only per-call values are synthetic execution ids and status strings.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from uuid import UUID

import pytest
import webhook_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers import pipeline
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

RUN = uuid.uuid4().hex[:12]
HOOK = "/hooks/v1/engine/fake"


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_copy(
        *, source_url: str, tenant_id: UUID, call_id: UUID, leg: str = "call"
    ) -> str:
        # `leg` NAMES WHICH OF A CALL'S TWO RECORDINGS (D-533): a call handed to a
        # person has a second one, and the two must not land on one key. Defaulted so
        # this stub reads the way the pipeline calls it for an ordinary call.
        suffix = "" if leg == "call" else "-transfer"
        return f"recordings/{tenant_id}/{call_id}{suffix}.wav"

    monkeypatch.setattr(pipeline, "copy_recording", _fake_copy)


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Every job the receiver and the ingest job asked for, in order.

    Patched on BOTH modules because the two halves enqueue from different places, and a
    test that watched only one would read a lost job as a deduplicated one.
    """
    seen: list[tuple[str, dict[str, Any]]] = []

    async def _capture(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        seen.append((job, payload))
        return f"{job}:{len(seen)}"

    monkeypatch.setattr(webhook_routes, "enqueue", _capture)
    monkeypatch.setattr(pipeline, "enqueue", _capture)
    return seen


async def _staged(label: str) -> tuple[UUID, str, str]:
    reset_engine_cache()
    agent_ref = f"ordering_{label}_{RUN}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_{label}_{RUN}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    return tenant_id, agent_ref, execution_id


async def _deliver(execution_id: str, status: str, agent_ref: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=voice_app), base_url="http://runtime"
    ) as http:
        return await http.post(
            HOOK, json={"execution_id": execution_id, "status": status, "agent_id": agent_ref}
        )


async def _inbox(execution_id: str) -> list[tuple[str, str]]:
    async with untenanted_session() as session:
        return [
            (str(row[0]), str(row[1]))
            for row in (
                await session.execute(
                    text(
                        "SELECT event_key, status FROM webhook_inbox_events "
                        "WHERE provider = 'fake' AND event_key LIKE :like ORDER BY event_key"
                    ),
                    {"like": f"{execution_id}:%"},
                )
            ).all()
        ]


async def _state(tenant_id: UUID, execution_id: str) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT id, status FROM calls WHERE engine_call_id = :e"),
                {"e": execution_id},
            )
        ).first()
        rows = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
        if row is None:
            return {"call": None, "call_rows": int(rows or 0)}
        usage = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": row[0]}
            )
        ).scalar()
        leads = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    return {
        "call": row[0],
        "status": str(row[1]),
        "call_rows": int(rows or 0),
        "usage": int(usage or 0),
        "leads": int(leads or 0),
    }


# ======================================= 1. terminal first, progress after (out of order)


async def test_a_terminal_and_a_late_progress_event_stay_two_units_of_work(
    queued: list[tuple[str, dict[str, Any]]],
) -> None:
    """D-40's keying, seen from the direction that arrives backwards.

    The inbox is keyed on `{execution}:{status}` — the TRANSITION — precisely so a
    later `completed` is not swallowed as a duplicate of an earlier `queued`. The
    consequence, which has to be deliberate rather than accidental, is that a LATE
    progress event is also its own unit of work: it claims its own row and gets its own
    job, and nothing about it may disturb the transition that already settled.
    """
    _tenant_id, agent_ref, execution_id = await _staged("late")

    terminal = await _deliver(execution_id, "completed", agent_ref)
    late = await _deliver(execution_id, "in-progress", agent_ref)

    assert terminal.json()["status"] == "accepted"
    assert late.json()["status"] == "accepted", (
        "a late progress event must not be answered `duplicate` — the inbox key is the "
        "transition, and collapsing them is how `completed` was lost (D-40)"
    )
    assert await _inbox(execution_id) == [
        (f"{execution_id}:completed", "enqueued"),
        (f"{execution_id}:in-progress", "enqueued"),
    ]
    assert [job for job, _ in queued] == [pipeline.INGEST_JOB] * 2


async def test_a_late_progress_event_cannot_undo_a_settled_call(
    queued: list[tuple[str, dict[str, Any]]],
) -> None:
    """The ledger is what this protects. The whole pipeline runs on `completed`, and the
    late `in-progress` then arrives and is INGESTED — with the engine itself reporting
    the older state, which is the eventually-consistent vendor this defends against.

    `pipeline_audit_test` asserts the same invariant one function down; this drives it
    from the wire, through the receiver and the inbox, because the keying above is what
    decides whether that second ingest happens at all.
    """
    tenant_id, agent_ref, execution_id = await _staged("regress")

    await _deliver(execution_id, "completed", agent_ref)
    ingest = next(p for job, p in queued if job == pipeline.INGEST_JOB)
    await pipeline.ingest_engine_event({}, ingest)
    postcall = next(p for job, p in queued if job == pipeline.POSTCALL_JOB)
    await pipeline.run_post_call_pipeline({}, postcall)
    settled = await _state(tenant_id, execution_id)
    assert settled["usage"] > 0 and settled["leads"] == 1

    # The vendor's own record regresses, which is the hostile version of a late event:
    # not just a stale payload, but a stale answer from the authenticated fetch itself.
    get_engine()._calls[execution_id]["status"] = "ringing"  # type: ignore[attr-defined]
    await _deliver(execution_id, "ringing", agent_ref)
    late_ingest = [p for job, p in queued if job == pipeline.INGEST_JOB][-1]
    outcome = await pipeline.ingest_engine_event({}, late_ingest)

    assert outcome.startswith("awaiting_completion"), outcome
    after = await _state(tenant_id, execution_id)
    assert after["status"] == "completed", "a finished call walked backwards"
    assert after["usage"] == settled["usage"], "a late event moved the append-only ledger"
    assert after["leads"] == 1


# ========================================== 2. two transitions arriving at the same time


async def test_two_transitions_of_one_execution_ingested_at_once_yield_one_call(
    queued: list[tuple[str, dict[str, Any]]],
) -> None:
    """The poller and the webhook, racing. Their ingest job ids differ by design
    (`...:reconcile` vs `...:{raw_status}`), so ARQ does not collapse them and two
    workers really can be inside `_upsert_call` for one execution at the same instant.

    `calls.engine_call_id` is globally unique, so the outcome is decided by the
    `ON CONFLICT` and by the loser's fallback read — the branch that exists precisely
    because the conflict's WHERE clause can refuse the update and return no row.
    """
    tenant_id, agent_ref, execution_id = await _staged("race")

    results = await asyncio.gather(
        pipeline.ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
        ),
        pipeline.ingest_engine_event(
            {},
            {
                "engine": "fake",
                "execution_id": execution_id,
                "engine_agent_ref": agent_ref,
                "source": "reconciliation",
            },
        ),
        return_exceptions=True,
    )

    assert not [r for r in results if isinstance(r, BaseException)], results
    assert results == ["pipeline_enqueued", "pipeline_enqueued"], results
    state = await _state(tenant_id, execution_id)
    assert state["call_rows"] == 1, (
        f"one execution became {state['call_rows']} call rows — every downstream count, "
        "including the invoice, is per call row"
    )
    postcall = {str(p["call_id"]) for job, p in queued if job == pipeline.POSTCALL_JOB}
    assert postcall == {str(state["call"])}, (
        "both racers must name the SAME call id, or ARQ's job-id dedupe has nothing to "
        f"collapse and the pipeline runs twice: {postcall}"
    )


async def test_the_same_transition_delivered_twice_at_once_is_one_job(
    queued: list[tuple[str, dict[str, Any]]],
) -> None:
    """The narrower race, at the wire rather than in the worker: two copies of ONE
    transition released together.

    `webhook_storm_test` measures this at width 24 with round-trip budgets; the reason
    it is repeated here in two lines is that the tests above deliver SEQUENTIALLY, and a
    file about ordering that never overlapped two deliveries would be asserting the
    inbox's behaviour on a schedule the vendor does not promise.
    """
    _tenant_id, agent_ref, execution_id = await _staged("herd")
    gate = asyncio.Barrier(2)

    async def _one() -> Any:
        await gate.wait()
        return await _deliver(execution_id, "completed", agent_ref)

    first, second = await asyncio.gather(_one(), _one())

    outcomes = sorted([first.json()["status"], second.json()["status"]])
    assert outcomes == ["accepted", "duplicate"], outcomes
    assert await _inbox(execution_id) == [(f"{execution_id}:completed", "enqueued")]
    assert len([job for job, _ in queued if job == pipeline.INGEST_JOB]) == 1
