"""Gemini's NATIVE `streamGenerateContent`, for the one turn the OpenAI-compatible surface
cannot carry: a question with a PDF attached (D-781).

WHY A SECOND GEMINI SURFACE. Pip's Google leg speaks Gemini's OpenAI-compatible endpoint
(`chat.stream`, `google` dialect). That endpoint documents images (`image_url`) and audio
and no PDF input (ai.google.dev/gemini-api/docs/openai, updated 2026-10-13, read 15 Oct
2026); the native API takes a PDF as `inlineData` with `mimeType: application/pdf` and reads
it with native vision, "up to 50MB or 1000 pages", each page "equivalent to 258 tokens"
(ai.google.dev/gemini-api/docs/document-processing, updated 2026-10-08, read 15 Oct 2026).
So a PDF turn — and only a PDF turn — goes here, on the same key, the same model and the
same metering; every other turn stays where it was.

THE SHAPES, from Google's API reference (ai.google.dev/api/generate-content, read
15 Oct 2026): `POST …/v1beta/models/{model}:streamGenerateContent?alt=sse` streams
`GenerateContentResponse` frames; a request carries `contents[]` (role `user` or `model`,
`parts[]`), `systemInstruction`, `tools[].functionDeclarations[]` (whose
`parametersJsonSchema` takes the JSON Schema our tools already have, mutually exclusive with
`parameters`), `toolConfig` and `generationConfig`; a `Part` is `text`, `inlineData`
(`mimeType`, `data`), `functionCall` (`id`, `name`, `args`) or `functionResponse` (`id`,
`name`, `response`), and may carry `thought` / `thoughtSignature`. The key travels in the
`x-goog-api-key` header (ai.google.dev/gemini-api/docs/api-key, updated 2026-10-06), never in
the URL, where it would reach an access log.

THOUGHT SIGNATURES ARE REPLAYED, NOT REBUILT. Google's guide says a stateless caller must
resend the model's turns "exactly as they were received" (ai.google.dev/gemini-api/docs/
thinking, updated 2026-10-14). So the model's parts are kept on `ChatOutcome.native_parts`
and the copilot loop carries them on the assistant message it replays (`_native_parts`);
this module sends them back untouched rather than re-deriving a `functionCall` from the
OpenAI-shaped copy.

NOTHING HERE OPENS A PDF. The bytes arrive base64-encoded from the uploads bucket and go out
the same way.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Final

import httpx

from apps.api.core.logging import get_logger
from apps.workers.chat import ChatLeg, ChatMessage, ChatOutcome, StreamEvent, TokenUsage, ToolCall

log = get_logger(__name__)

#: The content-part type the copilot uses for a PDF in its OpenAI-shaped message list. Only
#: this module understands it, which is the point: a PDF turn cannot reach another leg.
PDF_PART: Final = "pdf_data"

#: Gemini finish reasons, in the words the copilot already acts on (`service.
#: _no_answer_sentence`): a cut answer is `length`, a refused one is a filter.
#: The prefix of an id WE made for a call Gemini sent without one. Never sent back: a
#: response naming an id the model did not issue would describe a call it never made.
_LOCAL_ID: Final = "pipcall_"

_FINISH: Final[dict[str, str]] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "safety",
    "RECITATION": "recitation",
    "BLOCKLIST": "blocklist",
    "PROHIBITED_CONTENT": "safety",
    "SPII": "safety",
}


def _user_parts(content: object) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    parts: list[dict[str, Any]] = []
    for item in content if isinstance(content, list) else []:
        kind = item.get("type") if isinstance(item, Mapping) else None
        if kind == "text":
            parts.append({"text": str(item.get("text", ""))})
        elif kind == "image_url":
            url = str(item["image_url"]["url"])
            header, _, data = url.partition(",")
            mime = header.removeprefix("data:").split(";", 1)[0]
            parts.append({"inlineData": {"mimeType": mime, "data": data}})
        elif kind == PDF_PART:
            parts.append({"inlineData": {"mimeType": "application/pdf", "data": item["data"]}})
    return parts


def request_body(
    messages: Sequence[ChatMessage],
    *,
    tools: Sequence[Mapping[str, Any]] | None,
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    """The OpenAI-shaped message list the copilot builds, as one native request."""
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        if role == "system":
            system.append(str(message.get("content") or ""))
        elif role == "user":
            contents.append({"role": "user", "parts": _user_parts(message.get("content"))})
        elif role == "assistant":
            for call in message.get("tool_calls") or []:
                names[str(call["id"])] = str(call["function"]["name"])
            native = message.get("_native_parts")
            if native:
                contents.append({"role": "model", "parts": [dict(part) for part in native]})
                continue
            parts: list[dict[str, Any]] = []
            if message.get("content"):
                parts.append({"text": str(message["content"])})
            for call in message.get("tool_calls") or []:
                function = {
                    "name": call["function"]["name"],
                    "args": json.loads(call["function"]["arguments"] or "{}"),
                }
                if not str(call["id"]).startswith(_LOCAL_ID):
                    function["id"] = call["id"]
                parts.append({"functionCall": function})
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            call_id = str(message.get("tool_call_id"))
            response: dict[str, Any] = {
                "name": names.get(call_id, ""),
                "response": {"result": str(message.get("content") or "")},
            }
            if not call_id.startswith(_LOCAL_ID):
                response["id"] = call_id
            part = {"functionResponse": response}
            # Results of one model turn travel together in one user turn.
            if (
                contents
                and contents[-1]["role"] == "user"
                and all("functionResponse" in p for p in contents[-1]["parts"])
            ):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
    body: dict[str, Any] = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool["function"]["name"],
                        "description": tool["function"].get("description", ""),
                        "parametersJsonSchema": tool["function"].get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                    for tool in tools
                ]
            }
        ]
        body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
    config: dict[str, Any] = {}
    if temperature is not None:
        config["temperature"] = temperature
    if max_tokens is not None:
        config["maxOutputTokens"] = max_tokens
    if config:
        body["generationConfig"] = config
    return body


def usage_of(frame: Mapping[str, Any]) -> TokenUsage | None:
    """`usageMetadata` as our record. Tool-use prompt tokens are input; thinking tokens are
    billed as output (`totalTokenCount` = prompt + tool-use prompt + thoughts + candidates,
    per the API reference)."""
    meta = frame.get("usageMetadata")
    if not isinstance(meta, Mapping) or "promptTokenCount" not in meta:
        return None

    def count(key: str) -> int:
        value = meta.get(key)
        return int(value) if isinstance(value, int) else 0

    return TokenUsage(
        prompt_tokens=count("promptTokenCount") + count("toolUsePromptTokenCount"),
        output_tokens=count("candidatesTokenCount") + count("thoughtsTokenCount"),
        cached_prompt_tokens=count("cachedContentTokenCount"),
    )


def _frame(line: str) -> Mapping[str, Any] | None:
    if not line.startswith("data:"):
        return None
    try:
        frame = json.loads(line[len("data:") :].strip())
    except ValueError:
        log.warning("gemini_native_frame_unparseable")
        return None
    return frame if isinstance(frame, Mapping) else None


async def stream(
    leg: ChatLeg,
    messages: Sequence[ChatMessage],
    *,
    timeout_s: float,
    temperature: float | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    max_tokens: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[StreamEvent]:
    """`chat.stream`'s contract on the native API: text fragments, then ONE outcome.

    RAISES `httpx.HTTPStatusError` on a non-2xx, read before any frame, as `chat.stream`
    does. `leg.url` is the full `:streamGenerateContent?alt=sse` address.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=timeout_s), follow_redirects=False
    )
    content: list[str] = []
    calls: list[ToolCall] = []
    parts: list[Mapping[str, Any]] = []
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    try:
        async with http.stream(
            "POST",
            leg.url,
            headers={"x-goog-api-key": leg.api_key},
            json=request_body(
                messages, tools=tools, temperature=temperature, max_tokens=max_tokens
            ),
        ) as response:
            if response.is_error:
                await response.aread()
                log.warning(
                    "gemini_native_refused",
                    extra={"status": response.status_code, "model": leg.wire_model},
                )
                response.raise_for_status()
            async for line in response.aiter_lines():
                frame = _frame(line)
                if frame is None:
                    continue
                usage = usage_of(frame) or usage
                candidates = frame.get("candidates") or []
                if not candidates or not isinstance(candidates[0], Mapping):
                    continue
                candidate = candidates[0]
                reason = candidate.get("finishReason")
                if isinstance(reason, str):
                    finish_reason = _FINISH.get(reason, reason.lower())
                body = candidate.get("content")
                for part in (body.get("parts") or []) if isinstance(body, Mapping) else []:
                    if not isinstance(part, Mapping):
                        continue
                    parts.append(part)
                    text = part.get("text")
                    if isinstance(text, str) and text and not part.get("thought"):
                        content.append(text)
                        yield StreamEvent(text=text)
                    call = part.get("functionCall")
                    if isinstance(call, Mapping):
                        calls.append(
                            ToolCall(
                                id=str(call.get("id") or f"{_LOCAL_ID}{uuid.uuid4().hex[:12]}"),
                                name=str(call.get("name", "")),
                                arguments=json.dumps(call.get("args") or {}),
                            )
                        )
    finally:
        if owns_client:
            await http.aclose()
    if calls and finish_reason == "stop":
        finish_reason = "tool_calls"
    yield StreamEvent(
        outcome=ChatOutcome(
            content="".join(content),
            tool_calls=tuple(calls),
            finish_reason=finish_reason,
            usage=usage,
            native_parts=tuple(parts),
        )
    )


__all__ = ["PDF_PART", "request_body", "stream", "usage_of"]
