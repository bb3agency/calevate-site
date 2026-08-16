"""The periodic KB drift sweep (D-158) — the same gap D-123 closed for agents, for the
knowledge a client's agent answers from.

WHAT WAS MISSING. `kb/service._reconcile_engine_state` asks the engine what it is holding
and refuses to publish onto an agent carrying a copy no row of ours mentions. It runs AT
PUBLISH TIME and nowhere else, so the only two divergences it can find were found only by
whoever published next — and a knowledge base is the object in this system with the
longest gap between writes. A client pastes their price list once and does not touch it
for months, which is exactly how long a divergence stays invisible:

* a source added, replaced or DELETED in the VENDOR'S OWN DASHBOARD — nothing of ours ran,
  so every table we own agrees with itself and is wrong;
* a publish that failed on OUR side AFTER Bolna committed the attach. Our transaction
  rolled back and the engine kept the document. `publish_source` says so in its own last
  paragraph — "nothing here can" prevent it — and re-reading our own tables never will.

The first is the one with teeth. FLOWS §7's approval gate exists because a client editing
what their agent says is a client editing a legal instrument: the agent speaks on their
behalf under their PE registration. A knowledge base pasted into the vendor's console has
been through no gate at all, and the agent will read it aloud to callers.

**IT IS A READ. IT RE-PUBLISHES NOTHING AND IT DETACHES NOTHING.** D-121 argues this at
length for the agent sweep and it transfers with force, because the "obvious" repair here
is not an overwrite but a DELETE: `detach_kb` destroys the document at the vendor, and by
hypothesis the document this sweep found is one our tables cannot describe. A sweep that
tidied up would delete, unattended and platform-wide, the only copy of text somebody added
by hand — plausibly during an incident, while our console was the thing that was down. The
output is a RECORDED VERDICT (`engine_agent_routes.kb_drift_state`, read by
`GET /v1/ops/platform`) and an ALERT. A human decides.
`tests/kb_drift_reconciliation_test.py` holds that as a property: the sweep may call
`list_kb` and nothing else.

WHAT IT COSTS, AND THE BOUNDS THAT KEEP IT AFFORDABLE
------------------------------------------------------
One vendor round trip per live agent per tick, and here that round trip is dearer than the
agent sweep's: `bolna.list_kb` reads `GET /knowledgebase/all` — the WHOLE ACCOUNT's
knowledge list — and filters it to one agent on our side. So a tick of N agents pulls the
account listing N times, and the listing itself grows with every source every client
publishes. D-35 makes vendor limits a CONCURRENCY input, and an unbounded sweep is a
self-inflicted rate-limit incident that arrives on a schedule. Three bounds, each chosen
against that arithmetic rather than for looking tidy:

1. **`KB_SWEEP_BATCH_SIZE = 15` agents per tick**, stalest first (`claim_kb_drift_batch`).
   Smaller than the agent sweep's 25 for the amplification above. The ordering is what
   makes a per-tick cap fair rather than starving: writing `kb_drift_checked_at` is what
   moves a row to the back of the queue, so every live agent is reached without a cursor.
2. **`KB_SWEEP_BUDGET_S = 180` of wall clock**, checked BETWEEN reads. The batch cap
   bounds the COUNT; this bounds the TIME, and they are different failures. Checked
   between reads rather than enforced with a timeout because cancelling a read in flight
   would leave a round trip paid for and nothing recorded.
3. **HOURLY, not half-hourly** (`KB_SWEEP_MINUTES`). 15 an hour is 360 agents a day — past
   the platform's horizon (client #1, ROADMAP) at one account listing every four minutes.
   The cadence is set by how fast the thing being watched moves: an agent's prompt changes
   whenever a client edits a greeting, a knowledge base changes when a price list does.
   :23 because the round numbers and :05/:07/:35/:37 already carry the outbox dispatcher,
   the execution reconciler, the stalled-pipeline probe and the AGENT drift sweep — adding
   an account-wide vendor listing to the busiest minute of the hour is a sweep that shows
   up in someone else's latency graph.

And, as with the agent sweep, **the schedule strictly exceeds the worst case**, asserted at
import (`_assert_the_tick_fits_its_interval`). That is what makes overlap structurally
impossible rather than prevented by a Redis lease: the campaign tick needs one because a
30-second interval genuinely cannot contain its own work; a sweep bounded to ~240 seconds
inside a 3,600-second interval cannot collide with itself. Choosing the cheaper instrument
is only honest if the relationship it depends on is checked, so it is.

WHY NOT ONE JOB PER AGENT: `engine_reconciliation`'s argument, unchanged. Fanning out N
arq jobs replaces a platform-wide budget we control with a queue depth we do not, and the
retry that matters is the NEXT TICK, which is free — a row that failed keeps its old
`kb_drift_checked_at` and is therefore first in the next batch.

HARD RULE 6. Every log line carries ids and counts. No source name, no chunk, no handle —
an `EngineKBRef` is a vendor-issued opaque id and there is no reason to log one, because
the count is what sizes the decision and the agent id is what locates it.

HARD RULE 2. This module never sees a vendor payload. `list_kb` returns `list[str]` of our
own `EngineKBRef` alias and the adapter has already done the filtering.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.kb.reconciliation import (
    KB_DRIFT_STATES_OUT_OF_SYNC,
    KbDriftCandidate,
    claim_kb_drift_batch,
    classify_kb_drift,
    handles_if_no_publish_in_flight,
    record_kb_drift,
)

log = get_logger(__name__)

#: Vendor KB listings read per tick. See the module docstring for why 15 and not 25.
KB_SWEEP_BATCH_SIZE = 15

#: Wall clock a tick may spend STARTING reads, in seconds. A read already in flight is
#: allowed to finish — cancelling it would spend the round trip and record nothing.
KB_SWEEP_BUDGET_S = 180.0

#: The schedule, in minutes past the hour. `settings.py` builds the `cron()` registration
#: from this constant so the schedule and the arithmetic that reasons about the schedule
#: cannot disagree — the shape `campaign_dispatch.TICK_SECONDS` and
#: `engine_reconciliation.SWEEP_MINUTES` established.
KB_SWEEP_MINUTES = frozenset({23})
KB_SWEEP_INTERVAL_S = 60 * 60


def _assert_the_tick_fits_its_interval() -> None:
    """Overlap is prevented by ARITHMETIC here, not by a lease, so the arithmetic is
    checked at import rather than asserted in a comment.

    Identical in form to `engine_reconciliation._assert_the_tick_fits_its_interval`, and
    it is a second function rather than a shared one deliberately: the two sweeps have
    different budgets and different intervals, and a helper taking both as arguments
    would be a place for a caller to pass the wrong pair. What matters is that each
    module's own numbers fail at IMPORT when somebody widens the batch or shortens the
    schedule — which is where a concurrency assumption that has stopped being true should
    fail, rather than at 00:23 with two sweeps splitting one vendor budget.

    The read in flight is bounded by the adapter's own request timeout, which this module
    may not import (hard rule 2). 60s is a deliberately generous stand-in — every adapter
    in the tree is well under it, and being wrong in this direction only makes the
    assertion stricter.
    """
    worst_case_s = KB_SWEEP_BUDGET_S + 60.0
    if worst_case_s >= KB_SWEEP_INTERVAL_S:
        raise AssertionError(
            f"a KB drift sweep can run for {worst_case_s}s inside a {KB_SWEEP_INTERVAL_S}s "
            "interval, so two sweeps can overlap and each spend the vendor budget the "
            "other is counting on. Either lower KB_SWEEP_BUDGET_S/KB_SWEEP_BATCH_SIZE, "
            "widen KB_SWEEP_MINUTES, or take a single-flight lease the way "
            "campaign_dispatch does."
        )


_assert_the_tick_fits_its_interval()


@dataclass(frozen=True, slots=True)
class _Observation:
    """What one agent's round trip saw, held until the tick can classify it.

    Classification is deferred to the END of the tick because one input to it —
    `classify_kb_drift`'s `listing_attributes_by_agent` — is a fact about the TICK, not
    about the agent: an empty listing only becomes evidence once something in this tick
    has shown that the vendor's listing attributes rows to agents at all. See `_sweep`.
    """

    candidate: KbDriftCandidate
    #: The handles the engine listed, or None when the read itself failed.
    attached: frozenset[str] | None
    #: The handles our rows record, observed at an instant no publish was in flight.
    recorded: frozenset[str]


async def _observe_one(engine_name: str, candidate: KbDriftCandidate) -> _Observation | None:
    """One vendor round trip, bracketed by two reads of our own rows. None = no observation.

    THE BRACKET IS THE POINT and `handles_if_no_publish_in_flight` carries the argument:
    `publish_source` guarantees a stretch in which the engine holds fewer documents than
    our rows record, so a single unsynchronised read would report every routine price-list
    update as a divergence. Read one gates the round trip; read two proves nothing moved
    while it was in the air. Either failing the try-lock, or the two disagreeing, is a
    SKIP — not a verdict — and the skip costs nothing because the row keeps its old
    `kb_drift_checked_at` and leads the next batch.

    **None, NOT a verdict, for every non-outcome**, the distinction `_reconcile_one` draws
    for the agent sweep: `checked` must mean "we read the engine back and scored it", so
    counting an agent we deliberately stepped over would inflate the number an operator
    reads as coverage — and stamping a state for it would put an entry on the console that
    describes nothing that was measured.

    A FAILED READ IS AN OBSERVATION, not a skip: `unreachable` is a real thing to know
    about an agent, and it is what stops one sick agent failing the tick for the other
    fourteen. It short-circuits the second bracket read, which has nothing left to bracket.
    """
    async with tenant_session(candidate.tenant_id) as session:
        before = await handles_if_no_publish_in_flight(session, agent_id=candidate.agent_id)
    if before is None:
        return None

    try:
        attached: frozenset[str] | None = frozenset(await engine_list_kb(candidate))
    except Exception as exc:
        # Deliberately broad, and it does NOT swallow: the verdict below is the record.
        # `ProblemError` is what a well-behaved adapter raises, but an adapter is a network
        # client and the failure that matters most here is the one nobody normalized — a
        # timeout, a TLS error, a vendor answering HTML. Letting that escape would fail the
        # tick for the other fourteen agents, which is the outcome `unreachable` exists to
        # prevent. The type is logged so an operator can tell a refusal from a hang.
        log.warning(
            "kb_drift_sweep_unreachable",
            extra={
                "agent_id": str(candidate.agent_id),
                "engine": engine_name,
                "reason": type(exc).__name__,
            },
        )
        return _Observation(candidate=candidate, attached=None, recorded=before)

    async with tenant_session(candidate.tenant_id) as session:
        after = await handles_if_no_publish_in_flight(session, agent_id=candidate.agent_id)
    if after is None or after != before:
        log.info(
            "kb_drift_sweep_skipped_mid_publish",
            extra={"agent_id": str(candidate.agent_id), "engine": engine_name},
        )
        return None
    return _Observation(candidate=candidate, attached=attached, recorded=after)


async def engine_list_kb(candidate: KbDriftCandidate) -> list[str]:
    """The one vendor call this sweep makes, behind a name a test can assert on.

    Extracted so `test_the_sweep_only_ever_reads` can prove, by call inventory, that the
    module reaches for `list_kb` and never `attach_kb` or `detach_kb`, and so the
    `get_engine()` lookup happens per call rather than being captured in a closure at
    import — the engine is selectable at runtime (`platform_settings`).
    """
    return list(await get_engine().list_kb(candidate.engine_agent_ref))


async def _sweep() -> str:
    """One tick: the stalest live agents' knowledge read back, then scored, then recorded.

    TWO PHASES, and the split is not incidental. `classify_kb_drift` needs to know whether
    the vendor's listing attributes rows to agents AT ALL before it may read an empty
    listing as "the documents are gone" — pilot gate 8's `kb_list_carries_agent_linkage`
    is open, and `bolna.list_kb` filters on a field whose existence is a hand-maintained
    claim. The evidence that it does exist is any non-empty listing in this tick, and that
    is only known once the reads are done. So phase one gathers observations at the cost
    of the vendor round trips, and phase two scores them all against the same control.

    The control is deliberately the TICK and not a stored flag: a persisted "linkage was
    once observed" would keep asserting a vendor behaviour long after the vendor changed
    it, and a flag nobody re-derives is exactly the unverified premise D-31/D-32 exist to
    forbid. The cost of keeping it in-tick is honest and stated: on a platform where no
    agent in the batch lists anything, every agent that should hold knowledge reads
    `unreadable`. That is the true answer, it is visible on the ops console as a rising
    `undetermined`, and it is a far better failure than a fleet-wide false alarm.

    A tick that dies between the phases records nothing, which is the same outcome as a
    tick that dies at all: the rows keep their old `kb_drift_checked_at` and lead the next
    batch. Nothing is lost but the vendor calls.

    THE ALERT fires on the PROVEN divergences only (`KB_DRIFT_STATES_OUT_OF_SYNC`).
    `unreadable` and `unreachable` are held out for `agents/verification.py`'s reason: "we
    could not tell" is not evidence, and an alarm that fires whenever a vendor is briefly
    slow is an alarm somebody mutes long before it ever catches a real dashboard edit.
    """
    engine = get_engine()
    if not engine.capabilities.has("knowledge_base"):
        # An engine with no built-in knowledge base has nothing for this sweep to read,
        # and asking anyway would record `unreachable` for every live agent — a permanently
        # red console describing a capability the platform never had. `publish_source`
        # refuses on the same capability, so on such an engine there are no attachments to
        # have drifted. (D-93's fallback — our own in-call RAG — is a different milestone
        # and would need its own reconciliation, not this one.)
        log.info("kb_drift_sweep_no_knowledge_base", extra={"engine": engine.name})
        return "checked=0 drifted=0"

    async with untenanted_session() as session:
        batch = await claim_kb_drift_batch(session, engine=engine.name, limit=KB_SWEEP_BATCH_SIZE)
    if not batch:
        return "checked=0 drifted=0"

    started = time.monotonic()
    observations: list[_Observation] = []
    skipped = 0
    for candidate in batch:
        if time.monotonic() - started >= KB_SWEEP_BUDGET_S:
            # Not a failure and not a retry: the agents we did not reach kept their old
            # `kb_drift_checked_at`, so they lead the next tick by construction. Logged
            # because a sweep that ROUTINELY runs out of budget is a sweep whose batch size
            # no longer matches how slow the vendor's account listing has become.
            log.warning(
                "kb_drift_sweep_budget_exhausted",
                extra={
                    "engine": engine.name,
                    "observed": len(observations),
                    "batch": len(batch),
                },
            )
            break
        observation = await _observe_one(engine.name, candidate)
        if observation is None:
            skipped += 1
            continue
        observations.append(observation)

    # THE POSITIVE CONTROL. Any non-empty listing in this tick proves the vendor's KB list
    # carries the agent linkage the adapter filters on, which is what licenses reading an
    # EMPTY listing as evidence rather than as "we could not tell".
    listing_attributes_by_agent = any(observation.attached for observation in observations)

    verdicts: dict[str, int] = {}
    async with untenanted_session() as session:
        for observation in observations:
            state = classify_kb_drift(
                attached=observation.attached,
                recorded=observation.recorded,
                listing_attributes_by_agent=listing_attributes_by_agent,
            )
            recorded = await record_kb_drift(
                session,
                engine=engine.name,
                ref=observation.candidate.engine_agent_ref,
                state=state,
            )
            if not recorded:
                # The route was deleted between the batch read and now — the agent was
                # unpublished mid-sweep. Nothing to record and nothing wrong; it must not
                # count as coverage either.
                skipped += 1
                continue
            verdicts[state] = verdicts.get(state, 0) + 1

    drifted = sum(
        count for state, count in verdicts.items() if state in KB_DRIFT_STATES_OUT_OF_SYNC
    )
    checked = sum(verdicts.values())
    log.info(
        "kb_drift_sweep",
        extra={
            "engine": engine.name,
            "checked": checked,
            "drifted": drifted,
            # Agents in the batch that produced no verdict — mid-publish, moved under us,
            # or unpublished between the batch read and the record. A tick that is mostly
            # skips is a tick whose batch is stale, and that is worth seeing.
            "skipped": skipped,
            "listing_attributes_by_agent": listing_attributes_by_agent,
            **verdicts,
        },
    )
    if drifted:
        alert(
            # `WORKER_STALL`, following `sweep_engine_drift` and `report_stalled_pipeline`
            # rather than inventing a stage. The enum answers "where in the pipeline did
            # this die", and this alarm is not about a worker dying at all — it is a
            # scheduled PROBE reporting a bad state of the world it went and measured.
            # Adding a member for one alarm would make the enum a list of alarms.
            "WORKER_STALL",
            "engine_kb_drift_detected",
            # Counts and an engine name. The agent ids are in the per-agent rows and on the
            # console; an alert body is not the place for a list, and a source name would
            # be a tenant's own content in an email (hard rule 6).
            detail=(
                f"{drifted} of {checked} live agents hold knowledge on the voice platform "
                "that does not match what was approved and published"
            ),
        )
    return f"checked={checked} drifted={drifted}"


async def sweep_kb_drift(ctx: dict[str, Any]) -> str:
    """THE JOB. Read the stalest live agents' knowledge back off the engine; record it.

    IDEMPOTENT AND KEYED. Idempotent because it is a read whose only write is an
    observation stamped with the instant it was made: running it twice produces the same
    row, and the second run is at worst wasted vendor budget. Keyed by the cron's own arq
    id (`f'{name}:{to_unix_ms(next_run)}'`), which dedupes two WORKERS racing the same
    tick — there is no natural business key, because the unit of work is "the 15 stalest
    right now", not a named object.

    THE RETRY LADDER, spelled here rather than left to `max_tries`. arq 0.28 retries a job
    for `arq.Retry` and for nothing else — a job that fails by raising anything else is
    finished on its first attempt, whatever `max_tries` says. So a sweep that could not run
    AT ALL (the batch read failed, Postgres was unreachable) must ask for the retry
    explicitly, or every client's published knowledge goes unwatched until the next hour
    with nothing marked wrong. Three attempts, then an ALERT — not a dead-letter queue,
    which this docstring used to name and which does not exist (P6.5). An exhausted arq
    job is `zrem`'d off the queue and written to a result key nothing in this repository
    reads, so the alert on the last attempt IS the dead-letter mechanism.

    A VENDOR failure is deliberately NOT in scope: `_observe_one` converts one into a
    recorded `unreachable` for that agent, and re-running the whole sweep because one
    agent's listing was slow would spend the other fourteen's budget twice.
    """
    try:
        return await _sweep()
    except Exception as exc:
        log.warning(
            "kb_drift_sweep_failed",
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
            "kb_drift_sweep_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); "
                "every client's published knowledge is unwatched until this cron succeeds"
            ),
        )
        raise


__all__ = [
    "KB_SWEEP_BATCH_SIZE",
    "KB_SWEEP_BUDGET_S",
    "KB_SWEEP_INTERVAL_S",
    "KB_SWEEP_MINUTES",
    "sweep_kb_drift",
]
