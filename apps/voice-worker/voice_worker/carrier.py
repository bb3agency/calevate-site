"""The carrier leg: a Plivo call becomes a running pipeline (`docs/PIPECAT-MIGRATION.md`
§6 step 6).

**WHAT THIS MODULE IS FOR, IN ONE SENTENCE.** It turns an inbound carrier connection into
the three arguments `session.start_session` already takes — the platform API client, the
two ids of the agent being called, and a Pipecat transport — and it is the only place in
this repository that knows the carrier is Plivo.

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
   none: what is missing is one cell of that module's `CARRIER_ANSWER_CONTRACT`, and §5(d)
   of `docs/evidence/carrier-caller-identity.md` is the reading that fills it.
2. **Whether Plivo signs the HTTP request that fetches the answer document.** That leg
   is not here — see the next section — and nothing in the installed Pipecat tree
   verifies a Plivo request signature.
3. **Every carrier REST call except the hangup** — placing a call, listing a CDR, binding a
   number. `apps/api/engine/pipecat.py` refuses each by name for this reason and this
   module adds no second guess; see `OUTBOUND_DIAL_UNKNOWN` and `CDR_LISTING_UNKNOWN`
   below. The CDR is the costly one: it is the authority for the billable minute (§1.2),
   so while it cannot be read every call settles a carrier refusal and bills the client no
   minutes at all (`meter.CarrierFactsMissingError`).

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
inside the call — the handshake, the transport, `route_of` and `start_carrier_call`.

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
tenant and agent ids, the carrier's own stream id, and words. That now includes a number
that arrived on the stream URL's query rather than the handshake: `claim_from_stream_url`
normalises it onto `CallerIdentity.e164` and no logging path in this module reads that
field. `apps/voice-runtime/carrier_routes.plivo_stream_url` argues what putting it in a URL
at all costs, and what would remove it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, cast
from urllib.parse import parse_qsl
from uuid import UUID

from calevate_shared.engine import parse_owned_runtime_agent_ref
from calevate_shared.events import CallDirection
from calevate_shared.extraction import normalize_phone
from calevate_shared.worker_api import CallerIdentityState
from loguru import logger
from pipecat.frames.frames import EndWorkerFrame
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from voice_worker.api_client import WorkerApiClient
from voice_worker.knowledge import PackCache, PackFetcher, QueryEmbedder
from voice_worker.meter import CarrierCdr
from voice_worker.pipeline import (
    TELEPHONY_SAMPLE_RATE_HZ,
    AssembledCall,
    NormalizedEventSink,
    VendorCredentials,
)
from voice_worker.session import start_session

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

#: What Pipecat's telephony auto-detection calls our carrier (`runner/utils.py:89-96`), and
#: the value `create_transport` switches on (`:532`). ONE deployment, ONE carrier: anything
#: else on this socket is refused rather than served with the wrong serializer.
PLIVO_TRANSPORT_TYPE: Final = "plivo"

#: Why no outbound dial exists in this module, in the words an operator gets.
#:
#: Pipecat's whole tree contains ONE Plivo REST endpoint — the hangup DELETE at
#: `serializers/plivo.py:184` — and nothing that places a call. The dial is an HTTP request
#: to a surface nobody here has read, so it is REFUSED rather than guessed: the transport,
#: the serializer and everything in this module are direction-agnostic and will carry an
#: outbound call the moment that request can be written, which is why `start_carrier_call`
#: takes a `direction` instead of being named `answer`.
#: Why no CDR can be read here, in the words an operator gets.
#:
#: The carrier's record is the authority for the billable minute (PIPECAT-MIGRATION.md
#: §1.2) and for the client's billed minutes with it; the request that retrieves one has
#: not been read. See `fetch_call_detail_record` for the five facts it needs.
CDR_LISTING_UNKNOWN: Final = (
    "Reading a call detail record from this carrier is not built: the only Plivo REST "
    "endpoint in the installed Pipecat tree is the hangup (serializers/plivo.py:184), the "
    "vendor's API host is egress-blocked from the build environment, and the request that "
    "retrieves a CDR has not been read. Until it is, every call settles "
    "meter_carrier_cdr_missing and bills the client no minutes. See "
    "docs/evidence/pre-build-blockers-2026-09-13.md §10 and ROADMAP D-623."
)

OUTBOUND_DIAL_UNKNOWN: Final = (
    "Placing a call on this carrier is not built: the only Plivo REST endpoint in the "
    "installed Pipecat tree is the hangup (serializers/plivo.py:184), the vendor's API "
    "host is egress-blocked from the build environment, and the request that places a "
    "call has not been read. See docs/evidence/pre-build-blockers-2026-09-13.md §10."
)


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
        """True only when a number is really in hand. The one test callers should make."""
        return self.state == "known" and self.e164 is not None

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
    if isinstance(raw, str) and raw.strip():
        return CallerIdentity(
            state="known",
            ground=f"{transport_type} handshake carried a calling party",
            e164=normalize_phone(raw.strip()),
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

#: The query parameters `apps/voice-runtime/carrier_routes.plivo_stream_url` mints.
#:
#: DECLARED TWICE ACROSS TWO DEPLOYABLES, exactly like `TELEPHONY_SAMPLE_RATE_HZ`, because
#: neither module may import the other (hard rule 3 forbids the heavy import there, and
#: this container serves no HTTP). `tests/carrier_answer_identity_test.py` asserts the two
#: spellings equal, which is the only place that agreement can be checked.
CLAIM_CARRIER_PARAM: Final = "carrier"
CLAIM_CALLER_PARAM: Final = "caller"
CLAIM_CALLER_STATE_PARAM: Final = "caller_state"

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
    is the only safe direction: `build_plivo_transport` would otherwise hand the wrong
    serializer to the wrong protocol, which is a connected call with silence on it.
    """


