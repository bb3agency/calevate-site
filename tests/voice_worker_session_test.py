"""The middle of the in-call KB seam: the digest reaches the worker and the pack is loaded.

**WHAT THIS FILE IS TRYING TO CATCH.** Three commits built the two ends of this path — a
pack built and stored on publish, a search that answers four ways — and left the middle
open: nothing read `agents.knowledge_pack_sha256` into a `SessionConfig`, and nothing
awaited `load_session_knowledge` before `assemble_call`. A call would therefore have been
assembled with `knowledge=None` on EVERY agent, and every caller of every client would have
been told, in the agent's own voice, that the business had published nothing. The failure
has no error, no alarm and no red test; it just answers wrongly, in a client's name, on the
phone. So the assertions here are about the wiring itself:

1. the digest that `kb/pack.refresh_published_pack` wrote is the digest `load_session_config`
   returns, read out of a real database through a real RLS policy;
2. `open_session` fetches with it, and the tool the model sees answers `found`;
3. each way the load can fail produces the RIGHT silence — `no_knowledge_base` when the
   client published nothing, `temporarily_unavailable` when we could not read what they
   did — and in both cases the call is still assembled and still runs;
4. the process cache is process-wide (a second call for one agent downloads nothing) and is
   never a cross-tenant leak, which is DEMONSTRATED by asking for one tenant's pack with
   another tenant's ids rather than asserted;
5. nothing on the path logs a passage, a gloss or the caller's question (hard rule 6).

The fixture corpus is a tailoring shop's published facts. Small-business, boring, and the
`found` assertion is over a sentence the client would actually have written down.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
from apps.api.kb import service as kb_service
from botocore.exceptions import ClientError, EndpointConnectionError
from calevate_shared.engine import AgentConfig, ModelConfig, azure_openai_base_url
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.voice_worker_pipeline_test import (
    CREDENTIALS,
    FakeTransport,
    RecordingSink,
    invoke_tool,
    make_config,
)
from tests.worker_api_harness import worker_client
from voice_worker import pipeline, session, storage
from voice_worker.config import AgentNotRunnableError, load_session_config
from voice_worker.knowledge import PackCache

# Stable document ids, so a provenance assertion names a document rather than a uuid the
# fixture minted one line earlier.
ALTERATIONS_DOC = uuid.UUID("0199c1a0-0002-7000-8000-00000000001a")
DELIVERY_DOC = uuid.UUID("0199c1a0-0002-7000-8000-00000000001b")

ALTERATION_FACT = "Trouser alteration is eighty rupees and shirt alteration is sixty rupees."
DELIVERY_FACT = "Stitched clothes are ready for pickup in four working days."


# --------------------------------------------------------------------------------------
# Fixtures: a published pack, and fetchers that fail in each of the ways a store can.
# --------------------------------------------------------------------------------------


def _entries() -> tuple[PackEntry, ...]:
    return (
        PackEntry(
            chunk_id=uuid.uuid4(),
            document_id=ALTERATIONS_DOC,
            document_version=2,
            text=ALTERATION_FACT,
        ),
        PackEntry(
            chunk_id=uuid.uuid4(),
            document_id=DELIVERY_DOC,
            document_version=1,
            text=DELIVERY_FACT,
        ),
    )


def _pack(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> KnowledgePack:
    entries = _entries()
    return KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=KnowledgePack.digest(tenant_id, agent_id, entries),
        built_at=datetime(2026, 9, 14, 7, 0, tzinfo=UTC),
        entries=entries,
    )


class CountingFetcher:
    """A `PackFetcher` over a dict, which counts what it was asked for.

    The COUNT is the instrument for every cache assertion here: "the second call downloaded
    nothing" is a statement about how many times this was called, and asserting it any
    other way (a timing, a log line) would be asserting a proxy.
    """

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = {} if objects is None else objects
        self.asked: list[str] = []

    def hold(self, pack: KnowledgePack) -> str:
        key = pack_object_key(pack.tenant_id, pack.agent_id, pack.content_sha256)
        self.objects[key] = pack.model_dump_json().encode()
        return pack.content_sha256

    async def fetch(self, object_key: str) -> bytes | None:
        self.asked.append(object_key)
        return self.objects.get(object_key)


class BrokenFetcher:
    """A store we could not read. `PackFetcher` says `None` means ABSENT, so this raises."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def fetch(self, object_key: str) -> bytes | None:
        self.asked.append(object_key)
        raise EndpointConnectionError(endpoint_url="https://object-store.example.invalid")


