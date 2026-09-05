"""Requested callbacks: the two booking jobs, and the dial pass the campaign tick runs.

Three entry points, and they divide the way hard rule 3 divides everything on this path:

* `book_requested_callback` / `cancel_requested_callback` — queued by the in-call tool in
  `apps/voice-runtime/tool_routes.py`, which acked the caller in milliseconds and wrote
  nothing. Everything that costs anything is here.
* `dispatch_due_callbacks` — NOT an arq job. It is called by `campaign_dispatch._run_tick`,
  inside the tick's own single-flight lease and out of the tick's own line budget, because
  a callback and a campaign contact compete for the same ten lines and two schedulers with
  two opinions about that is how a receptionist stops being able to answer the phone.

**THE TOOL PAYLOAD IS A HINT; THE FETCH IS THE TRUTH** (D-31), exactly as for the opt-out
job beside this one. The endpoint is unsigned and IP-allowlisted, so a payload-supplied
phone number would let anyone inside that allowlist book a call to an arbitrary number on
an arbitrary tenant's account — an outbound call placed under a client's DLT header, from
their credit, to somebody who never rang them. So the only things crossing the queue are
the execution id and the RESOLVED slot; the number, the tenant, the agent and the lead all
come back from the authenticated Get Execution and from our own routing table.

**THE TIME IS NEVER RE-PARSED HERE.** `calevate_shared.calling_window.resolve_slot` ran at
the endpoint, refused what it had to refuse and produced an instant; this job stores that
instant. A second parser would be a second set of refusals, and the two would disagree
about 21:00 on the day one of them was edited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from arq import Retry
from calevate_shared.calling_window import ist_wall_clock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import DialUnconfirmedError, dispatch_call
from apps.api.callbacks import service as callbacks
from apps.api.compliance.service import PERSON_LEVEL_REFUSALS, check_dispatch
from apps.api.core.alerting import alert, record_compliance_block
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine

# The ingest job's retry ladder, its transience verdict and its tenant resolution, used
# rather than restated — `optout.py` imports the identical three for the identical reason
# and says so: this module asks the same questions of the same engine.
from apps.workers.pipeline import _is_transient, _resolve_agent, _retry_after

log = get_logger(__name__)

BOOK_JOB = "book_requested_callback"
CANCEL_JOB = "cancel_requested_callback"

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

#: What the caller hears about, in the ledger sense, when they call their own callback off.
CANCELLED_BY_CALLER_REASON = "The caller asked us not to ring them back."


async def _snapshot(engine_name: str, execution_id: str, attempt: int) -> Any:
    """The authenticated fetch, with `optout.py`'s retry ladder and its alert on giving up.

    Split out because both jobs need it and both must fail the same way: a booking that
    silently never happens and a cancellation that silently never happens are the same
    defect, and the caller was told about both.
    """
    engine = get_engine()
    try:
        return await engine.get_execution(execution_id)
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        alert(
            "WORKER_TERMINAL",
            "in_call_callback_unresolved",
            detail=f"{type(exc).__name__} after {attempt} attempt(s)",
            execution_id=execution_id,
        )
        raise


async def _subject(
    engine_name: str, snapshot: Any, execution_id: str
) -> tuple[UUID, UUID, str] | None:
    """`(tenant_id, agent_id, phone_e164)` for the person on this call, or None.

    The number is the OTHER party, chosen by direction exactly as `record_in_call_optout`
    chooses it: on an inbound call the caller is `from_e164`, on an outbound one they are
    `to_e164`. Getting this backwards would book a callback to our own header.
    """
    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, snapshot.engine_agent_ref)
    if resolved is None:
        alert(
            "WORKER_TERMINAL",
            "in_call_callback_agent_unmapped",
            detail=f"engine={engine_name}",
            execution_id=execution_id,
        )
        return None
    tenant_id, agent_id = resolved
    phone = snapshot.from_e164 if snapshot.direction == "inbound" else snapshot.to_e164
    if not phone:
        alert(
            "WORKER_TERMINAL",
            "in_call_callback_unattributable",
            detail=f"direction={snapshot.direction}",
            execution_id=execution_id,
        )
        return None
    return tenant_id, agent_id, str(phone)


async def book_requested_callback(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Write the promise the agent just made. Returns a short outcome string (arq keeps it).

    The outcome string is what makes "the tool fired and nothing happened" answerable
    without a transcript — `superseded` in particular, which is the correct and invisible
    answer when a caller booked twice and this is the earlier of the two jobs.
    """
    engine_name = str(payload.get("engine") or "fake")
    execution_id = str(payload["execution_id"])
    requested_at = datetime.fromisoformat(str(payload["requested_at"]))
    booked_at = datetime.fromisoformat(str(payload["booked_at"]))

    snapshot = await _snapshot(engine_name, execution_id, int(ctx.get("job_try", 1)))
    subject = await _subject(engine_name, snapshot, execution_id)
    if subject is None:
        return "unattributable"
    tenant_id, agent_id, phone = subject

    async with tenant_session(tenant_id) as session:
        call_id, lead_id = await _call_and_lead(session, tenant_id, snapshot.engine_call_id)
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=call_id,
            source_execution_id=execution_id,
            lead_id=lead_id,
            phone_e164=phone,
            requested_at=requested_at,
            booked_at=booked_at,
            note=payload.get("note") or None,
            language=payload.get("language") or None,
        )
    if booked is None:
        # Either a later booking from the same conversation is already on file, or the row
        # has been claimed/cancelled/settled since. Both are correct outcomes and neither
        # is an error — see `callbacks.service.book`.
        log.info("callback_booking_superseded", extra={"tenant_id": str(tenant_id)})
        return "superseded"
    # Ids and an instant only — never the number (hard rule 6).
    log.info(
        "callback_booked",
        extra={"tenant_id": str(tenant_id), "callback_id": str(booked[0])},
    )
    return "booked"


