"""Gemini's Flex tier for work nobody waits on (D-930): which calls may ask for it, the
request it sends, the fallback to the standard tier, and the budget it is held to."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from apps.api.core import provider_health
from apps.api.core.settings import get_settings
from apps.workers import chat, model_tiers, script_assist
from apps.workers.background_leg import BackgroundLeg
from apps.workers.extraction import TenantModelLeg

GOOGLE = chat.ChatLeg(
    url="https://gemini.test/v1beta/openai/chat/completions",
    api_key="g-test",
    wire_model="gemini-3.1-flash-lite",
    dialect="google",
)
AZURE = chat.ChatLeg(
    url="https://res.test/openai/v1/chat/completions",
    api_key="az-test",
    wire_model="dep",
    dialect="openai",
)
ANSWER = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
}


class _Provider:
    """An httpx transport that records each request body and answers in turn."""

    def __init__(self, *replies: int | type[Exception]) -> None:
        self.replies = list(replies)
        self.bodies: list[dict[str, Any]] = []
        self.timeouts: list[Any] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        self.timeouts.append(request.extensions.get("timeout"))
        reply = self.replies.pop(0)
        if isinstance(reply, type):
            raise reply("provider did not answer in time")
        return httpx.Response(reply, json=ANSWER if reply == 200 else {"error": {}})


async def _complete(
    provider: _Provider, leg: chat.ChatLeg, flex: chat.FlexRequest | None
) -> chat.ChatOutcome:
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        return await chat.complete(
            leg, [{"role": "user", "content": "x"}], timeout_s=30, client=client, flex=flex
        )


# --- the classification ------------------------------------------------------------------


def test_a_call_a_person_waits_on_can_never_be_given_flex() -> None:
    """FAILS IF: a person-facing call (Pip, the test chat, a button) can get a Flex request."""
    standard = [name for name, call in model_tiers.MODEL_CALLS.items() if call.tier == "standard"]
    assert {"copilot_chat", "agent_test", "script_draft", "extraction"} <= set(standard)
    for name in standard:
        with pytest.raises(ValueError, match="standard tier"):
            model_tiers.FlexAllowance(name)
    for name, call in model_tiers.MODEL_CALLS.items():
        assert call.reason.strip(), name
        if call.tier == "flex":
            assert model_tiers.FlexAllowance(name).request(standard_timeout_s=30) is not None


async def test_a_call_without_flex_never_sends_the_tier() -> None:
    provider = _Provider(200)
    outcome = await _complete(provider, GOOGLE, None)
    assert "service_tier" not in provider.bodies[0]
    assert outcome.service_tier == "standard"


# --- the request and the fallback --------------------------------------------------------


async def test_flex_is_asked_first_and_answers_at_the_flex_tier() -> None:
    provider = _Provider(200)
    outcome = await _complete(provider, GOOGLE, chat.FlexRequest(wait_s=45))
    assert provider.bodies[0]["service_tier"] == "flex"
    assert provider.timeouts[0] == {"connect": 45, "read": 45, "write": 45, "pool": 45}
    assert outcome.service_tier == "flex" and outcome.content == "ok"


@pytest.mark.parametrize("refusal", [429, 503, 400, httpx.ReadTimeout])
async def test_a_flex_refusal_or_timeout_falls_back_to_standard(
    refusal: int | type[Exception],
) -> None:
    """FAILS IF: a job fails only because the cheaper tier was at capacity or too slow."""
    provider = _Provider(refusal, 200)
    outcome = await _complete(provider, GOOGLE, chat.FlexRequest(wait_s=45))
    assert [body.get("service_tier") for body in provider.bodies] == ["flex", None]
    assert outcome.service_tier == "standard" and outcome.content == "ok"


async def test_a_flex_ask_the_response_says_standard_served_is_recorded_as_standard() -> None:
    """FAILS IF: the ledger labels an answer Flex because we asked for it, when Google says
    it served standard (it did exactly that for `priority` on our key, 21 Oct 2026)."""

    def _served_standard(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**ANSWER, "service_tier": "default"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_served_standard)) as client:
        outcome = await chat.complete(
            GOOGLE,
            [{"role": "user", "content": "x"}],
            timeout_s=30,
            client=client,
            flex=chat.FlexRequest(wait_s=45),
        )
    assert outcome.service_tier == "standard"


async def test_only_the_standard_attempts_failure_is_raised() -> None:
    provider = _Provider(503, 500)
    with pytest.raises(httpx.HTTPStatusError) as failed:
        await _complete(provider, GOOGLE, chat.FlexRequest(wait_s=45))
    assert failed.value.response.status_code == 500


async def test_a_leg_with_no_flex_tier_ignores_the_request() -> None:
    provider = _Provider(200)
    outcome = await _complete(provider, AZURE, chat.FlexRequest(wait_s=45))
    assert len(provider.bodies) == 1 and "service_tier" not in provider.bodies[0]
    assert outcome.service_tier == "standard"


# --- the budget --------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_flex_wait_never_leaves_less_than_a_standard_request_in_the_budget() -> None:
    clock = _Clock()
    allowance = model_tiers.FlexAllowance("kb_gloss", budget_s=240, clock=clock)
    asked = allowance.request(standard_timeout_s=30)
    assert asked is not None and asked.wait_s == model_tiers.FLEX_WAIT_CAP_S
    clock.now = 180.0
    asked = allowance.request(standard_timeout_s=30)
    assert asked is not None and asked.wait_s == 30.0
    clock.now = 200.0
    assert allowance.request(standard_timeout_s=30) is None


def test_after_one_fallback_the_rest_of_the_tick_asks_on_standard() -> None:
    allowance = model_tiers.FlexAllowance("copilot_memory")
    asked = allowance.request(standard_timeout_s=30)
    allowance.note(asked, chat.ChatOutcome(content="", service_tier="flex"))
    asked = allowance.request(standard_timeout_s=30)
    assert asked is not None
    allowance.note(asked, chat.ChatOutcome(content="", service_tier="standard"))
    assert allowance.request(standard_timeout_s=30) is None


async def test_the_background_leg_reports_the_tier_that_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []

    async def _served(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> chat.ChatOutcome:
        sent.append(kw["flex"])
        return chat.ChatOutcome(content="ok", service_tier="flex" if kw["flex"] else "standard")

    monkeypatch.setattr(chat, "complete", _served)
    gemini = BackgroundLeg(GOOGLE, "gemini-3.1-flash-lite", model_tiers.FlexAllowance("kb_gloss"))
    assert (await gemini.complete([], timeout_s=30))[1] == "flex"
    azure = BackgroundLeg(AZURE, "gpt-4o-mini")
    assert (await azure.complete([], timeout_s=30))[1] == "standard"
    assert sent[0] is not None and sent[1] is None


# --- the JSON ladder ---------------------------------------------------------------------


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    for field in ("azure_openai_resource", "azure_openai_api_key", "azure_openai_deployment"):
        monkeypatch.setattr(settings, field, None, raising=False)

    async def _quiet(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(provider_health, "note_failure", _quiet)
    monkeypatch.setattr(provider_health, "note_success", _quiet)


def _ok(raw: dict[str, Any]) -> bool:
    if not raw.get("ok"):
        raise script_assist.UnusableAnswerError("ok: must be true")
    return True


LEG = TenantModelLeg(model="gemini-3.1-flash-lite", provider="google", serves_dashboard=True)


async def test_the_ladder_asks_flex_first_and_repairs_on_standard(
    keyed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Any] = []
    replies = iter(['{"ok": false}', '{"ok": true}'])

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        asked.append(kw.get("flex"))
        return chat.ChatOutcome(
            content=next(replies),
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
            service_tier="flex" if kw.get("flex") else "standard",
        )

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json(
        "d",
        "i",
        parse=_ok,
        tenant_leg=LEG,
        gemini_only=True,
        flex=model_tiers.FlexAllowance("business_copy_scheduled"),
    )
    assert isinstance(asked[0], chat.FlexRequest) and asked[1] is None
    assert answer.value is True and answer.service_tier == "standard"


async def test_a_flex_answer_is_reported_as_flex(
    keyed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        return chat.ChatOutcome(content='{"ok": true}', finish_reason="stop", service_tier="flex")

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json(
        "d",
        "i",
        parse=_ok,
        tenant_leg=LEG,
        gemini_only=True,
        flex=model_tiers.FlexAllowance("business_copy_scheduled"),
    )
    assert answer.service_tier == "flex"
    plain = await script_assist.ask_json("d", "i", parse=_ok, tenant_leg=LEG, gemini_only=True)
    assert plain.service_tier == "standard"
