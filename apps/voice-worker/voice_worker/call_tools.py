"""The four in-call tools an `owned_runtime` agent may call, and the client behind them.

**FOUR, BECAUSE `apps/voice-runtime/tool_routes.py` SERVES FOUR ON THE RENTED ENGINE.**
"Which tools does an agent have" must not have two answers depending on which engine it
happens to run on. Advertising only the knowledge search here leaves an agent unable to
honour a caller's opt-out, book or cancel a call-back, or ask for a person — and the
opt-out half is a compliance defect (hard rule 5, SEC-COMP §2.3): no path by which "stop
calling me" reaches the DNC list at all.

**THE BEHAVIOUR IS THE SERVER'S AND THIS MODULE HOLDS NONE OF IT.** Every decision — what
an opt-out does, whether a time is lawful to dial, whether a booking was confirmed, what
the agent is told — is made by `apps/api/worker/tools.py`, which reaches the same service
functions the engine leg's ARQ jobs reach. What lives here is the vocabulary the MODEL
reads (names, descriptions, parameters) and the transport. A worker that decided any of it
would be a second opinion about compliance running on a vendor's infrastructure.

**THE `say` FIELD IS WHY THESE ANSWER AT ALL.** Every response carries English guidance for
the agent, which its own LLM renders into the caller's language (`calling_window.
SlotRefusal`'s rule). Three of the four handlers hand it straight back as the tool result
and compose nothing of their own, because the server is what knows whether the thing
happened.

**THE HANDOFF IS THE EXCEPTION, AND `HANDOFF_GUIDANCE` ARGUES IT WHERE IT LIVES.** In one
line: the server still decides WHAT HAPPENED, and this module keys a sentence on that word
so no prose in any `say` can license "I am putting you through" for a handover that did not
happen.

**FAILURE IS ANSWERED, NEVER SWALLOWED AND NEVER DRESSED AS SUCCESS.** If the API cannot be
reached the caller is still on the phone, so each handler returns its own honest payload —
and for the opt-out that payload explicitly forbids the model from saying the request was
recorded. A tool that raises reaches the model as "the function failed and returned no
result" (`pipecat/services/llm_service.py:301-303`), which is strictly less useful than a
word it can act on, and for the opt-out it is the difference between "a person will make
sure" and an invented reassurance.

**HARD RULE 6.** Nothing here logs a number, a caller's words, a response body or a URL
with a ref in it. What it logs is the tool name, the status word and an exception TYPE.

**HARD RULE 2.** This package may import Pipecat; what it SENDS is
`calevate_shared.worker_api`'s models and nothing else. `FunctionSchema` and
`FunctionCallParams` stop at this module's boundary.
"""

from __future__ import annotations

from typing import Any, Final, Protocol, TypeVar
from uuid import UUID

from calevate_shared.engine import pipecat_call_ref
from calevate_shared.worker_api import (
    CallbackBookIn,
    CallbackCancelIn,
    CallbackCancelOut,
    CallbackToolOut,
    CallerIdentityIn,
    CallerIdentityState,
    HandoffOutcome,
    HandoffToolIn,
    HandoffToolOut,
    OptOutToolIn,
    OptOutToolOut,
)
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from pydantic import BaseModel

from voice_worker.api_client import CALLS_PATH, WorkerApiClient, WorkerApiError

#: One of the tool wire models. Bound so `_tool` hands back the type its caller asked for
#: rather than `Any` — `api_client._parse`'s `_Wire`, for its reason: a client that widened
#: its own answers would defeat the point of both ends importing one module.
_ToolOut = TypeVar("_ToolOut", bound=BaseModel)

#: How long a tool call may wait on `apps/api` before the worker gives up and answers the
#: model itself.
#:
#: **IT IS DELIBERATELY UNDER `pipeline.FUNCTION_CALL_TIMEOUT_SECS` (2.0 s), AND THAT
#: ORDERING IS THE WHOLE POINT** — the same argument `build_knowledge_tool` already makes
#: about `embedding.EMBED_BUDGET_S`. The inner bound being the smaller is what lets a hung
#: API return OUR honest sentence inside the tool call; if the outer one fired first the
#: model would see "the function failed and returned no result" and say something it made
#: up, on a turn where the caller has just asked not to be called again.
#:
#: ⚠ **AN ASSUMPTION, NOT A MEASUREMENT.** Nobody has timed a
#: request from a Pipecat Cloud `ap-south` container to our API
#: (`docs/evidence/pre-build-blockers-2026-09-13.md` §3.6), which is the same gap
#: `api_client.SESSION_FETCH_BUDGET_S` carries and says so. What does not depend on the
#: number is that some bound exists and that it is smaller than the framework's.
TOOL_BUDGET_S: Final[float] = 1.5

