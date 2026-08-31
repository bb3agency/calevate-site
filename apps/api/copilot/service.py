"""The copilot's bounded tool-calling loop, and the server-side re-validation that is the
whole of its safety argument.

WHY THE MODEL IS CALLED FROM A REQUEST HANDLER (a departure, argued — `crm/assist.py`
makes the same one and `ops/secret_probes.py` makes its own).

CLAUDE.md says model providers are called from workers or the engine, never a request
handler. This calls one. The rule's purpose is to keep vendor latency off the
latency-critical path and off a blocking worker: the voice path is `apps/voice-runtime`
and is not this, and every hop here is `await`ed on an asyncio loop, so a slow Azure
occupies no thread. What `crm/assist.py` additionally pays — one pooled Postgres
connection held for the length of the round trip, because `Depends(db)`'s transaction is
open across it — THIS ROUTE DOES NOT PAY: it takes no `Depends(db)` at all. The gate, and
later the meter and the audit, each open their own short `tenant_session` and close it, so
no connection is held across a provider call. That is strictly better than the established
path and it is the reason a streaming route is affordable here at all.

THE ORDER IS `crm/assist.py`'s AND EVERY ARROW IS LOAD-BEARING: SUBJECT → GATE → RUN →
METER. `routes.py` is where it is spelled out; this module owns the RUN and hands back the
two facts the METER needs.

THE LOOP IS CAPPED AND THE CAP HAS A SENTENCE. A tool-calling loop that cannot end is a
spinner that never stops, which is the failure mode a person cannot act on. `MAX_TURNS`
turns, then an authored message telling them what to do instead.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import httpx
from calevate_shared.engine import (
    SARVAM_DEFAULT_LLM,
    azure_openai_base_url,
    google_openai_compat_base_url,
)

from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import tools as tools_module
from apps.api.copilot.sanitize import clean_value, strip_invisible
from apps.api.copilot.schemas import CopilotAskIn, CopilotField, CopilotFillItem
from apps.api.copilot.tools import ToolContext
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    AZURE_PROVIDER,
    GOOGLE_PROVIDER,
    SARVAM_CHAT_URL,
    AssistCapability,
    TenantModelLeg,
    assist_capability,
    assist_unavailable,
    azure_credentials,
)

log = get_logger(__name__)

#: How many model turns one question may take.
#:
#: **SIX, RAISED FROM FOUR WHEN THE READ TOOLS LANDED, AND THE NUMBER IS THE LONGEST
#: USEFUL SHAPE RATHER THAN A ROUND ONE.** Four was "ask, correct a refused fill, ask
#: again, answer", which is still the longest FILL-only shape and is untouched. What four
#: cannot express is the shape this feature exists for: look something up, look something
#: up that depended on the first answer, then answer in prose — three turns before a word
#: is written, and a refused fill on top of that would have had nowhere to go. Six is that
#: chain (2 lookups + answer) with a refused fill and its correction still fitting behind
#: it, and one turn of slack; it is NOT sized to let a model browse.
#:
#: Each turn is a paid round trip AND — now that a turn can call a tool — up to
#: `tools.MAX_CALLS_PER_TURN` database round trips, so the cap is a spend bound and a load
#: bound as well as a latency one. It is deliberately the WEAKEST of the three brakes:
#: `TOTAL_BUDGET_S` bounds the wall clock whatever the turns do, and `MAX_ANSWER_TOKENS`
#: bounds each turn's output. Those two are the real safety valves; this one exists so a
#: model that loops on a tool it keeps mis-calling still ends with a sentence.
MAX_TURNS: Final = 6

#: The longest gap between two frames of a streamed answer before we give up on it.
#:
#: A READ timeout, not a total one, and the distinction is the whole reason this is not
#: `ASSIST_TIMEOUT_S`. A generation that takes ninety seconds is not a failure; ninety
#: seconds of silence is. 15s matches `ASSIST_TIMEOUT_S`'s per-leg budget for the same
#: reason it was chosen there — long enough for a first token, short enough that a person
#: does not sit in front of a dead stream.
STREAM_IDLE_S: Final = 15.0

#: The ceiling on ONE model turn's OUTPUT, in tokens — a safety valve, never a target
#: (`EXTRACTION_MAX_TOKENS`'s shape, on the surface that had no cap at all).
#:
#: WHY A STREAMED TURN NEEDS ONE: `STREAM_IDLE_S` bounds SILENCE and `TOTAL_BUDGET_S`
#: bounds the wall clock, so before this cap the only brake on a model that kept talking
#: was 90 seconds of paid output tokens — per turn, up to `MAX_TURNS` times. The prompt
#: asks for "a couple of sentences", so a well-formed answer never approaches this; the
#: number is sized to the LARGEST legitimate output, a `set_fields` call drafting several
#: full-length textarea values in Telugu (each field value is bounded at 2,000 chars by
#: `schemas._MAX_TEXT`, and Telugu runs ~2.1-2.3 tokens/word), with headroom, so the valve
#: can only fire on a runaway. A hit surfaces as `finish_reason == "length"`: prose simply
#: ends, and a truncated tool call fails `validate_fill`'s JSON parse and re-enters the
#: loop as an ordinary refusal — both visible, neither silent.
#:
#: ⚠ NOT SENT ON THE GEMINI TURN. Whether Google's OpenAI-compat surface accepts
#: `max_tokens` is UNVERIFIED here — `ai.google.dev` and `developers.googleblog.com` are
#: egress-blocked from this container (403 on CONNECT, re-measured 31 Aug 2026), and a
#: live probe cannot settle it without a key (the endpoint answers an invalid key with
#: 400 `INVALID_ARGUMENT` before validating the body — probed 31 Aug 2026). Sending an
#: unsupported key risks a 400 that turns a working leg into a refusal, the exact trade
#: `_answer_via_sarvam` declines for `tools`. A credentialed probe closes it.
MAX_ANSWER_TOKENS: Final = 4096

#: The wall clock for the WHOLE loop, enforced with `asyncio.timeout` around it.
#:
#: WHY THIS DOES NOT HAVE TO FIT UNDER NGINX'S `proxy_read_timeout` — AND `crm/assist.py`'s
#: BUDGET DID. That constraint (`tests/assist_deadline_test.py`:
#: `2 * ASSIST_TIMEOUT_S + ASSIST_ROUTE_RESERVE_S < proxy`) is about a request whose
#: response arrives in ONE piece at the end: the edge sees nothing from the upstream for
#: the whole duration, and `proxy_read_timeout` bounds "time between two successive READ
#: operations from the proxied server" — so with one read, it bounds the whole request.
#: This response is a stream. FastAPI's SSE writer emits a `: ping` keep-alive comment
#: after 15s of producer silence (`fastapi/sse.py::_PING_INTERVAL`, installed 0.140), and
#: every text fragment is a read of its own, so the gap between reads is bounded by 15s
#: against the api vhost's 60s. `copilot/deadline_test.py` asserts both numbers out of
#: their real sources rather than trusting this paragraph.
#:
#: NO NGINX CHANGE IS NEEDED FOR BUFFERING EITHER, and this was checked rather than
#: recalled: FastAPI's SSE path sets `X-Accel-Buffering: no` on the response itself
#: (`fastapi/routing.py`, "For Nginx proxies to not buffer server sent events"), and
#: nginx's own documentation for that header reads "Sets the proxy buffering for this
#: connection. Setting this to 'no' will allow unbuffered responses suitable for Comet and
#: HTTP streaming applications" (nginxinc/nginx-wiki,
#: `source/start/topics/examples/x-accel.rst` @ master, read 27 Aug 2026 — `nginx.org` and
#: `docs.nginx.com` are both egress-blocked from this environment, so the vendor's own
#: wiki repository is the primary source actually read). `infra/nginx/` sets no
#: `proxy_ignore_headers`, which is the one directive that would switch that off — checked
#: by grep, not assumed. So `infra/` is untouched by this feature.
TOTAL_BUDGET_S: Final = 90.0

#: Said to the person when the loop runs out of turns. An authored sentence with an action
#: in it, never a spinner that stops.
EXHAUSTED_MESSAGE: Final = "I couldn't finish within the turn limit — please narrow the request."

#: Appended to `AssistCapability.disclosure` when the fallback leg answered.
#:
#: The fallback CANNOT FILL FIELDS (see `_answer_via_sarvam`), and a person who asked it to
#: and got prose back is owed the reason. D-127 G-6's disclosure says which model wrote the
#: answer; this says what that costs them, which is the part they can act on.
FALLBACK_NO_TOOLS_NOTE: Final = (
    " It can answer questions about this screen, but it cannot fill in fields or look up "
    "your calls, leads or campaigns."
)


#: Appended, last, on the fallback leg only. See `_answer_via_sarvam`.
_NO_TOOL_NOTE: Final = (
    "CORRECTION for this turn only: the set_fields tool AND every lookup tool (this "
    "account's calls, leads, campaigns and performance) are NOT available to you right "
    "now. Do not call any of them, do not say you have filled anything in, and do not say "
    "you have looked anything up. Answer the question in words from what you can already "
    "see. If the person asked you to fill a field, tell them the value they should type "
    "and that you cannot enter it for them this time. If they asked for a number about "
    "their business, say you cannot look it up right now — do not estimate one."
)


class FillRefusedError(Exception):
    """The model asked for a write this request does not permit.

    Carries the per-item reasons so the refusal can be handed BACK to the model as a tool
    result — the loop's one legitimate use of its remaining turns — and shown to the person
    if the loop then runs out.
    """

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(reasons))


@dataclass(frozen=True, slots=True)
class CopilotSpend:
    """What one copilot answer cost, who wrote it, and — when the run knows it — on which
    model.

    It satisfies `crm/assist.py::MeterableAssist` structurally — `.usage` and `.capability`,
    the two things metering is entitled to know — so that ONE metering path prices the
    re-summarise, the script draft and this. `model` is the third, added for D-478's Gemini
    leg (see below): it is not part of the `MeterableAssist` Protocol, and the copilot route
    reads it off this concrete type to pass to `meter_assist`, so the other two surfaces are
    untouched. A richer result beyond these would be an invitation to price a surface
    differently.

    `usage is None` means WE DO NOT KNOW WHAT THIS COST, never that it was free, and
    `meter_assist` already handles the two causes differently (a free Sarvam leg is logged;
    an uncounted Azure answer fires `ai_assist_unmeterable`). See `_sum_usage` for the
    multi-turn rule, which is where this could most easily have become a lie.

    `model` IS THE MODEL THE LEDGER MUST NAME, and it is carried rather than re-derived
    because the answering leg is the only place it is known (D-478). On Azure it is `None` —
    `meter_assist` reads the live `azure_openai_model` setting, because Azure answers under a
    deployment id and the model behind it is an operator switch. On the Gemini leg it is the
    account's own model id, which `rates.llm_inr_per_ktok` prices directly; handing `None`
    there would meter a Gemini answer at the Azure model's price on an append-only ledger.
    """

    usage: TokenUsage | None
    capability: AssistCapability
    model: str | None = None


@dataclass(frozen=True, slots=True)
class CopilotEvent:
    """One step of an answer. Exactly one of the three is set.

    `spend` is emitted exactly once, last, on every path that reached a provider — the
    route needs it whether the answer was good, refused or exhausted, because a completed
    model turn is money spent regardless of what it said.
    """

    text: str | None = None
    fill: tuple[CopilotFillItem, ...] | None = None
    spend: CopilotSpend | None = None


# --- the re-validation, which is the security argument ------------------------------


def _value_is_legal(field: CopilotField, value: object) -> str | None:
    """`None` if this value may be written to this field, else the reason it may not.

    `None` (clearing a field) is legal on every type: "the caller never said" has to be
    expressible, and a copilot that could set a field but never unset one would leave a
    person with a wrong value and no way to ask for it to be removed.
    """
    if value is None:
        return None
    if field.type == "bool":
        # `isinstance(True, int)` is True in Python, so the order of these checks matters
        # everywhere EXCEPT here — this is the one branch that wants bool and nothing else.
        return None if isinstance(value, bool) else "expects true or false"
    if isinstance(value, bool):
        # And this is the other side of the same trap: a bare `True` would satisfy an
        # `isinstance(value, int)` test on a number field and be written as 1.
        return "expects a value, not true/false"
    if field.type == "number":
        return None if isinstance(value, int | float) else "expects a number"
    if not isinstance(value, str):
        return "expects text"
    if field.type == "select":
        if not field.options:
            # A select whose options nobody declared has no value this server can PROVE is
            # legal. Passing the model's word through would be exactly the trust OWASP
            # LLM01 #4 says not to place in it, and the browser can fix it by declaring the
            # options — so this is a refusal rather than an allowance.
            return "is a dropdown with no options declared, so no value can be checked"
        if value not in {option.value for option in field.options}:
            return "is not one of that dropdown's options"
    return None


def validate_fill(payload: CopilotAskIn, arguments: str) -> tuple[CopilotFillItem, ...]:
    """The model's `set_fields` arguments, re-checked against THIS REQUEST. Raises
    `FillRefusedError` naming every item that failed.

    THE MODEL'S CLAIM ABOUT WHAT IS WRITABLE IS WORTHLESS, and the vendor says so about
    the payload itself: "the model does not always generate valid JSON, and may
    hallucinate parameters not defined by your function schema. Validate the arguments in
    your code before calling your function" (openai/openai-openapi `openapi.yaml` @ master,
    `ChatCompletionMessageToolCallChunk`, read 27 Aug 2026). OWASP GenAI LLM Top 10 2026
    LLM01 #4 states the same rule as a design constraint: hold state-change capability in
    application code, not in the model.

    ALL-OR-NOTHING, and that is a deliberate choice against the friendlier one. A partial
    apply — write the six that were fine, drop the one that was not — gives the person a
    form in a state neither they nor the copilot described, and one Undo that only undoes
    part of it. One call, one outcome, one Undo.

    EVERY REASON NAMES ITS FIELD, because the refusal is fed back to the model on the next
    turn and "one of your fields was wrong" is not something it can act on. Field IDS are
    named; field VALUES never are — a reason string reaches a log line and a person's
    screen, and a value may be the very thing `sanitize` exists to keep off both.
    """
    try:
        parsed = json.loads(arguments or "")
    except ValueError as exc:
        raise FillRefusedError(["the tool call was not valid JSON"]) from exc
    if not isinstance(parsed, dict):
        raise FillRefusedError(["the tool call was not an object"])
    raw_items = parsed.get("items")
    if not isinstance(raw_items, list):
        raise FillRefusedError(["`items` was missing or was not an array"])
    if not raw_items:
        raise FillRefusedError(["`items` was empty — nothing to fill"])

    by_id = {field.id: field for field in payload.fields}
    items: list[CopilotFillItem] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            reasons.append("one item was not an object")
            continue
        field_id = raw.get("field_id")
        if not isinstance(field_id, str) or not field_id:
            reasons.append("one item named no field")
            continue
        if field_id in seen:
            # Two writes to one field in one call: the second silently wins, and which one
            # that is depends on iteration order. Refused rather than resolved, because
            # there is no correct answer and a person cannot see the collision.
            reasons.append(f"`{field_id}` was set twice in one call")
            continue
        seen.add(field_id)
        field = by_id.get(field_id)
        if field is None:
            reasons.append(f"`{field_id}` is not a field on this screen")
            continue
        if not field.writable:
            reasons.append(f"`{field_id}` is not writable")
            continue
        value = raw.get("value")
        problem = _value_is_legal(field, value)
        if problem is not None:
            reasons.append(f"`{field_id}` {problem}")
            continue
        # THE EGRESS HALF OF THE INVISIBLE-CHARACTER RULE. The browser highlights a preview
        # of this value and then writes it; a tag-block character here makes the two
        # different strings, and the person approves the one they can see.
        items.append(CopilotFillItem(field_id=field_id, value=clean_value(value)))

    if reasons:
        raise FillRefusedError(reasons)
    return tuple(items)


# --- the provider legs ---------------------------------------------------------------


def _chat_leg(provider: str, *, model: str | None) -> chat.ChatLeg | None:
    """The ONE map from the ANSWERING provider to an addressed `chat.ChatLeg`, or None if
    this deployment holds no credential for it.

    Keyed on `capability.provider` — the provider the selector decided answers — NOT on the
    tenant's own provider, because a substituted account (its own provider cannot serve this
    leg) is answered by Azure while its `tenant_leg.provider` is something else. One function
    rather than a `_azure_leg`/`_google_leg` pair, so the provider→(dialect, base URL,
    credential) triple is stated in exactly one place (the "one resolver" D-478 asks for):

    * **`azure`** — `azure_credentials()` is THE reader of the three Azure settings, and the
      wire model is the DEPLOYMENT id (D-410/D-417), not the model name. `model` is unused
      here: Azure answers under the operator's deployment regardless of which account it is
      standing in for.
    * **`google`** — Gemini over its OpenAI-compat surface (D-478). The base URL is
      `google_openai_compat_base_url()`, the one verified emitter of the Developer API host
      (`scripts/check_model_residency.py` grants it the tree's single host literal); the wire
      model is the account's own Gemini id (`model`); the key is `gemini_api_key`. Bearer
      auth, non-streamed — `run_copilot` calls `chat.complete`, never `chat.stream`, on it.
    """
    settings = get_settings()
    if provider == AZURE_PROVIDER:
        credentials = azure_credentials()
        if credentials is None:
            return None
        resource, api_key, deployment = credentials
        return chat.ChatLeg(
            url=f"{azure_openai_base_url(resource)}/chat/completions",
            api_key=api_key,
            wire_model=deployment,
            dialect="openai",
        )
    if provider == GOOGLE_PROVIDER:
        if not settings.gemini_api_key or model is None:
            return None
        return chat.ChatLeg(
            url=f"{google_openai_compat_base_url()}/chat/completions",
            api_key=settings.gemini_api_key,
            wire_model=model,
            dialect="google",
        )
    return None


def _sum_usage(turns: Sequence[chat.ChatOutcome]) -> TokenUsage | None:
    """The whole loop's cost as one quantity, or None if any turn did not report its own.

    ONE `usage_events` ROW PAIR PER USER ACTION, not per model turn: `read_ai_quota`'s
    `requests_used` is a `COUNT(DISTINCT ref)` over the paid unit types, so N rows for one
    question would make the request count and the rupee ceiling disagree about the same
    month.

    **A SINGLE UNREPORTED TURN POISONS THE WHOLE SUM, and that is the point.** Summing the
    turns that DID report and calling it the total is a fabricated quantity — smaller than
    the truth, on an append-only ledger, indistinguishable from a real one, and invisible
    to both the tenant's ceiling and the platform brake. D-140 refused exactly that trade
    for exactly that reason. `None` reaches `meter_assist`, which fires
    `ai_assist_unmeterable` and asks an operator to look; a plausible invented number asks
    nobody anything.
    """
    total: TokenUsage | None = None
    for outcome in turns:
        if outcome.usage is None:
            return None
        total = outcome.usage if total is None else total.plus(outcome.usage)
    return total


async def _answer_via_sarvam(
    payload: CopilotAskIn, capability: AssistCapability
) -> AsyncIterator[CopilotEvent]:
    """The disclosed fallback: one non-streamed answer, in prose, with NO tools.

    **NOT STREAMED, AND NO TOOLS, AND BOTH ARE HONEST LIMITS RATHER THAN DESIGN.** Whether
    Sarvam's OpenAI-compatible chat supports `tools` or `stream_options` is **UNVERIFIED**
    — this environment holds no Sarvam key and their documentation was not read this
    session — and sending a parameter a provider does not support risks a 400, which would
    turn a working fallback into a refusal. So the fallback does the thing every
    OpenAI-compatible endpoint certainly does: one blocking completion, emitted as a single
    text event. It answers questions and it cannot fill fields, and
    `FALLBACK_NO_TOOLS_NOTE` is how the person is told that rather than left to discover
    it.

    Metering is unaffected: D-36 prices this leg at zero, so `CopilotSpend.usage` stays
    None and `meter_assist`'s Sarvam branch records nothing — the same shape re-summarise
    and the script draft already have.
    """
    settings = get_settings()
    if not settings.sarvam_api_key:  # pragma: no cover - unreachable via the selector
        raise assist_unavailable(capability)
    outcome = await chat.complete(
        chat.ChatLeg(
            url=SARVAM_CHAT_URL,
            api_key=settings.sarvam_api_key,
            wire_model=SARVAM_DEFAULT_LLM,
            dialect="sarvam",
        ),
        # THE SAME PROMPT, PLUS ONE CORRECTION AT THE END. `build_messages` tells the model
        # to call `set_fields`, and on this leg there is no such tool — a model told to use
        # a capability it has not been given answers "I've filled that in for you" and fills
        # nothing, which is the one failure mode worse than saying no. The correction goes
        # LAST rather than into the shared prompt, so the cacheable prefix stays byte
        # identical for the leg that has a cache (`prompt.py`, point 1).
        [*prompt_module.build_messages(payload), {"role": "system", "content": _NO_TOOL_NOTE}],
        timeout_s=STREAM_IDLE_S,
        temperature=0.2,
        # The same safety valve as the Azure turn. `max_tokens` is on Sarvam's own
        # client's fourteen-key request body (VERIFIED-VENDOR-SDK, `workers/chat.py::
        # _request_body`), so unlike `tools` it is safe to send here — and this leg is
        # PRICED (`billing/rates.SARVAM_LLM_INR_PER_MTOK`, ₹73.20/Mtok out) even though
        # nothing meters it yet, so a runaway would be real unrecorded spend.
        max_tokens=MAX_ANSWER_TOKENS,
    )
    if outcome.content:
        yield CopilotEvent(text=strip_invisible(outcome.content))
    yield CopilotEvent(spend=CopilotSpend(usage=None, capability=capability))


# --- the loop -------------------------------------------------------------------------


def tool_array() -> list[dict[str, Any]]:
    """Every tool the model is offered, in a FIXED order, IDENTICAL ON EVERY REQUEST.

    ONE COMPOSER, so there is one answer to "what tools exist" and the cacheable prefix has
    one definition. The write tool comes first because it was first and because moving it
    would change the prefix for no gain; the read tools follow in `READ_TOOLS` order.

    NOTHING IS GATED OUT OF THIS ARRAY — not by screen, not by tenant, not by role. Azure's
    prompt caching keys on a leading run of byte-identical tokens (`prompt.py`, point 1),
    and an array that dropped the tools a caller may not use would differ per role, giving
    every non-`owner` caller a cache miss on every request. A caller who may not use a read
    tool is refused INSIDE it by `tools.run_read_tool`, which is where the check has to
    exist anyway: a schema the model was never shown is obscurity, not an access control.
    `copilot/tools_test.py` pins the byte-identity across two differing requests.
    """
    return [prompt_module.set_fields_tool(), *tools_module.read_tool_schemas()]


async def _run_read_tools(
    calls: Sequence[chat.ToolCall], *, context: ToolContext | None
) -> list[dict[str, object]]:
    """Every read call of ONE turn, executed, as the `role: "tool"` messages that answer them.

    CONCURRENTLY, because independent calls in one turn are independent: "how are calls
    going and which leads are hot" is two lookups with no ordering between them, and running
    them in series doubles the person's wait for nothing. Each opens and closes its OWN
    `tenant_session` (`tools.run_read_tool`), so concurrency here costs a bounded handful of
    pooled connections for the length of a SELECT rather than one held across the stream.

    ONE MESSAGE PER CALL, INCLUDING THE ONES WE REFUSED, and that is not politeness: a
    provider rejects a tool result whose `tool_call_id` it never issued, and — worse —
    rejects the NEXT request if an issued call has no result at all. So an unknown tool
    name, a permission refusal and an over-the-cap call each get an answer rather than
    silence. `run_read_tool` never raises, so `gather` needs no `return_exceptions`.
    """
    permitted = calls[: tools_module.MAX_CALLS_PER_TURN]
    refused = calls[tools_module.MAX_CALLS_PER_TURN :]
    results = await asyncio.gather(
        *(
            tools_module.run_read_tool(call.name, call.arguments, context=context)
            for call in permitted
        )
    )
    messages: list[dict[str, object]] = [
        {"role": "tool", "tool_call_id": call.id, "content": result}
        for call, result in zip(permitted, results, strict=True)
    ]
    messages += [
        {
            "role": "tool",
            "tool_call_id": call.id,
            "content": (
                f"Not run: you asked for more than {tools_module.MAX_CALLS_PER_TURN} "
                "lookups in one turn. Ask for the ones you still need."
            ),
        }
        for call in refused
    ]
    return messages


def _assistant_tool_message(
    outcome: chat.ChatOutcome, calls: Sequence[chat.ToolCall]
) -> dict[str, object]:
    """The assistant turn that ISSUED these tool calls, replayed back into the message list.

    Required, not decorative: a `role: "tool"` message whose matching assistant `tool_calls`
    entry is missing is an orphan the provider refuses. The refusal-feedback path below
    builds the same shape for the single `set_fields` call, and this is that shape for N.
    """
    return {
        "role": "assistant",
        "content": outcome.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in calls
        ],
    }


#: One model turn, as the events `chat.stream` yields — text fragments, then ONE terminal
#: `StreamEvent` carrying the `ChatOutcome`. The two legs differ ONLY in this: Azure STREAMS
#: (fragments live), the Gemini leg is NON-STREAMED (`chat.complete`, one text event at the
#: end, then the outcome), because Gemini's streamed tool-call deltas can carry a `None` index
#: that would corrupt the accumulator (`workers/chat.stream` refuses it, `openai/openai-python
#: #2806`). Both shapes satisfy the loop below, so the loop is written once.
_TurnRunner = Callable[
    [chat.ChatLeg, Sequence[chat.ChatMessage], Sequence[Mapping[str, object]]],
    AsyncIterator[chat.StreamEvent],
]


def _azure_turn(
    leg: chat.ChatLeg,
    messages: Sequence[chat.ChatMessage],
    tools: Sequence[Mapping[str, object]],
) -> AsyncIterator[chat.StreamEvent]:
    """The streamed turn: `chat.stream` verbatim. `timeout_s` is a READ timeout here."""
    return chat.stream(
        leg,
        messages,
        timeout_s=STREAM_IDLE_S,
        temperature=0.2,
        tools=tools,
        tool_choice="auto",
        max_tokens=MAX_ANSWER_TOKENS,
    )


async def _google_turn(
    leg: chat.ChatLeg,
    messages: Sequence[chat.ChatMessage],
    tools: Sequence[Mapping[str, object]],
) -> AsyncIterator[chat.StreamEvent]:
    """The NON-STREAMED turn, re-shaped as the loop's events: one blocking `chat.complete`
    with tools (which returns a clean full `tool_calls` array — the reason the leg is not
    streamed, D-478), emitted as one text event and then the terminal outcome. `timeout_s` is
    a WHOLE-request timeout here, which is correct for a blocking call.

    NO `max_tokens` on this leg — see `MAX_ANSWER_TOKENS`: whether Gemini's OpenAI-compat
    surface accepts the key is unverified from this container, and an unsupported key is a
    400 that kills a working leg. The blocking `timeout_s` bounds this turn's wall clock
    (a whole-request bound the streamed turn does not have), so the exposure is smaller."""
    outcome = await chat.complete(
        leg, messages, timeout_s=STREAM_IDLE_S, temperature=0.2, tools=tools, tool_choice="auto"
    )
    if outcome.content:
        yield chat.StreamEvent(text=outcome.content)
    yield chat.StreamEvent(outcome=outcome)


async def _run_tool_loop(
    payload: CopilotAskIn,
    capability: AssistCapability,
    *,
    leg: chat.ChatLeg,
    turn: _TurnRunner,
    model: str | None,
    tool_context: ToolContext | None = None,
) -> AsyncIterator[CopilotEvent]:
    """Up to `MAX_TURNS` turns on the answering leg. Raises `httpx.HTTPError` if the FIRST
    turn never produced anything, so the caller can still fall back.

    ONE LOOP FOR BOTH LEGS (D-478). `turn` is the only thing that differs — Azure's streamed
    turn or Gemini's non-streamed one — so the tool-calling, re-validation, refusal-feedback
    and metering are byte-for-byte the same on both, which is what keeps the field-filling
    identical. `model` is threaded into `CopilotSpend` so the ledger names the Gemini model
    on the Gemini leg (`None` = Azure's live-switched setting).

    **THE LOOP NOW CONTINUES ON A READ TOOL, AND THAT IS THE BEHAVIOURAL CHANGE.** It used
    to continue on exactly one thing — a REFUSED fill — and end on everything else, because
    the only tool was `set_fields` and a successful fill is the end of the interaction. A
    read tool is the opposite shape: its result is not the answer, it is what the model
    needed in order to write one. So a turn that calls read tools appends the assistant's
    own `tool_calls` message plus one `role: "tool"` result per call and goes round again,
    which is what lets search → read → answer happen inside one question.

    `set_fields` KEEPS ITS SEMANTICS EXACTLY: one call honoured, one `fill` event, one
    Undo, loop over. It is checked FIRST, so a turn that somehow asks for both a write and
    a lookup is resolved the way it was before this change — the write wins and the turn
    ends. That is deliberate: the read results would have nowhere to go once the fill has
    been emitted, and inventing a second round after a person has already been shown a
    change is the "second chance to change what they were shown" that
    `test_a_valid_set_fields_stops_the_loop_immediately` exists to forbid."""
    messages = prompt_module.build_messages(payload)
    tools = tool_array()
    turns: list[chat.ChatOutcome] = []
    refusal: FillRefusedError | None = None

    for turn_index in range(MAX_TURNS):
        outcome: chat.ChatOutcome | None = None
        async for event in turn(leg, messages, tools):
            if event.text is not None:
                # EGRESS STRIPPING ON EVERY FRAGMENT, not once at the end: fragments are
                # what the browser renders, and a tag-block character split across two
                # frames still arrives whole in the DOM.
                yield CopilotEvent(text=strip_invisible(event.text))
            if event.outcome is not None:
                outcome = event.outcome
        if outcome is None:  # pragma: no cover - `chat.stream` always ends with one
            break
        turns.append(outcome)
        if outcome.finish_reason == "length":
            # The `MAX_ANSWER_TOKENS` valve fired: a runaway generation was cut off, not
            # a normal answer. The loop carries on — truncated prose has already reached
            # the screen and a truncated tool call fails `validate_fill` as ordinary
            # invalid JSON — but the event is an operator's to notice, because a turn
            # that HIT the ceiling spent the ceiling.
            log.warning("copilot_answer_truncated", extra={"turn": turn_index})
        if outcome.usage is None:
            # Not an error, and not silence either. `_sum_usage` will make the whole run
            # unmeterable off the back of this; the log line is what lets an operator tell
            # "the stream was cut" from "Azure stopped sending the block".
            log.warning(
                "copilot_turn_unmetered",
                extra={"turn": turn_index, "finish_reason": outcome.finish_reason},
            )

        calls = [
            call for call in outcome.tool_calls if call.name == prompt_module.SET_FIELDS_TOOL_NAME
        ]
        if not calls:
            read_calls = [
                call
                for call in outcome.tool_calls
                if call.name != prompt_module.SET_FIELDS_TOOL_NAME
            ]
            if not read_calls:
                # The model answered in prose. Done — the ordinary end of a question.
                yield CopilotEvent(
                    spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
                )
                return
            # A LOOKUP, NOT AN ANSWER. Feed the results back and go round again — this is
            # the one path that makes "answer about the business" possible, and it is why
            # `MAX_TURNS` had to grow. Anything the model said alongside the call has
            # already been streamed above; only the tool plumbing is added here.
            messages = [
                *messages,
                _assistant_tool_message(outcome, read_calls),
                *await _run_read_tools(read_calls, context=tool_context),
            ]
            log.info("copilot_read_tools", extra={"turn": turn_index, "calls": len(read_calls)})
            continue

        # ONE CALL, EVEN IF THE MODEL SENT SEVERAL. The tool takes an array precisely so
        # that a turn has one outcome and one Undo; a second call in the same turn is the
        # documented parallel-tool-call incorrectness, and honouring it would apply two
        # changes a person asked for as one.
        call = calls[0]
        try:
            items = validate_fill(payload, call.arguments)
        except FillRefusedError as refused:
            refusal = refused
            log.info(
                "copilot_fill_refused",
                # Ids and counts. Never a value (hard rule 6), and never the model's prose.
                extra={"turn": turn_index, "reasons": len(refused.reasons)},
            )
            # THE REFUSAL GOES BACK TO THE MODEL rather than to the person, while turns
            # remain. That is what the cap is FOR: a model told `agent_name` is not
            # writable usually fixes it in one more turn, and the alternative — surfacing
            # the first refusal — makes the copilot fail at the thing it exists to do
            # whenever it guesses one field id wrong.
            messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": outcome.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": (
                        "The fill was refused and NOTHING was written. "
                        + "; ".join(refused.reasons)
                        + ". Fix these and call set_fields once more, or tell the user "
                        "what you need."
                    ),
                },
            ]
            continue

        yield CopilotEvent(fill=items)
        yield CopilotEvent(
            spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
        )
        return

    # OUT OF TURNS. The person gets a sentence they can act on, and — when the last thing
    # that happened was a refused fill — the reason, because "narrow the request" is
    # unhelpful advice to somebody whose real problem is that the field is read-only.
    detail = f" ({'; '.join(refusal.reasons)})" if refusal is not None else ""
    yield CopilotEvent(text=f"{EXHAUSTED_MESSAGE}{detail}")
    yield CopilotEvent(
        spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
    )


async def run_copilot(
    payload: CopilotAskIn,
    *,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    tool_context: ToolContext | None = None,
) -> AsyncIterator[CopilotEvent]:
    """Answer one copilot question. THE RUN of SUBJECT → GATE → RUN → METER.

    THE ONE SELECTOR DECIDES WHO ANSWERS. `assist_capability` (D-127 G-6) is asked here
    exactly as `run_assist` and `draft_script` ask it, and a failure re-asks it with
    `provider_unavailable=True` rather than deciding locally what an outage means. A
    surface that grew its own idea of that is how two screens come to disagree about the
    same event.

    **A MID-STREAM AZURE FAILURE DOES NOT FALL BACK, AND THAT IS THE ONE PLACE THIS
    DEPARTS FROM `run_assist`.** `run_assist` can retry on the second leg because its
    answer is one object returned at the end; ours has already been partly rendered into
    somebody's screen. Restarting on Sarvam would print a second, different answer under
    the first. So the fallback is available only before the first fragment, and after it
    the failure is reported as itself. `_streamed_anything` is the flag that says which
    side of that line we are on.

    `quota_exhausted` is the GATE's verdict passed IN, never re-read here — this module has
    no session and no tenant, and a literal `False` would be a promise about
    `require_ai_assist`'s control flow made in the wrong file. `tenant_leg` arrives the same
    way and for the same reason: it is a row, and this module has no session to read one.

    `tool_context` arrives the same way for a THIRD instance of the same reason: it is who
    is asking, and this module has no request. It is what every read tool is executed
    under — the tenant whose RLS session the query runs in, and the role whose permission
    is checked before it does. `None` means "nobody was named", and every read tool then
    refuses; the tools are still OFFERED, because the tool array must not vary by caller
    (`tool_array`). In production it is never None: `routes.py` builds it from a principal
    whose `tenant_id` it has already asserted.
    """
    capability = assist_capability(tenant_leg=tenant_leg, quota_exhausted=quota_exhausted)
    if not capability.available:
        raise assist_unavailable(capability)

    # THE TWO TOOL-CAPABLE LEGS run the same bounded loop and fall back the same way. Azure is
    # the platform's own model (rung 1 or 2); Google (D-478) is the account's own Gemini model
    # (rung 1). The metered model differs — `None` lets `meter_assist` read the live Azure
    # setting, the Gemini id is named explicitly — and the turn differs (streamed vs not), but
    # the fallback rule is identical: a failure BEFORE the first fragment can retry on Sarvam,
    # one AFTER it cannot, because part of the answer is already on the screen.
    if capability.provider in (AZURE_PROVIDER, GOOGLE_PROVIDER):
        if capability.provider == GOOGLE_PROVIDER:
            # `tenant_leg` is not None here: Google only reaches rung 1, which requires the
            # account's own leg. Its model is the wire model AND the ledger name.
            model = tenant_leg.model if tenant_leg is not None else None
            leg, turn = _chat_leg(GOOGLE_PROVIDER, model=model), _google_turn
        else:
            model, leg, turn = None, _chat_leg(AZURE_PROVIDER, model=None), _azure_turn
        if leg is None:  # pragma: no cover - unreachable via the selector
            raise assist_unavailable(capability)
        streamed_anything = False
        try:
            async with asyncio.timeout(TOTAL_BUDGET_S):
                async for event in _run_tool_loop(
                    payload,
                    capability,
                    leg=leg,
                    turn=turn,
                    model=model,
                    tool_context=tool_context,
                ):
                    streamed_anything = streamed_anything or event.text is not None
                    yield event
            return
        except (httpx.HTTPError, TimeoutError) as failure:
            log.warning(
                "copilot_provider_failed",
                extra={"error": type(failure).__name__, "streamed": streamed_anything},
            )
            if streamed_anything:
                raise
        capability = assist_capability(
            tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, provider_unavailable=True
        )
        if not capability.available:
            raise assist_unavailable(capability)

    async for event in _answer_via_sarvam(payload, capability):
        yield event


def disclosure_for(capability: AssistCapability) -> str | None:
    """What the `done` event carries. D-127 G-6's sentence, plus what the substitution
    costs on THIS surface.

    ⚠ **THE NO-TOOLS NOTE IS APPENDED ONLY ON THE SARVAM LEG, AND IT USED TO BE APPENDED TO
    EVERY DISCLOSURE.** That was safe while every substitution landed on Sarvam. Since the
    selector became tenant-aware an AZURE answer can itself be a substitution — for an
    account whose chosen provider may not serve this leg — and that answer runs the full
    tool-calling loop. The Gemini leg (D-478) runs the loop WITH tools too. Appending the note
    on either would tell somebody their fields could not be filled while the model was filling
    them, which is the one failure mode worse than saying no. So the note is for the only leg
    that genuinely has no tools: Sarvam."""
    disclosure = capability.disclosure
    if disclosure is None:
        return None
    if capability.provider in (AZURE_PROVIDER, GOOGLE_PROVIDER):
        return disclosure
    return disclosure + FALLBACK_NO_TOOLS_NOTE


__all__ = [
    "EXHAUSTED_MESSAGE",
    "FALLBACK_NO_TOOLS_NOTE",
    "MAX_ANSWER_TOKENS",
    "MAX_TURNS",
    "STREAM_IDLE_S",
    "TOTAL_BUDGET_S",
    "CopilotEvent",
    "CopilotSpend",
    "FillRefusedError",
    "ToolContext",
    "disclosure_for",
    "run_copilot",
    "tool_array",
    "validate_fill",
]
