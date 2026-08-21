"""`VoiceEngine.get_agent` — the read-back, adapter by adapter.

The conformance suite (`packages/shared/tests/engine_conformance`) holds BOTH adapters
to the contract's behaviour. This file covers the two things a contract clause cannot:

* the `fake` adapter's read-back really tracking its own state (a read-back that agrees
  with the caller by construction measures nothing — OPERATIONS §2 gate 2);
* the `bolna` adapter's PARSER against the agent shapes its docstring says are guesses.
  Nothing here is evidence about Bolna: these payloads are hypotheses, and what is being
  tested is that the parser declines honestly when the shape is not the one we guessed,
  rather than reporting a confident empty answer (D-41).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.bolna import (
    BolnaEngine,
    _agent_greeting,
    _agent_kb_refs,
    _agent_models,
    _agent_object,
    _agent_system_prompt,
)
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_DIRECTIVE,
    AgentConfig,
    AgentSnapshot,
    KBSourceRef,
)


def _cfg(prompt: str = "You are the receptionist for Sunrise Clinic.") -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        system_prompt=prompt,
        opening_line="Idi AI assistant. Ee call record avutundi.",
    )


# --- fake ---------------------------------------------------------------------


async def test_fake_read_back_reflects_the_preceding_update() -> None:
    """The read-back tracks the STORE, not the last argument.

    Two writes to the same agent, and the second must be what comes back. A read-back
    that returned what it was handed most recently would also pass this — which is why
    the conformance suite additionally reads a second, untouched agent — but a read-back
    frozen at creation fails right here, and that is the other way to get this wrong.
    """
    engine = FakeEngine()
    ref = await engine.create_agent(_cfg("Receptionist, revision one."))
    assert (await engine.get_agent(ref)).carries_prompt_marker("revision one") is True

    await engine.update_agent(ref, _cfg("Receptionist, revision two."))
    snapshot = await engine.get_agent(ref)

    assert snapshot.carries_prompt_marker("revision two") is True
    assert snapshot.carries_prompt_marker("revision one") is False


async def test_fake_read_back_carries_the_opening_line_the_way_an_engine_holds_it() -> None:
    """Hard rule 5 is a property of the object the ENGINE holds, not of our config row.
    The fake renders it through `compose_engine_prompt`, exactly as
    `BolnaEngine._agent_body` does — opening line prepended, platform rules appended
    (D-163) — so a caller cannot write an equality check that only ever passes against
    the fake, and cannot get a fake-only agent that answers dishonestly."""
    engine = FakeEngine()
    cfg = _cfg()
    ref = await engine.create_agent(cfg)
    prompt = (await engine.get_agent(ref)).system_prompt
    assert prompt is not None
    assert prompt.startswith(cfg.opening_line)
    assert prompt.rstrip().endswith(TRUTHFUL_ANSWER_DIRECTIVE.rstrip())


async def test_fake_read_back_tracks_attach_and_detach() -> None:
    """D-41's instrument, exercised where an engine really does clear the reference."""
    engine = FakeEngine()
    ref = await engine.create_agent(_cfg())
    handle = await engine.attach_kb(ref, KBSourceRef(kb_id="kb_1", title="Fees", text="500"))
    assert (await engine.get_agent(ref)).references_kb(handle) is True

    await engine.detach_kb(ref, handle)
    assert (await engine.get_agent(ref)).references_kb(handle) is False


async def test_fake_refuses_to_describe_an_agent_it_never_created() -> None:
    engine = FakeEngine()
    with pytest.raises(ProblemError):
        await engine.get_agent("fakeagent_never_created")


# --- bolna: the parser, against SHAPES WE GUESSED ------------------------------


def test_agent_object_unwraps_their_documented_envelope() -> None:
    """`{"agent_id": ..., "data": {...}}` is the row shape their OSS `GET /all` is
    documented to use, and the id lives OUTSIDE `data` — losing it would make every
    read-back anonymous."""
    unwrapped = _agent_object({"agent_id": "agent_1", "data": {"agent_config": {"x": 1}}})
    assert unwrapped["agent_id"] == "agent_1"
    assert unwrapped["agent_config"] == {"x": 1}
    # An already-unwrapped object passes through untouched.
    assert _agent_object({"agent_config": {"x": 1}})["agent_config"] == {"x": 1}