#: The tool names the model sees. They describe the ACT, not our plumbing, because the
#: description and the name are what make triggering reliable — the vendor says so of the
#: rented engine (`custom-function-calls.md:47-49, 804-807`) and it is true of any model.
OPT_OUT_TOOL_NAME: Final[str] = "record_do_not_call"
BOOK_CALLBACK_TOOL_NAME: Final[str] = "book_callback"
CANCEL_CALLBACK_TOOL_NAME: Final[str] = "cancel_callback"
HANDOFF_TOOL_NAME: Final[str] = "request_human_handoff"


class CallToolApi(Protocol):
    """The four calls a running conversation makes. A Protocol so a test owns no socket.

    `pipeline.assemble_call` takes one of these rather than a concrete client for
    `VendorLegs`' reason: the seam is what lets the assembler run with no network at all,
    and a test that had to subclass an httpx client to check what an agent says about a
    do-not-call request would be testing the wrong thing.
    """

    async def opt_out(self, engine_call_id: str, request: OptOutToolIn) -> OptOutToolOut: ...

    async def book_callback(
        self, engine_call_id: str, request: CallbackBookIn
    ) -> CallbackToolOut: ...

    async def cancel_callback(
        self, engine_call_id: str, request: CallbackCancelIn
    ) -> CallbackCancelOut: ...

    async def handoff(self, engine_call_id: str, request: HandoffToolIn) -> HandoffToolOut: ...


class CallToolApiClient(WorkerApiClient):
    """`WorkerApiClient` plus the four tool calls. A SUBCLASS, and the reason is the socket.

    **ONE CLIENT PER CONTAINER IS THE MEASURED DECISION** (`api_client.WorkerApiClient`:
    a client per request re-does DNS, TCP and TLS, roughly half a round trip from this
    container). A second client built for tools would pay that handshake on the one call
    where somebody is listening to the wait. Subclassing reuses the pool, the Bearer
    header, the wall-clock bound and `WorkerApiError` rather than writing a second
    transport with its own opinions about all four.

    **THE BUDGET IS THIS CLASS'S AND NOT `WRITE_BUDGET_S`.** That constant (5 s) is sized
    for flushes and settlements, which nobody waits on. These are held open by a model
    mid-turn — see `TOOL_BUDGET_S`.
    """

    __slots__ = ()

    async def opt_out(self, engine_call_id: str, request: OptOutToolIn) -> OptOutToolOut:
        return await self._tool(
            engine_call_id, "tools/opt-out", request, OptOutToolOut, what="opt_out"
        )

    async def book_callback(self, engine_call_id: str, request: CallbackBookIn) -> CallbackToolOut:
        return await self._tool(
            engine_call_id, "tools/callback", request, CallbackToolOut, what="callback"
        )

    async def cancel_callback(
        self, engine_call_id: str, request: CallbackCancelIn
    ) -> CallbackCancelOut:
        return await self._tool(
            engine_call_id,
            "tools/callback/cancel",
            request,
            CallbackCancelOut,
            what="callback_cancel",
        )

    async def handoff(self, engine_call_id: str, request: HandoffToolIn) -> HandoffToolOut:
        return await self._tool(
            engine_call_id, "tools/handoff", request, HandoffToolOut, what="handoff"
        )

    async def _tool(
        self,
        engine_call_id: str,
        leaf: str,
        request: BaseModel,
        model: type[_ToolOut],
        *,
        what: str,
    ) -> _ToolOut:
        """One tool POST, under the tool budget. Raises `WorkerApiError` like every other call.

        The handlers below turn that into a sentence; the CLIENT does not, for
        `api_client._request`'s reason — the one place a transport failure becomes ours is
        the transport, and what a caller should be told about it is a conversational
        decision that belongs beside the tool.
        """
        body = await self._request(
            "POST",
            f"{CALLS_PATH}/{engine_call_id}/{leaf}",
            budget_s=TOOL_BUDGET_S,
            what=what,
            json=request.model_dump(mode="json"),
        )
        return self._parse(model, body, what=what)


