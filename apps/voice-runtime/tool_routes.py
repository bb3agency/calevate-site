"""In-call tool endpoints. LATENCY-CRITICAL (hard rule 3). Three of them.

`POST /tools/v1/{engine}/opt-out` is the engine-side custom function an agent invokes the
moment a caller says "don't call me again". SEC-COMP §2.3 asks for precisely this ("⇒ tool
adds to tenant `dnc_list` within the call"), and `apps/api/compliance/optout.py` argues at
length why it is built ALONGSIDE the post-call transcript pass rather than instead of it.

The same five obligations the webhook receiver carries, for the same reasons, and the
helpers are IMPORTED from it rather than re-implemented — a second ack-measuring,
body-bounding, source-verifying implementation in the same tiny service is the "two ways
of doing one thing" CLAUDE.md calls a defect even when both work:

1. verify the source before reading a byte of body;
2. ack under 500ms, measured and reported on every path including the refusals — into
   `tool_ack_ms`, this endpoint's OWN series, because the budget that actually governs it
   is TRD §6.2's 100ms and a percentile pooled with the post-call receiver's could never
   show it (D-109 measured the server half at p95 1.4ms single-flight and ~143ms at 250
   concurrent, so the number this series carries is one somebody has to be able to read);
3. defer the real work to ARQ — the tenant, the number and the call are resolved in
   `apps/workers/optout.py` from an authenticated Get Execution (D-31: the payload is a
   hint, the fetch is the truth);
4. no DB writes at all here — this endpoint does not even claim an inbox row, because
   there is no at-most-once event to dedupe: a repeated tool call collapses on the ARQ
   job id, and duplicate suppression of the same number is a no-op by construction;
5. answer every request deliberately — an unsigned endpoint gets malformed bodies,
   enormous bodies and payloads with no execution id, and none of them may be a 500.

WHAT IS ASSUMED AND WHAT IS VERIFIED (D-31/D-32 — an unverified vendor behaviour is a
gate or a marked assumption, never a silent premise):

* VERIFIED: nothing about Bolna's custom-function mechanism. It is OPERATIONS §2 gate 8
  ("test a custom function to our endpoint and record the tool-call p95 — **no timeout is
  documented**").
* ASSUMED, and the assumption is confined to this file: that the engine can be configured
  to POST a JSON body carrying the execution id of the call in progress, and that it
  tolerates a small JSON object in reply. Nothing downstream depends on the SHAPE of that
  body beyond one string, and the endpoint accepts the three spellings an engine plausibly
  uses (`execution_id`, `id`, `call_id`) rather than betting on one.
* CONSEQUENCE, stated plainly rather than hidden: until gate 8 is run and the engine is
  configured with this function, this route is reachable and correct but **nothing calls
  it**, and the post-call transcript pass is what actually closes the compliance hole. The
  route is not half-wired — it is mounted, registered, tested and its job is registered —
  but it is not yet EXERCISED by the vendor, and no reader should mistake one for the
  other.

The reply is `{"status": "accepted"}` and never "done": the write happens in a worker a
few hundred milliseconds later. What the agent may safely tell the caller is that the
request is registered — which is true the moment the job is queued, because the queue is
durable and the post-call pass is behind it.

THE CALLBACK PAIR (D-514) FOLLOWS THAT SHAPE EXACTLY, WITH ONE ADDITION
--------------------------------------------------------------------------------------
`POST /callback` books "ring me back Tuesday at four" and `POST /callback/cancel` calls it
off. Same five obligations, same helpers, same deferral — but the booking endpoint
ANSWERS A QUESTION as well as accepting work, and that is the whole reason it is allowed
to compute anything at all before it queues.

**The refusal has to reach the caller while they are still on the phone.** A time outside
09:00-21:00 IST is not merely unbookable, it is unlawful to dial (TCCCPR; SEC-COMP §3), and
a callback the gate will silently refuse two days later is worse than one that was never
booked — somebody was told we would ring. So `calevate_shared.calling_window.resolve_slot`
runs HERE, inline: two `strptime` calls and three comparisons over short strings, no IO, no
database, no model call. It is the only work this service does that is not deferred, and it
is deferred-work's opposite for a reason that is measurable rather than stylistic — the
answer must be in the tool response the engine feeds back to the agent's LLM, which
"continues the conversation naturally"
(`bolna-findings/mirror/pages/tool-calling/custom-function-calls.md:42-44`).

**CONFIRM-BEFORE-COMMIT IS A SERVER-SIDE CONTROL, NOT AN INSTRUCTION IN A PROMPT.** The
model resolves "Tuesday at four" into a date and a 24-hour time by talking to the caller;
we cannot see that conversation and must not assume it happened. So the tool takes a
`confirmed` flag, refuses to book without it, and hands back the resolved time in the
unambiguous spoken form the agent is to read out ("Tuesday 8 September at 4:00 PM"). Two
turns, and the second one costs a caller three seconds; a wrong one costs them a phone call
at four in the morning. The dangerous half of every am/pm ambiguity is closed structurally
as well — every hour before 09:00 is outside the calling window and cannot be booked at all
(see `resolve_slot`).

WHAT IS ASSUMED HERE AND WHAT IS VERIFIED (D-31/D-32), for the callback pair:

* VERIFIED, from the hash-pinned vendor mirror: a custom function is defined by an OpenAI
  function schema plus a Bolna `value` block, `"key": "custom_task"` is mandatory
  (`custom-function-calls.md:70,176`), parameters are collected from the conversation by
  the LLM and typed `string`/`integer`/`number`/`boolean` (`:226-234`), only members of
  `required` are insisted on (`:237-240`), the `param` map uses `%(name)s` specifiers whose
  names must match `properties` exactly (`:274-284`), and `{call_sid}`, `{agent_id}`,
  `{from_number}`, `{to_number}` are auto-injected context variables (`:581-586`). The
  response is fed back to the LLM (`:42-44`), and a `pre_call_message` is what the agent
  says while we answer (`:250`) — which is what covers our own round trip.
* ASSUMED, and confined to this file exactly as for the opt-out: that the body can be made
  to carry the id of the execution in progress. The documented auto-injected variable is
  `{call_sid}`, which the vendor describes as the TELEPHONY call id "from Twilio, Plivo,
  etc." — not necessarily the execution id `GET /executions/{id}` takes. So the payload is
  read through `execution_key`, which accepts three spellings, and the WORKER re-derives
  everything that matters from an authenticated fetch. OPERATIONS §2 gate 8 covers it.
* CONSEQUENCE, stated plainly: until gate 8 is run and the two functions are configured on
  the agent, these routes are mounted, tested and their jobs registered, and nothing calls
  them. That is not the same as half-wired, and no reader should read it as either.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.settings import get_settings
from calevate_shared.calling_window import SlotRefusal, resolve_slot
from calevate_shared.client_address import client_ip
from engine_intake import engine_label, execution_key, scalar_hint, verify_source
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

# The ack accounting and the bounded read, from the receiver that already owns them.
# Private by convention, not by intent — see the module docstring. `TOOL_ACK` is what
# tells the two endpoints apart inside those shared helpers: this one's acks land in
# `tool_ack_ms` and its breaches are named `tool_*`, so the in-call budget (TRD §6.2,
# 100ms) can be read off a series of its own instead of being averaged into the post-call
# receiver's `webhook_ack_ms`.
#
# **AND THE DEADLINES AND THE SIZE CAP TRAVEL WITH IT NOW.** This module used to import
# `_DURABLE_DEADLINE_S` by name and inherit `_BODY_DEADLINE_S` through a default argument
# — the RECEIVER's two seconds each, on the one endpoint in this service where a person
# is listening to the wait. Four seconds of dead air mid-call, on numbers justified by a
# sentence ("the cost of being wrong is one poller cycle") that this file's own docstring
# contradicts one paragraph later. They are per-surface facts and they now sit on the
# per-surface descriptor, argued where it is declared.
from webhook_routes import TOOL_ACK, _ack, _read_bounded, measured

log = get_logger(__name__)

router = APIRouter(prefix="/tools/v1", tags=["in-call-tools"])

# Must equal `apps.workers.optout.OPTOUT_JOB`. Spelled as a literal rather than imported,
# because `apps.workers` is FORBIDDEN in this process (hard rule 3, and
# `tests/voice_runtime_import_surface_test.py` enforces it) — the receiver spells
# `ingest_engine_event` the same way for the same reason. The two are asserted equal in
# `tests/call_optout_test.py`, so the duplication cannot drift.
OPTOUT_JOB = "record_in_call_optout"

# Must equal `apps.workers.callbacks.BOOK_JOB` / `CANCEL_JOB`. Literals for OPTOUT_JOB's
# reason (`apps.workers` is forbidden in this process), asserted equal in
# `tests/callback_tool_test.py` so the duplication cannot drift.
BOOK_CALLBACK_JOB = "book_requested_callback"
CANCEL_CALLBACK_JOB = "cancel_requested_callback"

# Must equal `apps.workers.handoff.HANDOFF_JOB`. A literal for the reason above (`apps.
# workers` is forbidden in this process), asserted equal in `tests/handoff_tool_test.py`.
HANDOFF_JOB = "record_handoff_started"


class ToolAckOut(BaseModel):
    """The in-call tool's ack, declared for the reason `WebhookAckOut` is (D-303).

    "Accepted" is the only thing this route can truthfully say — the suppression is
    written by a worker a few hundred milliseconds later — so the status is a one-value
    `Literal` rather than a free string, and the model refuses anything else.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"]
    execution_id: str
    job_id: str