def test_system_prompt_is_read_from_the_conversation_task() -> None:
    agent = {"agent_prompts": {"task_1": {"system_prompt": "hello"}, "task_2": {}}}
    assert _agent_system_prompt(agent) == "hello"


@pytest.mark.parametrize(
    "agent",
    [
        {},
        {"agent_prompts": {}},
        {"agent_prompts": {"task_2": {"system_prompt": "a"}, "task_3": {"system_prompt": "b"}}},
        {"agent_prompts": {"task_1": {"system_prompt": ""}}},
    ],
)
def test_an_unrecognised_prompt_shape_is_unreadable_not_empty(agent: dict[str, Any]) -> None:
    """None, never "". An empty string would flow into `system_prompt_readable=True` and
    let gate 2 report "the marker is absent" — i.e. blame the vendor for dropping a
    prompt — when the truth is that our field names are wrong. The ambiguous
    several-tasks case declines for the same reason: scoring a marker against an
    arbitrary task's prompt is a measurement of the wrong object."""
    assert _agent_system_prompt(agent) is None


def test_kb_refs_found_by_name_are_reported_as_readable() -> None:
    """The HYPOTHETICAL shape. If Bolna's agent object turns out to carry a `rag_id`
    anywhere in its nesting, this is what the adapter does with it — and the pilot is
    what decides whether that `if` is true (gate 8)."""
    agent = {
        "agent_config": {"tasks": [{"tools_config": {"rag": {"rag_id": "kb_42"}}}]},
    }
    handles, readable = _agent_kb_refs(agent)
    assert readable is True
    assert handles == ["kb_42"]


def test_a_present_but_empty_kb_field_is_an_answer() -> None:
    """ "The agent references nothing" is a real answer when the FIELD is there."""
    handles, readable = _agent_kb_refs({"agent_config": {"rag_ids": []}})
    assert readable is True
    assert handles == []


def test_no_kb_field_anywhere_is_declined_not_answered() -> None:
    """The distinction D-41 turns on. Reporting `readable=True, []` here would record
    'the deleted knowledge base left no dangling reference' on the strength of not
    having found the field that would say."""
    handles, readable = _agent_kb_refs({"agent_config": {"agent_name": "x", "tasks": []}})
    assert readable is False
    assert handles == []


# --- the greeting, which is the field that actually speaks (P3.3) --------------


def test_the_greeting_is_read_from_the_field_we_send_it_in() -> None:
    agent = {"agent_config": {"agent_welcome_message": "Idi AI assistant."}}
    greeting, readable = _agent_greeting(agent)
    assert (greeting, readable) == ("Idi AI assistant.", True)


def test_a_present_but_empty_greeting_is_an_answer_not_a_shrug() -> None:
    """THE DISTINCTION THIS READER'S `(value, readable)` PAIR EXISTS FOR, and the one a
    naive "empty means we could not read it" would erase.

    A vendor that stopped recognising the field, or an operator who blanked it in the
    vendor's own dashboard, leaves the key present and empty — and that agent OPENS THE
    CALL SAYING NOTHING, which is a provable hard rule 5 breach and the loudest failure on
    this path. Folding it into `readable=False` turns the one refusal `judge` can make on
    compliance grounds into a recorded uncertainty that does not block the publish.
    """
    greeting, readable = _agent_greeting({"agent_config": {"agent_welcome_message": ""}})
    assert readable is True, "the field WAS there — we read it, and it was empty"
    assert greeting == ""

    snapshot = AgentSnapshot(engine_agent_ref="r", greeting="", greeting_readable=True)
    assert snapshot.carries_greeting_marker("Idi AI assistant.") is False, (
        "an empty greeting must score FALSE — a publish is refused on this, and `None` "
        "would let it through as merely unconfirmed"
    )


def test_no_greeting_field_at_all_is_declined_rather_than_answered() -> None:
    """Our own adapter looking in the wrong place, which is not the vendor's failure and
    must never fail a publish. `_agent_kb_refs` makes the identical distinction for D-41
    and this follows it rather than inventing a second tri-state."""
    greeting, readable = _agent_greeting({"agent_config": {"agent_name": "x"}})
    assert (greeting, readable) == (None, False)

    snapshot = AgentSnapshot(engine_agent_ref="r", greeting=None, greeting_readable=False)
    assert snapshot.carries_greeting_marker("anything") is None


