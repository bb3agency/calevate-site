"""The periodic drift sweep — D-121's third gap, and the one that was never vendor-blocked.

WHAT WAS MISSING. `agents/publishing.py::engine_drift_for` asks the ENGINE what it is
running and compares it with our row, and `GET /v1/agents/{agent_id}/engine-state`
publishes the answer. Both are ON DEMAND, so the only two divergences that read can
possibly find were found only by whoever thought to look:

* an agent edited in the VENDOR'S OWN DASHBOARD — nothing of ours ran, so every table we
  own agrees with itself and is wrong;
* a publish that failed on OUR side AFTER the vendor committed — our transaction rolled
  back to the previous script and the engine kept the new one. The divergence points the
  other way, and re-reading our own tables can never find it.

Both are silent, both are indefinite, and both end with a client's phone line speaking a
script nobody approved. This cron is what finds them.

**IT IS A READ. IT RE-PUBLISHES NOTHING.** D-121 argues this at length and it is preserved
here as a property of the code, not a note: `_reconcile_one` calls `engine_drift_for`,
which is a pure read, and writes only OUR observation columns. Overwriting an operator's
emergency console edit — made, plausibly, while our console was the thing that was down —
is a decision with a blast radius, and doing it platform-wide on a schedule is the worst
possible way to make it. The output is a RECORD (`engine_agent_routes.drift_state`, read
by `GET /v1/ops/platform`) and an ALERT. A human decides.

WHAT IT COSTS, AND THE THREE BOUNDS THAT KEEP IT AFFORDABLE
-----------------------------------------------------------
One vendor round trip per live agent per tick is the whole bill, and an unbounded sweep is
a self-inflicted rate-limit incident that arrives on a schedule. Three bounds, each
chosen for a reason and none of them a round number picked for looking tidy:

1. **`SWEEP_BATCH_SIZE = 25` objects per tick**, stalest first. The ordering
   (`claim_drift_batch`) is what makes a per-tick cap fair rather than starving: writing
   `drift_checked_at` is what moves a row to the back of the queue, so every live agent is
   reached without a cursor. At 25 per half-hour the sweep covers 1,200 agents a day,
   which is far past the platform's horizon (client #1, ROADMAP) while keeping the vendor
   bill at roughly one request a minute.
2. **`SWEEP_BUDGET_S = 120` of wall clock**, checked BETWEEN reads. The batch cap bounds
   the count; this bounds the TIME, and they are different failures — 25 agents behind a
   vendor that has started answering in ten seconds each is a four-minute tick. Checked
   between reads rather than enforced with a timeout because cancelling a read in flight
   would leave a round trip paid for and nothing recorded.
3. **The schedule strictly exceeds the worst case**, asserted at import below. That is
   what makes overlap structurally impossible instead of prevented by a lock: the
   campaign tick needs a Redis lease because a 30-second interval genuinely cannot contain
   its own work, and a sweep bounded to ~130 seconds inside a 1,800-second interval cannot
   collide with itself. Choosing the cheaper instrument is only honest if the relationship
   it depends on is checked, so it is (`_assert_the_tick_fits_its_interval`).

WHY NOT ONE JOB PER AGENT. Fanning out an arq job per live agent would give per-agent
retries and would also turn one predictable tick into N enqueues, N job records and N
uncoordinated vendor calls with no platform-wide budget between them — replacing a bound
we control with a queue depth we do not. The retry that matters here is the NEXT TICK,
which is free: a row that failed keeps its old `drift_checked_at` and is therefore first
in the next batch.

RETRIES AND THE DLQ. `max_tries` is passed EXPLICITLY at the `cron()` call site because
`cron()` defaults it to 1 and `WorkerSettings.max_tries` does not reach a function that
carries its own — the argument `issue_one_time_charges` and `draw_qa_samples` both make,
and the reason a sweep that gave up on its first Redis blip would leave the platform
unwatched with every screen still green. This job only ASKS for a retry when the sweep
could not run at all; a vendor that refused one agent is recorded as `unreachable` for
that agent and is not a reason to re-run the other twenty-four.

HARD RULE 6. Every log line here carries ids and counts. No prompt body, no disclosure
line, no phone number — `engine_agent_ref` is a vendor-issued opaque id, which is what
`_reclaim_orphan` already logs for the same reason.
"""

from __future__ import annotations

import time
from typing import Any

from arq import Retry

