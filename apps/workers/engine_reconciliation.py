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

**ONE OF ITS VERDICTS IS NOW ENFORCED (D-562).** An object read back without the
truthful-answer directive is recorded as `truthful_answer_missing` rather than as the
generic `not_applied`, and `compliance.service.check_dispatch` refuses a dial on that
verdict alone while it is fresh. That is still not a repair — see below — and it is
deliberately narrow: an agent whose prompt merely differs from what we published goes on
calling, because halting a paying client over a cosmetic drift is the worse failure.

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

RETRIES, AND THERE IS NO DLQ (P6.5). `max_tries` is passed EXPLICITLY at the `cron()`
call site because
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
    TRUTHFUL_ANSWER_MISSING,
    TRUTHFUL_ANSWER_VERDICT_TTL_S,
    DriftCandidate,
    claim_drift_batch,
    record_drift,
    recorded_drift_state,
)
from apps.api.agents.service import reconcile_inbound_truthful_answer
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
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

#: The number of live vendor agent objects this platform is built to watch. Not a limit
#: and not a licence check — it is the figure the assertion below compares the sweep's
#: throughput against, so that "the sweep reaches every agent well inside a day" stays a
#: property somebody has checked rather than a sentence in a docstring. ROADMAP's horizon
#: is client #1 and then tens; 1,000 is that with two orders of magnitude of slack.
SWEEP_FLEET_HORIZON = 1000


def _assert_the_sweep_can_refresh_a_verdict_before_it_expires() -> None:
    """A `truthful_answer_missing` verdict REFUSES DIALS until it goes stale (D-562), and
    the only thing that can ever refresh or clear it is this sweep. So the two numbers
    have to be in a relationship, and it is checked here rather than described in a
    comment for `_assert_the_tick_fits_its_interval`'s reason.

    THE FAILURE IT PREVENTS IS SILENT IN BOTH DIRECTIONS. Too short a TTL (or too small a
    batch) and verdicts expire faster than the sweep can restate them, so the gate stops
    enforcing under entirely normal operation and nothing anywhere says so. `SWEEP_MINUTES`
    is the tick count per hour, `SWEEP_BATCH_SIZE` the objects per tick; their product over
    the TTL window is how many live objects the sweep can re-read before the oldest verdict
    expires, and `SWEEP_FLEET_HORIZON` is the fleet this platform is built for
    (`docs/ROADMAP.md` — client #1, then tens). Wrong in the safe direction by a wide
    margin today, which is what makes it an assertion and not a budget.
    """
    ticks_per_ttl = (TRUTHFUL_ANSWER_VERDICT_TTL_S / SWEEP_INTERVAL_S) * len(SWEEP_MINUTES)
    refreshable = ticks_per_ttl * SWEEP_BATCH_SIZE
    if refreshable < SWEEP_FLEET_HORIZON:
        raise AssertionError(
            f"the sweep can re-read {refreshable:.0f} objects inside the "
            f"{TRUTHFUL_ANSWER_VERDICT_TTL_S}s a truthful-answer verdict is honoured for, "
            f"which is short of the {SWEEP_FLEET_HORIZON}-object fleet this platform plans "
            "for — so a proven-missing compliance directive would expire out of the dial "
            "gate before this cron could restate it, and the gate would stop enforcing "
            "with nothing to show for it. Raise TRUTHFUL_ANSWER_VERDICT_TTL_S or "
            "SWEEP_BATCH_SIZE, or shorten the schedule."
        )


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
_assert_the_sweep_can_refresh_a_verdict_before_it_expires()


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
        drift = await engine_drift_for(
            tenant_id=candidate.tenant_id,
            agent_id=candidate.agent_id,
            # THE ROUTE'S OWN VENDOR OBJECT (D-380). Without it this read back the AGENT
            # once per route and stamped that verdict on an experiment ARM's row — a
            # verdict about a different object, and the arms are the traffic actually
            # under test. `record_drift` below writes against `candidate.engine_agent_ref`
            # either way, so the two halves have to name the same object.
            engine_agent_ref=candidate.engine_agent_ref,
        )
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
    # WHICH divergence, not just that there was one (D-562). `recorded_drift_state` is
    # the one place the refinement is made; storing `drift.state` raw is what left the
    # single divergence with a legal consequence indistinguishable from a whitespace
    # difference in a client's script, and therefore unenforceable at the dial gate.
    state = recorded_drift_state(drift.state, truthful_answer_applied=drift.truthful_answer_applied)
    # A TENANT SESSION, and it used to be `untenanted_session` (migration `b8e2d47f0c19`).
    # The sweep is still cross-tenant where that matters — `claim_drift_batch` reads the
    # stalest routes across the fleet from no session at all, which is how a drift sweep
    # can start from what the vendor lists rather than from a tenant. What moved is only
    # the WRITE: the candidate already names its tenant, and scoping the stamp to it is
    # what let `engine_agent_routes` drop the `OR <guc> IS NULL` arm that handed every
    # untenanted writer, present and future, the power to re-tenant a client's inbound
    # route. The second `tenant_session` below is the same tenant and stays separate: it
    # makes vendor calls, and this stamp must be committed before those are attempted.
    async with tenant_session(candidate.tenant_id) as session:
        recorded = await record_drift(
            session,
            tenant_id=candidate.tenant_id,
            engine=engine_name,
            ref=candidate.engine_agent_ref,
            state=state,
        )
    if not recorded:
        # The route was deleted between the batch read and now. Nothing to record and
        # nothing wrong — the object is no longer ours to watch.
        return None

    # THE INBOUND HALF OF THE VERDICT (D-564). `record_drift` above is the OUTBOUND half's
    # evidence — `check_dispatch` reads that column. Inbound reaches nothing of ours before
    # it is answered, so it needs durable state AT the engine, applied on this edge.
    # Handed the drift THIS TICK MEASURED rather than a re-read of the column: a verdict is
    # evidence about the instant it was taken, and `None` ("we could not tell") must not
    # move a client's phone. A TENANT SESSION because `agents` is FORCE-RLS'd — the sweep's
    # own session is untenanted, and only `engine_agent_routes` carries that exemption.
    async with tenant_session(candidate.tenant_id) as session:
        silence = await reconcile_inbound_truthful_answer(
            session,
            get_engine(),
            tenant_id=candidate.tenant_id,
            agent_id=candidate.agent_id,
            truthful_answer_applied=drift.truthful_answer_applied,
        )
    if silence not in ("unchanged", "indeterminate", "gone"):
        log.info(
            "inbound_truthful_answer_reconciled",
            extra={"agent_id": str(candidate.agent_id), "outcome": silence},
        )

    if state == TRUTHFUL_ANSWER_MISSING:
        # ITS OWN LINE, at ERROR, and it names the agent (hard rule 6: an id, never the
        # prompt). This is the only verdict that stops a client's calling, and an operator
        # reading the alert needs to be able to find WHICH agent from the logs — the alert
        # body carries counts because an email with 25 uuids in it is an email nobody reads.
        log.error(
            "engine_drift_truthful_answer_missing",
            extra={
                "agent_id": str(candidate.agent_id),
                "tenant_id": str(candidate.tenant_id),
                "engine": engine_name,
            },
        )
    return state


