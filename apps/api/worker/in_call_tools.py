"""The writes behind the platform's in-call tools: opt-out, call-back, call-back cancel, hand-over.

An agent must be able to honour a caller's opt-out, book or cancel a call-back, and ask for
a person. The opt-out half is a COMPLIANCE obligation and not a feature: hard rule 5 and
SECURITY-COMPLIANCE §2.3 require a caller's opt-out to be honoured and DNC additions to
propagate before the next dispatch tick. `worker/engine_actions.py` authenticates the
engine's action request and resolves the call; every function here then reaches the one
service function that owns its write:

    opt-out           -> `compliance/optout.record_call_optout` (which calls
                         `compliance/service.add_to_dnc` — the one single-number writer)
    call-back         -> `callbacks/service.book`
    call-back cancel  -> `callbacks/service.cancel_for_phones`
    hand-over         -> nothing to reach: no engine of ours carries a second leg

Two implementations of "add this caller to the DNC list" is the defect this arrangement
exists to prevent, and the repository already owns exactly one of each.

THE WRITE HAPPENS INSIDE THE REQUEST, under the tenant's RLS, so the truthful word is
`recorded` / `booked` / `cancelled`; a weaker "accepted" would be under-claiming in a
sentence an agent reads out loud. These run in `apps/api`, not in `voice-runtime`: they
write `dnc_list`, `consent_ledger` and `callbacks` and reach the compliance module, which
are exactly the imports hard rule 3 forbids there.

HARD RULE 6. Ids, states and outcome words. No phone number and no caller speech reaches a
log line here; `CallerIdentityIn.state` is authored by our own code, never built from wire
data, so it is safe to log and the number beside it never is.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from calevate_shared.calling_window import SlotRefusal, resolve_slot
from calevate_shared.worker_api import (
    CallbackBookIn,
    CallbackCancelIn,
    CallbackCancelOut,
    CallbackToolOut,
    CallerIdentityIn,
    HandoffToolIn,
    HandoffToolOut,
    OptOutToolIn,
    OptOutToolOut,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.handoff import HANDOFF_DEGRADED_SAY
from apps.api.agents.transfer_providers import NOT_OUR_CARRIER_LEG
from apps.api.callbacks import service as callbacks
from apps.api.compliance.consent import record_callback_request_consent
from apps.api.compliance.optout import DETECTED_IN_CALL, record_call_optout
from apps.api.compliance.trial_access import (
    TRIAL_CALLBACK_RULE,
    TRIAL_CALLBACK_SAY,
    restricting_trial,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.callbacks import CANCELLED_BY_CALLER_REASON
from apps.workers.optout import tool_signal

log = get_logger(__name__)


def refuse_wrong_engine() -> ProblemError:
    """409 for an engine request reaching a deployment that is not running that engine.

    The rows such a request would write are reconciled by the process-wide `ENGINE`, so
    they would be unreadable; the caller's credential is not at fault, which is why this is
    a conflict and not a 401.
    """
    return ProblemError.conflict(
        "worker_engine_not_enabled",
        "This deployment is not running the engine this request came from, so it cannot act on it.",
        remediation=(
            "An engine reaching an API configured for another engine is a deploy fault. "
            "Point the engine at the deployment whose ENGINE is this one."
        ),
    )


@dataclass(frozen=True, slots=True)
class ToolCall:
    """The call row a tool acts on, resolved once per request."""

    id: UUID
    agent_id: UUID
    direction: str
    from_e164: str | None
    to_e164: str | None


#: How a tool finds its call row inside the tenant session it writes in. The engine's
#: action route resolves the call (`worker/engine_actions.call_locator`) and hands the row
#: in, so the write each tool makes stays in one function.
CallLocator = Callable[[AsyncSession], Awaitable[ToolCall]]


def _subject(call: ToolCall, caller: CallerIdentityIn) -> tuple[str | None, str]:
    """The OTHER party's number and, when there is none, the ground in machine words.

    THE DIRECTION CHOOSES: on an inbound call the person is `from_e164`; on an outbound one
    they are `to_e164` (`workers/optout.py`, `workers/callbacks._subject`). Getting this
    backwards suppresses our own header.

    THE STORED ROW WINS OVER THE BODY. The column is what every downstream reader uses —
    the lead, caller memory, a DPDP erasure. `CallerIdentityIn` is the fallback, believed
    only when it says `known`, the one state that means a number was really read.

    It never invents a number: substituting the agent's own line would file the
    suppression against ourselves.
    """
    stored = call.from_e164 if call.direction == "inbound" else call.to_e164
    if stored:
        return stored, ""
    if caller.state == "known" and caller.e164:
        return caller.e164, ""
    # The STATE is the ground, so an operator reading the outcome can tell "withheld" from
    # "nobody looked" — the triage a bare NULL could never support.
    return None, f"caller_number_unknown:{caller.state}"


# --- opt-out ---------------------------------------------------------------------------

#: What the agent is told when the suppression is on file, which it is by the time this is
#: returned. Written as an instruction to the agent, never as a statement about "the
#: caller": a model handed a third-person English sentence reads it out as it stands, which
#: a Telugu caller heard in a test chat on 11 Oct 2026 (D-748).
OPTOUT_DONE_SAY = (
    "Done: their number is removed and they will not be called again. Now say so to them "
    "yourself, in one short sentence, speaking to them directly and in the language they "
    "are speaking. Do not read this note out, do not call them 'the caller', and do not "
    "promise anything further."
)

#: THE SENTENCE THAT DECIDES WHETHER THIS TOOL IS HONEST. A person who asked not to be
#: called again and was told "done" when nothing was written will not ring back to check —
#: they will be called again, and the first anybody hears of it is a TRAI complaint. Being
#: told a person will handle it is the only thing that is TRUE here.
#:
#: It is guidance and not a script (`SlotRefusal.say`'s rule): the caller may be speaking
#: Telugu, and the agent's own model renders this into their language.
_OPTOUT_UNATTRIBUTED_SAY = (
    "You could NOT record this request: this call did not give us the caller's number. Do "
    "NOT tell them they have been removed and do NOT say it is done. Apologise, tell them "
    "their request has been passed to a person who will make sure they are not called "
    "again, and — if they are willing — ask them to say their number so it can be taken "
    "down. A person has been alerted."
)


async def record_opt_out_for(
    tenant_id: UUID, request: OptOutToolIn, *, locate: CallLocator
) -> OptOutToolOut:
    """ "Don't call me again", honoured inside the call. SEC-COMP §2.3's tool.

    The post-call pass (`detect_opt_out`) runs over the transcript afterwards and reaches the
    same `record_call_optout`, whose dedupe makes a second write a no-op. It needs a number
    too, so it cannot rescue the unattributable case, which is answered here, while the
    agent is still holding the turn.
    """
    async with tenant_session(tenant_id) as session:
        call = await locate(session)
        phone, ground = _subject(call, request.caller)
        if phone is None:
            return _optout_unattributed(tenant_id, call, ground, request.caller.state)
        try:
            # `tool_signal` bounds the model's prose to 80 characters and leaves `turn_idx`
            # None: a tool call has no turn index of ours to point at, and inventing one
            # would put a meaningless number in append-only evidence.
            record = await record_call_optout(
                session,
                tenant_id=tenant_id,
                raw_phone=phone,
                call_id=call.id,
                detected_by=DETECTED_IN_CALL,
                signal=tool_signal(reason=request.reason, language=request.language),
            )
        except ProblemError:
            # `record_call_optout` refuses a number it cannot normalise, because a
            # suppression filed under a string the dispatch gate will never match blocks
            # nothing. That refusal must not reach the agent as an API error — a failing
            # tool call reads to the model as a misconfiguration and it would say something
            # invented. It reaches the caller as the honest sentence instead.
            return _optout_unattributed(tenant_id, call, "not_suppressible", request.caller.state)
    log.info(
        "worker_tool_optout_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call.id),
            "newly_suppressed": record.newly_suppressed,
            "evidence_written": record.evidence_written,
        },
    )
    return OptOutToolOut(status="recorded", say=OPTOUT_DONE_SAY)


def _optout_unattributed(tenant_id: UUID, call: ToolCall, ground: str, state: str) -> OptOutToolOut:
    """Alert, then tell the agent what it may and may not claim. Never a success."""
    alert(
        "WORKER_TERMINAL",
        # The post-call pass's code: same condition, same operator action, same rung in
        # `core/alarm_severity`.
        "in_call_optout_unattributable",
        detail=(
            "A caller asked not to be called again on a call whose number we do not hold "
            f"({ground}). No suppression could be written; the number must be added by hand "
            "from the call recording."
        ),
        tenant_id=str(tenant_id),
        call_id=str(call.id),
        caller_identity=state,
    )
    return OptOutToolOut(status="not_recorded", say=_OPTOUT_UNATTRIBUTED_SAY, reason=ground)


# --- call-back: book ---------------------------------------------------------------------

_CALLBACK_NO_NUMBER_SAY = (
    "You could NOT book a call-back: this call did not give us the caller's number, so "
    "there is nothing to ring. Tell them that plainly and ask them to say the number they "
    "would like us to call, or to ring back themselves."
)


async def book_callback_for(
    tenant_id: UUID, engine_call_id: str, request: CallbackBookIn, *, locate: CallLocator
) -> CallbackToolOut:
    """ "Ring me back Tuesday at four.", booked inside the request.

    `engine_call_id` is the engine's handle for the conversation, which keys the promise
    (`source_execution_id`) so two bookings in one conversation resolve against each other.

    THE REFUSAL HAS TO REACH THE CALLER WHILE THEY ARE STILL ON THE PHONE, which is why
    `resolve_slot` runs first and why an unbookable time is a 200 with `not_booked`. A time
    outside 09:00-21:00 IST is unlawful to dial (TCCCPR; SEC-COMP §3).

    CONFIRM-BEFORE-COMMIT IS A SERVER-SIDE CONTROL, NOT A LINE IN A PROMPT. We cannot see
    the conversation in which the model resolved "Tuesday at four", so the tool refuses to
    book without `confirmed` and hands back the unambiguous spoken form to read out.

    A FREE-TRIAL ACCOUNT BOOKS NOTHING (founder decision 1): nothing can ring a caller back
    until the account pays, so the agent is told to say the business will follow up rather
    than promise a call that would never come. Asked first, before the time is parsed.
    """
    async with tenant_session(tenant_id) as session:
        on_trial = await restricting_trial(session, tenant_id=tenant_id) is not None
    if on_trial:
        log.info("worker_tool_callback_trial", extra={"tenant_id": str(tenant_id)})
        return CallbackToolOut(
            status="not_booked", reason=TRIAL_CALLBACK_RULE, say=TRIAL_CALLBACK_SAY
        )
    slot = resolve_slot(request.callback_date, request.callback_time, now=datetime.now(UTC))
    if isinstance(slot, SlotRefusal):
        return CallbackToolOut(
            status="not_booked",
            reason=slot.code,
            say=slot.say,
            booked_for=slot.alternative.spoken if slot.alternative else "",
        )
    if not request.confirmed:
        return CallbackToolOut(
            status="needs_confirmation",
            booked_for=slot.spoken,
            say=(
                f"Read this back to the caller exactly: {slot.spoken}. If they agree, call "
                "this again with the confirmation set. If they want a different time, ask "
                "for it and start again."
            ),
        )

    async with tenant_session(tenant_id) as session:
        call = await locate(session)
        phone, ground = _subject(call, request.caller)
        if phone is None:
            log.info(
                "worker_tool_callback_unattributable",
                extra={"tenant_id": str(tenant_id), "call_id": str(call.id), "ground": ground},
            )
            return CallbackToolOut(status="not_booked", reason=ground, say=_CALLBACK_NO_NUMBER_SAY)
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=call.agent_id,
            source_call_id=call.id,
            source_execution_id=engine_call_id,
            # The lead does not exist yet — extraction has not run, the call is still in
            # progress — and a promise with no lead pointer is still a promise.
            lead_id=None,
            phone_e164=phone,
            # THE RESOLVED INSTANT, NEVER THE CALLER'S WORDS: one parser, one set of
            # refusals. Re-parsing downstream is what lets an endpoint refuse 22:00 and a
            # writer book it.
            requested_at=slot.at_utc,
            # WHEN THEY ASKED, so two bookings in one conversation resolve to the LATER word
            # whichever write commits first (`callbacks.service.book`).
            booked_at=datetime.now(UTC),
            note=request.note,
            language=request.language,
        )
        # The request is the caller's consent to that call, in the same transaction as the
        # promise, so a gate that would otherwise refuse it on the day cannot.
        if booked is not None:
            await record_callback_request_consent(
                session,
                tenant_id=tenant_id,
                phone_e164=phone,
                call_id=call.id,
                callback_id=booked[0],
                callback_at=booked[1],
            )
    if booked is None:
        # `callbacks.book` answers `None` when a LATER booking from the same conversation is
        # already on file, and when the promise has been claimed, cancelled or settled since.
        # One sentence is true of both: the time the caller just gave was not saved, and
        # anything they had already agreed still stands.
        log.info(
            "worker_tool_callback_not_bookable",
            extra={"tenant_id": str(tenant_id), "call_id": str(call.id)},
        )
        return CallbackToolOut(
            status="not_booked",
            reason="not_bookable_now",
            say=(
                "That time was NOT saved. Do NOT tell the caller it is booked. Tell them "
                "you were unable to save that time, that any call-back they have already "
                "agreed to still stands, and that a person will confirm with them."
            ),
        )
    log.info(
        "worker_tool_callback_booked",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call.id),
            "callback_id": str(booked[0]),
        },
    )
    return CallbackToolOut(
        status="booked",
        booked_for=slot.spoken,
        say=f"Tell the caller that is booked: {slot.spoken}.",
    )


# --- call-back: cancel -------------------------------------------------------------------


async def cancel_callback_for(
    tenant_id: UUID, request: CallbackCancelIn, *, locate: CallLocator
) -> CallbackCancelOut:
    """ "Actually, don't ring me back." Its own tool, and NOT an opt-out.

    EVERY LIVE PROMISE TO THIS NUMBER, NOT ONLY THIS CONVERSATION'S, which is the caller's
    own meaning. `tenant_session` makes the scope structural, so it cannot reach across
    accounts. "Do not ring me back on Tuesday" is not "never call me again": answering it
    with a DNC entry would suppress a number on a sentence its speaker did not say.
    """
    async with tenant_session(tenant_id) as session:
        call = await locate(session)
        phone, ground = _subject(call, request.caller)
        if phone is None:
            log.info(
                "worker_tool_callback_cancel_unattributable",
                extra={"tenant_id": str(tenant_id), "call_id": str(call.id), "ground": ground},
            )
            return CallbackCancelOut(
                status="not_cancelled",
                reason=ground,
                say=(
                    "You could NOT cancel anything: this call did not give us the caller's "
                    "number, so there is no promise to look up. Tell them that plainly and "
                    "offer to take their number so a person can check."
                ),
            )
        cancelled = await callbacks.cancel_for_phones(
            session, phones=[phone], reason=CANCELLED_BY_CALLER_REASON
        )
    log.info(
        "worker_tool_callback_cancelled",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call.id),
            "cancelled": cancelled,
        },
    )
    if cancelled == 0:
        # NOTHING WAS BOOKED, which is not a failure: nobody is going to ring them back,
        # and saying "we cancelled it" would describe a row that never existed.
        return CallbackCancelOut(
            status="cancelled",
            cancelled=0,
            reason="nothing_booked",
            say=(
                "There was no call-back booked for this caller, so nothing needed calling "
                "off. Tell them we have no call-back for them and will not ring them back."
            ),
        )
    return CallbackCancelOut(
        status="cancelled",
        cancelled=cancelled,
        say="Tell the caller we will not ring them back.",
    )


# --- hand-over ---------------------------------------------------------------------------

#: The reason beside `not_available`: nobody was rung and nobody will be.
ENGINE_CANNOT_TRANSFER: Final = "engine_cannot_transfer"


async def request_handoff_unplaced(
    tenant_id: UUID, agent_id: UUID, request: HandoffToolIn
) -> HandoffToolOut:
    """The hand-over answer when our platform carries no second leg.

    Every engine we run hosts the agent on its own platform (`control_plane`), so there is
    no call leg of ours to transfer: the answer is `not_available`, the agent says plainly
    that it cannot connect the caller and offers the call-back tool beside it (hard rule 5:
    never a promise this platform cannot keep). No call needs identifying to give it, and
    the model's `reason` and `summary` are conversation content, so neither is stored or
    logged (hard rule 6).
    """
    log.info(
        "worker_tool_handoff",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "status": "not_available",
            "reason": NOT_OUR_CARRIER_LEG,
            "reason_given": bool(request.reason),
            "summary_given": bool(request.summary),
        },
    )
    return HandoffToolOut(
        status="not_available", reason=ENGINE_CANNOT_TRANSFER, say=HANDOFF_DEGRADED_SAY
    )


__all__ = [
    "ENGINE_CANNOT_TRANSFER",
    "OPTOUT_DONE_SAY",
    "CallLocator",
    "ToolCall",
    "book_callback_for",
    "cancel_callback_for",
    "record_opt_out_for",
    "refuse_wrong_engine",
    "request_handoff_unplaced",
]
