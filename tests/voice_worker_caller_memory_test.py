"""A returning caller is recognised on the Pipecat leg — and a stranger is not, on any leg.

**WHAT THIS FILE IS TRYING TO CATCH.** Caller memory shipped complete for the RENTED
engine: the store, the keyed subject ref, both erasure arms, the 180-day clock, the spoken
notice and the hourly distiller all exist and have their own suites
(`tests/caller_memory_test.py`, `retention_caller_memory_test.py`,
`caller_memory_erasure_guard_test.py`, `caller_memory_notice_test.py`,
`caller_chunks_rls_test.py`). On that leg the ENGINE substitutes `CALLER_MEMORY_SLOT` per
call. `owned_runtime` has no engine, and `assemble_call` handed `config.system_prompt` to
the model verbatim — so a memory-enabled agent on this worker recalled nothing AND read the
literal `{caller_memory}` token as part of its instructions. No error, no alarm, in the
agent's own voice, on a live call. Every assertion here is about that wiring:

1. **the notice gate**, which is the reason this feature is shippable at all: the slot is
   in a prompt if and only if the agent's opening line carries the sentence that tells the
   caller notes are kept, so a worker that gates on the slot cannot remember for an agent
   that promised nothing — and it does not even send the number;
2. **the placeholder never survives**, with facts, without facts, and after a failure;
3. **the attested digest is still taken over the UNFILLED prompt**, because
   `agents/config_versions.py` puts `caller_memory` out of `prompt_sha256` by name and a
   worker that hashed what it filled would mismatch on every call;
4. **the read never extends a turn**: it is spent on the ring, concurrently with the pack,
   and a store that stops talking costs the budget and then nothing;
5. **hard rule 6**: the caller's number and the facts about them are in no log line.

The fixture caller rang a tailoring shop about an alteration. Small-business, boring, and
nothing here is clinical — `SPDI_REFUSED_VERTICALS` refuses that vertical outright, so a
clinic fixture would prove the store refuses rather than that this seam works.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
from calevate_shared.engine import (
    CALLER_MEMORY_SLOT,
    CALLER_MEMORY_VARIABLE,
    AgentConfig,
    ModelConfig,
    awaits_caller_memory,
    azure_openai_base_url,
    compose_engine_prompt,
    fill_caller_memory_slot,
    render_caller_memory,
)
from loguru import logger
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.voice_worker_pipeline_test import (
    CREDENTIALS,
    FakeTransport,
    RecordingSink,
    make_config,
)
from tests.worker_api_harness import worker_client
from voice_worker import memory, pipeline, session
from voice_worker.config import load_session_config

pytestmark = pytest.mark.anyio

#: The number the fixture caller rings from, and the one string that must never be logged.
CALLER = "+919876543210"

#: What an earlier call taught us. A distilled FACT and not a quote — `compliance/
#: caller_memory.py` §2 — so it is also the right shape to assert is absent from a log.
ALTERATION_MEMORY = "Asked about trouser alteration prices and pickup time."
PICKUP_MEMORY = "Prefers to be called after 8pm."


# --------------------------------------------------------------------------------------
# Fixtures: prompts as the control plane really composes them, and readers that fail.
# --------------------------------------------------------------------------------------


def _agent_config(*, remembers: bool) -> AgentConfig:
    """One agent, composed through the REAL composer, with memory on or off.

    `opening_line` carries the three sentences `compose_opening_line` produces, and the
    third of them is the memory notice — which is why the notice assertion below can be
    made against the same object the slot assertion is made against.
    """
    return AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Sri Lakshmi Tailors receptionist",
        direction="inbound",
        language_primary="te-IN",
        system_prompt="You are the receptionist for Sri Lakshmi Tailors.",
        opening_line=(
            "Idi AI assistant. Ee call record avutundi. "
            "Mee tho matladina vishayalu note chesukuntam."
            if remembers
            else "Idi AI assistant. Ee call record avutundi."
        ),
        caller_memory_enabled=remembers,
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v4",
            llm_provider="azure_openai",
            llm_model="calevate-gpt-4o-mini",
            llm_base_url=azure_openai_base_url("calevate-eastus2"),
            tts_provider="cartesia",
            tts_model="sonic-3.5",
            tts_voice="anushka",
        ),
    )


def _config(*, remembers: bool, **overrides: Any) -> pipeline.SessionConfig:
    """A `SessionConfig` whose prompt is what a publish would really have minted.

    The prompt is NOT hand-written here, and that is the point of the helper: this file's
    whole argument is about a token the composer leaves behind, so a fixture that typed the
    token itself would pass while the composer stopped emitting it.
    """
    cfg = _agent_config(remembers=remembers)
    prompt = compose_engine_prompt(cfg)
    base: dict[str, Any] = {
        "system_prompt": prompt,
        "prompt_sha256": pipeline.recompute_prompt_sha256(prompt),
        "engine_agent_ref": f"pipecat:{cfg.tenant_id}:{cfg.agent_id}",
    }
    base.update(overrides)
    return make_config(**base)


class RecordingReader:
    """A `CallerMemoryReader` that answers a fixed list and records what it was asked.

    The ASK LIST is the instrument for the gate: "an agent that does not remember never
    sends the number" is a statement about how many times this was called, and asserting it
    any other way would be asserting a proxy.
    """

    def __init__(self, facts: tuple[str, ...] = ()) -> None:
        self.facts = facts
        self.asked: list[tuple[str, str]] = []

    async def recall(self, *, engine_agent_ref: str, phone_e164: str) -> tuple[str, ...]:
        self.asked.append((engine_agent_ref, phone_e164))
        return self.facts


class SilentFetcher:
    """A `PackFetcher` for an agent with no pack. Never asked, because the digest is None."""

    async def fetch(self, object_key: str) -> bytes | None:
        raise AssertionError("an agent with no digest must never produce an object key")


async def _open(
    config: pipeline.SessionConfig,
    *,
    reader: memory.CallerMemoryReader | None = None,
    caller_e164: str | None = CALLER,
    fetcher: Any = None,
) -> pipeline.AssembledCall:
    """Start a session the way the entrypoint will, and hand back the assembled call."""
    return await session.open_session(
        config=config,
        credentials=CREDENTIALS,
        transport=FakeTransport(),
        sink=RecordingSink(),
        fetcher=SilentFetcher() if fetcher is None else fetcher,
        memory_reader=reader,
        caller_e164=caller_e164,
    )


def _system_message(call: pipeline.AssembledCall) -> str:
    (first,) = [m for m in call.context.get_messages() if m.get("role") == "system"]
    return str(first["content"])


# --------------------------------------------------------------------------------------
# 1. The notice gate: the slot and the spoken sentence are one condition, not two.
# --------------------------------------------------------------------------------------


def test_the_slot_is_present_exactly_when_the_agent_says_it_keeps_notes() -> None:
    """THE PROPERTY THE WORKER'S GATE RESTS ON, asserted rather than assumed.

    `awaits_caller_memory` is a compliance gate wearing a rendering predicate's clothes: it
    is trusted to mean "this agent already told the caller". That is only true because
    `_caller_memory_section` and `compose_opening_line` are driven by the SAME flag. If a
    future edit gives the memory section a switch of its own, this test is what fails —
    before a caller is remembered without having been told.
    """
    remembering = _agent_config(remembers=True)
    silent = _agent_config(remembers=False)

    assert awaits_caller_memory(compose_engine_prompt(remembering))
    assert remembering.opening_line.endswith("note chesukuntam.")

    assert not awaits_caller_memory(compose_engine_prompt(silent))
    assert "note chesukuntam" not in silent.opening_line


async def test_an_agent_that_does_not_remember_never_sends_the_number() -> None:
    """No slot, no request — the gate is on the door that transmits, not on the answer.

    A worker that asked first and discarded the answer would put a caller's phone number on
    the wire for an agent whose client never switched the feature on and whose caller was
    never told anything. The empty `asked` list is the whole assertion.
    """
    reader = RecordingReader(facts=(ALTERATION_MEMORY,))

    call = await _open(_config(remembers=False), reader=reader)

    assert reader.asked == []
    assert CALLER_MEMORY_SLOT not in _system_message(call)
    # And nothing was APPENDED either: an agent with no memory section must not acquire one.
    assert "WHAT YOU REMEMBER ABOUT THIS CALLER" not in _system_message(call)


async def test_an_agent_that_remembers_asks_with_its_own_ref_and_the_caller() -> None:
    """The happy path, through `open_session`, which is what a real call will run."""
    config = _config(remembers=True)
    reader = RecordingReader(facts=(ALTERATION_MEMORY, PICKUP_MEMORY))

    call = await _open(config, reader=reader)

    assert config.engine_agent_ref is not None
    assert reader.asked == [(config.engine_agent_ref, CALLER)]
    spoken = _system_message(call)
    assert ALTERATION_MEMORY in spoken and PICKUP_MEMORY in spoken
    assert CALLER_MEMORY_SLOT not in spoken


@pytest.mark.parametrize(
    ("reader", "caller"),
    [
        (None, CALLER),
        (RecordingReader(), None),
    ],
    ids=["no-reader-wired", "no-number-on-this-call"],
)
async def test_a_deployment_that_cannot_ask_still_empties_the_slot(
    reader: memory.CallerMemoryReader | None, caller: str | None
) -> None:
    """The two states that are NOT the feature being off, and both must still substitute.

    A container with no reader wired (every test, every local run, and any deploy before the
    bootstrap lands) and a call with no number (the carrier leg is BLOCKER-1) are ordinary
    and permanent. Leaving the token in either case would hand the model a placeholder for
    the life of that deployment — which is the defect this whole file exists for, arriving
    by a quieter road than the one that was fixed.
    """
    call = await _open(_config(remembers=True), reader=reader, caller_e164=caller)

    spoken = _system_message(call)
    assert CALLER_MEMORY_SLOT not in spoken
    assert CALLER_MEMORY_VARIABLE not in spoken
    # The SECTION stays, because the agent does remember callers and said so — it is simply
    # empty, which `CALLER_MEMORY_GUIDANCE` already tells the model means a caller it does
    # not know.
    assert "WHAT YOU REMEMBER ABOUT THIS CALLER" in spoken


async def test_a_first_time_caller_gets_the_section_with_nothing_in_it() -> None:
    """An empty recall is not a failure and must not read like one."""
    call = await _open(_config(remembers=True), reader=RecordingReader(facts=()))

    spoken = _system_message(call)
    assert CALLER_MEMORY_SLOT not in spoken
    assert "If there are no notes below, this is a caller you do not know." in spoken


# --------------------------------------------------------------------------------------
# 2. The attestation: what is hashed is what was published, not what was filled.
# --------------------------------------------------------------------------------------


async def test_the_attested_digest_is_taken_over_the_prompt_the_publish_minted() -> None:
    """§1.1's witness survives the substitution, which is why the fill is not in the digest.

    `agents/config_versions.prompt_digest` omits `caller_memory` by name — "facts about ONE
    caller, assembled per session; in the digest, every attestation would mismatch". So the
    worker must hash `config.system_prompt` and hand the model something else. A single
    `recompute_prompt_sha256(spoken_prompt)` would turn every remembered caller into a
    fleet-wide attestation mismatch, which reads exactly like a tampered prompt.
    """
    config = _config(remembers=True)

    call = await _open(config, reader=RecordingReader(facts=(ALTERATION_MEMORY,)))

    assert call.prompt_matches_config_version
    assert call.observed_prompt_sha256 == config.prompt_sha256
    assert ALTERATION_MEMORY in _system_message(call)
    assert ALTERATION_MEMORY not in config.system_prompt, "the attested artefact was edited"


def test_the_filler_is_shared_with_the_composer_and_is_idempotent_on_a_filled_prompt() -> None:
    """ONE filler, two callers (composition time and session time), one rendering.

    The second assertion is the one worth having: a prompt that has already been filled has
    no slot left, so a second pass cannot append, duplicate or overwrite what the first one
    put there. That is what makes it safe for `assemble_call` to run unconditionally.
    """
    once = fill_caller_memory_slot(
        compose_engine_prompt(_agent_config(remembers=True)), (PICKUP_MEMORY,)
    )
    twice = fill_caller_memory_slot(once, (ALTERATION_MEMORY,))

    assert render_caller_memory((PICKUP_MEMORY,)) in once
    assert twice == once
    assert ALTERATION_MEMORY not in twice


# --------------------------------------------------------------------------------------
# 3. The budget: spent on the ring, concurrently, and never on a turn.
# --------------------------------------------------------------------------------------


async def test_a_store_that_stops_talking_costs_the_budget_and_then_nothing() -> None:
    """The real reader against a transport that hangs. The call is assembled anyway.

    `httpx` raises `ReadTimeout` at the budget; the reader answers `()`; assembly finishes
    and the agent greets a returning caller as a stranger. The alternative — letting it
    raise — is a call that never connects because a nicety could not be fetched, which is
    the trade `caller_data_routes.py` refuses one hop away.
    """
    budget = 0.05

    async def hangs(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(budget * 40)
        raise AssertionError("the budget did not fire")

    reader = memory.ApiCallerMemoryReader(
        client=httpx.AsyncClient(transport=httpx.MockTransport(hangs)),
        base_url="https://api.calevate.test",
        token="token-under-test",
        engine=pipeline.ENGINE_NAME,
        budget_s=budget,
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    facts = await reader.recall(engine_agent_ref="pipecat:t:a", phone_e164=CALLER)
    elapsed = loop.time() - started

    assert facts == ()
    # THE READ IS TIMED AND THE ASSEMBLY IS NOT, deliberately: `assemble_call` constructs the
    # vendor legs and loads an ONNX turn model, which is seconds of one-off work on a cold
    # process and has nothing to do with the bound under test. Generous even so, because this
    # asserts the bound EXISTS rather than that the machine is fast — with no timeout the
    # handler above sits here for two seconds, not for a tenth of one.
    assert elapsed < budget * 20, "the read was not bounded by its own budget"

    # And the call is still assembled and still speaks, which is the half that matters to a
    # caller: a nicety we could not fetch must not be a call that does not connect.
    call = await _open(_config(remembers=True), reader=reader)
    assert CALLER_MEMORY_SLOT not in _system_message(call)


async def test_the_pack_and_the_memory_are_read_at_the_same_time() -> None:
    """Their budgets must not add, and this proves overlap rather than timing it.

    A stopwatch assertion here would be a speed-dependent test (D-29 exists because of nine
    of those), so each side signals that it has STARTED and then waits for the other. Run
    concurrently, both arrive and pass. Run in sequence, the first waits for a signal that
    cannot come until it returns, and the wait expires — deterministically, on any machine.
    """
    pack_started, memory_started = asyncio.Event(), asyncio.Event()

    async def meet(mine: asyncio.Event, theirs: asyncio.Event) -> bool:
        mine.set()
        try:
            await asyncio.wait_for(theirs.wait(), 1.0)
        except TimeoutError:
            return False
        return True

    overlapped: dict[str, bool] = {}

    class MeetingFetcher:
        async def fetch(self, object_key: str) -> bytes | None:
            overlapped["pack"] = await meet(pack_started, memory_started)
            return None

    class MeetingReader:
        async def recall(self, *, engine_agent_ref: str, phone_e164: str) -> tuple[str, ...]:
            overlapped["memory"] = await meet(memory_started, pack_started)
            return ()

    await _open(
        _config(remembers=True, knowledge_pack_sha256="a" * 64),
        reader=MeetingReader(),
        fetcher=MeetingFetcher(),
    )

    assert overlapped == {"pack": True, "memory": True}, (
        "the two reads ran in sequence, so the worst-case ring silence is the SUM of "
        "PACK_FETCH_BUDGET_S and MEMORY_FETCH_BUDGET_S rather than the larger of them"
    )


# --------------------------------------------------------------------------------------
# 4. Hard rule 6.
# --------------------------------------------------------------------------------------


async def test_nothing_on_this_path_logs_the_number_or_what_we_remember() -> None:
    """The number is the natural key of this whole feature and is never a log field.

    Both halves are asserted because they fail separately: the NUMBER would leak from the
    reader (a retry line, an error body) and the FACTS would leak from session assembly (a
    "resolved" line that helpfully included what it resolved).
    """
    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    config = _config(remembers=True)
    handler = logger.add(sink_log, level="DEBUG")
    try:
        call = await _open(config, reader=RecordingReader(facts=(ALTERATION_MEMORY,)))
    finally:
        logger.remove(handler)

    assert ALTERATION_MEMORY in _system_message(call), "the control failed: nothing was recalled"
    blob = "\n".join(captured)
    assert blob, "nothing was logged at all, so this test proves nothing"
    assert CALLER not in blob
    assert "9876543210" not in blob, "the number leaked without its country code"
    assert ALTERATION_MEMORY not in blob
    # The ids and the COUNT an operator needs are there, or the log line is not worth its
    # own risk: "this agent remembers and recalled one thing" is the only way to tell a
    # feature doing nothing from a token that stopped working.
    assert str(config.agent_id) in blob and "'remembers': 1" in blob


async def test_a_failing_read_logs_a_type_and_never_the_request_it_made() -> None:
    """A provider's error body quotes the request, and this request carries the number."""
    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    def refuses(request: httpx.Request) -> httpx.Response:
        # A 500 whose body echoes the query string, which is how the number would escape.
        return httpx.Response(500, text=f"upstream failed for {request.url}")

    reader = memory.ApiCallerMemoryReader(
        client=httpx.AsyncClient(transport=httpx.MockTransport(refuses)),
        base_url="https://api.calevate.test",
        token="token-under-test",
        engine=pipeline.ENGINE_NAME,
    )

    handler = logger.add(sink_log, level="DEBUG")
    try:
        facts = await reader.recall(engine_agent_ref="pipecat:t:a", phone_e164=CALLER)
    finally:
        logger.remove(handler)

    assert facts == ()
    blob = "\n".join(captured)
    assert "HTTPStatusError" in blob, "the failure was not reported to an operator at all"
    assert CALLER not in blob and "9876543210" not in blob
    assert "token-under-test" not in blob


