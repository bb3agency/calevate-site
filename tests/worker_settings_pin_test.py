"""A job resolves `Settings` once and holds that answer to its end (D-101).

Requests got this in `create_app`'s middleware. Jobs were the half left open when that
slice ran out of ownership, and they are the half that runs LONGEST — a post-call
pipeline can be alive for many seconds while a console change propagates in ~5.

The defect these pin: a job that reads `usd_inr_rate` when it prices a call and again
when it writes the usage row could read a different rate each time. That is one call
billed at two rates, in an append-only ledger where the fix is a compensating entry
rather than an edit. Half-applied is a WRONG number, not a stale one.

These drive `WorkerSettings.on_job_start` / `on_job_end` directly rather than booting a
real arq worker: the contract being tested is arq's, and it is exactly "these two hooks
run around the job, in the job's own task, and `on_job_end` runs even when it raised."
Booting a worker would test arq instead.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core import settings as settings_mod
from apps.api.core.settings import get_settings
from apps.workers.settings import WorkerSettings


def _override(**values: Any) -> None:
    """Move the process's settings the way a console write does, without a database."""
    settings_mod.apply_platform_overrides(values)


@pytest.fixture(autouse=True)
def _clean_overrides() -> Any:
    yield
    settings_mod.apply_platform_overrides({})


async def test_a_change_landing_mid_job_does_not_reach_the_job_that_started_first() -> None:
    """The whole point. A job reads a value, a console write lands, the job reads again —
    and must see what it started with, or one unit of work spans two configurations."""
    ctx: dict[str, Any] = {}
    _override(usd_inr_rate=Decimal("88.00"))

    await WorkerSettings.on_job_start(ctx)
    try:
        first = get_settings().usd_inr_rate
        # The refresh loop lands between the job's two reads.
        _override(usd_inr_rate=Decimal("91.50"))
        second = get_settings().usd_inr_rate
    finally:
        await WorkerSettings.on_job_end(ctx)

    assert first == Decimal("88.00")
    assert second == Decimal("88.00"), (
        "the job read two different rates for one call — a wrong number in an "
        "append-only ledger, not a stale one"
    )
    # And the NEXT job gets the new value: a pin holds a unit of work, not the process.
    assert get_settings().usd_inr_rate == Decimal("91.50")


async def test_the_pin_is_released_even_when_the_job_raised() -> None:
    """arq calls `on_job_end` whether the job returned or raised. If a failed job leaked
    its pin, the worker would serve every later job from the configuration of the one
    that died — the failure mode a `finally` exists to prevent, and one that would only
    show up after an unrelated job started misbehaving."""
    ctx: dict[str, Any] = {}
    _override(usd_inr_rate=Decimal("88.00"))
    await WorkerSettings.on_job_start(ctx)
    try:
        raise RuntimeError("the job failed")
    except RuntimeError:
        pass
    finally:
        await WorkerSettings.on_job_end(ctx)

    _override(usd_inr_rate=Decimal("91.50"))
    assert get_settings().usd_inr_rate == Decimal("91.50"), (
        "a failed job leaked its pin into the worker"
    )


async def test_two_concurrent_jobs_hold_their_own_answers() -> None:
    """arq runs jobs concurrently in one event loop. Tasks copy the context at creation,
    so each job's pin must be its own — otherwise the second job to start would move the
    first job's configuration underneath it, which is the same defect wearing a
    different hat."""
    _override(usd_inr_rate=Decimal("80.00"))
    started = asyncio.Event()

    async def slow_job() -> Decimal:
        ctx: dict[str, Any] = {}
        await WorkerSettings.on_job_start(ctx)
        try:
            first = get_settings().usd_inr_rate
            started.set()
            await asyncio.sleep(0.05)  # the other job runs, and the store moves
            assert get_settings().usd_inr_rate == first
            return first
        finally:
            await WorkerSettings.on_job_end(ctx)

    async def fast_job() -> Decimal:
        await started.wait()
        _override(usd_inr_rate=Decimal("95.00"))
        ctx: dict[str, Any] = {}
        await WorkerSettings.on_job_start(ctx)
        try:
            return get_settings().usd_inr_rate
        finally:
            await WorkerSettings.on_job_end(ctx)

    slow, fast = await asyncio.gather(slow_job(), fast_job())
    assert slow == Decimal("80.00"), "the slow job's answer moved under it"
    assert fast == Decimal("95.00"), "the later job must see the newer value"


async def test_the_hooks_are_actually_wired_to_the_worker() -> None:
    """A hook arq never calls is a pin that never happens. This is the half-wiring check:
    the functions could be perfect and `WorkerSettings` could simply not name them."""
    assert getattr(WorkerSettings, "on_job_start", None) is not None
    assert getattr(WorkerSettings, "on_job_end", None) is not None
