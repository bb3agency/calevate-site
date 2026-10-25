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
from calevate_shared.backoff import jittered_delay_s
from calevate_shared.engine import RecallOutcome, VoiceEngine
from sqlalchemy import text

from apps.api.compliance.dnc_recall import RECALL_CAUSE_CONSENT
from apps.api.compliance.models import (
    CALLBACK_CONSENT_WITHDRAWN_REASON,
    CALLBACK_SUPPRESSED_REASON,
)
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.reliability.service import enqueue_outbox
from apps.workers.dial_recall import QueuedDial, close_called_off_dial
from apps.workers.retention import CALLBACK_ERASED_REASON

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

#: An alert naming forty uuids is one nobody reads.
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


async def _stamp(
    tenant_id: UUID, call_ids: list[UUID], *, called_off_reason: str | None = None
) -> None:
    """The one-way stamp both recall paths share, so neither re-stops the other's work.

    ITS OWN COMMITTED TRANSACTION, PER DIAL, AND THAT IS THE POINT (see `_recall`). Batched
    after the loop it was a stamp that only existed if the loop finished, which is the one
    condition under which it was needed.

    `called_off_reason`, given for a dial the platform says it cancelled before ringing,
    also closes the row as never connected and settles its campaign contact and call-back
    as refused for the person (`dial_recall.close_called_off_dial`; the reason is what the
    client reads on the call-back), in the same transaction: a redelivery skips stamped
    dials, so a stamp committed without it would leave the row `queued` for good.

    A list rather than one id because `dial_recall._stamp_recalled` takes a list and the
    two are read side by side; the caller passes one.
    """
    async with tenant_session(tenant_id) as session:
        if called_off_reason is not None:
            for call_id in call_ids:
                await close_called_off_dial(session, call_id, person_reason=called_off_reason)
        await session.execute(
            text(
                "UPDATE calls SET recall_requested_at = now(), updated_at = now() "
                "WHERE id = ANY(:ids) AND recall_requested_at IS NULL"
            ),
            {"ids": call_ids},
        )


async def _has_not_rung(engine: VoiceEngine, dial: QueuedDial) -> bool:
    """The vendor's own status says this dial is still waiting to ring (ThinnestAI's
    `scheduled`, our `queued`). Read rather than taken from our row, which on ThinnestAI
    stays `queued` while the phone rings."""
    snapshot = await engine.get_execution(dial.engine_call_id)
    return snapshot.status == "queued" and not snapshot.terminal


async def _stop_dials(
    engine: VoiceEngine, dials: list[QueuedDial], *, unrung_only: bool, callback_reason: str
) -> tuple[dict[RecallOutcome, list[UUID]], list[UUID], list[UUID]]:
    """Ask the engine to stop each dial; the verdicts, the dials it refused or could not be
    asked about, and (with `unrung_only`) the dials left alone because they had rung.

    `unrung_only` is the erasure's rule: a booked dial is called off, but a phone already
    ringing or a call already answered is not hung up on. A dial that starts ringing
    between the read and the stop is ended on the line and comes back `ALREADY_RUNNING`.
    `callback_reason` is what a call-back the stop calls off says to the client."""
    verdicts: dict[RecallOutcome, list[UUID]] = defaultdict(list)
    refused: list[UUID] = []
    rung: list[UUID] = []
    for dial in dials:
        try:
            if unrung_only and not await _has_not_rung(engine, dial):
                rung.append(dial.call_id)
                continue
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
        # STAMPED PER DIAL, NOT AFTER THE LOOP. Batched at the end, the stamp existed only
        # if the loop ran to completion, and the loop not completing is the condition the
        # stamp is for: a redeploy or a `job_timeout` arrives as `CancelledError`, which the
        # `except` above does not catch. The retry then re-POSTed a stop for every dial
        # already stopped, the vendor refused each one, and those refusals fired
        # `dnc_recall_undetermined` ("may have been called AFTER the suppression was
        # recorded") for dials that had been stopped: a false alarm on a DNC control is the
        # one an operator learns to mute. One single-row UPDATE beside a vendor round trip.
        await _stamp(
            dial.tenant_id,
            [dial.call_id],
            called_off_reason=callback_reason if outcome is RecallOutcome.PREVENTED else None,
        )
    return verdicts, refused, rung


