"""The four in-call tools, for the engine we run ourselves (`owned_runtime`).

**WHY THIS FILE EXISTS: THE PRODUCT HAD TWO ENGINES AND ONE SET OF TOOLS.**
`apps/voice-runtime/tool_routes.py` serves four custom functions on the RENTED engine —
opt-out, call-back, call-back cancel, handoff — and `voice_worker/pipeline.assemble_call`
advertised exactly ONE, the knowledge search. So an agent running on our own Pipecat
container could not honour a caller's opt-out, could not book or cancel a call-back, and
could not ask for a person. The opt-out half of that is a COMPLIANCE defect and not a
missing feature: hard rule 5 and SECURITY-COMPLIANCE §2.3 require a caller's opt-out to be
honoured and DNC additions to propagate before the next dispatch tick, and on this engine
there was no path by which "stop calling me" reached the DNC list at all.

**`tool_routes.py` IS THE SPECIFICATION AND THIS IS NOT A SECOND OPINION ABOUT IT.** It
already decides what an opt-out does, what a booking validates, what a cancellation means
and what the agent is told in every outcome. Every handler below reaches the SAME service
function its engine-leg counterpart's ARQ job reaches:

    opt-out           -> `compliance/optout.record_call_optout` (which calls
                         `compliance/service.add_to_dnc` — the one single-number writer)
    call-back         -> `callbacks/service.book`
    call-back cancel  -> `callbacks/service.cancel_for_phones`
    handoff           -> nothing to reach: this engine cannot transfer (see `handoff`)

Two implementations of "add this caller to the DNC list" is the defect this arrangement
exists to prevent, and the repository already owns exactly one of each.

**WHAT IS DIFFERENT, AND IT IS THE TRANSPORT RATHER THAN THE BEHAVIOUR.** The engine leg
must defer: it is on the latency-critical service (hard rule 3), the payload is a HINT
(D-31), and the tenant, the number and the call are re-derived by a worker from an
authenticated Get Execution a few hundred milliseconds later. That is why its answer is
`accepted` and never "done". There is no execution to fetch here and no poller — the worker
names its own `pipecat:<tenant>:<call>` ref, the server parses the tenant out of it and
does the write inside this request, under that tenant's RLS. So the truthful word is
`recorded` / `booked` / `cancelled`, and using the engine leg's weaker one would be
under-claiming in a sentence an agent reads out loud.

**WHY THAT IS AFFORDABLE HERE.** These run in `apps/api`, not in `voice-runtime`: they
read `calls`, write `dnc_list`, `consent_ledger` and `callbacks`, and reach the compliance
module — exactly the imports hard rule 3 forbids on the latency-critical service, and
exactly the reason `worker/routes.py` exists at all. A caller IS waiting (the model holds
the turn open), so the work is two or three statements and the WORKER bounds its own wait
below Pipecat's `FUNCTION_CALL_TIMEOUT_SECS`; see `voice_worker/call_tools.py`.

**HARD RULE 6.** Ids, states and outcome words. No phone number and no caller speech
reaches a log line here — `CallerIdentityIn.state` is authored in `voice_worker/carrier.py`
and never built from wire data, so it is safe to log and the number beside it never is.
"""

from __future__ import annotations

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
    HandoffOutcome,
    HandoffToolIn,
    HandoffToolOut,
    OptOutToolIn,
    OptOutToolOut,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.handoff import ROSTER_UNAVAILABLE_REASONS
from apps.api.agents.handoff_execution import (
    OUTCOME_ARRIVES_LATE,
    OUTCOME_UNREPORTABLE,
    HandoffPlacement,
    place_handoff,
)
from apps.api.agents.transfer_providers import (
    NOT_OUR_CARRIER_LEG,
    PLATFORM_CANNOT_TRANSFER,
)
from apps.api.agents.transfer_providers import (
    PROVIDER_CONTRACT_UNVERIFIED as TRANSFER_CONTRACT_UNVERIFIED,
)
from apps.api.agents.transfer_providers import (
    PROVIDER_NOT_LICENSED as TRANSFER_PROVIDER_NOT_LICENSED,
)
from apps.api.callbacks import service as callbacks
from apps.api.compliance.optout import DETECTED_IN_CALL, record_call_optout
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.worker.service import _refuse_unknown_call, _tenant_of_call
from apps.workers.callbacks import CANCELLED_BY_CALLER_REASON
from apps.workers.optout import tool_signal