@dataclass(frozen=True, slots=True)
class ControlPlaneClaim:
    """What OUR OWN control plane says about a call, read off the stream URL it minted.

    **THIS IS AN EXPLICIT CLAIM AND NOT A DETECTION, WHICH IS THE POINT.** The carrier a
    number is on is a fact of our configuration: the answer route is `/carrier/v1/plivo/
    answer/{ref}`, one carrier per path, minted by us. Sniffing for it — which is what
    `parse_telephony_websocket` does — is a fallback designed for a multi-tenant gateway
    that really does not know, and it breaks silently when a vendor renames a handshake
    key. That is precisely how the calling-party gap arose.

    **THE DETECTION IS NOT DELETED AND MUST NOT BE**, and `read_plivo_handshake` says what
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


def claim_from_stream_url(url: str) -> ControlPlaneClaim:
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
        raw_number = (params.get(CLAIM_CALLER_PARAM) or "").strip()
        if state == "known" and not raw_number:
            caller = CallerIdentity(
                state="unparsed_by_client",
                ground=(
                    "the control plane claimed a known caller and carried no number, so "
                    "the claim is not usable (a state nothing backs may not authorise a "
                    "suppression)"
                ),
            )
        else:
            caller = CallerIdentity(
                state=state,
                ground=f"the control plane's answer leg reported {state}",
                e164=normalize_phone(raw_number) if raw_number and state == "known" else None,
            )
    if carrier is None and caller is None:
        return ControlPlaneClaim(present=False)
    return ControlPlaneClaim(present=True, carrier=carrier, caller=caller)


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
    4. **Exactly one names a number** → that one wins, with both grounds. This is the case
       that closes the gap: on Plivo the detection is structurally `unparsed_by_client`
       (`CALLER_IDENTITY_PARSE`) and the claim is the only leg that can say anything.
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
class PlivoHandshake:
    """What the carrier says at the top of a stream, as Pipecat parses it.

    TWO IDENTIFIERS AND A VERDICT. `parse_telephony_websocket` maps `start.streamId` and
    `start.callId` for this provider and nothing else (`runner/utils.py:257-262`).

    ⚠ **THIS DOCSTRING USED TO ARGUE THAT A THIRD FIELD WOULD BE WRONG** — "a
    `from_number`/`to_number` pair … would be two fields that are always `None` on the one
    carrier we run — an invitation to route on them". The routing half of that is still
    true and `route_of` still routes on the URL. The rest was the defect: the absence
    itself is a FACT the rest of the system needs, and modelling it as nothing at all is
    what left `calls.from_e164` NULL with no reader able to say why. `caller` is that fact
    — a state and a ground, never a guessed number — and it is not routable because it is
    not a number.

    `call_id` here is the CARRIER's id for the call and is NOT `SessionConfig.call_id`,
    which is ours (§1.2: the carrier's CDR is reconciled against our id rather than being
    its source). Both are kept: the hangup is addressed with theirs.
    """

    stream_id: str
    carrier_call_id: str
    #: DEFAULTS TO `not_read()` RATHER THAN BEING REQUIRED, and the default is the honest
    #: one: a handshake built by hand (a test fixture, a future second entrypoint) really
    #: has asked no carrier anything, and saying so is the state this type exists to make
    #: sayable. `from_call_data` always supplies a real verdict.
    caller: CallerIdentity = field(default_factory=lambda: CallerIdentity.not_read())

    @classmethod
    def from_call_data(
        cls, call_data: Any, *, transport_type: str = PLIVO_TRANSPORT_TYPE
    ) -> PlivoHandshake:
        """Build one from `parse_telephony_websocket`'s `CallData`.

        Takes the parsed object rather than the raw websocket so that the caller owns the
        single-use message stream, and takes it as `Any` because `CallData` declares both
        fields as `str | None` (`runner/types.py:94-95`) — a shape that is right for a
        model spanning four carriers and wrong for the one contract this worker has. The
        narrowing to two required strings happens here, once, with a refusal attached.

        `transport_type` is a keyword with a default rather than a positional, because the
        two ids are Plivo-shaped and the identity question is not: the default keeps every
        existing caller correct while `caller_identity_of` stays answerable for the carrier
        we migrate to.
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
            caller=caller_identity_of(transport_type, call_data),
        )


