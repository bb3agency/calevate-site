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
   `parse_telephony_websocket` populates `from`/`to` for Telnyx and Exotel and leaves both
   `None` for Plivo (`runner/utils.py:250-262`) — so this module does NOT route a call by
   the number that was dialled. See `route_of` for what it routes on instead, which is a
   design that does not need the answer.
2. **Whether Plivo signs the HTTP request that fetches the answer document.** That leg
   is not here — see the next section — and nothing in the installed Pipecat tree
   verifies a Plivo request signature.
3. **Every carrier REST call except the hangup** — placing a call, listing a CDR, binding a
   number. `apps/api/engine/pipecat.py` refuses each by name for this reason and this
   module adds no second guess; see `OUTBOUND_DIAL_UNKNOWN` below.

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
tenant and agent ids, the carrier's own stream id, and words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine import parse_owned_runtime_agent_ref
from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from voice_worker.api_client import WorkerApiClient
from voice_worker.knowledge import PackCache, PackFetcher, QueryEmbedder
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


@dataclass(frozen=True, slots=True)
class PlivoHandshake:
    """What the carrier says at the top of a stream, as Pipecat parses it.

    EXACTLY TWO FIELDS, because exactly two are populated for this provider:
    `parse_telephony_websocket` maps `start.streamId` and `start.callId` and nothing else
    (`runner/utils.py:257-262`). A `from_number`/`to_number` pair on this dataclass would
    be two fields that are always `None` on the one carrier we run — an invitation to route
    on them.

    `call_id` here is the CARRIER's id for the call and is NOT `SessionConfig.call_id`,
    which is ours (§1.2: the carrier's CDR is reconciled against our id rather than being
    its source). Both are kept: the hangup is addressed with theirs.
    """

    stream_id: str
    carrier_call_id: str

    @classmethod
    def from_call_data(cls, call_data: Any) -> PlivoHandshake:
        """Build one from `parse_telephony_websocket`'s `CallData`.

        Takes the parsed object rather than the raw websocket so that the caller owns the
        single-use message stream, and takes it as `Any` because `CallData` declares both
        fields as `str | None` (`runner/types.py:92-93`) — a shape that is right for a
        model spanning four carriers and wrong for the one contract this worker has. The
        narrowing to two required strings happens here, once, with a refusal attached.
        """
        stream_id = getattr(call_data, "stream_id", None)
        carrier_call_id = getattr(call_data, "call_id", None)
        if not stream_id or not carrier_call_id:
            raise UnroutableCallError(
                "the carrier handshake carried no stream id or no call id, so this "
                "connection cannot be answered or hung up"
            )
        return cls(stream_id=str(stream_id), carrier_call_id=str(carrier_call_id))


async def read_plivo_handshake(websocket: Any) -> PlivoHandshake:
    """The first two messages off a carrier socket, as OUR handshake — or a refusal.

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
    transport_type, call_data = await parse_telephony_websocket(websocket)
    if transport_type != PLIVO_TRANSPORT_TYPE:
        raise UnroutableCallError(
            f"this socket speaks {transport_type!r}, and this deployment's carrier is "
            f"{PLIVO_TRANSPORT_TYPE!r}"
        )
    return PlivoHandshake.from_call_data(call_data)


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
    """Make the agent speak first when the carrier connects — or refuse to pretend it will.

    `AssembledCall.start_conversation` holds the decision (and returns whether it spoke);
    this registers it on the transport's own connect event, which is the shipped pattern
    (`examples/voice/voice-cartesia.py:112-119`) and the reason `assemble_call` does not do
    it: a fake transport has no such event, and `assemble_call` must stay runnable against
    one.

    The registration is VERIFIED rather than attempted — see `CarrierWiringError`. The
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

    async def _greet(*_args: Any) -> None:
        # Two states an operator needs apart, and neither is an error: an agent that
        # opened the call, and one configured not to. Ids and words (hard rule 6).
        spoke = await call.start_conversation()
        logger.info("carrier call connected", call_id=call_id, spoke_first=spoke)

    transport.add_event_handler(CLIENT_CONNECTED_EVENT, _greet)


async def start_carrier_call(
    api: WorkerApiClient,
    *,
    token: str,
    call_id: str,
    direction: CallDirection,
    transport: BaseTransport,
    credentials: VendorCredentials,
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
    """
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
    )
    arm_first_turn(transport, call, call_id=call_id)
    # Ids and words (hard rule 6). No number is available here and none would be logged if
    # it were; the carrier's stream id is what ties this line to their side of the call.
    logger.info(
        "carrier call assembled",
        call_id=call_id,
        tenant_id=str(route.tenant_id),
        agent_id=str(route.agent_id),
        direction=direction,
    )
    return call


class CarrierNotWrittenError(RuntimeError):
    """A carrier operation whose request nobody has read. Refused by name, never guessed.

    The same shape `apps/api/engine/pipecat.py::_carrier_not_written` gives the control
    plane, for the same reason and with the same sentence: an unbuilt half must refuse
    where it is called rather than be discovered as an `AttributeError` by whoever wires
    the second entrypoint.
    """


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
    "CLIENT_CONNECTED_EVENT",
    "OUTBOUND_DIAL_UNKNOWN",
    "PLIVO_TRANSPORT_TYPE",
    "CallRoute",
    "CarrierNotWrittenError",
    "CarrierWiringError",
    "PlivoCredentials",
    "PlivoHandshake",
    "UnroutableCallError",
    "arm_first_turn",
    "build_plivo_transport",
    "place_outbound_call",
    "read_plivo_handshake",
    "route_of",
    "start_carrier_call",
]
