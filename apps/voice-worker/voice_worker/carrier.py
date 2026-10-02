"""The carrier leg: a Vobiz or Plivo media stream becomes a running pipeline
(`docs/PIPECAT-MIGRATION.md` §6 step 6, `docs/evidence/vobiz-integration-plan.md` §3).

**WHAT THIS MODULE IS FOR, IN ONE SENTENCE.** It turns a carrier connection into a routed
agent, a validated handshake and a Pipecat transport with the right serializer, and it is
the only place in this deployable that knows which carriers exist.

**WHICH CARRIER A SOCKET IS.** Our control plane claims it on the stream URL
(`carrier=vobiz|plivo`, minted by `apps/voice-runtime/carrier_routes.py`); without a claim
the worker's own `CARRIER` setting decides. Pipecat's auto-detection cannot tell the two
apart — a Vobiz `start` carries the exact keys Pipecat reads as Plivo
(`calevate_shared.carrier.WIRE_FAMILY`) — so detection CHECKS the claim and never chooses.
Vobiz gets `vobiz_serializer.VobizFrameSerializer` (in-band `stop`, no credential); Plivo
keeps Pipecat's `PlivoFrameSerializer` and the credentials its REST hangup needs.

**THE ACCOUNT IS THE GATE ON THE CALL, NOT ON THE CODE.** A Plivo account in the India data
region (BLOCKER-1) is what step 6 waits for; nothing here waits for it. Every Plivo-shaped
fact below is read out of the installed `pipecat-ai==1.10.0` tree and cited `file:line`,
every path is exercised against a fake transport with no socket and no account
(`tests/voice_worker_carrier_test.py`), and what remains when the account arrives is
credentials and a phone number.

WHAT IS VERIFIED, AND WHAT IS NOT
=================================
`www.plivo.com` and `api.plivo.com` are EGRESS-BLOCKED from this container (measured 13 Sep
2026, `docs/evidence/pre-build-blockers-2026-09-13.md` §10), so **no claim here is made from
Plivo's own documentation**. The evidence class for everything below is PIPECAT SOURCE —
the shipped client of that protocol, read in this session at
`/home/user/calevate-site/.venv/lib/python3.12/site-packages/pipecat/`:

* the media and DTMF envelopes, the `playAudio`/`clearAudio` replies and the 8 kHz μ-law
  encoding — `serializers/plivo.py:139-163`, `:224-254`;
* the handshake: a `start` message carrying `start.streamId` and `start.callId`, which is
  also how the runner DETECTS Plivo — `runner/utils.py:89-96`, `:257-262`;
* the stream URL's shape, a path segment — `runner/run.py:1410-1414`;
* the hangup, the ONE Plivo REST endpoint in the whole tree —
  `serializers/plivo.py:184`.

⚠ **WHAT IS UNKNOWN AND IS NOT INVENTED HERE** (each is listed in
`docs/PIPECAT-MIGRATION.md` §7):

1. **The dialed and calling numbers are not on the Plivo handshake as Pipecat parses it.**
   `parse_telephony_websocket` populates `from`/`to` for Twilio, Telnyx and Exotel and
   builds a two-key dict for Plivo that names neither (`runner/utils.py:230-272`) — so this
   module does NOT route a call by the number that was dialled. See `route_of` for what it
   routes on instead, which is a design that does not need the answer.

   ⚠ **AND THAT IS NOW A NAMED STATE RATHER THAN A `None`.** "We asked the carrier and it
   did not say" and "nobody has looked yet" were the same `None`, which is how
   `calls.from_e164` came to be NULL on every call with nothing anywhere saying why.
   `CallerIdentity` and `CALLER_IDENTITY_PARSE` below answer the question per CARRIER, with
   a state an operator and a compliance path can both read.

   ⚠ **AND THE STREAM IS NO LONGER THE ONLY LEG THAT CAN ANSWER IT (this change).** The
   carrier's request for the ANSWER DOCUMENT reaches a process we control, and
   `apps/voice-runtime/carrier_routes.py` now reads a calling party off it and mints it onto
   the stream URL as an explicit claim. `claim_from_stream_url` and `fold_caller_identity`
   below are this side of that seam. THE NUMBER IS STILL ABSENT ON PLIVO — this conjures
   none, and two things are missing: one cell of that module's `CARRIER_ANSWER_CONTRACT`
   (§5(d) of `docs/evidence/carrier-caller-identity.md` is the reading that fills it). The
   number then travels SEALED under a key derived from `CARRIER_CLAIM_SECRET`, and this
   side believes it only when it opens for this agent (`claim_from_stream_url`).
2. **Whether Plivo signs the HTTP request that fetches the answer document.** That leg
   is not here — see the next section — and nothing in the installed Pipecat tree
   verifies a Plivo request signature.
3. **No carrier REST call is made from this container** beyond Plivo's own hangup. The
   control plane dials, binds numbers and reads the carrier's CDR through
   `apps/api/engine/carrier.py` (D-662), so this module holds no dial and no CDR reader:
   the worker settles the carrier leg as `meter.CarrierFactsMissingError`, and the
   carrier's charge reaches the ledger later from `apps/workers/carrier_events.py`.

WHERE THE ANSWER DOCUMENT WENT (D-610)
======================================
`plivo_answer_document`, `ANSWER_DOCUMENT_CONTENT_TYPE` and `plivo_stream_url` used to
live in this module, beside the transport that consumes their result, and this docstring
already admitted the problem: *"WHO SERVES IT IS NOT THIS PROCESS … this container has no
HTTP server"*. They are now in `apps/voice-runtime/carrier_routes.py`, which is the
process that really serves them and which cannot import this module (it drags
`pipecat-ai`, ONNX turn detection and three vendor SDKs, and hard rule 3 forbids heavy
imports there BY NAME). MOVED rather than copied: two renderers of one wire format is the
"one way per problem" defect even while both agree. This module keeps the half that runs
inside the call — the handshake, the transport and `route_of`. Assembling the call is
`runtime.WorkerRuntime.run_call`'s, the one assembly path.

HARD RULE 5 IS NOT ENFORCED HERE, AND THAT IS DELIBERATE
========================================================
An agent with no AI-disclosure sentence must not be answerable. The refusal lives at
`config.load_session_config` — the ONE database read on this path — rather than in this
module, because a check in the carrier entrypoint is a check a second entrypoint can be
written around, and step 6 is the moment a second entrypoint becomes possible. This module
cannot reach `assemble_call` except through that read.

HARD RULE 6
===========
A phone number is PII and never reaches a log line here. What is logged is the call id, the
tenant and agent ids, the carrier's own stream id, and words. That includes a number that
arrived sealed on the stream URL's query rather than the handshake: `claim_from_stream_url`
normalises it onto `CallerIdentity.e164` and no logging path in this module reads that
field.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, cast
from urllib.parse import parse_qsl
from uuid import UUID

from calevate_shared.carrier import DEFAULT_CARRIER, WIRE_FAMILY, CarrierName, is_carrier
from calevate_shared.engine import parse_owned_runtime_agent_ref
from calevate_shared.events import CallDirection
from calevate_shared.extraction import normalize_phone
from calevate_shared.worker_api import (
    CALL_CLAIM_EXPIRES_PARAM,
    CALL_CLAIM_MAC_PARAM,
    CALL_DIRECTION_PARAM,
    CALL_ID_PARAM,
    CALLER_SEAL_PARAM,
    CallerIdentityState,
    UnverifiedCallClaim,
    open_caller_claim,
    verify_call_claim,
)
from loguru import logger
from pipecat.frames.frames import EndWorkerFrame
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from voice_worker.pipeline import (
    TELEPHONY_SAMPLE_RATE_HZ,
    AssembledCall,
)
from voice_worker.vobiz_serializer import MediaFormat, VobizFrameSerializer

#: The event a transport fires when the far end is really connected.
#:
#: `FastAPIWebsocketTransport` registers exactly three handlers and this is the one that
#: means "the carrier is on the line" (`pipecat/transports/websocket/fastapi.py:674-678`).
#: `AssembledCall.start_conversation` is documented as belonging to it, and this module is
#: the entrypoint that does the one-line registration.
CLIENT_CONNECTED_EVENT: Final = "on_client_connected"

#: The event the same transport fires when the far end closes the socket — the caller hanging
#: up (`fastapi.py:392-396`: fired only when WE were not the ones closing). It is an event and
#: nothing else: no frame reaches the pipeline, so without a handler the call runs on.
CLIENT_DISCONNECTED_EVENT: Final = "on_client_disconnected"


def wire_family_of(carrier: str) -> str:
    """What Pipecat's auto-detection calls a socket from `carrier` (`runner/utils.py:62-110`).

    A carrier we have no row for is expected to detect as its own name, which is how
    Pipecat names Twilio, Telnyx and Exotel; `build_transport` still refuses to serve it.
    """
    return WIRE_FAMILY[cast(CarrierName, carrier)] if is_carrier(carrier) else carrier


class UnroutableCallError(RuntimeError):
    """A carrier connection that names no agent of ours. The call is refused, not guessed.

    SEPARATE FROM `config.AgentNotRunnableError` because they are different failures with
    different owners: this one means the URL a carrier connected to does not name an agent
    at all (a provisioning fault — the number is pointed somewhere wrong, or at us by
    mistake), while that one means a named agent has nothing to run (a publish fault).
    Collapsing them would send an operator to the agent screen for a number that never
    reached one.

    Carries the token only when it is safe to: see `route_of`, which refuses to echo one.
    """


@dataclass(frozen=True, slots=True)
class CallRoute:
    """Which agent of which tenant a carrier connection is for."""

    tenant_id: UUID
    agent_id: UUID


@dataclass(frozen=True, slots=True)
class PlivoCredentials:
    """The carrier account's own two secrets. Never persisted, never hashed, never logged.

    Separate from `pipeline.VendorCredentials` (the three MODEL keys) because they are a
    different account, arrive from a different place and are needed for a different thing:
    these two are what `PlivoFrameSerializer` requires in order to hang up
    (`serializers/plivo.py:80-92`, which raises at construction when `auto_hang_up` is on
    and either is missing).
    """

    auth_id: str
    auth_token: str


class CarrierCredentialsMissingError(RuntimeError):
    """A Plivo call reached a worker that holds no Plivo credentials.

    The boot gate requires them only when `CARRIER=plivo`, so a Plivo-claimed socket on a
    worker configured for Vobiz lands here: refused before the call is answered, because
    `PlivoFrameSerializer` cannot hang the leg up without them and the carrier would go on
    billing a call nobody is on.
    """


#: WHY WE DO OR DO NOT KNOW WHO IS ON THE CALL. Four states, and the fourth is the defect.
#:
#: ⚠ **THIS WAS A SECOND DECLARATION OF THE SAME FOUR WORDS AND IS NOW AN IMPORT.** The
#: states travel on the wire — `calevate_shared.worker_api` carries them in the in-call
#: tool bodies, and `apps/api/worker/tools.py:150` answers an opt-out with
#: `caller_number_unknown:<state>` — so the shared contract package is the one home, and a
#: word spelled differently in the two deployables would be a tool refusal nobody could
#: read. Re-exported here because every caller in this deployable names it from this
#: module, and the authority on what the four words MEAN is the comment above the literal
#: in `worker_api.py`.


@dataclass(frozen=True, slots=True)
class CallerIdentity:
    """Who is on the far end of a carrier leg, or the named reason we cannot say.

    **THIS TYPE EXISTS BECAUSE A `None` MEANT FOUR THINGS.** `calls.from_e164` is NOT
    decoration — `leads.phone_e164` is NOT NULL and is derived from it, caller memory
    filters on `IS NOT NULL`, a DPDP erasure takes its subject from it, and an opt-out is
    keyed on it (`calevate_shared/worker_api.py:145-166`). A column that is NULL for four
    unrelated reasons cannot be triaged, which is how this went unnoticed.

    **IT NEVER INVENTS A NUMBER AND HAS NO FALLBACK.** There is no second source on this
    leg: our own session has no party, and substituting the agent's own line would file a
    lead against ourselves (`apps/api/worker/service.py:766-768` makes the same argument
    for the same reason). The honest act is a state, not a guess.

    HARD RULE 6: `e164` is PII. It is carried, never logged. `state` and `ground` are what
    goes in a log line, and both are safe by construction — `ground` is written HERE and is
    never built from wire data.
    """

    state: CallerIdentityState
    ground: str
    e164: str | None = None

    @property
    def is_known(self) -> bool:
        """True only when a number is really in hand. The one test callers should make.

        Non-empty, not merely present: `normalize_phone` keeps only digits, so a carrier's
        "anonymous" normalises to `""`, and a blank number keying an opt-out or a recalled
        memory is a suppression of nobody that the agent would report as done.
        """
        return self.state == "known" and bool(self.e164)

    @classmethod
    def not_read(cls) -> CallerIdentity:
        """The default: this code path has not asked the carrier anything."""
        return cls(
            state="not_read",
            ground="no carrier handshake has been read on this call",
        )


@dataclass(frozen=True, slots=True)
class CarrierIdentityParse:
    """Whether the PINNED client maps a carrier's calling party, and where that is written.

    **KEYED ON THE CARRIER, NOT ON PLIVO**, because the carrier is the part of this product
    most likely to change: Plivo signup failed, a Telnyx ticket is open, and D-05 picks
    Exotel (`docs/ROADMAP.md:348`). A seam that answered only for Plivo would be thrown
    away with Plivo, and — worse — the carrier that CAN answer would arrive with nothing
    ready to receive the answer.

    `evidence` is a `file:line` into the hash-pinned wheel and is the only kind of claim
    this table is allowed to hold (VERIFIED-VENDOR-DOCS, hard rule 11). It says what the
    CLIENT does, never what the CARRIER sends — those are different facts and only the
    first is readable from this container.
    """

    carrier: str
    #: Does `parse_telephony_websocket` map a `from` key for this carrier at all?
    maps_calling_party: bool
    evidence: str
    #: True when `evidence` is the CARRIER's own documentation showing the handshake has no
    #: calling party, rather than only our client's parse. Changes what the ground may say.
    documented_absent: bool = False


#: WHAT THE PINNED `pipecat-ai==1.10.0` CLIENT DOES WITH EACH CARRIER'S CALLING PARTY.
#:
#: Read out of the installed tree in this session, not recalled. `parse_telephony_websocket`
#: builds a per-carrier dict and only then validates it onto `CallData`, whose `from_number`
#: is `Field(alias="from")` (`runner/types.py:94`) — so a carrier whose branch writes no
#: `"from"` key leaves the field at its `None` default with nothing having been consulted.
#:
#: ⚠ **THE PLIVO ENTRY IS AN UNKNOWN, NOT A VENDOR FACT.** `False` here says only that the
#: CLIENT does not look; it does NOT say Plivo omits the number. Plivo's own `<Stream>`
#: documentation is the primary source for that and `www.plivo.com` is EGRESS-BLOCKED from
#: this container (measured 19 Sep 2026, `curl` → 000). Writing "Plivo does not send it"
#: anywhere is the exact failure hard rule 11 exists for.
CALLER_IDENTITY_PARSE: Final[Mapping[str, CarrierIdentityParse]] = {
    # A VENDOR FACT, unlike the Plivo row below: Vobiz documents the `start` event in full
    # and it carries `callId`, `streamId`, `accountId`, `tracks` and `mediaFormat` only. The
    # answer leg's signed claim is therefore the only source of the calling party.
    "vobiz": CarrierIdentityParse(
        carrier="vobiz",
        maps_calling_party=False,
        evidence=(
            "vobiz-findings/mirror/pages/xml/stream/stream-events.md:81-97 "
            "(start carries no from/to)"
        ),
        documented_absent=True,
    ),
    "plivo": CarrierIdentityParse(
        carrier="plivo",
        maps_calling_party=False,
        # Two keys and no third: `{"stream_id": start.streamId, "call_id": start.callId}`.
        evidence="pipecat/runner/utils.py:257-262",
    ),
    "telnyx": CarrierIdentityParse(
        carrier="telnyx",
        maps_calling_party=True,
        evidence="pipecat/runner/utils.py:253-254",
    ),
    "exotel": CarrierIdentityParse(
        carrier="exotel",
        maps_calling_party=True,
        evidence="pipecat/runner/utils.py:270-271",
    ),
    "twilio": CarrierIdentityParse(
        carrier="twilio",
        # NOT off the carrier's own start fields: Twilio's branch reads
        # `start.customParameters["from_number"]` — a parameter the ANSWER DOCUMENT put
        # there. That is the shape §STEP-4 of the evidence doc asks Plivo about, and the
        # reason it is the question worth asking: it needs nothing from the carrier's
        # schema, only the ability to attach our own parameters to the stream.
        maps_calling_party=True,
        evidence="pipecat/runner/utils.py:232,240-241",
    ),
}


def caller_identity_of(transport_type: str, call_data: Any) -> CallerIdentity:
    """The calling party of a parsed handshake, as a state that is always explainable.

    CARRIER-AGNOSTIC BY CONSTRUCTION: it reads `CallData.from_number`, the one field the
    client normalises across all four carriers (`runner/types.py:84,94`), and consults
    `CALLER_IDENTITY_PARSE` only to explain an absence. A new carrier needs a row in that
    table and nothing else here.

    **THE EMPTY STRING IS NOT THE SAME ABSENCE AS THE MISSING KEY**, and the distinction is
    the client's, not ours: the Telnyx and Exotel branches default their `"from"` to `""`
    (`runner/utils.py:253`, `:270`), so an empty value there means the carrier's own start
    event carried nothing — `withheld_by_carrier`. Plivo writes no key at all, so the field
    is untouched — `unparsed_by_client`, which is a statement about our client and not
    about Plivo.

    `normalize_phone` rather than a second canonicaliser: `leads.phone_e164`,
    `dnc_list.phone_e164` and the extraction path all key on its output, and a carrier
    number stored in a different form than the one the dispatch gate matches would be a
    suppression that suppresses nothing.
    """
    parse = CALLER_IDENTITY_PARSE.get(transport_type)
    raw = getattr(call_data, "from_number", None)
    number = normalize_phone(raw.strip()) if isinstance(raw, str) and raw.strip() else ""
    if number:
        return CallerIdentity(
            state="known",
            ground=f"{transport_type} handshake carried a calling party",
            e164=number,
        )
    if isinstance(raw, str) and raw.strip():
        # A value with no digit in it is a carrier's word for a withheld number.
        return CallerIdentity(
            state="withheld_by_carrier",
            ground=f"{transport_type} handshake carried a calling party with no number in it",
        )
    if parse is None:
        return CallerIdentity(
            state="unparsed_by_client",
            ground=(
                f"carrier {transport_type!r} is not in CALLER_IDENTITY_PARSE, so nothing "
                "here knows whether the pinned client reads its calling party"
            ),
        )
    if parse.maps_calling_party:
        return CallerIdentity(
            state="withheld_by_carrier",
            ground=(
                f"the pinned client reads {transport_type}'s calling party "
                f"({parse.evidence}) and the carrier sent none"
            ),
        )
    if parse.documented_absent:
        return CallerIdentity(
            state="unparsed_by_client",
            ground=(
                f"{transport_type}'s stream handshake carries no calling party "
                f"({parse.evidence}); only the answer leg's signed claim can supply one"
            ),
        )
    return CallerIdentity(
        state="unparsed_by_client",
        ground=(
            f"the pinned client maps no calling party for {transport_type} "
            f"({parse.evidence}); whether the carrier sends one is UNVERIFIED here because "
            "its documentation host is egress-blocked "
            "(docs/evidence/carrier-caller-identity.md)"
        ),
    )


# ======================================================================================
# THE CONTROL PLANE'S EXPLICIT CLAIM — the fifth source of truth (issue 3).
# ======================================================================================

#: The query parameters the voice-runtime's answer route mints onto the stream URL.
#:
#: DECLARED TWICE ACROSS TWO DEPLOYABLES, exactly like `TELEPHONY_SAMPLE_RATE_HZ`, because
#: neither module may import the other (hard rule 3 forbids the heavy import there, and
#: this container serves no HTTP). `tests/carrier_answer_identity_test.py` asserts the two
#: spellings equal, which is the only place that agreement can be checked. The sealed
#: number's parameter is `worker_api.CALLER_SEAL_PARAM`, which both deployables import.
CLAIM_CARRIER_PARAM: Final = "carrier"
CLAIM_CALLER_STATE_PARAM: Final = "caller_state"

#: Why a `known` caller claimed on the stream URL was not believed. See
#: `claim_from_stream_url`. Written here and never built from wire data (hard rule 6).
UNAUTHENTICATED_CLAIM_GROUND: Final = (
    "the stream URL claimed a known caller without a claim sealed for this agent and "
    "time, so its number may not key a suppression, a recalled memory, a call-back or a lead"
)

#: How informative each state is, when two sources disagree about an ABSENCE.
#:
#: `withheld_by_carrier` outranks `unparsed_by_client` because it is a statement about the
#: CARRIER (it was asked and it said nothing) where the other is a statement about US
#: (nobody could ask). `not_read` is last because it is the only word that means "unasked".
_STATE_INFORMATIVENESS: Final[Mapping[CallerIdentityState, int]] = {
    "known": 3,
    "withheld_by_carrier": 2,
    "unparsed_by_client": 1,
    "not_read": 0,
}


class CarrierClaimMismatchError(UnroutableCallError):
    """The control plane said one carrier and the socket speaks another. The call is refused.

    SEPARATE FROM ITS PARENT because the two mean different things to whoever is paged.
    `UnroutableCallError` from `route_of` is a provisioning fault — a number pointed
    somewhere wrong. This one means the answer URL we minted for carrier A was answered by
    a socket speaking carrier B, which is either a number bound to the wrong answer URL or
    somebody connecting to our stream endpoint while pretending to be a carrier. Refusing
    is the only safe direction: `build_transport` would otherwise hand the wrong
    serializer to the wrong protocol, which is a connected call with silence on it.
    """


@dataclass(frozen=True, slots=True)
class ControlPlaneClaim:
    """What OUR OWN control plane says about a call, read off the stream URL it minted.

    **THIS IS AN EXPLICIT CLAIM AND NOT A DETECTION, WHICH IS THE POINT.** The carrier a
    number is on is a fact of our configuration: the answer route is `/carrier/v1/<carrier>/
    answer/{ref}`, one carrier per path, minted by us. Sniffing for it — which is what
    `parse_telephony_websocket` does — is a fallback designed for a multi-tenant gateway
    that really does not know, and it breaks silently when a vendor renames a handshake
    key. That is precisely how the calling-party gap arose.

    **THE DETECTION IS NOT DELETED AND MUST NOT BE**, and `read_handshake` says what
    still depends on it: it is the ONLY source of `start.streamId` and `start.callId`,
    without which nothing can be hung up; it is what VALIDATES this claim rather than being
    replaced by it; and it is the only source of a calling party on the three carriers
    whose `from` the pinned client does read (`CALLER_IDENTITY_PARSE`).

    `present` is False for a socket that carried no claim at all — an older answer route, a
    test fixture, or a Pipecat Cloud front door that strips the query (the UNKNOWN recorded
    at `bot._route_token`). Absent is not the same as disagreeing, and neither is a refusal
    on its own.

    HARD RULE 6: `caller.e164` is PII, carried and never logged.
    """

    present: bool
    carrier: str | None = None
    caller: CallerIdentity | None = None


def claim_from_stream_url(
    url: str,
    *,
    ref: str | None = None,
    claim_secret: str | None = None,
    now: float | None = None,
) -> ControlPlaneClaim:
    """Read the control plane's claim off the stream URL a carrier connected to.

    Takes the whole URL (or a bare query string) rather than a parsed object, because the
    caller has a websocket and what a websocket exposes differs across servers — a string
    is the one shape every one of them can produce.

    **A MALFORMED CLAIM IS NO CLAIM, NEVER A GUESSED ONE.** Anything can connect to a
    WebSocket URL, so every value here is attacker-controlled: an unrecognised state word
    is dropped rather than coerced, a `caller` with no `caller_state` is ignored (the state
    is the verdict; the number is only meaningful under it), and a `caller_state` of
    `known` with no number is downgraded to `unparsed_by_client` — because
    `apps/api/worker/tools.py:150` lets an agent tell a caller their number was suppressed
    only on `known`, and a `known` with nothing behind it is exactly the sentence that must
    never be said.

    **A `known` NUMBER IS BELIEVED ONLY WHEN ITS SEALED CLAIM OPENS.** Nothing else
    authenticates this query, so an unsealed number is whatever the connecting party typed.
    Believed, it would key the in-call opt-out (a stranger's number suppressed), the
    caller-memory recall (another person's facts read out to whoever connected), a booked
    call-back (our platform dialling a number of the stranger's choosing) and
    `calls.from_e164`, from which the lead and the DPDP erasure subject are derived. So
    `known` stands only when `caller_seal` opens under `claim_secret` for `ref` (the agent
    this socket was routed to) inside its expiry (`worker_api.open_caller_claim`); on any
    failure — no key, no seal, another agent's claim, a forged or expired one, a payload
    with no number — it becomes `unparsed_by_client` with no number.
    """
    query = url.split("?", 1)[1] if "?" in url else url
    params = dict(parse_qsl(query, keep_blank_values=True))
    if not params:
        return ControlPlaneClaim(present=False)
    carrier = params.get(CLAIM_CARRIER_PARAM) or None
    raw_state = params.get(CLAIM_CALLER_STATE_PARAM) or None
    caller: CallerIdentity | None = None
    if raw_state in _STATE_INFORMATIVENESS:
        state = cast(CallerIdentityState, raw_state)
        if state == "known":
            opened = (
                open_caller_claim(
                    claim_secret, ref=ref, token=params.get(CALLER_SEAL_PARAM), now=now
                )
                if ref is not None
                else None
            )
            number = normalize_phone(opened) if opened is not None else ""
            if number:
                caller = CallerIdentity(
                    state="known",
                    ground="the control plane's answer leg reported known, in a sealed claim",
                    e164=number,
                )
            else:
                caller = CallerIdentity(
                    state="unparsed_by_client", ground=UNAUTHENTICATED_CLAIM_GROUND
                )
        else:
            caller = CallerIdentity(
                state=state, ground=f"the control plane's answer leg reported {state}"
            )
    if carrier is None and caller is None:
        return ControlPlaneClaim(present=False)
    return ControlPlaneClaim(present=True, carrier=carrier, caller=caller)


@dataclass(frozen=True, slots=True)
class ClaimedCall:
    """Our call id and direction, as the answer leg minted them for an outbound dial."""

    call_id: str
    direction: CallDirection


#: The query parameters that make up a call claim. Any one of them present means the
#: answer leg tried to say something, which is worth a log line when it does not verify.
_CALL_CLAIM_PARAMS: Final = (
    CALL_ID_PARAM,
    CALL_DIRECTION_PARAM,
    CALL_CLAIM_MAC_PARAM,
    CALL_CLAIM_EXPIRES_PARAM,
)


def call_claim_from_stream_url(
    url: str,
    *,
    ref: str,
    claim_key: bytes | None,
    now: float | None = None,
) -> ClaimedCall | UnverifiedCallClaim | None:
    """The call claim on the stream URL, believed only under a valid MAC for `ref`.

    An outbound dial reaches the worker through the same answer route as an inbound call,
    so neither its direction nor the id of the `calls` row `dispatch_call` already wrote can
    be read off the socket. The answer leg puts both on the URL under
    `worker_api.call_claim_mac`.

    Three answers. `ClaimedCall` when it verifies; `None` when the URL carries no claim at
    all (an inbound call); `UnverifiedCallClaim` when it carries one that does not verify
    (no key, another agent's MAC, an expired or far-future expiry, a direction outside
    `CallDirection`). The last runs as inbound with an id of its own, and the settlement
    reports it so the server can tell a forgery from a dialled call this worker could not
    verify because its secret differs from voice-runtime's.
    """
    query = url.split("?", 1)[1] if "?" in url else url
    params = dict(parse_qsl(query, keep_blank_values=True))
    if not any(name in params for name in _CALL_CLAIM_PARAMS):
        return None
    call_id = params.get(CALL_ID_PARAM) or None
    direction = params.get(CALL_DIRECTION_PARAM) or None
    if not verify_call_claim(
        claim_key,
        ref=ref,
        call_id=call_id,
        direction=direction,
        expires_at=params.get(CALL_CLAIM_EXPIRES_PARAM),
        mac=params.get(CALL_CLAIM_MAC_PARAM),
        now=time.time() if now is None else now,
    ):
        # No value from the query is logged: it is attacker-controlled.
        logger.warning("stream URL call claim did not verify; treating the call as inbound")
        return UnverifiedCallClaim(claimed_call_id=_uuid_or_none(call_id))
    return ClaimedCall(call_id=cast(str, call_id), direction=cast(CallDirection, direction))


def _uuid_or_none(value: str | None) -> UUID | None:
    """`value` as a uuid, or `None`: an unverified claim's id is a stranger's string."""
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


def fold_caller_identity(
    claimed: CallerIdentity | None, detected: CallerIdentity
) -> CallerIdentity:
    """One verdict from two sources, with the disagreement recorded rather than silently won.

    **WHY A FOLD RATHER THAN A PRECEDENCE RULE.** The claim and the detection are not rival
    answers to one question — they are answers from two DIFFERENT LEGS of the same call
    (the carrier's HTTP request, and the carrier's WebSocket handshake), and on today's
    carrier only one of them can ever speak. The rules, in order:

    1. **No claim** → the detection stands, unchanged. This is every call until a stream URL
       carries one.
    2. **Both name a number and they agree** (after `normalize_phone`, so a cosmetic
       difference is not a disagreement) → `known`, ground naming both legs.
    3. **Both name a number and they DIFFER** → `unparsed_by_client`, and the number is
       DROPPED. Two sources disagreeing about who is calling is not a tie to break: keying
       a DNC suppression on the loser would suppress a stranger, and `is_known` being False
       is what stops `apps/api/worker/tools.py` letting an agent say it did. The ground
       names both legs; the numbers are not logged (hard rule 6) and are recoverable from
       the carrier's CDR, which is the authority on the facts of a call (§1.2).
       ⚠ **`unparsed_by_client` IS THE CLOSEST OF FOUR CLOSED WORDS AND IS NOT THE RIGHT
       ONE.** The right word is a fifth — "two sources disagreed" — and
       `CallerIdentityState` lives in `calevate_shared/worker_api.py` and travels on the
       tool wire, outside this change's fence. Reported, not made. Until then the GROUND
       carries the distinction and `is_known` carries the safety.
    4. **Exactly one names a number** → that one wins, with both grounds. A claim names one
       only when its sealed claim opened (`claim_from_stream_url`); on Plivo and Vobiz the
       detection is structurally `unparsed_by_client`, so the claim is the only leg that can
       speak.
    5. **Neither names a number** → the more informative absence wins
       (`_STATE_INFORMATIVENESS`), ground naming both. A carrier's own "withheld" outranks
       our "we could not ask", which outranks "nobody asked".
    """
    if claimed is None:
        return detected
    if claimed.is_known and detected.is_known:
        if claimed.e164 == detected.e164:
            return CallerIdentity(
                state="known",
                ground="the control plane's answer leg and the carrier handshake agree",
                e164=detected.e164,
            )
        return CallerIdentity(
            state="unparsed_by_client",
            ground=(
                "the control plane's answer leg and the carrier handshake named DIFFERENT "
                "calling parties, so neither may key a suppression; the carrier's CDR is "
                "the authority (docs/evidence/carrier-caller-identity.md §1.2)"
            ),
        )
    if claimed.is_known or detected.is_known:
        winner = claimed if claimed.is_known else detected
        other = detected if claimed.is_known else claimed
        return CallerIdentity(
            state="known",
            ground=f"{winner.ground}; the other leg said: {other.ground}",
            e164=winner.e164,
        )
    ranked = sorted(
        (claimed, detected), key=lambda i: _STATE_INFORMATIVENESS[i.state], reverse=True
    )
    return CallerIdentity(
        state=ranked[0].state,
        ground=f"{ranked[0].ground}; the other leg said: {ranked[1].ground}",
    )


@dataclass(frozen=True, slots=True)
class CarrierHandshake:
    """What the carrier says at the top of a stream: which carrier, two ids and a verdict.

    `carrier` is the carrier this socket was CLAIMED (or configured) as and the detection
    agreed with, which is what `build_transport` chooses a serializer by.

    `carrier_call_id` is the CARRIER's id for the call (Vobiz `start.callId` = `CallUUID`,
    `stream-events.md:101`) and is NOT `SessionConfig.call_id`, which is ours (§1.2: the
    carrier's CDR is reconciled against our id rather than being its source). Both are kept:
    the carrier's is persisted as `calls.carrier_call_id`, the join key for its hangup
    webhook, its CDR and a transfer.

    `caller` is a state and a ground, never a guessed number, and is not routable because
    it is not a number; `route_of` routes on the URL.

    `media_format` is the `start` event's inbound format when the reader saw it, which only
    the Vobiz serializer checks.
    """

    stream_id: str
    carrier_call_id: str
    carrier: str = DEFAULT_CARRIER
    #: `not_read()` by default because a handshake built by hand really has asked no
    #: carrier anything; `from_call_data` always supplies a real verdict.
    caller: CallerIdentity = field(default_factory=lambda: CallerIdentity.not_read())
    media_format: MediaFormat | None = None

    @classmethod
    def from_call_data(
        cls, call_data: Any, *, carrier: str, media_format: MediaFormat | None = None
    ) -> CarrierHandshake:
        """Build one from `parse_telephony_websocket`'s `CallData`, or refuse.

        `CallData` declares both ids `str | None` (`runner/types.py:94-95`) because it spans
        four carriers; the narrowing to two required strings happens here, once.
        """
        stream_id = getattr(call_data, "stream_id", None)
        carrier_call_id = getattr(call_data, "call_id", None)
        if not stream_id or not carrier_call_id:
            raise UnroutableCallError(
                "the carrier handshake carried no stream id or no call id, so this "
                "connection cannot be answered or hung up"
            )
        return cls(
            stream_id=str(stream_id),
            carrier_call_id=str(carrier_call_id),
            carrier=carrier,
            caller=caller_identity_of(carrier, call_data),
            media_format=media_format,
        )


class _HandshakeTap:
    """The socket as `parse_telephony_websocket` sees it, keeping the frames it reads.

    The parser discards `start.mediaFormat`, which the Vobiz serializer must check, and the
    frames it reads are gone from the socket once read. Recording them on the way past
    keeps Pipecat as the one detector and parser while still letting us read the format.
    Every other attribute is the real socket's.
    """

    def __init__(self, websocket: Any) -> None:
        self._websocket = websocket
        self.frames: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._websocket, name)

    def iter_text(self) -> AsyncIterator[str]:
        async def _tapped() -> AsyncIterator[str]:
            async for frame in self._websocket.iter_text():
                self.frames.append(frame)
                yield frame

        return _tapped()

    def media_format(self) -> MediaFormat | None:
        """`start.mediaFormat` from the first `start` frame read, or `None`."""
        for frame in self.frames:
            try:
                message = json.loads(frame)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(message, dict) and message.get("event") == "start":
                start = message.get("start")
                return MediaFormat.from_start(start) if isinstance(start, Mapping) else None
        return None


async def read_handshake(
    websocket: Any,
    *,
    claim: ControlPlaneClaim | None = None,
    default_carrier: str = DEFAULT_CARRIER,
) -> CarrierHandshake:
    """The first two messages off a carrier socket, as OUR handshake — or a refusal.

    **THE CARRIER IS CLAIMED AND THEN CHECKED, NEVER SNIFFED FOR.** `claim.carrier` is what
    our control plane minted the stream URL for; without one, `default_carrier` (the
    worker's `CARRIER` setting) is expected. Pipecat's detection must then name that
    carrier's wire family (`wire_family_of`) or the call is refused: a mismatch against a
    claim is `CarrierClaimMismatchError`, against the configured default a plain
    `UnroutableCallError`. Serialising one protocol as another is a connected call with
    silence on it.

    **THE DETECTION STAYS AND MUST.** It is the only source of `start.streamId` and
    `start.callId` — without them no stream can be stopped and no Plivo leg hung up — and
    of a calling party on the carriers whose `from` the pinned client reads. Pipecat's
    parser is used rather than our own read of the socket because the detection rule and
    the field names are the vendor-shaped part and belong to the library that ships them.
    The transport reads the rest of the stream after it.
    """
    expected = (claim.carrier if claim is not None else None) or default_carrier
    family = wire_family_of(expected)
    tap = _HandshakeTap(websocket)
    transport_type, call_data = await parse_telephony_websocket(cast(Any, tap))
    if transport_type != family:
        if claim is not None and claim.carrier is not None:
            raise CarrierClaimMismatchError(
                f"the control plane minted this stream URL for carrier {expected!r} "
                f"(wire family {family!r}) and the socket speaks {transport_type!r}: "
                "refusing rather than serialising one protocol as the other"
            )
        raise UnroutableCallError(
            f"this socket speaks {transport_type!r}, and this worker's carrier is "
            f"{expected!r} (wire family {family!r})"
        )
    handshake = CarrierHandshake.from_call_data(
        call_data, carrier=expected, media_format=tap.media_format()
    )
    claimed = claim.caller if claim is not None else None
    return replace(handshake, caller=fold_caller_identity(claimed, handshake.caller))


def route_of(token: str) -> CallRoute:
    """The `(tenant, agent)` a carrier connection names, or a refusal.

    **THE ROUTE IS IN THE URL THE CARRIER CONNECTS TO, NOT IN THE CALL.** Neither carrier's
    stream handshake names the dialled number (`CALLER_IDENTITY_PARSE`), so routing on it
    would mean either reading a field that is not there or a cross-tenant read of
    `phone_numbers` — a FORCE-RLS'd tenant table with no exemption, which resolving a number
    before knowing its tenant would require us to add. Neither is necessary: the ref an
    `owned_runtime` engine mints for an agent already carries both ids
    (`calevate_shared.engine.owned_runtime_agent_ref`), it is minted by our own control
    plane on publish, and putting it in the stream URL is the shape Pipecat's own runner
    recommends for telephony ("URL path segment: `/ws/<token>`", `runner/run.py:1414`).
    The voice-runtime's answer route is what puts it there, and the number → agent decision
    is then made where a tenant session exists — on the screen that binds the number.

    **THE TOKEN IS NEVER ECHOED INTO THE REFUSAL.** It is attacker-controlled (anything can
    connect to a WebSocket URL), and a message that quoted it would put an arbitrary string
    into an operator's log line. The refusal says what was wrong with it, not what it was.
    """
    parsed = parse_owned_runtime_agent_ref(token)
    if parsed is None:
        raise UnroutableCallError(
            "the carrier connected to a stream URL that does not name an agent of this "
            "platform (expected an owned-runtime agent ref of three colon-separated parts)"
        )
    tenant_id, agent_id = parsed
    return CallRoute(tenant_id=tenant_id, agent_id=agent_id)


def _serializer_for(
    handshake: CarrierHandshake, plivo_credentials: PlivoCredentials | None
) -> FrameSerializer:
    """The serializer for the handshake's carrier, or a refusal naming why.

    **VOBIZ needs no credential.** The call is ended with an in-band `stop`
    (`vobiz_serializer`), and a start that reports anything but 8 kHz μ-law is refused
    here, before a byte of audio is decoded. A start the reader never saw a format on is
    refused too: the vendor documents `mediaFormat` on every `start`
    (`stream-events.md:58`).

    **PLIVO keeps `auto_hang_up` on.** Its default is True (`serializers/plivo.py:56`) and
    the hangup swallows every error and never retries (`:204-205`). Turning it off would
    leave a completed call up and billing; leaving it on makes a failed hangup invisible to
    us, which is the recoverable failure — the CDR reconciliation (§1.2) surfaces it.
    """
    if handshake.carrier == "vobiz":
        if handshake.media_format is None:
            raise UnroutableCallError(
                "the Vobiz stream's start event carried no mediaFormat, so its audio "
                "encoding is unknown and cannot be decoded"
            )
        return VobizFrameSerializer(handshake.stream_id, media_format=handshake.media_format)
    if handshake.carrier == "plivo":
        if plivo_credentials is None:
            raise CarrierCredentialsMissingError(
                "a Plivo call reached a worker with no PLIVO_AUTH_ID/PLIVO_AUTH_TOKEN, so it "
                "could not be hung up; set CARRIER=plivo and both variables in the Pipecat "
                "Cloud secret set, or route the number to Vobiz"
            )
        return PlivoFrameSerializer(
            stream_id=handshake.stream_id,
            call_id=handshake.carrier_call_id,
            auth_id=plivo_credentials.auth_id,
            auth_token=plivo_credentials.auth_token,
        )
    raise UnroutableCallError(
        f"this worker has no serializer for carrier {handshake.carrier!r}; it serves "
        "vobiz and plivo"
    )


def build_transport(
    websocket: Any,
    *,
    handshake: CarrierHandshake,
    plivo_credentials: PlivoCredentials | None = None,
) -> FastAPIWebsocketTransport:
    """The carrier transport for one call, with the serializer its carrier speaks.

    `websocket` is `Any` rather than `fastapi.WebSocket` because this module is imported by
    a process that may never serve HTTP, and `pipecat.transports.websocket.fastapi` already
    raises a named ImportError when FastAPI is absent.

    **THE THREE DEFAULTS CHANGED HERE.**

    * `add_wav_header=False` — Pipecat's own telephony helper sets it explicitly
      (`runner/utils.py:505-506`); a WAV header inside a μ-law frame is noise on the line.
    * `audio_in_sample_rate` / `audio_out_sample_rate` at 8 kHz — the rate both serializers
      convert to and from. Left unset, every turn would be resampled twice for nothing.
    * `serializer` — without it the transport sends raw PCM and the carrier hears silence.
    """
    params = FastAPIWebsocketParams(
        add_wav_header=False,
        audio_in_sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        audio_out_sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        serializer=_serializer_for(handshake, plivo_credentials),
    )
    return FastAPIWebsocketTransport(websocket=websocket, params=params)


@dataclass(frozen=True, slots=True)
class CarrierLeg:
    """A read handshake and the transport built for it: what `runtime.run_call` needs."""

    handshake: CarrierHandshake
    transport: FastAPIWebsocketTransport


async def open_carrier_leg(
    websocket: Any,
    *,
    claim: ControlPlaneClaim | None,
    default_carrier: str,
    plivo_credentials: PlivoCredentials | None = None,
) -> CarrierLeg:
    """Read the handshake and build the transport for it. The entrypoint's carrier half.

    Kept apart from call assembly, which has one home (`runtime.WorkerRuntime.run_call`).
    """
    handshake = await read_handshake(websocket, claim=claim, default_carrier=default_carrier)
    transport = build_transport(websocket, handshake=handshake, plivo_credentials=plivo_credentials)
    logger.info(
        "carrier leg opened",
        carrier=handshake.carrier,
        caller_identity=handshake.caller.state,
    )
    return CarrierLeg(handshake=handshake, transport=transport)


class CarrierWiringError(RuntimeError):
    """A transport that cannot tell us when the caller is connected.

    RAISED RATHER THAN LOGGED, because the symptom of ignoring it is the worst-shaped
    failure this path has: `BaseObject.add_event_handler` only WARNS when an event was
    never registered (`pipecat/utils/base_object.py:203-206`), so an agent whose greeting
    was armed on a transport that does not fire the event answers the phone and says
    nothing at all, on every call, with a green deploy.
    """


def arm_first_turn(transport: BaseTransport, call: AssembledCall, *, call_id: str) -> None:
    """Wire the call to the carrier's two edges — or refuse to pretend they are wired.

    **CONNECT: the agent speaks first.** `AssembledCall.start_conversation` holds the decision
    (and returns whether it spoke); this registers it on the transport's own connect event,
    which is the shipped pattern (`examples/voice/voice-cartesia.py:112-119`) and the reason
    `assemble_call` does not do it: a fake transport has no such event, and `assemble_call`
    must stay runnable against one.

    **DISCONNECT: the call ends.** A caller hanging up reaches the pipeline as nothing at
    all, and `assemble_call` sets `idle_timeout_secs=None`, so an unhandled hang-up left the
    pipeline — and this container's one session slot — running until the duration cap, with
    the call's terminal status that many minutes late. The vendor's template answers it with
    `runner.cancel()` (`cli/templates/server/_macros/event_handlers.jinja2:25-28`); this
    pushes `EndWorkerFrame` instead, as `pipeline.CallDurationCap` does, because a cancel
    ends the call as `failed` (`NormalizedEventBoundary`) and a caller hanging up is the
    ordinary end of a call, not a failure.

    Both registrations are VERIFIED rather than attempted — see `CarrierWiringError`. The
    membership test reads a private attribute because 1.10.0 exposes no public accessor for
    the registered set (`base_object.py:76`, `:195-206`); a `getattr` with a default keeps
    that read from becoming a crash if the attribute is ever renamed, and the refusal then
    says the honest thing.
    """
    registered = getattr(transport, "_event_handlers", {})
    if CLIENT_CONNECTED_EVENT not in registered:
        raise CarrierWiringError(
            f"this transport does not fire {CLIENT_CONNECTED_EVENT!r}, so the agent would "
            "never speak first and the caller would hear silence"
        )
    if CLIENT_DISCONNECTED_EVENT not in registered:
        raise CarrierWiringError(
            f"this transport does not fire {CLIENT_DISCONNECTED_EVENT!r}, so a caller "
            "hanging up would leave the call running until its duration cap"
        )

    async def _greet(*_args: Any) -> None:
        # Two states an operator needs apart, and neither is an error: an agent that
        # opened the call, and one configured not to. Ids and words (hard rule 6).
        spoke = await call.start_conversation()
        logger.info("carrier call connected", call_id=call_id, spoke_first=spoke)

    async def _hang_up(*_args: Any) -> None:
        logger.info("carrier call disconnected by the far end", call_id=call_id)
        await call.worker.queue_frames([EndWorkerFrame(reason="caller hung up")])

    transport.add_event_handler(CLIENT_CONNECTED_EVENT, _greet)
    transport.add_event_handler(CLIENT_DISCONNECTED_EVENT, _hang_up)


__all__ = [
    "CALLER_IDENTITY_PARSE",
    "CLAIM_CALLER_STATE_PARAM",
    "CLAIM_CARRIER_PARAM",
    "CLIENT_CONNECTED_EVENT",
    "CLIENT_DISCONNECTED_EVENT",
    "UNAUTHENTICATED_CLAIM_GROUND",
    "CallRoute",
    "CallerIdentity",
    "CallerIdentityState",
    "CarrierClaimMismatchError",
    "CarrierCredentialsMissingError",
    "CarrierHandshake",
    "CarrierIdentityParse",
    "CarrierLeg",
    "CarrierWiringError",
    "ClaimedCall",
    "ControlPlaneClaim",
    "PlivoCredentials",
    "UnroutableCallError",
    "arm_first_turn",
    "build_transport",
    "call_claim_from_stream_url",
    "caller_identity_of",
    "claim_from_stream_url",
    "fold_caller_identity",
    "open_carrier_leg",
    "read_handshake",
    "route_of",
    "wire_family_of",
]