# --- what the model reads ----------------------------------------------------------------

_OPT_OUT_DESCRIPTION = (
    "Call this the moment the caller asks not to be contacted again — 'stop calling me', "
    "'remove my number', 'don't call again', or the same thing in any language. Call it "
    "even if you have already apologised, and call it before you promise anything: it is "
    "what actually removes them. Do NOT call it when they only want a different time, or "
    "ask you not to ring back about THIS one thing — use the cancel-callback tool for "
    "that. Read the answer before you speak: it tells you whether they were really removed."
)

_BOOK_CALLBACK_DESCRIPTION = (
    "Book a call back for this caller. Ask them for the day and the time and resolve it "
    "yourself into a full calendar date (YYYY-MM-DD) and a 24-hour time (HH:MM) in Indian "
    "time before calling — never pass their words. Call it FIRST without the confirmation "
    "to get the time in a form you can read out, read that back to them exactly, and only "
    "then call it again with confirmed set. The answer may refuse the time; if it does, "
    "offer what it suggests instead."
)

_CANCEL_CALLBACK_DESCRIPTION = (
    "Call this when the caller no longer wants the call back they were promised — "
    "'actually, don't ring me back'. It cancels every call back waiting for them. It does "
    "NOT stop future calls of any other kind: if they asked never to be called again, use "
    "the do-not-call tool instead."
)

_HANDOFF_DESCRIPTION = (
    "Call this when the caller needs a person — because they have asked for one, or "
    "because your instructions tell you to hand this call over. Call it BEFORE you say "
    "anything about connecting, transferring or holding: whether anybody can be reached "
    "is not something you can know, and the answer is what tells you. You may say you are "
    "trying. You may only say the caller is being connected when the answer says a person "
    "has accepted. Then do what the answer's 'guidance' says."
)


def _confirmed(value: Any) -> bool:
    """Did the model say yes? Booleans, and the two strings a JSON-ish model produces.

    NARROW ON PURPOSE, and it is `tool_routes._truthy` (`apps/voice-runtime/tool_routes.py:
    526-536`) applied on this side of the wire: `true`, `"true"`, `"yes"` and nothing else
    — not `1`, not a non-empty string, not Python's truthiness. An unrecognised value is an
    unconfirmed booking, which costs one conversational turn; the other direction costs a
    caller a phone call at four in the morning.

    ⚠ **SPELLED TWICE, DELIBERATELY, AND THAT IS NOT DRIFT.** The engine-leg copy lives in
    `apps/voice-runtime`, which this container may not import (a separate deployable, and
    hard rule 3 keeps that service tiny); the shared package holds wire MODELS, and a
    parser for a vendor's substitution format is not one. What the two halves of OUR
    product share is the decided boolean on `CallbackBookIn.confirmed` — the narrowing
    happens before the body is built, so the server never re-interprets a string.
    """
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in {"true", "yes"}


def _text_arg(
    params: FunctionCallParams, name: str, *, into: type[BaseModel], clip: bool = False
) -> str | None:
    """One string argument, sized to fit field `name` of `into`, or None. Never raises.

    Absent, non-string and blank all become `None`: a handler that raised would reach the
    model as "the function failed and returned no result", which on these four tools is
    worse than the field simply being empty — every one of them has a defined behaviour
    for a missing hint, and none of them needs one to do its job.

    The same holds for LENGTH, which the model chooses and the wire model bounds. Building
    the request with a value over its `max_length` raises inside the handler, so the act is
    never sent — on the opt-out tool, a caller asking to be removed is not removed because
    the model spelled the language "Telugu (India)". Free text (`clip=True`) is shortened
    to the bound: the first 500 characters of a reason are still the reason. An identifier
    that does not fit (a language code, a date) is dropped instead, because a truncated
    code is a different, wrong code.
    """
    raw = params.arguments.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    limit = _max_length(into, name)
    if limit is None or len(value) <= limit:
        return value
    if not clip:
        return None
    return value[:limit].rstrip()


def _max_length(model: type[BaseModel], name: str) -> int | None:
    """The `max_length` the wire model declares for `name`, read rather than retyped."""
    for constraint in model.model_fields[name].metadata:
        limit = getattr(constraint, "max_length", None)
        if isinstance(limit, int):
            return limit
    return None


# --- the handlers ------------------------------------------------------------------------
#
# Each one answers the model with the SERVER's `status` and `say`, or — when the API could
# not be reached — with the honest local payload beside it.