log = get_logger(__name__)

#: The call this tool call is about, as one read rather than four.
_CALL_SQL = """
SELECT id, agent_id, direction, from_e164, to_e164
FROM calls WHERE engine_call_id = :ecid
"""


@dataclass(frozen=True, slots=True)
class _ToolCall:
    """The call row a tool acts on, resolved once per request."""

    id: UUID
    agent_id: UUID
    direction: str
    from_e164: str | None
    to_e164: str | None


async def _load_call(session: AsyncSession, engine_call_id: str) -> _ToolCall:
    """The `calls` row, or the one refusal every unknown ref gets (`_refuse_unknown_call`).

    A 404 RATHER THAN AN HONEST-FAILURE ANSWER, deliberately, and the line is where the
    fault lies. A ref naming no call of ours is a WIRING fault — the worker mints the ref
    itself — and the agent must hear a failure so it can say so. "We could not find the
    caller's number" is a different sentence from "we could not find the call", and only
    the first is something a caller can be told.
    """
    row = (await session.execute(text(_CALL_SQL), {"ecid": engine_call_id})).first()
    if row is None:
        raise _refuse_unknown_call()
    return _ToolCall(
        id=UUID(str(row[0])),
        agent_id=UUID(str(row[1])),
        direction=str(row[2]),
        from_e164=row[3],
        to_e164=row[4],
    )


def _subject(call: _ToolCall, caller: CallerIdentityIn) -> tuple[str | None, str]:
    """The OTHER party's number and, when there is none, the ground in machine words.

    **THE DIRECTION CHOOSES, EXACTLY AS IT DOES ON THE ENGINE LEG.** On an inbound call the
    person is `from_e164`; on an outbound one they are `to_e164` (`workers/optout.py`,
    `workers/callbacks._subject`). Getting this backwards suppresses our own header.

    **THE STORED ROW WINS OVER THE BODY, AND THE BODY IS NOT IGNORED.** The column is what
    every downstream reader uses — the lead, caller memory, a DPDP erasure — and it is
    written under RLS by `_upsert_call`, which keeps the FIRST party it learned. The
    container's own observation is the fallback for the window where nothing has flushed
    yet: a caller can say "stop calling me" in the first three seconds of a call, before
    any batch has been sent, and refusing them because our own write had not landed would
    be a suppression lost to timing. `CallerIdentityIn` is only ever believed when it says
    `known`, which is the one state that means a number was really read off a handshake.

    ⚠ **IT NEVER INVENTS ONE AND HAS NO SECOND SOURCE.** `_alert_if_nobody_was_on_the_call`
    and `carrier.CallerIdentity` make the same argument in the same words: substituting the
    agent's own line would file the suppression against ourselves.
    """
    stored = call.from_e164 if call.direction == "inbound" else call.to_e164
    if stored:
        return stored, ""
    if caller.state == "known" and caller.e164:
        return caller.e164, ""
    # The STATE is the ground, so an operator reading the outcome can tell "the carrier
    # withheld it" from "nobody looked" — the triage a bare NULL could never support.
    return None, f"caller_number_unknown:{caller.state}"


# --- opt-out ---------------------------------------------------------------------------

#: What the agent is told when the suppression is on file. The engine leg's tool answers
#: `accepted` and says only that the request is registered, because its write has not
#: happened yet; ours has.
_OPTOUT_DONE_SAY = (
    "The caller's number is on this business's do-not-call list and no further calls will "
    "be placed to it. Tell them plainly that they have been removed and will not be "
    "called again, and do not promise anything further."
)

#: ⚠ **THE SENTENCE THAT DECIDES WHETHER THIS TOOL IS HONEST.** A person who asked not to
#: be called again and was told "done" when nothing was written will not ring back to
#: check — they will be called again, by a platform that recorded nothing, and the first
#: anybody hears of it is a TRAI complaint. Being told a person will handle it is a worse
#: experience and a better outcome, and it is the only thing that is TRUE here.
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