#: The erased dials still to be asked about: the enqueue's predicates again, because a
#: dial may have settled, or a delivery of this same message may have stopped it, since
#: the erasure committed.
_ERASED_DIALS_SQL = (
    "SELECT id, engine_call_id FROM calls WHERE id = ANY(CAST(:ids AS uuid[])) "
    "AND direction = 'outbound' AND status IN ('queued', 'ringing') "
    "AND recall_requested_at IS NULL AND engine_call_id NOT LIKE 'local:%' "
    "ORDER BY created_at, id LIMIT :limit"
)

#: Of the dials called off, those an erasure owes the platform's copy of
#: (`compliance/engine_content`) and that copy is not yet deleted.
_CONTENT_OWED_SQL = (
    "SELECT id FROM calls WHERE id = ANY(CAST(:ids AS uuid[])) "
    "AND engine_content_delete_requested_at IS NOT NULL AND engine_content_deleted_at IS NULL "
    "ORDER BY id"
)


async def _ask_content_deleted(tenant_id: UUID, call_ids: list[UUID]) -> int:
    """Owe the platform's copy of dials it cancelled before they rang, now.

    `queue_engine_content_deletion` marked these at the erasure and held them back: our row
    still read `queued`, and the platform answers 409 for a call booked and not rung
    (delete-call-content.md:506-509). A dial the platform says it cancelled before ringing
    recorded nothing, and `_stamp` has closed its row as never connected, which
    `engine_content._READY_SQL` lets through, so it need not wait for the daily backstop.
    """
    if not call_ids:
        return 0
    async with tenant_session(tenant_id) as session:
        owed = (
            (await session.execute(text(_CONTENT_OWED_SQL), {"ids": [str(c) for c in call_ids]}))
            .scalars()
            .all()
        )
        if owed:
            # The literal, so `scripts/check_job_wiring` reads the job name at its enqueue site.
            await enqueue_outbox(
                session,
                job="delete_engine_call_content",
                payload={"tenant_id": str(tenant_id), "call_ids": [str(c) for c in owed]},
            )
    return len(owed)


async def _recall_erased(tenant_id: UUID, call_ids: list[str], scope: str) -> str:
    """An erasure's recall: call off the erased dials the vendor booked and has not rung."""
    engine = get_engine()
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(_ERASED_DIALS_SQL), {"ids": call_ids, "limit": DNC_RECALL_SCAN_LIMIT}
            )
        ).all()
    dials = [QueuedDial(tenant_id, UUID(str(r[0])), str(r[1])) for r in rows]
    if not dials:
        log.info("erasure_recall_nothing_booked", extra={"tenant_id": str(tenant_id)})
        return "found=0"

    verdicts, refused, rung = await _stop_dials(
        engine, dials, unrung_only=True, callback_reason=CALLBACK_ERASED_REASON
    )
    prevented = verdicts[RecallOutcome.PREVENTED]
    undetermined = (
        verdicts[RecallOutcome.ALREADY_RUNNING] + verdicts[RecallOutcome.UNKNOWN] + refused
    )
    content_owed = await _ask_content_deleted(tenant_id, prevented)
    # A tenant erasure can name more dials than one run asks about. The rest go to a run of
    # their own rather than an alarm: the list only shrinks, so the chain ends.
    reached = {str(dial.call_id) for dial in dials}
    rest = [c for c in call_ids if c not in reached] if len(dials) >= DNC_RECALL_SCAN_LIMIT else []
    if rest:
        async with tenant_session(tenant_id) as session:
            await enqueue_outbox(
                session,
                job=DNC_RECALL_JOB,
                payload={"tenant_id": str(tenant_id), "erasure": scope, "call_ids": rest},
            )
    log.info(
        "erasure_recall",
        extra={
            "engine": engine.name,
            "tenant_id": str(tenant_id),
            "scope": scope,
            "found": len(dials),
            "prevented": len(prevented),
            # Already ringing, answered or ended when read: left alone by decision. Records
            # such a call produces re-file the erasure (`deletion.refile_erasure_for_late_records`).
            "rung": len(rung),
            "undetermined": len(undetermined),
            "content_deletion_queued": content_owed,
            "continued": len(rest),
        },
    )
    if undetermined:
        named = ", ".join(str(c) for c in undetermined[:_ALERT_ID_LIMIT])
        alert(
            "WORKER_STALL",
            "dnc_recall_undetermined",
            detail=(
                f"{len(undetermined)} of {len(dials)} booked dial(s) to a person whose data "
                "was erased could not be confirmed called off before ringing: the platform "
                "had started them, did not say what it caught, or refused. Call ids: "
                f"{named}"
            ),
            episode="erasure",
            tenant_id=str(tenant_id),
        )
    return (
        f"found={len(dials)} prevented={len(prevented)} rung={len(rung)} "
        f"undetermined={len(undetermined)}"
    )


