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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine import bolna as bolna_module
from apps.api.engine.bolna import BASE_URL, BOLNA_CAPABILITIES, BolnaEngine, _agent_models
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


# --- the knowledge base we cannot drive -------------------------------------


def test_the_descriptor_says_this_engine_holds_no_knowledge_base() -> None:
    """D-354. Bolna HAS a knowledge base; what it does not have is one this port can drive.
    `POST /knowledgebase` is multipart and takes a PDF or a URL — never our
    `KBSourceRef.text` — and the created object carries no agent, so the link is made on
    the AGENT's `vector_ids` by a `vector_id` this adapter never read. A descriptor that
    said `True` was a promise three methods could not keep."""
    assert BOLNA_CAPABILITIES.knowledge_base is False


async def test_attaching_a_knowledge_base_refuses_by_name_and_sends_nothing() -> None:
    """An absent capability produces a NAMED refusal, never a silent no-op and never a
    request the vendor will reject. The second half is the one worth testing: the old body
    was a JSON POST the route does not accept, so a 2xx was impossible and a 4xx would have
    been read as a transient engine fault."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"rag_id": "kb_1"})

    with pytest.raises(ProblemError) as raised:
        await _engine(handler).attach_kb(
            "agent_1", KBSourceRef(kb_id="kb-1", title="Fees", text="Consultation is 500 rupees.")
        )

    assert raised.value.code == "engine_capability_absent"
    assert calls == [], "a refusal must not reach the vendor at all"


async def test_listing_knowledge_bases_refuses_rather_than_reporting_an_empty_engine() -> None:
    """The worst of the three if it were a stub. `kb/reconciliation` reads an empty list as
    "the engine holds no documents for this agent", which is a positive claim about a
    system we cannot read — and it would have been made on every sweep forever, because the
    old implementation filtered `GET /knowledgebase/all` on a `row["agent_id"]` the vendor's
    `Knowledgebase` schema does not have."""
    with pytest.raises(ProblemError):
        await _engine(lambda _r: httpx.Response(200, json=[])).list_kb("agent_1")


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