def test_a_non_string_greeting_is_read_as_empty_rather_than_trusted() -> None:
    """A vendor answering `null` under a key it still publishes has told us the agent
    holds no welcome message. That is the empty case, not the unreadable one."""
    greeting, readable = _agent_greeting({"agent_config": {"agent_welcome_message": None}})
    assert (greeting, readable) == ("", True)


# --- bolna: the round trip over a transport stub -------------------------------


def _engine(handler: Any) -> BolnaEngine:
    return BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai", transport=httpx.MockTransport(handler)
        ),
    )


async def test_bolna_read_back_maps_their_agent_object_into_ours() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/agent/agent_1", "the read-back must GET one agent"
        return httpx.Response(
            200,
            json={
                "agent_id": "agent_1",
                "data": {
                    "agent_config": {"agent_name": "Sunrise Clinic receptionist"},
                    "agent_prompts": {"task_1": {"system_prompt": "disclosure\n\nmarker-alpha"}},
                },
            },
        )

    snapshot = await _engine(handler).get_agent("agent_1")
    assert snapshot.engine == "bolna"
    assert snapshot.engine_agent_ref == "agent_1"
    assert snapshot.name == "Sunrise Clinic receptionist"
    assert snapshot.carries_prompt_marker("marker-alpha") is True
    # Their published documentation says nothing about the agent object holding a KB
    # reference, so a payload without one must DECLINE rather than report none.
    assert snapshot.knowledge_base_refs_readable is False
    assert snapshot.references_kb("kb_42") is None


