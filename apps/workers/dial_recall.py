"""The big red switch reaches the dials the carrier is already holding.

WHY THIS JOB EXISTS (D-432, closing the halt half of D-428). `outbound_halted` stops this
platform PLACING dials; it does nothing about a dial the carrier has already accepted. On
Vobiz an accepted dial is "accepted and queued, not answered"
(`vobiz-findings/mirror/pages/call/make-call.md:122-124`) and then rings for up to
the ring timeout (`engine/carrier.RING_TIMEOUT_S`). An operator throwing the switch
at 20:55 IST must not leave those phones ringing past 21:00, so this job asks the engine to
end every outbound dial that is still `queued` or `ringing` (migration b7e4c0a63f29 widened
the scan to `ringing`, which is where the carrier's `Ring` callback moves the row).

WHAT IT DOES NOT DO. A call somebody has answered (`in_progress`) is a conversation, and the
halt does not hang up on a person who is talking: it stops new dials and recalls unanswered
ones. A dial answered between the scan and the stop runs to its end.

IT READS THE ENGINE'S VERDICT (D-509). `end_call` returns a `RecallOutcome`, and only
`PREVENTED` is counted as stopped. The owned runtime answers `UNKNOWN` for every hang-up,
because Vobiz's hang-up answers 204 whether the call was queued or ringing
(`call/hangup-call.md:60`), so it can never prove the phone did not ring. Those dials are
reported as "ended, not proven unrung", which is the direction to be wrong in mid-incident.
Nothing here retries and nothing fails the halt because a stop failed: the halt is
best-effort by decision (D-428). `dnc_recall` reads the same verdict.

WHY IT IS FIRED BY THE HALT RATHER THAN CRONNED. The condition is a transition, not a
state: dials are only ever illegitimately in flight *because* somebody just halted, and a
cron would be a fleet-wide scan every N minutes for a thing that is almost never true.
`ops/routes.set_platform` enqueues it on the `false -> true` edge; the job re-reads the
halt before it stops anything, because an operator who halted and released inside the
job's queue latency must not have their campaign torn down behind them.

WHAT IT DOES NOT WRITE. Not the call's `status`. The carrier's hangup callback
(`workers/carrier_events`) moves the row terminal with the carrier's own cause, and a
`failed` written here first would be a second answer to a question the carrier owns. The
one thing this job stamps is `calls.recall_requested_at` — see migration d5c81f30ab47 for
why that column is what keeps a second halt from re-stopping every dial it already
stopped and then alarming about it.

HARD RULE 6. Every id here is a call row id, a tenant id, or the vendor's opaque
execution handle. No number and no transcript reaches this module.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, NamedTuple
from uuid import UUID

from arq import Retry
from calevate_shared.engine import RecallOutcome
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine

log = get_logger(__name__)

#: How many queued dials one run will try to pull back.
#:
#: A COUNT rather than the time budget `dispatcher.ERASURE_PROBE_BUDGET` uses, and the
#: distinction is `pipeline.OUTSTANDING_PROBE_BUDGET`'s: the cost per item here is one
#: VENDOR REQUEST, which is roughly fixed, so a count is a faithful proxy for wall clock.
#: 500 sequential stops at a conservative 200ms each is 100s, comfortably inside
#: `WorkerSettings.job_timeout` (300s) with room for the scan and the alert.
#:
#: It is also far above any real backlog: unanswered dials are bounded by the outbound line
#: pool (`engine/carrier_pacing.outbound_line_pool`), so a fleet that reaches this cap is one
#: whose numbers nobody here has seen. Hitting it is therefore reported as a FLOOR and
#: alarmed, never silently truncated.
RECALL_SCAN_LIMIT = 500

#: How many call ids an alert body names before it stops listing them: an alert naming
#: forty uuids is one nobody reads.
_ALERT_ID_LIMIT = 5


class QueuedDial(NamedTuple):
    """One dial the vendor is holding, as the scan sees it."""

    tenant_id: UUID
    call_id: UUID
    engine_call_id: str


async def _queued_dials(limit: int) -> list[QueuedDial]:
    """Every outbound dial still `queued` or `ringing` at the carrier, across the fleet.

    `queued_dial_scan()` is SECURITY INVOKER and loops the tenants with the GUC set to
    each in turn — `dispatch_scan`'s construction (a8d4f21c9b06), taken rather than
    re-invented, because `calls` is FORCE-RLS'd and the obvious untenanted probe returns
    zero rows for every tenant and reads exactly like an empty queue.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT scanned_tenant_id, call_id, engine_call_id "
                    "FROM queued_dial_scan(:limit)"
                ),
                {"limit": limit},
            )
        ).all()
    return [QueuedDial(UUID(str(r[0])), UUID(str(r[1])), str(r[2])) for r in rows]


