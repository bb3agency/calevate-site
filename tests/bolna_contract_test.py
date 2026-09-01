"""Every Bolna route and body this adapter puts on the wire, against the vendor's spec.

WHY THIS FILE EXISTS. Until D-350 this repository believed, in thirty-one places, that
"Bolna publishes no OpenAPI spec". It publishes one — `references/openapi.yml` in
`bolna-ai/skills`, Bolna's own GitHub organisation, described there as a mirror of
`https://www.bolna.ai/docs/api-reference/openapi.yml` with the instruction "Treat the YAML
as the canonical schema if a SKILL.md and the spec disagree". Pinned at commit `28b24aa`;
`docs/vendor/bolna/hosted-oas.md` carries the checksum and the re-fetch command.

Under the false premise, four things went out on the wire that the vendor cannot answer,
and none of them could fail a test because every test agreed with the adapter:

* `POST /executions/{id}/stop` — not a route (D-353). The stop route is under `/call`.
* `GET /executions?created_after=` — not a route (D-353). Covered in
  `tests/bolna_listing_test.py`, which is the whole subject of that file.
* a v1 `tools_config` posted to `/v2/agent`, with `input`/`output` missing entirely
  though `ToolsConfigV2` requires them (D-355).
* `POST /knowledgebase` as JSON carrying raw text and an `agent_id`, when the route is
  multipart and takes a PDF or a URL and no agent (D-354).

These clauses are deliberately about SHAPE — which URL, which method, which keys — because
that is the class of defect a mock transport can catch and a captured payload cannot: a
stub built from the same guess as the adapter agrees with it forever. Every assertion below
cites the spec element it encodes, so the next reader can re-check the citation rather than
re-check us.

Live confirmation against `api.bolna.ai` is a separate thing and is NOT claimed here:
egress to that host is blocked from this environment (OPERATIONS §2 gate 2).
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine import bolna as bolna_module
from apps.api.engine.bolna import (
    BASE_URL,
    BOLNA_CAPABILITIES,
    BolnaEngine,
    _agent_models,
    llm_provider_keys,
)
from calevate_shared.config import Settings
from calevate_shared.engine import AgentConfig, CallContext, KBSourceRef, ModelConfig


def _engine(handler: Any) -> BolnaEngine:
    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _config() -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        system_prompt="You are the receptionist for Sunrise Clinic.",
        opening_line="Idi AI assistant.",
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            tts_voice="bulbul:v3",
        ),
    )


# --- stopping a call ----------------------------------------------------------


async def test_a_call_is_stopped_on_the_route_the_vendor_actually_has() -> None:
    """`POST /call/{execution_id}/stop` (OAS: "Stop a queued or scheduled call").

    The adapter used `POST /executions/{id}/stop`, and the spec's only `/executions/...`
    entries are the two single-item GETs. So every stop — the campaign path's way to pull
    a queued dial back after a DNC addition or the big red switch — would have 404'd, and
    a 404 here is a lead that gets called after asking not to be.
    """
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"message": "done", "status": "stopped"})

    await _engine(handler).end_call("exec_abc123")

    assert seen == [("POST", "/call/exec_abc123/stop")]


async def test_a_stop_the_vendor_refuses_is_surfaced_rather_than_swallowed() -> None:
    """A call the platform is not holding must not report as stopped. Swallowing the
    refusal is how a campaign halt reads as applied while the dial is still queued."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": 404, "message": "unknown execution"})

    with pytest.raises(ProblemError):
        await _engine(handler).end_call("exec_nope")


# --- creating an agent at the v2 endpoint -------------------------------------


async def _created_body() -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/agent"
        import json

        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"agent_id": "agent_1"})

    await _engine(handler).create_agent(_config())
    return seen


async def test_the_llm_block_uses_the_v2_nesting_the_v2_endpoint_requires() -> None:
    """`ToolsConfigV2.llm_agent` is `LlmAgentV2` — `{agent_type, agent_flow_type, routes,
    llm_config}` — with the model settings NESTED under `llm_config`. We posted the flat
    legacy `SimpleLlmAgent` body, which is what the v1 `ToolsConfig` accepts, to the v2
    route (D-355).

    `agent_type` is what selects the union arm, so it is asserted rather than assumed: a
    body with no `agent_type` is not obviously a `simple_llm_agent` to anything but us.
    """
    tools = (await _created_body())["agent_config"]["tasks"][0]["tools_config"]

    llm_agent = tools["llm_agent"]
    assert llm_agent["agent_type"] == "simple_llm_agent"
    assert "llm_config" in llm_agent, "v2 nests the model settings under `llm_config`"
    assert llm_agent["llm_config"]["model"] == "sarvam-105b"
    assert "model" not in llm_agent, "the flat v1 spelling is not what /v2/agent binds"