# --------------------------------------------------------------------------------------
# 5. The wire shape, against the renderer that actually produces it.
# --------------------------------------------------------------------------------------


async def test_the_reader_parses_exactly_what_the_endpoint_renders() -> None:
    """Round trip through `render_caller_memory`, not through a hand-typed body.

    The endpoint answers `{caller_memory: render_caller_memory(facts)}`, so a fixture body
    typed by hand would pin this file's guess at the wire rather than the wire.
    """
    facts = (ALTERATION_MEMORY, PICKUP_MEMORY)
    seen: dict[str, Any] = {}

    def answers(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={CALLER_MEMORY_VARIABLE: render_caller_memory(facts)})

    reader = memory.ApiCallerMemoryReader(
        client=httpx.AsyncClient(transport=httpx.MockTransport(answers)),
        base_url="https://api.calevate.test/",
        token="token-under-test",
        engine=pipeline.ENGINE_NAME,
    )

    assert await reader.recall(engine_agent_ref="pipecat:t:a", phone_e164=CALLER) == facts
    assert f"{memory.CALLER_DATA_PATH}/{pipeline.ENGINE_NAME}" in seen["url"]
    assert seen["auth"] == "Bearer token-under-test"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"caller_memory": ""},
        {"something_else": "x"},
        [],
        "not-json-object",
        {"caller_memory": 7},
    ],
    ids=["empty-object", "empty-block", "other-key", "a-list", "a-string", "wrong-type"],
)
async def test_every_shape_that_is_not_an_answer_is_the_same_silence(body: Any) -> None:
    """`{}` is the endpoint's own fail-open and its first-time-caller answer alike.

    They must not be told apart HERE: the endpoint deliberately renders both as `{}` so a
    reader cannot start treating "we could not look" as a state worth telling a caller
    about, and this asserts no branch here reintroduces the distinction.
    """
    reader = memory.ApiCallerMemoryReader(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=body))
        ),
        base_url="https://api.calevate.test",
        token="token-under-test",
        engine=pipeline.ENGINE_NAME,
    )

    assert await reader.recall(engine_agent_ref="pipecat:t:a", phone_e164=CALLER) == ()


