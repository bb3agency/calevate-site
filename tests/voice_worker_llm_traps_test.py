"""What the in-call LLM leg actually puts on the wire, per selectable model.

The body is captured at the HTTP transport of the service `_build_llm` constructed, so the
assertion covers pipecat's parameter assembly AND the OpenAI SDK's stripping of unset
fields — the two places a `temperature` or a token cap could appear without anyone having
typed one. No network: the transport answers every request with a 400.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest
from calevate_shared.engine import (
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
    ModelConfig,
    azure_openai_base_url,
    openai_base_url,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.openai.base_llm import BaseOpenAILLMService
from tests.voice_worker_pipeline_test import CREDENTIALS, make_config
from voice_worker import pipeline

#: The keys every request carries regardless of model.
_BASE_KEYS = {"model", "stream", "stream_options", "messages"}

#: The sampling fields and token caps no model on this leg may be sent.
_NEVER_SENT = {
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
}


def _config_for(model: str) -> pipeline.SessionConfig:
    """The `ModelConfig` `agents/service.in_call_llm` would hand the worker for `model`."""
    spec = LLM_MODELS[model]
    llm: dict[str, Any] = {
        "llm_provider": spec.provider,
        "llm_traps": tuple(trap.name for trap in spec.traps),
    }
    if spec.provider == "azure_openai":
        llm["llm_model"] = f"calevate-{model}"
        llm["llm_base_url"] = azure_openai_base_url("calevate-eastus2")
    else:
        llm["llm_model"] = model
    if spec.provider == "openai":
        llm["llm_base_url"] = openai_base_url()
    return make_config(
        models=ModelConfig(
            stt_model="saaras:v4",
            tts_provider="cartesia",
            tts_model="sonic-3.5",
            tts_voice="shubh",
            **llm,
        )
    )


async def _wire_body(service: BaseOpenAILLMService) -> dict[str, Any]:
    captured: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(400, json={"error": {"message": "captured"}})

    service._client = openai.AsyncOpenAI(
        api_key="llm-test",
        base_url=str(service._client.base_url),
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )
    context = LLMContext(messages=[{"role": "user", "content": "namaskaram"}])
    with pytest.raises(openai.BadRequestError):
        await service.get_chat_completions(context)
    (request,) = captured
    body: dict[str, Any] = json.loads(request.content)
    return body


def _build(model: str) -> BaseOpenAILLMService:
    llm = pipeline.build_vendor_legs(_config_for(model), CREDENTIALS).llm
    assert isinstance(llm, BaseOpenAILLMService)
    return llm


@pytest.mark.parametrize("model", sorted(SELECTABLE_LLM_MODELS))
async def test_no_sampling_field_or_token_cap_reaches_the_wire(model: str) -> None:
    body = await _wire_body(_build(model))
    assert not _NEVER_SENT & body.keys(), f"{model} sent {_NEVER_SENT & body.keys()}"


@pytest.mark.parametrize(
    ("model", "expected_extra"),
    [
        ("gpt-4o-mini", {}),
        ("gpt-4.1-mini", {}),
        ("gpt-5.4-mini", {"reasoning_effort": "none"}),
        ("gemini-2.5-flash", {"reasoning_effort": "none"}),
        ("gemini-2.5-flash-lite", {"reasoning_effort": "none"}),
    ],
)
async def test_each_selectable_model_sends_exactly_its_trap_mitigation(
    model: str, expected_extra: dict[str, str]
) -> None:
    body = await _wire_body(_build(model))
    extra_keys = body.keys() - _BASE_KEYS
    assert {key: body[key] for key in extra_keys} == expected_extra
    assert body["stream"] is True


def test_the_parametrisation_above_covers_every_selectable_model() -> None:
    """A model made selectable without a row above would send an unasserted body."""
    assert {
        "gpt-4o-mini",
        "gpt-4.1-mini",
        "gpt-5.4-mini",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    } == SELECTABLE_LLM_MODELS


def test_reasoning_is_switched_off_by_trap_not_by_provider() -> None:
    assert pipeline._trap_request_extra(()) == {}
    assert pipeline._trap_request_extra(("temperature-must-be-one",)) == {}
    assert pipeline._trap_request_extra(("thinking-tokens-share-the-reply-budget",)) == {
        "reasoning_effort": "none"
    }
    assert pipeline._trap_request_extra(
        ("temperature-must-be-one", "max-tokens-becomes-max-completion-tokens")
    ) == {"reasoning_effort": "none"}
