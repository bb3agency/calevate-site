"""Audit of the reliability machinery: idempotency, outbox, inbox, and the Redis
fast paths they lean on (BACKEND-PATTERNS §4-§5).

Everything here is written as a PROPERTY the triad must hold, not as a description of
what the code currently does — the point of an audit test is that it fails first.

Two house rules, both learned the hard way:

- **Run-unique keys.** Other suites hammer the same Postgres, and these tables are not
  truncated between runs. Every row this file writes carries `RUN` in its key, and
  every assertion counts only rows carrying `RUN`. A test that counts a whole table is
  testing the other agents, not the code.
- **Concurrency means overlapping transactions.** Two sequential claims prove nothing:
  a re-claim after the first transaction ended is often the retry path working as
  designed. The races below interleave with `asyncio.gather` + an `asyncio.Event` so
  the second claimer really does run against the first one's uncommitted locks.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import timedelta
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability import service as rel
from redis.exceptions import RedisError
from sqlalchemy import text

# Every key this module writes is prefixed with the run id, so a parallel suite's rows
# can never be mistaken for ours.
RUN = uuid.uuid4().hex[:12]

SCOPE = f"audit-scope-{RUN}"
ROUTE = "/v1/leads/{lead_id}/call"
PROVIDER = f"audit-{RUN}"


def key(name: str) -> str:
    return f"{name}-{RUN}"


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> Any:
    """Our outbox rows are deliberately backdated so the oldest-first claims reach them.
    That also puts them at the front of every OTHER suite's dispatcher tick, so they do
    not get to outlive this module."""
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE payload->>'marker' LIKE :m"),
            {"m": f"%{RUN}"},
        )
        await session.execute(
            text("DELETE FROM webhook_inbox_events WHERE provider = :p"), {"p": PROVIDER}
        )
        await session.execute(
            text("DELETE FROM idempotency_records WHERE scope_key = :s"), {"s": SCOPE}
        )


# --------------------------------------------------------------------- helpers


async def _idempotency_row(k: str) -> tuple[str, int | None, dict[str, Any] | None] | None:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, response_status, response_payload FROM idempotency_records "
                    "WHERE scope_key = :s AND route = :r AND method = 'POST' "
                    "AND idempotency_key = :k"
                ),
                {"s": SCOPE, "r": ROUTE, "k": k},
            )
        ).first()
    return (row[0], row[1], row[2]) if row else None


async def _age_idempotency(k: str, *, minutes: int) -> None:
    """Simulate elapsed wall-clock: the holder of this claim died `minutes` ago."""
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE idempotency_records SET updated_at = now() - :age "
                "WHERE scope_key = :s AND route = :r AND idempotency_key = :k"
            ),
            {"age": timedelta(minutes=minutes), "s": SCOPE, "r": ROUTE, "k": k},
        )


async def _age_inbox(event_key: str, *, minutes: int) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE webhook_inbox_events SET updated_at = now() - :age "
                "WHERE provider = :p AND event_key = :k"
            ),
            {"age": timedelta(minutes=minutes), "p": PROVIDER, "k": event_key},
        )


async def _inbox_rows(event_key: str) -> list[tuple[Any, ...]]:
    async with untenanted_session() as session:
        return [
            tuple(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT id, status, duplicate_count FROM webhook_inbox_events "
                        "WHERE provider = :p AND event_key = :k"
                    ),
                    {"p": PROVIDER, "k": event_key},
                )
            ).all()
        ]


async def _seed_outbox(marker: str, *, count: int = 1, status: str = "pending") -> list[uuid.UUID]:
    """Seed outbox rows dated well into the past.

    Both `claim_outbox_batch` and `replay_dead_letters` work oldest-first over the WHOLE
    table, and this database already carries hundreds of pending rows left by other
    suites (the oldest several hours back). Backdating far enough to beat all of them
    makes our rows deterministically the front of the queue, so a SMALL `limit` reaches
    them and — just as important — never reaches anybody else's. The module fixture
    deletes them again as soon as the file is done.
    """
    ids: list[uuid.UUID] = []
    async with untenanted_session() as session:
        for _ in range(count):
            mid = uuid7()
            ids.append(mid)
            await session.execute(
                text(
                    "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                    "created_at, updated_at) VALUES (:id, 'default', 'notify_hot_lead', "
                    "CAST(:p AS jsonb), :st, 0, now() - interval '30 days', now())"
                ),
                {"id": mid, "p": json.dumps({"marker": marker}), "st": status},
            )
    return ids


async def _retire(*ids: uuid.UUID) -> None:
    """Drop this test's outbox rows the moment it is done with them.

    Two reasons, both about the oldest-first ordering these rows deliberately game:
    they must not sit at the head of another suite's dispatcher tick, and they must not
    sit at the head of the NEXT test in this file either — a leftover backdated row is
    exactly the kind of shared state that makes a claim test quietly assert nothing.
    """
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = ANY(:ids)"), {"ids": list(ids)}
        )


async def _run_one_job_to_exhaustion(
    func: Any, payload: Any, *, max_tries: int, settings: Any
) -> int:
    """Run ONE job on a REAL arq worker until it stops being retried; return the number
    of attempts the worker actually made.

    The whole point is that nothing here is simulated. `ctx["job_try"]` is written by
    arq, the retry decision is arq's, and the count comes back from the worker rather
    than from the job. A test that injects `job_try` into `ctx` can only ever confirm
    that an `if` statement compares two numbers correctly — it cannot notice that the
    branch is unreachable.

    Burst mode drains what is ready and returns, so deferred retries need another pass;
    the loop is the scheduler.
    """
    from arq import create_pool
    from arq.worker import Worker

    # A queue and a job id unique per CALL, not per function: two tests exercising the
    # same job on the same queue would otherwise collide on arq's job-id dedupe and the
    # second would silently enqueue nothing — reading as "the job was never retried".
    run_id = uuid7().hex
    queue_name = f"audit:{RUN}:{run_id}"
    attempts = 0
    real = func

    async def counting(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        return await real(ctx, *args, **kwargs)

    # arq registers a function under its __qualname__, and a closure's qualname is
    # `_run_one_job_to_exhaustion.<locals>.counting` — enqueueing under the real name
    # would silently miss and the worker would report "function not found".
    counting.__name__ = func.__name__
    counting.__qualname__ = func.__name__
    worker = Worker(
        functions=[counting],
        redis_settings=settings,
        queue_name=queue_name,
        max_tries=max_tries,
        burst=True,
        poll_delay=0.02,
        keep_result=1,
        retry_jobs=True,
        handle_signals=False,
    )
    pool = await create_pool(settings, default_queue_name=queue_name)
    args = () if payload is None else (payload,)
    enqueued = await pool.enqueue_job(func.__name__, *args, _job_id=run_id)
    assert enqueued is not None, "the harness must actually enqueue the job it measures"
    try:
        stagnant = 0
        seen = 0
        for _ in range(max_tries * 4):
            await worker.main()
            if attempts >= max_tries:
                break
            if attempts == seen:
                # A job that is NOT being retried leaves the queue immediately; waiting
                # for a ladder that does not exist is how this harness would hang.
                stagnant += 1
                if attempts and stagnant >= 2:
                    break
            else:
                stagnant, seen = 0, attempts
            await asyncio.sleep(0.05)
    finally:
        await worker.close()
        await pool.aclose()
    return attempts


async def _outbox_row(message_id: uuid.UUID) -> tuple[str, int, str | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT status, attempt_count, job_id FROM outbox_messages WHERE id = :id"),
                {"id": message_id},
            )
        ).first()
    assert row is not None
    return (row[0], row[1], row[2])


# ======================================================================= IDEMPOTENCY


async def test_the_same_key_twice_does_the_work_once() -> None:
    """The baseline promise: claim, complete, replay."""
    k = key("plain")
    body = rel.body_hash({"lead_id": "abc"})

    async with untenanted_session() as session:
        first = await rel.claim_idempotency(
            session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
        )
        assert first.state == "fresh"
        await rel.complete_idempotency(
            session, record_id=first.record_id, response_status=200, response_payload={"n": 1}
        )

    async with untenanted_session() as session:
        second = await rel.claim_idempotency(
            session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
        )
    assert second.state == "replay"
    assert second.record_id == first.record_id
    assert second.response_payload == {"n": 1}


async def test_a_different_body_under_the_same_key_is_never_a_replay() -> None:
    """A reused key with new content is a client bug, and answering it with the OLD
    response would silently drop the new request on the floor."""
    k = key("reused")
    async with untenanted_session() as session:
        claim = await rel.claim_idempotency(
            session,
            scope=SCOPE,
            route=ROUTE,
            method="POST",
            key=k,
            request_hash=rel.body_hash({"lead_id": "one"}),
        )
        await rel.complete_idempotency(
            session, record_id=claim.record_id, response_status=200, response_payload={"n": 1}
        )

    with pytest.raises(ProblemError) as caught:
        async with untenanted_session() as session:
            await rel.claim_idempotency(
                session,
                scope=SCOPE,
                route=ROUTE,
                method="POST",
                key=k,
                request_hash=rel.body_hash({"lead_id": "TWO"}),
            )
    assert caught.value.code == "idempotency_key_reused"


async def test_a_crash_between_claim_and_completion_does_not_poison_the_key() -> None:
    """THE property this table exists to have, and the one a naive implementation
    misses: a holder that died owns the key until the 24h TTL sweep.

    The claim commits (that is what makes it visible to the next attempt at all), the
    process then dies before `complete_idempotency` or `fail_idempotency` runs. Nothing
    will ever move that row again. Every retry the client makes for the next 24 hours
    gets `409 in flight` for a request that is not in flight and never will be.

    "In flight" has to mean "someone is plausibly still working on it". Past the lease
    it means "abandoned", and an abandoned claim must be re-claimable by CAS — exactly
    the treatment §4 already gives a FAILED record.
    """
    k = key("crashed")
    body = rel.body_hash({"lead_id": "abc"})

    async with untenanted_session() as session:
        claim = await rel.claim_idempotency(
            session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
        )
        assert claim.state == "fresh"
    # ...and here the worker is SIGKILLed. No complete, no fail.

    # Still in flight a second later: 409 is correct, the first attempt may be running.
    with pytest.raises(ProblemError) as caught:
        async with untenanted_session() as session:
            await rel.claim_idempotency(
                session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
            )
    assert caught.value.code == "idempotent_request_in_flight"

    # Half an hour later it is not in flight, it is dead. The retry must get to work.
    await _age_idempotency(k, minutes=30)
    async with untenanted_session() as session:
        retry = await rel.claim_idempotency(
            session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
        )
        assert retry.state == "fresh", "an abandoned claim must be re-claimable, not owned forever"
        await rel.complete_idempotency(
            session, record_id=retry.record_id, response_status=200, response_payload={"n": 2}
        )

    assert await _idempotency_row(k) == ("completed", 200, {"n": 2})


async def test_only_one_of_two_takeovers_of_an_abandoned_claim_wins() -> None:
    """The takeover is a race like every other claim: two retries arriving together
    must not BOTH be told to do the work."""
    k = key("takeover-race")
    body = rel.body_hash({"lead_id": "abc"})
    async with untenanted_session() as session:
        await rel.claim_idempotency(
            session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
        )
    await _age_idempotency(k, minutes=30)

    both_open = asyncio.Event()
    results: list[str] = []

    async def retrier(hold: bool) -> None:
        async with untenanted_session() as session:
            if not hold:
                await both_open.wait()
            try:
                claim = await rel.claim_idempotency(
                    session, scope=SCOPE, route=ROUTE, method="POST", key=k, request_hash=body
                )
                results.append(claim.state)
            except ProblemError as exc:
                results.append(exc.code)
            if hold:
                both_open.set()
                await asyncio.sleep(0.25)

    await asyncio.gather(retrier(True), retrier(False))
    assert results.count("fresh") == 1, f"exactly one takeover may win, got {results}"


# ============================================================================= INBOX


async def test_a_duplicate_delivery_is_one_row_and_one_unit_of_work() -> None:
    ek = key("dup")
    digest = rel.body_hash({"status": "completed"})

    async with untenanted_session() as session:
        first = await rel.claim_inbox_event(
            session, provider=PROVIDER, event_key=ek, payload_hash=digest, event_name="completed"
        )
        assert first.state == "claimed"
        await rel.mark_inbox_processed(session, row_id=first.row_id)

    async with untenanted_session() as session:
        second = await rel.claim_inbox_event(
            session, provider=PROVIDER, event_key=ek, payload_hash=digest, event_name="completed"
        )
    assert second.state == "duplicate"
    assert second.row_id == first.row_id

    rows = await _inbox_rows(ek)
    assert len(rows) == 1, "one event key is one row"
    assert rows[0][2] == 1, "and the retry is counted, not swallowed"


async def test_the_same_event_key_with_different_content_is_refused() -> None:
    ek = key("spoof")
    async with untenanted_session() as session:
        await rel.claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=ek,
            payload_hash=rel.body_hash({"status": "completed"}),
        )
    with pytest.raises(ProblemError) as caught:
        async with untenanted_session() as session:
            await rel.claim_inbox_event(
                session,
                provider=PROVIDER,
                event_key=ek,
                payload_hash=rel.body_hash({"status": "completed", "cost": 999}),
            )
    assert caught.value.code == "webhook_payload_mismatch"


async def test_two_simultaneous_deliveries_of_one_event_yield_one_claim() -> None:
    """The vendor's retry and the original can land on two workers at the same instant.
    Overlapping transactions, so the ON CONFLICT really is contended."""
    ek = key("simultaneous")
    digest = rel.body_hash({"status": "completed"})
    both_open = asyncio.Event()
    states: list[str] = []

    async def receiver(hold: bool) -> None:
        async with untenanted_session() as session:
            if not hold:
                await both_open.wait()
            claim = await rel.claim_inbox_event(
                session, provider=PROVIDER, event_key=ek, payload_hash=digest
            )
            states.append(claim.state)
            if hold:
                both_open.set()
                await asyncio.sleep(0.25)

    await asyncio.gather(receiver(True), receiver(False))
    assert states.count("claimed") == 1, f"exactly one claim, got {states}"
    assert len(await _inbox_rows(ek)) == 1


async def test_a_crashed_consumer_does_not_poison_an_event_key_forever() -> None:
    """`claim_inbox_event` already re-claims a FAILED row, because a failed attempt must
    not permanently own an at-most-once event. A CRASHED attempt is worse — it never
    reaches `mark_inbox_failed` at all, and the row sits in PROCESSING.

    This is live today, not hypothetical: `apps/api/tenancy/clerk_webhooks.py:159-183`
    commits the claim in one transaction, does the mirroring work OUTSIDE it, and has no
    failure path that marks the row failed. Any exception in `_mirror_user` leaves
    PROCESSING behind, and every Clerk retry of that svix-id is then answered
    "duplicate" — the user is never mirrored and nothing ever says so.
    """
    ek = key("crashed-consumer")
    digest = rel.body_hash({"type": "user.created"})

    async with untenanted_session() as session:
        first = await rel.claim_inbox_event(
            session, provider=PROVIDER, event_key=ek, payload_hash=digest
        )
        assert first.state == "claimed"
    # Consumer dies here: no mark_inbox_processed, no mark_inbox_failed.

    async with untenanted_session() as session:
        immediate = await rel.claim_inbox_event(
            session, provider=PROVIDER, event_key=ek, payload_hash=digest
        )
    assert immediate.state == "duplicate", "a retry seconds later is a genuine duplicate"

    await _age_inbox(ek, minutes=30)
    async with untenanted_session() as session:
        later = await rel.claim_inbox_event(
            session, provider=PROVIDER, event_key=ek, payload_hash=digest
        )
        assert later.state == "claimed", "an abandoned claim must be re-claimable"
        await rel.mark_inbox_processed(session, row_id=later.row_id)

    rows = await _inbox_rows(ek)
    assert len(rows) == 1 and rows[0][1] == "processed"


async def test_a_failed_event_is_reclaimable_but_only_by_one_retry() -> None:
    ek = key("failed-retry")
    digest = rel.body_hash({"status": "completed"})
    async with untenanted_session() as session:
        claim = await rel.claim_inbox_event(
            session, provider=PROVIDER, event_key=ek, payload_hash=digest
        )
        await rel.mark_inbox_failed(session, row_id=claim.row_id, error="boom")

    both_open = asyncio.Event()
    states: list[str] = []

    async def retrier(hold: bool) -> None:
        async with untenanted_session() as session:
            if not hold:
                await both_open.wait()
            again = await rel.claim_inbox_event(
                session, provider=PROVIDER, event_key=ek, payload_hash=digest
            )
            states.append(again.state)
            if hold:
                both_open.set()
                await asyncio.sleep(0.25)

    await asyncio.gather(retrier(True), retrier(False))
    assert states.count("claimed") == 1, f"a failed row is re-claimable exactly once, got {states}"


# ============================================================================ OUTBOX


async def _step_over_the_backoff(message_id: uuid.UUID) -> float | None:
    """Read the wait `mark_outbox_failed` gave this message, then skip it.

    Returns the wait in seconds, or `None` when the row holds no lease (the terminal
    branch clears it).

    WHY THE WAIT IS MEASURED AND THEN DISCARDED rather than slept through or mocked
    away. Slept through, the loop below takes 30+60+90+120 = five real minutes. Mocked —
    patching `now()`, or a fake clock — and the assertion stops being about the interval
    the production statement actually wrote, which is the only thing worth asserting
    here. So the row is read for the wait it was given, that number is returned to the
    caller to assert on, and only THEN is `locked_until` pushed into the past so the next
    claim can proceed. The fast-forward is the test's, the interval is the code's.

    `locked_until` is written with the OWNER role because `outbox_messages` is not
    tenant-scoped; `untenanted_session` is what every other helper in this file uses.
    """
    async with untenanted_session() as session:
        remaining = (
            await session.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM (locked_until - now())) "
                    "FROM outbox_messages WHERE id = :id AND locked_until IS NOT NULL"
                ),
                {"id": message_id},
            )
        ).scalar()
        if remaining is None:
            return None
        await session.execute(
            text(
                "UPDATE outbox_messages SET locked_until = now() - interval '1 second' "
                "WHERE id = :id"
            ),
            {"id": message_id},
        )
    return float(remaining)


async def test_a_permanently_failing_message_reaches_the_dlq() -> None:
    """Spinning forever is the failure mode: the retry budget has to actually end.

    Driven through the real claim so the attempt counter that ends the loop is the one
    the dispatcher actually writes, not one this test invents.

    **AND THE BUDGET IS SPENT OVER TIME, NOT INSTANTLY.** This loop used to claim the
    same row five times in a row with no wait between them, because `mark_outbox_failed`
    cleared `locked_until` on the retry branch — five attempts in as many statements,
    which in production was five attempts in fifty seconds against a receiver that might
    only be restarting. The retry branch holds the message now, so the loop has to step
    over each wait explicitly, and the wait it steps over is asserted rather than
    ignored: a backoff nobody checks is a backoff that can regress to zero and leave
    every test in this file still green.
    """
    marker = key("dlq")
    (message_id,) = await _seed_outbox(marker)

    ticks = 0
    for _ in range(rel.OUTBOX_MAX_ATTEMPTS * 3):
        async with untenanted_session() as session:
            mine = [
                m for m in await rel.claim_outbox_batch(session, limit=20) if m.id == message_id
            ]
            if not mine:
                break
            ticks += 1
            attempt = mine[0].attempt_count
            await rel.mark_outbox_failed(
                session,
                message_id=message_id,
                error="the receiver is gone",
                attempt_count=attempt,
            )
        waited = await _step_over_the_backoff(message_id)
        if attempt >= rel.OUTBOX_MAX_ATTEMPTS:
            # The terminal branch. A dead letter must hold NO lease, or `locked_until IS
            # NOT NULL` stops meaning "claimed right now, or abandoned".
            assert waited is None, f"a dead letter is holding a {waited}s lease"
        else:
            # The curve, against the attempt count the CLAIM returned — not against a
            # counter this test kept, so a concurrent dispatcher tick that bumped the row
            # cannot make this assert the wrong rung.
            expected = min(rel.OUTBOX_RETRY_BACKOFF_S * attempt, rel.OUTBOX_RETRY_BACKOFF_CAP_S)
            assert waited is not None, (
                f"attempt {attempt} of {rel.OUTBOX_MAX_ATTEMPTS} left the message "
                "immediately re-claimable — the whole budget burns in one dispatcher minute"
            )
            assert waited == pytest.approx(expected, abs=3), (
                f"attempt {attempt} waited {waited}s, not the ~{expected}s the backoff owes it"
            )

    status, attempts, _ = await _outbox_row(message_id)
    assert status == "failed", (
        f"a message that never publishes must end up in the DLQ, not retry forever "
        f"(still {status!r} after {ticks} dispatcher ticks)"
    )
    # `>=` rather than `==`: a concurrent suite's dispatcher tick may also have claimed
    # this row and bumped the counter. What must hold is that the budget is finite.
    assert attempts >= rel.OUTBOX_MAX_ATTEMPTS
    # The loop must have actually run — an empty loop would satisfy every assertion above
    # it by never executing one, which is how a rewritten harness asserts nothing.
    assert ticks >= 2, f"only {ticks} tick(s) ran, so the backoff assertions never fired"
    await _retire(message_id)


async def test_the_dlq_boundary_is_exactly_the_documented_budget() -> None:
    """The off-by-one that would make the DLQ unreachable (or reached a try early),
    asserted without touching any shared ordering."""
    below = (await _seed_outbox(key("boundary-below")))[0]
    at = (await _seed_outbox(key("boundary-at")))[0]

    async with untenanted_session() as session:
        await rel.mark_outbox_failed(
            session,
            message_id=below,
            error="still has budget",
            attempt_count=rel.OUTBOX_MAX_ATTEMPTS - 1,
        )
        await rel.mark_outbox_failed(
            session, message_id=at, error="budget spent", attempt_count=rel.OUTBOX_MAX_ATTEMPTS
        )

    assert (await _outbox_row(below))[0] == "pending", "one try short of the ceiling still retries"
    assert (await _outbox_row(at))[0] == "failed", "at the ceiling it is a dead letter"
    # The two branches differ in the LEASE as well as in the status, and the pair is
    # asserted together because that is the invariant: below the ceiling the message is
    # held for its backoff, at the ceiling a dead letter holds nothing.
    assert await _step_over_the_backoff(below) is not None, (
        "a retryable failure left the message immediately re-claimable"
    )
    assert await _step_over_the_backoff(at) is None, "a dead letter is holding a lease"
    await _retire(below, at)


async def test_a_failure_report_cannot_resurrect_a_published_message() -> None:
    """Every claim in this codebase is a conditional UPDATE whose guard is in the WHERE
    clause (§5). `mark_outbox_failed` is the one status transition written without a
    guard, so it will happily drag a PUBLISHED row — whose job is already queued and may
    already have run — back to PENDING, where the next dispatcher tick publishes it
    again. For `deliver_outbound_webhook` that is a duplicate POST into a client's CRM.
    """
    marker = key("resurrect")
    (message_id,) = await _seed_outbox(marker)

    async with untenanted_session() as session:
        await rel.mark_outbox_published(session, message_id=message_id, job_id="job-1")
    assert (await _outbox_row(message_id))[0] == "published"

    async with untenanted_session() as session:
        await rel.mark_outbox_failed(
            session, message_id=message_id, error="a late report from a lost retry", attempt_count=1
        )

    status, _, job_id = await _outbox_row(message_id)
    await _retire(message_id)
    assert status == "published", f"a published message must stay published, got {status!r}"
    assert job_id == "job-1"


async def test_replaying_dead_letters_only_touches_dead_letters() -> None:
    """The ops replay must be a CAS like everything else.

    `replay_dead_letters` filters on `status = 'failed'` in a SUBQUERY and then updates
    by id with no guard of its own. Under READ COMMITTED the outer UPDATE blocks on a
    concurrent writer's row lock and, when it wakes, re-checks only its own WHERE — which
    is just `id IN (...)`. So a message that was dead when the subquery ran and is
    PUBLISHED by the time the lock is granted gets flipped back to PENDING and delivered
    a second time.
    """
    marker = key("replay-race")
    (message_id,) = await _seed_outbox(marker, status="failed")
    publisher_locked = asyncio.Event()
    replay_started = asyncio.Event()

    async def publisher() -> None:
        async with untenanted_session() as session:
            # An ops "this one actually went out, close it" write — any writer to the row
            # would do; what matters is that it holds the lock while the replay runs.
            await session.execute(
                text(
                    "UPDATE outbox_messages SET status = 'published', job_id = 'job-x', "
                    "published_at = now(), updated_at = now() WHERE id = :id"
                ),
                {"id": message_id},
            )
            publisher_locked.set()
            await replay_started.wait()
            await asyncio.sleep(0.25)

    async def replayer() -> int:
        await publisher_locked.wait()
        async with untenanted_session() as session:
            task = asyncio.create_task(rel.replay_dead_letters(session, limit=50))
            await asyncio.sleep(0.1)  # let the UPDATE reach the lock and block
            replay_started.set()
            return await task

    _, replayed = await asyncio.gather(publisher(), replayer())
    status, _, _ = await _outbox_row(message_id)
    await _retire(message_id)
    assert status == "published", (
        f"replay resurrected a message that was published while it waited (status={status!r}, "
        f"replayed={replayed})"
    )


async def test_the_dead_letter_replay_honours_its_limit() -> None:
    """Same regression shape as the batch claim: `LIMIT` inside `WHERE id IN (SELECT ...)`
    with a non-total ordering. The rows below all share `created_at` to the microsecond
    because they are written in one transaction."""
    marker = key("replay-limit")
    ids = await _seed_outbox(marker, count=12, status="failed")

    async with untenanted_session() as session:
        replayed = await rel.replay_dead_letters(session, limit=5)

    async with untenanted_session() as session:
        flipped = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE id = ANY(:ids) "
                    "AND status = 'pending'"
                ),
                {"ids": list(ids)},
            )
        ).scalar()
    await _retire(*ids)
    assert replayed <= 5, f"the limit is a limit, it reported {replayed}"
    assert flipped <= 5, f"the limit is a limit, it flipped {flipped} rows"


async def test_two_dispatchers_never_claim_the_same_outbox_row() -> None:
    """Restated here against run-scoped rows so it is provable in a shared database."""
    marker = key("claim-race")
    ids = set(await _seed_outbox(marker, count=6))
    both_open = asyncio.Event()

    async def claimer(hold: bool) -> set[uuid.UUID]:
        async with untenanted_session() as session:
            if not hold:
                await both_open.wait()
            batch = await rel.claim_outbox_batch(session, limit=3)
            mine = {m.id for m in batch} & ids
            if hold:
                both_open.set()
                await asyncio.sleep(0.3)
            return mine

    left, right = await asyncio.gather(claimer(True), claimer(False))
    await _retire(*ids)
    assert not (left & right), "overlapping dispatchers took the same message"
    assert left and right, "SKIP LOCKED must hand the second dispatcher DIFFERENT work"


# ============================================================================== REDIS


async def test_enqueueing_against_a_dead_redis_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """`enqueue` sits inside the voice-runtime webhook handler, whose ack budget is 500ms
    (hard rule 3, alerted on at `webhook_routes.py:143`). `arq.create_pool` defaults to
    `conn_retries=5` with a 1s delay between attempts, so an unreachable Redis makes that
    handler sit for ~5 seconds before it can even fail — an order of magnitude past the
    budget, with a connection and a worker slot held the whole time. A dependency that is
    down must be reported as down promptly, not waited for.
    """
    import apps.api.core.queue as queue_mod
    from arq.connections import RedisSettings

    saved = queue_mod._pool
    queue_mod._pool = None
    # Port 1 is reserved and never listening: connections are refused immediately, so
    # everything measured below is retry/backoff, not network latency.
    monkeypatch.setattr(
        queue_mod, "redis_settings", lambda: RedisSettings(host="127.0.0.1", port=1)
    )
    try:
        started = time.perf_counter()
        # RedisError, OSError — the point is only that it gives up, and how fast.
        with pytest.raises((RedisError, OSError)):
            await queue_mod.enqueue("notify_hot_lead", {"x": 1}, job_id=key("dead-redis"))
        elapsed = time.perf_counter() - started
    finally:
        queue_mod._pool = saved

    assert elapsed < 1.5, f"a refused Redis took {elapsed:.1f}s to report itself down"


async def test_a_cold_start_burst_builds_exactly_one_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cold voice-runtime meeting a wave of webhooks: every concurrent handler finds
    `_pool is None` and, without a single-flight guard, builds its own. All but the last
    are then unreachable — connections open, no reference left for `close_queue`."""
    import apps.api.core.queue as queue_mod

    saved = queue_mod._pool
    queue_mod._pool = None
    built: list[Any] = []
    real = queue_mod.create_pool

    async def counting_create_pool(settings: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.05)  # a connect takes time; that is where the race lives
        pool = await real(settings, **kwargs)
        built.append(pool)
        return pool

    monkeypatch.setattr(queue_mod, "create_pool", counting_create_pool)
    try:
        await asyncio.gather(*(queue_mod.get_queue() for _ in range(6)))
        assert len(built) == 1, (
            f"a cold-start burst built {len(built)} pools and leaked {len(built) - 1}"
        )
    finally:
        for pool in built:
            await pool.aclose()
        queue_mod._pool = saved


