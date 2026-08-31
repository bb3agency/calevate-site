"""The shared chat client, driven through httpx's real plumbing.

WHY `httpx.MockTransport` AND NOT A HAND-WRITTEN STAND-IN. Every property this file
asserts is a property of a REQUEST or of a byte stream — the header the key travels in,
the keys the body does and does not carry, and the reassembly of frames a provider sends
one at a time. A stand-in for `httpx` could not get any of those wrong, which is exactly
what these tests are trying to catch. Same argument `tests/azure_extraction_test.py` makes
for the extractor it drives.

Nothing here talks to Azure or Sarvam: there is no credential in this environment and
neither host is reachable from it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from calevate_shared.engine import GOOGLE_DIRECT_MODELS

from apps.workers import chat

#: A real selectable Gemini model, SOURCED FROM THE CATALOGUE rather than spelled as a
#: literal here. `tests/sarvam_model_identifier_test.py` keeps every Google model id in
#: `engine.py` and the lifecycle registry alone, so a fixture that needs one reads it back
#: rather than duplicating the string — the centralization the guard exists to hold. `min`
#: only makes the pick deterministic; either member exercises the `google` dialect equally.
_GOOGLE_MODEL = min(GOOGLE_DIRECT_MODELS)

LEG = chat.ChatLeg(
    url="https://example.invalid/openai/v1/chat/completions",
    api_key="k",
    wire_model="dep",
    dialect="openai",
)

#: The same request aimed at the other vendor. Every property below that differs between
#: the two is a property of the ENVELOPE, not of the body — which is why "it is
#: OpenAI-compatible" was not enough to get either of them right.
SARVAM_LEG = chat.ChatLeg(
    url="https://example.invalid/v1/chat/completions",
    api_key="k",
    wire_model="sarvam-105b",
    dialect="sarvam",
)

#: Gemini via Google's OpenAI-compat surface (D-478). Same body and same `Authorization:
#: Bearer` envelope as `openai` (VERIFIED-LIVE, see `chat.ChatDialect`), but NON-STREAMED
#: only — the streaming refusal is the property that keeps `#2806` out of the accumulator.
GOOGLE_LEG = chat.ChatLeg(
    url="https://example.invalid/v1beta/openai/chat/completions",
    api_key="k",
    wire_model=_GOOGLE_MODEL,
    dialect="google",
)


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _sse(*frames: dict[str, Any]) -> bytes:
    return (
        "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n"
    ).encode()


def _chunk(**overrides: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {"object": chat.CHUNK_OBJECT, "choices": [{"index": 0, "delta": {}}]}
    frame.update(overrides)
    return frame


def _stream_client(body: bytes) -> httpx.AsyncClient:
    async def _bytes() -> AsyncIterator[bytes]:
        # One byte-run per SSE frame, so `aiter_lines` has to do real reassembly rather
        # than being handed whole lines by the test.
        for piece in body.split(b"\n\n"):
            if piece:
                yield piece + b"\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_bytes())

    return _client(handler)


# --- the request shape --------------------------------------------------------------


async def test_the_key_travels_as_a_static_bearer_and_optional_keys_are_omitted() -> None:
    """A STATIC KEY in `Authorization: Bearer`, and no key we did not ask for.

    FAILS IF: somebody adds an unconditional `temperature`. `LlmModelSpec.traps` exists
    because a GPT-5 model REJECTS `temperature: 0.1` at agent create — a helper that always
    spelled the key would make every caller's request unserveable on a model none of them
    chose.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async with _client(handler) as client:
        await chat.complete(LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client)

    assert seen["headers"]["authorization"] == "Bearer k"
    assert "api-key" not in seen["headers"]
    assert "api-subscription-key" not in seen["headers"]
    assert seen["body"] == {"model": "dep", "messages": [{"role": "user", "content": "q"}]}


