"""`docs/PIPECAT-MIGRATION.md` §6 step 6: the carrier leg, with no carrier.

**WHAT THIS FILE IS TRYING TO CATCH.** Step 6 is gated on a Plivo account in the India data
region, and the whole point of building it now is that the ACCOUNT gates the CALL and not
the CODE. So every assertion here is one that a real call would otherwise have been the
first to make:

1. **Every Plivo-shaped fact we build on is read back out of the installed
   `pipecat-ai==1.10.0` tree rather than restated.** `www.plivo.com` is egress-blocked from
   this container, so Pipecat's source is the only primary source available (hard rule 11);
   a dependency bump that moves the envelope, the encoding or the answer document fails
   HERE, where somebody is looking, instead of on a live call.
2. **The inbound path runs end to end** — a route token off a stream URL, a real database
   read under a real RLS policy, the published config version, the agent's knowledge, an
   assembled pipeline, and the agent speaking first — against a fake transport with no
   socket, no account and no network.
3. **Hard rule 5 cannot be gone around on this leg.** An agent with no AI-disclosure
   sentence, or a published prompt that does not carry the truthful-answer floor, is
   refused before anything is assembled. This is the leg where `apps/api`'s two existing
   guards do not apply: an inbound call reaches the worker directly.
4. **A call that names no agent of ours is refused without touching the database at all**,
   which is asserted by handing the path a connection factory that fails if it is opened.
5. **Hard rule 6**: the agent's own phone number is in the database throughout, and no log
   line on this path contains it or any transcript text.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast
from urllib.parse import unquote, urlparse
from xml.etree.ElementTree import fromstring

import pytest
from apps.api.db.session import tenant_session
from calevate_shared.engine import TRUTHFUL_ANSWER_DIRECTIVE, owned_runtime_agent_ref
from loguru import logger
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.plivo import PlivoFrameSerializer
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.voice_worker_pipeline_test import CREDENTIALS, FakeTransport, RecordingSink
from tests.voice_worker_session_test import CountingFetcher, _publish_a_fact, _runtime_agent
from voice_worker import carrier
from voice_worker.config import AgentNotRunnableError, refuse_unless_disclosed
from voice_worker.knowledge import PackCache

#: The carrier account's own two secrets, which are NOT the three model keys
#: (`CREDENTIALS`, imported above): different account, different place, different job.
PLIVO_CREDENTIALS = carrier.PlivoCredentials(auth_id="MA-test", auth_token="token-test")


@dataclass
class _SetupWithRate:
    """The one field `PlivoFrameSerializer.setup` reads (`serializers/plivo.py:116`)."""

    audio_in_sample_rate: int = carrier.TELEPHONY_SAMPLE_RATE_HZ


class _SocketSaying:
    """A websocket that says `connected`, then one start message, and nothing else.

    Two messages because that is what `parse_telephony_websocket` reads
    (`runner/utils.py:185-208`); `headers` because the parser's callers read it.
    """

    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, start_message: str) -> None:
        self._start = start_message

    def iter_text(self) -> Any:
        async def _messages() -> Any:
            yield '{"event": "connected"}'
            yield self._start

        return _messages()


def _pipecat_source(relative: str) -> str:
    """One file of the INSTALLED pipecat tree, as text.

    Read off the imported package rather than from a path this file spells, so the source
    under assertion is the one the worker will actually import.
    """
    import pipecat

    return (Path(pipecat.__file__).parent / relative).read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# 1. The Plivo facts, each against the installed source that gave it to us.
# --------------------------------------------------------------------------------------


def test_the_answer_document_is_pipecats_own_template_and_not_our_reading_of_it() -> None:
    """`plivo_answer_document` must render exactly the element the shipped runner renders.

    The template is extracted from `pipecat/runner/run.py` and parsed, rather than copied
    into this file — a copy would assert that we still agree with ourselves. What is
    compared is the tag and the full attribute set, because the ATTRIBUTES are the part we
    could not verify any other way (Plivo's own grammar is egress-blocked here).
    """
    source = _pipecat_source("runner/run.py")
    match = re.search(r"<Response>\s*(<Stream [^>]*>)[^<]*</Stream>\s*</Response>", source)
    assert match, "pipecat no longer ships a Plivo answer template at the shape we read"
    theirs = fromstring(match.group(1) + "</Stream>")

    ours = fromstring(carrier.plivo_answer_document("wss://voice.example.invalid/ws/token"))

    assert ours.tag == "Response"
    (stream,) = list(ours)
    assert stream.tag == theirs.tag == "Stream"
    assert stream.attrib == theirs.attrib
    assert stream.text == "wss://voice.example.invalid/ws/token"
    assert carrier.ANSWER_DOCUMENT_CONTENT_TYPE == "application/xml"


def test_the_answer_document_escapes_a_url_rather_than_concatenating_it() -> None:
    """A wire value with an `&` in it must not break the document a carrier parses."""
    url = "wss://voice.example.invalid/ws/a?x=1&y=2"
    document = carrier.plivo_answer_document(url)

    assert "&amp;" in document
    (stream,) = list(fromstring(document))
    assert stream.text == url


async def test_the_handshake_fields_are_the_ones_pipecat_parses_for_plivo() -> None:
    """`PlivoHandshake` carries what the vendor's client really hands us, and no more.

    Driven through `parse_telephony_websocket` itself — Pipecat's own detector and parser —
    so this fails if the provider's start message, its detection rule or the parsed field
    names move. The `from`/`to` assertion is the UNKNOWN `carrier.route_of` is designed
    around: those two are populated for Telnyx and Exotel and are `None` here.
    """

    socket = _SocketSaying(
        '{"event": "start", "start": {"streamId": "stream-1", "callId": "carrier-call-1"}}'
    )
    transport_type, call_data = await parse_telephony_websocket(socket)

    assert transport_type == carrier.PLIVO_TRANSPORT_TYPE == "plivo"
    assert call_data.from_number is None and call_data.to_number is None

    handshake = carrier.PlivoHandshake.from_call_data(call_data)
    assert handshake.stream_id == "stream-1"
    assert handshake.carrier_call_id == "carrier-call-1"
    assert set(carrier.PlivoHandshake.__dataclass_fields__) == {"stream_id", "carrier_call_id"}


async def test_the_handshake_reader_uses_pipecats_detection_and_agrees_with_it() -> None:
    """`read_plivo_handshake` is the door a mount will use, so it is driven whole."""
    socket = _SocketSaying(
        '{"event": "start", "start": {"streamId": "stream-2", "callId": "carrier-call-2"}}'
    )

    handshake = await carrier.read_plivo_handshake(socket)

    assert handshake == carrier.PlivoHandshake(
        stream_id="stream-2", carrier_call_id="carrier-call-2"
    )


async def test_a_socket_from_another_carrier_is_refused_rather_than_mis_serialized() -> None:
    """Pipecat's parser spans four providers; this deployment has one.

    A Twilio start message really does detect as `twilio` (`runner/utils.py:62-110`), and a
    mount that handed that `CallData` to `build_plivo_transport` would connect a call and
    put silence on it — the serializer would be speaking the wrong protocol. The refusal is
    what makes that impossible rather than unlikely.
    """
    socket = _SocketSaying(
        '{"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1", '
        '"customParameters": {}}}'
    )

    with pytest.raises(carrier.UnroutableCallError) as refusal:
        await carrier.read_plivo_handshake(socket)

    assert "twilio" in str(refusal.value) and "plivo" in str(refusal.value)


async def test_a_handshake_missing_its_ids_is_refused_rather_than_answered() -> None:
    """A `CallData` whose two fields are `None` is not a call we can answer or hang up."""

    class _Empty:
        stream_id = None
        call_id = None

    with pytest.raises(carrier.UnroutableCallError):
        carrier.PlivoHandshake.from_call_data(_Empty())


async def test_the_serializer_speaks_the_envelopes_this_module_depends_on() -> None:
    """The media wire shape, round-tripped through the vendor's own serializer.

    Not a test OF Pipecat: it is the pin on the two facts `build_plivo_transport` is built
    from — that outbound audio leaves as a `playAudio` envelope of 8 kHz μ-law, and that
    inbound `media` arrives as PCM at the pipeline's rate. If either moves, the transport
    we hand `assemble_call` is wrong and every call is silence.
    """
    serializer = PlivoFrameSerializer(
        stream_id="stream-1",
        call_id="carrier-call-1",
        auth_id=PLIVO_CREDENTIALS.auth_id,
        auth_token=PLIVO_CREDENTIALS.auth_token,
    )
    # `FrameSerializer.setup` reads exactly one field (`serializers/plivo.py:116`), and
    # `FrameProcessorSetup` requires a clock, a task manager and a worker this test has no
    # use for — so it is given the field rather than a pipeline.
    await serializer.setup(cast(FrameProcessorSetup, _SetupWithRate()))

    out = await serializer.serialize(
        OutputAudioRawFrame(
            audio=b"\x00\x01" * 160, sample_rate=carrier.TELEPHONY_SAMPLE_RATE_HZ, num_channels=1
        )
    )
    assert isinstance(out, str)
    envelope = json.loads(out)
    assert envelope["event"] == "playAudio"
    assert envelope["streamId"] == "stream-1"
    assert envelope["media"]["contentType"] == "audio/x-mulaw"
    assert envelope["media"]["sampleRate"] == carrier.TELEPHONY_SAMPLE_RATE_HZ

    frame = await serializer.deserialize(
        json.dumps({"event": "media", "media": {"payload": envelope["media"]["payload"]}})
    )
    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == carrier.TELEPHONY_SAMPLE_RATE_HZ
    assert base64.b64decode(envelope["media"]["payload"])


def test_the_serializer_refuses_to_be_built_without_what_a_hangup_needs() -> None:
    """`auto_hang_up` is ON by default and the two secrets are what it costs.

    Asserted because `PlivoCredentials` exists for exactly this: a transport built without
    them would raise at the moment a call arrives rather than at deploy time.
    """
    assert PlivoFrameSerializer.InputParams().auto_hang_up is True
    assert PlivoFrameSerializer.InputParams().plivo_sample_rate == carrier.TELEPHONY_SAMPLE_RATE_HZ

    with pytest.raises(ValueError) as refusal:
        PlivoFrameSerializer(stream_id="stream-1")

    assert "auth_id" in str(refusal.value) and "auth_token" in str(refusal.value)


def test_no_outbound_dial_is_invented_and_the_refusal_says_why() -> None:
    """The one carrier operation that is NOT built, refused by name (hard rule 11)."""
    with pytest.raises(carrier.CarrierNotWrittenError) as refusal:
        carrier.place_outbound_call()

    assert "not built" in str(refusal.value)
    assert "serializers/plivo.py:184" in str(refusal.value)


# --------------------------------------------------------------------------------------
# 2. Routing: the stream URL names the agent, and nothing else does.
# --------------------------------------------------------------------------------------


def test_a_stream_url_round_trips_to_the_agent_it_names() -> None:
    """Mint -> URL -> the path segment a carrier connects back to -> the same two ids."""
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    ref = owned_runtime_agent_ref(str(tenant_id), str(agent_id))

    url = carrier.plivo_stream_url("wss://voice.example.invalid/ws", ref)
    token = unquote(urlparse(url).path.rsplit("/", 1)[-1])

    assert carrier.route_of(token) == carrier.CallRoute(tenant_id=tenant_id, agent_id=agent_id)


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        "pipecat:not-a-uuid:also-not",
        f"bolna:{uuid.uuid4()}:{uuid.uuid4()}",
        f"pipecat:{uuid.uuid4()}",
    ],
)
def test_a_token_that_names_no_agent_of_ours_is_refused_and_never_echoed(token: str) -> None:
    """Anything can connect to a WebSocket URL, so the token is attacker-controlled.

    Two assertions and the second matters as much as the first: the refusal must not put an
    arbitrary string into an operator's log line.
    """
    with pytest.raises(carrier.UnroutableCallError) as refusal:
        carrier.route_of(token)

    assert token not in str(refusal.value)


# --------------------------------------------------------------------------------------
# 3. The inbound path, end to end, against a fake transport.
# --------------------------------------------------------------------------------------


class ConnectableFakeTransport(FakeTransport):
    """The step-4 fake, plus the one event a carrier transport really fires.

    `FastAPIWebsocketTransport` registers `on_client_connected`
    (`pipecat/transports/websocket/fastapi.py:674-678`) and `carrier.arm_first_turn` refuses
    a transport that does not — so a fake without it would make the greeting untestable AND
    make the refusal untestable. `connect()` is what a carrier's connection does.
    """

    def __init__(self) -> None:
        super().__init__()
        self._register_event_handler(carrier.CLIENT_CONNECTED_EVENT)

    async def connect(self) -> None:
        await self._call_event_handler(carrier.CLIENT_CONNECTED_EVENT, self)


class RefusingConnections:
    """A connection factory that fails if it is ever opened.

    The instrument for "the call was refused before any database work", which is otherwise
    only assertable by timing or by not asserting it at all.
    """

    def __init__(self) -> None:
        self.opened: list[uuid.UUID] = []

    @asynccontextmanager
    async def __call__(self, tenant_id: uuid.UUID) -> Any:
        self.opened.append(tenant_id)
        raise AssertionError("a database connection was opened for an unroutable call")
        yield  # pragma: no cover - unreachable, present for the generator protocol


@asynccontextmanager
async def tenant_connection(tenant_id: uuid.UUID) -> Any:
    """`carrier.TenantConnection` over the suite's real, RLS-scoped session."""
    async with tenant_session(tenant_id) as db:
        yield await db.connection()


async def _number_for(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    """Give this agent a real number, and hand it back.

    The number is hard rule 6's instrument: a path that resolved a call by the dialled
    number — or that carried one into a log line "for support" — would print this string.
    `e164` is unique platform-wide, so each test mints its own rather than sharing one.
    """
    e164 = f"+9198765{uuid.uuid4().int % 100000:05d}"
    async with tenant_session(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                "dlt_status, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, 'standard', 'pending', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "aid": agent_id, "e": e164},
        )
    return e164


async def _settle() -> None:
    """Let the transport's event task run.

    `BaseObject._call_event_handler` dispatches a non-sync handler as an asyncio TASK
    (`pipecat/utils/base_object.py:255-260`), so the greeting lands on the next turn of the
    loop rather than inside `connect()`. Asserting without this would be asserting that an
    event handler is synchronous, which it is not.
    """
    for _ in range(50):
        await asyncio.sleep(0)


FACT = "Trouser alteration is eighty rupees."


async def test_a_call_arrives_and_the_agent_is_loaded_assembled_and_speaks_first(
    s3: FakeS3,
) -> None:
    """The whole inbound path: token in, a running agent out.

    This is the assertion step 6 exists to make and the one a real call would otherwise
    have made first. Everything it touches is real except the carrier: a real published
    config version, a real RLS-scoped read, a real knowledge pack fetched by digest, the
    real assembler, and the agent's first turn queued from the transport's own connect
    event.
    """
    tenant_id, agent_id = await _runtime_agent()
    await _publish_a_fact(tenant_id, agent_id, FACT)
    await _number_for(tenant_id, agent_id)
    fetcher = CountingFetcher()
    transport = ConnectableFakeTransport()
    ref = owned_runtime_agent_ref(str(tenant_id), str(agent_id))

    call = await carrier.start_carrier_call(
        tenant_connection,
        token=unquote(
            urlparse(carrier.plivo_stream_url("wss://voice.example.invalid/ws", ref)).path.rsplit(
                "/", 1
            )[-1]
        ),
        call_id="call-carrier-1",
        direction="inbound",
        transport=transport,
        credentials=CREDENTIALS,
        sink=RecordingSink(),
        fetcher=fetcher,
        cache=PackCache(),
    )

    # The config version really loaded, and the worker's own recomputation agrees with it
    # (§1.1) — so this call is running the prompt the control plane published.
    assert call.prompt_matches_config_version
    assert call.greet_first
    # The agent has not spoken yet: `start_conversation` belongs to the connect event, and
    # a greeting queued at assembly would be a greeting queued before the caller was there.
    assert call.context.messages[-1]["role"] == "system"

    await transport.connect()
    await _settle()

    assert call.context.messages[-1] == {
        "role": "developer",
        "content": "Greet the caller as your instructions direct.",
    }


async def test_a_transport_that_cannot_say_when_the_caller_connected_is_refused(
    s3: FakeS3,
) -> None:
    """The failure with no symptom: `add_event_handler` only WARNS on an unknown event.

    Without this refusal the agent would answer every call and say nothing at all, with a
    green deploy — so the plain step-4 fake (which has no connect event) must not be
    accepted here.
    """
    tenant_id, agent_id = await _runtime_agent()
    ref = owned_runtime_agent_ref(str(tenant_id), str(agent_id))

    with pytest.raises(carrier.CarrierWiringError):
        await carrier.start_carrier_call(
            tenant_connection,
            token=ref,
            call_id="call-carrier-2",
            direction="inbound",
            transport=FakeTransport(),
            credentials=CREDENTIALS,
            sink=RecordingSink(),
            fetcher=CountingFetcher(),
            cache=PackCache(),
        )


async def test_a_call_for_an_unknown_agent_is_refused_without_opening_the_database() -> None:
    """A token nobody minted: refused at the parse, before a connection exists."""
    connections = RefusingConnections()

    with pytest.raises(carrier.UnroutableCallError):
        await carrier.start_carrier_call(
            connections,
            token="pipecat:nobody:nothing",
            call_id="call-carrier-3",
            direction="inbound",
            transport=ConnectableFakeTransport(),
            credentials=CREDENTIALS,
            sink=RecordingSink(),
            fetcher=CountingFetcher(),
            cache=PackCache(),
        )

    assert connections.opened == []


async def test_a_call_for_an_agent_that_was_never_published_is_refused_cleanly(
    s3: FakeS3,
) -> None:
    """A well-formed token naming an agent with no runtime row.

    The refusal is `AgentNotRunnableError` and not `UnroutableCallError`, because the two
    send an operator to different screens: this is a publish fault, not a provisioning one.
    """
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()

    with pytest.raises(AgentNotRunnableError):
        await carrier.start_carrier_call(
            tenant_connection,
            token=owned_runtime_agent_ref(str(tenant_id), str(agent_id)),
            call_id="call-carrier-4",
            direction="inbound",
            transport=ConnectableFakeTransport(),
            credentials=CREDENTIALS,
            sink=RecordingSink(),
            fetcher=CountingFetcher(),
            cache=PackCache(),
        )


# --------------------------------------------------------------------------------------
# 4. Hard rule 5 on the leg where `apps/api`'s guards do not run.
# --------------------------------------------------------------------------------------


def test_an_agent_with_no_disclosure_sentence_may_not_answer_or_place_a_call() -> None:
    """The dial gate's question, asked of ANSWERING.

    Called directly rather than through a row, and the reason is that the database will not
    let the row exist: `agents.ai_disclosure_line` is NOT NULL with
    `length(btrim(...)) > 0` (`apps/api/agents/models.py:211`). That is precisely why this
    check is belt and braces — reaching it means something bypassed the schema — and a
    guard whose only test needed the schema to be broken would have no test at all.
    """
    agent_id = uuid.uuid4()
    prompt = "You are a receptionist.\n" + _floor()

    for missing in (None, "", "   "):
        with pytest.raises(AgentNotRunnableError) as refusal:
            refuse_unless_disclosed(
                agent_id=agent_id, ai_disclosure_line=missing, composed_prompt=prompt
            )
        assert "AI disclosure line" in str(refusal.value)
        assert str(agent_id) in str(refusal.value)


def test_a_prompt_that_lost_the_truthful_answer_floor_may_not_run_a_call() -> None:
    """The other half, and the one no column constrains.

    `compose_engine_prompt` appends the floor to every version, so a version without it was
    composed by something else — and this worker is the last reader before a model speaks
    to a caller.
    """
    agent_id = uuid.uuid4()

    for prompt in (None, "", "You are a receptionist. Tell callers you are human."):
        with pytest.raises(AgentNotRunnableError) as refusal:
            refuse_unless_disclosed(
                agent_id=agent_id,
                ai_disclosure_line="I am an AI assistant.",
                composed_prompt=prompt,
            )
        assert "truthful-answer floor" in str(refusal.value)


def test_a_published_agent_passes_both_conditions() -> None:
    """The control. Without it the two tests above would pass on a guard that refuses
    everything, which is the shape a compliance check fails in most quietly."""
    refuse_unless_disclosed(
        agent_id=uuid.uuid4(),
        ai_disclosure_line="I am an AI assistant.",
        composed_prompt="You are a receptionist.\n" + _floor(),
    )


def _floor() -> str:
    """The one block every composed prompt carries. Read from the contract, never retyped —
    a copy here would let this suite go on passing after the real sentence changed."""
    return TRUTHFUL_ANSWER_DIRECTIVE


# --------------------------------------------------------------------------------------
# 5. Hard rule 6 on the new path.
# --------------------------------------------------------------------------------------


async def test_the_carrier_path_logs_no_phone_number_and_no_transcript_text(
    s3: FakeS3,
) -> None:
    """Two new log lines stand on this path and a phone number is in the database for the
    whole of it.

    The number is the real instrument: an implementation that resolved a call by the dialled
    number, or that carried one into a log line "for support", fails here. The published
    fact stands in for transcript text — it is the content the pack holds and the one thing
    a knowledge-shaped log line would be tempted to print.
    """
    tenant_id, agent_id = await _runtime_agent()
    await _publish_a_fact(tenant_id, agent_id, FACT)
    e164 = await _number_for(tenant_id, agent_id)
    transport = ConnectableFakeTransport()

    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink_log, level="DEBUG")
    try:
        await carrier.start_carrier_call(
            tenant_connection,
            token=owned_runtime_agent_ref(str(tenant_id), str(agent_id)),
            call_id="call-carrier-5",
            direction="inbound",
            transport=transport,
            credentials=CREDENTIALS,
            sink=RecordingSink(),
            fetcher=CountingFetcher(),
            cache=PackCache(),
        )
        await transport.connect()
        await _settle()
    finally:
        logger.remove(handler)

    blob = "\n".join(captured)
    assert blob, "nothing was logged at all, so this test proves nothing"
    assert e164 not in blob
    assert FACT not in blob
    # The ids an operator needs ARE there, or the log lines are not worth their own risk.
    assert "call-carrier-5" in blob and str(agent_id) in blob


async def test_the_transport_is_built_from_the_handshake_and_the_carrier_secrets() -> None:
    """`build_plivo_transport` wires the serializer, the rate and the header setting.

    Asserted on the params the transport holds rather than by connecting anything: this is
    the one function here that touches a real `FastAPIWebsocketTransport`, and what it must
    get right is the three defaults it changes.
    """

    class _Socket:
        headers: ClassVar[dict[str, str]] = {}

        async def accept(self) -> None:  # pragma: no cover - never called here
            raise AssertionError("the transport must not accept a socket at construction")

    transport = carrier.build_plivo_transport(
        _Socket(),
        handshake=carrier.PlivoHandshake(stream_id="stream-1", carrier_call_id="carrier-call-1"),
        credentials=PLIVO_CREDENTIALS,
    )

    params = transport._params
    assert isinstance(params.serializer, PlivoFrameSerializer)
    assert params.add_wav_header is False
    assert params.audio_in_sample_rate == carrier.TELEPHONY_SAMPLE_RATE_HZ
    assert params.audio_out_sample_rate == carrier.TELEPHONY_SAMPLE_RATE_HZ
    assert carrier.CLIENT_CONNECTED_EVENT in transport._event_handlers