async def test_a_raising_job_is_actually_retried_by_a_real_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry ladder every worker in this repo is written against.

    `WORKER_MAX_TRIES` and `WorkerSettings.max_tries` promise three attempts, and
    `apps/workers/outbound_webhooks.py` is built on that promise: it raises to ask for a
    retry and treats `job_try == MAX_ATTEMPTS` as the last one. But arq 0.28 only retries
    for `arq.Retry`, `RetryJob` or `CancelledError` — a plain exception sets `finish=True`
    and the job leaves the queue after ONE attempt (`arq/worker.py`, the `else` branch of
    `run_job`'s handler). So the ladder is imaginary, the last-try branch is unreachable,
    and `outbound_webhook_exhausted` — the alert that tells us a client's integration has
    gone stale — can never fire.

    This runs a REAL worker over the REAL job function and counts real attempts. Nothing
    is injected into `ctx`: the number asserted here is the one arq actually produced.
    """
    from apps.api.core.queue import WORKER_MAX_TRIES, redis_settings
    from apps.api.integrations import service as integrations
    from apps.workers import outbound_webhooks

    tries: list[int] = []

    async def _endpoint(session: Any, endpoint_id: uuid.UUID) -> dict[str, Any]:
        return {"url": "https://down.example/hook", "secret": "s", "mapping": {}}

    async def _refuse(**kwargs: Any) -> integrations.DeliveryResult:
        return integrations.DeliveryResult(delivered=False, status_code=503, error="HTTP 503")

    async def _record(session: Any, **kwargs: Any) -> None:
        tries.append(int(kwargs["attempts"]))

    monkeypatch.setattr(integrations, "load_endpoint", _endpoint)
    monkeypatch.setattr(integrations, "deliver", _refuse)
    monkeypatch.setattr(integrations, "record_delivery", _record)
    # Real backoff is minutes; the ladder's SHAPE is what is under test, not its pace.
    monkeypatch.setattr(outbound_webhooks, "RETRY_BACKOFF_S", (0.02, 0.02))
    monkeypatch.setattr(outbound_webhooks, "alert", lambda *a, **k: None)

    attempts = await _run_one_job_to_exhaustion(
        outbound_webhooks.deliver_outbound_webhook,
        {
            "tenant_id": str(uuid7()),
            "endpoint_id": str(uuid7()),
            "event": "lead.created",
            "data": {"lead_id": "1"},
            "delivery_id": str(uuid7()),
        },
        max_tries=WORKER_MAX_TRIES,
        settings=redis_settings(),
    )

    assert attempts == WORKER_MAX_TRIES, (
        f"a transient 503 must be retried up to the budget; the worker ran it {attempts} time(s)"
    )
    assert tries == list(range(1, WORKER_MAX_TRIES + 1)), (
        f"and every attempt records its real try number, got {tries}"
    )


async def test_a_permanent_rejection_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of a retry policy: knowing what NOT to retry.

    A 400 from a client's endpoint is a contract mismatch — the same signed body will be
    rejected identically in thirty seconds and in two minutes. Retrying it delays the
    delivery row's verdict, triples the load on an endpoint that is already unhappy, and
    tells the client's logs a story about our reliability rather than their config.
    """
    from apps.api.core.queue import WORKER_MAX_TRIES, redis_settings
    from apps.api.integrations import service as integrations
    from apps.workers import outbound_webhooks

    fired: list[str] = []

    async def _endpoint(session: Any, endpoint_id: uuid.UUID) -> dict[str, Any]:
        return {"url": "https://picky.example/hook", "secret": "s", "mapping": {}}

    async def _reject(**kwargs: Any) -> integrations.DeliveryResult:
        return integrations.DeliveryResult(delivered=False, status_code=400, error="HTTP 400")

    async def _record(session: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(integrations, "load_endpoint", _endpoint)
    monkeypatch.setattr(integrations, "deliver", _reject)
    monkeypatch.setattr(integrations, "record_delivery", _record)
    monkeypatch.setattr(outbound_webhooks, "RETRY_BACKOFF_S", (0.02, 0.02))
    monkeypatch.setattr(outbound_webhooks, "alert", lambda stage, code, **kw: fired.append(code))

    attempts = await _run_one_job_to_exhaustion(
        outbound_webhooks.deliver_outbound_webhook,
        {
            "tenant_id": str(uuid7()),
            "endpoint_id": str(uuid7()),
            "event": "lead.created",
            "data": {"lead_id": "1"},
            "delivery_id": str(uuid7()),
        },
        max_tries=WORKER_MAX_TRIES,
        settings=redis_settings(),
    )

    assert attempts == 1, f"a 400 is not a blip; it was attempted {attempts} times"
    assert fired, "and giving up on a client's endpoint must still be said out loud"


async def test_a_lost_recording_copy_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """`StorageUnavailableError` exists, in its own words, "so the ARQ retry ladder can do
    its job" (`apps/workers/storage.py:37-39`), and the post-call pipeline re-raises it
    with the comment "Re-raise so ARQ retries". Under arq 0.28 neither is true.

    This one is the most expensive to get wrong: the recording copy runs FIRST precisely
    because Bolna's URLs have no documented expiry — a copy we do not retry is a call
    recording that is simply gone, against a 90-day TRAI floor.
    """
    from apps.api.core.queue import WORKER_MAX_TRIES, redis_settings
    from apps.workers.storage import StorageUnavailableError

    seen: list[int] = []

    async def copy_the_recording(ctx: dict[str, Any]) -> str:
        seen.append(int(ctx["job_try"]))
        # Real defer is 30s; the ladder's SHAPE is under test, not its pace.
        raise StorageUnavailableError("recording fetch failed: ConnectTimeout", defer_s=0.02)

    attempts = await _run_one_job_to_exhaustion(
        copy_the_recording, None, max_tries=WORKER_MAX_TRIES, settings=redis_settings()
    )
    assert attempts == WORKER_MAX_TRIES, (
        f"a recording copy that failed on a blip must be retried, not dropped after {attempts}"
    )


async def test_a_failed_pool_build_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Redis blip must not leave the process permanently unable to enqueue."""
    import apps.api.core.queue as queue_mod
    from arq.connections import RedisSettings

    saved = queue_mod._pool
    queue_mod._pool = None
    monkeypatch.setattr(
        queue_mod, "redis_settings", lambda: RedisSettings(host="127.0.0.1", port=1)
    )
    try:
        with pytest.raises((RedisError, OSError)):
            await queue_mod.get_queue()
        assert queue_mod._pool is None, "a pool that never connected must not be cached"
    finally:
        queue_mod._pool = saved