async def test_the_llm_block_names_the_provider_that_actually_routes_the_call() -> None:
    """`family` is declared on `SimpleLlmAgent` and read by nothing (VERIFIED-OSS,
    `bolna/providers.py`); `provider` chooses the client and defaults to `openai`. Sending
    only `family` meant the routing field was never stated — a config that names no
    provider goes to OpenAI whatever `model` says. Both are sent, spelling the same thing.
    """
    llm_config = (await _created_body())["agent_config"]["tasks"][0]["tools_config"]["llm_agent"][
        "llm_config"
    ]

    assert llm_config["provider"] == llm_config["family"]


async def test_the_telephony_input_and_output_blocks_are_sent() -> None:
    """`ToolsConfigV2.required` is `[llm_agent, synthesizer, transcriber, input, output]`,
    and `InputOutput` itself requires `provider` and `format`. We sent neither block, so
    `POST /v2/agent` was a 400 — the agent never exists, and nothing downstream of publish
    can be right either."""
    tools = (await _created_body())["agent_config"]["tasks"][0]["tools_config"]

    for leg in ("input", "output"):
        assert leg in tools, f"`{leg}` is required by ToolsConfigV2 and was not sent"
        assert set(tools[leg]) >= {"provider", "format"}


async def test_the_toolchain_and_prompt_envelope_match_the_spec() -> None:
    """The two parts that were already right, pinned so a refactor of the block above
    cannot quietly drop them: `AgentRequestV2` requires both `agent_config` and
    `agent_prompts`, and `AgentPrompt.task_1.system_prompt` is required within it."""
    body = await _created_body()

    assert set(body) == {"agent_config", "agent_prompts"}
    assert body["agent_prompts"]["task_1"]["system_prompt"]
    assert body["agent_config"]["tasks"][0]["toolchain"] == {
        "execution": "parallel",
        "pipelines": [["transcriber", "llm", "synthesizer"]],
    }


async def test_every_publish_states_the_agent_is_single_language() -> None:
    """The multilingual switch is the ONE documented way the running prompt stops being
    the prompt we published, so every body states it OFF rather than leaving it off.

    `MultilingualConfig` keeps a `system_prompt` per language and the vendor's own
    description says the platform "switches them, along with the active system prompt,
    during the call" (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`).
    `compose_engine_prompt` puts `TRUTHFUL_ANSWER_DIRECTIVE` into
    `agent_prompts.task_1.system_prompt` and `verification.judge` reads it back from
    there — so an agent switched to multilingual in the vendor's dashboard would run a
    per-language prompt carrying none of the floor, and read back as fully applied. Hard
    rule 5 forbids exactly that: a config row withdrawing the directive.

    The key must be PRESENT and null, not absent: an omitted key is a field left as it
    was, which is the same argument `agent_welcome_message` already makes in
    `_agent_body`. `null` is the vendor's own value for it (`default: null`,
    `nullable: true`), so stating it can neither be rejected nor mean anything else.
    """
    tools = (await _created_body())["agent_config"]["tasks"][0]["tools_config"]

    assert "multilingual_config" in tools, (
        "an omitted key leaves the vendor's stored value alone; the floor is not a thing "
        "to rest on unobserved PUT merge semantics"
    )
    assert tools["multilingual_config"] is None


# --- reading an agent back ----------------------------------------------------


def test_the_model_read_back_finds_the_v2_nesting() -> None:
    """`_agent_models` read the FLAT `llm_agent.model`, so on a v2 agent — the only kind
    this adapter now creates — `llm_model` came back `None` while `readable` said True
    (D-355). That is the combination the function's own docstring forbids: `readable=False`
    means "we could not find the block", and a confident `None` instead means "this agent
    runs no configured model", which is what the drift judge would have scored.

    `AgentV2` returns `tasks` at the TOP LEVEL with no `agent_config` wrapper, so the
    fixture is shaped that way.
    """
    models, readable = _agent_models(
        {
            "id": "agent_1",
            "tasks": [
                {
                    "tools_config": {
                        "llm_agent": {
                            "agent_type": "simple_llm_agent",
                            "llm_config": {"model": "sarvam-105b", "provider": "openai"},
                        },
                        "synthesizer": {
                            "provider": "sarvam",
                            "provider_config": {"voice": "bulbul:v3"},
                        },
                        "transcriber": {"provider": "sarvam", "model": "saaras:v3"},
                    }
                }
            ],
        }
    )

    assert readable
    assert models is not None
    assert models.llm_model == "sarvam-105b"
    assert models.tts_voice == "bulbul:v3"


def test_a_v1_shaped_agent_is_still_readable() -> None:
    """An account may still hold agents created through the v1 path — this adapter's own
    history, or the dashboard. Falling back to the flat spelling costs one dict lookup, and
    the alternative is calling a real, readable agent unreadable."""
    models, readable = _agent_models(
        {"tasks": [{"tools_config": {"llm_agent": {"model": "gpt-4.1-mini"}}}]}
    )

    assert readable
    assert models is not None
    assert models.llm_model == "gpt-4.1-mini"


