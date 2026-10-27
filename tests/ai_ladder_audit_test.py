"""The dashboard AI ladders end to end: who answers, what each paid leg costs on the ledger,
how long the whole ladder may take, and what a refusal says.

The provider is faked at `chat.complete`, one layer below every ladder, so each test drives
the real ladder code (`extraction.run_assist`, `script_assist.ask_json`, the teach sort, the
lead-field draft) with the request each leg would have sent.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest
from apps.api.billing.models import ASSIST_FEATURE_BUSINESS_TYPE
from apps.api.core import provider_health
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.workers import (
    agent_test_conversations,
    business_type,
    call_translation,
    chat,
    extraction,
    kb_teach,
    lead_fields_draft,
    script_assist,
)
from apps.workers.extraction import TenantModelLeg
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec

GEMINI = "gemini-3.1-flash-lite"
GOOGLE_LEG = TenantModelLeg(model=GEMINI, provider="google", serves_dashboard=True)
SPEC = ExtractionSchemaSpec(
    version=1, fields=[ExtractionField(key="caller_name", label="Caller name", type="text")]
)
TRANSCRIPT = "caller: I want to book a table\nagent: For how many?"
ANSWER = json.dumps({"summary": "The caller wants a table.", "caller_name": None})


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini and Sarvam keyed, no Azure leg: the production shape of the dashboard ladder."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    for field in ("azure_openai_resource", "azure_openai_api_key", "azure_openai_deployment"):
        monkeypatch.setattr(settings, field, None, raising=False)

    async def _quiet(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(provider_health, "note_failure", _quiet)
    monkeypatch.setattr(provider_health, "note_success", _quiet)


def _outcome(content: str, *, finish: str = "stop", tokens: int = 10) -> chat.ChatOutcome:
    return chat.ChatOutcome(
        content=content,
        finish_reason=finish,
        usage=chat.TokenUsage(prompt_tokens=tokens, output_tokens=tokens // 2),
    )


def _status(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.test/chat/completions")
    return httpx.HTTPStatusError(
        "refused", request=request, response=httpx.Response(code, request=request)
    )


# --- run_assist (re-summarise) -----------------------------------------------------------


async def test_the_google_rung_of_re_summarise_answers_on_google(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an account on the Google rung is answered by the standby while the result
    still says Google (no disclosure, and the meter cannot price it)."""
    legs: list[tuple[str, Any]] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        legs.append((leg.dialect, kw.get("temperature", "unset")))
        return _outcome(ANSWER)

    monkeypatch.setattr(chat, "complete", _complete)
    result = await extraction.run_assist(SPEC, TRANSCRIPT, tenant_leg=GOOGLE_LEG)

    assert [dialect for dialect, _ in legs] == ["google"]
    # Gemini 3: no temperature sent (D-786).
    assert legs[0][1] is None
    assert result.capability.provider == extraction.GOOGLE_PROVIDER
    assert result.capability.disclosure is None
    assert result.model == GEMINI
    assert result.usage is not None and result.usage.prompt_tokens == 10


async def test_a_truncated_google_answer_is_metered_at_google_and_the_standby_at_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the paid turn that failed in front of the standby is folded into the
    standby's result (priced as the standby's model), or the standby's own usage is lost."""

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        if leg.dialect == "google":
            return _outcome('{"summary": "cut', finish="length", tokens=40)
        return _outcome(ANSWER, tokens=20)

    monkeypatch.setattr(chat, "complete", _complete)
    result = await extraction.run_assist(SPEC, TRANSCRIPT, tenant_leg=GOOGLE_LEG)

    assert result.capability.provider == extraction.SARVAM_PROVIDER
    assert result.capability.disclosure is not None
    assert result.usage is not None and result.usage.prompt_tokens == 20
    assert len(result.earlier) == 1
    paid = result.earlier[0]
    assert paid.model == GEMINI and paid.capability.provider == extraction.GOOGLE_PROVIDER
    assert paid.usage is not None and paid.usage.prompt_tokens == 40


# --- ask_json (script helper, agent tests, business type) --------------------------------


def _strict_parse(raw: dict[str, Any]) -> bool:
    if not raw.get("ok"):
        raise script_assist.UnusableAnswerError("ok: must be true")
    return True


