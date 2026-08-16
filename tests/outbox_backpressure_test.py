"""The outbox dispatcher under a failing QUEUE, as opposed to a failing message.

`dispatch_outbox` had one `except`, so it had one verdict: charge the message an attempt
and, at the ceiling, dead-letter it. That is the right answer for a poisoned payload and
the wrong one for Redis being down, and the arithmetic is what makes it matter — the
cron ticks every 10 seconds (`WorkerSettings.CRON_JOBS`) and `OUTBOX_MAX_ATTEMPTS` is 5,
so **fifty seconds of an unreachable queue dead-letters the entire outbox**. Fifty
seconds is shorter than a Redis restart. Nothing was wrong with any of those messages,
and the only way back is `POST /v1/ops/outbox/replay` — a step-up-confirmed operator
action, at whatever hour the outage happened.

Every other retry ladder in this repo already backs off for exactly this reason
(`pipeline.RETRY_BACKOFF_S`, `outbound_webhooks.RETRY_BACKOFF_S`, both `(30, 120)` with
the same "a receiver that is restarting wants half a minute" argument). The dispatcher —
the fastest loop of the three — had none.

So a systemic failure now stops the tick and hands the claim back with a wait
(`defer_outbox_claim`), and a poisoned message is unchanged. The tests below are both
halves: the outage must not dead-letter, and the fix must not have bought that by making
the DLQ unreachable.

Cross-suite courtesy: `outbox_messages` is platform-wide, so every row here is backdated
far enough to lead the oldest-first claim, marked with a run id, and deleted on the way
out. The claim is filtered to this file's own rows — what is under test is the LOOP's
failure classification, and `reliability_audit_test` is where the claim itself is raced.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability import service as rel
from apps.workers import dispatcher
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text

RUN = uuid.uuid4().hex[:12]
PROBE_JOB = "cron:outbox_backpressure_probe"


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE payload->>'marker' LIKE :m"),
            {"m": f"%{RUN}"},
        )


async def _seed(count: int) -> list[UUID]:
    """`count` pending rows, backdated so they lead the oldest-first claim."""
    ids: list[UUID] = []
    async with untenanted_session() as session:
        for _ in range(count):
            message_id = uuid7()
            ids.append(message_id)
            await session.execute(
                text(
                    "INSERT INTO outbox_messages (id, queue, job, payload, status, "
                    "attempt_count, created_at, updated_at) VALUES (:id, 'default', :job, "
                    "CAST(:payload AS jsonb), 'pending', 0, now() - interval '20 years', now())"
                ),
                {
                    "id": message_id,
                    "job": PROBE_JOB,
                    "payload": json.dumps({"marker": f"backpressure-{RUN}"}),
                },
            )
    return ids


async def _rows(ids: list[UUID]) -> dict[UUID, tuple[str, int, bool, str | None]]:
    """(status, attempt_count, is_deferred, last_error) per message."""
    async with untenanted_session() as session:
        found = (
            await session.execute(
                text(
                    "SELECT id, status, attempt_count, "
                    "  (locked_until IS NOT NULL AND locked_until > now()) AS deferred, "
                    "  last_error "
                    "FROM outbox_messages WHERE id = ANY(:ids)"
                ),
                {"ids": ids},
            )
        ).all()
    return {row[0]: (str(row[1]), int(row[2]), bool(row[3]), row[4]) for row in found}


async def _step_over_the_backoff(message_id: UUID) -> float | None:
    """Read the wait `mark_outbox_failed` gave this message, then skip it.

    Returns the wait in seconds, or `None` when the row holds no lease. Same helper, same
    argument as `reliability_audit_test`'s: sleeping it out costs five real minutes and
    mocking the clock would stop the assertion being about the interval the production
    statement actually wrote. So the wait is measured, handed back to the caller to
    assert on, and only then pushed into the past.
    """
    async with untenanted_session() as session:
        remaining = (
            await session.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM (locked_until - now())) FROM outbox_messages "
                    "WHERE id = :id AND locked_until IS NOT NULL AND locked_until > now()"
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


@pytest.fixture
def only_mine(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Run the REAL claim, then hand the loop only this file's rows.

    The claim has to be real — `attempt_count` is what the DLQ boundary is measured in,
    and a stubbed claim would let this file assert against a counter it wrote itself.
    Filtering afterwards is what keeps a dispatcher test from publishing another suite's
    pending notifications as a side effect; their rows keep the two-minute lease the
    claim gave them and are picked up again by the next real tick.
    """
    real = rel.claim_outbox_batch

    def _install(ids: list[UUID]) -> None:
        wanted = set(ids)

        async def _claim(session: Any, *, limit: int = rel.OUTBOX_BATCH) -> list[Any]:
            return [row for row in await real(session, limit=limit) if row.id in wanted]

        monkeypatch.setattr(dispatcher, "claim_outbox_batch", _claim)

    return _install


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    fired: list[tuple[str, str, str | None]] = []

    def _alert(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, detail))

    monkeypatch.setattr(dispatcher, "alert", _alert)
    return fired


