"""P6.7: the four "have we already promised this?" probes, and the tables nothing pruned.

THE DEFECT. `outbox_messages` has one index — `(status, created_at)` — and four call
sites asked `WHERE job = :job AND payload @> :matcher`, which neither that index nor any
other could answer. Every one was a sequential scan of a table **nothing ever deleted
from**, and the worst of them ran twice per completed call, under `lock_call_writes`, on
the 2-minute SLO path, while `dispatch_outbox` contended for the same rows every ten
seconds.

The fix is two-shaped, and this file tests the BEHAVIOUR of each rather than the SQL:

  * `calls.crm_notified_at` for the CRM fan-out, because that side effect writes one
    outbox row per subscribed endpoint and so has no single row to key on;
  * `enqueue_outbox_once` + a partial UNIQUE index for the three that write exactly one
    row — which is strictly stronger than the indexed probe the finding asked for,
    because once-only stops depending on the caller having taken a lock first. The third
    test is the one that would not have passed under the old shape at all.

And the pruning half, which is a compliance fix wearing a performance fix's clothes: an
outbox payload carries a lead's name, number and call summary, so an outbox nothing
prunes is a copy of tenant personal data sitting outside every retention policy a tenant
can set. The last two tests pin what the sweep must NEVER delete — the DLQ an operator
replays from, and the events a client can still re-drive.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import enqueue_outbox, enqueue_outbox_once
from apps.workers import retention
from sqlalchemy import text

RUN = uuid.uuid4().hex[:12]


@pytest.fixture(scope="module", autouse=True)
def _reclaim_seeded_rows() -> Iterator[None]:
    """Delete every row this module seeds, once the module is done.

    **THIS FIXTURE EXISTS BECAUSE ITS ABSENCE BROKE ANOTHER SUITE.** Two tests below seed
    outbox rows aged `RELIABILITY_PRUNE_AFTER * 10` — 900 days — to prove the sweep will
    NOT delete a `failed` or `pending` row however old it is. That assertion is right and
    the rows are the point of it. Leaving them behind is not: `claim_outbox_batch` is
    oldest-first over the WHOLE table, so a 900-day-old pending row sits permanently at
    the head of every dispatcher's queue, ahead of the 30-day backdating that
    `reliability_audit_test._seed_outbox` uses precisely so its own rows come first.

    What that cost, measured rather than reasoned: after several runs of this file,
    `test_two_dispatchers_never_claim_the_same_outbox_row` began failing — both claimers
    took THIS module's ancient leftovers, so neither saw any of its own six rows and
    `left` came back empty. Thirty orphans had accumulated. The failure named SKIP LOCKED,
    which was working correctly the whole time.

    Module-scoped rather than per-test because the tests assert across each other's rows
    (the prune runs globally, so a row seeded by one test must survive another's sweep),
    and the same shape `reliability_audit_test` already documents: "the module fixture
    deletes them again as soon as the file is done."
    """
    yield
    asyncio.run(_delete_seeded_rows())


async def _delete_seeded_rows() -> None:
    """Every shape this module inserts, matched by its run-scoped marker.

    Enumerated rather than "delete where created_at is absurd": another suite is entitled
    to seed an old row too, and a teardown that reaches beyond its own rows is the defect
    it is cleaning up after.
    """
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE dedupe_key LIKE :keyed OR job = ANY(:jobs)"),
            {"keyed": f"test-{RUN}:%", "jobs": [f"fanout-{RUN}", f"legacy-shape-{RUN}"]},
        )
        await session.execute(
            text("DELETE FROM webhook_inbox_events WHERE provider = :provider"),
            {"provider": f"probe-{RUN}"},
        )


def _key(suffix: str) -> str:
    """Namespaced per run: this suite shares a database with every other suite, and a
    fixed key would collide with a previous run's surviving row rather than with a
    duplicate this test wrote."""
    return f"test-{RUN}:{suffix}"


async def _outbox_row_count(dedupe_key: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE dedupe_key = :k"),
                    {"k": dedupe_key},
                )
            ).scalar_one()
        )


# --- the promise happens once -------------------------------------------------


@pytest.mark.asyncio
async def test_the_same_promise_twice_writes_one_row_and_says_so() -> None:
    """The sequential case: the second call returns None rather than a second id."""
    key = _key("once")
    async with untenanted_session() as session:
        first = await enqueue_outbox_once(
            session, job="notify_hot_lead", payload={"n": 1}, dedupe_key=key
        )
        second = await enqueue_outbox_once(
            session, job="notify_hot_lead", payload={"n": 2}, dedupe_key=key
        )
    assert first is not None
    assert second is None, "a repeat promise must be refused, not queued a second time"
    assert await _outbox_row_count(key) == 1


@pytest.mark.asyncio
async def test_two_racing_promises_still_write_one_row() -> None:
    """**The claim the old shape could not make.** `SELECT … LIMIT 1` then INSERT is a
    check-then-write: two transactions both read "nothing yet" and both insert, and the
    only thing that ever prevented it was every caller remembering to take
    `lock_call_writes` first — which `enqueue_campaign_escalation` never did, having no
    call to lock.

    THE RACE IS FORCED, NOT HOPED FOR. Two separate sessions, each opened and then held
    at a barrier, so both transactions are demonstrably in flight before either writes —
    `asyncio.gather` alone would let the first finish before the second starts, and a
    concurrent test that never actually raced is the commonest way to be fooled (the
    argument `postcall_concurrency_test` makes at length). The negative control below
    runs the OLD shape through this same harness and shows it writing two rows, which is
    what makes the harness evidence rather than decoration.
    """
    key = _key("race")
    barrier = asyncio.Barrier(2)

    async def _promise(n: int) -> object:
        async with untenanted_session() as session:
            await session.execute(text("SELECT 1"))  # the transaction is now really open
            await barrier.wait()
            return await enqueue_outbox_once(
                session, job="notify_hot_lead", payload={"n": n}, dedupe_key=key
            )

    results = await asyncio.gather(_promise(1), _promise(2))
    assert sum(1 for r in results if r is not None) == 1, results
    assert await _outbox_row_count(key) == 1


@pytest.mark.asyncio
async def test_negative_control_the_probe_then_insert_shape_writes_two() -> None:
    """The harness above, running what the four call sites used to do.

    This is the defect itself, reproduced: probe the outbox by payload containment, see
    nothing, insert. Under the same forced race both promises are made, and the client
    is told twice about one lead under two delivery ids their receiver cannot collapse.

    It asserts TWO rather than one so it fails if the race stops being real — if this
    ever reports 1, the test above is proving nothing and this is where that shows up.
    """
    job = f"legacy-shape-{RUN}"
    matcher = json.dumps({"lead": RUN})
    barrier = asyncio.Barrier(2)

    async def _promise(n: int) -> None:
        async with untenanted_session() as session:
            existing = (
                await session.execute(
                    text(
                        "SELECT 1 FROM outbox_messages WHERE job = :job "
                        "AND payload @> CAST(:matcher AS jsonb) LIMIT 1"
                    ),
                    {"job": job, "matcher": matcher},
                )
            ).first()
            await barrier.wait()
            if existing is None:
                await enqueue_outbox(session, job=job, payload={"lead": RUN, "n": n})

    await asyncio.gather(_promise(1), _promise(2))
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE job = :j"), {"j": job}
            )
        ).scalar_one()
    assert count == 2, (
        "the old check-then-write must double-write under a real race; a 1 here means "
        "the harness is not racing and the test above proves nothing"
    )


@pytest.mark.asyncio
async def test_an_unkeyed_row_is_never_deduped_against_another() -> None:
    """The partial index must not collapse the fan-out. `enqueue_outbox` writes NULL,
    and n NULLs are n distinct rows — which is the whole reason the index is partial
    rather than a NOT NULL column with a synthesised key per row.
    """
    job = f"fanout-{RUN}"
    async with untenanted_session() as session:
        await enqueue_outbox(session, job=job, payload={"endpoint": 1})
        await enqueue_outbox(session, job=job, payload={"endpoint": 2})
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE job = :j AND dedupe_key IS NULL"),
                {"j": job},
            )
        ).scalar_one()
    assert count == 2, "one row per subscribed endpoint; those are not duplicates"


# --- the prune sweep ----------------------------------------------------------


async def _seed_outbox(*, status: str, age: timedelta, dedupe_key: str) -> uuid.UUID:
    """One outbox row with an explicit age. `created_at` is written directly because the
    sweep's predicate is about age, and waiting 90 days is not a test."""
    row_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, dedupe_key, status, "
                "attempt_count, created_at, updated_at) VALUES (:id, 'default', 'prune_probe', "
                "CAST(:payload AS jsonb), :k, :status, 0, :at, :at)"
            ),
            {
                "id": row_id,
                "payload": json.dumps({"probe": RUN}),
                "k": dedupe_key,
                "status": status,
                "at": datetime.now(UTC) - age,
            },
        )
    return row_id


