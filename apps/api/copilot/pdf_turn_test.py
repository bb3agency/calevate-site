"""A question with a PDF (D-781): Gemini reads the PDF natively; if that fails, Gemini on
Pip's usual leg reads the browser-extracted text and the answer says so; if that fails too, or
the PDF had no text, the question is refused. Never Azure, never Sarvam.

Both transports are faked at their module seams (`gemini_native.stream`, `chat.stream`) and
every leg they are handed is recorded, which is what proves which companies a PDF turn
reached. `request_body` and the native stream parser are tested against Google's documented
shapes with a fake HTTP transport.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from calevate_shared.engine import (
    PLATFORM_DEFAULT_LLM_MODEL,
    google_native_base_url,
    google_openai_compat_base_url,
)

from apps.api.copilot import attachments, service
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.workers import chat, gemini_native
from apps.workers.extraction import AssistCapability, TenantModelLeg

MODEL = PLATFORM_DEFAULT_LLM_MODEL
PDF_B64 = "JVBERi0xLjcKJeLjz9M="  # "%PDF-1.7\n%..."


def _payload() -> CopilotAskIn:
    return CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/leads", "title": "Leads", "realm": "client"},
            "question": "what does tea cost?",
        }
    )


def _attached(text: str | None = "Page 1\nTea 20") -> attachments.Attached:
    extracted = (
        attachments.AttachedText(name="menu.pdf (text only)", text=text, truncated=False)
        if text is not None
        else None
    )
    return attachments.Attached(
        pdfs=(attachments.AttachedPdf(name="menu.pdf", data=PDF_B64, text=extracted),)
    )


GOOGLE = AssistCapability(available=True, provider="google")
LEG = TenantModelLeg(model=MODEL, provider="google", serves_dashboard=True)


class Legs:
    """Records every leg a transport was handed, and plays a script per transport."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, native: str, usual: str) -> None:
        self.calls: list[tuple[str, str, list[Any]]] = []
        monkeypatch.setattr(get_settings(), "gemini_api_key", "g-key", raising=False)
        monkeypatch.setattr(service, "assist_capability", lambda **_: GOOGLE)

        def fake(kind: str, mode: str) -> Any:
            def stream(leg: chat.ChatLeg, messages: Any, **kwargs: Any) -> AsyncIterator[Any]:
                self.calls.append((kind, leg.url, list(messages)))

                async def events() -> AsyncIterator[chat.StreamEvent]:
                    if mode == "fail":
                        raise httpx.HTTPStatusError(
                            "400",
                            request=httpx.Request("POST", leg.url),
                            response=httpx.Response(400),
                        )
                    yield chat.StreamEvent(text=f"Tea is 20 ({kind}).")
                    yield chat.StreamEvent(
                        outcome=chat.ChatOutcome(
                            content=f"Tea is 20 ({kind}).",
                            finish_reason="stop",
                            usage=chat.TokenUsage(prompt_tokens=600, output_tokens=8),
                        )
                    )

                return events()

            return stream

        monkeypatch.setattr(gemini_native, "stream", fake("native", native))
        monkeypatch.setattr(chat, "stream", fake("usual", usual))


async def _run(attached: attachments.Attached) -> list[service.CopilotEvent]:
    return [
        event
        async for event in service.run_copilot(
            _payload(), tenant_leg=LEG, attached=attached, allow_azure=True
        )
    ]


def _text(events: list[service.CopilotEvent]) -> str:
    return "".join(event.text for event in events if event.text)


async def test_gemini_reads_the_pdf_itself_on_its_native_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legs = Legs(monkeypatch, native="ok", usual="ok")
    events = await _run(_attached())
    assert [kind for kind, _, _ in legs.calls] == ["native"]
    _, url, messages = legs.calls[0]
    assert url == f"{google_native_base_url()}/models/{MODEL}:streamGenerateContent?alt=sse"
    last = messages[-1]["content"]
    assert {"type": gemini_native.PDF_PART, "data": PDF_B64} in last
    assert _text(events) == "Tea is 20 (native)."
    spends = [event.spend for event in events if event.spend]
    assert len(spends) == 1 and spends[0].model == MODEL


async def test_a_failed_native_read_falls_back_to_the_text_on_the_usual_gemini_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legs = Legs(monkeypatch, native="fail", usual="ok")
    events = await _run(_attached())
    assert [kind for kind, _, _ in legs.calls] == ["native", "usual"]
    _, url, messages = legs.calls[1]
    assert url == f"{google_openai_compat_base_url()}/chat/completions"
    body = messages[-1]["content"]
    # Text only: no PDF part, the extracted text fenced as an attachment.
    assert isinstance(body, str)
    assert "<attachment name='menu.pdf (text only)'>" in body or (
        '<attachment name="menu.pdf (text only)">' in body
    )
    assert "Tea 20" in body
    assert _text(events).startswith(attachments.PDF_TEXT_ONLY_NOTE)


async def test_both_gemini_paths_failing_refuse_and_reach_nobody_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legs = Legs(monkeypatch, native="fail", usual="fail")
    with pytest.raises(ProblemError) as refused:
        await _run(_attached())
    assert refused.value.code == "copilot_pdf_unavailable"
    assert "can't take PDFs right now. Try again in a little while." in refused.value.detail
    assert [kind for kind, _, _ in legs.calls] == ["native", "usual"]
    assert all(url.startswith(google_native_base_url()) for _, url, _ in legs.calls)