async def read_plivo_handshake(
    websocket: Any, *, claim: ControlPlaneClaim | None = None
) -> PlivoHandshake:
    """The first two messages off a carrier socket, as OUR handshake — or a refusal.

    **THE CARRIER IS NOW CLAIMED AND THEN CHECKED, RATHER THAN SNIFFED FOR (issue 3).**
    `claim.carrier` is what our own control plane minted the answer URL for; the detection
    still runs, and the two must agree or the call is refused
    (`CarrierClaimMismatchError`). With no claim, the expected carrier falls back to this
    deployment's constant, which is what every caller did before.

    **WHAT STILL DEPENDS ON THE DETECTION, so that nobody deletes it as redundant.** It is
    the ONLY source of `start.streamId` and `start.callId` — without them
    `PlivoFrameSerializer` cannot hang the leg up (`serializers/plivo.py:80-92`). It is the
    only source of a calling party on the three carriers whose `from` the pinned client
    reads (`CALLER_IDENTITY_PARSE`). And it is what VALIDATES the claim: a claim nothing
    checks is a claim an attacker writes.

    **IT REFUSES A CARRIER THAT IS NOT OURS RATHER THAN GUESSING WHAT IT MEANT.**
    `parse_telephony_websocket` auto-detects across four providers and will happily hand
    back `twilio`, `telnyx`, `exotel` or `unknown` (`runner/utils.py:62-110`), and each of
    those carries different field names on a `CallData` whose every field is optional. A
    mount that passed any of them to `build_plivo_transport` would build a serializer for
    the wrong protocol — a connected call with silence on it. One deployment, one carrier,
    and the check is here so the next entrypoint inherits it.

    Using Pipecat's own parser rather than reading the socket ourselves is the point: the
    detection rule and the field names are the vendor-shaped part, and they belong to the
    library that ships them. The parse is cached on the websocket, so a caller may call
    this and then let the transport read the rest of the stream (`runner/utils.py:172-183`).
    """
    expected = (claim.carrier if claim is not None else None) or PLIVO_TRANSPORT_TYPE
    transport_type, call_data = await parse_telephony_websocket(websocket)
    if transport_type != expected:
        if claim is not None and claim.carrier is not None:
            raise CarrierClaimMismatchError(
                f"the control plane minted this stream URL for carrier {expected!r} and "
                f"the socket speaks {transport_type!r}: refusing rather than serialising "
                "one protocol as the other"
            )
        raise UnroutableCallError(
            f"this socket speaks {transport_type!r}, and this deployment's carrier is {expected!r}"
        )
    handshake = PlivoHandshake.from_call_data(call_data, transport_type=transport_type)
    claimed = claim.caller if claim is not None else None
    return replace(handshake, caller=fold_caller_identity(claimed, handshake.caller))