async def _stamp_recalled(tenant_id: UUID, call_ids: list[UUID]) -> None:
    """Record that the vendor accepted a stop for these dials.

    Written per tenant under that tenant's own policies rather than untenanted, for hard
    rule 1's reason: there is no platform-wide write to `calls` in this tree and this is
    not the place to invent the first one.
    """
    if not call_ids:
        return
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET recall_requested_at = now(), updated_at = now() "
                "WHERE id = ANY(:ids) AND recall_requested_at IS NULL"
            ),
            {"ids": call_ids},
        )


async def _recall() -> str:
    """One run: pull back every queued dial the engine will let us pull back."""
    engine = get_engine()
    if not engine.holds_credentials():
        # An engine configured by name with no key cannot be asked to stop anything, and
        # the operator who just threw the switch must not read silence as success.
        alert(
            "WORKER_TERMINAL",
            "dial_recall_impossible",
            detail=(
                "outbound was halted but the voice platform holds no credentials here, so "
                "no queued dial could be recalled; dials already accepted by the vendor "
                "will ring"
            ),
        )
        return "skipped_no_credentials"

    status = await get_platform_status(force_refresh=True)
    if not status.outbound_halted:
        # Released between the enqueue and the run. Tearing down a campaign that an
        # operator has just deliberately resumed is the one wrong answer here.
        log.info("dial_recall_skipped", extra={"reason": "not_halted"})
        return "skipped_not_halted"

    dials = await _queued_dials(RECALL_SCAN_LIMIT)
    # PREVENTED ONLY. `stopped` used to mean "the vendor did not raise", which counted a
    # dial the vendor told us was already ringing as one we had stopped.
    prevented: dict[UUID, list[UUID]] = defaultdict(list)
    #: Answered, and NOT stopped: `ALREADY_RUNNING` (it rang) and `UNKNOWN` (the vendor
    #: said nothing about what it caught — silence is not a denial that the phone rang).
    #: Together because the distinction that matters to an operator mid-incident is binary:
    #: is this line quiet, or might it not be. `dnc_recall` folds the same two for the same
    #: reason, one rule along.
    still_live: list[UUID] = []
    unreachable: list[UUID] = []
    for dial in dials:
        try:
            outcome = await engine.end_call(dial.engine_call_id)
        except Exception as exc:
            # ONE DIAL'S FAILURE IS NOT THE RUN'S — `report_stalled_pipeline`'s argument,
            # and sharper here: the loop is what stops phones ringing, and abandoning it
            # at the first refusal would leave the rest of the batch queued while the job
            # reports a number that reads smaller and healthier than the truth.
            log.warning(
                "dial_recall_failed",
                extra={"call_id": str(dial.call_id), "reason": exc.__class__.__name__},
            )
            unreachable.append(dial.call_id)
            continue
        if outcome is RecallOutcome.PREVENTED:
            prevented[dial.tenant_id].append(dial.call_id)
        else:
            still_live.append(dial.call_id)
        # STAMPED HERE, NOT AFTER THE LOOP — `dnc_recall._recall` carries the full
        # argument and this is the same defect in the same shape. In short: batched at the
        # end, the stamp existed only if the loop finished, and the loop not finishing is
        # what it is for. The per-dial `except` above catches `Exception`; a redeploy or a
        # `job_timeout` arrives as `CancelledError`, which it does not. The re-run then
        # re-POSTs a stop for every dial the first run already stopped, takes the vendor's
        # refusal for an already-stopped execution, and reports them as `unstoppable` —
        # alarming `dial_recall_unstopped`, whose detail tells an operator mid-incident
        # that dials "will run to its end" when they were stopped on the first pass. One
        # indexed UPDATE beside a vendor round trip, on the path where being wrong is
        # most expensive.
        await _stamp_recalled(dial.tenant_id, [dial.call_id])

    total_prevented = sum(len(v) for v in prevented.values())
    # THE NUMBER AN OPERATOR ACTS ON. Everything we cannot say we stopped, together —
    # answered-but-running, answered-but-silent, and never answered at all.
    not_stopped = still_live + unreachable
    capped = len(dials) >= RECALL_SCAN_LIMIT
    log.info(
        "dial_recall",
        extra={
            "engine": engine.name,
            "found": len(dials),
            "prevented": total_prevented,
            "still_live": len(still_live),
            "unreachable": len(unreachable),
            "tenants": len(prevented),
            "capped": capped,
        },
    )

    if capped:
        # BEFORE the failure alarm, because a
        # capped run's counts are a floor, and "stopped 500" off a scan that stopped
        # looking at 500 is the one wrong sentence to leave on an operator's screen.
        alert(
            "WORKER_STALL",
            "dial_recall_incomplete",
            detail=(
                f"the recall scan hit its {RECALL_SCAN_LIMIT}-dial cap, so more dials may "
                "still be queued at the vendor; re-post the halt to run another pass"
            ),
        )

    if not_stopped:
        named = ", ".join(str(c) for c in not_stopped[:_ALERT_ID_LIMIT])
        alert(
            # WORKER_STALL because this is a scheduled action
            # reporting a bad state of the world it went and measured, not a worker dying.
            # Nothing is retried by reporting it — the vendor has refused these.
            "WORKER_STALL",
            "dial_recall_unstopped",
            detail=(
                f"{len(not_stopped)} of {len(dials)} unanswered dial(s) are not proven "
                f"stopped by the outbound halt ({len(still_live)} the voice platform ended "
                f"without confirming the phone had not rung, {len(unreachable)} it did not "
                "end at all). A dial answered between the scan and the stop runs to its "
                f"end. Call ids: {named}"
            ),
        )

    return (
        f"found={len(dials)} prevented={total_prevented} "
        f"still_live={len(still_live)} unreachable={len(unreachable)}"
    )


