"""Two dispatch ticks must never run at once, and arq will not stop them.

The tick is registered `cron(..., second=TICK_SECONDS)` — every 30 seconds. arq 0.28
gives each cron firing a job id of `f'{name}:{to_unix_ms(next_run)}'`
(`arq/worker.py::run_cron`) and dedupes on that id, which `arq/constants.py` spells out
in the comment on `keep_cronjob_progress`: the in-progress key can be kept a long time
"since each cron job has an ID that is unique for the INTENDED EXECUTION TIME". So it
stops two WORKERS from running the :30 firing twice. It does nothing about the :30
firing starting while the :00 one is still going — different ids, different keys, and
`Worker.start_jobs` only checks the key belonging to the id it is about to start.

**What overlap breaks is NOT the thing it sounds like.** Two ticks cannot double-dial a
person: `_dispatch_for_campaign` claims contacts with a conditional UPDATE off
`status = 'pending'` under `FOR UPDATE SKIP LOCKED`, so the second tick skips whatever
the first has locked, and `tests/campaigns_test.py` already proves that. What two ticks
DO both do is read `total_active`, compute `global_budget = pool - total_active` from it,
and each spend the whole thing — a read-then-act on a platform-wide budget whose job is
to keep lines free for other clients' inbound receptionists (FLOWS §5 rules 1+2).
BACKEND-PATTERNS §5 says replace read-then-write with a CAS or a lock; there is no row to
CAS a platform-wide budget against, so `_tick_lease` is a lock.

The rejected alternative is arq's own: a fixed `cron(job_id=...)`, which its issue #459
recommends for exactly this. It cannot be used at 30 seconds, because a fixed id keeps
its in-progress key for `keep_cronjob_progress` = 60 SECONDS AFTER THE JOB ENDS — a
30-second tick would quietly become a 60-second one, and hard rule 5's DNC propagation
deadline is "before the next dispatch tick".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from apps.api.core.redis import get_redis
from apps.workers import campaign_dispatch
from apps.workers import settings as worker_settings
from apps.workers.campaign_dispatch import dispatch_campaign_tick


@pytest.fixture(autouse=True)
async def _no_stale_lease() -> Any:
    """Leave the platform's tick lease as quiet as we found it — it is ONE key shared
    with every other pytest process on this Redis, and a lease left behind would skip
    every later suite's tick."""
    redis = get_redis()
    await redis.delete(campaign_dispatch._TICK_LEASE_KEY)
    yield
    await redis.delete(campaign_dispatch._TICK_LEASE_KEY)


async def test_a_second_tick_refuses_to_run_while_the_first_still_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property, driven through the real entry point rather than through the lease.

    `_run_tick` is replaced by one that blocks until released, so the overlap is a
    certainty rather than a race this test hopes to win — the point is what the SECOND
    call does, and a timing-dependent version would be green on a fast box for the wrong
    reason.

    **The second call is bounded and the release is in a `finally`, and both are the
    result of running the sabotage.** With the lease removed, the second call does not
    return a wrong answer — it enters the same blocked `_run_tick` and the test deadlocks
    until pytest's own timeout, which reads as "hung suite" rather than "broken
    dispatcher". A test whose failure mode is a hang is a test nobody trusts, so the
    overlap window has a deadline of its own.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_tick() -> str:
        started.set()
        await release.wait()
        return "first"

    monkeypatch.setattr(campaign_dispatch, "_run_tick", slow_tick)

    first = asyncio.create_task(dispatch_campaign_tick({}))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        second = await asyncio.wait_for(dispatch_campaign_tick({}), timeout=5)
    finally:
        release.set()

    assert second == "skipped_previous_tick_running"
    assert await first == "first"


async def test_the_lease_is_released_so_the_next_tick_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lock that is not released is an outage with a 330-second fuse. The lease is
    dropped in a `finally`, and it is compare-and-delete so a tick that overran its TTL
    cannot release the lease its successor now holds."""
    calls: list[int] = []

    async def counting_tick() -> str:
        calls.append(1)
        return "ran"

    monkeypatch.setattr(campaign_dispatch, "_run_tick", counting_tick)

    assert await dispatch_campaign_tick({}) == "ran"
    assert await dispatch_campaign_tick({}) == "ran"
    assert len(calls) == 2

    redis = get_redis()
    assert await redis.get(campaign_dispatch._TICK_LEASE_KEY) is None


async def test_a_tick_that_raises_still_gives_the_lease_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode that matters most: a tick dies (an engine timeout, a cancelled
    job) and every later tick is refused because the corpse still holds the lease. The
    dispatcher would stop dialling platform-wide and the only symptom would be an alert
    saying the previous tick is still running — forever."""

    async def exploding_tick() -> str:
        raise RuntimeError("engine refused")

    monkeypatch.setattr(campaign_dispatch, "_run_tick", exploding_tick)
    with pytest.raises(RuntimeError):
        await dispatch_campaign_tick({})

    redis = get_redis()
    assert await redis.get(campaign_dispatch._TICK_LEASE_KEY) is None