async def _open(
    config: pipeline.SessionConfig,
    *,
    fetcher: Any,
    cache: PackCache | None = None,
) -> tuple[pipeline.AssembledCall, Any]:
    """Start a session the way the entrypoint does, and hand back its ONE advertised tool."""
    call = await session.open_session(
        config=config,
        credentials=CREDENTIALS,
        transport=FakeTransport(),
        sink=RecordingSink(),
        fetcher=fetcher,
        cache=cache,
    )
    tools = call.context.tools
    assert isinstance(tools, ToolsSchema)
    (schema,) = tools.standard_tools
    return call, schema


# --------------------------------------------------------------------------------------
# 1. The four outcomes, through the real entrypoint.
# --------------------------------------------------------------------------------------


async def test_a_configured_digest_is_fetched_and_the_tool_answers_found() -> None:
    """The happy path end to end, and the one assertion that the seam is closed at all.

    The digest on the config decides the object key, the key decides the bytes, the bytes
    become the index, and the index answers the caller — through `open_session`, which is
    what a real call will run, rather than through `assemble_call` with a pack handed in.
    """
    config = make_config(tenant_id=uuid.uuid4(), agent_id=uuid.uuid4())
    fetcher = CountingFetcher()
    digest = fetcher.hold(_pack(config.tenant_id, config.agent_id))
    config = make_config(
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        knowledge_pack_sha256=digest,
    )

    call, schema = await _open(config, fetcher=fetcher, cache=PackCache())

    assert fetcher.asked == [pack_object_key(config.tenant_id, config.agent_id, digest)]
    assert call.knowledge is not None and call.knowledge.available
    payload = await invoke_tool(schema, "how much is a trouser alteration")
    assert payload["outcome"] == "found"
    # The client's own published words reach the model, not the gloss and not a summary.
    assert any(ALTERATION_FACT in str(passage["text"]) for passage in payload["passages"])


async def test_an_agent_with_no_pack_says_no_knowledge_base_and_is_never_fetched_for() -> None:
    """`None` is an ordinary day-one agent, and it must not become an object key.

    The fetch count is the real assertion. A loader that built a key from an empty digest
    would 404 on every call of every agent that has published nothing — a per-call round
    trip to prove something the row already said — and the caller would then hear
    `temporarily_unavailable`, which is a claim about US, for a client who simply has no
    knowledge base.
    """
    config = make_config(knowledge_pack_sha256=None)
    fetcher = CountingFetcher()

    call, schema = await _open(config, fetcher=fetcher, cache=PackCache())

    assert fetcher.asked == []
    assert call.knowledge is None
    payload = await invoke_tool(schema, "how much is a trouser alteration")
    assert payload["outcome"] == pipeline.KNOWLEDGE_OUTCOME_NO_PACK == "no_knowledge_base"


async def test_an_object_that_is_not_there_is_temporarily_unavailable_and_the_call_runs() -> None:
    """A pointer at an object the store does not hold. The call is NOT refused.

    `absent` is the reason an operator gets; the caller gets an agent that answers the phone
    and says it cannot verify this one thing. A raise here would have been the other design,
    and it trades a client's whole conversation for a missing file.
    """
    config = make_config(knowledge_pack_sha256="b" * 64)
    fetcher = CountingFetcher()

    call, schema = await _open(config, fetcher=fetcher, cache=PackCache())

    assert len(fetcher.asked) == 1
    assert call.knowledge is not None
    assert call.knowledge.unavailable_reason == "absent"
    payload = await invoke_tool(schema, "how much is a trouser alteration")
    assert payload["outcome"] == "temporarily_unavailable"
    # The pipeline is whole: the tool is still advertised and the call is still assembled.
    assert call.worker is not None and call.observed_prompt_sha256 == config.prompt_sha256


