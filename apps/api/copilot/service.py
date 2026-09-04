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
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import httpx
from calevate_shared.engine import (
    SARVAM_DEFAULT_LLM,
    azure_openai_base_url,
    google_openai_compat_base_url,
)

from apps.api.copilot import admin_prompt as admin_prompt_module
from apps.api.copilot import admin_tools, navigation, write_tools
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import tools as tools_module
from apps.api.copilot.identity import (
    IdentityEgress,
    identity_answer,
    question_touches_model_identity,
)
from apps.api.copilot.sanitize import clean_value, strip_invisible
from apps.api.copilot.schemas import (
    CopilotActionEvent,
    CopilotAskIn,
    CopilotField,
    CopilotFillItem,
    CopilotNavigateEvent,
    CopilotProposalEvent,
    CopilotRealm,
    CopilotStepEvent,
)
from apps.api.copilot.tools import ToolContext
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
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

#: Said when a model TURN ENDED WITH NO ANSWER IN IT — the defect this constant exists for.
#:
#: **A TURN THAT PRODUCES NO TEXT USED TO END THE RUN IN SILENCE**, and the observed symptom
#: was exactly that: a person asked for a summary of their week, `business_snapshot` ran and
#: rendered its card, the next turn came back with an empty `content` and no tool calls, and
#: the prose exit below returned having emitted a `spend` event and not one word. On the
#: wire that is a paid round trip, a database read and a debug card, with the question
#: unanswered — and NOTHING DOWNSTREAM CAN TELL IT FROM A GOOD ANSWER, because
#: `chat.ChatOutcome.content` is a `str` and `str(content or "")` collapses a JSON `null`
#: candidate and an empty string into the same value (`workers/chat.py::complete`). So the
#: loop cannot distinguish them either, and it does not try: BOTH are "no answer", and the
#: only honest response to a turn with no answer in it is to say so.
#:
#: This is a real state and not a hypothetical one. Google's own documentation says
#: `thinkingBudget: 0` disables thinking on 2.5 flash/flash-lite but that Gemini 3 Flash
#: models "do not support full thinking-off" — a candidate can come back with no content at
#: all (CLAUDE.md, the multi-provider paragraph; every `gemini-3.*` is `selectable=False` on
#: that ground). Azure's content filter is likewise an ORDINARY response carrying
#: `finish_reason: "content_filter"` and a null `content`, not an exception
#: (`workers/chat.py::_message_of`, from openai/openai-openapi @ master).
NO_ANSWER_MESSAGE: Final = (
    "I couldn't put an answer together this time. Please ask me again — nothing on your "
    "screen was changed."
)

#: The same event, when the provider says its own filter stopped the reply.
#:
#: A DIFFERENT SENTENCE BECAUSE IT IS A DIFFERENT INSTRUCTION TO THE PERSON: "ask again"
#: is the right advice after a dropped turn and the wrong advice after a filtered one,
#: where asking the identical question again reproduces it.
FILTERED_MESSAGE: Final = (
    "I couldn't answer that one — the model's safety filter stopped the reply before any of "
    "it reached you. Try asking it a different way."
)

#: The same event, when the turn hit `MAX_ANSWER_TOKENS` before saying anything at all.
#:
#: Distinct from the ordinary truncation the loop already logs: there, prose reached the
#: screen and was cut off, which the person can see. Here the whole ceiling was spent
#: without a word arriving, so there is nothing on screen to explain it.
TRUNCATED_MESSAGE: Final = (
    "The answer ran past its length limit before any of it reached you — please ask for "
    "something narrower."
)

#: Finish reasons that mean A FILTER STOPPED IT rather than the model finishing.
#:
#: `content_filter` is the value OpenAI's own schema documents and the one Azure returns
#: (`workers/chat.py::_message_of`, openai/openai-openapi @ master, read 27 Aug 2026).
#: The rest are Gemini's own candidate finish reasons, lowercased, and how — or whether —
#: Google's OpenAI-compat surface spells them here is **UNVERIFIED**: `ai.google.dev` is
#: egress-blocked from this container. That is safe to leave unproven because the set only
#: ever picks a BETTER sentence: a value not in it falls to `NO_ANSWER_MESSAGE`, which is
#: still an answer. Nothing branches on it beyond the wording.
_FILTERED_FINISH_REASONS: Final = frozenset({"content_filter", "safety", "recitation", "blocklist"})

#: The longest ONE read tool may take before it is stopped and answered with a sentence.
#:
#: TEN SECONDS, AND THE NUMBER IS A FRACTION OF THE BUDGET RATHER THAN A GUESS AT A QUERY.
#: `TOTAL_BUDGET_S` is 90 and a useful answer is two or three lookups plus the turns that
#: read them, so a single lookup that has taken ten seconds has already cost more than the
#: whole shape should; letting it run costs the question. There is no `statement_timeout`
#: set anywhere in this deployment (grepped across `apps/api/db` and `apps/api/core` rather
#: than recalled), so before this the database was the only thing deciding how long a
#: copilot lookup could take.
READ_TOOL_BUDGET_S: Final = 10.0

#: What the model is told when it asks for a lookup it has already run this answer.
#: See `_run_read_tools` — it is a refusal rather than a second identical result.
_REPEAT_RESULT: Final = (
    "Not run: you already ran this exact lookup with these exact arguments while answering "
    "this question, and its result is earlier in this conversation. Use that result, or ask "
    "for something different."
)

#: How many TIER 1 actions one question may perform. D-500.
#:
#: **THREE, AND IT IS A BLAST-RADIUS BOUND RATHER THAN A COST ONE.** `MAX_TURNS` already
#: bounds the round trips and `TOTAL_BUDGET_S` the wall clock; neither bounds the number of
#: things that CHANGED, and a Tier 1 action changes the database without anybody clicking.
#: A person asking for one agent gets one; a person asking for "an inbound and an outbound
#: agent" gets two and a sentence; a model that has decided to create seven is a model whose
#: run should end with an explanation rather than with seven rows. The cap is per ANSWER and
#: not per turn, because the thing worth bounding is what one question did.
#:
#: What happens at the cap is a refusal fed back to the model, not a silent stop: it still
#: gets to tell the person what it did and what it did not.
MAX_ACTIONS_PER_RUN: Final = 3

#: The longest a step frame's `args` or `detail` preview may be, in characters.
#:
#: A DISPLAY bound, not a safety one. The safety properties are elsewhere — the request was
#: already refused if it carried an unredacted personal value (`sanitize.assert_redacted`),
#: and none of this is logged or stored. What this bounds is a panel row: a tool result is
#: prose written for a model and can run to thousands of characters, and a step list that
#: rendered all of it would push the answer off the screen. 200 characters is about two
#: lines at the panel's width.
MAX_STEP_CHARS: Final = 200

#: Appended to `AssistCapability.disclosure` when the fallback leg answered.
#:
#: The fallback CANNOT FILL FIELDS (see `_answer_via_sarvam`), and a person who asked it to
#: and got prose back is owed the reason. D-127 G-6's disclosure says which model wrote the
#: answer; this says what that costs them, which is the part they can act on.
FALLBACK_NO_TOOLS_NOTE: Final = (
    " It can answer questions about this screen, but it cannot fill in fields or look up "
    "your calls, leads, campaigns or agents."
)


