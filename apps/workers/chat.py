"""ONE OpenAI-compatible chat completion, for every surface in this repository that makes
one — blocking or streamed, with tools or without.

WHY THIS FILE EXISTS. There were three hand-rolled `httpx.post(... "/chat/completions")`
bodies in this tree — `AzureOpenAIExtractor.run`, `SarvamExtractor.run` and
`script_assist._draft_via_azure`/`_draft_via_sarvam` — and each one had independently
re-derived the same four facts: the key travels in `Authorization: Bearer`, the wire
`model` is the DEPLOYMENT on Azure and the model id on Sarvam, `choices` can come back
empty when the provider declines, and `usage` may be absent. Three copies of four facts is
the shape CLAUDE.md's "one way per problem, and migrate rather than accumulate" names as a
defect even when every copy works: the fourth caller (the in-app copilot) needed TOOLS and
STREAMING, neither of which any copy had, and adding them to one copy would have made the
three permanently different.

**AND THE FIRST OF THOSE FOUR FACTS WAS FALSE, WHICH IS THE BEST ARGUMENT THIS FILE HAS.**
The key does NOT travel in `Authorization: Bearer` on both legs — Sarvam reads it from
`api-subscription-key` and reads nothing else (`ChatDialect`, `_AUTH_HEADER`). Three
copies of a wrong fact is three sites to find; one copy was one edit. The lesson for the
next reader is the sharper half: consolidating did not DISCOVER the error, because the
error was consistent everywhere. Reading the vendor's own client did.

WHAT IS AND IS NOT IN HERE. This module knows the OpenAI chat wire format and nothing
else. It does not know what a transcript is, what an extraction schema is, which provider
should serve a request (`extraction.assist_capability` is the ONE selector), what a token
costs (`billing/rates.llm_inr_per_ktok`), or how to build an endpoint
(`calevate_shared.engine.azure_openai_base_url` is the one builder and
`scripts/check_model_residency.py` proves it). A `ChatLeg` arrives already addressed.

HARD RULE 6 THROUGHOUT: no function here logs a message, a delta, a tool argument or a
response body. Every log line is a status code, a wire model name and a count. Provider
error bodies quote the request, and on some callers the request is a call transcript.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import httpx

from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: A chat message, in the vendor's own vocabulary (`role`, `content`, `tool_calls`,
#: `tool_call_id`). Deliberately a plain mapping rather than a typed model: this is the
#: wire shape, the four roles carry four different key sets, and a Pydantic model over it
#: would be a second, lossier spelling of a schema OpenAI already publishes. Callers build
#: it; nothing here inspects it.
ChatMessage = Mapping[str, Any]

#: The only `object` value an OpenAI-compatible stream frame may carry and still be a
#: piece of the completion.
#:
#: **AZURE EMITS FRAMES THAT ARE NOT.** With the asynchronous content filter enabled, the
#: first frame of a stream is an annotation carrying `prompt_filter_results` and NOTHING
#: else: `{"id":"","choices":[],"created":0,"model":"","object":"",...}` — verbatim, from
#: Microsoft's own `microsoft/semantic-kernel` issue #3650 (read 27 Aug 2026;
#: `learn.microsoft.com` is egress-blocked from this environment, so that repository issue
#: is the primary source actually read rather than the docs page it describes). Feeding
#: one into an index-addressed accumulator corrupts `choices[0]`, and every reported
#: symptom of it is an `AttributeError` on `NoneType` several frames later.
#:
#: Checked POSITIVELY (`== CHUNK_OBJECT`) rather than by refusing the empty string: a
#: frame this module does not recognise is not a piece of a completion, whatever it is,
#: and an allow-list cannot be widened by a vendor shipping a third annotation shape.
CHUNK_OBJECT: Final = "chat.completion.chunk"

#: `stream_options` as every streamed call in this repository sends it.
#:
#: VERIFIED (openai/openai-openapi `openapi.yaml` @ master, read 27 Aug 2026): "If set, an
#: additional chunk will be streamed before the `data: [DONE]` message. The `usage` field
#: on this chunk shows the token usage statistics for the entire request, and the `choices`
#: field will always be an empty array." The same document carries the warning that makes
#: this a MONEY question rather than a telemetry one: "**NOTE:** If the stream is
#: interrupted or cancelled, you may not receive the final usage chunk which contains the
#: total token usage for the request."
#:
#: So a stream that ends without one leaves `ChatOutcome.usage is None`, which throughout
#: this repository means "we do not know what this cost" and never "it was free"
#: (`usage_from_body`, `crm/assist.py::meter_assist`). Hard rule 7 is why the two may not
#: collapse: a fabricated zero on an append-only ledger is indistinguishable from a real
#: one, and it moves neither the tenant's ceiling nor the platform brake.
STREAM_OPTIONS: Final[dict[str, Any]] = {"include_usage": True}


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What one model call cost, in the vendor's own count.

    Tokens, not thousands: `billing/ai_quota.ktok()` converts, once, where the money is,
    because `qty` is `NUMERIC` and a division done here would arrive as a float.

    MOVED HERE FROM `workers/extraction.py` (which re-exports it, so every existing
    importer is unchanged) because it is a property of the WIRE FORMAT, not of extraction:
    three surfaces now read a `usage` block off the same JSON and there is one definition
    of what they read.
    """

    prompt_tokens: int
    output_tokens: int

    def plus(self, other: TokenUsage) -> TokenUsage:
        """The two turns of one multi-turn assist as one metered quantity.

        A tool-calling loop pays for every turn, so the thing that reaches the ledger is
        the SUM — the alternative is N `usage_events` rows for one user action, which
        would move `read_ai_quota`'s `requests_used` (a `COUNT(DISTINCT ref)`) by N and
        make the request count and the rupee ceiling disagree about the same month.
        """
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


