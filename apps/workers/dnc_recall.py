"""A suppression reaches the dials the vendor is already holding — D-428(b).

WHAT WAS OPEN. D-428 split the recall in two and shipped only the halt half. A DNC
addition closed `check_dispatch` for the next tick and never reached the queue: `POST
/call` answers `queued` for every dial, and over the account's concurrency ceiling the
surplus waits in a queue we cannot see, cancel or scrub. So a number suppressed at 20:58
could ring at 21:01 from a dial accepted before the suppression existed — with our records
showing the contact lawfully cleared, because it was, at the moment it was checked.

WHY THIS IS A SEPARATE JOB FROM `dial_recall`, and not a parameter on it. The two differ in
the only way that matters here: what they are allowed to CLAIM afterwards.

* The halt is best-effort by decision. It stops what it can and its alarm says outright
  that a dial which started ringing will run to its end. Nobody asks it to prove anything.
* A suppression may have to be defended. "Prove this number was not called after we were
  told to stop" is a question a TSP or a regulator can ask, `consent_ledger` is append-only
  so a wrong answer can only be compensated rather than corrected, and the honest answer
  depends on something the halt path never needed: whether the vendor caught this dial
  BEFORE the phone rang.

So this job reads `RecallOutcome`, which the halt job ignores, and reports the three
answers separately. `PREVENTED` is the vendor's own adjudication — their stop route says
`status: stopped` and documents itself as cancelling "pending calls before they are
executed". `ALREADY_RUNNING` and `UNKNOWN` are both "we cannot say this number was not
called", and are alarmed rather than counted quietly, because they are the cases a person
has to know about.

WHAT IT DOES NOT DO. It records no ledger row and writes no consent fact. `calls` already
answers "was this number dialled" and is the one place that question is asked; a second
record of the same fact, in a table whose rows cannot be corrected, is how two sources of
truth start disagreeing. What this job adds is the STAMP (`recall_requested_at`, shared
with the halt path so both are idempotent) and an alarm naming what it could not prevent.

HARD RULE 6. No phone number reaches a log line or an alert body here. The numbers arrive
in the payload because the scan has to match on them, and they are counted, never printed
— an operator gets call ids, which is what `runbooks/dnc-complaint.md` needs anyway.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from arq import Retry
from calevate_shared.engine import RecallOutcome
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.workers.dial_recall import QueuedDial

log = get_logger(__name__)

#: The ARQ function name, registered in `apps/workers/settings.FUNCTIONS`. The outbox
#: dispatcher publishes `job` verbatim, so this string IS the contract with the worker.
DNC_RECALL_JOB = "recall_dials_for_dnc"

#: How many queued dials one suppression will try to pull back.
#:
#: Far smaller than `dial_recall.RECALL_SCAN_LIMIT` (500) and deliberately so: that one is
#: a fleet-wide emergency stop, this one is "the dials to THESE numbers". A single number
#: can have at most a handful queued — the outbound pool drains at the account's
#: concurrency ceiling — so a run that reaches this cap is a bulk import of thousands of
#: suppressions, where the cap is a floor to report rather than a limit to raise.
DNC_RECALL_SCAN_LIMIT = 100

#: For `engine_violations._ALERT_ID_LIMIT`'s reason: an alert naming forty uuids is one
#: nobody reads.
_ALERT_ID_LIMIT = 5


async def _queued_dials_to(
    phones: list[str], tenant_id: UUID | None, limit: int
) -> list[QueuedDial]:
    """Every queued dial to one of `phones`, in one tenant or across the fleet.

    The SAME `queued_dial_scan` the halt uses, with its two filters supplied (migration
    a7e3b91c04df). Not a second scan function: the hard part is the SECURITY INVOKER
    tenant loop — `calls` is FORCE-RLS'd, so an untenanted probe returns zero rows for
    every tenant and reads exactly like an empty queue — and two copies of that would
    answer differently the day one of them was fixed.

    `tenant_id is None` means a GLOBAL suppression, which outranks every tenant's own list
    and therefore has to reach every tenant's queue.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT scanned_tenant_id, call_id, engine_call_id "
                    "FROM queued_dial_scan(:limit, :phones, :tenant)"
                ),
                {"limit": limit, "phones": phones, "tenant": tenant_id},
            )
        ).all()
    return [QueuedDial(UUID(str(r[0])), UUID(str(r[1])), str(r[2])) for r in rows]