from apps.api.agents.publishing import engine_drift_for
from apps.api.agents.reconciliation import (
    DRIFT_STATES_OUT_OF_SYNC,
    DriftCandidate,
    claim_drift_batch,
    record_drift,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine

log = get_logger(__name__)

#: Vendor agent objects read back per tick. See the module docstring for why 25.
SWEEP_BATCH_SIZE = 25

#: Wall clock a tick may spend STARTING reads, in seconds. A read already in flight is
#: allowed to finish — cancelling it would spend the round trip and record nothing.
SWEEP_BUDGET_S = 120.0

#: The schedule, in minutes past the hour. `settings.py` builds the `cron()` registration
#: from this constant so the schedule and the arithmetic that reasons about the schedule
#: cannot disagree — the shape `campaign_dispatch.TICK_SECONDS` established.
#:
#: :07 and :37 rather than :00 and :30 deliberately: the outbox dispatcher, the execution
#: reconciler and the stalled-pipeline probe all fire on the round numbers, and a sweep
#: that adds 25 vendor round trips to the busiest second of every half hour is a sweep
#: that shows up in someone else's latency graph.
SWEEP_MINUTES = frozenset({7, 37})
SWEEP_INTERVAL_S = 30 * 60


def _assert_the_tick_fits_its_interval() -> None:
    """Overlap is prevented by ARITHMETIC here, not by a lease, so the arithmetic is
    checked at import rather than asserted in a comment.

    `campaign_dispatch._tick_lease` exists because a 30-second interval cannot contain its
    own work and arq does not serialise crons (a cron job's id embeds its INTENDED
    execution time, so the :30 tick and the :00 tick are different jobs with different
    in-progress keys). The same problem does not arise here and the same instrument is
    therefore not reached for: the budget plus one read in flight is the worst case, and
    it is an order of magnitude inside the interval. If a future edit closes that gap —
    a bigger batch, a shorter schedule — this fails at import, which is where a
    concurrency assumption that has stopped being true should fail.

    The read in flight is bounded by the adapter's own request timeout, which this module
    may not import (hard rule 2: only `apps/api/engine/` sees vendor modules). 60s is a
    deliberately generous stand-in for it — every adapter in the tree is well under that,
    and being wrong in this direction only makes the assertion stricter.
    """
    worst_case_s = SWEEP_BUDGET_S + 60.0
    if worst_case_s >= SWEEP_INTERVAL_S:
        raise AssertionError(
            f"a drift sweep can run for {worst_case_s}s inside a {SWEEP_INTERVAL_S}s "
            "interval, so two sweeps can overlap and each spend the vendor budget the "
            "other is counting on. Either lower SWEEP_BUDGET_S/SWEEP_BATCH_SIZE, widen "
            "SWEEP_MINUTES, or take a single-flight lease the way campaign_dispatch does."
        )


_assert_the_tick_fits_its_interval()


async def _reconcile_one(engine_name: str, candidate: DriftCandidate) -> str | None:
    """One vendor round trip, one recorded verdict — or None when there was no verdict.

    `engine_drift_for` already converts an unreachable engine into the `unreachable`
    VERDICT rather than an exception, which is the property that lets a sweep of 25 agents
    survive one sick agent. What it DOES raise is `not_found` — the agent was soft-deleted
    between the batch read and this call, since `_load_agent` carries `deleted_at IS NULL`
    — and that is a normal outcome of a sweep over a snapshot, not an error.

    **None, NOT a verdict string, for both non-outcomes**, and the distinction is what
    keeps the tick's own report honest: `checked` must mean "we read the engine back and
    scored it", so counting a soft-deleted agent we never dialled would inflate the number
    an operator reads as coverage. Neither case writes a row either — stamping
    `not_published` for an agent that no longer exists would put a permanent entry on the
    console that nothing can ever clear.
    """
    try:
        drift = await engine_drift_for(tenant_id=candidate.tenant_id, agent_id=candidate.agent_id)
    except ProblemError as exc:
        # `exc.code` is ours — the adapter normalizes — so this carries no vendor text.
        log.info(
            "engine_drift_sweep_skipped",
            extra={
                "agent_id": str(candidate.agent_id),
                "engine": engine_name,
                "reason": exc.code,
            },
        )
        return None
    async with untenanted_session() as session:
        recorded = await record_drift(
            session, engine=engine_name, ref=candidate.engine_agent_ref, state=drift.state
        )
    if not recorded:
        # The route was deleted between the batch read and now. Nothing to record and
        # nothing wrong — the object is no longer ours to watch.
        return None
    return drift.state


async def _sweep() -> str:
    """One tick's work: the stalest live agents read back and their verdicts recorded.

    THE ALERT is the half that makes this more than a table nobody reads, and it fires on
    `not_applied` ONLY. `unreadable` and `unreachable` are held out for the reason
    `agents/verification.py` separates them from a mismatch in the first place: "we could
    not tell" is not evidence, and an alarm that fires whenever a vendor is briefly slow is
    an alarm somebody mutes long before it ever catches a real dashboard edit. They are
    still COUNTED, still recorded per agent, and still on the ops console — where a rising
    `undetermined` is legible as a vendor problem rather than as a fleet of drifted agents.
    """
    engine = get_engine()
    async with untenanted_session() as session:
        batch = await claim_drift_batch(session, engine=engine.name, limit=SWEEP_BATCH_SIZE)
    if not batch:
        return "checked=0 drifted=0"

    started = time.monotonic()
    verdicts: dict[str, int] = {}
    skipped = 0
    for candidate in batch:
        if time.monotonic() - started >= SWEEP_BUDGET_S:
            # Not a failure and not a retry: the rows we did not reach kept their old
            # `drift_checked_at`, so they are first in the next tick's batch by
            # construction. Logged because a sweep that ROUTINELY runs out of budget is a
            # sweep whose batch size no longer matches how slow the vendor has become.
            log.warning(
                "engine_drift_sweep_budget_exhausted",
                extra={
                    "engine": engine.name,
                    "checked": sum(verdicts.values()),
                    "batch": len(batch),
                },
            )
            break
        verdict = await _reconcile_one(engine.name, candidate)
        if verdict is None:
            skipped += 1
            continue
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

    drifted = sum(count for state, count in verdicts.items() if state in DRIFT_STATES_OUT_OF_SYNC)
    checked = sum(verdicts.values())
    log.info(
        "engine_drift_sweep",
        extra={
            "engine": engine.name,
            "checked": checked,
            "drifted": drifted,
            # Agents that were in the batch and produced no verdict — soft-deleted, or
            # unpublished, between the batch read and the round trip. A tick that is
            # mostly skips is a tick whose batch is stale, and that is worth seeing.
            "skipped": skipped,
            **verdicts,
        },
    )
    if drifted:
        alert(
            # `WORKER_STALL`, following `report_stalled_pipeline` rather than inventing a
            # stage. The enum answers "where in the pipeline did this die", and neither of
            # these alarms is about a worker dying at all — both are a scheduled PROBE
            # reporting a bad state of the world it went and measured. Picking the stage
            # that already carries that meaning keeps the vocabulary a reader can trust;
            # adding a tenth member for one alarm would make the enum a list of alarms.
            "WORKER_STALL",
            "engine_agent_drift_detected",
            # Counts and an engine name. The agent ids are in the per-agent log lines and
            # the console; an alert body is not the place for a list (hard rule 6 aside,
            # an email with 25 uuids in it is an email nobody reads).
            detail=(
                f"{drifted} of {checked} live agents are running something other than "
                "what we published"
            ),
        )
    return f"checked={checked} drifted={drifted}"


async def sweep_engine_drift(ctx: dict[str, Any]) -> str:
    """THE JOB. Read the stalest live agents back off the engine, record what they hold.

    IDEMPOTENT AND KEYED. Idempotent because it is a read whose only write is an
    observation stamped with the instant it was made: running it twice produces the same
    row, and the second run is at worst wasted vendor budget. Keyed by the cron's own arq
    id (`f'{name}:{to_unix_ms(next_run)}'`), which is what dedupes two WORKERS racing the
    same tick — there is no natural business key to add, because the unit of work is "the
    25 stalest right now", not a named object.

    THE RETRY LADDER, and why it is spelled here rather than left to `max_tries`. arq 0.28
    retries a job for `arq.Retry` and for nothing else — a job that fails by raising
    anything else is finished on its first attempt, whatever `max_tries` says
    (`WorkerSettings` says so in its own comment). So a sweep that could not run AT ALL —
    the batch read failed, Postgres was unreachable — must ask for the retry explicitly, or
    the platform goes unwatched until the next half hour with nothing marked wrong. Three
    attempts, then the DLQ, which is this repo's convention and is also what puts an
    exhausted sweep on the ops console beside every other dead letter.

    A VENDOR failure is deliberately NOT in scope: `_reconcile_one` already converts one
    into a recorded `unreachable` for that agent, and re-running the whole sweep because
    one agent's engine was slow would spend the budget for the other twenty-four twice.
    """
    try:
        return await _sweep()
    except Exception as exc:
        log.warning(
            "engine_drift_sweep_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        # `defer` climbs with the attempt so a database that is restarting is not hammered
        # by three sweeps in nine seconds — the ladder BACKEND-PATTERNS §4 asks for.
        raise Retry(defer=30 * int(ctx.get("job_try", 1) or 1)) from exc


__all__ = [
    "SWEEP_BATCH_SIZE",
    "SWEEP_BUDGET_S",
    "SWEEP_INTERVAL_S",
    "SWEEP_MINUTES",
    "sweep_engine_drift",
]