def usage_from_body(body: Mapping[str, Any]) -> TokenUsage | None:
    """A response's `usage` block as our own record, or None if it did not send one.

    NONE IS NOT ZERO and the difference is a billing one: a missing block means we do not
    know what this call cost, and metering it as zero would quietly give one tenant a free
    assist and move the platform brake by nothing. `record_ai_assist_usage` is therefore
    never called on a None, and that is the caller's rule to keep.

    `completion_tokens` IS THE WHOLE OUTPUT LEG AND NOTHING IS ADDED TO IT. On the OpenAI
    wire format `completion_tokens_details` is a BREAKDOWN of `completion_tokens`, not an
    addition to it, and summing them would bill a tenant twice for the same tokens. (Vertex
    reported `thoughtsTokenCount` separately and had to be summed — porting that line
    across is the tempting edit and it is wrong in the expensive direction. D-410 left
    Vertex; the warning stays because the edit is still tempting.)
    """
    raw = body.get("usage")
    if not isinstance(raw, dict):
        return None

    def _count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    total_in = _count("prompt_tokens")
    total_out = _count("completion_tokens")
    if total_in == 0 and total_out == 0:
        return None
    return TokenUsage(prompt_tokens=total_in, output_tokens=total_out)


#: WHICH VENDOR'S SPELLING OF THE OPENAI CHAT FORMAT A LEG SPEAKS.
#:
#: "OpenAI-compatible" is a claim about the BODY, and both our providers honour it. It is
#: not a claim about the envelope, and this repository shipped for months believing it
#: was: the credential header and the set of optional request keys a provider will accept
#: both differ, and neither difference is visible from the response of a request that
#: works.
#:
#: TWO MEMBERS, NOT A BOOLEAN, and not a per-difference flag either. A `sends_bearer:
#: bool` beside a `supports_stream_options: bool` would let a caller assemble a
#: combination no vendor implements, which is how a "configuration" grows states nobody
#: has ever run. A closed vocabulary of vendors we have actually read the client for
#: cannot: each member is a citation, and adding one means reading a third vendor's
#: client first.
ChatDialect = Literal["openai", "sarvam"]