async def _stamp(tenant_id: UUID, call_ids: list[UUID]) -> None:
    """The one-way stamp both recall paths share, so neither re-stops the other's work."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET recall_requested_at = now(), updated_at = now() "
                "WHERE id = ANY(:ids) AND recall_requested_at IS NULL"
            ),
            {"ids": call_ids},
        )


async def _recall(phones: list[str], tenant_id: UUID | None) -> str:
    """One suppression's worth of recall, and the verdict for each dial it reached."""
    engine = get_engine()
    dials = await _queued_dials_to(phones, tenant_id, DNC_RECALL_SCAN_LIMIT)
    if not dials:
        # The overwhelmingly common case, and it is a real answer rather than a no-op:
        # nothing was queued to these numbers, so the suppression cost nothing to honour.
        log.info(
            "dnc_recall_nothing_queued",
            extra={"engine": engine.name, "numbers": len(phones), "scoped": tenant_id is not None},
        )
        return "found=0"

    stamped: dict[UUID, list[UUID]] = defaultdict(list)
    verdicts: dict[RecallOutcome, list[UUID]] = defaultdict(list)
    refused: list[UUID] = []

    for dial in dials:
        try:
            outcome = await engine.end_call(dial.engine_call_id)
        except Exception as exc:
            # ONE DIAL'S FAILURE IS NOT THE RUN'S, `dial_recall`'s argument: abandoning the
            # loop at the first refusal leaves the rest queued and reports a number that
            # reads smaller and healthier than the truth. A refusal here is also the most
            # likely single outcome — the vendor refuses a call that has already left the
            # queue, which is exactly the race this job exists to measure.
            log.warning(
                "dnc_recall_failed",
                extra={"call_id": str(dial.call_id), "reason": exc.__class__.__name__},
            )
            refused.append(dial.call_id)
            continue
        verdicts[outcome].append(dial.call_id)
        stamped[dial.tenant_id].append(dial.call_id)

    for scoped_tenant, call_ids in stamped.items():
        await _stamp(scoped_tenant, call_ids)

    prevented = verdicts[RecallOutcome.PREVENTED]
    # EVERYTHING THAT IS NOT `PREVENTED`, together, because the distinction that matters to
    # a person is binary: can we say this number was not called, or not. `ALREADY_RUNNING`
    # and `UNKNOWN` differ in why we cannot say it, which the log carries and the alarm
    # does not need to.
    undetermined = (
        verdicts[RecallOutcome.ALREADY_RUNNING] + verdicts[RecallOutcome.UNKNOWN] + refused
    )

    log.info(
        "dnc_recall",
        extra={
            "engine": engine.name,
            "numbers": len(phones),
            "found": len(dials),
            "prevented": len(prevented),
            "already_running": len(verdicts[RecallOutcome.ALREADY_RUNNING]),
            "unknown": len(verdicts[RecallOutcome.UNKNOWN]),
            "refused": len(refused),
            "capped": len(dials) >= DNC_RECALL_SCAN_LIMIT,
        },
    )

    if len(dials) >= DNC_RECALL_SCAN_LIMIT:
        # BEFORE the verdict alarm, for `engine_violation_sweep_incomplete`'s reason: a
        # capped run's counts are a floor, and "prevented 100" off a scan that stopped
        # looking at 100 is the one wrong sentence to leave on this screen.
        alert(
            "WORKER_STALL",
            "dnc_recall_incomplete",
            detail=(
                f"the DNC recall scan hit its {DNC_RECALL_SCAN_LIMIT}-dial cap, so more "
                "dials to these suppressed numbers may still be queued at the vendor"
            ),
        )

    if undetermined:
        named = ", ".join(str(c) for c in undetermined[:_ALERT_ID_LIMIT])
        alert(
            # WORKER_STALL for `engine_violation_open`'s reason: a scheduled action
            # reporting a bad state of the world it measured, not a worker dying. Nothing
            # is retried by reporting it — these dials are past recalling.
            "WORKER_STALL",
            "dnc_recall_undetermined",
            detail=(
                f"{len(undetermined)} of {len(dials)} dial(s) to a newly suppressed number "
                "could not be confirmed as prevented — the engine had already started them, "
                "or did not say what it caught. These numbers may have been called AFTER "
                f"the suppression was recorded. Call ids: {named}"
            ),
        )

    return f"found={len(dials)} prevented={len(prevented)} undetermined={len(undetermined)}"


async def recall_dials_for_dnc(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """THE JOB. Pull back the queued dials to numbers a suppression just covered.

    ENQUEUED THROUGH THE OUTBOX, in the same transaction as the `dnc_list` insert
    (`compliance/dnc_recall.py`), so a suppression that rolls back cannot leave a recall
    chasing dials nobody suppressed — and one that commits cannot lose its recall to a
    crash between the two writes.

    IDEMPOTENT. `recall_requested_at` is a one-way stamp shared with the halt path, so a
    retried attempt re-scans, finds the dials it already stopped excluded, and stops
    nothing twice. Without it a second run would re-POST a stop for every dial the first
    already stopped, take the vendor's refusal for an already-stopped execution, and
    report those as undetermined — turning a clean recall into a compliance alarm.

    THE RETRY LADDER IS SPELLED HERE for `sweep_engine_violations`' reason: arq 0.28
    retries for `arq.Retry` and nothing else, so a job that dies any other way is finished
    on its first attempt whatever `max_tries` says. Three attempts, then an ALERT — there
    is no dead-letter queue (P6.5), so the alert on the last attempt IS the dead-letter
    mechanism, and here it has to be loud: an abandoned recall means a suppression that
    never reached the queue and nobody looking.
    """
    phones = [str(p) for p in payload.get("phones") or []]
    raw_tenant = payload.get("tenant_id")
    tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
    if not phones:
        # Not an error and not retried: `enqueue_dnc_recall` refuses to enqueue an empty
        # list, so this is a payload from an older release or a hand-made one.
        log.warning("dnc_recall_empty_payload")
        return "found=0"

    try:
        return await _recall(phones, tenant_id)
    except Exception as exc:
        log.warning(
            "dnc_recall_job_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=15 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "dnc_recall_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); dials to a newly "
                "suppressed number were never pulled back from the voice platform and may "
                "still ring. The suppression itself is in force for the next dispatch tick"
            ),
        )
        raise


__all__ = ["DNC_RECALL_JOB", "DNC_RECALL_SCAN_LIMIT", "recall_dials_for_dnc"]