async def test_a_store_that_refuses_is_temporarily_unavailable_and_the_call_runs() -> None:
    """The other failure, which must not be confused with the one above.

    `load_session_knowledge` never raises, so `open_session` needs no try/except — and this
    test exists to prove that rather than to trust the docstring, because a fetcher that
    raised through the entrypoint would take the CALL down, not the lookup.
    """
    config = make_config(knowledge_pack_sha256="c" * 64)

    call, schema = await _open(config, fetcher=BrokenFetcher(), cache=PackCache())

    assert call.knowledge is not None
    assert call.knowledge.unavailable_reason == "fetch_failed"
    payload = await invoke_tool(schema, "when will my clothes be ready")
    assert payload["outcome"] == "temporarily_unavailable"


# --------------------------------------------------------------------------------------
# 2. The cache: process-wide, and not a way across a tenant boundary.
# --------------------------------------------------------------------------------------


async def test_the_second_call_for_one_agent_downloads_nothing() -> None:
    """§8.2's claim, measured: "a busy agent's second call downloads nothing".

    Two SESSIONS, one cache — the shape a warm Pipecat Cloud container has — and the second
    session's tool still answers from the pack. A per-call cache would pass every other test
    in this file and fail this one, which is exactly why it is here.
    """
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    fetcher = CountingFetcher()
    digest = fetcher.hold(_pack(tenant_id, agent_id))
    cache = PackCache()

    first_config = make_config(
        call_id="call-1", tenant_id=tenant_id, agent_id=agent_id, knowledge_pack_sha256=digest
    )
    second_config = make_config(
        call_id="call-2", tenant_id=tenant_id, agent_id=agent_id, knowledge_pack_sha256=digest
    )
    _first, _first_schema = await _open(first_config, fetcher=fetcher, cache=cache)
    assert len(fetcher.asked) == 1

    _second, second_schema = await _open(second_config, fetcher=fetcher, cache=cache)
    assert len(fetcher.asked) == 1, "the second session went back to the store"
    payload = await invoke_tool(second_schema, "when will my clothes be ready")
    assert payload["outcome"] == "found"
    assert any(DELIVERY_FACT in str(passage["text"]) for passage in payload["passages"])


async def test_one_tenants_warm_pack_is_never_served_into_another_tenants_call() -> None:
    """Cross-tenant isolation of the shared cache, DEMONSTRATED rather than asserted.

    Tenant B is pointed at the digest tenant A's pack is warm under — the exact state a
    mis-set pointer or a hostile write to `agents.knowledge_pack_sha256` would produce, and
    the one that ends badly in silence: the pack validates, its id names its own bytes, and
    B's callers would hear A's prices. So the test makes B ask for A's key by digest and
    checks three things: B is not served A's index, the poisoned entry is EVICTED rather
    than left for the next caller, and B's own tool says `temporarily_unavailable` — a
    refusal, not a neighbour's answer.

    The store is left holding A's object under A's key, deliberately: B's fetch for its own
    key misses, so nothing but the cache could have produced a wrong answer here.
    """
    tenant_a, agent_a = uuid.uuid4(), uuid.uuid4()
    tenant_b, agent_b = uuid.uuid4(), uuid.uuid4()
    fetcher = CountingFetcher()
    digest = fetcher.hold(_pack(tenant_a, agent_a))
    cache = PackCache()

    a_call, a_schema = await _open(
        make_config(tenant_id=tenant_a, agent_id=agent_a, knowledge_pack_sha256=digest),
        fetcher=fetcher,
        cache=cache,
    )
    assert a_call.knowledge is not None and a_call.knowledge.available
    assert cache.keys == (digest,), "the control failed: A's pack never warmed the cache"
    assert (await invoke_tool(a_schema, "how much is a trouser alteration"))["outcome"] == "found"

    b_call, b_schema = await _open(
        make_config(tenant_id=tenant_b, agent_id=agent_b, knowledge_pack_sha256=digest),
        fetcher=fetcher,
        cache=cache,
    )

    assert b_call.knowledge is not None
    assert not b_call.knowledge.available, "a neighbour's pack was served into this call"
    assert b_call.knowledge.unavailable_reason == "absent"
    assert cache.keys == (), "the mismatched entry was left for the next caller"
    payload = await invoke_tool(b_schema, "how much is a trouser alteration")
    assert payload["outcome"] == "temporarily_unavailable"
    assert ALTERATION_FACT not in str(payload)