async def test_bolna_read_back_of_an_unknown_agent_raises() -> None:
    """A 404 is the honest outcome of an endpoint path that is itself an unverified
    vendor claim — and it must reach the caller rather than become an empty snapshot."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    with pytest.raises(ProblemError):
        await _engine(handler).get_agent("agent_nope")


# --- Reconciliation against bolna-ai/bolna@cd2e192 (D-260) --------------------
#
# Unlike the hypothesis-shaped payloads above, these two pin shapes READ AT SOURCE in the
# OSS framework the hosted platform is built on. Evidence: docs/vendor/bolna/oss-harvest.md.


def test_the_agent_body_carries_the_toolchain_their_runtime_dereferences() -> None:
    """`Task.toolchain` has no default in `bolna/models.py`, and the runtime reads
    `task["toolchain"]["pipelines"]` with a bare subscript (`task_manager.py`, and
    `helpers/utils.py::get_required_input_types`).

    We were not sending it, so the agent we create is one their engine cannot start —
    and the pipeline list is also what declares this task consumes AUDIO, which is not
    something an engine can guess from the rest of the body.
    """
    body = BolnaEngine(api_key="k", fx_rate=Decimal("83.50"))._agent_body(_cfg())
    task = body["agent_config"]["tasks"][0]

    assert task["toolchain"] == {
        "execution": "parallel",
        "pipelines": [["transcriber", "llm", "synthesizer"]],
    }


def test_models_are_readable_when_tasks_come_back_at_the_root() -> None:
    """Their server stores `agent_config.model_dump()` and `GET /agent/{id}` returns THAT,
    so `tasks` arrives at the top level with no `agent_config` wrapper
    (`local_setup/quickstart_server.py`).

    `_agent_models` looked only inside the wrapper, so a perfectly readable agent reported
    `models_readable=False` — which the judge is required to treat as "we could not find
    the synthesizer", never as "no voice configured". Its two siblings `_agent_name` and
    `_agent_greeting` already fell back to the root; this one did not.
    """
    root_shaped: dict[str, Any] = {
        "agent_name": "Sunrise Clinic receptionist",
        "agent_welcome_message": "Idi AI assistant.",
        "tasks": [
            {
                "tools_config": {
                    "transcriber": {"provider": "sarvam", "model": "saaras:v3"},
                    "llm_agent": {"model": "sarvam-m"},
                    "synthesizer": {
                        "provider": "sarvam",
                        "provider_config": {"voice": "anushka"},
                    },
                }
            }
        ],
    }

    models, readable = _agent_models(_agent_object(root_shaped))

    assert readable is True
    assert models is not None
    assert models.stt_provider == "sarvam"
    assert models.stt_model == "saaras:v3"
    assert models.llm_model == "sarvam-m"
    assert models.tts_provider == "sarvam"
    assert models.tts_voice == "anushka"


def test_kb_refs_are_found_at_the_name_the_vendor_actually_documents() -> None:
    """THE SPELLING THAT WAS MISSING. `_AGENT_KB_REF_KEYS` shipped as five guesses under
    the premise that "nothing in their published documentation says the agent object
    carries one at all" — and their read schema does:
    `tools_config.llm_agent.llm_config` is a `KnowledgebaseAgent` whose
    `vector_store.provider_config` is a `LanceDbConfig` declaring `vector_id` and
    `vector_ids` (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:806-817,
    1164-1195`). Neither was in the set, so an agent that HAS a knowledge base read back
    `readable=False` — D-41's question answered "we could not find the field" from a
    payload that contained the answer.

    Nested at the vendor's own depth, wrapper included, because that is the other half of
    the same defect: the walk's bound landed exactly on the last dict it had to open.
    """
    agent = {
        "agent_config": {
            "tasks": [
                {
                    "tools_config": {
                        "llm_agent": {
                            "agent_type": "knowledgebase_agent",
                            "llm_config": {
                                "model": "gpt-4o-mini",
                                "vector_store": {
                                    "provider": "lancedb",
                                    "provider_config": {
                                        "vector_ids": [
                                            "3c90c3cc-0d44-4b50-8822-8dd25736052a",
                                            "4d91c4dd-1e55-5c61-9933-9ee36847163b",
                                        ]
                                    },
                                },
                            },
                        }
                    }
                }
            ]
        }
    }

    handles, readable = _agent_kb_refs(agent)

    assert readable is True
    assert handles == [
        "3c90c3cc-0d44-4b50-8822-8dd25736052a",
        "4d91c4dd-1e55-5c61-9933-9ee36847163b",
    ]


def test_the_legacy_single_vector_id_is_read_too() -> None:
    """Their own schema calls `vector_id` "legacy, use `vector_ids` for multiple" — which
    means accounts hold both, so both are read."""
    agent = {
        "tasks": [
            {
                "tools_config": {
                    "llm_agent": {
                        "llm_config": {
                            "vector_store": {"provider_config": {"vector_id": "kb-legacy-1"}}
                        }
                    }
                }
            }
        ]
    }

    handles, readable = _agent_kb_refs(agent)

    assert readable is True
    assert handles == ["kb-legacy-1"]


def test_the_conversation_task_decides_the_models_not_the_first_task() -> None:
    """Every task carries its OWN required `tools_config`
    (`api-reference/agent/v2/get.md:201-243`), and `task_type` is an enum of
    `conversation`/`extraction`/`summarization`. `_agent_models` took `tasks[0]`, so a
    console-added extraction task landing first made the read-back report the extraction
    leg's model and voice as the ones the CALLER is hearing — `readable=True` beside a
    wrong answer, which this function's docstring names as the outcome it must never
    produce.
    """
    agent: dict[str, Any] = {
        "tasks": [
            {
                "task_type": "extraction",
                "tools_config": {
                    "transcriber": {"provider": "deepgram", "model": "nova-2"},
                    "llm_agent": {"llm_config": {"model": "gpt-4o"}},
                    "synthesizer": {"provider": "polly", "provider_config": {"voice": "Aditi"}},
                },
            },
            {
                "task_type": "conversation",
                "tools_config": {
                    "transcriber": {"provider": "sarvam", "model": "saaras:v3"},
                    "llm_agent": {"llm_config": {"model": "sunrise-gpt-4o-mini"}},
                    "synthesizer": {"provider": "sarvam", "provider_config": {"voice": "anushka"}},
                },
            },
        ]
    }

    models, readable = _agent_models(agent)

    assert readable is True
    assert models is not None
    assert models.llm_model == "sunrise-gpt-4o-mini"
    assert models.tts_voice == "anushka"
    assert models.stt_model == "saaras:v3"


def test_a_task_list_that_names_no_types_still_reads_the_first_one() -> None:
    """The fallback, unchanged: where nothing declares a `task_type` the first task is the
    only guess available, and `readable` is the honest part of the answer. This is every
    agent `_agent_body` publishes, so the clause above changes nothing for them."""
    agent: dict[str, Any] = {
        "tasks": [
            {
                "tools_config": {
                    "transcriber": {"provider": "sarvam", "model": "saaras:v3"},
                    "llm_agent": {"llm_config": {"model": "only-task"}},
                    "synthesizer": {"provider": "sarvam", "provider_config": {"voice": "anushka"}},
                }
            }
        ]
    }

    models, readable = _agent_models(agent)

    assert readable is True
    assert models is not None
    assert models.llm_model == "only-task"