async def test_the_sarvam_leg_sends_its_key_raw_in_the_header_sarvam_actually_reads() -> None:
    """`api-subscription-key: <key>`, with NO `Authorization` header at all.

    THE REGRESSION THIS PINS IS A SHIPPED ONE. `_headers` returned `Authorization: Bearer`
    for every leg under a docstring asserting Sarvam took the same, and it does not:
    VERIFIED-VENDOR-SDK `sarvamai==0.1.31` (PyPI wheel), `core/client_wrapper.py:39` sets
    `headers["api-subscription-key"]` and has no `Authorization` branch, and the same
    wheel's `chat/raw_client.py:189` posts to the very endpoint `SARVAM_CHAT_URL` names.
    So every request on the disclosed fallback leg was a 401 waiting for the first
    deployment configured with a Sarvam key and no Azure one.

    FAILS IF: somebody re-unifies the two headers. The `Authorization` assertion is the
    load-bearing half — sending BOTH would make the leg work and would still be wrong,
    because it puts a credential in a header the vendor does not read and our own log
    redaction reaches by a different entry.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async with _client(handler) as client:
        await chat.complete(
            SARVAM_LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client
        )

    assert seen["headers"]["api-subscription-key"] == "k"
    assert "authorization" not in seen["headers"]


async def test_a_streamed_sarvam_request_omits_the_stream_options_key_sarvam_has_no_slot_for() -> (
    None
):
    """`stream` yes, `stream_options` no.

    VERIFIED-VENDOR-SDK: `sarvamai==0.1.31`, `chat/raw_client.py:191-215` builds its
    request body from a fixed key list that does not include `stream_options`. Sending an
    unknown key risks a 400, which would turn the working fallback into a refusal — and
    we lose nothing by omitting it, because the vendor's `ChatCompletionChunk` carries its
    own optional `usage` block (`types/chat_completion_chunk.py:41`).

    A stream that ends without one leaves `usage is None`, which means "we do not know
    what this cost" and never "it was free" — the direction hard rule 7 requires.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with _client(handler) as client:
        async for _ in chat.stream(
            SARVAM_LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client
        ):
            pass

    assert seen["body"]["stream"] is True
    assert "stream_options" not in seen["body"]


async def test_a_streamed_request_carries_the_output_ceiling_when_asked_and_omits_it_when_not() -> (
    None
):
    """`stream(max_tokens=N)` puts the ceiling on the wire; the default omits the key.

    THE MONEY SHAPE THIS PINS: a stream's read timeout only bounds SILENCE, so before
    `stream()` grew this parameter the only brake on a model that kept talking was the
    caller's wall clock — 90 seconds of paid output tokens on the copilot. FAILS IF: the
    parameter stops reaching `_request_body`, or starts being sent unconditionally (an
    always-spelled optional key is the `temperature` trap, `LlmModelSpec.traps`).
    """
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with _client(handler) as client:
        async for _ in chat.stream(
            LEG, [{"role": "user", "content": "q"}], timeout_s=1, max_tokens=64, client=client
        ):
            pass
        async for _ in chat.stream(
            LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client
        ):
            pass

    assert bodies[0]["max_tokens"] == 64
    assert "max_tokens" not in bodies[1]