@dataclass(frozen=True, slots=True)
class ChatLeg:
    """Where one chat completion goes, already addressed.

    `wire_model` is the string that goes in the request's `model` field, and it is NOT
    always the model we meter. On Azure it is the DEPLOYMENT — you deploy a model under an
    id you choose and call THAT id (D-410/D-417) — while the ledger names the model, so the
    field is spelled for what it holds rather than "model". On Sarvam the two coincide.

    NO BUILDER HERE, deliberately. `azure_openai_base_url()` in
    `packages/shared/src/calevate_shared/engine.py` is the single constructor
    `scripts/check_model_residency.py` grants the tree's one host literal to; a second
    place that assembled a URL would be the exact thing that check exists to refuse.

    **`dialect` HAS NO DEFAULT, AND THAT IS THE FIX RATHER THAN AN INCONVENIENCE.** The
    defect this field exists to close was a DEFAULT: `_headers` returned
    `Authorization: Bearer` for every leg, under a docstring asserting that Sarvam took
    the same, and the assertion was simply false. A default here would have carried that
    bug forward for whichever leg somebody forgot — so every construction site names its
    vendor, mypy refuses the ones that do not, and getting it wrong requires typing the
    wrong vendor rather than typing nothing.
    """

    url: str
    api_key: str
    wire_model: str
    dialect: ChatDialect


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool the model asked for, with its arguments STILL AS TEXT.

    Unparsed on purpose. The vendor's own OpenAPI says of this field: "Note that the model
    does not always generate valid JSON, and may hallucinate parameters not defined by your
    function schema. Validate the arguments in your code before calling your function."
    (openai/openai-openapi `openapi.yaml` @ master, `ChatCompletionMessageToolCallChunk`,
    read 27 Aug 2026.) A parse here would put the failure inside the transport, where the
    caller cannot turn it into a message a person can act on.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatOutcome:
    """One completed model turn: what it said, what it asked for, and what it cost.

    `usage is None` means the provider did not tell us — never that it was free. See
    `STREAM_OPTIONS`.

    `finish_reason is None` after a STREAM means the stream ended without a terminal
    frame, which is the interruption the vendor's note above warns about. Callers that
    meter must read it: a `None` finish reason beside a `None` usage is an outage, not a
    free answer.
    """

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One step of a streamed turn: a text fragment, or the finished turn.

    Exactly one of the two is set, and the `outcome` event is emitted exactly once, last.
    A union of two dataclasses would read better and would make every caller write an
    `isinstance` ladder for a two-member union; one frozen record with two optional slots
    is the shape the two consumers actually want (`if event.outcome is not None`).
    """

    text: str | None = None
    outcome: ChatOutcome | None = None


#: The credential header each dialect actually reads, from each vendor's OWN client.
#:
#: * `openai` — `Authorization: Bearer`. Azure's v1 surface takes a static key in exactly
#:   this header (D-410): never an `api-key:` header, never a query parameter, never an
#:   OAuth handshake.
#: * `sarvam` — `api-subscription-key`, and NOTHING ELSE. VERIFIED-VENDOR-SDK:
#:   `sarvamai==0.1.31` (PyPI wheel), `core/client_wrapper.py:39`, read 27 Aug 2026 —
#:   `get_headers()` builds a User-Agent and five Fern telemetry headers and then sets
#:   `headers["api-subscription-key"]`. There is no `Authorization` branch in it at all.
#:   The same SDK's `chat/raw_client.py:189` posts to `v1/chat/completions` against base
#:   `https://api.sarvam.ai`, which is `SARVAM_CHAT_URL` character for character — so this
#:   is the vendor's own client hitting our exact endpoint with a different credential
#:   header than we were sending.
#:
#: **WHAT THIS COST, said plainly because the shape is more instructive than the fix.**
#: The line this replaces sent Bearer on both legs, and the docstring above it asserted
#: that Sarvam "takes the same" — an assertion nobody could have made from a source,
#: because the leg has never been exercised: this environment holds no Sarvam key and
#: `api.sarvam.ai` is egress-blocked from it. So the disclosed Sarvam fallback — the rung
#: `assist_capability` drops to when Azure is absent, which is the rung a deployment with
#: only a Sarvam key runs on for EVERY assist — would have 401'd on its first request, and
#: the symptom would have been "the assistant is broken" on a console, not a wire error
#: anyone was watching. Hard rule 11 is the rule this violated, and it violated it in the
#: costly direction: the value was in our own code, which made it look verified.
_AUTH_HEADER: Final[dict[ChatDialect, str]] = {
    "openai": "Authorization",
    "sarvam": "api-subscription-key",
}


def _headers(leg: ChatLeg) -> dict[str, str]:
    """This leg's credential, in the header ITS vendor reads.

    The key travels raw on `sarvam` and prefixed on `openai`, which is the vendors'
    difference and not a choice of ours. `core/logging.REDACT_KEYS` masks both names, so
    neither reaches a log by either spelling — check there before adding a third.
    """
    if leg.dialect == "sarvam":
        return {_AUTH_HEADER["sarvam"]: leg.api_key}
    return {_AUTH_HEADER["openai"]: f"Bearer {leg.api_key}"}


def _request_body(
    leg: ChatLeg,
    messages: Sequence[ChatMessage],
    *,
    temperature: float | None,
    response_format: Mapping[str, Any] | None,
    tools: Sequence[Mapping[str, Any]] | None,
    tool_choice: str | Mapping[str, Any] | None,
    stream: bool,
) -> dict[str, Any]:
    """The request, with every optional key OMITTED rather than sent as null.

    Omission is not tidiness: `temperature` is the worked example. Sending
    `temperature: 0.1` unconditionally is what a GPT-5 model rejects at agent CREATE
    (CLAUDE.md's `LlmModelSpec.traps`), so a helper that always spelled the key would make
    every caller's request unserveable on a model none of them chose. `None` means "do not
    mention it".
    """
    body: dict[str, Any] = {"model": leg.wire_model, "messages": list(messages)}
    if temperature is not None:
        body["temperature"] = temperature
    if response_format is not None:
        body["response_format"] = dict(response_format)
    if tools:
        body["tools"] = [dict(tool) for tool in tools]
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
    if stream:
        body["stream"] = True
        # `stream_options` IS AN OPENAI-DIALECT KEY AND SARVAM'S REQUEST HAS NO SLOT FOR
        # IT. VERIFIED-VENDOR-SDK: `sarvamai==0.1.31` (PyPI wheel),
        # `chat/raw_client.py:191-215`, read 27 Aug 2026 — the vendor's own client builds
        # its request body from exactly fourteen keys (`messages`, `model`, `temperature`,
        # `top_p`, `reasoning_effort`, `max_tokens`, `stream`, `stop`, `n`, `seed`,
        # `frequency_penalty`, `presence_penalty`, `wiki_grounding`, `tools`,
        # `tool_choice`) and `stream_options` is not among them.
        #
        # WHY OMITTING IT COSTS US NOTHING HERE, which is the part worth checking before
        # assuming a degradation. `STREAM_OPTIONS` exists to make the provider append a
        # final usage-bearing frame; Sarvam's `ChatCompletionChunk` carries an optional
        # `usage` block of its own (`types/chat_completion_chunk.py:41`, same wheel), so
        # `usage_from_body` reads a Sarvam stream by the same path it reads an Azure one.
        # If a Sarvam stream turns out to end without one, `ChatOutcome.usage` is `None`,
        # which throughout this repository means "we do not know what this cost" and never
        # "it was free" — the safe direction, and the one hard rule 7 requires.
        if leg.dialect == "openai":
            body["stream_options"] = dict(STREAM_OPTIONS)
    return body


def _message_of(body: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    """The one message of a non-streamed answer, and its finish reason.

    `choices` comes back EMPTY, or carries a null `content`, when the provider declines to
    answer — Azure's content filter is an ordinary response with
    `finish_reason: "content_filter"`, not an exception, and Structured Outputs adds a
    model-authored `refusal` beside `content` on the same footing. Neither is read: the
    refusal is the model's prose about the caller's own input, which is not a thing this
    module logs or returns (hard rule 6), and both land as "no answer". Indexing blindly
    turns "the model said nothing" into an IndexError, and losing the call to keep the
    fields is the wrong trade.
    """
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return {}, None
    first = choices[0]
    message = first.get("message")
    return (message if isinstance(message, dict) else {}), first.get("finish_reason")


def _tool_calls_of(message: Mapping[str, Any]) -> tuple[ToolCall, ...]:
    """`message.tool_calls` as our own records, skipping anything malformed.

    A tool call with no `function.name` is not a tool call; dropping it here means the
    caller sees "the model asked for nothing", which is a state it already handles, rather
    than a `KeyError` inside a request handler.
    """
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return ()
    calls: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        arguments = function.get("arguments")
        calls.append(
            ToolCall(
                id=str(entry.get("id") or ""),
                name=name,
                arguments=arguments if isinstance(arguments, str) else "",
            )
        )
    return tuple(calls)


async def complete(
    leg: ChatLeg,
    messages: Sequence[ChatMessage],
    *,
    timeout_s: float,
    temperature: float | None = None,
    response_format: Mapping[str, Any] | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    tool_choice: str | Mapping[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> ChatOutcome:
    """One blocking chat completion. RAISES `httpx.HTTPStatusError` on a non-2xx.

    RAISING RATHER THAN RETURNING A STATUS is what keeps the three existing callers
    unchanged in behaviour: `extraction.extract_call`'s ladder already catches
    `httpx.HTTPError` and turns it into `errors["_model"]`, and the two callers that want
    to act on a specific status (Azure's 400 → degrade from Structured Outputs to
    `json_object`) catch it and read `exc.response.status_code`. A helper that returned an
    error object instead would make every caller's happy path carry an `if`.

    `follow_redirects=False` on a client we own is load-bearing rather than tidy: a
    redirect off the configured host is a residency question, and answering it silently by
    following the hop is the one thing these legs must not do. A caller-supplied client is
    the caller's to configure and to close — the ownership rule
    `AzureOpenAIExtractor` and `GoogleSheetsTransport` already keep.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s, follow_redirects=False)
    try:
        response = await http.post(
            leg.url,
            headers=_headers(leg),
            json=_request_body(
                leg,
                messages,
                temperature=temperature,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                stream=False,
            ),
        )
    finally:
        if owns_client:
            await http.aclose()
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):  # pragma: no cover - a provider that is not this API
        return ChatOutcome(content="")
    message, finish_reason = _message_of(body)
    content = message.get("content")
    return ChatOutcome(
        content=str(content or ""),
        tool_calls=_tool_calls_of(message),
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        usage=usage_from_body(body),
    )