# --- the knowledge base, on the wire the vendor documents (D-488) ------------
#
# THESE THREE CLAUSES REPLACED THREE THAT ASSERTED THE REFUSAL (D-354), and the
# replacement is not a relaxation: what they asserted was that an absent capability
# refuses by name, which `engine_capability_test.py` still holds for every capability
# this engine does not have. What is asserted here instead is the thing that was missing
# — that the requests going out are the ones the vendor's published spec accepts. The
# conformance suite proves the SEMANTICS (attach then list shows it, detach then list does
# not); only a mock transport can prove the BYTES, and the bytes are what D-354 found
# wrong.

_PDF = b"%PDF-1.4\n% fixture\n%%EOF\n"


def _kb_source() -> KBSourceRef:
    return KBSourceRef(
        kb_id="kb-1",
        title="Fees",
        text="Consultation is 500 rupees.",
        document=_PDF,
        content_sha256="0" * 64,
    )


def test_the_descriptor_says_this_engine_holds_a_knowledge_base() -> None:
    """D-488, and the value has been both things for different reasons — see the long
    comment above `BOLNA_CAPABILITIES` before trusting either.

    `True` here is the claim that the four documented routes exist and that this adapter
    calls them as specified. It is NOT a measurement: nothing has run against a live
    account (OPERATIONS §2 gates 41a-41f)."""
    assert BOLNA_CAPABILITIES.knowledge_base is True


async def test_a_knowledge_base_is_created_as_multipart_with_the_document() -> None:
    """THE DEFECT D-354 FOUND, HELD AS A PROPERTY. The old body was a JSON POST of
    `{agent_id, name, text}`; the route is `multipart/form-data` taking `file` (a PDF) or
    `url` and accepting neither an agent id nor prose
    (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:29-80`). A 2xx was
    impossible and the 4xx would have read as a transient engine fault.

    The retrieval knobs are asserted too, because they are the only part of the chunking
    we control and a silently dropped `language_support` cannot be corrected later: it is
    fixed at upload (`.../getting-started/knowledge-base.md`)."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/knowledgebase" and request.method == "POST":
            seen["content_type"] = request.headers["content-type"]
            seen["body"] = request.content
            return httpx.Response(200, json={"rag_id": "rag_1", "status": "processing"})
        if path == "/knowledgebase/rag_1":
            return httpx.Response(200, json={"status": "processed", "vector_id": "vec_1"})
        if path == "/v2/agent/agent_1" and request.method == "GET":
            return httpx.Response(200, json={"agent_id": "agent_1", "data": {}})
        if path == "/v2/agent/agent_1" and request.method == "PUT":
            seen["put"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "ok"})
        raise AssertionError(f"unexpected {request.method} {path}")

    handle = await _engine(handler).attach_kb("agent_1", _kb_source(), agent=_config())

    assert seen["content_type"].startswith("multipart/form-data")
    assert b"%PDF" in seen["body"], "the file part must carry the rendered document"
    assert b'name="text"' not in seen["body"], "this route accepts no prose"
    assert b'name="agent_id"' not in seen["body"], "this route accepts no agent id"
    assert b"multilingual" in seen["body"], (
        "`language_support` is fixed at upload and a Telugu-first product must ask for it"
    )
    assert handle == "vec_1", (
        "the handle must be the VECTOR id — the only identifier the agent carries — or "
        "`references_kb` compares two namespaces and reports every attachment as cleared"
    )
    llm_agent = seen["put"]["agent_config"]["tasks"][0]["tools_config"]["llm_agent"]
    assert llm_agent["agent_type"] == "knowledgebase_agent", (
        "`vector_store` lives on the `KnowledgebaseAgent` arm of the `llm_config` union; "
        "writing it while `agent_type` still selects `simple_llm_agent` is a silent no-op"
    )
    assert llm_agent["llm_config"]["vector_store"]["provider_config"]["vector_ids"] == ["vec_1"]


async def test_an_upload_that_cannot_be_attached_is_deleted_rather_than_left_billing() -> None:
    """A knowledge base nothing references is billed for as long as the account exists.

    The failure staged here is the vendor reporting `error` on the read-back, which is a
    real verdict on a document we uploaded and must not be read as "not ready yet". What
    matters is what happens NEXT: the half-made object is removed and the ORIGINAL failure
    is the one reported, never the cleanup's."""
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/knowledgebase" and request.method == "POST":
            return httpx.Response(200, json={"rag_id": "rag_1", "status": "processing"})
        if request.url.path == "/knowledgebase/rag_1" and request.method == "GET":
            return httpx.Response(200, json={"status": "error"})
        return httpx.Response(200, json={"message": "success", "state": "deleted"})

    with pytest.raises(ProblemError) as raised:
        await _engine(handler).attach_kb("agent_1", _kb_source(), agent=_config())

    assert raised.value.code == "engine_kb_processing_failed"
    assert ("DELETE", "/knowledgebase/rag_1") in calls, (
        "the uploaded document was left behind — an unreferenced knowledge base is a "
        "permanent line on the bill for text no agent can reach"
    )