async def test_a_standby_answer_after_an_unusable_gemini_answer_meters_both_at_their_own_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: Gemini's two billed attempts ride the standby's answer to the meter and are
    priced as the standby's model, or the standby's own usage is dropped."""

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        if leg.dialect == "google":
            return _outcome('{"ok": false}', tokens=10)
        return _outcome('{"ok": true}', tokens=30)

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json("d", "i", parse=_strict_parse, tenant_leg=GOOGLE_LEG)

    assert answer.capability.provider == extraction.SARVAM_PROVIDER
    assert answer.usage is not None and answer.usage.prompt_tokens == 30
    assert [(t.model, t.usage.prompt_tokens if t.usage else None) for t in answer.earlier] == [
        (GEMINI, 20)
    ]


async def test_a_refusal_after_gemini_answered_carries_what_gemini_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the paid leg answered (and was billed) but the refusal that follows carries
    no spend, so no ledger row is ever written for it (hard rule 7)."""

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        if leg.dialect == "google":
            return _outcome('{"ok": false}', tokens=10)
        raise httpx.ConnectTimeout("standby unreachable")

    monkeypatch.setattr(chat, "complete", _complete)
    with pytest.raises(extraction.SpentRefusalError) as refused:
        await script_assist.ask_json("d", "i", parse=_strict_parse, tenant_leg=GOOGLE_LEG)
    assert refused.value.code == script_assist.ANSWER_UNUSABLE_CODE
    assert [t.model for t in refused.value.earlier] == [GEMINI]
    assert refused.value.earlier[0].usage is not None


async def test_a_repair_that_never_reached_the_provider_keeps_the_first_spend_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a repair request that failed in transit turns the first attempt's known
    usage into "not reported", which the meter then alarms on instead of recording."""
    calls = 0

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        nonlocal calls
        if leg.dialect == "google":
            calls += 1
            if calls > 1:
                raise httpx.ReadError("gone")
            return _outcome('{"ok": false}', tokens=10)
        return _outcome('{"ok": true}', tokens=30)

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json("d", "i", parse=_strict_parse, tenant_leg=GOOGLE_LEG)
    assert answer.earlier[0].usage is not None
    assert answer.earlier[0].usage.prompt_tokens == 10


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_the_whole_ladder_fits_inside_its_budget_even_when_every_request_runs_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the strict-schema degrade, the repair and the standby each get a fresh full
    budget, so a worst case runs past `ASSIST_LADDER_LEGS` budgets (the route's edge
    deadline is pinned against that sum in `tests/assist_deadline_test.py`)."""
    clock = _Clock()
    monkeypatch.setattr(extraction, "_now", clock)

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        clock.now += kw["timeout_s"]
        if leg.dialect == "google":
            if kw["response_format"].get("type") == "json_schema":
                raise _status(400)
            return _outcome('{"ok": false}')
        raise httpx.ReadTimeout("standby too slow")

    monkeypatch.setattr(chat, "complete", _complete)
    start = clock.now
    with pytest.raises(ProblemError):
        await script_assist.ask_json(
            "d",
            "i",
            parse=_strict_parse,
            azure_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
            tenant_leg=GOOGLE_LEG,
        )
    spent = clock.now - start
    assert spent <= extraction.ASSIST_LADDER_LEGS * extraction.ASSIST_TIMEOUT_S


async def test_the_standby_inherits_the_time_a_fast_failing_paid_leg_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the standby is held to one fixed request budget when the paid leg failed at
    once (production, 18 Oct 2026: the standby timed out at 15 s on a long answer)."""
    clock = _Clock()
    monkeypatch.setattr(extraction, "_now", clock)
    timeouts: list[float] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        if leg.dialect == "google":
            raise _status(503)
        timeouts.append(kw["timeout_s"])
        return _outcome('{"ok": true}')

    monkeypatch.setattr(chat, "complete", _complete)
    await script_assist.ask_json("d", "i", parse=_strict_parse, tenant_leg=GOOGLE_LEG)
    assert timeouts == [extraction.ASSIST_LADDER_LEGS * extraction.ASSIST_TIMEOUT_S]


# --- the teach-box sort and the lead-field draft -----------------------------------------


async def test_the_teach_sort_answers_on_the_google_rung(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: the sort skips the account's Google leg and goes straight to the standby
    while still claiming Google (no disclosure, an unmeterable alarm per teaching)."""
    dialects: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        dialects.append(leg.dialect)
        return _outcome(json.dumps({"items": [{"kind": "fact", "text": "We open at 9."}]}))

    monkeypatch.setattr(chat, "complete", _complete)
    capability = extraction.assist_capability(tenant_leg=GOOGLE_LEG)
    result = await kb_teach.sort_words(
        "We open at 9.", capability=capability, tenant_leg=GOOGLE_LEG, quota_exhausted=False
    )
    assert dialects == ["google"]
    assert result.answered and result.model == GEMINI
    assert result.items == [{"kind": "fact", "text": "We open at 9."}]


async def test_the_lead_field_draft_runs_on_the_accounts_google_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the draft has its own Azure-then-standby ladder that never reaches the
    account's Google leg, so a deployment without Azure drafts on the standby."""
    dialects: list[str] = []
    body = {
        "fields": [
            {
                "key": "produce",
                "label": "Produce",
                "type": "text",
                "reason": "what they grow",
                "required": True,
                "enum_values": [],
            }
        ]
    }

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        dialects.append(leg.dialect)
        return _outcome(json.dumps(body))

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await lead_fields_draft._draft("Business name: Raghava Farms", GOOGLE_LEG)
    assert dialects == ["google"]
    assert answer.model == GEMINI and answer.value