#: ⚠ **THE MOST IMPORTANT SENTENCE IN THIS FILE.** When the API cannot be reached, the
#: suppression was NOT written, and a caller told "done" will not ring back to check: they
#: will simply be called again by a platform that recorded nothing. Being told a person
#: will handle it is a worse conversation and the only true one.
_OPT_OUT_UNREACHABLE_SAY = (
    "You could NOT record this request: the system that removes numbers could not be "
    "reached. Do NOT tell the caller they have been removed and do NOT say it is done. "
    "Apologise, tell them you are passing their request to a person who will make sure "
    "they are not called again, and move on."
)

_CALLBACK_UNREACHABLE_SAY = (
    "The call back could NOT be saved: the system could not be reached. Tell the caller we "
    "were unable to save it and ask them to say the day and time again in a moment, or "
    "offer to have somebody ring them."
)

_CANCEL_UNREACHABLE_SAY = (
    "The call back could NOT be called off: the system could not be reached. Tell the "
    "caller we could not do it just now and that a person will make sure they are not rung."
)

# --- what the agent says about a person -------------------------------------------------
#
# **THESE FIVE SENTENCES ARE THE FEATURE.** Everything else on this path is plumbing: what a
# caller who needs a person actually gets is one of these, rendered by the agent's own model
# into their language. They are keyed on `HandoffOutcome` — the one vocabulary, declared on
# the wire — so the server decides which is true and the worker decides what it sounds like.
#
# **WHY THE WORKER AUTHORS THEM WHEN THE SERVER ALREADY SENDS A `say`.** For the other three
# tools the server's sentence is the whole answer and this module adds nothing, because the
# server is the only thing that knows what happened. Here there is one claim that must be
# impossible rather than merely unlikely — that the caller is being put through to somebody
# who is not there — and a floor enforced by prose travelling in a field is not a floor. The
# guidance below is keyed on the outcome word `handoff_outcome` resolves, so no wording in
# any `say` can license "I am connecting you" unless that word is `connected`. The server's
# `say` still travels, beside it, for the detail this module cannot know.
#
# **NOTHING HERE IS VERTICAL-SPECIFIC.** The same call is answered for a dealership, a
# coaching centre, a law office and a clinic, and a sentence that assumes a waiting room or
# an appointment would be wrong in three of the four. What triggers a handover at all is the
# CLIENT's own script — this module never decides when a person is needed, only what is
# true once one has been asked for.

#: The claim that must never be made about a handover that did not happen. Spelled once and
#: carried into all four failures: it is the sentence a caller acts on by waiting.
_NEVER_CLAIM_A_TRANSFER = (
    "Do not say you are transferring them, do not say you are putting them through, and do "
    "not ask them to hold."
)

#: The distressed caller, who is vertical-agnostic and is most of why this tool exists. Not
#: a state of its own: whether somebody is upset does not change what is TRUE about the
#: handover, and a sixth outcome word for it would be a claim about a person's feelings made
#: by a model. It rides on every failure instead, where it changes the order of the agent's
#: own sentences.
_DISTRESS = (
    "If they sound upset or worried, acknowledge that first, in one short sentence, before "
    "you explain anything — and do not hurry them off the call."
)

#: The fallback, and the reason it names no interval. A promise has to be kept by something:
#: `callbacks/service.book` writes a row the dispatcher really rings, so a time it hands back
#: is a promise this platform keeps — "within the hour" is a number nobody here can honour
#: and nothing anywhere would make true.
_OFFER_A_CALLBACK = (
    "Offer to arrange for somebody to call them back. If they agree, ask which day and what "
    "time suits them, use the call-back tool, and read back the time it gives you. Do not "
    "promise a time of your own — not 'shortly', not 'within the hour' — because nothing "
    "here can keep that promise. When you book it, put one line in the note about what they "
    "want, so the person ringing back is not starting from nothing. If they would rather not "
    "wait for a call back, offer to take a message instead."
)