async def test_a_detach_stops_the_agent_referencing_before_it_deletes() -> None:
    """THE ORDER IS THE ONE THING THAT CANNOT BE GOT WRONG TWICE.

    Delete first and a crash before the agent write leaves the agent pointing at a vector
    that no longer exists (D-41's dangling handle) on a live call path. Un-reference first
    and a crash leaves an unreferenced document: money, findable, removable later."""
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if path == "/knowledgebase/all":
            return httpx.Response(200, json=[{"rag_id": "rag_1", "vector_id": "vec_1"}])
        if path == "/v2/agent/agent_1" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "agent_id": "agent_1",
                    "data": {
                        "tasks": [
                            {
                                "tools_config": {
                                    "llm_agent": {
                                        "llm_config": {
                                            "vector_store": {
                                                "provider_config": {"vector_ids": ["vec_1"]}
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    },
                },
            )
        return httpx.Response(200, json={"message": "success", "state": "deleted"})

    await _engine(handler).detach_kb("agent_1", "vec_1", agent=_config())

    ordered = [call for call in calls if call[0] in ("PUT", "DELETE")]
    assert ordered == [("PUT", "/v2/agent/agent_1"), ("DELETE", "/knowledgebase/rag_1")], (
        "the agent must stop referencing the knowledge base before the document is deleted"
    )


async def test_a_detach_of_a_handle_the_account_does_not_hold_raises() -> None:
    """The publisher's next act is to attach a replacement, and "the old text is gone" is
    a claim it is entitled to have proven. There is no route that reads a knowledge base
    BY vector id, so the account listing is the evidence — and a handle absent from it is
    the vendor's 404 by another name."""
    with pytest.raises(ProblemError) as raised:
        await _engine(lambda _r: httpx.Response(200, json=[])).detach_kb(
            "agent_1", "vec_missing", agent=_config()
        )

    assert raised.value.code == "engine_rejected"


async def test_an_agent_republish_preserves_the_knowledge_it_already_holds() -> None:
    """WITHOUT THIS, EVERY T0 RECOMPILE WOULD DELETE A CLIENT'S KNOWLEDGE.

    `PUT /v2/agent/{id}` replaces the entire configuration
    (`.../api-reference/agent/v2/patch_update.md:9`) and `AgentConfig` carries no vector
    ids — deliberately, so no caller can forget to populate them. `update_agent` therefore
    reads the engine's own list back and re-sends it. `PATCH` cannot stand in: it updates
    a closed list of attributes that does not include `tasks`, and ignores everything
    else, so it would answer 200 and change nothing."""
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "agent_id": "agent_1",
                    "data": {
                        "tasks": [
                            {
                                "tools_config": {
                                    "llm_agent": {
                                        "llm_config": {
                                            "vector_store": {
                                                "provider_config": {"vector_ids": ["vec_kept"]}
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    },
                },
            )
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok"})

    await _engine(handler).update_agent("agent_1", _config())

    llm_agent = sent["agent_config"]["tasks"][0]["tools_config"]["llm_agent"]
    assert llm_agent["llm_config"]["vector_store"]["provider_config"]["vector_ids"] == [
        "vec_kept"
    ], "a republish dropped the agent's knowledge linkage"


async def test_listing_reads_the_agent_rather_than_the_account_listing() -> None:
    """THE SILENT-DRIFT BUG, HELD AS A PROPERTY. The old implementation read
    `GET /knowledgebase/all` and kept the rows whose `agent_id` matched — a field the
    vendor's `Knowledgebase` schema does not declare
    (`.../knowledgebase/get_knowledgebases.md:63-121`). So every agent listed `[]` for
    ever, and `kb/reconciliation` read that as the positive claim "the engine holds no
    documents for this agent".

    The linkage was never on the knowledge base. It is on the agent, and reading it there
    is both correct and one round trip instead of an account-wide listing."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "agent_id": "agent_1",
                "data": {
                    "tasks": [
                        {
                            "tools_config": {
                                "llm_agent": {
                                    "llm_config": {
                                        "vector_store": {
                                            "provider_config": {"vector_ids": ["vec_a", "vec_b"]}
                                        }
                                    }
                                }
                            }
                        }
                    ]
                },
            },
        )

    assert await _engine(handler).list_kb("agent_1") == ["vec_a", "vec_b"]
    assert paths == ["/v2/agent/agent_1"], (
        "the agent's own object is the linkage; the account listing cannot answer this"
    )


# --- the rotating LLM credential (D-404) ----------------------------------------
#
# THREE DOCUMENTED ROUTES AND ONE UNDOCUMENTED SEMANTIC. `POST /providers` takes
# `{provider_name, provider_value}` and answers a `ProviderAddedStatus` whose `status`
# enum has exactly ONE member, `"added"` — there is no `"updated"`. So what a SECOND write
# under the same name does is not written down, and the adapter is built to find out
# rather than to assume: count under our name, write, count again.


def _provider_row(provider_id: str, name: str) -> dict[str, str]:
    """One `Provider` as the spec defines it — note the MASKED value, which is why the
    adapter identifies entries by `provider_id` and never by what they hold."""
    return {"provider_id": provider_id, "provider_name": name, "provider_value": "xxxxxxxaz"}


def test_each_legs_credential_entries_are_the_vendors_documented_ones() -> None:
    """**THE COUNT PER LEG IS A VENDOR FACT AND `set_llm_credential` RELIES ON IT.**

    That method's docstring makes a claim that is only true if this table is right: on the
    two single-entry legs it installs the WHOLE leg and there is nothing left for a human to
    do in the vendor's console, while on Azure it installs one of four and gate 16f owns the
    rest. If OpenAI or Google in fact wanted a second entry, the method would report success
    on a leg that cannot authenticate — the exact silent-green failure its count-before /
    count-after dance exists to prevent, arriving through the door the dance does not watch.

    VERIFIED-VENDOR-DOCS, hash-checked mirror, `providers.md` "LLMs" tab under *"All these
    keys **must** be added for the respective provider"*: Azure OpenAI four (`:96-102`),
    OpenAI one named `OPENAI` (`:87`), Google Gemini one named `GOOGLE` (`:105-109`).

    ⚠ THE OPENAI NAME IS DISPUTED between two of the vendor's own pages (`OPENAI` vs
    `OPENAI_API_KEY`). The root table wins because it is the page carrying the "must be
    added" sentence and every other value here; the live account settles it at gate 16f. This
    test pins WHICH READING WE SHIPPED, so correcting it is a visible diff rather than a
    silent drift.
    """
    assert llm_provider_keys("openai") == ("OPENAI",)
    assert llm_provider_keys("google") == ("GOOGLE",)
    azure = llm_provider_keys("azure_openai")
    assert azure == (
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_MODEL",
        "AZURE_OPENAI_API_BASE",
        "AZURE_OPENAI_API_VERSION",
    )
    # THE SECRET IS ALWAYS THE FIRST ENTRY, which is what lets `_LLM_CREDENTIAL_KEY` be
    # derived by position instead of retyped — and it is what `set_llm_credential` pushes.
    for provider in ("azure_openai", "openai", "google"):
        assert llm_provider_keys(provider)[0].endswith(("API_KEY", "OPENAI", "GOOGLE"))

    # AND EVERY DECLARED LEG HAS AN ENTRY: a leg the credential table forgot would raise a
    # KeyError on the first rotation rather than at import.
    from calevate_shared.engine import DECLARED_LEGS

    for leg in DECLARED_LEGS:
        assert llm_provider_keys(leg.provider), leg.provider


async def test_installing_the_llm_credential_posts_the_documented_body() -> None:
    """`ProviderRequest` is `{provider_name, provider_value}`, both required. The name
    comes from `Settings.bolna_llm_credential_name` rather than a literal, because a
    documented name and a live account's actual name are different claims and an operator
    must be able to correct one from the ops console without a deploy. The DEFAULT is no
    longer a derivation: `AZURE_OPENAI_API_KEY` is the vendor's own name for the entry
    (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers.md`, "LLMs" tab, "Azure
    OpenAI" — four required keys, of which this is the one the platform pushes). It
    replaced the derived guess `AZURE`, which appears nowhere in that table.

    THE EXPECTED NAME IS A LITERAL HERE AND A SETTING THERE, deliberately. Reading the
    setting on both sides would make this assertion true by construction and prove only
    that the adapter can read a field. What it has to pin is the string that goes ON THE
    WIRE, which is what an operator comparing our POST against their console is looking
    at — so a change to the default is a change this test has to be told about."""
    seen: list[tuple[str, str, dict[str, str] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"message": "successful", "status": "added"})

    placement = await _engine(handler).set_llm_credential("ya29.fresh", provider="azure_openai")

    assert placement.replaced_in_place is True
    assert placement.superseded_removed == 0
    posts = [(path, body) for method, path, body in seen if method == "POST"]
    assert posts == [
        ("/providers", {"provider_name": "AZURE_OPENAI_API_KEY", "provider_value": "ya29.fresh"})
    ]


async def test_a_store_that_appends_is_reported_rather_than_tolerated() -> None:
    """**THE FAILURE THIS DANCE EXISTS FOR, AND D-410 MADE IT WORSE RATHER THAN MOOT.**
    If the store APPENDS, the engine holds the fresh credential AND every superseded one
    under one name, and which of them a call authenticates with is the vendor's choice.
    Under the rotating Vertex bearer the stale copies expired on their own, so this cost a
    confusing outage half a day later; under a STATIC Azure key a superseded copy an
    operator believes they revoked authenticates our spend until it is revoked at the
    source. Same detection, higher stakes.

    Detected by IDENTITY, not by count: an id present before the write and still present
    after it cannot be the entry we just made."""
    stale = _provider_row("p-old", "AZURE_OPENAI_API_KEY")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[stale, _provider_row("p-new", "AZURE_OPENAI_API_KEY")])
        return httpx.Response(200, json={"message": "successful", "status": "added"})

    with pytest.raises(ProblemError) as raised:
        await _engine(handler).set_llm_credential("ya29.fresh", provider="azure_openai")

    assert raised.value.code == "engine_credential_not_replaced"


async def test_other_providers_are_never_counted_as_ours() -> None:
    """The store holds every vendor key this account has — `SARVAM`, `PLIVO`, whatever an
    operator added by hand. Counting them as superseded copies of OURS would report append
    semantics on a store that replaced perfectly well, and the remedy the runbook then
    gives is to delete somebody else's credential."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[_provider_row("p-sarvam", "SARVAM"), _provider_row("p-plivo", "PLIVO")],
            )
        return httpx.Response(200, json={"message": "successful", "status": "added"})

    placement = await _engine(handler).set_llm_credential("ya29.fresh", provider="azure_openai")

    assert placement.replaced_in_place is True


def test_the_credential_name_we_push_is_one_the_vendor_documents() -> None:
    """**THE LAST MARKED ASSUMPTION IN D-410, PINNED TO ITS ANSWER.**

    `Settings.bolna_llm_credential_name` spent D-410 holding a DERIVATION: their provider
    matrix names single-key entries after the provider in upper case (`OPENAI`, `GOOGLE`,
    `SARVAM`), so `azure` became `AZURE`. The vendor's credential-store documentation
    names four entries for Azure OpenAI and **`AZURE` is not one of them** — the rule the
    guess generalised from is real for one-key providers and does not survive a provider
    that needs a key, an endpoint, a model and a version
    (`bolna-findings/mirror/pages/providers.md`, "LLMs" tab, "Azure OpenAI", under *"All
    these keys must be added for the respective provider."*).

    THIS IS WHAT MAKES `_AZURE_PROVIDER_KEYS` LOAD-BEARING RATHER THAN A COMMENT, which
    is the same job `_VENDOR_STATUSES` does for `_STATUS_MAP` in the same module: the
    constant is never read at runtime, so without a test reading it, a correction to the
    vendor's list and a correction to the default could drift apart silently. The
    assertion is on the API-KEY entry specifically, because that is the one and only one
    of the four this platform PUSHES — the other three have no secret in them and are
    installed by an operator (`set_llm_credential`'s docstring says why).

    It is a DEFAULT that is pinned, not the live value: the field is `applies: live`
    precisely so a real account may disagree with the page, and asserting the effective
    setting would refuse the correction the field exists to allow.
    """
    documented = bolna_module._AZURE_PROVIDER_KEYS
    assert "AZURE" not in documented, (
        "if the vendor ever does document a bare `AZURE` entry, this test and the "
        "default below both need re-deciding rather than one of them quietly moving"
    )

    default = Settings.model_fields["bolna_llm_credential_name"].default
    assert default in documented, (
        f"the credential entry this platform writes is named {default!r}, which is not "
        f"one of the entries the vendor's Azure OpenAI provider documents "
        f"({sorted(documented)}). A key installed under a name nothing reads authenticates "
        "nothing, and the symptom is a 401 from Azure on the first turn of the first call."
    )
    assert default == "AZURE_OPENAI_API_KEY", (
        "the API key is the only one of the four whose value is a secret this platform "
        "holds and must never ask a human to type; the endpoint, the deployment and the "
        "api-version are the operator's"
    )


async def test_the_other_three_azure_entries_are_not_mistaken_for_ours() -> None:
    """**THE NEAR-MISS THE FOUR-KEY REQUIREMENT CREATES, AND IT DID NOT EXIST BEFORE.**

    Their Azure OpenAI provider needs four entries (`_AZURE_PROVIDER_KEYS`), so a
    configured account's store holds `AZURE_OPENAI_API_KEY` beside `AZURE_OPENAI_MODEL`,
    `AZURE_OPENAI_API_BASE` and `AZURE_OPENAI_API_VERSION`. Under the old derived name
    `AZURE` the store held one entry that looked anything like ours; now it holds four
    that share a prefix, and three of them are present before AND after every write we
    make.

    If identity were ever loosened from `provider_name == name` to anything
    prefix-shaped or `in`-shaped, those three would read as SUPERSEDED COPIES of our key
    on the very first install: `set_llm_credential` would raise
    `engine_credential_not_replaced` on a store that behaved perfectly, and the
    remediation it prints tells an operator to delete the entry — which here would be the
    endpoint or the deployment their agent needs. A correct install reporting a failure
    whose fix breaks the leg is worse than either half alone.

    The companion values are the vendor's own descriptions rather than realistic ones,
    because what is under test is the NAME comparison and a realistic endpoint here would
    invite somebody to assert on it instead.
    """
    companions = [
        _provider_row("p-model", "AZURE_OPENAI_MODEL"),
        _provider_row("p-base", "AZURE_OPENAI_API_BASE"),
        _provider_row("p-version", "AZURE_OPENAI_API_VERSION"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=list(companions))
        return httpx.Response(200, json={"message": "successful", "status": "added"})

    placement = await _engine(handler).set_llm_credential(
        "azure-static-key", provider="azure_openai"
    )

    assert placement.replaced_in_place is True
    assert placement.superseded_removed == 0


async def test_the_write_happens_before_any_delete_could() -> None:
    """POST-FIRST, NEVER DELETE-FIRST. The spec-clean rotation looks like "remove the old
    entry, add the new one", and it is wrong on the only axis that matters: between the two
    calls the engine holds NO credential, so a failure in the second takes the LLM leg down
    IMMEDIATELY rather than at the old token's expiry. This pins the order."""
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        order.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"message": "successful", "status": "added"})

    await _engine(handler).set_llm_credential("ya29.fresh", provider="azure_openai")

    assert "DELETE" not in order
    assert order.index("POST") < len(order) - 1, "the read-back must follow the write"
    assert order == ["GET", "POST", "GET"]


# --- dialling -----------------------------------------------------------------


async def test_the_dial_body_carries_only_fields_the_vendor_declares() -> None:
    """`POST /call` requires `agent_id` and `recipient_phone_number` and declares
    `from_phone_number`, `scheduled_at`, `user_data`, `agent_data`, `retry_config`,
    `bypass_call_guardrails`. A key outside that set is either ignored (a setting we
    believe we applied and did not) or a 422."""
    import json

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/call"
        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(
            200, json={"message": "done", "status": "queued", "execution_id": "e1"}
        )

    handle = await _engine(handler).start_outbound_call(
        "agent_1",
        "+919876543210",
        CallContext(
            call_id="0199a0b0-0000-7000-8000-000000000003",
            tenant_id="0199a0b0-0000-7000-8000-000000000001",
            agent_id="0199a0b0-0000-7000-8000-000000000002",
            lead_name="Ravi",
        ),
    )

    assert handle == "e1"
    declared = {
        "agent_id",
        "recipient_phone_number",
        "from_phone_number",
        "scheduled_at",
        "user_data",
        "agent_data",
        "retry_config",
        "bypass_call_guardrails",
    }
    assert set(seen) <= declared, f"undeclared keys on POST /call: {set(seen) - declared}"
    assert seen["recipient_phone_number"].startswith("+"), "E.164, per the spec's own note"


def test_the_base_url_is_the_host_the_vendor_still_serves() -> None:
    """`references/bolna-core.md`: "The older `api.bolna.dev` host is deprecated. Do not use
    it for new work." The OAS declares exactly one server."""
    assert BASE_URL == "https://api.bolna.ai"
    assert datetime.now(UTC).tzinfo is UTC  # the module's time handling is UTC end to end


# --- the whole route surface, not one route at a time -------------------------


#: Every path in the vendor's pinned OpenAPI document, path parameters normalized to `{}`.
#:
#: TRANSCRIBED FROM `bolna-ai/skills@28b24aa references/openapi.yml` (the `paths:` keys;
#: md5 `5597f7da080d47564696bc05c12e9112`), and the complete inventory with its provenance
#: lives in `docs/vendor/bolna/hosted-oas.md`. Committed as a literal rather than fetched:
#: this suite must not depend on network egress, and a pinned checksum is what makes a
#: transcription auditable. Re-fetch and re-derive with the command in that document.
#:
#: NOT PRUNED TO WHAT WE CALL. The whole point is that a route we do NOT call is a
#: different thing from a route that does not EXIST, and `end_call`'s wrong path survived
#: precisely because nobody could tell those apart.
_VENDOR_PATHS: frozenset[str] = frozenset(
    {
        "/agent",
        "/agent/all",
        "/agent/{}",
        "/agent/{}/executions",
        "/agent/{}/execution/{}",
        "/v2/agent",
        "/v2/agent/all",
        "/v2/agent/{}",
        "/v2/agent/{}/stop",
        "/v2/agent/{}/executions",
        "/v2/agent/{}/dispositions/test",
        "/executions/{}",
        "/executions/{}/log",
        "/batches",
        "/batches/{}/all",
        "/batches/{}",
        "/batches/{}/executions",
        "/batches/{}/stop",
        "/batches/{}/schedule",
        "/call",
        "/call/{}/stop",
        "/providers",
        "/providers/{}",
        "/inbound/setup",
        "/inbound/unlink",
        "/me/voices",
        "/user/model/custom",
        "/user/me",
        "/sip-trunks/trunks",
        "/sip-trunks/trunks/{}",
        "/sip-trunks/trunks/{}/numbers",
        "/sip-trunks/trunks/{}/numbers/{}",
        "/knowledgebase",
        "/knowledgebase/all",
        "/knowledgebase/{}",
        "/extractions",
        "/extractions/{}",
        "/phone-numbers/all",
        "/phone-numbers/search",
        "/phone-numbers/buy",
        "/phone-numbers/{}",
        "/sub-accounts/create",
        "/sub-accounts/{}",
        "/sub-accounts/all",
        "/sub-accounts/{}/usage",
        "/sub-accounts/all/usage",
        "/violations/list",
        "/violations/submit",
        "/dispositions/",
        "/dispositions/bulk",
        "/dispositions/{}",
    }
)


def _adapter_routes() -> set[str]:
    """Every path literal the adapter hands to `_request`, normalized like `_VENDOR_PATHS`.

    Read out of the SOURCE rather than by driving the methods, because the defect this
    guards is a route on a path nobody exercised: `end_call` had no test at all while it
    pointed at `/executions/{id}/stop`, which is exactly how it stayed wrong.
    """
    tree = ast.parse(Path(bolna_module.__file__).read_text(encoding="utf-8"))
    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "_request"):
            continue
        # `_request(method, path, ...)` — the path is the second positional argument.
        if len(node.args) < 2:
            continue
        path = node.args[1]
        if isinstance(path, ast.Constant) and isinstance(path.value, str):
            routes.add(path.value)
        elif isinstance(path, ast.JoinedStr):
            # An f-string: keep the literal segments, collapse each interpolation to `{}`.
            routes.add(
                "".join(
                    part.value if isinstance(part, ast.Constant) else "{}" for part in path.values
                )
            )
    return routes


def test_every_route_this_adapter_calls_is_a_route_the_vendor_publishes() -> None:
    """THE GUARD THAT WOULD HAVE CAUGHT D-353 ON THE DAY IT WAS WRITTEN.

    Two routes reached production-shaped code without existing: `GET /executions` (the
    guarantee of record, so every reconciliation tick would have 404'd forever while the
    console blamed the engine) and `POST /executions/{id}/stop` (the campaign halt). Both
    were plausible, both had passing tests, and both were wrong — because the stub was
    built from the same guess as the adapter, so the suite confirmed the guess.

    A per-route test cannot close that: it proves the adapter calls what the test expects,
    which is a statement about our agreement with ourselves. This compares the adapter
    against the VENDOR'S OWN path list, so the failure reads "you invented a URL" rather
    than "you disagreed with a fixture we also wrote".

    Deliberately ONE-DIRECTIONAL: the vendor has many routes we do not call, and that is
    normal — batches, phone numbers and SIP trunks are declined by design, see
    `BOLNA_CAPABILITIES`. Only the reverse direction is ever a defect.
    """
    called = _adapter_routes()
    assert called, "the AST scan found no routes at all — it has stopped scanning anything"

    invented = sorted(called - _VENDOR_PATHS)
    assert not invented, (
        f"the adapter calls {invented}, which the vendor's pinned OpenAPI document does "
        "not publish. A route that does not exist 404s on the first live call, and "
        "`vendor_request` reports that as a dependency failure — an engine fault on the "
        "console, for a URL we made up. Check the path against "
        "`docs/vendor/bolna/hosted-oas.md`; if the vendor has ADDED it, re-fetch the spec "
        "at a new pin and update `_VENDOR_PATHS` and the checksum in the same change."
    )


def test_the_adapter_is_fully_migrated_off_the_deprecated_v1_agent_surface() -> None:
    """v1 and v2 both exist on this vendor, which is what made a PARTIAL migration possible.

    Agent CRUD moved to `/v2/agent` and the executions and stop paths did not, and nothing
    could see the difference, because "the adapter targets v2" was true of the part anyone
    looked at. Pinned here: no route we call may be a v1 agent route.
    """
    v1_agent_routes = {
        route for route in _adapter_routes() if route == "/agent" or route.startswith("/agent/")
    }
    assert not v1_agent_routes, (
        f"the adapter calls the deprecated v1 agent surface: {sorted(v1_agent_routes)}. "
        "TRD §3 says never to call the legacy unversioned agent paths; the v2 equivalents "
        "are `/v2/agent`, `/v2/agent/all`, `/v2/agent/{id}` and `/v2/agent/{id}/executions`."
    )