def _queue_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _refuse(*args: Any, **kwargs: Any) -> str | None:
        raise RedisConnectionError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(dispatcher, "enqueue", _refuse)


# ================================================== 1. an outage is not a poison message


async def test_an_unreachable_queue_does_not_dead_letter_the_outbox(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """THE DEFECT. Six ticks of an unreachable Redis — a minute of downtime at the
    dispatcher's real cadence, one tick past the whole attempt budget.

    Every one of these messages is a client's hot-lead notification or a CRM delivery
    that was committed in the same transaction as the lead itself. Dead-lettering them
    for an outage nobody could have prevented turns a Redis restart into an operator
    replay, and the replay is the only thing that gets those clients their leads.
    """
    ids = await _seed(3)
    only_mine(ids)
    _queue_is_down(monkeypatch)

    for _ in range(rel.OUTBOX_MAX_ATTEMPTS + 1):
        assert await dispatcher.dispatch_outbox({}) == "published=0"

    rows = await _rows(ids)
    assert [status for status, *_ in rows.values()] == ["pending"] * 3, (
        f"an unreachable queue dead-lettered messages that were never wrong: {rows}"
    )
    assert all(deferred for _s, _a, deferred, _e in rows.values()), (
        "a message handed back with no wait is re-claimed ten seconds later, which is "
        "how the budget is spent inside a minute"
    )
    assert all(attempts < rel.OUTBOX_MAX_ATTEMPTS for _s, attempts, *_ in rows.values()), rows


async def test_the_outage_stops_the_tick_instead_of_charging_every_message(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """Nothing after the first systemic failure would fare differently, so trying the
    rest spends forty-nine more attempts to learn what the first one said — and, on a
    full batch, is forty-nine more connection attempts against a host that is already
    refusing them."""
    ids = await _seed(4)
    only_mine(ids)
    attempted: list[str] = []

    async def _refuse(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
        attempted.append(str(job_id))
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(dispatcher, "enqueue", _refuse)

    await dispatcher.dispatch_outbox({})

    assert len(attempted) == 1, f"the tick tried {len(attempted)} messages against a dead queue"
    rows = await _rows(ids)
    assert all(deferred for _s, _a, deferred, _e in rows.values()), (
        "the messages the tick never reached must be handed back too, not left leased"
    )


async def test_the_outage_is_reported_once_and_names_what_it_did(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """An operator reading this alert needs to know the outbox is safe, or they will
    reach for the replay button during the outage — which enqueues nothing and writes an
    `ops.outbox_replay` audit row for a redelivery that never happened."""
    ids = await _seed(2)
    only_mine(ids)
    _queue_is_down(monkeypatch)

    await dispatcher.dispatch_outbox({})

    outage = [entry for entry in alerts if entry[1] == "outbox_queue_unreachable"]
    assert len(outage) == 1, f"one incident, one notice per tick; got {alerts}"
    stage, _code, detail = outage[0]
    assert stage == "OUTBOX_DISPATCH"
    assert detail is not None
    assert "deferred, not dead-lettered" in detail, detail
    assert "2 message(s)" in detail, detail
    assert not [entry for entry in alerts if entry[1] == "outbox_dead_letter"], (
        "an outage must not be announced as a dead letter"
    )


async def test_the_deferred_messages_go_out_when_the_queue_comes_back(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """The half that makes the deferral a delay rather than a hiding place: the whole
    point is that the client still gets the notification."""
    ids = await _seed(2)
    only_mine(ids)
    _queue_is_down(monkeypatch)
    await dispatcher.dispatch_outbox({})
    assert all(status == "pending" for status, *_ in (await _rows(ids)).values())

    # The wait elapses and Redis answers again.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE outbox_messages SET locked_until = now() - interval '1 second' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    published: list[str] = []

    async def _accept(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
        published.append(str(job_id))
        return job_id

    monkeypatch.setattr(dispatcher, "enqueue", _accept)

    await dispatcher.dispatch_outbox({})

    rows = await _rows(ids)
    assert [status for status, *_ in rows.values()] == ["published"] * 2, rows
    assert len(published) == 2


# =========================================== 2. and the DLQ is still reachable for poison


async def test_a_poisoned_payload_still_walks_to_the_dlq(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """The counterweight. If every publish failure were treated as an outage, a message
    the queue can never accept would be retried forever and the DLQ — and the ops replay
    screen built on it — would stand for nothing.

    The distinction is the exception type, and it is not a guess: `RedisError, OSError`
    is what `apps/api/core/queue.py`'s callers already treat as "the queue is down"
    (`reliability_audit_test::test_enqueueing_against_a_dead_redis_fails_fast` pins that
    pair). Anything else is the message.

    **THE WALK TAKES TIME NOW, and the loop has to say so.** `mark_outbox_failed` used to
    clear `locked_until` on the retry branch, so five ticks back to back spent the whole
    budget — which is exactly why it was a defect: in production those five ticks are
    fifty seconds. The retry branch holds the message for its backoff, so this loop steps
    over each wait explicitly rather than pretending there was none. What is asserted is
    unchanged: poison still reaches the DLQ, and it still holds no lease when it gets
    there.
    """
    ids = await _seed(1)
    only_mine(ids)

    async def _refuse(*args: Any, **kwargs: Any) -> str | None:
        raise ValueError("this payload cannot be serialised")

    monkeypatch.setattr(dispatcher, "enqueue", _refuse)

    waits: list[float | None] = []
    for _ in range(rel.OUTBOX_MAX_ATTEMPTS):
        await dispatcher.dispatch_outbox({})
        waits.append(await _step_over_the_backoff(ids[0]))

    status, attempts, deferred, last_error = (await _rows(ids))[ids[0]]
    assert status == "failed", (
        f"a payload the queue can never accept must reach the DLQ; it is {status!r} after "
        f"{attempts} attempt(s)"
    )
    assert not deferred, "a dead letter holds no lease — the ops replay must be able to move it"
    assert last_error is not None and last_error.startswith("ValueError:"), last_error
    # Every tick before the last one had to be waited out, and the last one did not: the
    # poison budget is spent over minutes rather than in one loop, and the terminal
    # transition clears the hold. Without this the loop above would silently degrade into
    # "one attempt then four no-ops" the moment the backoff changed shape.
    assert waits[:-1] and all(w is not None for w in waits[:-1]), (
        f"a retryable failure left the message immediately re-claimable: {waits}"
    )
    assert waits[-1] is None, f"the dead letter is holding a {waits[-1]}s lease"


async def test_an_outage_and_a_poison_message_are_told_apart_by_the_row(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """An operator arriving after the fact reads `last_error`, and the two situations
    have different answers: one is "wait", the other is "fix the receiver"."""
    outage_ids = await _seed(1)
    only_mine(outage_ids)
    _queue_is_down(monkeypatch)
    await dispatcher.dispatch_outbox({})
    _status, _attempts, deferred, outage_error = (await _rows(outage_ids))[outage_ids[0]]

    assert deferred
    assert outage_error is not None and outage_error.startswith("ConnectionError:"), outage_error


# =============================== 2b. and an operator can SEE the backlog while it happens


async def test_the_ops_read_counts_deferred_messages_during_an_outage(
    monkeypatch: pytest.MonkeyPatch, only_mine: Any, alerts: list[tuple[str, str, str | None]]
) -> None:
    """THE THIRD STATE, ON THE SCREEN. The half `defer_outbox_claim` created and left
    invisible.

    The backoff is what makes an outage survivable, and it is also what makes it look
    like nothing: the messages stay `pending`, the DLQ stays honestly empty, and the ops
    console — which published `depth` and nothing else — showed a green "Nothing is
    dead-lettered" for the whole five minutes. An operator arriving mid-incident read the
    one number on the screen and concluded the outbox was fine.

    Asserted through `read_dead_letter_queue`, which is THE definition of the queue's
    depth for both the metric and `GET /v1/ops/platform`, so this is the number the
    console actually renders rather than a second count written for the test.

    **THE COUNT IS COMPARED AS A DELTA, not as an absolute** — `outbox_messages` is
    platform-wide and other suites leave rows in it, so a bare `deferred == 3` would be
    asserting about the whole database's mood.

    **AND THE DELTA IS NOT THIS FILE'S OWN DOING, which is what this docstring used to
    claim and why this test failed on a busy database.** `only_mine` filters the claim's
    RESULT, but it runs the real `claim_outbox_batch` first — and that stamps a
    two-minute `locked_until` on every row in the batch, up to `OUTBOX_BATCH`. The
    production code says so itself: `read_dead_letter_queue` counts "a PENDING one
    holding a lease into the future", and its own comment records that this is
    indistinguishable from a claimed in-flight message by deliberate design. So on a
    database where other suites have left 50 pending rows, the delta is 50, and the
    equality was asserting the batch size.

    What is actually being measured is that the ops read COUNTS a deferred message at
    all — the console published `depth` alone and rendered a green "Nothing is
    dead-lettered" through a five-minute outage. That property is exact per ROW, and the
    fleet number can only be bounded from below.
    """
    ids = await _seed(3)
    only_mine(ids)

    async with untenanted_session() as session:
        before = await rel.read_dead_letter_queue(session)

    _queue_is_down(monkeypatch)
    assert await dispatcher.dispatch_outbox({}) == "published=0"

    async with untenanted_session() as session:
        during = await rel.read_dead_letter_queue(session)

    # THE EXACT HALF: each of OUR three is pending, holding a backoff, and un-dead.
    for message_id, (status, _attempts, deferred, _error) in (await _rows(ids)).items():
        assert status == "pending", f"{message_id} left `pending` during a queue outage"
        assert deferred, f"{message_id} was handed back without a backoff"

    # THE FLEET HALF, as an ABSOLUTE FLOOR rather than a delta — because a delta is not
    # measurable here at all. `only_mine` runs the real claim, which stamps a two-minute
    # `locked_until` on up to `OUTBOX_BATCH` rows belonging to other suites, and
    # `read_dead_letter_queue`'s own comment records that a lease and a backoff are one
    # column by design. So every reading of this number during this test is dominated by
    # rows this file did not create, and both the before/after equality and the delta are
    # assertions about the rest of the database.
    #
    # What IS provable from the fleet number, and is the original defect, is that the read
    # counts the pending-with-a-lease slice AT ALL: the console published `depth` alone
    # and rendered a green "Nothing is dead-lettered" through a five-minute outage. A read
    # that lost that FILTER returns 0 here, whatever else is in the table.
    assert during.deferred >= len(ids), (
        f"three messages are holding a backoff and the ops read says {during.deferred} "
        "deferred — the console cannot show a backlog it does not count, which is how an "
        "outage renders as 'nothing wrong'"
    )
    # The DLQ is genuinely EMPTY of our rows, and that is the whole point: the number that
    # used to be the only one on screen is still telling the truth, and the truth was
    # misleading on its own.
    assert during.depth == before.depth, "an outage must not dead-letter anything"

    # And when the queue comes back, the count comes down. A gauge that only rises is a
    # gauge an operator learns to ignore.
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE outbox_messages SET locked_until = NULL WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
    monkeypatch.setattr(dispatcher, "enqueue", _publishes)
    assert await dispatcher.dispatch_outbox({}) == f"published={len(ids)}"

    async with untenanted_session() as session:
        after = await rel.read_dead_letter_queue(session)

    # SAME SPLIT AS ABOVE, and for the same reason: `after.deferred == before.deferred`
    # is an equality over the WHOLE table, and `before` was itself taken after a real
    # claim leased up to `OUTBOX_BATCH` of other suites' rows — rows whose two-minute
    # leases outlive this test. What recovery means exactly is that OUR three left the
    # deferred set, which is a per-row fact.
    for message_id, (status, _attempts, deferred, _error) in (await _rows(ids)).items():
        assert status == "published", f"{message_id} was not published once the queue came back"
        assert not deferred, (
            f"{message_id} is still holding a backoff after a successful publish — a "
            "gauge that only rises is a gauge an operator learns to ignore"
        )
    # NO FLEET ASSERTION ON RECOVERY, deliberately. The recovering tick runs the real
    # claim a second time and leases another batch of other suites' rows, so
    # `after.deferred` RISES on a busy database however perfectly our three recovered —
    # measured, not assumed. The per-row loop above is the whole property, and it is the
    # exact one: our rows left the deferred set. `after` is read so the failure message
    # above can show the trajectory.
    assert after.depth == during.depth, "recovery must not dead-letter anything either"


async def _publishes(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
    """A queue that works — the recovery half of the outage test above."""
    return job_id or "queued"


# ================================================= 3. the deferral is still a CAS (§5)


async def test_deferring_cannot_pull_back_a_message_another_dispatcher_published() -> None:
    """`defer_outbox_claim` writes a lease on rows it believes it still holds. A second
    dispatcher that published one of them in the meantime must win: leasing a published
    row would park it, and — worse — leave a `locked_until` on a row whose job is already
    running, which reads to an operator as "claimed right now".
    """
    ids = await _seed(2)
    published, still_pending = ids[0], ids[1]
    async with untenanted_session() as session:
        await rel.mark_outbox_published(session, message_id=published, job_id="job-elsewhere")

    async with untenanted_session() as session:
        moved = await rel.defer_outbox_claim(session, message_ids=ids, error="queue unreachable")

    rows = await _rows(ids)
    assert moved == 1, f"only the pending row may be deferred, {moved} were"
    assert rows[published][0] == "published"
    assert rows[published][2] is False, "a published row must not be left holding a lease"
    assert rows[still_pending][2] is True


async def test_the_wait_grows_with_the_attempts_already_spent() -> None:
    """A flat wait would be the same defect at a slower pace: five attempts ten seconds
    apart, or five thirty seconds apart, both end with the outbox dead-lettered before a
    long outage is over. The wait is proportional to what the message has already spent,
    and capped so it cannot become a message nobody ever retries.
    """
    ids = await _seed(2)
    early, late = ids[0], ids[1]
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE outbox_messages SET attempt_count = 1 WHERE id = :id"), {"id": early}
        )
        await session.execute(
            text("UPDATE outbox_messages SET attempt_count = 4 WHERE id = :id"), {"id": late}
        )
        await rel.defer_outbox_claim(session, message_ids=ids, error="queue unreachable")

    async with untenanted_session() as session:
        waits = {
            row[0]: float(row[1])
            for row in (
                await session.execute(
                    text(
                        "SELECT id, EXTRACT(EPOCH FROM (locked_until - now())) "
                        "FROM outbox_messages WHERE id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
            ).all()
        }

    assert waits[late] > waits[early], waits
    assert waits[early] == pytest.approx(rel.OUTBOX_RETRY_BACKOFF_S, abs=2)
    assert waits[late] <= rel.OUTBOX_RETRY_BACKOFF_CAP_S


async def test_the_budget_now_outlives_a_restart_rather_than_a_minute() -> None:
    """The number this whole file is about, asserted as arithmetic rather than as prose
    so it cannot rot: the dispatcher's cadence, its attempt budget and its backoff have
    to add up to more downtime than a queue restart takes.
    """
    from apps.workers.settings import CRON_JOBS

    tick = next(job for job in CRON_JOBS if job.name.endswith("dispatch_outbox"))
    seconds = sorted(tick.second or {0})
    cadence = seconds[1] - seconds[0] if len(seconds) > 1 else 60
    undeferred = cadence * rel.OUTBOX_MAX_ATTEMPTS
    deferred = sum(
        min(rel.OUTBOX_RETRY_BACKOFF_S * attempt, rel.OUTBOX_RETRY_BACKOFF_CAP_S)
        for attempt in range(1, rel.OUTBOX_MAX_ATTEMPTS)
    )

    assert undeferred <= 60, (
        f"the premise: without a backoff the whole budget is spent in {undeferred}s"
    )
    assert deferred >= 300, (
        f"a deferred budget of {deferred}s does not cover an outage worth the name"
    )


# ================================== 4. what a DLQ replay actually re-sends to the client


async def test_a_replayed_dead_letter_carries_the_id_the_receiver_deduplicates_on() -> None:
    """The outbox's other promise: delivery is AT-LEAST-ONCE, with a key the receiver can
    use to make it exactly-once on their side.

    The key is `delivery_id`, minted by `integrations.enqueue_event` INSIDE the outbox
    payload (not by the worker, which arq re-runs), carried in the envelope's `id` and in
    the `X-Calevate-Delivery` header (WEBHOOKS §1.5). So an ops replay — which flips the
    row back to `pending` and lets the dispatcher publish it again — re-sends the same
    identifier rather than minting a second event out of the same lead.

    That is the whole difference between "the client's CRM saw a retry" and "the client's
    CRM saw a second lead", and the replay screen's own copy tells an operator the first
    of those is what will happen. Asserted on the row, because the payload is what
    survives a replay: the worker reads `payload['delivery_id']` and nothing else.
    """
    from apps.api.db.session import tenant_session
    from apps.api.integrations import service as integrations

    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Replay Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"replay-{RUN}"},
        )
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, events, active, "
                "created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example.invalid/hook', ARRAY['call.completed'], true, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )
        await integrations.enqueue_event(
            session,
            tenant_id=tenant_id,
            event="call.completed",
            data={"call_id": f"replay-{RUN}"},
        )

    async def _payload() -> dict[str, Any]:
        async with untenanted_session() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id, payload FROM outbox_messages "
                        "WHERE job = 'deliver_outbound_webhook' "
                        "AND payload @> CAST(:m AS jsonb) LIMIT 1"
                    ),
                    {"m": json.dumps({"data": {"call_id": f"replay-{RUN}"}})},
                )
            ).first()
        assert row is not None, "the fan-out wrote no outbox row"
        return {"id": row[0], **(row[1] or {})}

    before = await _payload()
    assert before["delivery_id"], "an outbox row with no delivery id is an undedupable POST"

    # Dead-letter it the way an exhausted publish does, then replay it the way ops does.
    #
    # The counter is set to the ceiling FIRST, and that is not scene-setting: without it
    # the row's `attempt_count` is still 0 and the "fresh budget" assertion below reads
    # zero-equals-zero, which passes whether or not the replay resets anything. Found by
    # deleting `attempt_count = 0` from `replay_dead_letters` and watching this test stay
    # green.
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE outbox_messages SET attempt_count = :n WHERE id = :id"),
            {"n": rel.OUTBOX_MAX_ATTEMPTS, "id": before["id"]},
        )
        await rel.mark_outbox_failed(
            session,
            message_id=before["id"],
            error="the queue refused it",
            attempt_count=rel.OUTBOX_MAX_ATTEMPTS,
        )
        replayed = await rel.replay_dead_letters(session, job="deliver_outbound_webhook", limit=100)
    assert replayed >= 1

    after = await _payload()
    assert after["delivery_id"] == before["delivery_id"], (
        "the replay changed the delivery id, so the client's receiver sees a second "
        "event rather than a retry it can deduplicate"
    )
    async with untenanted_session() as session:
        status, attempts = (
            await session.execute(
                text("SELECT status, attempt_count FROM outbox_messages WHERE id = :id"),
                {"id": before["id"]},
            )
        ).first() or (None, None)
        # Housekeeping: this row would otherwise sit at the head of every later tick.
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = :id"), {"id": before["id"]}
        )
    assert (status, attempts) == ("pending", 0), (
        "a replay must hand the message a FRESH budget, or one that ran out once can "
        "never be recovered"
    )
