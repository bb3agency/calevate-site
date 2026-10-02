"""Requested callbacks: the dial pass the campaign tick runs.

`dispatch_due_callbacks` is NOT an arq job. It is called by `campaign_dispatch._run_tick`,
inside the tick's own single-flight lease and out of the tick's own line budget, because a
callback and a campaign contact compete for the same lines and two schedulers with two
opinions about that is how a receptionist stops being able to answer the phone.

Callbacks are BOOKED elsewhere: in a call by the voice worker's `book_callback` tool
(`apps/api/worker/tools.book_callback`, inside the request), and after a call by the
post-call pipeline. Both write through `apps/api/callbacks/service.book`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from calevate_shared.calling_window import ist_wall_clock

from apps.api.agents.service import DialUnconfirmedError, dispatch_call
from apps.api.callbacks import service as callbacks
from apps.api.compliance.service import (
    BIG_RED_SWITCH_REASON,
    BIG_RED_SWITCH_RULE,
    PERSON_LEVEL_REFUSALS,
    DispatchDecision,
    check_dispatch,
)
from apps.api.core.alerting import record_compliance_block
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.workers.carrier_pacing import PACING_RULE, DialPacingTimeoutError, await_dial_slot

# The ingest job's retry ladder, its transience verdict and its tenant resolution, used
# rather than restated — `optout.py` imports the identical three for the identical reason
# and says so: this module asks the same questions of the same engine.

log = get_logger(__name__)


#: The most callbacks one tenant may be dialled in one tick. It is a fairness bound, not a
#: throughput one: a tenant whose morning produced forty promises must not spend the whole
#: shared pool at 09:00 and leave every other client's campaigns and receptionists waiting.
#: Five per thirty-second tick is ten a minute, which clears any realistic backlog inside
#: the grace window while never being more than half the outbound pool.
MAX_PER_TICK = 5

#: What a client is told when the vendor may or may not have rung the caller. The campaign
#: dispatcher's answer to the same situation, in a sentence rather than a status: never
#: retry a dial we cannot prove did not ring.
UNCONFIRMED_REASON = (
    "We started this call and did not hear back from the phone system, so it may have "
    "gone through. We will not try again in case it rings them twice."
)

#: ...and when the engine refused before dialling. One attempt, not a ladder: the promise
#: has a time on it, and the tick will come back inside the grace window anyway.
DIAL_FAILED_REASON = "The phone system would not place this call."

#: ...and when the carrier's calls-per-second limit left no slot for it this tick.
PACING_DEFERRED_REASON = "The phone line was busy starting other calls; we will try again shortly."

#: What the caller hears about, in the ledger sense, when they call their own callback off.
CANCELLED_BY_CALLER_REASON = "The caller asked us not to ring them back."


async def dispatch_due_callbacks(tenant_id: UUID, slots: int) -> dict[str, int]:
    """One tenant's slice of a tick: settle what is finished, expire what is stale, dial
    what is due. Returns `{"dialled", "blocked", "settled"}`.

    **THE SHAPE IS `_dispatch_for_campaign`'S, DELIBERATELY.** The claim commits before the
    first dial and every dial gets its own transaction, for the reason that function spells
    out at length: a single transaction around the batch means anything escaping the loop
    after the engine accepted a call — `CancelledError` from a deploy or a job timeout, a
    `BaseException` `except Exception` does not catch — rolls the CLAIM back too, and the
    next tick rings somebody whose phone has already rung. With the claim committed first
    that failure leaves the callback `dialing` against a committed `calls` row, and
    `settle_dialled` ends it without a second ring.

    **EVERY REFUSAL IS SETTLED OR RETRIED EXPLICITLY, AND NEITHER FOR EVER.**
    `PERSON_LEVEL_REFUSALS` — the gate's own classification, never a second opinion here —
    decides which; `callbacks.service.GRACE` is what bounds the retry side regardless of
    the classification, which is the part `tests/dispatch_refusal_settlement_test.py`'s
    three livelocks did not have.
    """
    dialled = blocked = 0
    async with tenant_session(tenant_id) as session:
        settled = await callbacks.settle_dialled(session)
        settled += await callbacks.expire_stale(session)
        due = await callbacks.claim_due(session, limit=min(slots, MAX_PER_TICK))
    # The claim is COMMITTED here. Everything below runs in its own short transaction.

    for callback in due:
        async with tenant_session(tenant_id) as session:
            # THE GATE (hard rule 5), per callback, at the moment of dialling. This is the
            # dispatch tick DNC additions must precede, and its DNC read is uncached — so a
            # number suppressed between the promise and its time is refused here, on this
            # very tick, whether or not anything cancelled the row first.
            #
            # The halt is read PAST the in-process memo first, for the reason
            # `campaign_dispatch._dispatch_for_campaign` gives: `_run_tick` primed that
            # memo before this loop, `check_dispatch` would answer from it for up to five
            # seconds after an operator halts in the API process, and a dial placed after
            # `dial_recall`'s one scan is never recalled by anything.
            if (await get_platform_status(force_refresh=True)).outbound_halted:
                decision = DispatchDecision(
                    allowed=False, rule=BIG_RED_SWITCH_RULE, reason=BIG_RED_SWITCH_REASON
                )
            else:
                decision = await check_dispatch(
                    session,
                    tenant_id=tenant_id,
                    agent_id=callback.agent_id,
                    phone_e164=callback.phone_e164,
                )
            if not decision.allowed:
                rule = decision.rule or "unknown"
                record_compliance_block(rule=rule)
                if rule in PERSON_LEVEL_REFUSALS:
                    # A fact about the PERSON. Waiting cannot lift it, so the promise ends
                    # now with the gate's own sentence on it rather than being retried for
                    # two hours to reach the same answer.
                    await callbacks.settle(
                        session,
                        callback.id,
                        status="refused",
                        rule=rule,
                        reason=decision.reason,
                    )
                else:
                    await callbacks.defer(session, callback.id, rule=rule, reason=decision.reason)
                blocked += 1
                log.info(
                    "callback_blocked",
                    extra={
                        "tenant_id": str(tenant_id),
                        "rule": rule,
                        # THE PROMISED TIME, IST — the one field that turns this line into
                        # something an operator can act on. "A call-back was blocked" is a
                        # metric; "the 16:00 one was blocked" is the row a client is about
                        # to ask about. Not PII (hard rule 6): an instant, no number, no
                        # name, and it is already on the client's own screen.
                        "promised_for": promised_for(callback.requested_at),
                    },
                )
                continue

            # After the gate, so a refused call-back never spends one of the account's slots.
            try:
                await await_dial_slot()
            except DialPacingTimeoutError:
                await callbacks.defer(
                    session, callback.id, rule=PACING_RULE, reason=PACING_DEFERRED_REASON
                )
                blocked += 1
                continue

            try:
                # THE ONE OUTBOUND ENTRY POINT. Not a parallel dial path: everything a dial
                # is supposed to inherit — the A/B arm, the resolved DLT header, the intent
                # row written before the phone can ring, and whatever `CallContext` carries
                # by the time you read this — arrives here for free precisely because this
                # is the same function the campaign tick and the "call this lead" button
                # call. A second dial path would have to be told about each of them.
                await dispatch_call(
                    session,
                    tenant_id=tenant_id,
                    agent_id=callback.agent_id,
                    lead_id=callback.lead_id,
                    phone_e164=callback.phone_e164,
                    lead_name=None,
                    context_note=callbacks.context_note(callback.requested_at, callback.note),
                    on_reserved=callbacks.link_callback_to_call(callback.id),
                )
            except DialUnconfirmedError as unconfirmed:
                await callbacks.settle(
                    session,
                    callback.id,
                    status="failed",
                    reason=UNCONFIRMED_REASON,
                    call_id=unconfirmed.call_id,
                )
                log.warning(
                    "callback_dial_unconfirmed",
                    extra={"call_id": str(unconfirmed.call_id), "code": unconfirmed.code},
                )
                continue
            except Exception as exc:
                # The engine refused BEFORE dialling. Back on the ladder rather than
                # settled — a vendor 502 is the most transient fact there is — and the
                # grace window is what stops that being for ever.
                await callbacks.defer(
                    session, callback.id, rule="dial_failed", reason=DIAL_FAILED_REASON
                )
                blocked += 1
                log.warning("callback_dial_failed", extra={"code": type(exc).__name__})
                continue
            dialled += 1
    return {"dialled": dialled, "blocked": blocked, "settled": settled}


def promised_for(requested_at: datetime) -> str:
    """The promised instant as IST wall clock, for a log line or an operator's question.

    Here rather than in `service.py` because it exists for the worker's own diagnostics;
    the client's screen renders the instant itself and formats it in the browser.
    """
    return ist_wall_clock(requested_at).strftime("%Y-%m-%d %H:%M IST")


__all__ = [
    "MAX_PER_TICK",
    "dispatch_due_callbacks",
    "promised_for",
]