async def test_a_scanned_pdf_with_gemini_unable_to_read_it_is_refused_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legs = Legs(monkeypatch, native="fail", usual="ok")
    with pytest.raises(ProblemError) as refused:
        await _run(_attached(text=None))
    assert refused.value.code == "copilot_pdf_unavailable"
    assert [kind for kind, _, _ in legs.calls] == ["native"]


@pytest.mark.parametrize("provider", ["azure", "sarvam"])
async def test_a_pdf_turn_whose_leg_is_not_google_is_refused_without_a_call(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    legs = Legs(monkeypatch, native="ok", usual="ok")
    monkeypatch.setattr(
        service,
        "assist_capability",
        lambda **_: AssistCapability(available=True, provider=provider, fallback_reason="x"),
    )
    with pytest.raises(ProblemError) as refused:
        await _run(_attached())
    assert refused.value.code == "copilot_pdf_unavailable"
    assert legs.calls == []


# --- the native wire ------------------------------------------------------------------------


def test_the_native_request_carries_the_pdf_tools_and_the_replayed_turn_as_google_documents() -> (
    None
):
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are Pip."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what does tea cost?"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/AA"}},
                {"type": gemini_native.PDF_PART, "data": PDF_B64},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c-1", "type": "function", "function": {"name": "leads", "arguments": "{}"}}
            ],
            "_native_parts": [
                {
                    "functionCall": {"id": "c-1", "name": "leads", "args": {}},
                    "thoughtSignature": "SIG",
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c-1", "content": "3 leads"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "leads",
                "description": "Find leads.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
    ]
    body = gemini_native.request_body(messages, tools=tools, temperature=0.2, max_tokens=4096)
    assert body["systemInstruction"] == {"parts": [{"text": "You are Pip."}]}
    user, model, results = body["contents"]
    assert user["parts"][1] == {"inlineData": {"mimeType": "image/jpeg", "data": "/9j/AA"}}
    assert user["parts"][2] == {"inlineData": {"mimeType": "application/pdf", "data": PDF_B64}}
    # The model's turn is replayed EXACTLY, signature and all.
    assert model == {
        "role": "model",
        "parts": [
            {"functionCall": {"id": "c-1", "name": "leads", "args": {}}, "thoughtSignature": "SIG"}
        ],
    }
    assert results == {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": "leads", "response": {"result": "3 leads"}, "id": "c-1"}}
        ],
    }
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["parametersJsonSchema"]["additionalProperties"] is False
    assert "parameters" not in declaration
    assert body["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 4096}


async def test_the_native_stream_yields_text_calls_usage_and_keeps_the_parts() -> None:
    frames = [
        {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": "Thinking", "thought": True}]}}
            ]
        },
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Tea "}]}}]},
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"text": "is 20."},
                            {
                                "functionCall": {"name": "leads", "args": {"q": "tea"}},
                                "thoughtSignature": "S",
                            },
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 900,
                "toolUsePromptTokenCount": 10,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 5,
                "cachedContentTokenCount": 100,
            },
        },
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    leg = chat.ChatLeg(
        url="https://x.test/v1beta/models/m:streamGenerateContent?alt=sse",
        api_key="K",
        wire_model="m",
        dialect="google",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in gemini_native.stream(
                leg, [{"role": "user", "content": "hi"}], timeout_s=5, client=client
            )
        ]
    assert seen[0].headers["x-goog-api-key"] == "K"
    assert "key=" not in str(seen[0].url)
    assert [event.text for event in events if event.text] == ["Tea ", "is 20."]
    outcome = events[-1].outcome
    assert outcome is not None
    assert outcome.finish_reason == "tool_calls"
    assert outcome.usage == chat.TokenUsage(
        prompt_tokens=910, output_tokens=25, cached_prompt_tokens=100
    )
    [call] = outcome.tool_calls
    assert call.name == "leads" and json.loads(call.arguments) == {"q": "tea"}
    assert any(part.get("thoughtSignature") == "S" for part in outcome.native_parts)
    # A call Gemini sent without an id gets one of ours, which is never sent back.
    replay = gemini_native.request_body(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": "leads", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call.id, "content": "ok"},
        ],
        tools=None,
        temperature=None,
        max_tokens=None,
    )
    assert "id" not in replay["contents"][0]["parts"][0]["functionCall"]
    assert "id" not in replay["contents"][1]["parts"][0]["functionResponse"]


async def test_a_refused_native_request_raises_before_any_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad"}})

    leg = chat.ChatLeg(url="https://x.test/m", api_key="K", wire_model="m", dialect="google")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in gemini_native.stream(leg, [], timeout_s=5, client=client):
                pass


# --- the policy -----------------------------------------------------------------------------


def test_pdfs_are_allowed_and_bounded_for_the_inline_request() -> None:
    assert attachments.stored_type_for("menu.pdf", "application/pdf") == "application/pdf"
    assert attachments.kind_of("application/pdf") == "pdf"
    assert attachments.limit_for("application/pdf") == attachments.MAX_PDF_BYTES
    # 14 MiB of PDF is ~18.7 MB of base64, inside Gemini's 20 MB inline request.
    assert attachments.MAX_PDF_BYTES * 4 / 3 < 20_000_000
    assert attachments.signature_matches("application/pdf", b"%PDF-1.7\n")
    assert not attachments.signature_matches("application/pdf", b"\xff\xd8\xff")


def test_without_text_a_pdf_has_no_text_only_form() -> None:
    assert _attached(text=None).as_text_only() is None
    text_only = _attached().as_text_only()
    assert text_only is not None and text_only.pdfs == ()
    assert [item.name for item in text_only.texts] == ["menu.pdf (text only)"]