async def test_the_process_cache_is_what_a_session_uses_when_it_is_given_none() -> None:
    """`PackCache` lives in `session.py` and is ONE per process. Both halves are checked.

    `pack_cache()` returning the same object twice would pass with a per-call cache behind
    a memoised accessor, so the second half is the one that means something: a session
    started with no cache argument leaves its pack in the object `pack_cache()` hands out,
    which is what makes the next session in this container free.
    """
    assert session.pack_cache() is session.pack_cache()

    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    fetcher = CountingFetcher()
    digest = fetcher.hold(_pack(tenant_id, agent_id))
    config = make_config(tenant_id=tenant_id, agent_id=agent_id, knowledge_pack_sha256=digest)
    try:
        call, _schema = await _open(config, fetcher=fetcher, cache=None)
        assert call.knowledge is not None and call.knowledge.available
        assert digest in session.pack_cache().keys
    finally:
        # The process cache outlives this test by design, so the test cleans up after
        # itself rather than leaving a warm pack for whatever runs next in this process.
        session.pack_cache().get(digest, tenant_id=uuid.uuid4(), agent_id=uuid.uuid4())
    assert digest not in session.pack_cache().keys


# --------------------------------------------------------------------------------------
# 3. Hard rule 6 on the new path.
# --------------------------------------------------------------------------------------


async def test_the_start_path_logs_no_pack_text_and_no_question() -> None:
    """Two new log calls stand on this path (`config.py`, `session.py`) and both are new
    chances to log the thing that must never be logged.

    `knowledge._log_answer` is proven clean in its own suite; what is new here is a load
    step that HOLDS the whole corpus in a local variable and a resolution log line written
    for an operator. Ids, words and counts only.
    """
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    fetcher = CountingFetcher()
    digest = fetcher.hold(_pack(tenant_id, agent_id))
    config = make_config(tenant_id=tenant_id, agent_id=agent_id, knowledge_pack_sha256=digest)

    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink_log, level="DEBUG")
    try:
        _call, schema = await _open(config, fetcher=fetcher, cache=PackCache())
        payload = await invoke_tool(schema, "how much is a trouser alteration")
    finally:
        logger.remove(handler)

    assert payload["outcome"] == "found"
    blob = "\n".join(captured)
    assert blob, "nothing was logged at all, so this test proves nothing"
    for forbidden in (
        "how much is a trouser alteration",  # the caller's turn
        ALTERATION_FACT,  # a passage
        DELIVERY_FACT,  # a passage nobody even asked for
    ):
        assert forbidden not in blob
    # The ids an operator needs ARE there, or the log line is not worth its own risk.
    assert digest in blob and str(agent_id) in blob


# --------------------------------------------------------------------------------------
# 4. The real fetcher, against a store that is a dict.
# --------------------------------------------------------------------------------------


def _fetcher_over(client: Any, *, budget_s: float = 5.0) -> storage.ObjectStorePackFetcher:
    return storage.ObjectStorePackFetcher(bucket="calevate-test", client=client, budget_s=budget_s)


async def test_the_object_store_fetcher_answers_none_for_gone_and_raises_for_unreachable(
    s3: FakeS3,
) -> None:
    """The distinction the whole four-outcome design rests on, at the one place it is read
    off a vendor error code.

    `FakeS3` is the suite's own S3 double and raises the real `ClientError` shapes, so the
    codes being matched here are the codes botocore actually produces rather than strings
    this test invented.
    """
    pack = _pack(uuid.uuid4(), uuid.uuid4())
    key = pack_object_key(pack.tenant_id, pack.agent_id, pack.content_sha256)
    s3.objects[key] = pack.model_dump_json().encode()
    fetcher = _fetcher_over(s3)

    assert await fetcher.fetch(key) == s3.objects[key]
    assert await fetcher.fetch("knowledge-packs/nobody/nothing/deadbeef.json") is None

    s3.fail = True
    with pytest.raises(ClientError):
        await fetcher.fetch(key)