async def test_the_google_leg_sends_the_openai_body_and_a_bearer_key() -> None:
    """Gemini's OpenAI-compat surface takes the SAME envelope as OpenAI (D-478).

    VERIFIED-LIVE (the compat `/chat/completions` endpoint probed from this container,
    27 Aug 2026 — see `chat.ChatDialect` for the host and the finding): an anonymous OpenAI
    body returned 400 "Missing or invalid Authorization header", so the endpoint accepts the
    `messages` body and reads the key from `Authorization: Bearer` exactly as the `openai`
    dialect does. This pins that `_headers` folds `google` into the bearer branch and does NOT
    reach for Sarvam's header.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async with _client(handler) as client:
        await chat.complete(
            GOOGLE_LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client
        )

    assert seen["headers"]["authorization"] == "Bearer k"
    assert "api-subscription-key" not in seen["headers"]
    assert seen["body"] == {
        "model": _GOOGLE_MODEL,
        "messages": [{"role": "user", "content": "q"}],
    }


async def test_a_google_completion_returns_a_full_tool_calls_array() -> None:
    """The reason the Gemini leg runs NON-STREAMED: a blocking `complete()` with tools
    returns a clean full `tool_calls` array, so field-filling works without ever meeting the
    `None`-index streaming bug (`openai/openai-python#2806`) `stream()` refuses.

    FAILS IF: `complete` stops reading `tool_calls`, or the google leg stops being served by
    the same non-streamed path as every other dialect.
    """
    tools = [{"type": "function", "function": {"name": "fill_field", "parameters": {}}}]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == tools
        assert body["model"] == _GOOGLE_MODEL
        assert "stream" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "fill_field",
                                        "arguments": '{"name":"Asha"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    async with _client(handler) as client:
        outcome = await chat.complete(
            GOOGLE_LEG,
            [{"role": "user", "content": "q"}],
            timeout_s=1,
            tools=tools,
            client=client,
        )

    assert outcome.tool_calls == (
        chat.ToolCall(id="c1", name="fill_field", arguments='{"name":"Asha"}'),
    )
    assert outcome.finish_reason == "tool_calls"
    assert outcome.usage == chat.TokenUsage(prompt_tokens=12, output_tokens=4)


async def test_streaming_the_google_dialect_is_refused_loud() -> None:
    """`stream()` on the Gemini leg RAISES rather than corrupt the by-index accumulator.

    Gemini's streamed tool-call deltas can carry a `None` `index` (`openai/openai-python
    #2806`, read 27 Aug 2026); `_ToolCallAccumulator` drops a fragment with no index, silently
    losing a tool call's arguments. So the leg runs non-streamed and a caller that reaches for
    `stream()` is made to fail loud — no request is issued.

    FAILS IF: the refusal is removed, or a fourth dialect is added to the bearer branch
    without deciding whether it, too, is stream-unsafe.
    """
    issued = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        nonlocal issued
        issued = True
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with _client(handler) as client:
        with pytest.raises(ValueError, match="must not be streamed"):
            async for _ in chat.stream(
                GOOGLE_LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client
            ):
                pass

    assert issued is False, "the refusal must fire before any request leaves"


async def test_a_streamed_request_asks_for_usage() -> None:
    """`stream_options: {"include_usage": true}`, or the final usage chunk never arrives
    and every streamed answer is unmeterable."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with _client(handler) as client:
        async for _ in chat.stream(
            LEG, [{"role": "user", "content": "q"}], timeout_s=1, client=client
        ):
            pass

    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}


# --- the two Azure stream traps ------------------------------------------------------


async def test_an_azure_content_filter_annotation_frame_is_discarded_mid_stream() -> None:
    """The frame Microsoft's own issue #3650 records verbatim, dropped rather than parsed.

    `{"id":"","choices":[],"created":0,"model":"","object":"",...}` is what the
    asynchronous content filter emits, and it can arrive at any point in the stream rather
    than only first. Feeding one into an index-addressed accumulator corrupts `choices[0]`.

    FAILS IF: the frame filter is relaxed to "skip the first frame" or to "skip empty
    choices" — this one is placed BETWEEN two content frames and carries a `choices` key
    that a naive reader would happily index.
    """
    annotation = {
        "id": "",
        "choices": [],
        "created": 0,
        "model": "",
        "object": "",
        "prompt_filter_results": [{"prompt_index": 0, "content_filter_results": {}}],
    }
    body = _sse(
        _chunk(choices=[{"index": 0, "delta": {"content": "Hel"}}]),
        annotation,
        _chunk(choices=[{"index": 0, "delta": {"content": "lo"}}, {"index": 1, "delta": {}}]),
        _chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]),
    )
    async with _stream_client(body) as client:
        events = [e async for e in chat.stream(LEG, [], timeout_s=1, client=client)]

    assert [e.text for e in events if e.text is not None] == ["Hel", "lo"]
    outcome = events[-1].outcome
    assert outcome is not None
    assert outcome.content == "Hello"
    assert outcome.finish_reason == "stop"


async def test_tool_call_fragments_are_reassembled_by_index_not_by_position() -> None:
    """OpenAI's accumulator: address by `index`, replace `index`/`type`, concatenate
    strings, recurse dicts.

    TWO PARALLEL CALLS, INTERLEAVED, and the second one's fragments arrive FIRST in one
    frame. A reader that appended by list position would splice the two sets of arguments
    into one unparseable string — which is the defect `index` exists in the payload to
    prevent, and the only field the vendor marks required on the chunk.
    """
    body = _sse(
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "b",
                                "type": "function",
                                "function": {"name": "second", "arguments": '{"x'},
                            },
                            {
                                "index": 0,
                                "id": "a",
                                "type": "function",
                                "function": {"name": "set_", "arguments": '{"items'},
                            },
                        ]
                    },
                }
            ]
        ),
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"name": "fields", "arguments": '": []}'}},
                            {"index": 1, "function": {"arguments": '": 1}'}},
                        ]
                    },
                }
            ]
        ),
        _chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]),
    )
    async with _stream_client(body) as client:
        events = [e async for e in chat.stream(LEG, [], timeout_s=1, client=client)]

    outcome = events[-1].outcome
    assert outcome is not None
    assert [(c.id, c.name, c.arguments) for c in outcome.tool_calls] == [
        ("a", "set_fields", '{"items": []}'),
        ("b", "second", '{"x": 1}'),
    ]