async def _sweep() -> str:
    """One tick's work: the stalest live agents read back and their verdicts recorded.

    THE ALERT is the half that makes this more than a table nobody reads, and it fires on
    the OUT-OF-SYNC verdicts only — `not_applied` and, since D-562, its compliance
    refinement `truthful_answer_missing`, which the body names separately because that one
    has already stopped the client's calling rather than merely asking someone to look.
    `unreadable` and `unreachable` are held out for the reason
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
    uncompliant = verdicts.get(TRUTHFUL_ANSWER_MISSING, 0)
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
                + (
                    # SAID FIRST-CLASS AND SAID PLAINLY (D-562). These agents are now
                    # REFUSED at the dial gate, so the operator is being told what has
                    # already happened to a client's calling, not only what they must go
                    # and look at. Without this sentence the alert reported the compliance
                    # failure and the campaign outage as the same anonymous count.
                    f"; {uncompliant} of them have lost the truthful-answer rule and can "
                    "no longer place calls until a republish restores it"
                    if uncompliant
                    else ""
                )
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
    attempts, then an ALERT — not a dead-letter queue, which this docstring used to name
    and which does not exist (P6.5). An exhausted arq job is `zrem`'d off the queue and
    written to a result key nothing in this repository reads, so the alert on the last
    attempt IS the dead-letter mechanism.

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
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            # `defer` climbs with the attempt so a database that is restarting is not
            # hammered by three sweeps in ninety seconds — the ladder BACKEND-PATTERNS §4
            # asks for.
            raise Retry(defer=30 * attempt) from exc
        # THE LAST ATTEMPT IS THE ONE THAT HAS TO SHOUT (P6.5). This used to raise `Retry`
        # unconditionally, and on the final try arq does not honour it: the job finishes
        # with `JobExecutionFailed` and a `logger.warning`, which nothing reads. The
        # docstring's "three attempts, then the DLQ" was describing a queue that does not
        # exist — an exhausted arq job is `zrem`'d and written to a result key nobody
        # reads. So the alert IS the dead-letter mechanism, and it has to be here.
        alert(
            "WORKER_TERMINAL",
            "engine_drift_sweep_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); "
                "every client's live agent is unwatched until this cron succeeds"
            ),
        )
        raise


__all__ = [
    "SWEEP_BATCH_SIZE",
    "SWEEP_BUDGET_S",
    "SWEEP_INTERVAL_S",
    "SWEEP_MINUTES",
    "sweep_engine_drift",
]