HANDOFF_GUIDANCE: Final[dict[HandoffOutcome, str]] = {
    "connected": (
        "A person has accepted this call and is on the line now. Tell the caller you are "
        "connecting them now — one short sentence — and then stop talking."
    ),
    "no_answer": (
        "Somebody was rung and did not take the call. The caller is NOT connected. "
        f"{_NEVER_CLAIM_A_TRANSFER} Tell them you tried to reach a person just now and "
        f"could not. {_DISTRESS} {_OFFER_A_CALLBACK}"
    ),
    "nobody_on_duty": (
        "There is nobody on duty to take calls at the moment, so nobody was rung — do not "
        f"say you tried. {_NEVER_CLAIM_A_TRANSFER} Tell them there is nobody available to "
        f"take the call right now. {_DISTRESS} {_OFFER_A_CALLBACK}"
    ),
    "not_available": (
        "This line cannot put a caller through to a person at all, and nobody was rung. "
        f"{_NEVER_CLAIM_A_TRANSFER} Do not say you are trying, either. Tell them plainly "
        f"that you are not able to connect them to somebody on this call. {_DISTRESS} "
        f"{_OFFER_A_CALLBACK}"
    ),
    "not_transferred": (
        "The caller is NOT connected, and the answer does not say why. "
        f"{_NEVER_CLAIM_A_TRANSFER} Tell them you were not able to connect them, and do "
        f"not offer a reason you do not have. {_DISTRESS} {_OFFER_A_CALLBACK}"
    ),
}

#: The machine reason the server sends when nobody was rung and nobody ever will be until
#: a carrier leg exists (`apps/api/worker/tools.ENGINE_CANNOT_TRANSFER`, spelling pinned by
#: `tests/handoff_transfer_seam_test.py`).
#:
#: **READ FOR VERSION SKEW, NOT FOR TODAY'S ANSWER.** The current server sends this reason
#: beside the NARROW word `not_available` and needs no help. A server deployed before the
#: outcome vocabulary widened could only answer `not_transferred` — the wide word, "it did
#: not happen and we cannot say which" — with this reason beside it, and this worker ships
#: on its own schedule to a different platform. Reading the reason keeps a caller on that
#: pairing from hearing the vaguest of the five sentences for the least vague situation.
_ENGINE_CANNOT_TRANSFER: Final[str] = "engine_cannot_transfer"


def _handoff_payload(outcome: HandoffOutcome, *, say: str, reason: str) -> dict[str, str]:
    """What the model reads: the word, what to do about it, the server's detail, the code.

    `outcome` rather than the `status` its three sibling tools use, and the difference is
    real: those pass the server's word through untouched, this one is DERIVED (see
    `handoff_outcome`). One key per meaning. It is the knowledge tool's shape —
    `outcome` + `guidance` — for the knowledge tool's reason: the description is read once
    when the tools are advertised, and this is read in the same breath as the result.
    """
    return {
        "outcome": outcome,
        "guidance": HANDOFF_GUIDANCE[outcome],
        "say": say,
        "reason": reason,
    }


def handoff_outcome(answer: HandoffToolOut) -> HandoffOutcome:
    """The outcome word this answer really means, which is its status except in one case."""
    if answer.status == "not_transferred" and answer.reason == _ENGINE_CANNOT_TRANSFER:
        return "not_available"
    return answer.status


#: What the agent is told when the API could not be reached at all.
#:
#: **`not_transferred` AND NOT `not_available`, THOUGH THE SENTENCES ARE NEARLY THE SAME.**
#: We know the handover did not happen — nothing was asked of anybody — and we do NOT know
#: whether this deployment could have done one. Answering with the confident word would be
#: this module stating a fact about a server it could not reach.
_HANDOFF_UNREACHABLE_REASON: Final[str] = "api_unreachable"
_HANDOFF_UNREACHABLE_SAY = (
    "The system that reaches a person could not be contacted, so nothing was tried and "
    "nobody is coming to this call."
)