async def _survives(row_id: uuid.UUID) -> bool:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text("SELECT 1 FROM outbox_messages WHERE id = :id"), {"id": row_id}
            )
        ).first() is not None


@pytest.mark.asyncio
async def test_the_sweep_forgets_a_published_row_past_the_floor() -> None:
    old = await _seed_outbox(
        status="published",
        age=retention.RELIABILITY_PRUNE_AFTER + timedelta(days=1),
        dedupe_key=_key("prune-old"),
    )
    young = await _seed_outbox(
        status="published", age=timedelta(days=1), dedupe_key=_key("prune-young")
    )
    await retention.prune_reliability_tables({})
    assert not await _survives(old), "a published row past the floor is what the sweep is for"
    assert await _survives(young), "the floor is not decoration"


@pytest.mark.asyncio
async def test_the_sweep_never_touches_the_dead_letter_queue() -> None:
    """`status = 'failed'` IS the DLQ an operator replays from (`ops/routes.py`). Deleting
    one is not forgetting a completed side effect, it is losing an uncompleted one — and
    the age makes no difference, which is the point of asserting on a very old row."""
    ancient = retention.RELIABILITY_PRUNE_AFTER * 10
    dlq = await _seed_outbox(status="failed", age=ancient, dedupe_key=_key("dlq"))
    pending = await _seed_outbox(status="pending", age=ancient, dedupe_key=_key("pending"))
    await retention.prune_reliability_tables({})
    assert await _survives(dlq), "a failed row is work owed, however old"
    assert await _survives(pending), "a pending row is work not yet done"