class _ToolCallAccumulator:
    """OpenAI's own reassembly rule for `tool_calls` arriving in fragments.

    ADDRESSED BY `index`, WHICH IS THE ONLY FIELD THE VENDOR MARKS REQUIRED on a
    `ChatCompletionMessageToolCallChunk` (openai/openai-openapi `openapi.yaml` @ master,
    read 27 Aug 2026): `id`, `type` and `function.name` arrive once, on some frame, while
    `function.arguments` arrives in pieces across many. Addressing by list POSITION instead
    — the obvious reading of a JSON array — silently interleaves two parallel tool calls
    into one, which is why the vendor puts the index in the payload at all.

    THE RULE, and it is three lines because it has three cases: `index` and `type` are
    REPLACED, every other string is CONCATENATED (a name that arrives once concatenates to
    itself, which is why one rule covers both), and a nested object recurses. This is
    openai-node's `ChatCompletionStream` accumulator restated; the alternative — "set the
    name, append the arguments" — is the same thing with the general case deleted, and it
    breaks the first time a provider splits a function NAME across two frames.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, Any]] = {}

    def feed(self, deltas: object) -> None:
        if not isinstance(deltas, list):
            return
        for entry in deltas:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if not isinstance(index, int):
                # No index, no address. A frame we cannot place is dropped rather than
                # appended to whatever came last — mis-attributing an argument fragment is
                # worse than losing it, because the loss is visible as a JSON parse
                # failure and the mis-attribution is not.
                continue
            self._merge(self._by_index.setdefault(index, {}), entry)

    def _merge(self, into: dict[str, Any], fragment: Mapping[str, Any]) -> None:
        for key, value in fragment.items():
            if key in ("index", "type"):
                into[key] = value
            elif isinstance(value, str):
                previous = into.get(key)
                into[key] = (previous if isinstance(previous, str) else "") + value
            elif isinstance(value, dict):
                nested = into.get(key)
                if not isinstance(nested, dict):
                    nested = {}
                    into[key] = nested
                self._merge(nested, value)

    def finish(self) -> tuple[ToolCall, ...]:
        """The accumulated calls, in index order, validated the same way a blocking
        answer's are — one `_tool_calls_of`, so a streamed tool call and a blocking one
        cannot be judged by two different rules."""
        ordered = [self._by_index[index] for index in sorted(self._by_index)]
        return _tool_calls_of({"tool_calls": ordered})


def _stream_frames(line: str) -> Mapping[str, Any] | None:
    """One `data:` line as a frame, or None for everything else.

    Returns None for the SSE comment lines, the blank separators, `[DONE]`, and any frame
    whose `object` is not `CHUNK_OBJECT` — see that constant for the Azure annotation frame
    this last clause exists for.
    """
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        frame = json.loads(payload)
    except ValueError:
        # A frame we cannot parse is one we cannot place. Logged as a count of nothing —
        # the payload is model output and never reaches a log line (hard rule 6).
        log.warning("chat_stream_frame_unparseable")
        return None
    if not isinstance(frame, dict) or frame.get("object") != CHUNK_OBJECT:
        return None
    return frame


async def stream(
    leg: ChatLeg,
    messages: Sequence[ChatMessage],
    *,
    timeout_s: float,
    temperature: float | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    tool_choice: str | Mapping[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[StreamEvent]:
    """One streamed chat completion: text fragments as they arrive, then ONE outcome.

    `timeout_s` IS A READ TIMEOUT, NOT A TOTAL ONE, and the difference is the whole reason
    this signature is not `complete`'s. A generation that takes ninety seconds is not a
    failure; ninety seconds of SILENCE is. `httpx.Timeout(read=...)` bounds the gap between
    frames, and the caller bounds the wall clock (`copilot/service.py` does it with
    `asyncio.timeout`, and says why there).

    RAISES `httpx.HTTPStatusError` on a non-2xx, for `complete`'s reason. The status is
    available before any frame is read, so a caller can still fall back to another leg.

    THE USAGE FRAME IS NOT A CONTENT FRAME. It arrives after the last delta with an empty
    `choices` array (see `STREAM_OPTIONS`), so the loop below reads `usage` off every frame
    and `choices` off the ones that have any — a single pass that does not need to know
    which frame is last.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=timeout_s), follow_redirects=False
    )
    accumulator = _ToolCallAccumulator()
    content: list[str] = []
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    try:
        async with http.stream(
            "POST",
            leg.url,
            headers=_headers(leg),
            json=_request_body(
                leg,
                messages,
                temperature=temperature,
                response_format=None,
                tools=tools,
                tool_choice=tool_choice,
                stream=True,
            ),
        ) as response:
            if response.is_error:
                # The body has not been read yet on a streaming response, and
                # `raise_for_status()` needs it to build its message. Read it, then raise —
                # the body itself is never logged (hard rule 6: a provider's error body
                # quotes the request, and on the copilot leg the request is a screen).
                await response.aread()
                log.warning(
                    "chat_stream_refused",
                    extra={"status": response.status_code, "model": leg.wire_model},
                )
                response.raise_for_status()
            async for line in response.aiter_lines():
                frame = _stream_frames(line)
                if frame is None:
                    continue
                usage = usage_from_body(frame) or usage
                choices = frame.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                reason = choice.get("finish_reason")
                if isinstance(reason, str):
                    finish_reason = reason
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                accumulator.feed(delta.get("tool_calls"))
                fragment = delta.get("content")
                if isinstance(fragment, str) and fragment:
                    content.append(fragment)
                    yield StreamEvent(text=fragment)
    finally:
        if owns_client:
            await http.aclose()
    yield StreamEvent(
        outcome=ChatOutcome(
            content="".join(content),
            tool_calls=accumulator.finish(),
            finish_reason=finish_reason,
            usage=usage,
        )
    )


__all__ = [
    "CHUNK_OBJECT",
    "STREAM_OPTIONS",
    "ChatDialect",
    "ChatLeg",
    "ChatMessage",
    "ChatOutcome",
    "StreamEvent",
    "TokenUsage",
    "ToolCall",
    "complete",
    "stream",
    "usage_from_body",
]