# --------------------------------------------------------------------------------------
# 6. The handle, out of the real database through the real policy.
# --------------------------------------------------------------------------------------


async def test_the_ref_the_publish_wrote_is_the_ref_the_session_config_carries(
    worker_token: None,
) -> None:
    """`engine_agent_ref` is READ and not rebuilt, so the read has to actually happen.

    The worker could compose `pipecat:<tenant>:<agent>` in one line; it does not, because
    `engine/pipecat.engine_agent_ref_for` is that string's author and this container may not
    import the monolith. What replaces the import is this column — and a column nobody reads
    is the defect CLAUDE.md names by hand, so the read is asserted against what the control
    plane really wrote rather than against a fixture's hope.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await PipecatEngine().create_agent(
        AgentConfig(
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
                llm_model="calevate-gpt-4o-mini",
                llm_base_url=azure_openai_base_url("calevate-eastus2"),
                tts_provider="cartesia",
                tts_model="sonic-3.5",
                tts_voice="anushka",
            ),
        )
    )

    async with tenant_session(tenant_id) as db:
        stored = (
            await db.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    async with worker_client() as api:
        config = await load_session_config(
            api,
            call_id="call-memory-1",
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
        )

    assert stored, "the control failed: the fixture published no ref"
    assert config.engine_agent_ref == stored
    # This tenant is a clinic, which `SPDI_REFUSED_VERTICALS` refuses outright, so its agent
    # carries no memory section at all — the store's refusal and the worker's gate agreeing
    # on one agent, which is the seam this file's first test proves in the abstract.
    assert not awaits_caller_memory(config.system_prompt)