async def test_a_store_that_never_answers_is_bounded_and_becomes_temporarily_unavailable() -> None:
    """The bound that keeps a hung store from holding a caller in ringing forever.

    The budget is set to a few milliseconds here because what is under test is that a
    deadline EXISTS and that its expiry travels the same road as every other storage
    failure — `storage.PACK_FETCH_BUDGET_S` itself is an assumption stated in that module
    and is not a number this test could confirm.

    The blocked call is released in `finally`: a test that left a thread parked on an event
    for the life of the process would be trading a real resource for a passing assertion.
    """
    released = threading.Event()

    class HangingClient:
        def get_object(self, **_kwargs: Any) -> dict[str, Any]:
            released.wait(timeout=30)
            raise AssertionError("the fetch was supposed to be abandoned before this returned")

    fetcher = _fetcher_over(HangingClient(), budget_s=0.01)
    config = make_config(knowledge_pack_sha256="d" * 64)
    try:
        started = asyncio.get_running_loop().time()
        call, schema = await _open(config, fetcher=fetcher, cache=PackCache())
        waited = asyncio.get_running_loop().time() - started

        assert waited < 5.0, "the session waited on a store that was never going to answer"
        assert call.knowledge is not None
        assert call.knowledge.unavailable_reason == "fetch_failed"
        payload = await invoke_tool(schema, "when will my clothes be ready")
        assert payload["outcome"] == "temporarily_unavailable"
    finally:
        released.set()