@pytest.mark.asyncio
async def test_an_unprocessed_inbox_event_survives_however_old() -> None:
    """The inbox twin of the rule above. A `failed` row is what the client's own ingest
    activity screen offers a re-drive from, so its age is not a reason to lose it."""
    ancient = datetime.now(UTC) - retention.RELIABILITY_PRUNE_AFTER * 10
    processed, failed = uuid.uuid4(), uuid.uuid4()
    async with untenanted_session() as session:
        for row_id, status in ((processed, "processed"), (failed, "failed")):
            await session.execute(
                text(
                    "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, "
                    "status, duplicate_count, created_at, updated_at) VALUES (:id, :p, :k, "
                    "'deadbeef', :status, 0, :at, :at)"
                ),
                {
                    "id": row_id,
                    "p": f"probe-{RUN}",
                    "k": f"{RUN}-{status}",
                    "status": status,
                    "at": ancient,
                },
            )
    await retention.prune_reliability_tables({})
    async with untenanted_session() as session:
        surviving = {
            r[0]
            for r in (
                await session.execute(
                    text("SELECT id FROM webhook_inbox_events WHERE provider = :p"),
                    {"p": f"probe-{RUN}"},
                )
            ).all()
        }
    assert processed not in surviving, "a processed event's only remaining job is dedupe"
    assert failed in surviving, "a failed event is one the client can still re-drive"