async def test_the_business_type_suggestion_asks_on_the_accounts_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the suggestion is asked with no account leg, which skips the Gemini rung."""
    seen: dict[str, Any] = {}

    @contextlib.asynccontextmanager
    async def _session(tenant_id: Any) -> AsyncIterator[None]:
        yield None

    async def _state(tenant_id: Any) -> tuple[bool, bool]:
        return True, False

    async def _context(tenant_id: Any, *, include_type: bool = True) -> tuple[str, None]:
        return "Business name: Raghava Farms", None

    async def _leg(session: Any) -> TenantModelLeg:
        return GOOGLE_LEG

    async def _ask(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise ProblemError.business_rule("assist_provider_unavailable", "x")

    async def _meter(*args: Any, **kwargs: Any) -> None:
        seen["metered_feature"] = kwargs["feature"]

    monkeypatch.setattr(business_type, "tenant_session", _session)
    monkeypatch.setattr(business_type, "_suggestion_state", _state)
    monkeypatch.setattr(business_type, "business_context", _context)
    monkeypatch.setattr(business_type, "account_assist_leg", _leg)
    monkeypatch.setattr(business_type, "ask_json", _ask)
    monkeypatch.setattr(business_type.crm_assist, "meter_refusal", _meter)
    import uuid

    await business_type._suggest(uuid.uuid4())
    assert seen["tenant_leg"] == GOOGLE_LEG
    assert seen["metered_feature"] == ASSIST_FEATURE_BUSINESS_TYPE


def test_an_unusable_answer_is_not_reported_to_the_owner_as_no_ai() -> None:
    """FAILS IF: the agent-test note for an answer the model gave in an unusable shape says
    AI help was not available."""
    note = agent_test_conversations.not_written_note(script_assist.ANSWER_UNUSABLE_CODE)
    assert "not available" not in note
    assert "came back incomplete" in note


# --- the shared client, the alarm and the cached count -----------------------------------


async def test_a_2xx_body_that_is_not_json_is_a_provider_failure_not_a_crash() -> None:
    """FAILS IF: a 200 with an HTML body raises a bare ValueError, which every ladder's
    `httpx.HTTPError` arm lets through as a crash."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    leg = chat.ChatLeg(
        url="https://provider.test/v1", api_key="k", wire_model="m", dialect="openai"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        with pytest.raises(httpx.HTTPError):
            await chat.complete(leg, [], timeout_s=1, client=client)


async def test_the_degraded_alarm_names_the_model_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a watched leg reports its failure with no model, so the alarm reads
    "on model unknown"."""
    seen: dict[str, Any] = {}

    async def _note(
        leg: str, provider: str, exc: BaseException, *, model: str | None = None
    ) -> None:
        seen["model"] = model

    monkeypatch.setattr(provider_health, "note_failure", _note)
    with pytest.raises(httpx.ReadError):
        async with provider_health.watch("ocr", "google", model=GEMINI):
            raise httpx.ReadError("down")
    assert seen["model"] == GEMINI


async def test_the_call_translation_meter_passes_the_cached_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the cached input count is written only into `meta`, so the ledger prices
    every input token at the full rate."""
    seen: dict[str, Any] = {}

    async def _record(session: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(call_translation, "record_ai_assist_usage", _record)
    monkeypatch.setattr(call_translation, "llm_price_is_billable", lambda model: True)
    import uuid

    usage = chat.TokenUsage(
        prompt_tokens=100, output_tokens=10, cached_prompt_tokens=60, cached_reported=True
    )
    await call_translation.meter_language_pass(
        None, uuid.uuid4(), uuid.uuid4(), usage, feature="call_translation", source="test"
    )
    assert seen["cached_tokens_in"] == 60


async def test_the_ocr_reading_carries_the_cached_count_to_its_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a photo reading reports what Google served from its prompt cache and the
    count never reaches the ledger, so every input token is priced at the full rate."""
    from apps.workers import document_ocr

    leg = chat.ChatLeg(
        url="https://provider.test/v1", api_key="k", wire_model=GEMINI, dialect="google"
    )
    usage = chat.TokenUsage(
        prompt_tokens=1200, output_tokens=80, cached_prompt_tokens=1000, cached_reported=True
    )

    async def _read(leg: chat.ChatLeg, image: Any, http: Any) -> tuple[str, None, chat.TokenUsage]:
        return "We open at nine every day of the week.", None, usage

    monkeypatch.setattr(document_ocr, "ocr_leg", lambda: leg)
    monkeypatch.setattr(document_ocr, "_transcribe", _read)
    image = document_ocr.OcrImage(data=b"\xff\xd8\xff", mime_type="image/jpeg", position=1)
    extracted = await document_ocr.ocr_images([image])
    assert extracted.cached_prompt_tokens == 1000