def build_call_tools(
    api: CallToolApi | None,
    *,
    tenant_id: UUID,
    call_id: str,
    caller_state: CallerIdentityState = "not_read",
    caller_e164: str | None = None,
) -> list[FunctionSchema]:
    """The four tools, bound to one call. Empty when there is no API to reach.

    **`api is None` MEANS NO TOOL IS ADVERTISED, AND THAT IS THE OPPOSITE OF
    `build_knowledge_tool`'s CHOICE ON PURPOSE.** The knowledge tool is advertised even
    with nothing to search, because a model with no search tool answers a question about a
    client's business from its own priors and invents a fact. These four are ACTS, not
    answers: a model that cannot reach the API cannot perform any of them, and advertising
    four tools that can only ever fail would spend a turn of a live call to arrive at the
    sentence the model could have said without them. `None` is a local run, a replay, or a
    test — never a production session.

    **THE CALL REF IS BUILT HERE FROM THE IDS, AS `sink.py` BUILDS IT**, through
    `calevate_shared.engine.pipecat_call_ref` — the one author of that format, and the only
    legal reader of it. A second spelling of a handle is the drift the quality bar refuses.

    **THE CALLER IDENTITY IS BOUND AT ASSEMBLY, NOT ASKED OF THE MODEL.** Who is on the
    call is a fact from the carrier handshake (`carrier.CallerIdentity`); a model able to
    supply a number in a tool argument could suppress somebody else's. It travels as the
    STATE plus, only when the state is `known`, the number — so the server can answer
    truthfully in the moment rather than letting an ARQ job discover minutes later that
    nothing could be attributed.
    """
    if api is None:
        return []
    engine_call_id = pipecat_call_ref(tenant_id, call_id)
    caller = CallerIdentityIn(
        state=caller_state,
        # THE NUMBER TRAVELS ONLY WITH THE ONE STATE THAT MEANS IT WAS REALLY READ. Sending
        # it under any other state would make the wire disagree with itself, and the server
        # only believes `known` anyway (`worker/tools._subject`).
        e164=caller_e164 if caller_state == "known" else None,
    )

    async def _opt_out(params: FunctionCallParams) -> None:
        request = OptOutToolIn(
            reason=_text_arg(params, "reason", into=OptOutToolIn, clip=True),
            language=_text_arg(params, "language", into=OptOutToolIn),
            caller=caller,
        )
        try:
            answer = await api.opt_out(engine_call_id, request)
        except WorkerApiError as failure:
            _log_failure(OPT_OUT_TOOL_NAME, call_id, failure)
            await params.result_callback(
                {"status": "not_recorded", "say": _OPT_OUT_UNREACHABLE_SAY}
            )
            return
        _log_outcome(OPT_OUT_TOOL_NAME, call_id, answer.status, answer.reason)
        await params.result_callback(
            {"status": answer.status, "say": answer.say, "reason": answer.reason}
        )

    async def _book_callback(params: FunctionCallParams) -> None:
        request = CallbackBookIn(
            callback_date=_text_arg(params, "callback_date", into=CallbackBookIn),
            callback_time=_text_arg(params, "callback_time", into=CallbackBookIn),
            confirmed=_confirmed(params.arguments.get("confirmed")),
            note=_text_arg(params, "note", into=CallbackBookIn, clip=True),
            language=_text_arg(params, "language", into=CallbackBookIn),
            caller=caller,
        )
        try:
            answer = await api.book_callback(engine_call_id, request)
        except WorkerApiError as failure:
            _log_failure(BOOK_CALLBACK_TOOL_NAME, call_id, failure)
            await params.result_callback({"status": "not_booked", "say": _CALLBACK_UNREACHABLE_SAY})
            return
        _log_outcome(BOOK_CALLBACK_TOOL_NAME, call_id, answer.status, answer.reason)
        await params.result_callback(
            {
                "status": answer.status,
                "say": answer.say,
                # THE SPOKEN FORM, which is the whole point of the confirm step: the agent
                # must read back "Tuesday 8 September at 4:00 PM" and not a date it
                # reformatted itself.
                "booked_for": answer.booked_for,
                "reason": answer.reason,
            }
        )

    async def _cancel_callback(params: FunctionCallParams) -> None:
        try:
            answer = await api.cancel_callback(engine_call_id, CallbackCancelIn(caller=caller))
        except WorkerApiError as failure:
            _log_failure(CANCEL_CALLBACK_TOOL_NAME, call_id, failure)
            await params.result_callback(
                {"status": "not_cancelled", "say": _CANCEL_UNREACHABLE_SAY}
            )
            return
        _log_outcome(CANCEL_CALLBACK_TOOL_NAME, call_id, answer.status, answer.reason)
        await params.result_callback(
            {"status": answer.status, "say": answer.say, "reason": answer.reason}
        )

    async def _handoff(params: FunctionCallParams) -> None:
        request = HandoffToolIn(
            reason=_text_arg(params, "reason", into=HandoffToolIn, clip=True),
            summary=_text_arg(params, "summary", into=HandoffToolIn, clip=True),
        )
        try:
            answer = await api.handoff(engine_call_id, request)
        except WorkerApiError as failure:
            _log_failure(HANDOFF_TOOL_NAME, call_id, failure)
            # NOTHING WAS TRIED, WHICH IS ITSELF AN OUTCOME THE AGENT HAS A SENTENCE FOR.
            # The dangerous shape here is a tool that "failed" with no word in it: the model
            # is then free to improvise at somebody who has just asked for help, and what it
            # improvises is "putting you through".
            await params.result_callback(
                _handoff_payload(
                    "not_transferred",
                    say=_HANDOFF_UNREACHABLE_SAY,
                    reason=_HANDOFF_UNREACHABLE_REASON,
                )
            )
            return
        outcome = handoff_outcome(answer)
        _log_outcome(HANDOFF_TOOL_NAME, call_id, outcome, answer.reason)
        await params.result_callback(
            _handoff_payload(outcome, say=answer.say, reason=answer.reason)
        )

    return [
        FunctionSchema(
            name=OPT_OUT_TOOL_NAME,
            description=_OPT_OUT_DESCRIPTION,
            properties={
                "reason": {
                    "type": "string",
                    "description": (
                        "A few of the caller's own words asking not to be called, in the "
                        "language they said them. Kept as evidence of the request; leave "
                        "empty if they did not give one."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": "BCP-47 code of the language they said it in, e.g. te-IN.",
                },
            },
            # NOTHING IS REQUIRED, and that is deliberate: a caller who says "stop calling
            # me" and nothing else must not be blocked by a model waiting for a reason.
            required=[],
            handler=_opt_out,
        ),
        FunctionSchema(
            name=BOOK_CALLBACK_TOOL_NAME,
            description=_BOOK_CALLBACK_DESCRIPTION,
            properties={
                "callback_date": {
                    "type": "string",
                    "description": "The day, as YYYY-MM-DD. Never a relative word.",
                },
                "callback_time": {
                    "type": "string",
                    "description": (
                        "The time, as HH:MM on a 24-hour clock, Indian time. 4 PM is 16:00."
                    ),
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "True ONLY after you have read the resolved time back to the caller "
                        "and they agreed to it. False or absent on the first call."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": (
                        "One short line about what the call back is for, read by the person "
                        "who makes it. If this call back is because you could not reach a "
                        "person, say so here and include what the caller wants — they are "
                        "ringing somebody who has heard none of this conversation."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": "BCP-47 code of the caller's language, e.g. te-IN.",
                },
            },
            required=["callback_date", "callback_time"],
            handler=_book_callback,
        ),
        FunctionSchema(
            name=CANCEL_CALLBACK_TOOL_NAME,
            description=_CANCEL_CALLBACK_DESCRIPTION,
            properties={},
            required=[],
            handler=_cancel_callback,
        ),
        FunctionSchema(
            name=HANDOFF_TOOL_NAME,
            description=_HANDOFF_DESCRIPTION,
            properties={
                "reason": {
                    "type": "string",
                    "description": "One short line on why a person is needed.",
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "One or two lines on what the caller wants and what you have "
                        "already told them, for the person taking the call over. If this "
                        "ends in a call back instead, put the same summary in the "
                        "call-back note so whoever rings is not starting from nothing."
                    ),
                },
            },
            required=[],
            handler=_handoff,
        ),
    ]


def _log_outcome(tool: str, call_id: str, status: str, reason: str) -> None:
    """The tool, the call id, the status word and the machine reason. Nothing else.

    HARD RULE 6: `say` is prose about a caller's request and `reason` is a machine code the
    server authored — the first is never logged and the second always can be. No argument
    the model supplied reaches this line.
    """
    logger.info("in-call tool answered", tool=tool, call_id=call_id, status=status, reason=reason)


def _log_failure(tool: str, call_id: str, failure: WorkerApiError) -> None:
    """A tool the API could not answer. The TYPE, never the message (`api_client`'s rule)."""
    logger.warning(
        "in-call tool unanswered", tool=tool, call_id=call_id, reason=type(failure).__name__
    )


__all__ = [
    "BOOK_CALLBACK_TOOL_NAME",
    "CANCEL_CALLBACK_TOOL_NAME",
    "HANDOFF_GUIDANCE",
    "HANDOFF_TOOL_NAME",
    "OPT_OUT_TOOL_NAME",
    "TOOL_BUDGET_S",
    "CallToolApi",
    "CallToolApiClient",
    "build_call_tools",
    "handoff_outcome",
]