async def recall_queued_dials(ctx: dict[str, Any]) -> str:
    """THE JOB. After the big red switch, ask the engine to drop every dial it is holding.

    IDEMPOTENT AND KEYED. Idempotent because `recall_requested_at` is a one-way stamp the
    scan filters on: a re-run sees only the dials the last run did not stop. Keyed by
    arq's own job id — there is no business key to add, because the unit of work is "every
    dial the vendor is holding right now", and two runs racing that question converge on
    the same empty scan.

    THE RETRY LADDER IS SPELLED HERE because arq 0.28
    retries for `arq.Retry` and nothing else, so a job that dies any other way is finished
    on its first attempt whatever `max_tries` says. Note what CANNOT reach this handler —
    a single vendor refusal, which `_recall` counts and carries on past. What reaches it
    is the scan failing or the engine being unreachable, i.e. the recall not happening at
    all, which is a phone ringing after a halt and therefore a page.
    """
    try:
        return await _recall()
    except Exception as exc:
        log.warning(
            "dial_recall_run_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            # Climbing `defer`, BACKEND-PATTERNS §4's ladder — but a SHORT one, unlike the
            # violations sweep's 30s: every second of it is a dial the vendor may start
            # ringing, and `end_call` stops working the moment it does.
            raise Retry(defer=5 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "dial_recall_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); outbound is halted "
                "but dials already accepted by the voice platform were not recalled and "
                "will ring"
            ),
        )
        raise


__all__ = ["RECALL_SCAN_LIMIT", "recall_queued_dials"]