async def cancel_requested_callback(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """ "Actually, don't ring me back." Cancels every live promise to this caller's number.

    EVERY live promise, not the one from this conversation, and that is the caller's own
    meaning: somebody who says "do not call me back" while a callback booked last week is
    still pending has not asked us to keep that one. It is scoped to the tenant they are
    speaking to — `tenant_session` makes that structural rather than a WHERE clause — so it
    cannot reach across accounts.
    """
    engine_name = str(payload.get("engine") or "fake")
    execution_id = str(payload["execution_id"])
    snapshot = await _snapshot(engine_name, execution_id, int(ctx.get("job_try", 1)))
    subject = await _subject(engine_name, snapshot, execution_id)
    if subject is None:
        return "unattributable"
    tenant_id, _agent_id, phone = subject
    async with tenant_session(tenant_id) as session:
        cancelled = await callbacks.cancel_for_phones(
            session, phones=[phone], reason=CANCELLED_BY_CALLER_REASON
        )
    log.info(
        "callback_cancelled_in_call",
        extra={"tenant_id": str(tenant_id), "cancelled": cancelled},
    )
    return f"cancelled={cancelled}"


async def _call_and_lead(
    session: AsyncSession, tenant_id: UUID, engine_call_id: str
) -> tuple[UUID | None, UUID | None]:
    """The call row this promise was made on, and the lead behind it, if either exists yet.

    BOTH ARE OPTIONAL AND NEITHER IS WORTH FAILING FOR. The `calls` row is written by the
    status webhook, which is at-most-once and may not have arrived; the lead is written by
    the post-call extraction, which has certainly not run — the call is still in progress.
    A promise with no pointers is still a promise, and both are backfilled by nothing on
    purpose: what the dial needs is the number and the agent, and it has those.
    """
    row = (
        await session.execute(
            text("SELECT id, lead_id FROM calls WHERE engine_call_id = :ecid AND tenant_id = :tid"),
            {"ecid": engine_call_id, "tid": tenant_id},
        )
    ).first()
    if row is None:
        return None, None
    return UUID(str(row[0])), (UUID(str(row[1])) if row[1] else None)


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
    "BOOK_JOB",
    "CANCEL_JOB",
    "MAX_PER_TICK",
    "book_requested_callback",
    "cancel_requested_callback",
    "dispatch_due_callbacks",
    "promised_for",
]