def test_an_unconfigured_container_refuses_at_build_time_and_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deploy fault must fail where a human is looking, not once per call afterwards."""
    monkeypatch.delenv(storage.BUCKET_ENV, raising=False)
    monkeypatch.delenv(storage.ENDPOINT_ENV, raising=False)

    with pytest.raises(storage.ObjectStoreNotConfiguredError) as refusal:
        storage.ObjectStorePackFetcher.from_env()

    assert storage.BUCKET_ENV in str(refusal.value)
    assert storage.ENDPOINT_ENV in str(refusal.value)


# --------------------------------------------------------------------------------------
# 5. The config load, against the real database and the real policy.
# --------------------------------------------------------------------------------------


def _agent_config(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> AgentConfig:
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name="Sri Lakshmi Tailors receptionist",
        direction="inbound",
        language_primary="te-IN",
        system_prompt="You are the receptionist for Sri Lakshmi Tailors.",
        opening_line="Idi AI assistant. Ee call record avutundi.",
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v4",
            llm_provider="azure_openai",
            # The DEPLOYMENT id, not a model name — `ModelConfig.llm_model`'s own warning
            # about the Azure leg — and the base URL beside it, which that model requires
            # of this provider so an endpoint is never implied.
            llm_model="calevate-gpt-4o-mini",
            llm_base_url=azure_openai_base_url("calevate-eastus2"),
            tts_provider="sarvam",
            tts_model="bulbul:v3",
            tts_voice="anushka",
        ),
    )


async def _runtime_agent() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent has a published runtime row — the state a real call starts in.

    `PipecatEngine.create_agent` is what mints `agent_config_versions` and `pipecat_agents`,
    so the row under test is the one the control plane really writes rather than one this
    file inserted in the shape it hoped for.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))
    return tenant_id, agent_id


async def _publish_a_fact(tenant_id: uuid.UUID, agent_id: uuid.UUID, fact: str) -> None:
    """submit -> approve -> publish, which is the only path that writes the pack pointer."""
    async with tenant_session(tenant_id) as db:
        submitted = await kb_service.submit_source(
            db, tenant_id=tenant_id, agent_id=agent_id, name="Alterations", body=fact
        )
        await kb_service.approve_source(db, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            db, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )


async def test_the_digest_the_publish_wrote_is_the_digest_the_session_config_carries(
    s3: FakeS3,
    worker_token: None,
) -> None:
    """The half of the seam that crosses the database, with nothing hand-inserted.

    The pointer is written by `kb/pack.refresh_published_pack` on a real publish and read
    by `config.load_session_config`; this asserts they are the same value, and that the
    object that value names is really in the store — because a digest that reaches the
    worker and addresses nothing is the same outage as no digest at all, arriving by a
    longer road.
    """
    tenant_id, agent_id = await _runtime_agent()
    await _publish_a_fact(tenant_id, agent_id, ALTERATION_FACT)

    async with tenant_session(tenant_id) as db:
        stored = (
            await db.execute(
                text("SELECT knowledge_pack_sha256 FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    async with worker_client() as api:
        config = await load_session_config(
            api,
            call_id="call-db-1",
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
        )

    assert stored is not None, "the control failed: the publish wrote no pointer"
    assert config.knowledge_pack_sha256 == stored
    assert pack_object_key(tenant_id, agent_id, stored) in s3.objects

    # The rest of the row arrived too, because a config that carried only the digest would
    # close this seam and open a worse one.
    assert config.call_id == "call-db-1"
    assert config.tenant_id == tenant_id and config.agent_id == agent_id
    assert config.direction == "inbound"
    assert config.language == "te-IN"
    assert config.models.tts_model == "bulbul:v3"
    # §1.1: the worker's own recomputation agrees with the version it loaded. This is the
    # comparison the attestation is judged by, and it is meaningful only because the two
    # sides are computed independently.
    assert pipeline.recompute_prompt_sha256(config.system_prompt) == config.prompt_sha256


async def test_an_agent_that_has_published_nothing_loads_a_none_digest(
    s3: FakeS3,
    worker_token: None,
) -> None:
    """The ordinary day-one agent, from the database rather than from a fixture's default.

    Asserted against a REAL unpublished agent because `SessionConfig.knowledge_pack_sha256`
    defaults to `None` — a loader that forgot the column entirely would pass any test that
    built its config by hand.
    """
    tenant_id, agent_id = await _runtime_agent()

    async with worker_client() as api:
        config = await load_session_config(
            api,
            call_id="call-db-2",
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="outbound",
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
        )

    assert config.knowledge_pack_sha256 is None
    assert config.direction == "outbound", "the call's direction, not the agent's permission"


async def test_an_agent_with_no_runtime_row_is_refused_rather_than_assembled(
    s3: FakeS3,
    worker_token: None,
) -> None:
    """No version means no prompt, and no prompt means no truthful-answer floor.

    The one place on this path that raises. Assembling the call anyway would hand a live
    caller to a model running on the vendor's default system message, which is the single
    outcome hard rule 5 cannot tolerate.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))

    async with worker_client() as api:
        with pytest.raises(AgentNotRunnableError) as refusal:
            await load_session_config(
                api,
                call_id="call-db-3",
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
            )

    assert str(agent_id) in str(refusal.value)


@pytest.mark.rls
async def test_a_neighbour_cannot_load_this_agents_session_config(
    s3: FakeS3,
    worker_token: None,
) -> None:
    """Hard rule 1 at the worker's own read, which is a new reader of three tenant tables.

    The neighbour names A's agent explicitly — the query has A's ids in it — so what refuses
    is the policy and not the predicate. A leak here is not a screen with the wrong data on
    it: it is a worker that loads a neighbour's prompt, their model configuration and the
    pointer to their published knowledge, and then answers a phone with all three.
    """
    tenant_a, agent_a = await _runtime_agent()
    await _publish_a_fact(tenant_a, agent_a, ALTERATION_FACT)
    tenant_b, agent_b = await _runtime_agent()

    # B's ref, A's ids. The server resolves the TENANT from the ref and reads under its RLS,
    # so what comes back is B's agent — and `load_session_config` refuses the disagreement
    # rather than running A's prompt on B's call or the reverse.
    async with worker_client() as api:
        with pytest.raises(AgentNotRunnableError) as refusal:
            await load_session_config(
                api,
                call_id="call-db-4",
                tenant_id=tenant_a,
                agent_id=agent_a,
                direction="inbound",
                engine_agent_ref=engine_agent_ref_for(str(tenant_b), str(agent_b)),
            )
    assert str(tenant_a) in str(refusal.value)