def route_of(token: str) -> CallRoute:
    """The `(tenant, agent)` a carrier connection names, or a refusal.

    **THE ROUTE IS IN THE URL THE CARRIER CONNECTS TO, NOT IN THE CALL.** The dialed number
    is absent from the Plivo handshake as Pipecat parses it (module docstring, UNKNOWN 1),
    so routing on it would mean either reading a field nobody has verified exists or a
    cross-tenant read of `phone_numbers` — a FORCE-RLS'd tenant table with no exemption,
    which resolving a number before knowing its tenant would require us to add. Neither is
    necessary: the ref an `owned_runtime` engine mints for an agent already carries both
    ids (`calevate_shared.engine.owned_runtime_agent_ref`), it is minted by our own control
    plane on publish, and putting it in the stream URL is the shape Pipecat's own runner
    recommends for telephony ("URL path segment: `/ws/<token>`", `runner/run.py:1414`).
    `carrier_routes.plivo_stream_url` in the voice-runtime is what puts it there, and the
    number → agent decision is then made where a tenant session exists — on the screen
    that binds the number — rather than on the call.

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


def build_plivo_transport(
    websocket: Any,
    *,
    handshake: PlivoHandshake,
    credentials: PlivoCredentials,
) -> FastAPIWebsocketTransport:
    """The carrier transport for one call.

    `websocket` is `Any` rather than `fastapi.WebSocket` because this module is imported by
    a process that may never serve HTTP, and `pipecat.transports.websocket.fastapi` already
    raises a named ImportError when FastAPI is absent. The type that matters is checked by
    the transport itself.

    **THE THREE DEFAULTS CHANGED HERE, EACH AGAINST THE LINE THAT GAVE US THE DEFAULT.**

    * `add_wav_header=False` — the parameter's default is already False
      (`fastapi.py:83`) and Pipecat's own telephony helper sets it explicitly anyway
      (`runner/utils.py:505-506`, "Always set add_wav_header to False for telephony"). A
      WAV header inside a μ-law telephony frame is noise on the line.
    * `audio_in_sample_rate` / `audio_out_sample_rate` at 8 kHz — the rate the serializer
      converts to and from (`serializers/plivo.py:54`, `:145-147`). Left unset, the
      pipeline's own rate would be resampled twice per turn for nothing.
    * `serializer` — without it the transport sends raw PCM and Plivo hears silence.

    **`auto_hang_up` IS LEFT ON, AND ITS FAILURE MODE IS STATED RATHER THAN FIXED HERE.**
    The default is True (`serializers/plivo.py:56`) and the hangup swallows every error and
    never retries (`:204-205`) — §4 of the migration doc names that as a capability
    declaration, not a footnote. Turning it OFF would mean a completed pipeline leaves the
    carrier's call up and billing; leaving it on means a failed hangup is invisible to us.
    The second is the recoverable one, and what makes it visible is the CDR reconciliation
    (§1.2, step 7) rather than a retry loop in a container that is about to exit.
    """
    params = FastAPIWebsocketParams(
        add_wav_header=False,
        audio_in_sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        audio_out_sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        serializer=PlivoFrameSerializer(
            stream_id=handshake.stream_id,
            call_id=handshake.carrier_call_id,
            auth_id=credentials.auth_id,
            auth_token=credentials.auth_token,
        ),
    )
    return FastAPIWebsocketTransport(websocket=websocket, params=params)


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


async def start_carrier_call(
    api: WorkerApiClient,
    *,
    token: str,
    call_id: str,
    direction: CallDirection,
    transport: BaseTransport,
    credentials: VendorCredentials,
    caller: CallerIdentity | None = None,
    sink: NormalizedEventSink,
    fetcher: PackFetcher,
    cache: PackCache | None = None,
    embedder: QueryEmbedder | None = None,
) -> AssembledCall:
    """A carrier connection in, a runnable call out. The whole inbound path, in order.

    1. **Route.** The token off the stream URL becomes a tenant and an agent, or the call is
       refused (`route_of`). Nothing is read from the database before this: a connection
       cannot be opened until a tenant is named.
    2. **Scope.** The token IS the agent ref, so it is what `start_session` presents to the
       platform API — and the server resolves the tenant from it and reads under that
       tenant's RLS (D-621). Hard rule 1 is still in the signature, one indirection out: a
       carrier call cannot reach a row without naming the ref it was routed by, and the ref
       names the tenant.
    3. **Load and assemble.** `session.start_session` is the existing seam and is called
       unchanged in everything but its first argument: the agent's published config version,
       its knowledge pack, then `assemble_call`. The hard rule 5 refusal lives inside its
       first step.
    4. **Arm the first turn**, so the agent volunteers its disclosure toggles (D-163) rather
       than waiting for a caller who has just heard a click.

    `direction` is an argument rather than the constant `"inbound"` because everything above
    is direction-agnostic and only the DIAL is missing (`OUTBOUND_DIAL_UNKNOWN`). When that
    request can be written, an outbound call reaches this same function with the same
    transport.

    **THE ORDER IS A DECISION.** Arming the greeting comes last, after the pipeline exists:
    armed first, a carrier that connected during the pack fetch would find a handler closing
    over a call that has not been assembled.

    **`caller` IS NOW CARRIED INTO THE SESSION, AND THAT IS THE HOP THE FOUR IN-CALL TOOLS
    WERE WAITING ON.** `assemble_call` takes `caller=None` by default and does NOT advertise
    opt-out, book / cancel call-back or handoff to the model when it is absent — four tools
    that could only fail waste a conversational turn — so until this argument was forwarded,
    a caller on an owned_runtime call could not opt out at all. `apps/api/worker/tools.py:150`
    then refuses to write, and refuses to let the agent claim success, unless
    `state == "known"`, answering `caller_number_unknown:<state>` with the state spelled
    out. That is why `fold_caller_identity`'s disagreement rule is not academic: it decides,
    synchronously, what an agent is allowed to SAY to a person who has just asked not to be
    called again, and the safe direction is always the one where `is_known` is False.

    The verdict's STATE is also logged at call start, which is the signal an operator has
    been missing: `apps/api/worker/service.py::_alert_if_nobody_was_on_the_call` can only
    notice the absence once the call has already ended. Passing `None` means the same as
    passing `CallerIdentity.not_read()` and is the honest default for a caller that has not
    read a handshake at all.
    """
    caller = caller or CallerIdentity.not_read()
    route = route_of(token)
    call = await start_session(
        api,
        call_id=call_id,
        tenant_id=route.tenant_id,
        agent_id=route.agent_id,
        direction=direction,
        engine_agent_ref=token,
        credentials=credentials,
        transport=transport,
        sink=sink,
        fetcher=fetcher,
        cache=cache,
        embedder=embedder,
        caller=caller,
    )
    arm_first_turn(transport, call, call_id=call_id)
    # Ids and words (hard rule 6). `caller.state` and `caller.ground` are written in this
    # module and never built from wire data, so neither can carry a number; `caller.e164`
    # is deliberately absent from this call and from every other log line here.
    logger.info(
        "carrier call assembled",
        call_id=call_id,
        tenant_id=str(route.tenant_id),
        agent_id=str(route.agent_id),
        direction=direction,
        caller_identity=caller.state,
        caller_identity_ground=caller.ground,
    )
    return call


class CarrierNotWrittenError(RuntimeError):
    """A carrier operation whose request nobody has read. Refused by name, never guessed.

    The same shape `apps/api/engine/pipecat.py::_carrier_not_written` gives the control
    plane, for the same reason and with the same sentence: an unbuilt half must refuse
    where it is called rather than be discovered as an `AttributeError` by whoever wires
    the second entrypoint.
    """


def fetch_call_detail_record(*_args: Any, **_kwargs: Any) -> CarrierCdr:
    """REFUSES. Nothing in this repository can read a carrier CDR, and this is where it would.

    **THIS IS THE LEG'S MISSING PRODUCER, AND IT IS DECLARED RATHER THAN LEFT ABSENT** — the
    shape `apps/api/agents/transfer_providers/plivo.py` and `place_outbound_call` below both
    take. `meter.CarrierCdr` is constructed nowhere but the meter's own tests, so every call
    settles `meter_carrier_cdr_missing`: no `telephony_s` row, and therefore no billed
    minutes for the client (see `CarrierFactsMissingError`). An absence with no name reads as
    an oversight and gets re-derived by whoever looks next; a refusal at the call site is
    where the wiring lands when the account arrives.

    **WHAT IS KNOWN, FROM THE ONE PRIMARY SOURCE READABLE HERE.** The pinned
    `pipecat-ai==1.10.0` tree contains exactly ONE Plivo REST endpoint — the hangup DELETE
    at `serializers/plivo.py:184`, Basic-authed over `(auth_id, auth_token)` at `:187`. It
    establishes the host, the account path and the auth scheme, and nothing about CDRs.

    **WHAT IS UNKNOWN — `api.plivo.com` and `www.plivo.com` are egress-blocked from this
    container** (`curl: (56) CONNECT tunnel failed, response 403`; the same measurement
    `docs/evidence/pre-build-blockers-2026-09-13.md` §10 records). The five facts that would
    let this be written, each to be answered ONLY from the vendor's own pages, quoting page
    and date beside it, with "not stated on these pages" rather than an inference:

      1. The exact request that retrieves ONE call's detail record by the carrier's own call
         id: method, full path, required headers, and every query parameter.
      2. The field carrying BILLED duration and its unit, and whether it differs from
         connected duration (answer-to-hangup) — they are the same field on some carriers
         and not on others, and the wrong one is a systematically wrong invoice.
      3. The field carrying the CHARGE, its currency, and whether it is final at hangup or
         settles later. A figure that moves after we have written it lands in an
         append-only ledger that has no UPDATE to correct it (hard rule 4).
      4. How long after hangup the record is available and complete, which is what decides
         whether this is a settlement-time fetch or a reconciliation sweep.
      5. The rounding rule: the minimum billable unit and the increment past it. Without it
         a per-second quantity cannot be reconciled against the carrier's own invoice.

    ⚠ **FACT 3 IS NOT ENOUGH ON ITS OWN, AND THE REST IS NOT THIS FILE'S TO DECIDE.** Whose
    cost that charge IS remains open: under D-474 Model B the CLIENT is the subscriber of
    record and the carrier bills them directly, so the charge would be theirs and never
    `unit_cost_paid`, while `PLIVO_AUTH_ID`/`PLIVO_AUTH_TOKEN` in this deployment are OURS.
    `docs/evidence/per-minute-cost-model-2026-09-21.md` §4.1 states the tension and leaves
    it to the founder. The QUANTITY is wanted either way; the charge is not.
    """
    raise CarrierNotWrittenError(CDR_LISTING_UNKNOWN)


def place_outbound_call(*_args: Any, **_kwargs: Any) -> AssembledCall:
    """REFUSES. The dial is the one carrier operation this module cannot perform.

    Everything else about an outbound call is already built: the same transport, the same
    serializer, the same pipeline, and `start_carrier_call(direction="outbound")` runs it
    once a media stream exists. What is missing is the HTTP request that makes the carrier
    ring a number, and its method, path and body are UNKNOWN here — see
    `OUTBOUND_DIAL_UNKNOWN`.
    """
    raise CarrierNotWrittenError(OUTBOUND_DIAL_UNKNOWN)


__all__ = [
    "CALLER_IDENTITY_PARSE",
    "CDR_LISTING_UNKNOWN",
    "CLAIM_CALLER_PARAM",
    "CLAIM_CALLER_STATE_PARAM",
    "CLAIM_CARRIER_PARAM",
    "CLIENT_CONNECTED_EVENT",
    "CLIENT_DISCONNECTED_EVENT",
    "OUTBOUND_DIAL_UNKNOWN",
    "PLIVO_TRANSPORT_TYPE",
    "CallRoute",
    "CallerIdentity",
    "CallerIdentityState",
    "CarrierCdr",
    "CarrierClaimMismatchError",
    "CarrierIdentityParse",
    "CarrierNotWrittenError",
    "CarrierWiringError",
    "ControlPlaneClaim",
    "PlivoCredentials",
    "PlivoHandshake",
    "UnroutableCallError",
    "arm_first_turn",
    "build_plivo_transport",
    "caller_identity_of",
    "claim_from_stream_url",
    "fetch_call_detail_record",
    "fold_caller_identity",
    "place_outbound_call",
    "read_plivo_handshake",
    "route_of",
    "start_carrier_call",
]