async def _recall(phones: list[str], tenant_id: UUID | None, *, callback_reason: str) -> str:
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

    verdicts, refused, _rung = await _stop_dials(
        engine, dials, unrung_only=False, callback_reason=callback_reason
    )

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
        # BEFORE the verdict alarm, because a
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
            # WORKER_STALL because this is a scheduled action
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


def _callback_reason(payload: dict[str, Any]) -> str:
    """What a call-back this recall calls off says: the sentence its suppression's own door
    writes (`compliance.models`), so the client cannot tell which path stopped it. A
    payload without `cause` predates it and came from a do-not-call entry."""
    if payload.get("cause") == RECALL_CAUSE_CONSENT:
        return CALLBACK_CONSENT_WITHDRAWN_REASON
    return CALLBACK_SUPPRESSED_REASON


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

    THE RETRY LADDER IS SPELLED HERE because arq 0.28
    retries for `arq.Retry` and nothing else, so a job that dies any other way is finished
    on its first attempt whatever `max_tries` says. Three attempts, then an ALERT — there
    is no dead-letter queue (P6.5), so the alert on the last attempt IS the dead-letter
    mechanism, and here it has to be loud: an abandoned recall means a suppression that
    never reached the queue and nobody looking.

    AN ERASURE USES IT TOO (`compliance/dnc_recall.enqueue_erasure_recall`): an erased
    number is refused for new dials like a suppressed one, and the dials already booked to
    it are pulled back by the same stop. Its payload names `erasure` and call ids instead
    of numbers, and only dials the vendor still holds unrung are stopped.
    """
    phones = [str(p) for p in payload.get("phones") or []]
    raw_tenant = payload.get("tenant_id")
    tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
    erasure = payload.get("erasure")
    call_ids = [str(c) for c in payload.get("call_ids") or []]
    if erasure and (tenant_id is None or not call_ids):
        log.warning("erasure_recall_empty_payload")
        return "found=0"
    if not erasure and not phones:
        # Not an error and not retried: `enqueue_dnc_recall` refuses to enqueue an empty
        # list, so this is a payload from an older release or a hand-made one.
        log.warning("dnc_recall_empty_payload")
        return "found=0"

    try:
        if erasure and tenant_id is not None:
            return await _recall_erased(tenant_id, call_ids, str(erasure))
        return await _recall(phones, tenant_id, callback_reason=_callback_reason(payload))
    except Exception as exc:
        log.warning(
            "dnc_recall_job_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=jittered_delay_s(15 * attempt)) from exc
        alert(
            "WORKER_TERMINAL",
            "dnc_recall_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); dials to a newly "
                + ("erased" if erasure else "suppressed")
                + " number were never pulled back from the voice platform and may still "
                "ring. New dials to it are refused from the next dispatch tick"
            ),
            episode="erasure" if erasure else None,
        )
        raise


__all__ = ["DNC_RECALL_JOB", "DNC_RECALL_SCAN_LIMIT", "recall_dials_for_dnc"]