async def test_start_session_loads_the_config_and_its_pack_in_one_call(
    s3: FakeS3,
    worker_token: None,
) -> None:
    """The entrypoint, whole: ids in, a call that can answer a question out.

    Everything above tests one half; this is the only assertion that the halves are joined,
    and it runs against the real database and a fetcher reading the object the publish
    really stored — so the digest in the row, the key in the bucket and the pack in memory
    are proven to be one fact rather than three that happen to agree.
    """
    tenant_id, agent_id = await _runtime_agent()
    await _publish_a_fact(tenant_id, agent_id, ALTERATION_FACT)
    fetcher = CountingFetcher(dict(s3.objects))

    async with worker_client() as api:
        call = await session.start_session(
            api,
            call_id="call-db-5",
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
            credentials=CREDENTIALS,
            transport=FakeTransport(),
            sink=RecordingSink(),
            fetcher=fetcher,
            cache=PackCache(),
        )

    assert call.knowledge is not None and call.knowledge.available
    tools = call.context.tools
    assert isinstance(tools, ToolsSchema)
    (schema,) = tools.standard_tools
    payload = await invoke_tool(schema, "how much is a trouser alteration")
    assert payload["outcome"] == "found"
    assert any(
        ALTERATION_FACT in str(passage["text"]) for passage in cast(list[Any], payload["passages"])
    )


async def test_a_bucket_that_is_not_there_is_an_outage_and_not_an_empty_knowledge_base() -> None:
    """`NoSuchBucket` is "we could not look", never "this client published nothing".

    `voice_worker.storage` states the contract itself — absent and unreachable "must not
    merge", because merging them "would tell an operator that a client had published
    nothing when in truth we could not reach the bucket". A bucket that does not exist is
    a DEPLOY fault: one misspelled `OBJECT_STORE_BUCKET` makes every call of every tenant
    on that container report the benign, permanent state, and the log line an operator
    reads then says the clients emptied their own knowledge bases.

    It is also the exact set `apps/workers/storage.read_kb_object` matches, which
    `_MISSING_CODES`' own comment claims parity with and did not have.
    """

    class NoBucket:
        def get_object(self, **_kwargs: Any) -> dict[str, Any]:
            raise ClientError(
                {"Error": {"Code": "NoSuchBucket", "Message": "no such bucket"}}, "GetObject"
            )

    fetcher = _fetcher_over(NoBucket())
    with pytest.raises(ClientError):
        await fetcher.fetch("knowledge-packs/t/a/" + "d" * 64 + ".json")

    config = make_config(knowledge_pack_sha256="d" * 64)
    call, _schema = await _open(config, fetcher=fetcher, cache=PackCache())
    assert call.knowledge is not None
    assert call.knowledge.unavailable_reason == "fetch_failed"


def test_the_pack_fetcher_retries_nothing_inside_its_wall_clock_budget() -> None:
    """`_client` says "no retry" and botocore's `max_attempts` does not mean that.

    VERIFIED-VENDOR-SPEC, botocore `config.py` as installed in this tree's own lockfile
    (read 14 Sep 2026): `max_attempts` is "the maximum number of RETRY attempts", so
    `max_attempts=1` buys one retry — two round trips, each with its own
    `PACK_FETCH_BUDGET_S` connect and read timeout, behind an `asyncio.timeout` that
    releases the caller after one. The await is bounded either way; the THREAD is not, and
    a thread parked on a second attempt holding a connection for the life of a hung socket
    is precisely what the comment above those timeouts says cannot happen.
    `total_max_attempts` is the key that means what was intended — the same page says it
    "includes the initial request, so a value of 1 indicates that no requests will be
    retried".
    """
    client = storage._client("http://localhost:9000")

    assert client.meta.config.retries["total_max_attempts"] == 1