# --- the money question --------------------------------------------------------------


async def test_a_missing_final_usage_chunk_is_none_and_never_zero() -> None:
    """The vendor's own note: "If the stream is interrupted or cancelled, you may not
    receive the final usage chunk". That is its own outcome.

    FAILS IF: `ChatOutcome.usage` ever defaults to `TokenUsage(0, 0)`. A fabricated zero on
    an append-only ledger is indistinguishable from a real one and moves neither the
    tenant's ceiling nor the platform brake (hard rule 7, D-140).
    """
    body = _sse(_chunk(choices=[{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}]))
    async with _stream_client(body) as client:
        events = [e async for e in chat.stream(LEG, [], timeout_s=1, client=client)]

    outcome = events[-1].outcome
    assert outcome is not None
    assert outcome.usage is None


async def test_the_final_usage_chunk_is_read_off_a_frame_with_no_choices() -> None:
    """The usage frame carries an EMPTY `choices` array by contract, so a reader that only
    looked at frames with choices would never see it."""
    body = _sse(
        _chunk(choices=[{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}]),
        _chunk(choices=[], usage={"prompt_tokens": 1200, "completion_tokens": 800}),
    )
    async with _stream_client(body) as client:
        events = [e async for e in chat.stream(LEG, [], timeout_s=1, client=client)]

    outcome = events[-1].outcome
    assert outcome is not None
    assert outcome.usage == chat.TokenUsage(prompt_tokens=1200, output_tokens=800)


def test_completion_token_details_are_a_breakdown_and_are_not_added() -> None:
    """Summing `completion_tokens_details` into `completion_tokens` bills a tenant twice
    for the same tokens. Vertex's `thoughtsTokenCount` WAS separate and had to be summed;
    porting that line across is the tempting edit and it is wrong in the expensive
    direction."""
    usage = chat.usage_from_body(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 15},
            }
        }
    )
    assert usage == chat.TokenUsage(prompt_tokens=10, output_tokens=20)


def test_no_usage_block_and_an_all_zero_one_both_read_as_unknown() -> None:
    assert chat.usage_from_body({}) is None
    assert chat.usage_from_body({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}) is None


# --- the shapes a provider declining to answer produces ------------------------------


async def test_an_empty_choices_array_is_no_answer_rather_than_an_indexerror() -> None:
    """Azure's content filter is an ordinary 200 with `choices: []`. Indexing blindly turns
    "the model said nothing" into an IndexError that escapes `extract_call`'s ladder and
    fails a whole post-call job — losing the call to keep the fields."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    async with _client(handler) as client:
        outcome = await chat.complete(LEG, [], timeout_s=1, client=client)
    assert outcome.content == "" and outcome.tool_calls == ()


async def test_a_null_content_is_no_answer_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    async with _client(handler) as client:
        outcome = await chat.complete(LEG, [], timeout_s=1, client=client)
    assert outcome.content == ""


async def test_a_non_2xx_raises_so_a_caller_can_read_the_status() -> None:
    """`extract_call`'s ladder already catches `httpx.HTTPError`, and the two callers that
    degrade from Structured Outputs need the 400. A helper that returned an error object
    instead would put an `if` on every caller's happy path."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "unsupported"}})

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await chat.complete(LEG, [], timeout_s=1, client=client)
    assert raised.value.response.status_code == 400


async def test_a_streamed_non_2xx_raises_before_any_frame_is_read() -> None:
    """So `run_copilot` can still fall back to the disclosed second leg — which it may only
    do while nothing has been streamed to the person yet."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in chat.stream(LEG, [], timeout_s=1, client=client):
                pass


async def test_an_unparseable_frame_is_dropped_rather_than_ending_the_stream() -> None:
    body = b"data: {not json\n\n" + _sse(
        _chunk(choices=[{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}])
    )
    async with _stream_client(body) as client:
        events = [e async for e in chat.stream(LEG, [], timeout_s=1, client=client)]
    assert [e.text for e in events if e.text is not None] == ["ok"]