@router.post(
    "/{engine}/opt-out",
    status_code=202,
    response_model=ToolAckOut,
    summary="In-call opt-out (engine custom function) — queues the suppression",
)
async def in_call_opt_out(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()
    return await measured(
        started, engine, _opt_out(engine, request, response, started), meter=TOOL_ACK
    )


async def _opt_out(
    engine: str, request: Request, response: Response, started: float
) -> dict[str, str]:
    """The tool call proper. Split from the route only so `measured` can wrap every exit.

    Verification, the bounded read and the execution key are `_tool_payload`'s, and the
    enqueue's deadline and refusal are `_durable`'s — both shared with the callback pair
    below rather than copied into it, which is the same argument this module's docstring
    makes for importing the ack accounting from the receiver instead of writing a second
    one. The `enqueue` call itself stays here, naming its job as a literal, for the reason
    `_durable` records.
    """
    payload, execution_id = await _tool_payload(engine, request)
    job_id: str | None = None
    async with _durable(
        engine,
        started,
        "The request was not registered; please tell the caller it will be handled.",
    ):
        job_id = await enqueue(
            OPTOUT_JOB,
            {
                "engine": engine,
                "execution_id": execution_id,
                # HINTS ONLY, both bounded and both re-derived downstream where it
                # matters: the worker reads the number, the direction and the tenant from
                # the authenticated fetch. These two only become evidence text.
                #
                # `scalar_hint`, NOT `str(...)`. `str()` renders a CONTAINER with Python's
                # repr, so a caller sending `{"reason": {"a": 1}}` filed `"{'a': 1}"` as
                # the words a caller used to withdraw consent — into `consent_ledger`,
                # which is append-only (hard rule 4) and is the evidence this platform
                # would show a regulator. A reason we cannot read is no reason at all, and
                # an empty one is honest.
                "reason": (scalar_hint(payload.get("reason")) or "")[:200],
                "language": (scalar_hint(payload.get("language")) or "")[:8],
            },
            # One suppression per execution: the model invoking the function twice, or the
            # engine retrying it, must not queue two jobs. Not a correctness requirement —
            # `record_call_optout` is idempotent — but a queue that collapses the duplicate
            # is cheaper than a database that does.
            job_id=job_id_for(OPTOUT_JOB, engine, execution_id),
        )
    # Ids only (hard rule 6): no number is in this payload and none is in this line.
    log.info("in_call_optout_queued", extra={"engine": engine, "job_id": job_id or "deduped"})
    return _ack(
        response,
        started,
        engine,
        {"status": "accepted", "execution_id": execution_id, "job_id": job_id or "deduped"},
        meter=TOOL_ACK,
    )


class CallbackToolOut(BaseModel):
    """The callback tool's three answers, declared for the reason `ToolAckOut` is.

    ONE MODEL, THREE STATUSES, because they are three outcomes of one conversational turn
    rather than three endpoints: the agent asks "can I book this", and the answer is yes,
    "read it back first", or "not that time, try this one". Every field is a string so the
    shared ack helpers (`_ack`, `measured`) keep their one signature, and the optional ones
    default to empty rather than being absent — a model reading a missing key and a model
    reading an empty one behave differently, and the empty string is the one we can test.

    `say` is guidance for the agent, in English, which its own LLM renders into the
    caller's language; `booked_for` is the unambiguous spoken form it must read back.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "needs_confirmation", "not_booked"]
    execution_id: str
    say: str
    booked_for: str = ""
    reason: str = ""
    job_id: str = ""


@router.post(
    "/{engine}/callback",
    status_code=202,
    response_model=CallbackToolOut,
    summary="Book the call-back a caller asked for (engine custom function)",
)
async def book_callback(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()
    return await measured(
        started, engine, _book_callback(engine, request, response, started), meter=TOOL_ACK
    )


async def _book_callback(
    engine: str, request: Request, response: Response, started: float
) -> dict[str, str]:
    """Resolve the time, insist on a confirmation, then queue the booking."""
    payload, execution_id = await _tool_payload(engine, request)

    slot = resolve_slot(
        scalar_hint(payload.get("callback_date")),
        scalar_hint(payload.get("callback_time")),
        now=datetime.now(UTC),
    )
    if isinstance(slot, SlotRefusal):
        # 200 AND NOT A 4xx, deliberately. This is a normal turn of a conversation — the
        # caller asked for ten at night and we may not ring them then — and the vendor's
        # own troubleshooting reads a failing tool call as a misconfiguration
        # (`custom-function-calls.md:810-813`). An error would tell the agent that OUR API
        # is broken; what it needs to hear is what to offer the caller instead. The 4xx
        # codes below are kept for the protocol failures they belong to (a stranger, an
        # enormous body, a payload naming no call).
        response.status_code = 200
        return _ack(
            response,
            started,
            engine,
            {
                "status": "not_booked",
                "execution_id": execution_id,
                "reason": slot.code,
                "say": slot.say,
                "booked_for": slot.alternative.spoken if slot.alternative else "",
            },
            meter=TOOL_ACK,
        )

    if not _truthy(payload.get("confirmed")):
        # CONFIRM BEFORE COMMIT. The one thing this endpoint can enforce about a value a
        # model interpreted is that somebody said it back out loud first — see the module
        # docstring. The agent gets the resolved time in the form it must read; the caller
        # gets the chance to say "no, four in the afternoon".
        response.status_code = 200
        return _ack(
            response,
            started,
            engine,
            {
                "status": "needs_confirmation",
                "execution_id": execution_id,
                "booked_for": slot.spoken,
                "say": (
                    f"Read this back to the caller exactly: {slot.spoken}. If they agree, "
                    "call this again with the confirmation set. If they want a different "
                    "time, ask for it and start again."
                ),
            },
            meter=TOOL_ACK,
        )

    job_id: str | None = None
    async with _durable(
        engine,
        started,
        "The call-back was not booked. Tell the caller we could not save it and ask them "
        "to say it again.",
    ):
        job_id = await enqueue(
            BOOK_CALLBACK_JOB,
            {
                "engine": engine,
                "execution_id": execution_id,
                # THE RESOLVED INSTANT, not the caller's words. The worker must never
                # re-parse a time — one parser, in one place, with one set of refusals, is
                # what stops the endpoint refusing 22:00 and the worker booking it.
                "requested_at": slot.at_utc.isoformat(),
                # WHEN THE CALLER ASKED, so two bookings in one conversation resolve to the
                # LATER word whichever job commits first (`callbacks.service.book`).
                "booked_at": datetime.now(UTC).isoformat(),
                # HINTS ONLY, bounded, and `scalar_hint` rather than `str()` for the reason
                # spelled out on the opt-out payload above: `str()` renders a container
                # with Python's repr, and this one is read out to a person on the call-back.
                "note": (scalar_hint(payload.get("note")) or "")[:200],
                "language": (scalar_hint(payload.get("language")) or "")[:8],
            },
            # One promise per execution: the model invoking the function twice with the
            # same answer, or the engine retrying it, must not queue two jobs. The
            # BOOKED-FOR time is in the key, so a caller who genuinely changes their mind
            # ("make it five") gets a second job that supersedes the first — which is
            # exactly the case a job id keyed on the execution alone would have swallowed.
            job_id=job_id_for(BOOK_CALLBACK_JOB, engine, execution_id, slot.at_utc.isoformat()),
        )
    log.info("in_call_callback_queued", extra={"engine": engine, "job_id": job_id or "deduped"})
    return _ack(
        response,
        started,
        engine,
        {
            "status": "accepted",
            "execution_id": execution_id,
            "booked_for": slot.spoken,
            "job_id": job_id or "deduped",
            "say": f"Tell the caller that is booked: {slot.spoken}.",
        },
        meter=TOOL_ACK,
    )


@router.post(
    "/{engine}/callback/cancel",
    status_code=202,
    response_model=CallbackToolOut,
    summary="Call off a call-back this caller had booked (engine custom function)",
)
async def cancel_callback(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()
    return await measured(
        started, engine, _cancel_callback(engine, request, response, started), meter=TOOL_ACK
    )


async def _cancel_callback(
    engine: str, request: Request, response: Response, started: float
) -> dict[str, str]:
    """ "Actually, don't call me back." Its own function rather than a flag on the booking.

    A flag would have meant the model choosing between two behaviours of one tool from one
    description, and the vendor is explicit that the description is what makes triggering
    reliable (`custom-function-calls.md:47-49, 804-807`). It is also a DIFFERENT promise: a
    cancellation must not be able to fail because a date could not be parsed, so this path
    has no time in it at all.

    It is NOT the opt-out. "Do not ring me back on Tuesday" is not "never call me again",
    and answering it with a DNC entry would suppress a number on a sentence its speaker did
    not say. The opt-out tool beside it is the one that does that, and `record_call_optout`
    is what it reaches.
    """
    _payload, execution_id = await _tool_payload(engine, request)
    job_id: str | None = None
    async with _durable(
        engine,
        started,
        "The call-back was not called off. Tell the caller we could not do it just now.",
    ):
        job_id = await enqueue(
            CANCEL_CALLBACK_JOB,
            {"engine": engine, "execution_id": execution_id},
            # Cancelling twice is cancelling once — collapsing on the execution is free.
            job_id=job_id_for(CANCEL_CALLBACK_JOB, engine, execution_id),
        )
    log.info("in_call_callback_cancel", extra={"engine": engine, "job_id": job_id or "deduped"})
    return _ack(
        response,
        started,
        engine,
        {
            "status": "accepted",
            "execution_id": execution_id,
            "job_id": job_id or "deduped",
            "say": "Tell the caller we will not ring them back.",
        },
        meter=TOOL_ACK,
    )


@router.post(
    "/{engine}/handoff",
    status_code=202,
    response_model=ToolAckOut,
    summary="A handover to a person has started (engine pre-call webhook)",
)
async def handoff_started(engine: str, request: Request, response: Response) -> dict[str, str]:
    started = time.perf_counter()
    return await measured(
        started, engine, _handoff_started(engine, request, response, started), meter=TOOL_ACK
    )


async def _handoff_started(
    engine: str, request: Request, response: Response, started: float
) -> dict[str, str]:
    """The engine tells us, mid-call, that it is about to put the caller through (D-533).

    **THIS IS NOT A TOOL THE MODEL CALLS AND ITS REPLY REACHES NOBODY.** The other three
    endpoints on this router are custom functions whose response is fed back to the LLM and
    spoken; this is the transfer tool's PRE-CALL WEBHOOK, which the vendor describes as
    fire-and-forget — *"A slow or failing webhook endpoint never blocks or delays the
    transfer itself"* (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/tool-calling/
    transfer-calls.md`, "Pre-call Webhook"; VERIFIED-OSS: `bolna-ai/bolna@cd2e192`,
    `bolna/agent_manager/task_manager.py:3143-3160`, fired as a background task with errors
    swallowed, BEFORE the leg is placed). So nothing here can refuse a handover, delay one,
    or tell the agent anything — and the ack discipline still applies in full, because a
    slow endpoint is dead air on a live call whether or not the vendor promises otherwise.
    A vendor's promise is not a budget we get to spend.

    **IT IS THE ONLY SIGNAL THAT EXISTS WHILE THE CALL IS STILL HAPPENING**, which is why
    it is worth an endpoint at all. Everything else about the handover — whether the person
    picked up, how long they spoke, whether a second recording was made — arrives minutes
    later on the execution record. This is what lets the person whose phone is ringing be
    told what the call is about, and it is the nearest honest thing to the whisper the
    founder asked for: a message on their phone, not a voice in their ear (see
    `agents/handoff.py`, and `docs/evidence/handoff-warm-transfer.md` for why).

    THE FIVE OBLIGATIONS ARE THE SAME as every other handler here, and the fourth is worth
    naming: **no DB writes at all**. The `handoff_attempts` row is written by the worker,
    from an AUTHENTICATED execution fetch — this payload names a tenant to nobody and
    carries the model's own prose about a live conversation, which is a hint (D-31), not a
    record.
    """
    payload, execution_id = await _tool_payload(engine, request)
    job_id: str | None = None
    async with _durable(
        engine,
        started,
        # Nobody hears this sentence — see the docstring — but the shape is shared with the
        # three tools above and a `_durable` block with no detail would be the odd one out.
        "The handover notice was not recorded.",
    ):
        job_id = await enqueue(
            HANDOFF_JOB,
            {
                "engine": engine,
                "execution_id": execution_id,
                # THE MODEL'S OWN WORDS, PASSED THROUGH UNREAD AND UNLOGGED. Both are
                # conversation content: the worker redacts them before either touches a
                # column (hard rule 6), and nothing on this path may look at them. They are
                # carried rather than re-derived because they exist ONLY here — the
                # execution record's own `summary` is not populated until the call ends
                # (`transfer-calls.md`: "fields that are only finalized at call end ...
                # won't be complete yet"), and the whole point is to reach the person while
                # their phone is still ringing.
                "reason": scalar_hint(payload.get("reason")),
                "summary": scalar_hint(payload.get("summary")),
            },
            # One handover per conversation, which is the ENGINE's own behaviour and not
            # our policy (`task_manager.py:3116-3126`), so collapsing on the execution
            # cannot lose a second real one.
            job_id=job_id_for(HANDOFF_JOB, engine, execution_id),
        )
    # Ids only. Not the reason, not the summary, not the destination (hard rule 6).
    log.info("in_call_handoff_started", extra={"engine": engine, "job_id": job_id or "deduped"})
    return _ack(
        response,
        started,
        engine,
        {"status": "accepted", "execution_id": execution_id, "job_id": job_id or "deduped"},
        meter=TOOL_ACK,
    )


def _truthy(value: Any) -> bool:
    """Did the model say yes? Booleans, and the two strings a JSON-ish model produces.

    NARROW ON PURPOSE. This decides whether a caller heard their appointment read back, so
    it says yes to `true`, `"true"` and `"yes"` and to nothing else — not to `1`, not to a
    non-empty string, not to Python's truthiness. An unrecognised value is an unconfirmed
    booking, which costs one conversational turn; the other direction costs a wrong time.
    """
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in {"true", "yes"}


async def _tool_payload(engine: str, request: Request) -> tuple[dict[str, Any], str]:
    """Verify the source, read the body, key it by execution. The three obligations every
    tool call on this router shares, in one place rather than three.

    Extracted when the callback pair arrived: `_opt_out` had done all three inline, and a
    second and third copy of "verify, bound, decode, key" is exactly the drift this
    module's docstring refuses to accept from the ack accounting one paragraph above it.
    """
    source_ip = client_ip(
        request.client.host if request.client else None,
        request.headers,
        app_env=get_settings().app_env,
    )
    verdict = verify_source(engine, source_ip)
    if not verdict.ok:
        alert(
            "ROUTE_HANDLER",
            "tool_source_rejected",
            detail=verdict.reason,
            # Bounded for the receiver's reason — see `webhook_routes._receive`.
            engine=engine_label(engine),
            source_ip=source_ip or "unknown",
        )
        raise ProblemError.unauthorized("This caller is not permitted to call this tool.")

    raw = await _read_bounded(request, engine=engine, meter=TOOL_ACK)
    if raw is None:
        alert("ROUTE_HANDLER", "tool_payload_too_large", engine=engine)
        raise ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Payload too large",
            detail="The tool call body exceeds the accepted size.",
            status=413,
        )

    payload: dict[str, Any] = {}
    try:
        decoded = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        decoded = None
    if isinstance(decoded, dict):
        payload = decoded

    execution_id = execution_key(payload)
    if execution_id is None:
        # A 422, not an ack — `_opt_out`'s comment carries the full argument, and it holds
        # here twice over: a booking nobody can attribute to a call is a promise with no
        # phone number behind it, and the agent must hear a failure so it can say so.
        alert("ROUTE_HANDLER", "tool_call_unkeyable", engine=engine)
        raise ProblemError(
            kind="validation",
            code="tool_call_unkeyable",
            title="Missing execution id",
            detail="The tool call did not name the execution it belongs to.",
            status=422,
        )
    return payload, execution_id


@asynccontextmanager
async def _durable(engine: str, started: float, failure_detail: str) -> AsyncIterator[None]:
    """Hold the durable deadline over an enqueue, or refuse in words the agent can say.

    **A WRAPPER RATHER THAN A `_queue(job, payload)` HELPER, AND THE REASON IS A GUARD
    RATHER THAN TASTE.** The obvious shape — one function taking the job name and calling
    `enqueue` — puts the name in a PARAMETER, and `scripts/check_job_wiring` reads enqueue
    sites from the AST: a name it cannot resolve is a name it cannot compare against the
    worker registry, which is exactly the hole that check exists to close. That shape cost
    an entry in its `DYNAMIC_ENQUEUE_SITES`, on three of this platform's quietest failures
    — an agent tells a caller their call-back is booked, arq does not recognise the name,
    and unlike the opt-out there is no post-call pass behind it.

    Wrapping keeps both: the deadline, the alert and the refusal wording live in ONE place,
    and every `enqueue` stays a literal call naming a module-level constant the guard can
    read. The exemption was withdrawn rather than argued for.
    """
    try:
        async with asyncio.timeout(TOOL_ACK.durable_deadline_s):
            yield
    except TimeoutError:
        elapsed = (time.perf_counter() - started) * 1000
        alert("ROUTE_HANDLER", "tool_enqueue_timeout", detail=f"{elapsed:.0f}ms", engine=engine)
        raise ProblemError(
            kind="transient",
            code="tool_queue_unavailable",
            title="That could not be saved",
            detail=failure_detail,
        ) from None


__all__ = [
    "BOOK_CALLBACK_JOB",
    "CANCEL_CALLBACK_JOB",
    "HANDOFF_JOB",
    "OPTOUT_JOB",
    "router",
]