async def record_opt_out(engine_call_id: str, request: OptOutToolIn) -> OptOutToolOut:
    """ "Don't call me again", honoured inside the call. SEC-COMP §2.3's tool, this leg.

    **THE UNATTRIBUTABLE CASE IS ANSWERED HERE AND NOT DISCOVERED LATER.** On the engine
    leg the same condition is found by an ARQ job minutes after the caller hung up: it
    alerts `in_call_optout_unattributable` and returns `"unattributable"`, having already
    let the agent say the request was registered. This engine knows the answer while the
    agent is still holding the turn, so it answers with it — the alert still fires, on the
    SAME code, because the operator obligation is identical and a second code for one
    condition would split an alarm nobody could then triage.

    **THE POST-CALL PASS IS STILL THE BRACES AND IS NOT A REASON TO BE VAGUE HERE.**
    `detect_opt_out` runs over the transcript afterwards and reaches the same
    `record_call_optout`, whose dedupe makes a second write a no-op. It needs a number too,
    so it cannot rescue the unattributable case either.
    """
    tenant_id = _tenant_of_call(engine_call_id)
    async with tenant_session(tenant_id) as session:
        call = await _load_call(session, engine_call_id)
        phone, ground = _subject(call, request.caller)
        if phone is None:
            return _optout_unattributed(tenant_id, call, ground, request.caller.state)
        try:
            # `tool_signal` — the engine leg's own signal builder, imported rather than
            # rebuilt. It bounds the model's prose to 80 characters and leaves `turn_idx`
            # None, which is right here for its reason: a tool call has no turn index of
            # ours to point at, and inventing one would put a meaningless number in
            # append-only evidence.
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
            # suppression filed under a string the dispatch gate will never match is a row
            # that looks like protection and blocks nothing. That refusal must not reach
            # the agent as an API error — the vendor's own troubleshooting reads a failing
            # tool call as a misconfiguration (`tool_routes._book_callback`'s argument) and
            # the model would say something invented. It reaches the caller as the honest
            # sentence instead.
            return _optout_unattributed(tenant_id, call, "not_suppressible", request.caller.state)
    # Ids and outcomes (hard rule 6). Never the number, never the caller's words.
    log.info(
        "worker_tool_optout_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call.id),
            "newly_suppressed": record.newly_suppressed,
            "evidence_written": record.evidence_written,
        },
    )
    return OptOutToolOut(status="recorded", say=_OPTOUT_DONE_SAY)


