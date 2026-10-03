"""Carrier status and hangup callbacks → the inbox → ARQ. LATENCY-CRITICAL (hard rule 3).

`POST|GET /carrier/v1/{carrier}/events/{ref}[/outbound/{call_id}]` is the URL the control
plane gives the carrier as `hangup_url` / `ring_url` (`calevate_shared.carrier.
events_path`). The route authenticates the sender (`carrier_routes.admit`), keys the
callback on `CallUUID` + `Event`, and hands everything after that to the engine
receiver's own machinery (`webhook_routes.settle`): the Redis fast path, the inbox claim
and forensic row and enqueue in one transaction under the durable deadline, `X-Ack-Ms`.
One implementation, two intake surfaces.

The key is the TRANSITION, not the call: Vobiz sends one callback per `Event` with the
same `CallUUID` (`vobiz-findings/mirror/pages/concepts/callbacks.md:70-105`) and retries a
non-200 up to three times (`:125-126`), so a retry is a duplicate and a new event is not.

HARD RULE 6. A callback carries `From` and `To` (`call/make-call.md:177-195`). The job
payload's `fields` is the callback minus every party number (`event_fields`); the route
logs and alerts with ids and labels only.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Final

from apps.api.core.alerting import alert
from apps.api.core.queue import job_id_for
from apps.api.reliability.service import body_hash
from calevate_shared.carrier import CARRIER_EVENT_JOB
from carrier_routes import (
    CARRIER_ACK,
    admit,
    parse_call_id,
    parse_ref,
    read_params,
    refuse,
)
from engine_intake import keyable
from fastapi import APIRouter, Request, Response
from webhook_routes import InboxWork, WebhookAckOut, acknowledge_ignored, measured, settle

router = APIRouter(prefix="/carrier/v1", tags=["carrier"])

#: The job this route enqueues, spelled as a literal so `scripts.check_job_wiring` can pair it
#: with its registration in `apps/workers/settings.py`; the shared constant is the source.
INGEST_CARRIER_EVENT_JOB: Final = "ingest_carrier_event"
assert INGEST_CARRIER_EVENT_JOB == CARRIER_EVENT_JOB

#: Fields that name a party to the call, by the vendor's own spelling
#: (`xml/request.md:30-32`, `call/make-call.md:159-195`, `xml/dial.md`).
_PARTY_FIELDS: Final = frozenset(
    {"From", "To", "CallerName", "ForwardedFrom", "DialBLegFrom", "DialBLegTo"}
)

#: Fields that are ids, states, durations or times — kept even when their value is
#: digit-heavy (an epoch timestamp, a hangup cause code).
_KEPT_FIELDS: Final = frozenset(
    {
        "CallUUID",
        "Event",
        "CallStatus",
        "Direction",
        "HangupCause",
        "HangupCauseCode",
        "HangupSource",
        "Duration",
        "BillDuration",
        "StartTime",
        "AnswerTime",
        "EndTime",
        "SessionStart",
        "Timestamp",
        "timestamp",
        "ALegUUID",
        "ALegRequestUUID",
        "RequestUUID",
        "StreamID",
        "Error",
        "DialBLegUUID",
        "DialBLegStatus",
        "DialStatus",
        "DialAction",
        "DialBLegDuration",
        "DialBLegBillDuration",
        "DialBLegHangupCause",
        "MachineDetection",
        # `RecordStop` (`xml/record/stream-with-record.md:54-78`, `xml/record.md:43-62`).
        # Ids, durations, epoch milliseconds and a reason word: an epoch in ms is thirteen
        # digits and a uuid can hold a seven-digit run, so the value test below would drop
        # exactly the fields the recording copy needs. The file URLs (`RecordUrl`,
        # `RecordFile`) are deliberately NOT kept: the worker asks the carrier's API for
        # the recording by id, so nothing downstream trusts a URL off the wire.
        "RecordingID",
        "RecordingDuration",
        "RecordingDurationMs",
        "RecordingStartMs",
        "RecordingEndMs",
        "RecordingEndReason",
    }
)

#: Fields no worker reads and nothing should hold: a recording's file URL, which the worker
#: re-resolves from the carrier's API by `RecordingID` instead of trusting the wire.
_NEVER_FORWARDED: Final = frozenset({"RecordUrl", "RecordFile"})

#: A field NAME with one of these words in it may hold a number; dropped unread.
_PARTY_WORDS: Final = frozenset(
    {"from", "to", "caller", "callee", "number", "phone", "msisdn", "ani", "dnis", "sip", "uri"}
)

#: A VALUE with seven or more digits once separators are removed is treated as a number.
_SEPARATORS: Final = re.compile(r"[\s().+-]")
_DIGIT_RUN: Final = re.compile(r"\d{7,}")
_NAME_WORD: Final = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")

_MAX_FIELDS: Final = 64
_MAX_VALUE_CHARS: Final = 256


def _may_name_a_party(name: str, value: str) -> bool:
    if name in _PARTY_FIELDS:
        return True
    if name in _KEPT_FIELDS:
        return False
    if any(word.lower() in _PARTY_WORDS for word in _NAME_WORD.findall(name)):
        return True
    return bool(_DIGIT_RUN.search(_SEPARATORS.sub("", value)))


def event_fields(params: Mapping[str, str]) -> dict[str, str]:
    """The callback's fields minus anything that could be a phone number (hard rule 6).

    An allowlist would be safer still and would drop fields the worker has not been
    written against yet; this keeps every field that is provably not a number and drops
    the rest, failing in the direction of losing a field rather than leaking a number.
    """
    kept: dict[str, str] = {}
    for name, value in params.items():
        if len(kept) >= _MAX_FIELDS:
            break
        if len(name) > _MAX_VALUE_CHARS or len(value) > _MAX_VALUE_CHARS:
            continue
        if name in _NEVER_FORWARDED or _may_name_a_party(name, value):
            continue
        kept[name] = value
    return kept


async def _receive(
    carrier: str,
    ref: str,
    call_id: str | None,
    request: Request,
    response: Response,
    started: float,
) -> dict[str, str]:
    """Source and signature, then the ref, then the body — the order every carrier route
    keeps, so a caller we refuse never gets us to allocate for them."""
    surface = "events"
    contract, verdict = admit(carrier, request, surface=surface)
    if not contract.status_callbacks:
        raise refuse("status_callbacks_not_supported", carrier=carrier, surface=surface)
    parse_ref(ref, carrier=carrier, surface=surface)
    ours = parse_call_id(call_id, carrier=carrier, surface=surface) if call_id else None
    params, readable = await read_params(request, carrier=carrier)

    carrier_call_id = keyable(params.get("CallUUID", ""))
    event = keyable(params.get("Event") or "unknown")
    if carrier_call_id is None or event is None:
        # Acked: a callback we cannot key we can never dedupe, and a non-200 would only
        # make the vendor send it three more times.
        alert("ROUTE_HANDLER", "webhook_unkeyable", engine=carrier)
        return acknowledge_ignored(
            response,
            started,
            carrier,
            reason="unusable call key" if readable else "unreadable payload",
            meter=CARRIER_ACK,
        )

    return await settle(
        InboxWork(
            provider=carrier,
            key_id=carrier_call_id,
            event_name=event,
            payload_hash=body_hash(
                {"carrier": carrier, "carrier_call_id": carrier_call_id, "event": event}
            ),
            redis_key=f"calevate:wh:carrier:{carrier}:{carrier_call_id}:{event}",
            job=INGEST_CARRIER_EVENT_JOB,
            job_id=job_id_for(INGEST_CARRIER_EVENT_JOB, carrier, carrier_call_id, event),
            job_payload={
                "carrier": carrier,
                "carrier_call_id": carrier_call_id,
                "event": event,
                "engine_agent_ref": ref,
                "call_id": ours,
                "fields": event_fields(params),
            },
        ),
        params_digest(params),
        response=response,
        started=started,
        meter=CARRIER_ACK,
        signed=verdict.method == "signature",
    )


def params_digest(params: Mapping[str, str]) -> bytes:
    """The bytes the fast path fingerprints: the parsed parameters in a stable order, so a
    GET and a POST of one callback are the same delivery."""
    return "&".join(f"{name}={params[name]}" for name in sorted(params)).encode()


@router.api_route(
    "/{carrier}/events/{ref}",
    methods=["GET", "POST"],
    include_in_schema=False,
    response_model=WebhookAckOut,
    response_model_exclude_none=True,
)
async def carrier_events(
    carrier: str, ref: str, request: Request, response: Response
) -> dict[str, str]:
    """A status or hangup callback for an inbound call (200, never 202: Vobiz retries a
    non-200, `concepts/callbacks.md:125-126`)."""
    started = time.perf_counter()
    return await measured(
        started,
        carrier,
        _receive(carrier, ref, None, request, response, started),
        meter=CARRIER_ACK,
    )


@router.api_route(
    "/{carrier}/events/{ref}/outbound/{call_id}",
    methods=["GET", "POST"],
    include_in_schema=False,
    response_model=WebhookAckOut,
    response_model_exclude_none=True,
)
async def carrier_events_outbound(
    carrier: str, ref: str, call_id: str, request: Request, response: Response
) -> dict[str, str]:
    """A callback for a call we dialled; our call id rides the PATH, which is signed."""
    started = time.perf_counter()
    return await measured(
        started,
        carrier,
        _receive(carrier, ref, call_id, request, response, started),
        meter=CARRIER_ACK,
    )


__all__ = ["event_fields", "params_digest", "router"]
