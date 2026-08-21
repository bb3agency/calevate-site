"""The post-call pipeline under PARTIAL failure: killed between two stages, then re-driven.

`pipeline_audit_test` proves a clean re-run converges. `postcall_concurrency_test` proves
two overlapping runs converge. Neither asks the question a real worker actually poses,
which is the one in the middle: **the job died with stages 1..n committed and n+1..8 not,
and something re-drove it.** That is not a rare shape — it is what an ARQ retry, a
`job_timeout` cancellation, a deploy mid-batch and every reconciliation repair look like
from the database's side — and it is the only shape under which "usage_events is
append-only" becomes a permanent double charge rather than a tidy no-op.

So this file walks the seam once per stage boundary. For each stage it makes that stage
fail on the first attempt and succeed on the second, then compares the FULL artefact
census — transcript turns, extraction, lead, lead timeline, usage rows, the money on
them, the credit debit, the spend counter the cap is enforced against, and both outbox
promises — against a clean single run of an identical call. Anything a partial run
duplicates, loses or leaves half-written shows up as a census that does not match.

Three defects this pass found, each with its own test below:

1. **`ingest_engine_event`'s failure policy covered two of its five steps.** The engine
   fetch and the enqueue were inside a `try`; `_resolve_agent`, `_upsert_call` and
   `mark_inbox_processed` were not. A blip in those got ONE attempt from arq, fired no
   alert, and left the inbox row in `processing` — which `claim_inbox_event` answers
   `duplicate` for the whole `CLAIM_LEASE`, so the vendor's own retry was dropped too.
2. **The recording copy re-downloaded on every re-drive**, so a repair for a MISSING
   EXTRACTION could be blocked forever by a vendor link that had since expired: step 1
   raised before step 3 was ever reached.
3. **`storage.recording_key` interpolated `datetime.now(UTC)`**, so a second copy of one
   call landed under a second key across a month boundary — an object the DPDP erasure
   cannot enumerate, under a certificate saying the recording was destroyed.

Scope discipline: every test builds its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import SAMPLE_TURNS
from apps.api.integrations import service as integrations
from apps.workers import campaign_dispatch, pipeline, storage
from apps.workers.storage import StorageUnavailableError
from arq import Retry
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text
from tests.ingest_ordering_test import _inbox_status, _run_to_exhaustion, _seed_inbox
from tests.platform_support import requires_posix_signals
from tests.smoke_pipeline_test import _seed_tenant

RUN = uuid.uuid4().hex[:12]


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bucket is an environment concern; the same substitution the smoke test makes.

    It returns `storage.recording_key`'s own answer rather than a hand-written string, so
    a test that asserts on the stored key is asserting on the real key shape.
    """

    async def _fake_copy(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        return storage.recording_key(tenant_id, call_id)

    monkeypatch.setattr(pipeline, "copy_recording", _fake_copy)
    # The ladder's SHAPE is what these tests are about, never its pace.
    monkeypatch.setattr(pipeline, "RETRY_BACKOFF_S", (0.02, 0.02))


async def _staged(label: str) -> tuple[UUID, str, UUID]:
    """A fresh tenant with one completed inbound call, ingested. The pipeline has NOT run.

    A tenant of its own per call, because `spend_state` is per TENANT: two calls sharing
    one would accumulate, and the census below compares one call against another.
    """
    reset_engine_cache()
    agent_ref = f"partial_{label}_{RUN}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_{label}_{RUN}"
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
        # A subscribed CRM endpoint, so step 8 actually writes rather than being a
        # no-op the census cannot see (D-23).
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, events, active, "
                "created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example.invalid/hook', ARRAY['call.completed'], true, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )
        # `self_serve` so the prepaid credit debit runs too — a managed tenant is invoiced
        # against a retainer and never touches `credit_ledger`, which would have made the
        # money half of every census below prove half of what it says.
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
    return tenant_id, execution_id, UUID(str(call_id))


async def _run(tenant_id: UUID, call_id: UUID, execution_id: str, attempt: int = 1) -> str:
    return await pipeline.run_post_call_pipeline(
        {"job_try": attempt},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )


async def _census(tenant_id: UUID, call_id: UUID) -> dict[str, Any]:
    """Everything one completed call is supposed to leave behind, by count and by rupee.

    Counts, ids and NUMERIC money only — no phone number and no transcript text crosses
    this boundary either (hard rule 6).
    """
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM transcript_turns WHERE call_id = :c), "
                    "(SELECT count(*) FROM call_extractions WHERE call_id = :c), "
                    "(SELECT count(*) FROM leads WHERE tenant_id = :t), "
                    "(SELECT COALESCE(max(call_count), 0) FROM leads WHERE tenant_id = :t), "
                    "(SELECT COALESCE(bool_or(is_repeat_caller), false) FROM leads "
                    "  WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM lead_events WHERE tenant_id = :t AND type = 'call'), "
                    "(SELECT count(*) FROM usage_events WHERE call_id = :c), "
                    "(SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                    "  FROM usage_events WHERE call_id = :c), "
                    "(SELECT count(*) FROM credit_ledger WHERE ref = :cs AND reason = 'usage'), "
                    "(SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE ref = :cs "
                    "  AND reason = 'usage'), "
                    "(SELECT recording_url FROM calls WHERE id = :c), "
                    "(SELECT summary IS NOT NULL FROM calls WHERE id = :c), "
                    "(SELECT lead_id IS NOT NULL FROM calls WHERE id = :c)"
                ),
                {"c": call_id, "t": tenant_id, "cs": str(call_id)},
            )
        ).first()
        spend = (
            await session.execute(
                text("SELECT minutes_used, spend_used, capped FROM spend_state WHERE tenant_id=:t"),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None
    async with untenanted_session() as session:
        outbox = (
            await session.execute(
                text(
                    "SELECT job, count(*) FROM outbox_messages "
                    "WHERE payload @> CAST(:m AS jsonb) OR payload @> CAST(:d AS jsonb) "
                    "GROUP BY job"
                ),
                {
                    "m": json.dumps({"call_id": str(call_id)}),
                    "d": json.dumps({"data": {"call_id": str(call_id)}}),
                },
            )
        ).all()
    return {
        "turns": row[0],
        "extractions": row[1],
        "leads": row[2],
        "lead_call_count": row[3],
        "lead_is_repeat": row[4],
        "lead_call_events": row[5],
        "usage_rows": row[6],
        "usage_cost": Decimal(str(row[7])),
        "credit_rows": row[8],
        "credit_delta": Decimal(str(row[9])),
        "recording_stored": bool(row[10]),
        "summary_stored": bool(row[11]),
        "call_linked_to_lead": bool(row[12]),
        "spend_minutes": Decimal(str(spend[0])) if spend else None,
        "spend_used": Decimal(str(spend[1])) if spend else None,
        "spend_capped": spend[2] if spend else None,
        "outbox": {job: int(count) for job, count in outbox},
    }


async def _clean_census(label: str) -> dict[str, Any]:
    """One identical call, run ONCE, cleanly. The shape everything else must match."""
    tenant_id, execution_id, call_id = await _staged(f"clean{label}")
    assert await _run(tenant_id, call_id, execution_id) == "ok"
    return await _census(tenant_id, call_id)


# --- 1. killed between two stages, then re-driven ------------------------------
#
# Each entry is (label, module, attribute). The attribute is the stage that FAILS, so
# everything before it committed and everything from it onward did not — which is the
# state a killed worker leaves and the state a re-drive has to converge from.

STAGE_BOUNDARIES: list[tuple[str, Any, str]] = [
    ("transcript", pipeline, "_persist_transcript"),
    ("opt_out", pipeline, "_maybe_record_opt_out"),
    ("context_load", pipeline, "_load_call_context"),
    ("extract", pipeline, "extract_call"),
    ("extraction_persist", pipeline, "_persist_extraction"),
    ("lead_upsert", pipeline, "_upsert_lead"),
    ("meter", pipeline, "_meter"),
    ("notify", pipeline, "_maybe_notify_hot_lead"),
    # Step 7 and step 8 share ONE transaction under `lock_call_writes`; both are reached
    # through names this module does not own, so they are patched at their source.
    ("campaign_resolve", campaign_dispatch, "resolve_campaign_contact"),
    ("crm_fanout", integrations, "enqueue_event"),
]


@pytest.mark.parametrize(
    "label,module,attr", STAGE_BOUNDARIES, ids=[stage[0] for stage in STAGE_BOUNDARIES]
)
async def test_a_worker_killed_at_one_stage_converges_when_it_is_re_driven(
    monkeypatch: pytest.MonkeyPatch, label: str, module: Any, attr: str
) -> None:
    """The whole seam, one boundary at a time.

    The first attempt dies AT `attr` — so every stage before it is committed and every
    stage from it onward is not. The second attempt is the retry arq makes, and the
    census afterwards must equal a clean single run's, exactly: one extraction, one lead,
    one timeline entry, one set of usage rows, one credit debit, one spend figure and one
    of each outbox promise.

    A stage that is not idempotent shows up here as a count of two — and on
    `usage_events`, which is append-only (hard rule 4), a two is a charge only a
    hand-written compensating entry can answer.
    """
    clean = await _clean_census(label)
    tenant_id, execution_id, call_id = await _staged(f"kill{label}")

    real = getattr(module, attr)
    calls = {"n": 0}

    async def _fail_once(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(f"the worker died at {attr}")
        return await real(*args, **kwargs)

    monkeypatch.setattr(module, attr, _fail_once)
    monkeypatch.setattr(pipeline, "alert", lambda *a, **k: None)

    # Attempt 1: a transient failure asks arq for a retry rather than finishing the job.
    with pytest.raises(Retry):
        await _run(tenant_id, call_id, execution_id, attempt=1)
    partial = await _census(tenant_id, call_id)

    # Attempt 2: the retry, completing the job.
    assert await _run(tenant_id, call_id, execution_id, attempt=2) == "ok"
    assert calls["n"] >= 2, "the retry did not re-run the stage that failed"

    final = await _census(tenant_id, call_id)
    assert final == clean, (
        f"a run killed at {attr} and re-driven does not match a clean run.\n"
        f"  after the partial run: {partial}\n"
        f"  after the re-drive:    {final}\n"
        f"  a clean single run:    {clean}"
    )


async def test_the_census_can_actually_see_a_double(monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative control: a census that cannot go red measures nothing.

    `_upsert_lead`'s timeline INSERT is guarded by `WHERE NOT EXISTS (... payload->>
    'call_id' = :cid)`. Break exactly that guard — the shape a plain INSERT would have —
    and the re-drive must file the call on the lead's timeline twice, which the comparison
    above has to catch. Nothing else about the run changes.
    """
    clean = await _clean_census("control")
    tenant_id, execution_id, call_id = await _staged("control")

    real_upsert = pipeline._upsert_lead

    async def _unguarded(*args: Any, **kwargs: Any) -> Any:
        lead_id = await real_upsert(*args, **kwargs)
        if lead_id is not None:
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                        "created_at, updated_at) VALUES (:id, :tid, :lid, 'call', "
                        "CAST(:payload AS jsonb), 'system', now(), now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tid": tenant_id,
                        "lid": lead_id,
                        "payload": json.dumps({"call_id": str(call_id), "status": "completed"}),
                    },
                )
        return lead_id

    monkeypatch.setattr(pipeline, "_upsert_lead", _unguarded)
    assert await _run(tenant_id, call_id, execution_id) == "ok"

    final = await _census(tenant_id, call_id)
    assert final != clean, "the census compared equal against a deliberately doubled timeline"
    assert final["lead_call_events"] == clean["lead_call_events"] + 1


# --- 2. the ingest job's failure policy covers every one of its stages ---------


async def _staged_engine_call(label: str) -> tuple[UUID, str, str]:
    """A tenant whose engine holds one completed inbound call. Nothing ingested yet."""
    reset_engine_cache()
    agent_ref = f"ingestpol_{label}_{RUN}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_ingestpol_{label}_{RUN}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    return tenant_id, agent_ref, execution_id


@pytest.mark.parametrize("stage", ["_upsert_call", "mark_inbox_processed"])
@requires_posix_signals
async def test_a_blip_in_the_ingest_jobs_middle_gets_the_ladder_and_says_so(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """THE DEFECT. `ingest_engine_event` wrapped its engine fetch and its enqueue in
    `_abandon_ingest` and left the three steps between them bare.

    Measured on a real arq worker before the fix, for BOTH stages below: **1 attempt, 0
    alerts, and the inbox row still `processing`**. Every part of that is wrong in the
    same direction:

    * arq 0.28 retries only for `Retry`/`RetryJob`/`CancelledError`, so `max_tries = 3`
      was decorative for a database blip in the one step that WRITES THE CALL ROW;
    * nothing alerted, so a dropped call looked exactly like a quiet hour;
    * `processing` is what `claim_inbox_event` answers `duplicate` to for the whole
      `CLAIM_LEASE` — so the vendor's own retry of an at-most-once webhook was swallowed
      by a claim with nobody behind it, for ten minutes.

    The 10-minute reconciliation poller bounded the damage, which is the inversion D-31
    warns about: the ladder is the fast recovery and the poller is the guarantee, not the
    other way round.

    Attempts come from a REAL worker (`_run_to_exhaustion`), never from an injected
    `job_try` — a test that writes its own can only prove that an `if` compares two
    integers, which is exactly how this survived.
    """
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(pipeline, "alert", lambda s, code, **kw: fired.append((str(s), str(code))))
    _tenant_id, agent_ref, execution_id = await _staged_engine_call(stage)
    row_id = await _seed_inbox(f"{stage}:{execution_id}")

    async def _blip(*args: Any, **kwargs: Any) -> Any:
        raise ProblemError(
            kind="transient",
            code="db_unavailable",
            title="The database did not answer",
            detail="A connection was reset mid-statement.",
        )

    monkeypatch.setattr(pipeline, stage, _blip)

    attempts = await _run_to_exhaustion(
        pipeline.ingest_engine_event,
        {
            "engine": "fake",
            "execution_id": execution_id,
            "engine_agent_ref": agent_ref,
            "inbox_row_id": str(row_id),
        },
    )

    assert attempts == WORKER_MAX_TRIES, (
        f"a blip in `{stage}` must get the whole ladder; the worker ran it {attempts} time(s)"
    )
    assert ("WORKER_TERMINAL", "engine_ingest_abandoned") in fired, (
        "the end of the ladder is a call nobody was told about, and it has to say so"
    )
    assert await _inbox_status(row_id) == "failed", (
        "the row was left `processing`, which answers every vendor retry `duplicate` for "
        "the whole CLAIM_LEASE with nothing behind the claim"
    )


@requires_posix_signals
async def test_an_ingest_payload_with_no_execution_id_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of a retry policy, and the reason the parse moved inside it.

    `str(payload["execution_id"])` used to run before the `try`, so a malformed payload
    left the job as a bare `KeyError`: no alert, and — because arq finishes a job on
    anything that is not `Retry` — no ladder either, which was accidentally the right
    number of attempts for the wrong reason. It is now a `validation` ProblemError, which
    the ONE transient/permanent split classifies, exactly as `_post_call_target` already
    did for the other job.
    """
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(pipeline, "alert", lambda s, code, **kw: fired.append((str(s), str(code))))

    attempts = await _run_to_exhaustion(pipeline.ingest_engine_event, {"engine": "fake"})

    assert attempts == 1, f"a payload that cannot be parsed was retried {attempts} times"
    assert ("WORKER_TERMINAL", "engine_ingest_abandoned") in fired


async def test_the_happy_ingest_path_still_closes_its_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """The counterweight: wrapping the job in a failure policy must not change what a
    healthy event does. The row still ends `processed`, and the pipeline is still queued."""
    _tenant_id, agent_ref, execution_id = await _staged_engine_call("happy")
    row_id = await _seed_inbox(f"happy:{execution_id}")

    async def _swallow(job: str, *args: Any, **kwargs: Any) -> str:
        return "queued"

    monkeypatch.setattr(pipeline, "enqueue", _swallow)

    result = await pipeline.ingest_engine_event(
        {},
        {
            "engine": "fake",
            "execution_id": execution_id,
            "engine_agent_ref": agent_ref,
            "inbox_row_id": str(row_id),
        },
    )

    assert result == "pipeline_enqueued"
    assert await _inbox_status(row_id) == "processed"


async def test_a_second_completed_webhook_with_a_fuller_body_is_still_one_unit_of_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two `completed` deliveries of one execution with DIFFERENT bodies, answered by the
    DURABLE dedupe rather than by the Redis one.

    `claim_inbox_event` refuses a known `event_key` whose `payload_hash` has changed —
    that is the alarm for a doctored replay at an unsigned endpoint, and it is a 409. Two
    honest deliveries of one transition can legitimately differ in body (a vendor retry
    carrying a fuller payload), so `_claim_and_enqueue` hashes the UNIT OF WORK — engine,
    execution, raw_status — rather than the delivery. `webhook_routes` argues that in full
    and nothing exercised it: an alarm that fires on healthy traffic is one nobody reads
    when a real one arrives.

    **Redis is taken out of the picture on purpose, and that is what makes this test
    measure the layer it names.** The fast path is keyed on the transition, so it would
    absorb the second delivery before Postgres ever saw it — leaving this test green while
    proving nothing about the inbox. `_fast_path_seen` is documented to answer "not seen"
    when Redis is unavailable and fall through to the durable claim, so that is the
    condition simulated here: a real, supported state, in which the inbox is the only
    thing standing between a fuller retry and a spoofing alarm.

    `duplicate_count` is the proof the second delivery really reached the claim: the fast
    path returns before touching Postgres, so an absorb there leaves it at 0.
    """
    import webhook_routes

    _tenant_id, agent_ref, execution_id = await _staged_engine_call("fuller")

    # `digest` is the settled delivery's body fingerprint, which `_fast_path_seen`
    # compares to count `webhook_replay_divergence`; a stub that never reports a hit
    # has nothing to compare and only has to accept it.
    async def _redis_down(redis_key: str, digest: str, *, engine: str) -> bool:
        return False

    monkeypatch.setattr(webhook_routes, "_fast_path_seen", _redis_down)

    hook = "/hooks/v1/engine/fake"
    lean = {"execution_id": execution_id, "status": "completed", "agent_id": agent_ref}
    fuller = {**lean, "recording_url": "https://vendor.example.invalid/a.wav", "duration": 95}

    transport = ASGITransport(app=voice_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://runtime") as http:
        first = await http.post(hook, json=lean)
        second = await http.post(hook, json=fuller)

    assert first.json()["status"] == "accepted", first.text
    assert second.status_code == 202, (
        "a retry with a fuller body was refused outright — the inbox read a changed "
        f"payload hash as a doctored replay: {second.text}"
    )
    assert second.json()["status"] == "duplicate"

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status, duplicate_count FROM webhook_inbox_events "
                    "WHERE provider = 'fake' AND event_key = :k"
                ),
                {"k": f"{execution_id}:completed"},
            )
        ).all()
    assert len(rows) == 1, f"{len(rows)} inbox rows for one transition"
    assert rows[0][1] == 1, (
        "the second delivery never reached the durable dedupe this test exists to measure"
    )


# --- 3. the recording copy runs once, and cannot block a repair ----------------


async def test_a_re_drive_does_not_re_fetch_a_recording_we_already_hold() -> None:
    """Step 1 is the only stage whose re-run costs a round trip to a THIRD PARTY.

    Everything else re-runs by rewriting a row we own; this one re-downloads several
    megabytes from the vendor. A repair that re-fetches audio it already has is paying
    for the same bytes on every tick of the guarantee of record.
    """
    tenant_id, execution_id, call_id = await _staged("recopy")
    fetches = {"n": 0}

    async def _counting_copy(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        fetches["n"] += 1
        return storage.recording_key(tenant_id, call_id)

    original = pipeline.copy_recording
    pipeline.copy_recording = _counting_copy  # type: ignore[assignment]
    try:
        await _run(tenant_id, call_id, execution_id)
        await _run(tenant_id, call_id, execution_id)
    finally:
        pipeline.copy_recording = original  # type: ignore[assignment]

    assert fetches["n"] == 1, f"the vendor's audio was fetched {fetches['n']} times for one call"
    key = await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    assert key == storage.recording_key(tenant_id, call_id)


async def test_an_expired_vendor_link_cannot_block_the_repair_of_a_lost_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DEFECT, and it is the guarantee of record quietly ceasing to guarantee.

    `_pipeline_settled` re-drives a call whose EXTRACTION or USAGE is missing. The
    recording is not one of the artefacts it checks — but the pipeline starts with it, so
    the re-drive had to get past a vendor fetch before it could reach the stage it came
    to repair. Bolna's recording URLs are direct S3 links with no documented expiry
    (TRD §5), so an hour later the fetch 403s, `StorageUnavailableError` fails the whole
    job, and the poller re-drives it again next hour to fail identically: the lead is
    never repaired and nothing else will ever mention it.

    Here the recording is already ours, the extraction has been lost, and the vendor link
    now refuses. The repair must still land.
    """
    tenant_id, execution_id, call_id = await _staged("expired")
    await _run(tenant_id, call_id, execution_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM call_extractions WHERE call_id = :c"), {"c": call_id}
        )

    async def _gone(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        raise StorageUnavailableError("recording fetch failed: HTTPStatusError")

    monkeypatch.setattr(pipeline, "copy_recording", _gone)

    assert await _run(tenant_id, call_id, execution_id) == "ok"
    assert (
        await _scalar(
            tenant_id, "SELECT count(*) FROM call_extractions WHERE call_id = :c", c=call_id
        )
        == 1
    ), "the artefact the poller came to repair was never written"


async def test_a_first_copy_that_storage_refuses_still_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counterweight, so the guard above cannot become "never copy anything".

    A call whose audio we do NOT hold and whose copy fails must still raise, and must
    still alert: a lost recording is unrecoverable and TRAI's 90-day floor is our
    obligation, not the vendor's.
    """
    tenant_id, execution_id, call_id = await _staged("firstfail")
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(pipeline, "alert", lambda s, code, **kw: fired.append((str(s), str(code))))

    async def _refused(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        raise StorageUnavailableError("recording upload failed: ClientError")

    monkeypatch.setattr(pipeline, "copy_recording", _refused)

    with pytest.raises(StorageUnavailableError):
        await _run(tenant_id, call_id, execution_id)
    assert ("WORKER_DELIVERY", "recording_copy_failed") in fired
    assert (
        await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    ) is None


def test_a_recordings_key_does_not_depend_on_when_it_was_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DPDP erasure destroys the object `calls.recording_url` names, and nothing else.

    The key used to interpolate `datetime.now(UTC).strftime("%Y/%m")`, so a second copy of
    one call — the pipeline crashing between the PUT and the `recording_url` commit, or an
    operator replaying a call that ended at 23:58 on the 31st — landed under a SECOND key.
    The database holds one; the other is reachable by nothing the retention sweep or the
    erasure worker can enumerate, and the erasure certificate says the recording was
    destroyed. The bucket's lifecycle rule would reach it eventually, on a clock nobody
    asked about.

    Pinned as the property rather than as a literal: the key must be a pure function of
    (tenant, call).
    """
    tenant_id, call_id = uuid.uuid4(), uuid.uuid4()
    first = storage.recording_key(tenant_id, call_id)

    class _NextMonth(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return datetime(2027, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(storage, "datetime", _NextMonth)
    assert storage.recording_key(tenant_id, call_id) == first, (
        "two copies of one call's audio land under two keys, and only one of them is "
        "reachable by an erasure"
    )
    assert first.startswith("recordings/"), "the lifecycle rule is scoped to this prefix"


# --- 4. what a real vendor sends when it has nothing to send -------------------


async def test_a_completed_call_with_nothing_on_it_finishes_without_half_artefacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No transcript, no recording, no numbers, no duration, no cost — every optional
    field absent, which is what a vendor sends for a call that connected and died.

    The pipeline must complete rather than raise (a raise here is three retries and a
    terminal alert for a call that is simply empty), and it must not invent the artefacts
    it had no input for: no turns, no lead keyed on a number nobody gave, no usage row for
    a cost the engine never reported.
    """
    tenant_id, execution_id, call_id = await _staged("barren")
    barren = ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref=None,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=None,
        ended_at=None,
        duration_s=None,
        from_e164=None,
        to_e164=None,
        recording_url=None,
        transcript=[],
        cost=None,
        engine="fake",
    )

    class _Barren:
        name = "fake"

        async def get_execution(self, execution: str) -> ExecutionSnapshot:
            return barren

    monkeypatch.setattr(pipeline, "get_engine", lambda: _Barren())

    assert await _run(tenant_id, call_id, execution_id) == "ok"
    census = await _census(tenant_id, call_id)
    assert census["turns"] == 0
    assert census["leads"] == 0, "a lead keyed on a number nobody gave is a lead nobody can call"
    assert census["usage_rows"] == 0, "no cost was reported, so nothing may be billed"
    assert census["recording_stored"] is False
    # The extraction still lands: the agent HAS schema fields, and `EXTRACTION_OWED_SQL`
    # says so to both the stall alarm and the poller. A call that wrote none would be
    # re-driven forever by the mechanism that reads that rule.
    assert census["extractions"] == 1


async def test_a_zero_length_call_bills_what_the_ledger_can_express(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured size of a gap two docstrings used to disagree about.

    `_unit_price` keeps a leg whole when `qty` is 0, and every READER multiplies by `qty`
    — so the duration-priced legs contribute nothing. `billing.service._spend_used` has
    always said so; `_unit_price` used to claim the opposite ("the money never silently
    disappears from the ledger"). This pins the arithmetic in both directions so the
    number in that docstring is a measurement:

    * `spend_state.spend_used` takes `cost.total_inr` directly and is exact;
    * `SUM(qty * unit_cost_paid)` reconstructs only the two legs priced per unit.

    Not fixable on the write side — writing `qty = 1` for `telephony_s` would bill the
    client a second that never happened, and `usage_summary` reads minutes off that
    column. The closable half is a reader in `apps/api/billing`.
    """
    tenant_id, execution_id, call_id = await _staged("zerolen")
    real = await get_engine().get_execution(execution_id)
    zero = real.model_copy(
        update={
            "duration_s": 0,
            "cost": CostBreakdown(
                total_inr=Decimal("1.0000"),
                platform_inr=Decimal("0.4000"),
                network_inr=Decimal("0.3000"),
                llm_inr=Decimal("0.1000"),
                tts_inr=Decimal("0.1000"),
                stt_inr=Decimal("0.1000"),
                source_currency="INR",
            ),
        }
    )

    class _ZeroLength:
        name = "fake"

        async def get_execution(self, execution: str) -> ExecutionSnapshot:
            return zero

    monkeypatch.setattr(pipeline, "get_engine", lambda: _ZeroLength())
    assert await _run(tenant_id, call_id, execution_id) == "ok"

    census = await _census(tenant_id, call_id)
    assert census["spend_used"] == Decimal("1.0000"), "the cap counter takes the whole cost"
    assert census["usage_cost"] == Decimal("0.2000"), (
        "the ledger reconstructs only the tts and llm legs, which carry qty 1; the three "
        "duration-priced legs are on rows with qty 0 and multiply out to nothing"
    )
    assert census["usage_rows"] == 5, "every leg is still recorded, even the ones qty hides"


# --- 4b. a re-drive rewrites a turn WHOLE, or it rewrites a lie ----------------


async def test_a_re_driven_transcript_replaces_a_turn_rather_than_half_of_it() -> None:
    """`_persist_transcript`'s upsert was PARTIAL, and a partial upsert is a fabrication.

    The statement is `ON CONFLICT (call_id, idx) DO UPDATE SET text, text_redacted` — so a
    re-drive whose transcript differs at an index rewrote WHAT was said and kept WHO said
    it, WHICH LANGUAGE it was in and WHEN. The row that comes out was never spoken by
    anybody: the second run's words under the first run's speaker.

    IT IS REACHABLE THROUGH THE PARSER, not only through a vendor changing its mind.
    Bolna hands us one prefix-tagged text blob and `parse_transcript` indexes turns by
    POSITION, dropping a leading line it cannot attribute (`bolna.parse_transcript`: "an
    unprefixed line arriving BEFORE any turn exists" is counted lost). So a first fetch
    that lost the opening line and a second that did not are off by one for the whole
    call, and every turn keeps the previous run's speaker. `apps/api/engine/fake.py`
    already records what that costs downstream in so many words — the extractor
    attributing the agent's words to the caller is how a call became a hot lead that never
    was — and `speaker` also drives the client's transcript view and the QA sample.

    The same statement also left ORPHANS: a re-drive producing FEWER turns updated the
    ones it had and left the tail of the longer run in place, so the call ends with turns
    from two different readings of it.

    Nothing here is about a vendor being fickle; it is about a row being written half-way.
    Both halves are asserted on one call, which is the only way to see that the fix is a
    REPLACEMENT of the transcript rather than a merge of two.
    """
    tenant_id, execution_id, call_id = await _staged("turnswap")

    long_read = ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref=f"partial_turnswap_{RUN}",
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        transcript=[
            TranscriptTurn(call_id=execution_id, idx=0, speaker="caller", text="naaku appointment"),
            TranscriptTurn(call_id=execution_id, idx=1, speaker="agent", text="evening 6 gantalu"),
            TranscriptTurn(call_id=execution_id, idx=2, speaker="caller", text="sare"),
        ],
    )
    # The SAME call read again with the opening line recovered: every turn shifts by one
    # and the last one is gone from this reading.
    short_read = ExecutionSnapshot(
        **{
            **long_read.model_dump(),
            "transcript": [
                TranscriptTurn(
                    call_id=execution_id, idx=0, speaker="agent", text="namaskaram", lang="te-IN"
                ),
                TranscriptTurn(
                    call_id=execution_id,
                    idx=1,
                    speaker="caller",
                    text="naaku appointment",
                    lang="te-IN",
                ),
            ],
        }
    )

    await pipeline._persist_transcript(tenant_id, call_id, long_read)
    await pipeline._persist_transcript(tenant_id, call_id, short_read)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT idx, speaker, text, lang FROM transcript_turns "
                    "WHERE call_id = :c ORDER BY idx"
                ),
                {"c": call_id},
            )
        ).all()

    assert [(r[0], r[1], r[2]) for r in rows] == [
        (0, "agent", "namaskaram"),
        (1, "caller", "naaku appointment"),
    ], (
        "the second reading of this call did not replace the first: a turn kept the "
        "earlier run's speaker under the later run's words, or the earlier run's tail "
        "survived as a turn nobody in this call ever spoke"
    )
    assert [r[3] for r in rows] == ["te-IN", "te-IN"], (
        "`lang` was not carried by the upsert either — the columns a re-drive refreshes "
        "must be every column the turn has, not the two the first version happened to name"
    )


# --- 5. hard rule 6, across every line this path can write ---------------------


async def test_no_stage_of_the_pipeline_hands_a_number_or_a_transcript_to_a_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6, asserted BEFORE the formatter rather than after it.

    `JsonFormatter` runs every extra through `redact_mapping`, so a test that reads
    formatted output would pass no matter what the pipeline handed it — the second line of
    defence proving the first one exists. So this captures the raw `LogRecord`s and the
    `alert()` arguments, and asserts the pipeline never PUTS a phone number or a
    transcript fragment into either.

    The call is driven all the way through with a caller number and a transcript that
    contains one, and every stage is exercised: recording copy, transcript persist,
    extraction, lead upsert, metering, the hot-lead promise and the CRM fan-out.
    """
    tenant_id, execution_id, call_id = await _staged("logs")
    caller = await _scalar(tenant_id, "SELECT from_e164 FROM calls WHERE id = :c", c=call_id)
    assert caller, "the fixture must give this test a number to look for"

    fired: list[str] = []

    def _capture_alert(stage: Any, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append(f"{stage} {code} {detail} {ids}")

    monkeypatch.setattr(pipeline, "alert", _capture_alert)

    with caplog.at_level(logging.DEBUG):
        assert await _run(tenant_id, call_id, execution_id) == "ok"

    fragments = [str(caller), str(caller)[-6:], *(body for _speaker, body in SAMPLE_TURNS)]
    written = [f"{record.getMessage()} {record.__dict__}" for record in caplog.records] + fired
    for line in written:
        for fragment in fragments:
            assert fragment not in line, (
                f"a phone number or transcript fragment reached a log line: {line[:200]}"
            )
    assert written, "the pipeline logged nothing at all, so this test proved nothing"


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).scalar()