#: Appended, last, on the fallback leg only. See `_answer_via_sarvam`.
_NO_TOOL_NOTE: Final = (
    "CORRECTION for this turn only: the set_fields tool, every lookup tool (this "
    "account's calls, leads, campaigns, agents and performance) and every tool that "
    "proposes a change are NOT available to you right now. Do not call any of them, do not say you "
    "have filled anything in, do not say you have looked anything up, and do not say you "
    "have suggested a change. Answer the question in words from what you can already see. "
    "If the person asked you to fill a field or change something, tell them the value they "
    "should type or the button they should press, and that you cannot do it for them this "
    "time. If they asked for a number about their business, say you cannot look it up "
    "right now — do not estimate one."
)


#: The longest a model-supplied field id may be when it is quoted into a refusal reason.
#: DERIVED from the wire contract rather than retyped, so it moves if `CopilotField.id`'s
#: ceiling ever does and a real id is never cut whatever that ceiling becomes. See
#: `validate_fill` for why the bound exists at all.
#:
#: READ BY `getattr` RATHER THAN BY IMPORTING `annotated_types.MaxLen`, which is the
#: precedent `scripts/check_list_bounds.py::_bounding_parameter` already set for reading
#: Pydantic v2's constraint metadata: `annotated_types` is pydantic's own dependency and
#: not one this project declares, so duck-typing it keeps an undeclared package out of an
#: import line.
_MAX_REASON_ID: Final[int] = max(
    length
    for constraint in CopilotField.model_fields["id"].metadata
    if (length := getattr(constraint, "max_length", None)) is not None
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
    """One step of an answer. Exactly one of the members is set.

    `spend` is emitted exactly once, last, on every path that reached a provider — the
    route needs it whether the answer was good, refused or exhausted, because a completed
    model turn is money spent regardless of what it said.

    `proposal` is a WRITE tool's output and it is NOT a change: `write_tools.py` mints it
    from reads alone, and it becomes a change only when a person posts its token back to
    `POST /v1/copilot/confirm`. It sits beside `fill` rather than inside it because the two
    are different promises — a fill lands in local form state and is undone by a keystroke,
    a proposal is an offer to touch the database.
    """

    text: str | None = None
    fill: tuple[CopilotFillItem, ...] | None = None
    proposal: CopilotProposalEvent | None = None
    #: One tool call, as it happens (D-500). TWO of these per call — `running`, then a
    #: terminal one — and they are the only member of this union that is not exactly one
    #: per answer. Purely observational: a `step` changes nothing and the browser may drop
    #: every one of them without losing an outcome, which is what makes it safe to emit for
    #: reads as well as for actions.
    step: CopilotStepEvent | None = None
    #: A TIER 1 action that HAS ALREADY RUN. Beside `proposal` rather than inside it,
    #: because the two are opposite promises: a proposal is an offer with nothing behind it
    #: yet, this is a receipt for a database write. The browser must never render them the
    #: same way, so the wire does not let it confuse them.
    action: CopilotActionEvent | None = None
    #: A SCREEN TO OPEN (D-524). Beside `action` rather than inside it, because the browser
    #: has to DO something with this one and does nothing with a receipt — a consumer that
    #: rendered them through one path would either navigate on an agent_create or ignore a
    #: navigation. At most one per answer (`navigation.MAX_NAVIGATIONS_PER_RUN`).
    navigate: CopilotNavigateEvent | None = None
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
        raw_field_id = raw.get("field_id")
        if not isinstance(raw_field_id, str) or not raw_field_id:
            reasons.append("one item named no field")
            continue
        # THE ID IS THE MODEL'S TEXT, so it is bounded before it is quoted into a reason.
        # A reason goes back into the NEXT turn's prompt and, when the loop runs out,
        # onto the person's screen: an unbounded id is a model that can grow its own
        # context and paste a wall of text into somebody's panel. A real field id is
        # `_MAX_ID` long by `schemas.CopilotField`, so nothing legitimate is truncated —
        # and a truncated id still fails the lookup below, which is the right answer.
        field_id = raw_field_id[:_MAX_REASON_ID]
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


def _no_answer_sentence(finish_reason: str | None) -> str:
    """What to say when a completed model turn contained no answer. Never an empty string.

    ONE function for every leg — the streamed one, the non-streamed Gemini one and the
    Sarvam fallback — because "the turn said nothing" is a property of the OUTCOME and not
    of the transport, and three sites deciding it separately is how two of them would end
    up silent again.
    """
    if finish_reason is not None and finish_reason.lower() in _FILTERED_FINISH_REASONS:
        return FILTERED_MESSAGE
    if finish_reason == "length":
        return TRUNCATED_MESSAGE
    return NO_ANSWER_MESSAGE


async def _answer_via_sarvam(
    payload: CopilotAskIn,
    capability: AssistCapability,
    *,
    live: str = "",
    realm: CopilotRealm = "client",
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
        [
            *build_messages(payload, live, realm),
            {"role": "system", "content": _NO_TOOL_NOTE},
        ],
        timeout_s=STREAM_IDLE_S,
        temperature=0.2,
        # The same safety valve as the Azure turn. `max_tokens` is on Sarvam's own
        # client's fourteen-key request body (VERIFIED-VENDOR-SDK, `workers/chat.py::
        # _request_body`), so unlike `tools` it is safe to send here — and this leg is
        # PRICED (`billing/rates.SARVAM_LLM_INR_PER_MTOK`, ₹73.20/Mtok out) even though
        # nothing meters it yet, so a runaway would be real unrecorded spend.
        max_tokens=MAX_ANSWER_TOKENS,
    )
    # THE FALLBACK IS SUBJECT TO THE SAME RULE AS THE LOOP: a leg that answered nothing
    # says so. This one is the last rung of the ladder, so silence here is silence for the
    # whole question — there is nothing left to fall back to.
    yield CopilotEvent(
        text=strip_invisible(outcome.content or _no_answer_sentence(outcome.finish_reason))
    )
    yield CopilotEvent(spend=CopilotSpend(usage=None, capability=capability))


# --- the loop -------------------------------------------------------------------------


def build_messages(payload: CopilotAskIn, live: str, realm: CopilotRealm) -> list[Any]:
    """This realm's message list. THE ONE PLACE the realm picks a prompt (D-499).

    Two prompts, two prefixes, two caches — `prompt.SYSTEM_PROMPT` for a business owner and
    `admin_prompt.ADMIN_SYSTEM_PROMPT` for an operator. The ORDER inside each is identical
    and is argued once, in `prompt.py`'s module docstring; neither builder re-decides where
    untrusted content sits.

    A branch here rather than a `realm` parameter on `prompt.build_messages`, because the
    two differ in their CONSTANTS and in nothing else: a single function reading one of two
    module-level strings would put the realm switch inside the file whose whole subject is
    the client prompt, where the next reader would not look for it.
    """
    if realm == "admin":
        return admin_prompt_module.build_admin_messages(payload, live)
    return prompt_module.build_messages(payload, live)


def realm_read_tools(realm: CopilotRealm) -> tuple[tools_module.ReadTool, ...]:
    """The read tools of ONE realm, in a FIXED order. The single enumeration (D-499).

    `tool_array` shows these to the model and `_read_tool_registry` runs them, and both go
    through this function so the schema list and the executable set cannot disagree about
    what exists — the property `tools.py` argues for being a registry at all, now held
    across two realms.

    THE ADMIN REALM GETS BOTH SETS, and the order is platform-first. An operator's own
    tools (roster, triage board, ops state, runbooks) answer the questions that have no
    account behind them; the client tools then answer about the ONE account whose page is
    open, under that account's own RLS, and refuse with a sentence when none is
    (`run_read_tool`'s tenant-scope guard). Giving the admin realm a strict superset is
    what makes "the tenant currently being viewed" a real capability rather than a second
    implementation of six tools that already exist.
    """
    if realm == "admin":
        return (*admin_tools.ADMIN_READ_TOOLS, *tools_module.READ_TOOLS)
    return tools_module.READ_TOOLS


def _read_tool_registry(realm: CopilotRealm) -> Mapping[str, tools_module.ReadTool]:
    """This realm's read tools by name, for `tools.run_read_tool`.

    NOT ONE FLAT NAMESPACE ACROSS BOTH REALMS. A client caller naming `platform_tenants`
    must be told there is no such tool, not that they may not use it: the second sentence
    tells them the admin console has one, which is an information leak with no upside, and
    the permission check that would produce it exists for callers who could plausibly hold
    the permission.
    """
    return {tool.name: tool for tool in realm_read_tools(realm)}


def tool_array(realm: CopilotRealm) -> list[dict[str, Any]]:
    """Every tool the model is offered, in a FIXED order, IDENTICAL ON EVERY REQUEST OF
    THIS REALM.

    ONE COMPOSER FOR BOTH REALMS, so there is still one answer to "what tools exist" and
    the cacheable prefix has one definition per realm. `set_fields` comes first because it
    was first and because moving it would change the prefix for no gain; the read tools
    follow in `realm_read_tools` order, and the proposing write tools last in registration
    order.

    **THE RULE IS NOT "NEVER VARY", IT IS "BYTE-IDENTICAL WITHIN A REALM", AND D-499 IS
    WHERE THAT DISTINCTION HAD TO BE MADE.** Prompt caching keys on a leading run of
    identical tokens: *"A minimum of 1,024 tokens in length"*, *"The first 1,024 tokens in
    the prompt must be identical"*, over *"both the messages array and tool definitions"*
    (MicrosoftDocs/azure-ai-docs, `articles/foundry/openai/includes/
    how-to-prompt-caching-content.md` @ main, read 1 Sep 2026). A REALM is a stable
    partition of requests — every admin request gets one array, every client request gets
    the other — so it is two caches, each hit by its own population. A per-SCREEN or
    per-ROLE array is the thing that destroys caching, because it partitions the traffic
    into slices too small and too numerous to keep warm.

    NOTHING IS GATED OUT OF EITHER ARRAY — not by screen, not by tenant, not by role. A
    caller who may not use a read tool is refused INSIDE it by `tools.run_read_tool`, which
    is where the check has to exist anyway: a schema the model was never shown is
    obscurity, not an access control. `copilot/tools_test.py` pins the byte-identity across
    two differing requests, per realm, and that the two realms differ.
    """
    return [
        prompt_module.set_fields_tool(),
        *[
            prompt_module.function_tool(
                name=tool.name, description=tool.description, parameters=tool.parameters
            )
            for tool in realm_read_tools(realm)
        ],
        *write_tools.write_tool_schemas(),
        # NAVIGATION, LAST, AND CLIENT-REALM ONLY (D-524). `screens.py` is an inventory of
        # the CLIENT console and there is no admin equivalent, so offering the tool to an
        # operator would be offering one whose every argument is a refusal. Appended rather
        # than inserted for the reason `set_fields` stays first: the array is the cacheable
        # prefix, so a new tool costs one re-warm at deploy where a reordering would cost
        # every request behind it.
        *([navigation.open_screen_tool()] if realm == "client" else []),
    ]


async def _run_one_read_tool(
    call: chat.ToolCall,
    *,
    context: ToolContext | None,
    registry: Mapping[str, tools_module.ReadTool],
) -> tuple[CopilotStepEvent, str]:
    """One read call, run under its own clock, as (its terminal step frame, its result).

    **THE PER-CALL BUDGET IS THE POINT OF THIS FUNCTION.** `run_read_tool` never raises,
    but nothing bounded how long it could take: this deployment sets no
    `statement_timeout` anywhere (checked by grep across `apps/api/db` and
    `apps/api/core`, not recalled), so one lookup against a lock or a bad plan could burn
    the whole of `TOTAL_BUDGET_S` and turn a question into either a fallback answer with
    no tools or a "the assistant stopped part-way" body. A stopped lookup is a SENTENCE
    the model can act on — the same shape every other failure in `run_read_tool` already
    takes — so the person is told what could not be read instead of waiting 90 seconds
    for nothing.

    IT ALSO MAKES THE STEP TIMING TRUE. The frames used to be built after `gather`
    returned, so every call in a batch reported the duration of the slowest one — the
    exact number a person watching the panel is trying to find out. Timing here, beside
    the await, is per call because the await is per call.
    """
    started_at = time.monotonic()
    try:
        async with asyncio.timeout(READ_TOOL_BUDGET_S):
            result = await tools_module.run_read_tool(
                call.name, call.arguments, context=context, registry=registry
            )
    except TimeoutError:
        # The tool NAME and nothing else: the arguments were composed by the model out of
        # screen content and the result is the caller's own data (hard rule 6).
        log.warning("copilot_tool_timeout", extra={"tool": call.name})
        timed_out = (
            f"`{call.name}` took too long to answer and was stopped. Tell the user you "
            "could not look that up just now, and do not invent the answer."
        )
        return _step_end(call, status="failed", detail=timed_out, started_at=started_at), timed_out
    if not result.strip():
        # A BLANK TOOL RESULT IS SILENCE ONE LAYER DOWN. `run_read_tool` contracts to
        # return a sentence the model can act on, so this is its bug rather than a state —
        # but the cost of it lands here as a `role: "tool"` message with no content, which
        # some providers reject outright and every model reads as "nothing happened".
        # Answered with our own sentence, and logged so the tool that did it can be found.
        log.warning("copilot_tool_blank", extra={"tool": call.name})
        result = (
            f"`{call.name}` came back with nothing at all. Tell the user you could not "
            "look that up, and do not invent the answer."
        )
    # A REFUSAL FROM A READ TOOL IS STILL A `done` STEP, and that is honest rather than
    # lazy: `run_read_tool` answers a permission refusal, an unknown tool and an empty
    # result with the same kind of sentence, and this function cannot tell them apart
    # without parsing our own prose. The sentence itself is in `detail`, where the person
    # reads it. A TIMEOUT is different — we know that one, so it is `failed`.
    return _step_end(call, status="done", detail=result, started_at=started_at), result


async def _run_read_tools(
    calls: Sequence[chat.ToolCall],
    *,
    context: ToolContext | None,
    registry: Mapping[str, tools_module.ReadTool],
    steps: list[CopilotStepEvent],
    already_run: set[tuple[str, str]],
) -> list[dict[str, object]]:
    """Every read call of ONE turn, executed, as the `role: "tool"` messages that answer them.

    CONCURRENTLY, because independent calls in one turn are independent: "how are calls
    going and which leads are hot" is two lookups with no ordering between them, and running
    them in series doubles the person's wait for nothing. Each opens and closes its OWN
    `tenant_session` (`tools.run_read_tool`), so concurrency here costs a bounded handful of
    pooled connections for the length of a SELECT rather than one held across the stream.

    ONE MESSAGE PER CALL, IN THE ORDER THE MODEL ISSUED THEM, INCLUDING THE ONES WE
    REFUSED, and that is not politeness: a provider rejects a tool result whose
    `tool_call_id` it never issued, and — worse — rejects the NEXT request if an issued
    call has no result at all. So an unknown tool name, a permission refusal, an
    over-the-cap call and a repeat each get an answer rather than silence.
    `run_read_tool` never raises and `_run_one_read_tool` swallows only its own timeout,
    so `gather` needs no `return_exceptions`.

    **A REPEAT IS NOT RUN TWICE.** `already_run` carries (name, arguments) across the whole
    ANSWER, so a model that asks for the identical lookup on turn after turn is told that it
    already has the result instead of being served it again. Nothing about the second answer
    could differ — the same tool, the same arguments, inside one question — so re-running it
    buys a database round trip and a paid turn and changes nothing, and the loop converges on
    a sentence rather than on `MAX_TURNS`. It is keyed on the ARGUMENT STRING as the model
    wrote it: two spellings of the same JSON run twice, which is the safe direction (a
    duplicate lookup, not a withheld one).
    """
    permitted = list(enumerate(calls))[: tools_module.MAX_CALLS_PER_TURN]
    over_cap = list(enumerate(calls))[tools_module.MAX_CALLS_PER_TURN :]
    fresh: list[int] = []
    repeats: list[int] = []
    for index, call in permitted:
        key = (call.name, call.arguments)
        (repeats if key in already_run else fresh).append(index)
        already_run.add(key)

    results = await asyncio.gather(
        *(_run_one_read_tool(calls[index], context=context, registry=registry) for index in fresh)
    )
    # INDEXED, NOT KEYED ON `tool_call_id`. An id is the model's own string and
    # `chat._tool_calls_of` defaults a missing one to "" — two of those in one turn would
    # collide in a dict and pair a call with another call's timing and result.
    contents: list[str] = [""] * len(calls)
    frames: dict[int, CopilotStepEvent] = {}
    for index, (frame, result) in zip(fresh, results, strict=True):
        contents[index], frames[index] = result, frame
    for index in repeats:
        contents[index] = _REPEAT_RESULT
        frames[index] = _step_end(
            calls[index], status="refused", detail=_REPEAT_RESULT, started_at=time.monotonic()
        )
    for index, _ in over_cap:
        contents[index] = (
            f"Not run: you asked for more than {tools_module.MAX_CALLS_PER_TURN} "
            "lookups in one turn. Ask for the ones you still need."
        )
    steps.extend(frames[index] for index, _ in permitted)
    return [
        {"role": "tool", "tool_call_id": call.id, "content": contents[index]}
        for index, call in enumerate(calls)
    ]


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


def _with_tool_result(
    messages: Sequence[chat.ChatMessage],
    outcome: chat.ChatOutcome,
    call: chat.ToolCall,
    result: str,
) -> list[chat.ChatMessage]:
    """The conversation plus "you called this, here is what happened".

    ONE builder for both tool families rather than two copies of the same eight lines. The
    assistant turn has to be replayed WITH its `tool_calls` array and the tool turn has to
    carry the matching `tool_call_id`, or the provider rejects the next request outright —
    which is the kind of detail that gets subtly wrong in the second copy.

    `result` is authored by us and names ids and shapes only: it becomes prompt text, and a
    refusal that quoted a value would put that value in front of the provider (hard rule 6).
    """
    return [
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
        {"role": "tool", "tool_call_id": call.id, "content": result},
    ]


def _preview(value: str) -> str:
    """One string, safe to put in a step frame and short enough to render as a row.

    Stripped of invisible characters (`sanitize`'s egress half — this reaches the DOM), then
    collapsed to one line, then truncated with an ellipsis so a reader can see that there
    was more. NOT redacted here and deliberately: `routes.assert_redacted` has already
    refused the whole request if the payload carried a personal value, and this text is the
    caller's own account data going back to the caller's own screen.
    """
    flat = " ".join(strip_invisible(value).split())
    return flat if len(flat) <= MAX_STEP_CHARS else flat[: MAX_STEP_CHARS - 1] + "…"


def _step_start(call: chat.ToolCall) -> CopilotStepEvent:
    """The frame that says a tool call has STARTED, emitted before it runs.

    The provider's own `tool_call_id` is the step id: it is unique within the response, it
    is already the key the message plumbing uses to pair a call with its result, and
    inventing a second identifier would be a second way to name one thing.
    """
    return CopilotStepEvent(
        id=call.id, tool=call.name, status="running", args=_preview(call.arguments or "")
    )


def _step_end(
    call: chat.ToolCall,
    *,
    status: Literal["done", "refused", "failed"],
    detail: str,
    started_at: float,
) -> CopilotStepEvent:
    """The terminal frame for one call, carrying what came back and how long it took.

    `time.monotonic` rather than the wall clock: this is a DURATION, and a wall clock can
    step backwards under NTP and report a negative one.
    """
    return CopilotStepEvent(
        id=call.id,
        tool=call.name,
        status=status,
        args=_preview(call.arguments or ""),
        detail=_preview(detail),
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
    )


def _problem_result(problem: ProblemError) -> str:
    """A platform refusal, as the tool result the model reads. D-500.

    **THE FOUNDER'S RULE IN ONE FUNCTION: "if the gate refuses, the assistant reports the
    refusal and its remediation — it never retries around it."** A compliance gate that
    said no is not an error to recover from, it is the answer, and the person needs the
    reasons and the next step rather than an apology. `title`, `detail` and `remediation`
    are the three fields every `ProblemError` in this platform already carries and the same
    three the console renders through `ProblemNotice`, so the assistant and the screen say
    the same thing about the same refusal.

    THE `code` IS DELIBERATELY NOT INCLUDED. It is an internal identifier a person cannot
    act on, and a model handed one will repeat it. Nothing here is a value from the object
    either — every string is authored by this repository (hard rule 6).
    """
    parts = [f"REFUSED, and NOTHING was changed. {problem.title}: {problem.detail}"]
    if problem.remediation:
        parts.append(f"What would fix it: {problem.remediation}")
    parts.append(
        "Tell the person this, in your own words, including what would fix it. Do NOT call "
        "the tool again and do NOT look for another way to do it."
    )
    return " ".join(parts)


async def _run_tool_loop(
    payload: CopilotAskIn,
    capability: AssistCapability,
    *,
    leg: chat.ChatLeg,
    turn: _TurnRunner,
    model: str | None,
    realm: CopilotRealm = "client",
    tool_context: ToolContext | None = None,
    live: str = "",
    principal: Principal | None = None,
    seed: str = "",
    ip: str | None = None,
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
    `test_a_valid_set_fields_stops_the_loop_immediately` exists to forbid.

    **THE LOOP NOW DISPATCHES ON THE ACTION'S TIER, AND THAT IS D-500's LOAD-BEARING LINE.**
    An action tool is either `confirm` — plan it, sign it, emit a proposal, END, exactly as
    every write tool did before — or `immediate`, which RUNS and then goes round again so
    the model can tell the person what it did and where to find it. Which of the two is read
    from `write_tools.tier_of`, i.e. from the registry, and from nothing else: not from the
    arguments, not from the object, and above all not from anything the model said. A
    mis-tiered action is a campaign launched with no click, so there is exactly one source
    for the answer and it is a required field with no default.

    A `confirm` action ENDS the loop for the same reason a fill does: one act per turn, so
    the person has one thing in front of them to decide about. An `immediate` action does
    NOT end it, and that asymmetry is the whole point of the tier — the change has already
    happened, so there is nothing to decide and everything to explain, and a run that
    stopped at the write would leave somebody with a receipt and no sentence.

    `principal` is who the actions run AS. It replaced a narrowed `ToolActor` because a Tier
    1 action writes an `audit_log` row in the same transaction as its change and
    `write_audit` names the actor from a `Principal`; passing both would have been one fact
    in two shapes that a caller could get out of step. `None` is a legitimate value that the
    tools refuse rather than a state this function branches on — see
    `write_tools.write_tool_schemas`, which is the same list for every caller precisely so
    that the cacheable prefix cannot become a function of who is asking.

    `seed` is `write_tools.conversation_seed(...)`: what makes a Tier 1 action's idempotency
    key stable across a retry of the same question. `""` means "nobody named this
    conversation", which still produces a deterministic key for a given tool and arguments —
    the same conversation, unnamed, is still one conversation for the length of a run."""
    messages: list[chat.ChatMessage] = list(build_messages(payload, live, realm))
    # ONE LIST, SAME BYTES, EVERY REQUEST OF THIS REALM — see `tool_array`, which is the
    # only composer, and which argues why a realm is a partition caching survives and a
    # screen or a role is not.
    tools = tool_array(realm)
    turns: list[chat.ChatOutcome] = []
    # THE NARROWING HAPPENS ONCE, HERE. `actor_for` is the only place a `Principal` becomes
    # a `ToolActor`, and it refuses rather than defaults, so a principal with no tenant
    # cannot reach a tool as a `None` id.
    actor = None if principal is None else write_tools.actor_for(principal)
    #: How many TIER 1 actions this ANSWER has performed. See `MAX_ACTIONS_PER_RUN` — the
    #: bound is on what one question changed, so it lives outside the turn loop.
    actions_run = 0
    #: How many SCREEN CHANGES this answer has made. Outside the turn loop for
    #: `actions_run`'s reason — the bound is on what one ANSWER did to the person, not on
    #: what one turn asked for. See `navigation.MAX_NAVIGATIONS_PER_RUN`.
    navigations_run = 0
    #: The LAST refusal fed back to the model, kept so the out-of-turns message can name
    #: it. One tuple for both tool families: "narrow the request" is unhelpful advice to
    #: somebody whose real problem is that the field is read-only OR that their role may
    #: not pause a campaign, and the person cannot tell which loop they were in.
    refusal_reasons: tuple[str, ...] = ()
    #: Every (tool, arguments) lookup this ANSWER has already run. Carried across the turns
    #: because that is the span a repeat is pointless over — see `_run_read_tools`.
    lookups_run: set[tuple[str, str]] = set()

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
        if outcome is None:
            # THE STREAM ENDED WITHOUT ITS TERMINAL FRAME — the interruption the vendor's
            # own note warns about (`chat.STREAM_OPTIONS`). It used to `break` into the
            # out-of-turns message below, which blames a turn limit this run never reached
            # and tells the person to narrow a request that was never the problem.
            #
            # THE SPEND IS `None` RATHER THAN THE SUM SO FAR, and that is `_sum_usage`'s
            # rule applied to a turn that never reported at all: a turn happened, it was
            # paid for, and we do not know what it cost. `meter_assist` fires
            # `ai_assist_unmeterable` on that, which is an operator looking at a real
            # interruption rather than a fabricated total on an append-only ledger.
            log.warning("copilot_turn_incomplete", extra={"turn": turn_index})
            yield CopilotEvent(text=strip_invisible(NO_ANSWER_MESSAGE))
            yield CopilotEvent(spend=CopilotSpend(usage=None, capability=capability, model=model))
            return
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

        fill_calls = [
            call for call in outcome.tool_calls if call.name == prompt_module.SET_FIELDS_TOOL_NAME
        ]
        write_calls = [call for call in outcome.tool_calls if write_tools.is_write_tool(call.name)]
        # THE TIER SPLIT, READ FROM THE REGISTRY. `tier_of` is the one reader; a call whose
        # name is in `write_calls` always has a tier, so the `== "confirm"` test is total
        # and the `immediate` list is its complement rather than a second lookup.
        confirm_calls = [
            call for call in write_calls if write_tools.tier_of(call.name) == "confirm"
        ]
        immediate_calls = [call for call in write_calls if call not in confirm_calls]
        # A SCREEN TO OPEN (D-524), and it is a THIRD family rather than a write tool: it
        # touches no row, so it has no planner, no executor, no idempotency record and no
        # audit row (`navigation.py` argues why putting one on the hash chain would be
        # wrong). GATED ON THE REALM, because the tool is only in the client array — an
        # operator's model naming it falls through to `read_calls` and is told there is no
        # such tool, which is the honest answer there.
        nav_calls = (
            [call for call in outcome.tool_calls if call.name == navigation.OPEN_SCREEN_TOOL_NAME]
            if realm == "client"
            else []
        )
        # WHATEVER IS LEFT IS A LOOKUP. Derived by elimination rather than by asking the
        # read registry, so a tool the model invents lands here and is answered by
        # `_run_read_tools` with "no such tool" instead of vanishing into a turn that
        # never explains itself.
        read_calls = [
            call
            for call in outcome.tool_calls
            if call.name != prompt_module.SET_FIELDS_TOOL_NAME
            and not write_tools.is_write_tool(call.name)
            and call not in nav_calls
        ]
        if not fill_calls and not write_calls and not nav_calls and not read_calls:
            # The model answered in prose. Done — this is the ordinary end of a question.
            #
            # UNLESS IT SAID NOTHING, which is the same branch and is NOT the ordinary end
            # of anything: see `NO_ANSWER_MESSAGE`. `outcome.content` is the whole of this
            # turn's text on both legs (`chat.stream` joins the fragments it yielded,
            # `chat.complete` returns the one message), so an empty one means nothing
            # reached the person on this turn and this turn was the last — the run owes
            # them a sentence. Emitted rather than retried: a contentless candidate is a
            # state the vendors document, not a transient, and another turn is another
            # paid round trip at the same odds.
            if not outcome.content.strip():
                log.warning(
                    "copilot_empty_answer",
                    # Ids and shapes (hard rule 6). `finish_reason` is the vendor's own
                    # enum and is what tells an operator a filter from a dropped turn.
                    extra={"turn": turn_index, "finish_reason": outcome.finish_reason},
                )
                yield CopilotEvent(text=strip_invisible(_no_answer_sentence(outcome.finish_reason)))
            yield CopilotEvent(
                spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
            )
            return

        # ONE CALL PER TURN, EVEN IF THE MODEL SENT SEVERAL. `set_fields` takes an array
        # precisely so that a turn has one outcome and one Undo; a second call in the same
        # turn is the documented parallel-tool-call incorrectness, and honouring it would
        # apply two changes a person asked for as one.
        #
        # A TURN THAT MIXES A FILL AND A PROPOSAL IS REFUSED RATHER THAN PART-HONOURED, and
        # that is the one new rule here. Silently dropping the proposal would leave a model
        # that had just told somebody it was suggesting a change having suggested nothing,
        # and silently dropping the fill would lose work. Both go back as one refusal and
        # the model spends a turn separating them.
        # OPENING A SCREEN AND DOING SOMETHING ELSE IN ONE TURN IS REFUSED, and against a
        # FILL it is not a tidiness rule — it is the hazard this whole feature had to be
        # careful about (D-524). A fill writes into the form on the screen the person is
        # standing on and nothing saves it; navigating away in the same breath would throw
        # those values away as its first act. The refusal costs one turn and the model can
        # do either one next.
        if nav_calls and (fill_calls or write_calls):
            call = nav_calls[0]
            reasons = (
                "you asked to open another screen in the same turn as changing something, "
                "which this app cannot do as one act — anything filled into the form on "
                "this screen would be lost by the move",
            )
            messages = _with_tool_result(
                messages,
                outcome,
                call,
                "NOTHING was done and NOBODY was moved. "
                + reasons[0]
                + ". Do one of them in this turn and the other in the next.",
            )
            refusal_reasons = reasons
            log.info("copilot_mixed_navigation_turn", extra={"turn": turn_index})
            continue

        if fill_calls and write_calls:
            call = fill_calls[0]
            reasons = (
                "you filled fields and asked for a change in the same turn, "
                "which this app cannot apply as one act",
            )
            messages = _with_tool_result(
                messages,
                outcome,
                call,
                "NOTHING was written and nothing was proposed. "
                + reasons[0]
                + ". Do one of them in this turn and the other in the next.",
            )
            refusal_reasons = reasons
            log.info("copilot_mixed_tool_turn", extra={"turn": turn_index})
            continue

        if fill_calls:
            call = fill_calls[0]
            try:
                items = validate_fill(payload, call.arguments)
            except FillRefusedError as refused:
                refusal_reasons = refused.reasons
                log.info(
                    "copilot_fill_refused",
                    # Ids and counts. Never a value (hard rule 6), never the model's prose.
                    extra={"turn": turn_index, "reasons": len(refused.reasons)},
                )
                # THE REFUSAL GOES BACK TO THE MODEL rather than to the person, while turns
                # remain. That is what the cap is FOR: a model told `agent_name` is not
                # writable usually fixes it in one more turn, and the alternative —
                # surfacing the first refusal — makes the copilot fail at the thing it
                # exists to do whenever it guesses one field id wrong.
                messages = _with_tool_result(
                    messages,
                    outcome,
                    call,
                    "The fill was refused and NOTHING was written. "
                    + "; ".join(refused.reasons)
                    + ". Fix these and call set_fields once more, or tell the user "
                    "what you need.",
                )
                continue

            yield CopilotEvent(fill=items)
            yield CopilotEvent(
                spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
            )
            return

        # TIER 2 — THE PROPOSING PATH, AND IT WRITES NOTHING. `plan_write` reads, describes
        # and signs; the only thing that reaches the person is a proposal they can refuse by
        # doing nothing. The loop ENDS here for the same reason a fill ends it: one act per
        # turn, so the person has one thing in front of them to decide about.
        #
        # GUARDED, because a read-only turn now reaches this line. Before the read tools
        # existed the prose exit above guaranteed a write call was present by the time
        # control got here, and this was an unconditional `write_calls[0]`; a lookup-only
        # turn would have made that an IndexError.
        #
        # CHECKED BEFORE THE IMMEDIATE PATH, so a turn that somehow asks for both resolves
        # towards the one that needs a person: the proposal is shown, the run ends, and
        # nothing has happened. The opposite order would perform a write and then ask about
        # another one in the same breath.
        if confirm_calls:
            call = confirm_calls[0]
            started_at = time.monotonic()
            yield CopilotEvent(step=_step_start(call))
            try:
                proposal = await write_tools.plan_write(call.name, call.arguments, actor=actor)
            except write_tools.WriteRefusedError as refused:
                refusal_reasons = (refused.reason,)
                log.info(
                    "copilot_write_refused",
                    # The tool NAME and the turn. The reason string is authored by us and names
                    # ids and shapes only, but it is not needed here and a log line is the
                    # cheapest place for a value to end up by accident (hard rule 6).
                    extra={"turn": turn_index, "tool": call.name},
                )
                yield CopilotEvent(
                    step=_step_end(
                        call, status="refused", detail=refused.reason, started_at=started_at
                    )
                )
                messages = _with_tool_result(
                    messages,
                    outcome,
                    call,
                    "NOTHING was proposed and NOTHING was changed. "
                    + refused.reason
                    + ". Fix it and call the tool once more, or tell the user what you need.",
                )
                continue
            except ProblemError as problem:
                # A FACT ABOUT THE WORLD THE MODEL CANNOT ARGUE WITH — a 404 agent, a
                # campaign this account cannot see. It used to end the stream through
                # `routes.py`'s generic arm, which is the right shape for a button and the
                # wrong one for a conversation: the person asked a question and got "the
                # assistant stopped part-way". Handing it back as a tool result lets the
                # model say what the platform said, which is also the founder's rule for a
                # refused gate — report it, do not retry around it.
                refusal_reasons = (problem.title,)
                log.info(
                    "copilot_write_problem",
                    extra={"turn": turn_index, "tool": call.name, "code": problem.code},
                )
                yield CopilotEvent(
                    step=_step_end(
                        call, status="refused", detail=problem.detail, started_at=started_at
                    )
                )
                messages = _with_tool_result(messages, outcome, call, _problem_result(problem))
                continue

            yield CopilotEvent(
                step=_step_end(call, status="done", detail=proposal.summary, started_at=started_at)
            )
            yield CopilotEvent(proposal=proposal)
            yield CopilotEvent(
                spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
            )
            return

        # TIER 1 — IT RUNS, AND THEN THE LOOP GOES ROUND. D-500. The change has already
        # happened by the time the event is emitted, so there is nothing for the person to
        # decide and everything for the model to explain: the outcome goes back as a tool
        # result naming what was done and WHERE IT LIVES, and the next turn is the sentence
        # they read. That is also the founder's cross-screen rule — act from wherever they
        # are, then say where the result is, rather than navigating them.
        if immediate_calls:
            call = immediate_calls[0]
            if actions_run >= MAX_ACTIONS_PER_RUN:
                # A REFUSAL FED BACK, NOT A SILENT STOP. The model still has turns and still
                # owes the person an account of what it did and did not do.
                refusal_reasons = (
                    f"you have already made {MAX_ACTIONS_PER_RUN} changes answering this "
                    "one question, which is the limit",
                )
                log.warning("copilot_action_cap", extra={"turn": turn_index, "tool": call.name})
                yield CopilotEvent(
                    step=_step_end(
                        call,
                        status="refused",
                        detail=refusal_reasons[0],
                        started_at=time.monotonic(),
                    )
                )
                messages = _with_tool_result(
                    messages,
                    outcome,
                    call,
                    "NOTHING was done. " + refusal_reasons[0] + ". Tell the person what "
                    "you have already changed and ask them to confirm the rest in a new "
                    "message.",
                )
                continue
            started_at = time.monotonic()
            yield CopilotEvent(step=_step_start(call))
            try:
                action = await write_tools.run_immediate(
                    call.name, call.arguments, principal=principal, seed=seed, ip=ip
                )
            except write_tools.WriteRefusedError as refused:
                refusal_reasons = (refused.reason,)
                log.info("copilot_action_refused", extra={"turn": turn_index, "tool": call.name})
                yield CopilotEvent(
                    step=_step_end(
                        call, status="refused", detail=refused.reason, started_at=started_at
                    )
                )
                messages = _with_tool_result(
                    messages,
                    outcome,
                    call,
                    "NOTHING was changed. "
                    + refused.reason
                    + ". Fix it and call the tool once more, or tell the user what you need.",
                )
                continue
            except ProblemError as problem:
                # The platform refused: a closed account, an archived agent, an engine that
                # would not take the publish. Same treatment as the Tier 2 arm above and for
                # the same reason.
                refusal_reasons = (problem.title,)
                log.info(
                    "copilot_action_problem",
                    extra={"turn": turn_index, "tool": call.name, "code": problem.code},
                )
                yield CopilotEvent(
                    step=_step_end(
                        call, status="failed", detail=problem.detail, started_at=started_at
                    )
                )
                messages = _with_tool_result(messages, outcome, call, _problem_result(problem))
                continue

            actions_run += 1
            yield CopilotEvent(
                step=_step_end(call, status="done", detail=action.detail, started_at=started_at)
            )
            yield CopilotEvent(action=action)
            messages = _with_tool_result(
                messages,
                outcome,
                call,
                # THE SERVER'S OWN SENTENCE, handed back verbatim. The model is being told
                # what happened rather than being asked to remember what it asked for, which
                # is the difference between "I created it" and "I created it, and it is a
                # draft under Agents".
                f"DONE. {action.detail} The person will find it {action.where}. "
                "Tell them in one or two sentences what you did and where it is. Do not "
                "call this tool again for the same thing.",
            )
            continue

        # OPEN A SCREEN (D-524, closing D-523). A TIER 1 act by the contract's own test —
        # reversible with the back button, reaching no caller, spending nothing — so there
        # is no token and no Confirm button, and the loop GOES ROUND for the Tier 1 reason:
        # the destination is settled and what is left is the sentence that tells the person
        # where they are being taken.
        #
        # THE SERVER DECIDES WHERE AND THE BROWSER DECIDES WHEN. Only the browser can know
        # whether the form on the screen being left is DIRTY, so it asks before it moves
        # when it cannot rule unsaved work out — which is why the tool result below says
        # "opening", not "opened", and why the model is told to say the same.
        if nav_calls:
            call = nav_calls[0]
            started_at = time.monotonic()
            yield CopilotEvent(step=_step_start(call))
            if navigations_run >= navigation.MAX_NAVIGATIONS_PER_RUN:
                refusal_reasons = ("you have already opened a screen answering this question",)
                log.info("copilot_navigation_cap", extra={"turn": turn_index})
                yield CopilotEvent(
                    step=_step_end(
                        call, status="refused", detail=refusal_reasons[0], started_at=started_at
                    )
                )
                messages = _with_tool_result(
                    messages,
                    outcome,
                    call,
                    "NOBODY was moved. " + refusal_reasons[0] + ", and one answer opens at "
                    "most one screen. Tell them where the other screen is instead.",
                )
                continue
            try:
                destination = navigation.resolve_destination(
                    call.arguments,
                    # THE VERIFIED ROLE, from the same `ToolContext` every read tool is
                    # judged against — never from the body, which is a caller-composed
                    # description of a screen. `None` is refused inside `resolve_destination`
                    # rather than defaulted to a role.
                    role=None if tool_context is None else tool_context.role,
                    # WHERE THEY ARE, which is what makes "you are already there" decidable.
                    # It is the browser's own claim about its address and is used ONLY to
                    # avoid a pointless move — never to authorize one.
                    current_route=payload.screen.route,
                )
            except navigation.NavigationRefusedError as refused:
                refusal_reasons = (refused.reason,)
                # The tool NAME and the turn. The reason names a screen and a role and no
                # value, but a log line is the cheapest place for one to end up by accident.
                log.info("copilot_navigation_refused", extra={"turn": turn_index})
                yield CopilotEvent(
                    step=_step_end(
                        call, status="refused", detail=refused.reason, started_at=started_at
                    )
                )
                messages = _with_tool_result(
                    messages,
                    outcome,
                    call,
                    "NOBODY was moved. " + refused.reason + ".",
                )
                continue

            navigations_run += 1
            yield CopilotEvent(
                step=_step_end(
                    call, status="done", detail=destination.detail, started_at=started_at
                )
            )
            yield CopilotEvent(navigate=destination)
            messages = _with_tool_result(
                messages,
                outcome,
                call,
                # THE SERVER'S OWN SENTENCE, handed back verbatim — the model is told what
                # is happening rather than asked to remember what it asked for. The
                # PARENTHESIS IS LOAD-BEARING: if the browser finds unsaved work it asks
                # first, so an assistant that said "you are now on Credits & billing" would be
                # wrong for exactly the person who most needs it not to be.
                f"OPENING {destination.where} for them now. If they have unsaved work on "
                "this screen the console asks them before moving, so say you are opening "
                "it — not that they have arrived. One short sentence naming the screen. Do "
                "not call this tool again.",
            )
            continue

        # A LOOKUP, NOT AN ANSWER, and the only branch that goes round again. It sits
        # AFTER the fill and write paths because both of those END the turn: a turn that
        # asks for a change and a lookup at once resolves the way it always did — the act
        # the person will see wins, and the lookup is dropped rather than answered into a
        # turn that has already shown them something. Anything the model said alongside
        # the calls has already been streamed; only the tool plumbing is added here.
        # THE STEP FRAMES ARE EMITTED AROUND the batch: every `running` first, so the
        # panel shows all of them at once (they run concurrently and a person should see
        # that), then the terminal frames `_run_read_tools` collected with their own
        # per-call timings.
        for call in read_calls[: tools_module.MAX_CALLS_PER_TURN]:
            yield CopilotEvent(step=_step_start(call))
        read_steps: list[CopilotStepEvent] = []
        read_messages = await _run_read_tools(
            read_calls,
            context=tool_context,
            registry=_read_tool_registry(realm),
            steps=read_steps,
            already_run=lookups_run,
        )
        for step in read_steps:
            yield CopilotEvent(step=step)
        messages = [
            *messages,
            _assistant_tool_message(outcome, read_calls),
            *read_messages,
        ]
        log.info("copilot_read_tools", extra={"turn": turn_index, "calls": len(read_calls)})
        continue

    # OUT OF TURNS. The person gets a sentence they can act on, and — when the last thing
    # that happened was a refused tool call — the reason, because "narrow the request" is
    # unhelpful advice to somebody whose real problem is that the field is read-only.
    detail = f" ({'; '.join(refusal_reasons)})" if refusal_reasons else ""
    # STRIPPED LIKE EVERY OTHER TEXT EVENT. This one is assembled here rather than
    # forwarded from `turn`, so it missed the strip in the loop above — and it is not
    # purely our own words: the reasons quote field ids and tool names the MODEL wrote,
    # which is exactly the untrusted string the egress half of the rule exists for.
    yield CopilotEvent(text=strip_invisible(f"{EXHAUSTED_MESSAGE}{detail}"))
    yield CopilotEvent(
        spend=CopilotSpend(usage=_sum_usage(turns), capability=capability, model=model)
    )


async def _answer_stream(
    payload: CopilotAskIn,
    *,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    realm: CopilotRealm = "client",
    tool_context: ToolContext | None = None,
    live: str = "",
    principal: Principal | None = None,
    seed: str = "",
    ip: str | None = None,
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
    `live` is the rendered LIVE BUSINESS STATE block (`copilot/context.py`), composed by the
    route in its own short session BEFORE this runs, and passed in for the third time for
    the same reason: this module holds no connection across a provider call and is not about
    to open one. `""` — the default, and what a degraded snapshot produces — means the model
    sees the screen alone, which is exactly what it saw before that module existed.
    `principal` arrives the same way again: it is WHO IS ASKING, and this module must not go
    looking for one. `None` defaults to "this run may propose nothing and change nothing",
    which the action tools enforce themselves — see `write_tools.plan_write` and
    `write_tools.run_immediate`, both of which refuse an actorless call rather than assuming
    one. It is deliberately NOT a switch that changes the tool list
    (`write_tools.write_tool_schemas`).

    ⚠ **IT WAS A NARROWED `ToolActor` UNTIL D-500 AND IS NOW THE `Principal` ITSELF.** The
    narrowing did not disappear — `write_tools.actor_for` still performs it, once, inside
    the loop — it MOVED, because a Tier 1 action writes an `audit_log` row in the same
    transaction as its change and `write_audit` names the actor from a `Principal`. Passing
    both would have been one fact in two shapes, which a caller can get out of step; passing
    the narrowed one and reconstructing a principal from it would have been a fabricated
    auth object. This is the smaller of the three.

    `seed` and `ip` belong to the same act: the first is what makes a Tier 1 action's
    idempotency key stable across a retry of the same question
    (`write_tools.conversation_seed`), the second is the audit row's fourth field
    (SEC-COMP §5). Both are composed by the ROUTE, which is the only layer that has a
    request.
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
                    realm=realm,
                    tool_context=tool_context,
                    live=live,
                    principal=principal,
                    seed=seed,
                    ip=ip,
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

    async for event in _answer_via_sarvam(payload, capability, live=live, realm=realm):
        yield event


async def run_copilot(
    payload: CopilotAskIn,
    *,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    realm: CopilotRealm = "client",
    tool_context: ToolContext | None = None,
    live: str = "",
    principal: Principal | None = None,
    seed: str = "",
    ip: str | None = None,
) -> AsyncIterator[CopilotEvent]:
    """`_answer_stream`, with the two identity controls around it (`copilot/identity.py`).

    THIS IS THE ONE CHOKEPOINT AND THAT IS WHY IT IS HERE rather than in either route.
    Both realms' routes consume this generator and neither composes an answer of its own,
    so a control at this seam covers the client dashboard, the admin console, all three
    provider legs and the Sarvam fallback — and a fourth leg added tomorrow inherits it
    without anybody remembering to. Wrapping in a route would have been two copies of one
    rule, which is the arrangement they drift apart from.

    CONTROL 1, BEFORE THE GATE AND BEFORE THE SELECTOR. A question that is asking what the
    assistant IS is answered from `CANONICAL_IDENTITY_ANSWER` here — no capability lookup,
    no provider, no tokens, no `CopilotSpend`. It precedes `assist_capability`
    deliberately: an account whose provider is down or whose quota is spent still gets a
    true answer to "who are you", because this answer costs nothing to give and refusing
    it would be an outage in a sentence that never needed a model. The route already
    handles a run that emits no spend — `_record` writes nothing when `spends` is empty.

    CONTROL 2, ON EVERY FRAGMENT THAT COMES BACK. `IdentityEgress` is the belt: it holds
    the sentence in flight, and text asserting that this assistant is some vendor's model
    never reaches the browser whatever the model emitted. Only `text` is filtered — a
    `fill`, a `proposal`, an `action`, a `navigate` and the `spend` are structured events
    whose only prose is the SERVER'S OWN, and a run that leaked one sentence still filled
    the field it was asked to.
    """
    canned = identity_answer(payload.question)
    if canned is not None:
        yield CopilotEvent(text=canned)
        return

    egress = IdentityEgress(strict=question_touches_model_identity(payload.question))
    inner = _answer_stream(
        payload,
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
        realm=realm,
        tool_context=tool_context,
        live=live,
        principal=principal,
        seed=seed,
        ip=ip,
    )
    try:
        async for event in inner:
            if event.text is not None:
                released = egress.feed(event.text)
                if released:
                    yield CopilotEvent(text=released)
                continue
            if event.spend is not None:
                # THE HELD TAIL GOES OUT BEFORE THE SPEND, not after the generator
                # ends. `spend` is emitted last on every path that reached a provider, so
                # this is where an answer finishes; flushing after the loop instead would
                # print the last sentence of the answer AFTER the event that says the
                # answer is paid for and done, which is the wrong order on the wire and
                # reads as a second answer in the panel. Emitting it twice is not possible
                # — `close` clears what it released — and the fallback leg's second spend
                # flushes its own.
                tail = egress.close()
                if tail:
                    yield CopilotEvent(text=tail)
            yield event
    except Exception:
        # `Exception` AND NOT `BaseException`, which is not a stylistic choice: a browser
        # that closes the panel throws `GeneratorExit` into this generator, and yielding
        # inside a `GeneratorExit` handler is a `RuntimeError` ("async generator ignored
        # GeneratorExit"). There is also nobody left to yield to. Cancellation is the same
        # argument. A provider failure is an ordinary `Exception` (`httpx.HTTPError`,
        # `TimeoutError`) and is the only case this arm is for.
        #
        # A PROVIDER THAT DIED MID-ANSWER STILL OWES THE PERSON WHAT IT ALREADY SAID, and
        # without this arm the buffer would swallow it. `run_copilot`'s whole fallback rule
        # turns on whether anything reached the screen, and the fragment held here IS what
        # reached it as far as `_answer_stream` is concerned — so it goes out, judged, in
        # front of the failure rather than being dropped by the guard that was only ever
        # meant to delay it. Yielded before the re-raise, which is the order the route's
        # `except` arm already expects (`routes.py`: text frames, then a problem body).
        held = egress.close()
        if held:
            yield CopilotEvent(text=held)
        raise
    # A path that ended without a spend (the selector refused before any leg) can still
    # be holding text. Never reached in production; cheaper than reasoning about whether.
    remainder = egress.close()
    if remainder:
        yield CopilotEvent(text=remainder)
    if egress.substituted:
        # An operator's line, not a person's. Ids and shapes only (hard rule 6): the
        # offending sentence is exactly the text this control exists to keep out of
        # places it does not belong, so it is counted and never quoted.
        log.warning("copilot_identity_substituted", extra={"realm": realm})


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
    "FILTERED_MESSAGE",
    "MAX_ANSWER_TOKENS",
    "MAX_TURNS",
    "NO_ANSWER_MESSAGE",
    "READ_TOOL_BUDGET_S",
    "STREAM_IDLE_S",
    "TOTAL_BUDGET_S",
    "TRUNCATED_MESSAGE",
    "CopilotEvent",
    "CopilotSpend",
    "FillRefusedError",
    "ToolContext",
    "disclosure_for",
    "run_copilot",
    "tool_array",
    "validate_fill",
]