def _optout_unattributed(
    tenant_id: UUID, call: _ToolCall, ground: str, state: str
) -> OptOutToolOut:
    """Alert, then tell the agent what it may and may not claim. Never a success."""
    alert(
        "WORKER_TERMINAL",
        # THE ENGINE LEG'S CODE, NOT A NEW ONE. Same condition, same operator action, same
        # rung in `core/alarm_severity` — a second spelling would split one alarm in two.
        "in_call_optout_unattributable",
        detail=(
            "A caller asked not to be called again on an owned_runtime call whose number "
            f"we do not hold ({ground}). No suppression could be written; the number must "
            "be added by hand from the call recording."
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


async def book_callback(engine_call_id: str, request: CallbackBookIn) -> CallbackToolOut:
    """ "Ring me back Tuesday at four." The engine leg's endpoint, with the write inline.

    **THE REFUSAL HAS TO REACH THE CALLER WHILE THEY ARE STILL ON THE PHONE**, which is why
    `resolve_slot` runs before anything else and why an unbookable time is a 200 with
    `not_booked` rather than an error. A time outside 09:00-21:00 IST is not merely
    inconvenient, it is unlawful to dial (TCCCPR; SEC-COMP §3), and a callback the dispatch
    gate refuses two days later is worse than one that was never booked — somebody was told
    we would ring. `tool_routes._book_callback` carries the full argument.

    **CONFIRM-BEFORE-COMMIT IS A SERVER-SIDE CONTROL, NOT A LINE IN A PROMPT.** The model
    resolved "Tuesday at four" into a date and a 24-hour time by talking to the caller; we
    cannot see that conversation and must not assume it happened. So the tool refuses to
    book without `confirmed` and hands back the unambiguous spoken form to read out. Two
    turns cost a caller three seconds; a wrong one costs them a phone call at four in the
    morning — and every hour before 09:00 is outside the window anyway, which closes the
    dangerous half of the am/pm ambiguity structurally rather than by care.
    """
    tenant_id = _tenant_of_call(engine_call_id)
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
        call = await _load_call(session, engine_call_id)
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
            # THE CALL REF, WHICH ON THIS ENGINE IS WHAT AN EXECUTION ID IS ELSEWHERE.
            # `callbacks.book` keys the promise on it so two bookings in one conversation
            # resolve against each other rather than becoming two calls to one person.
            source_execution_id=engine_call_id,
            # The lead does not exist yet — extraction has not run, the call is still in
            # progress — and a promise with no lead pointer is still a promise
            # (`workers/callbacks._call_and_lead`'s argument, which holds identically here).
            lead_id=None,
            phone_e164=phone,
            # THE RESOLVED INSTANT, NEVER THE CALLER'S WORDS. One parser, one place, one set
            # of refusals: re-parsing downstream is what lets an endpoint refuse 22:00 and
            # a writer book it.
            requested_at=slot.at_utc,
            # WHEN THEY ASKED, so two bookings in one conversation resolve to the LATER word
            # whichever write commits first (`callbacks.service.book`).
            booked_at=datetime.now(UTC),
            note=request.note,
            language=request.language,
        )
    if booked is None:
        # **`callbacks.book` ANSWERS `None` FOR TWO REASONS AND THIS PATH MUST BE TRUE OF
        # BOTH.** Its upsert refuses when a LATER booking from the same conversation is
        # already on file, and when the promise has been claimed, cancelled or settled since
        # (`status = 'scheduled'` is in the predicate, so a cancelled call-back is never
        # resurrected). The second is an ordinary conversation — "book me Tuesday",
        # "actually cancel it", "no, make it Wednesday" — and in THAT case telling the
        # caller Wednesday is booked would be inventing a promise nobody wrote.
        #
        # ONE ANSWER RATHER THAN A SECOND QUERY TO TELL THEM APART, because one sentence is
        # true of both: the time the caller just gave was not saved, and anything they had
        # already agreed still stands. A `SELECT` to choose between two wordings would add
        # a branch, a round trip and a race for a distinction the caller cannot act on.
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


async def cancel_callback(engine_call_id: str, request: CallbackCancelIn) -> CallbackCancelOut:
    """ "Actually, don't ring me back." Its own tool, and NOT an opt-out.

    **EVERY LIVE PROMISE TO THIS NUMBER, NOT ONLY THIS CONVERSATION'S**, which is the
    caller's own meaning: somebody who says "do not call me back" while a promise from last
    week is still pending has not asked us to keep that one. `tenant_session` makes the
    scope structural rather than a WHERE clause, so it cannot reach across accounts.

    **IT IS NOT THE OPT-OUT AND MUST NEVER BECOME ONE.** "Do not ring me back on Tuesday" is
    not "never call me again", and answering it with a DNC entry would suppress a number on
    a sentence its speaker did not say. `record_opt_out` above is the one that does that.

    It is a separate tool rather than a flag on the booking for the vendor-documented
    reason `tool_routes._cancel_callback` records: the DESCRIPTION is what makes triggering
    reliable, and a cancellation must not be able to fail because a date could not be
    parsed — so there is no time in this path at all.
    """
    tenant_id = _tenant_of_call(engine_call_id)
    async with tenant_session(tenant_id) as session:
        call = await _load_call(session, engine_call_id)
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
        # NOTHING WAS BOOKED, which is not a failure and must not be reported as one. The
        # caller's wish is satisfied — nobody is going to ring them back — and saying "we
        # cancelled it" would be describing a row that never existed.
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


# --- handoff -----------------------------------------------------------------------------

#: OUR OUTCOME WORD -> THE WORD THE AGENT HAS A SENTENCE FOR.
#:
#: `HandoffOutcome` is declared in `calevate_shared/worker_api.py` because both halves of
#: the product import it: the server decides which word is true and `voice_worker/
#: call_tools.py` holds the sentence for each. The four unsuccessful endings collapse to
#: `no_answer` HERE and not in the seam — a client's screen needs to know whether their
#: person declined, was busy or never picked up, and a caller does not.
#:
#: `failed` is `not_transferred`, the WIDE word: a leg we could not place is not evidence
#: that nobody would have answered, and telling a caller "nobody took it" would be a
#: claim about the client's staff that we cannot make.
_STATUS_OF_OUTCOME: Final[dict[str, HandoffOutcome]] = {
    "bridged": "connected",
    "declined": "no_answer",
    "busy": "no_answer",
    "unanswered": "no_answer",
    "whisper_timeout": "no_answer",
    "failed": "not_transferred",
}

#: THE WIRE WORD FOR "NOBODY WAS RUNG AND NOBODY WILL BE", carried as the detail beside
#: `not_available`. `voice_worker/call_tools._ENGINE_CANNOT_TRANSFER` matches this exact
#: string; that service may not import this package (hard rule 3), so the two spellings are
#: pinned against each other by `tests/handoff_transfer_seam_test.py`.
ENGINE_CANNOT_TRANSFER: Final = "engine_cannot_transfer"

#: The placement reasons that mean the PLATFORM cannot do it, as opposed to the ones a
#: client or a clock will resolve. Only these earn `not_available`: telling a caller at 9pm
#: that a person is unavailable full stop, when the answer is "not until nine tomorrow", is
#: a wider claim than we hold — the roster's own reasons say `nobody_on_duty` instead.
_PERMANENTLY_UNAVAILABLE: Final[frozenset[str]] = frozenset(
    {
        PLATFORM_CANNOT_TRANSFER,
        NOT_OUR_CARRIER_LEG,
        TRANSFER_CONTRACT_UNVERIFIED,
        TRANSFER_PROVIDER_NOT_LICENSED,
        OUTCOME_UNREPORTABLE,
        OUTCOME_ARRIVES_LATE,
    }
)


def _handoff_status(placement: HandoffPlacement) -> HandoffOutcome:
    """Which word is true about this handover.

    **`connected` IS NEVER REACHED FROM A REASON, ONLY FROM AN OUTCOME**, and that is the
    hard rule 5 property of this function: the only path to the one word that licenses "I
    am putting you through" is a leg that was placed and a person who ACCEPTED it.
    """
    if placement.placed:
        return _STATUS_OF_OUTCOME.get(placement.outcome or "", "not_transferred")
    if placement.reason in _PERMANENTLY_UNAVAILABLE:
        return "not_available"
    if placement.reason in ROSTER_UNAVAILABLE_REASONS:
        return "nobody_on_duty"
    return "not_transferred"


async def request_handoff(engine_call_id: str, request: HandoffToolIn) -> HandoffToolOut:
    """The agent wants a person. `agents/handoff_execution` decides what actually happens.

    **THIS TOOL DECIDES NOTHING ABOUT HANDOVERS AND THAT IS THE POINT.** The roster, the
    hours, the platform's ability to transfer at all, the header the second leg presents
    and the whisper are one ladder in one place (`place_handoff`), because the client's
    own screen and the publish path ask the same questions and three implementations of
    "can this caller reach a person" is how two of them come to be wrong.

    **WHAT THE CALLER HEARS IS NEVER A PROMISE THIS PLATFORM CANNOT KEEP** (hard rule 5).
    Today every deployment degrades — no carrier's transfer grammar has been read
    (`agents/transfer_providers/plivo.py`) — and the agent is told to say plainly that it
    cannot connect them and to offer the call-back tool beside it. What was there before
    this tool existed was worse than a refusal: with no tool at all a model asked to fetch
    a human answers from its priors, says "putting you through now", and the caller hears
    nothing happen.

    The model's `reason` and `summary` are conversation content: they are never logged and
    never stored on a degraded path (hard rule 6), and on a placed one they travel into the
    whisper and onto the attempt row, which is where the person taking the call and the
    client reading it later both need them.
    """
    tenant_id = _tenant_of_call(engine_call_id)
    async with tenant_session(tenant_id) as session:
        call = await _load_call(session, engine_call_id)
        # The OTHER party, chosen by direction exactly as `_subject` chooses it: on an
        # inbound call the caller is `from_e164`. It reaches the whisper and nothing else.
        caller = call.from_e164 if call.direction == "inbound" else call.to_e164
        placement = await place_handoff(
            session,
            engine=get_engine(),
            tenant_id=tenant_id,
            agent_id=call.agent_id,
            engine_call_id=engine_call_id,
            caller_e164=caller,
            about=request.reason,
            summary=request.summary,
            # The agent is holding a turn open and this response carries the outcome, so
            # the seam may place a leg — and must not place one it cannot report.
            outcome_reaches_agent=True,
        )
    status = _handoff_status(placement)
    log.info(
        "worker_tool_handoff",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call.id),
            "agent_id": str(call.agent_id),
            "status": status,
            "reason": placement.reason,
            # WHETHER the model gave a reason, never what it said.
            "reason_given": bool(request.reason),
            "summary_given": bool(request.summary),
        },
    )
    return HandoffToolOut(
        status=status,
        reason=(
            ENGINE_CANNOT_TRANSFER
            if placement.reason in _PERMANENTLY_UNAVAILABLE
            else (placement.reason or "")
        ),
        say=placement.say,
    )


__all__ = [
    "book_callback",
    "cancel_callback",
    "record_opt_out",
    "request_handoff",
]