async def test_a_refused_tick_alerts_rather_than_skipping_quietly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """CLAUDE.md: no silent caps. A tick that could not run is a tick whose predecessor
    is past its own interval, and from the outside that looks like campaigns dialling
    late — nothing else says so."""
    redis = get_redis()
    await redis.set(campaign_dispatch._TICK_LEASE_KEY, "someone-else", px=10_000)

    with caplog.at_level("ERROR"):
        result = await dispatch_campaign_tick({})

    assert result == "skipped_previous_tick_running"
    codes = [r.__dict__.get("code") for r in caplog.records if r.__dict__.get("code")]
    assert "dispatch_tick_overlap" in codes, codes


async def test_a_redis_outage_does_not_stop_the_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL OPEN, like the audit chain's lock. Redis is arq's own transport, so a tick
    that reaches this code has already been delivered through Redis; refusing to dial
    because the lease write failed would turn a blip into a campaign that stops. The
    claim CAS still stands between that and a double dial."""

    class _Broken:
        async def set(self, *_a: Any, **_k: Any) -> bool:
            raise ConnectionError("redis down")

    monkeypatch.setattr(campaign_dispatch, "get_redis", lambda: _Broken())
    monkeypatch.setattr(campaign_dispatch, "_run_tick", _ran)

    assert await dispatch_campaign_tick({}) == "ran"


async def test_a_tick_that_overruns_its_own_interval_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The alert that makes the not-fitting VISIBLE, which is the whole point of D-57.

    A tick that no longer fits inside its schedule is invisible from the outside — the
    overlap guard above turns the SECOND tick into a refusal, so what an operator sees is
    campaigns dialling late and nothing saying why. This is the signal that names it.

    It drives the comparison by making the tick genuinely slow rather than by shrinking
    the interval, because the interval is read from `TICK_SECONDS` in two places (the
    cron and the dispatcher) and a test that moved it would be asserting against a
    configuration nothing runs.

    Written because the ratchet said so. This branch and the lease-release failure below
    were the whole of a +4 regression on `dial-path` — two new observability paths whose
    only test was "hope it fires in production", which is the same defect as the >500ms
    ack alert that had CI red for nine commits.
    """

    async def slow_tick() -> str:
        await asyncio.sleep(campaign_dispatch.TICK_INTERVAL_S + 0.05)
        return "ran"

    monkeypatch.setattr(campaign_dispatch, "TICK_INTERVAL_S", 0.05)
    monkeypatch.setattr(campaign_dispatch, "_run_tick", slow_tick)

    with caplog.at_level("ERROR"):
        assert await dispatch_campaign_tick({}) == "ran"

    codes = [r.__dict__.get("code") for r in caplog.records if r.__dict__.get("code")]
    assert "dispatch_tick_overrun" in codes, codes


async def test_a_lease_that_cannot_be_released_warns_instead_of_failing_the_tick(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The release is best-effort, and the TTL is what actually guarantees progress.

    If Redis dies between taking the lease and giving it back, raising here would turn a
    completed tick — contacts already dialled — into a job arq retries, re-running the
    work for a lease nobody can hold. The lease expires on its own; the correct behaviour
    is to say so and return the outcome the tick actually produced.
    """

    class _ReleaseFails:
        async def set(self, *_a: Any, **_k: Any) -> bool:
            return True

        async def eval(self, *_a: Any, **_k: Any) -> Any:
            raise ConnectionError("redis went away mid-tick")

    monkeypatch.setattr(campaign_dispatch, "get_redis", lambda: _ReleaseFails())
    monkeypatch.setattr(campaign_dispatch, "_run_tick", _ran)

    with caplog.at_level("WARNING"):
        assert await dispatch_campaign_tick({}) == "ran"

    assert "dispatch_tick_lease_release_failed" in caplog.text


async def _ran() -> str:
    return "ran"


def test_the_lease_outlives_the_longest_a_tick_can_run() -> None:
    """arq cancels a job at `job_timeout`, so that is the longest a tick can be alive.
    A lease shorter than that would expire UNDER a tick that is still dialling and hand
    the shared line pool to a second one — the exact failure it exists to prevent."""
    assert worker_settings.WorkerSettings.job_timeout < campaign_dispatch.TICK_LEASE_TTL_S


def test_the_cron_schedule_and_the_dispatcher_agree_on_the_interval() -> None:
    """The dispatcher alerts when a tick exceeds `TICK_INTERVAL_S`, so a schedule written
    independently of it would make that alarm either deaf or permanently on. `settings.py`
    builds the cron FROM these constants; this pins that it still does."""
    # arq prefixes a cron job's registered name with "cron:".
    tick = next(
        job for job in worker_settings.CRON_JOBS if job.name.endswith("dispatch_campaign_tick")
    )
    assert tick.second == set(campaign_dispatch.TICK_SECONDS)
    assert (
        frozenset(range(0, 60, campaign_dispatch.TICK_INTERVAL_S)) == campaign_dispatch.TICK_SECONDS
    )
