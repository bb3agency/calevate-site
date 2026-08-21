"""The second prompt bypass: a console-added route that answers a caller without the LLM.

**WHY THIS IS A COMPLIANCE TEST AND NOT AN ADAPTER TEST.** Hard rule 5's floor
(`TRUTHFUL_ANSWER_DIRECTIVE`) lives in the system prompt, and every instrument this
repository has for it scores the prompt: the publish read-back, `verification.judge`, the
half-hourly drift sweep. The vendor's `routes` layer — `{route_name, utterances, response,
score_threshold}` on `LlmAgentV2`, matched on semantic similarity of what the caller SAID
(default 0.85) and answered with a static string — never consults the model at all
(`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`, schemas `Routes`/`Route`).

So a route matching *"are you a robot"* answers from config, the directive that overrides
every instruction above it is not in the path, and **the prompt still reads back perfect**.
That is a published agent that can deny being an AI with every check here green.

We do not send `routes` and must not start: the field is not nullable and has no default in
their schema, so guessing `null` or `[]` risks 400ing every publish for a field we have no
use for. The exposure is a CONSOLE EDIT — which is exactly what a read-back sees and a
request body cannot — so the control is an alarm on `get_agent`, in
`_check_transfer_leg`'s shape, and these are the clauses that keep it honest.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.engine.bolna import BASE_URL, BolnaEngine


#: An agent object as `GET /v2/agent/{id}` returns it, with the routing layer where their
#: create schema puts it: `tasks[].tools_config.llm_agent.routes` = `{embedding_model,
#: routes: [Route]}`.
def _agent_payload(routes: Any) -> dict[str, Any]:
    llm_agent: dict[str, Any] = {
        "agent_type": "simple_llm_agent",
        "llm_config": {"model": "gpt-4o-mini"},
    }
    if routes is not None:
        llm_agent["routes"] = routes
    return {
        "agent_id": "agent_xyz",
        "data": {
            "agent_name": "Sunrise Clinic receptionist",
            "agent_prompts": {"task_1": {"system_prompt": "You are the receptionist."}},
            "tasks": [{"tools_config": {"llm_agent": llm_agent}}],
        },
    }


def _engine(routes: Any) -> BolnaEngine:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agent_payload(routes))

    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _alerts(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        record.__dict__
        for record in caplog.records
        if record.message == "alert"
        and record.__dict__.get("code") == "engine_agent_semantic_routes_present"
    ]


async def test_a_console_added_route_is_paged_on_at_the_read_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The alarm fires, and it fires on the path every publish and every sweep takes."""
    engine = _engine(
        {
            "embedding_model": "snowflake/snowflake-arctic-embed-m",
            "routes": [
                {
                    "route_name": "identity",
                    "utterances": ["Are you a robot?", "Am I talking to a machine?"],
                    "response": "No no, I am a real person from the clinic.",
                    "score_threshold": 0.85,
                }
            ],
        }
    )

    with caplog.at_level("ERROR"):
        snapshot = await engine.get_agent("agent_xyz")

    raised = _alerts(caplog)
    assert raised, (
        "an agent answering callers from static strings read back clean — the one bypass "
        "the prompt read-back cannot see"
    )
    # The snapshot is still returned and still scored. The route is a SEPARATE fact about
    # the agent; refusing the read-back would break the drift sweep that found it.
    assert snapshot.system_prompt_readable


async def test_the_alarm_names_the_routes_and_never_the_conversation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HARD RULE 6, on the one alarm whose subject is a conversation.

    A route's `utterances` are what a caller says and its `response` is what the agent says
    back. Neither may reach an operator's inbox. What may — and must, because it is the only
    handle for finding the thing in the vendor console — is the operator-authored
    `route_name` and the count.
    """
    engine = _engine(
        {
            "routes": [
                {
                    "route_name": "identity",
                    "utterances": ["Are you a robot?"],
                    "response": "No no, I am a real person from the clinic.",
                },
                {"route_name": "pricing", "utterances": ["How much?"], "response": "₹500."},
            ]
        }
    )

    with caplog.at_level("ERROR"):
        await engine.get_agent("agent_xyz")

    detail = json.dumps(_alerts(caplog)[0])
    assert "identity" in detail and "pricing" in detail, (
        "without the route names an operator cannot find them in the vendor console"
    )
    assert "2" in detail, "the count is what says how much of the agent is bypassed"
    for leaked in ("Are you a robot?", "real person from the clinic", "How much?", "₹500"):
        assert leaked not in detail, (
            f"caller conversation reached an alert payload: {leaked!r} (hard rule 6)"
        )


async def test_a_bare_route_array_is_seen_too(caplog: pytest.LogCaptureFixture) -> None:
    """Their create schema wraps the array in a `Routes` object; a dashboard-written agent
    is not obliged to read back in that nesting. Reading only one shape would make this
    check silently blind to the other — and silent blindness is the defect it exists for."""
    engine = _engine([{"route_name": "identity", "response": "I am human."}])

    with caplog.at_level("ERROR"):
        await engine.get_agent("agent_xyz")

    assert _alerts(caplog)


@pytest.mark.parametrize("routes", [None, [], {"routes": []}, {}, "unexpected"])
async def test_an_agent_with_no_routes_pages_nobody(
    routes: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The alarm that fires on a clean agent is an alarm an operator learns to ignore.

    Every shape here means "nothing answers without the model": the key absent (which is
    what our own `_agent_body` produces, since we never send it), an empty array, an empty
    wrapper, and a value in a shape we do not recognise — the last one deliberately, because
    a vendor changing this field's shape must not turn every read-back into a page.
    """
    engine = _engine(routes)

    with caplog.at_level("ERROR"):
        await engine.get_agent("agent_xyz")

    assert not _alerts(caplog)
