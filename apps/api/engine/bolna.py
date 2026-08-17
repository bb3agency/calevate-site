"""Bolna adapter — the ONLY place in the codebase that knows Bolna's payload shapes.

Adopted by D-31 (supersedes D-02's ThinnestAI pick), gated on the pilot scorecard.
Everything here is hand-maintained from docs.bolna.ai + payloads captured during the
pilot, because **Bolna publishes no OpenAPI spec** (TRD §5). Treat every field name as
a claim that needs re-checking against a captured payload, not as a guarantee.

Three properties of this vendor shape the whole design and are load-bearing:

1. **Webhooks are unsigned and at-most-once** (verified in their docs AND their OSS
   delivery code: a single aiohttp POST, no retry, no timeout, errors swallowed). So
   authenticity = source-IP allowlist + execution-id dedupe, webhook payloads are
   HINTS, and the List-Executions poller is the guarantee of record.
2. **cost / recording_url / extracted_data populate only at `completed`**, roughly
   2-3 min after disconnect. The post-call pipeline therefore triggers on `completed`,
   never on a disconnect event — `billable_ready` encodes exactly that.
3. **Costs arrive in USD cents** with a per-leg breakdown. The adapter converts to INR
   at capture and stamps the fx rate, so a ledger row can always be re-derived
   (hard rule 7).

Per-turn timings are NOT mapped here, and there is no call-latency column to map them
into any more (migration f1a7c39d5be2 dropped it). Their docs now describe a
`latency_data` object on Get Execution — per-component `transcriber`/`llm`/`synthesizer`
timings plus a first-audio number — but it is an unverified claim with no captured
payload, it is not the voice-to-voice measurement the budget is written in, and its
transcriber entries carry recognised TEXT (hard rules 5/6). So it stays a PILOT GATE:
capture it at OPERATIONS §2 gate 4 beside the stopwatch that can falsify it, then decide
what to store. Until then latency measurement is the stopwatch, not a field.

Resilience shipped here: a request timeout and jittered backoff on 429 (SURFACES §3.3).
The circuit breaker that section also describes is deliberately NOT built — see the
throttle block below for what is and is not retried, and why.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
from calevate_shared.config import bolna_source_ips
from calevate_shared.engine import (
    E164,
    AgentConfig,
    AgentSnapshot,
    CallContext,
    CallHandle,
    CostBreakdown,
    EngineAgentRef,
    EngineCapabilities,
    EngineKBRef,
    ExecutionListing,
    ExecutionSnapshot,
    KBSourceRef,
    ListingIncompleteReason,
    ModelConfig,
    NumberSpec,
    ProvisionedNumber,
    WebhookVerdict,
    compose_engine_prompt,
)
from calevate_shared.events import CallEvent, CallStatus, TranscriptTurn

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import require_capability, require_speech_leg
from apps.api.engine.document import engine_document

log = get_logger(__name__)

BASE_URL = "https://api.bolna.ai"
REQUEST_TIMEOUT_S = 10.0

# --- Throttle handling (SURFACES §3.3) ---------------------------------------
# Bolna's rate limits are unpublished (pilot item), so 429 is a response we will meet
# without warning. Three deliberate limits on what we do about it:
#
# 1. **429 ONLY.** A 429 means the request was refused, not performed — the one status
#    where retrying `POST /call` cannot dial a person twice. A 502/503/504 on the same
#    endpoint is ambiguous, so those are reported, never repeated. Retrying a
#    non-idempotent create because it "felt transient" is how a lead gets two calls.
# 2. **Jitter, always.** Our workers are throttled in the same second and would
#    otherwise retry in the same second; a synchronized herd is how a rate limit
#    becomes an outage. Full jitter, and a `Retry-After` is a floor we never undercut.
# 3. **A short ceiling.** Adapter calls happen inside request handlers as well as
#    workers, so the adapter may stall a request by a second or two — not by two
#    minutes. A `Retry-After` longer than the ceiling is not slept through: it is
#    reported as `transient`, which is the caller's cue to reschedule the work.
THROTTLE_STATUS = 429
THROTTLE_MAX_ATTEMPTS = 3
THROTTLE_BASE_S = 0.5
THROTTLE_MAX_SLEEP_S = 8.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """`Retry-After` in delay-seconds form. The HTTP-date form is not parsed on
    purpose: a clock-skewed date is worse than no hint, and the fallback is a sane
    backoff either way."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def throttle_delay_s(
    attempt: int,
    retry_after: float | None,
    *,
    rand: Callable[[], float] = random.random,
) -> float:
    """How long to wait before retry `attempt` (0-based). Never zero-variance.

    `rand` is injected so the jitter is assertable in a test — an un-jittered backoff
    passes every "does it retry" test ever written and still takes the platform down.
    """
    if retry_after is not None:
        # Their number is a FLOOR. Jitter goes on top so we do not all wake together
        # at exactly the moment they told everyone to wake.
        return retry_after + THROTTLE_BASE_S * rand()
    # Full jitter over an exponentially growing ceiling: the delay is uniform in
    # [0, capped], so two workers throttled in the same second do not wake in the same
    # second. A fixed backoff would just move the herd, not disperse it.
    capped = min(THROTTLE_BASE_S * (2.0**attempt), THROTTLE_MAX_SLEEP_S)
    return capped * rand()


# Their 15-value status enum → our 8. Anything unmapped becomes `failed`, which is the
# safe direction: a call we cannot classify must not look successful.
_STATUS_MAP: dict[str, CallStatus] = {
    "scheduled": "queued",
    "queued": "queued",
    "initiated": "ringing",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "call-connected": "in_progress",
    "call-disconnected": "completed",
    "completed": "completed",
    "no-answer": "no_answer",
    "busy": "busy",
    "voicemail": "voicemail",
    "failed": "failed",
    "canceled": "failed",
    "cancelled": "failed",
    "stopped": "failed",
    "error": "failed",
    "balance-low": "failed",
}

_TERMINAL_RAW = frozenset(
    {
        "completed",
        "no-answer",
        "busy",
        "failed",
        "canceled",
        "cancelled",
        "stopped",
        "error",
        "balance-low",
        "voicemail",
    }
)

# Transcript arrives as prefix-tagged plain text, e.g.
#   "assistant: namaskaram\nuser: appointment kavali"
_TURN_RE = re.compile(r"^\s*(assistant|agent|user|human|bot)\s*:\s*(.*)$", re.IGNORECASE)
_SPEAKER_MAP = {
    "assistant": "agent",
    "agent": "agent",
    "bot": "agent",
    "user": "caller",
    "human": "caller",
}

_PAISE = Decimal("0.0001")

# What the adapter treats a cost as when the payload does not say. Read off docs.bolna.ai
# and NOT confirmed against a live account — pilot gate 7 (OPERATIONS §2) is where it
# stops being an assumption. `CostBreakdown.currency_stated` carries the difference into
# every row, so a wrong guess is discoverable rather than baked in.
_ASSUMED_CURRENCY = "USD"
# Currencies this adapter can turn into INR. Anything else is refused rather than
# converted at the wrong rate — see `_cost`.
_CONVERTIBLE_CURRENCIES = frozenset({"USD", "INR"})


def _to_inr(usd_cents: Any, fx_rate: Decimal) -> Decimal | None:
    """USD cents → INR, quantized to the ledger's NUMERIC(12,4). Floats never touch
    money: the vendor value is stringified before it becomes a Decimal."""
    if usd_cents is None:
        return None
    try:
        cents = Decimal(str(usd_cents))
    except (ArithmeticError, ValueError):
        return None
    return (cents / Decimal(100) * fx_rate).quantize(_PAISE, rounding=ROUND_HALF_UP)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --- List-Executions completeness (D-31: this poller IS the guarantee of record) ------
#
# Bolna documents no pagination for GET /executions and publishes no OpenAPI spec, so we
# do not know whether it paginates, what the page size is, or what a continuation looks
# like. What we refuse to do is GUESS a parameter name and loop on it: a `?page=` the
# vendor ignores returns page one forever, which is a silent truncation wearing the
# costume of a fix (the same class of silent premise D-31/D-32 exist to prevent).
#
# So: follow a continuation ONLY if the payload hands us one (`_next_link`), and
# otherwise report whether the answer might have been cut short.
#
# `_LISTING_PAGE_SIZES` is the heuristic that makes "might have been cut short"
# answerable with no metadata at all. A truncated listing returns EXACTLY the server's
# limit; an untruncated one returns however many executions the window happened to hold.
# Landing exactly on a conventional limit is therefore weak evidence of truncation, and
# it is the only evidence available. The failure modes are asymmetric and that is the
# whole argument: a false positive (a window that really held exactly 100 calls) costs
# one alert an operator can dismiss in ten seconds; a false negative is a call nobody
# ever hears about again. Rejected alternative: comparing counts across ticks — it needs
# state, it is confounded by traffic, and it still cannot tell page one from a quiet
# hour. Delete this heuristic once the pilot records the real page size (OPERATIONS §2
# gate 6); until then it is the only thing standing between us and a silent gap.
_LISTING_PAGE_SIZES = frozenset({10, 20, 25, 50, 100, 200, 250, 500, 1000})
# A bound on continuation-following. 20 pages at any plausible page size covers far more
# than a 30-minute reconciliation window, and a bound is what keeps a malformed `next`
# from turning the poller into an infinite request loop against the vendor.
_LISTING_MAX_PAGES = 20


def _listing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The execution rows in one List-Executions response, whatever they are wrapped in.

    Both key names are claims from their docs; `_request` also wraps a bare top-level
    JSON array as `{"data": [...]}`, which is the third shape this has to survive.
    """
    data = payload.get("data")
    rows = data if isinstance(data, list) else payload.get("executions")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _claims_more(payload: dict[str, Any], row_count: int) -> bool:
    """Does the response ITSELF say the window holds more than it returned?

    Every key here is a hypothesis about a payload nobody has captured yet, so this is
    written to be inert when absent and correct when present: an unknown shape simply
    never matches, and the page-size heuristic remains the backstop. A `total` that is
    not larger than what we got is not a claim of more — that is the normal, complete
    answer, and treating it as truncation would alert on every healthy tick.
    """
    for key in ("has_more", "has_next", "more"):
        value = payload.get(key)
        if isinstance(value, bool) and value:
            return True
    for key in ("total", "total_count", "count", "total_results"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > row_count:
            return True
    # A cursor we cannot turn into a request (`_next_link` rejected it as off-origin, or
    # it is an opaque token whose parameter name we would have to guess) is still the
    # vendor telling us there is another page. This runs only after `_next_link` has
    # declined, so a followable link never lands here.
    for key in ("next_cursor", "next_page_token", "cursor", "next", "next_page_url", "next_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


# --- reading an agent back (see `BolnaEngine.get_agent` for the evidence) ------
#
# Every name below is a hand-maintained claim, so each helper is written to be INERT
# when the shape is not what we guessed: it returns "could not read" rather than a
# confident empty answer. That asymmetry is the whole design — an unreadable prompt must
# not look like an applied one, and an unlocatable KB reference must not look like a
# cleared one (D-41).

#: Envelopes their OSS server is documented to use around the agent object
#: (`GET /all` rows are `{"agent_id": ..., "data": {...}}`). Tried in order; a payload
#: that is already the agent object falls through unwrapped.
_AGENT_ENVELOPE_KEYS = ("data", "agent", "agent_data")

#: Field names that MIGHT hold the agent's knowledge-base reference. Pure guesswork —
#: nothing in their published documentation says the agent object carries one at all
#: (see `get_agent`). Present-but-empty is an answer ("this agent references nothing");
#: absent everywhere is NOT an answer, and `_agent_kb_refs` reports the difference.
_AGENT_KB_REF_KEYS = frozenset(
    {"rag_id", "rag_ids", "knowledgebase_id", "knowledge_base_id", "vector_store_id"}
)

#: How deep the KB-reference search walks. Their agent object nests
#: agent_config → tasks[] → tools_config → <component>, i.e. four or five levels; the
#: bound stops a pathological or hostile payload from turning a read-back into a hang.
_AGENT_WALK_MAX_DEPTH = 8


def _agent_object(payload: dict[str, Any]) -> dict[str, Any]:
    """The agent object itself, whatever envelope it arrived in."""
    for key in _AGENT_ENVELOPE_KEYS:
        inner = payload.get(key)
        if isinstance(inner, dict):
            # Keep the envelope's own id reachable: their list rows carry `agent_id`
            # OUTSIDE `data`, and losing it would make every read-back anonymous.
            merged = dict(inner)
            for id_key in ("agent_id", "id"):
                if id_key not in merged and isinstance(payload.get(id_key), str):
                    merged[id_key] = payload[id_key]
            return merged
    return payload


def _agent_name(agent: dict[str, Any]) -> str | None:
    config = agent.get("agent_config")
    source = config if isinstance(config, dict) else agent
    name = source.get("agent_name") or source.get("name")
    return name if isinstance(name, str) and name else None


def _agent_system_prompt(agent: dict[str, Any]) -> str | None:
    """The live system prompt, or None when the response does not contain one.

    `agent_prompts` is keyed by task (`task_1` is the conversation task we create). The
    first task is preferred rather than "any prompt we can find": an agent with several
    tasks has several prompts, and returning an arbitrary one would let gate 2 score a
    marker against a prompt nobody updated. Falling back to the sole remaining entry is
    safe for the same reason — there is nothing to confuse it with.
    """
    prompts = agent.get("agent_prompts")
    if not isinstance(prompts, dict):
        return None
    candidates = [prompts.get("task_1")] if "task_1" in prompts else list(prompts.values())
    if len(candidates) != 1:
        return None
    task = candidates[0]
    if not isinstance(task, dict):
        return None
    prompt = task.get("system_prompt")
    return prompt if isinstance(prompt, str) and prompt else None


def _agent_greeting(agent: dict[str, Any]) -> tuple[str | None, bool]:
    """`(greeting, readable)` — the welcome message the engine holds.

    `agent_welcome_message` is the key `_agent_body` SENDS (read at source in their OSS
    server's agent object), so this is hand-maintained from our own request shape for
    `_agent_system_prompt`'s reason — Bolna publishes no OpenAPI spec. If their read path
    spells it differently the honest outcome is `readable=False`, which the judge reports
    as `unreadable` rather than as a missing disclosure: an adapter that cannot find the
    field must not be able to fail a publish on a compliance ground (P3.3).

    A `(readable, value)` PAIR rather than "None means unreadable", which is the shape
    the prompt reader uses and the wrong one here. A key present and EMPTY is an agent
    that speaks nothing first — a real compliance failure, and exactly the shape a vendor
    dropping an unrecognised field takes — while an ABSENT key is our own adapter looking
    in the wrong place. Collapsing them would turn every provable failure into a shrug,
    which is the direction that lets an agent go live saying nothing.
    """
    config = agent.get("agent_config")
    source = config if isinstance(config, dict) else agent
    if "agent_welcome_message" not in source:
        return None, False
    greeting = source.get("agent_welcome_message")
    return (greeting if isinstance(greeting, str) else ""), True


def _agent_models(agent: dict[str, Any]) -> tuple[ModelConfig | None, bool]:
    """`(selections, readable)` — the BYOK choices the agent is RUNNING, in our terms.

    The read half of the `EngineCapabilities` BYOK claim (D-93). `update_agent` sends
    `llm_agent.model`, `synthesizer.provider`/`provider_config.voice` and
    `transcriber.provider`/`model`; without a way to read them back, "the engine is using
    Bulbul v3" was a claim resting on a 2xx — the same ACCEPTED-versus-APPLIED gap
    `AgentSnapshot.system_prompt` was introduced to close, for the setting that decides
    what a client's caller actually HEARS.

    `readable=False` when the tools block cannot be located at all, for the third time
    for the reason `_agent_kb_refs` gives: "we could not find the synthesizer" and "this
    agent has no voice configured" are different facts with opposite next actions, and
    reporting the first as the second would let a publish that never applied read as an
    agent deliberately left on the engine's default.

    SAME STANDING AS `_agent_system_prompt`: hand-maintained from the shape we POST,
    because Bolna publishes no OpenAPI spec. If their read path names these fields
    differently the honest outcome is `readable=False`, not a wrong answer.
    """
    config = agent.get("agent_config")
    tasks = config.get("tasks") if isinstance(config, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return None, False
    first = tasks[0]
    tools = first.get("tools_config") if isinstance(first, dict) else None
    if not isinstance(tools, dict):
        return None, False

    def leaf(block: str, *path: str) -> str | None:
        node: Any = tools.get(block)
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node if isinstance(node, str) and node else None

    return (
        ModelConfig(
            stt_provider=leaf("transcriber", "provider"),
            stt_model=leaf("transcriber", "model"),
            llm_model=leaf("llm_agent", "model"),
            tts_provider=leaf("synthesizer", "provider"),
            tts_voice=leaf("synthesizer", "provider_config", "voice"),
        ),
        True,
    )


def _agent_kb_refs(agent: dict[str, Any]) -> tuple[list[EngineKBRef], bool]:
    """`(handles, readable)` — the agent's own knowledge references, and whether we
    actually found the field that would hold them.

    `readable=False` is the honest answer when no candidate key appears anywhere in the
    object, and it is NOT the same as an empty list: D-41 asks whether a deleted
    knowledge base leaves the agent pointing at a dead `rag_id`, and "we could not find
    the field" would otherwise be recorded as "the reference was cleared" — closing the
    question in the direction that adds no work to our code, on no evidence.
    """
    handles: list[EngineKBRef] = []
    found_key = False

    def walk(node: Any, depth: int) -> None:
        nonlocal found_key
        if depth > _AGENT_WALK_MAX_DEPTH:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _AGENT_KB_REF_KEYS:
                    found_key = True
                    for candidate in value if isinstance(value, list) else [value]:
                        if isinstance(candidate, str) and candidate and candidate not in handles:
                            handles.append(candidate)
                    continue
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(agent, 0)
    return handles, found_key


def parse_transcript(raw: str | None, call_id: str) -> tuple[list[TranscriptTurn], int]:
    """Prefix-tagged text -> typed turns, AND how many lines were lost. `(turns, lost)`.

    A continuation line with no prefix is appended to the previous turn rather than
    dropped — long agent answers wrap. Two lines genuinely cannot be placed, and both
    used to vanish without trace:

    * an unprefixed line arriving BEFORE any turn exists — there is no previous turn to
      append it to, and inventing a speaker for it would put words in someone's mouth;
    * a recognised prefix with an empty body.

    THE COUNT IS THE POINT. This returned a bare list, so a shape it does not recognise
    at all came back as `[]` — identical to a call where nobody spoke. Pilot gate 7's
    transcript criterion could therefore only ever detect a TOTAL parse failure, and a
    prefix-format change that cost us a third of every transcript would have looked like
    quiet callers (OPERATIONS §2). The count travels to `ExecutionSnapshot
    .transcript_lines_unparsed` and the gate scores it.

    A COUNT, not the lines. Hard rule 6: transcript text never leaves the engine
    boundary except as a `TranscriptTurn`, so what could not become one is measured and
    discarded rather than logged for later inspection.
    """
    if not raw:
        return [], 0
    turns: list[TranscriptTurn] = []
    lost = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        match = _TURN_RE.match(line)
        if match is None:
            if turns:
                previous = turns[-1]
                turns[-1] = previous.model_copy(
                    update={"text": f"{previous.text} {line.strip()}".strip()}
                )
            else:
                lost += 1
            continue
        speaker = _SPEAKER_MAP.get(match.group(1).lower(), "caller")
        text_value = match.group(2).strip()
        if not text_value:
            lost += 1
            continue
        turns.append(
            TranscriptTurn(
                call_id=call_id,
                idx=len(turns),
                speaker=speaker,
                text=text_value,
            )
        )
    return turns, lost


# Bolna's answers (D-93). Every one of these was already true and was previously
# expressed only as a `raise` inside the method that hit it — discoverable by calling and
# failing, which is why screens could offer controls this engine refuses.
#
# WHAT IS GROUNDED: BYOK on all three legs is D-31/D-36 and is what `_agent_body` above
# actually sends (`llm_agent.model`, `synthesizer.provider`, `transcriber.provider` all
# carry OUR strings). The built-in knowledge base is the `rag_id` CRUD API this adapter
# calls. `webhook_auth="source_ip"` is D-31's finding that Bolna signs nothing.
#
# WHAT IS A DELIBERATE *NO* RATHER THAN AN UNKNOWN:
# * `campaigns=False`. Bolna HAS campaign objects; TRD §5 records them and CLAUDE.md
#   prefers configuring engine built-ins over rebuilding them. We do not use them — every
#   campaign in this system is dispatched by `apps/api/campaigns` + `apps/workers`,
#   through the compliance gate, which is not something an engine-side campaign object
#   can be trusted to run (hard rule 5 forbids a bypass). So the honest value of this
#   field, whose meaning is "is there an engine-side campaign object OUR code depends
#   on", is False. If that ever changes it is a decision-log entry, not a flag flip.
# * `number_series=frozenset()`. Numbers come from the telephony vendor directly (D-05:
#   Exotel, Vobiz for the 140-series) — `campaigns/provisioning.py` is that seam. This
#   adapter's `provision_number` has always raised; now it says so before being called.
# * `transfer=False`. Bolna may well support it; nobody has run the pilot gate, and an
#   unverified vendor behaviour is not a capability (D-31/D-32). False is therefore the
#   only answer we can stand behind, and the pilot gate is what changes it. `transfer`
#   below now raises the ONE capability refusal rather than its own private
#   `engine_capability_unverified` — a method whose refusal code disagreed with the
#   descriptor is the drift this descriptor exists to remove.
BOLNA_CAPABILITIES = EngineCapabilities(
    stt="ours",
    tts="ours",
    llm="ours",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    transfer=False,
    webhook_auth="source_ip",
)


class BolnaEngine:
    """Implements `VoiceEngine`. Constructed per process; the httpx client is reused."""

    name = "bolna"
    capabilities = BOLNA_CAPABILITIES
    #: `BOLNA_API_KEY` only. An injected client also satisfies `holds_credentials`, but no
    #: operator can set one from a console, so it is not a key readiness may name.
    # Annotated, not inferred: without it mypy reads `tuple[str]` (a ONE-element tuple
    # type), and a Protocol's mutable attributes are invariant, so the adapter would stop
    # satisfying `VoiceEngine` the moment a second key is added. Same for every adapter.
    credential_env_keys: tuple[str, ...] = ("BOLNA_API_KEY",)

    def __init__(
        self,
        *,
        api_key: str | None,
        fx_rate: Decimal,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._fx_rate = fx_rate
        self._base_url = base_url
        self._client = client

    def holds_credentials(self) -> bool:
        """An API key, or an injected client (the conformance stub and the pilot harness
        both supply one). Mirrors `_http`'s own precondition exactly rather than
        restating it — a second copy of that rule is a second thing to get wrong."""
        return bool(self._api_key) or self._client is not None

    # --- plumbing ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                raise ProblemError(
                    kind="dependency",
                    code="engine_not_configured",
                    title="Voice engine is not configured",
                    detail="No Bolna API key is available in this environment.",
                )
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def _request(
        self, method: str, path: str, *, absent_is_success: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        """One vendor round trip, with the throttle ladder and the error normalization.

        `absent_is_success` exists for `delete_agent` and for nothing else: the Protocol
        makes delete IDEMPOTENT, so "the object you asked me to remove is not here" is
        that method's postcondition rather than a failure. It is opt-in per call site
        because on every OTHER route a 404 is a real defect — `get_agent` raising on an
        unknown ref is a contract clause, and a path we got wrong 404s exactly the same
        way, which is how a wrong path gets FOUND (see `get_agent`'s note on gate 2).
        """
        for attempt in range(THROTTLE_MAX_ATTEMPTS):
            try:
                response = await self._http().request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise ProblemError(
                    kind="dependency",
                    code="engine_unreachable",
                    title="Voice engine unreachable",
                    detail="The voice platform did not respond.",
                    failure_stage="CORE_LOGIC",
                ) from exc
            if response.status_code != THROTTLE_STATUS:
                break
            retry_after = _retry_after_seconds(response)
            last_attempt = attempt == THROTTLE_MAX_ATTEMPTS - 1
            if last_attempt or (retry_after is not None and retry_after > THROTTLE_MAX_SLEEP_S):
                break
            log.warning("engine_throttled", extra={"route": path, "attempt": attempt + 1})
            await asyncio.sleep(throttle_delay_s(attempt, retry_after))

        if response.status_code == THROTTLE_STATUS:
            # Distinct from `engine_rejected` on purpose. A throttle says nothing about
            # the request — so on the campaign path it must not burn a contact's retry
            # budget for a reason that has nothing to do with the contact. `transient`
            # is the ladder rung that means "identical retry can work" (503, retryable).
            log.warning("engine_throttle_exhausted", extra={"route": path})
            raise ProblemError(
                kind="transient",
                code="engine_rate_limited",
                title="Voice engine is rate limiting us",
                detail="The voice platform is temporarily refusing new requests.",
                remediation="This will be retried automatically.",
                failure_stage="CORE_LOGIC",
            )
        if absent_is_success and response.status_code == 404:
            # NOT a swallowed error: the caller declared that an absent object satisfies
            # it. Logged at info so a compensation that found nothing to compensate is
            # still legible in the record — `delete_agent`'s caller is an orphan
            # reclaimer, and "there was no orphan" is a fact worth having.
            log.info("engine_delete_already_absent", extra={"route": path})
            return {}
        if response.status_code >= 400:
            # Never echo a vendor error body to a client — it is not user-safe and it
            # is not our vocabulary.
            log.warning("engine_error", extra={"status": response.status_code, "route": path})
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform could not complete this operation.",
                failure_stage="CORE_LOGIC",
            )
        if not response.content:
            # A successful DELETE may answer 204/empty. `response.json()` raises on an
            # empty body, and a delete that "failed" only because the vendor said
            # nothing is the worst possible lie on this particular path.
            return {}
        try:
            payload = response.json()
        except ValueError:
            # A 2xx WITH A NON-JSON BODY (P2.2). The `>= 400` branch above raises first,
            # so what reaches here is a success status carrying something that is not
            # JSON: a WAF challenge, a proxy interstitial, a CDN maintenance page. Those
            # are the ordinary failure modes of an API behind an edge, and they are
            # indistinguishable from a real answer until the parse fails.
            #
            # `json.JSONDecodeError` is a `ValueError` — NOT a `ProblemError` and NOT an
            # `httpx.HTTPError` — so it was caught by nothing. It surfaced as a raw 500
            # with no code and no remediation on `create_agent`; it made
            # `verify_publish`'s "never raises for a vendor-side failure" docstring
            # false; and it DLQ'd the post-call pipeline and the reconciliation poller,
            # which is D-31's guarantee of record.
            #
            # This repository had already solved it twice — `billing/payments.py` catches
            # `ValueError` and `payment_order_test` pins it by name, and
            # `engine/cartesia.py` has the guard. The adapter actually going to
            # production is the one that missed it.
            #
            # RAISED rather than returning `{}` like Cartesia's, and the difference is
            # deliberate: an empty dict here would flow on to callers that read fields
            # out of it and fail somewhere further from the cause. The body is never
            # echoed — it is not our vocabulary and it is not user-safe.
            log.warning(
                "engine_non_json_success",
                extra={"status": response.status_code, "route": path},
            )
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unreadable response",
                detail="The voice platform answered successfully with a body we could not read.",
                failure_stage="CORE_LOGIC",
            ) from None
        return payload if isinstance(payload, dict) else {"data": payload}

    # --- agent lifecycle -----------------------------------------------------

    def _agent_body(self, cfg: AgentConfig) -> dict[str, Any]:
        """Our AgentConfig → their agent object.

        TWO STRINGS OUR LAYER OWNS BRACKET THE CLIENT'S SCRIPT, and the order is the
        whole design (D-163). `opening_line` is PREPENDED — hard rule 5 wants whatever
        the tenant volunteers spoken first — and `TRUTHFUL_ANSWER_DIRECTIVE` is APPENDED,
        because it must beat the script rather than be beaten by it. The directive is a
        `Final` in the portability contract with no writer anywhere, so no script, prompt
        version or column can withdraw it; `agents/verification.judge` scores it on the
        read-back, so an engine that truncated it away refuses the publish instead of
        going live quietly.

        The speech guards below never fire for THIS engine — Bolna is BYOK on all three
        legs — and they are here anyway, in the one place both `create_agent` and
        `update_agent` pass through. What they buy is that the descriptor is the
        AUTHORITY rather than a description: narrowing `BOLNA_CAPABILITIES` (a vendor
        withdrawing a BYOK leg is exactly the kind of thing that gets announced in a
        changelog) changes what this adapter accepts, instead of leaving a field that
        says one thing and a request body that does another.
        """
        require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
        require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
        require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)
        prompt = compose_engine_prompt(cfg)
        return {
            "agent_config": {
                "agent_name": cfg.name,
                "agent_type": "other",
                # Empty when the tenant volunteers neither notice: the vendor then has no
                # welcome message to play and the agent opens on its script. Sent as ""
                # rather than omitted, so a toggle switched OFF actually CLEARS a greeting
                # the vendor is already holding — an omitted key is a field left as it was.
                "agent_welcome_message": cfg.opening_line,
                "webhook_url": cfg.webhook_url,
                "tasks": [
                    {
                        "task_type": "conversation",
                        "tools_config": {
                            "llm_agent": {
                                "agent_flow_type": "streaming",
                                "family": "openai",
                                "model": cfg.models.llm_model,
                            },
                            "synthesizer": {
                                "provider": cfg.models.tts_provider,
                                "provider_config": {"voice": cfg.models.tts_voice},
                                "stream": True,
                            },
                            "transcriber": {
                                "provider": cfg.models.stt_provider,
                                "model": cfg.models.stt_model,
                                "language": cfg.language_primary,
                                "stream": True,
                            },
                        },
                        "task_config": {
                            "hangup_after_silence": 10,
                            "call_terminate": cfg.max_call_duration_s,
                        },
                    }
                ],
            },
            "agent_prompts": {"task_1": {"system_prompt": prompt}},
        }

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        # /v2/agent — legacy unversioned agent paths are deprecated, never call them.
        data = await self._request("POST", "/v2/agent", json=self._agent_body(cfg))
        ref = data.get("agent_id") or data.get("id")
        if not isinstance(ref, str):
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return an agent id.",
            )
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await self._request("PUT", f"/v2/agent/{ref}", json=self._agent_body(cfg))

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """`DELETE /v2/agent/{agent_id}` — the orphan compensator's one instrument.

        **THE PATH AND THE VERB ARE DOCUMENTED, and this is a stronger footing than the
        rest of this adapter's agent lifecycle stands on.** Bolna's API reference publishes
        the route as `DELETE https://api.bolna.ai/v2/agent/{agent_id}` with a
        `Authorization: Bearer` header, `agent_id` as a required path parameter, a 200
        answering `{"message": "success", "state": "deleted"}`, and 400 as the only other
        documented status. The OSS server's own `API.md` documents the same route shape
        (`DELETE /agent/{agent_id}` → `{"agent_id": ..., "state": "deleted"}`).
        Retrieved 2026-08-15 via search summary of https://docs.bolna.ai/api-reference/agent/v2/delete
        and read at source at https://github.com/bolna-ai/bolna/blob/master/API.md —
        the hosted docs host itself is refused by this environment's egress proxy, so the
        first is REPORTED, NOT READ and the second is READ AT SOURCE for the OSS server.

        **THE RESPONSE BODY IS NOT PARSED, deliberately.** `{"state": "deleted"}` is the
        only signal the vendor offers and it is a string we would be checking against our
        own guess about its spelling; the 2xx plus the conformance clause's re-read is
        what makes the delete mean something. Nothing here maps a vendor field.

        **MARKED ASSUMPTION — what is assumed and what falsifies it.**
        ASSUMED: deleting an `agent_id` this account does not hold (already deleted, or
        never existed) answers **404**, which `absent_is_success` converts into the
        Protocol's idempotent success. Nothing published says so: the reference documents
        200 and 400 and says nothing at all about a repeat.
        FALSIFIED BY: a repeat delete answering **400** — in which case this method raises
        `engine_rejected` on a compensation whose work is already done, and the retry
        ladder DLQs a job that has nothing left to do.
        NOT ASSUMED THE OTHER WAY: a 400 is left as a failure rather than also folded into
        success, because a 400 is what a malformed request looks like too, and an adapter
        that reported "deleted" for a request the vendor rejected would be the exact class
        of silent lie `detach_kb` refuses to be. If the pilot returns 400 for a repeat, the
        fix is a narrow branch here on the vendor's actual body — not a wider status range.
        MEASURED BY: OPERATIONS §2 gate 2's `delete_agent` sub-check, which creates a
        throwaway agent, deletes it, re-reads it, and deletes it a SECOND time, recording
        the status of the repeat. That is the whole question, and it needs an account.

        **WHAT IT DESTROYS.** Their reference states this removes all of the agent's data
        including its batches and executions. That is why the only caller in this repo is
        the orphan compensator (`agents/service.py`), whose subject is an agent minted
        seconds ago that has never taken a call — and why a human soft-deleting an agent
        does NOT reach here: their call history is a retention obligation of ours
        (SECURITY-COMPLIANCE §4), not a console-click side effect.
        """
        await self._request("DELETE", f"/v2/agent/{ref}", absent_is_success=True)

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """`GET /v2/agent/{agent_id}` → our `AgentSnapshot`.

        **UNVERIFIED AGAINST A LIVE ACCOUNT — the same standing as `create_agent` and
        `update_agent` above, and marked here so nobody reads it as a measurement.**
        Evidence actually gathered (2026-08-14), and its exact weight:

        * READ AT THE SOURCE. `bolna-ai/bolna` (their OSS server) documents
          `GET /agent/{agent_id}` in `API.md` and implements it in
          `local_setup/quickstart_server.py` — it returns the STORED AGENT OBJECT as JSON
          (the same `{agent_config, agent_prompts}` pair that was POSTed) and 404s an
          unknown id. `GET /all` returns rows shaped `{"agent_id": ..., "data": {...}}`,
          which is why the unwrapping below tolerates a `data`/`agent` envelope. This is
          the self-hosted server, NOT api.bolna.ai — it is strong evidence about the
          SHAPE and no evidence at all about the hosted path.
        * NOT READ, ONLY REPORTED. A web search of their hosted API reference (the v2
          agent overview) lists `GET /v2/agent/{agent_id}` beside the `POST /v2/agent`,
          `PUT /v2/agent/:agent_id` and `GET /v2/agent/all` this adapter already calls.
          The page ITSELF could not be fetched: `docs.bolna.ai` and `www.bolna.ai` are
          both blocked by this environment's egress proxy, so the path below is a claim
          from a search summary, not something a human here has read. Bolna publishes no
          OpenAPI spec (module docstring), so there is no schema to fall back on.
        * NOT FOUND AT ALL — the loudest gap. **Nothing found anywhere says where a
          knowledge base reference lives inside the agent object**, or whether the agent
          object carries one. `_AGENT_KB_REF_KEYS` is therefore a guessed set of field
          names, and `knowledge_base_refs_readable` is False whenever none of them is
          present — which is why a "no dangling `rag_id`" verdict can never be inferred
          from silence here. That is precisely D-41's open question and it stays a PILOT
          GATE (OPERATIONS §2 gate 8), not a premise.

        * THE GREETING has the same standing as the prompt and no better:
          `agent_welcome_message` is the key we SEND (their OSS agent object carries it),
          and whether the hosted GET echoes it under that name is inferred from the same
          "it returns the stored agent object" claim. `greeting_readable=False` when the
          key is absent, which the judge scores `unreadable` — never as a missing
          disclosure, because an adapter looking in the wrong place must not be able to
          fail a publish on a compliance ground (P3.3).

        If the path is wrong, `_request` raises `engine_rejected` on the 404 and the gate
        reports a failed read-back — loud, and the correct outcome for an unverified
        endpoint. It never degrades to a green tick.
        """
        payload = await self._request("GET", f"/v2/agent/{ref}")
        agent = _agent_object(payload)
        prompt = _agent_system_prompt(agent)
        greeting, greeting_readable = _agent_greeting(agent)
        kb_refs, kb_readable = _agent_kb_refs(agent)
        models, models_readable = _agent_models(agent)
        returned_id = agent.get("agent_id") or agent.get("id") or payload.get("agent_id")
        return AgentSnapshot(
            # Their id when they state one, so a vendor answering about a DIFFERENT agent
            # is visible to the caller rather than papered over with the ref we asked for.
            engine_agent_ref=returned_id if isinstance(returned_id, str) and returned_id else ref,
            name=_agent_name(agent),
            system_prompt=prompt,
            system_prompt_readable=prompt is not None,
            greeting=greeting,
            greeting_readable=greeting_readable,
            knowledge_base_refs=kb_refs,
            knowledge_base_refs_readable=kb_readable,
            models=models,
            models_readable=models_readable,
            engine="bolna",
        )

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        # `user_data` dynamic variables are rendered into the prompt — our CallContext
        # mechanism for lead callbacks (D-21).
        user_data = {k: v for k, v in ctx.fields.items() if v}
        if ctx.lead_name:
            user_data["lead_name"] = ctx.lead_name
        if ctx.context_note:
            user_data["context_note"] = ctx.context_note
        if ctx.prior_call_summary:
            user_data["prior_call_summary"] = ctx.prior_call_summary
        data = await self._request(
            "POST",
            "/call",
            json={"agent_id": ref, "recipient_phone_number": to, "user_data": user_data},
        )
        handle = data.get("execution_id") or data.get("id")
        if not isinstance(handle, str):
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a call id.",
            )
        return handle

    async def end_call(self, call_id: str) -> None:
        await self._request("POST", f"/executions/{call_id}/stop")

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        # UNVERIFIED on Bolna (pilot item), which `BOLNA_CAPABILITIES.transfer=False`
        # already declares. Failing loudly beats pretending a transfer happened — and it
        # now fails with the SAME code a caller could have asked the descriptor for
        # BEFORE calling, so a screen and this method cannot disagree.
        require_capability("transfer", engine=self)

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        # Numbers come from the telephony vendor directly (D-05), which is the seam in
        # `campaigns/provisioning.py`. `BOLNA_CAPABILITIES.number_series` is empty, so
        # this refuses every series rather than only the DLT ones.
        require_capability("numbers", engine=self)
        # Unreachable while `number_series` is empty. Kept as a real refusal rather than
        # an `assert`, because the way this line gets reached is somebody widening the
        # descriptor without writing the client — and that must fail loudly here rather
        # than fall off the end of the function returning None.
        raise ProblemError(
            kind="dependency",
            code="engine_capability_unverified",
            title="Number provisioning is not automated yet",
            detail="Numbers are provisioned with the telephony provider directly (M1).",
        )

    # --- knowledge base ------------------------------------------------------
    #
    # Their surface, and how far each part of it is actually verified (TRD §5 records
    # it as "rag_id CRUD API (POST/GET/DELETE /knowledgebase)", and their published API
    # reference indexes POST /knowledgebase, GET /knowledgebase/all,
    # GET /knowledgebase/{rag_id}, DELETE /knowledgebase/{rag_id}):
    #
    # * VERIFIED from published docs — the ROUTES and the fact that a knowledge base is
    #   addressed by the vendor's own `rag_id`. Note what that rules out: our
    #   `kb_sources.id` is not a key on their side, so `DELETE /knowledgebase/<our uuid>`
    #   would 404 forever while looking like a working detach. The id we delete by must
    #   be the one POST handed back, which is why `attach_kb` now returns it.
    # * UNVERIFIED until the pilot — every BODY on this path. Bolna publishes no OpenAPI
    #   spec, so the create payload here, the `rag_id` field name in its response, and
    #   the row shape of the list are hand-maintained claims (the module docstring's
    #   standing warning). Two specifically to settle at gate 8:
    #     (a) does the list response carry the agent linkage this filters on? Our account
    #         holds every tenant's agents, so `list_kb` filters STRICTLY — a row that
    #         does not name this agent is not attributed to it.
    #     (b) does deleting the knowledge base also drop the agent's reference to it, or
    #         does the agent config keep a dangling `rag_id`? If the latter, detach grows
    #         a second call (an agent update) — it does NOT become optional.

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        """Built-in KB (`rag_id`). Under BYOK the KB is NOT a model slot (D-33): this
        is a document push, and multilingual mode is IMMUTABLE at KB creation — Telugu
        retrieval quality is pilot gate 8.

        The returned handle is the ONLY way this document can ever be removed again, so
        a response we cannot read a handle out of is a failure, not a success: treating
        it as one would attach text nobody can retract.
        """
        require_capability("knowledge_base", engine=self)
        data = await self._request(
            "POST",
            "/knowledgebase",
            json={"agent_id": ref, "name": source.title, "text": source.text},
        )
        rag_id = data.get("rag_id") or data.get("id")
        if not isinstance(rag_id, str) or not rag_id:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a knowledge base id.",
            )
        return rag_id

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        """`DELETE /knowledgebase/{rag_id}`.

        No swallowing of the vendor's 404: an id we cannot delete is an id we cannot
        prove is gone, and the caller's next act is to publish a replacement.
        """
        require_capability("knowledge_base", engine=self)
        await self._request("DELETE", f"/knowledgebase/{kb}")

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        require_capability("knowledge_base", engine=self)
        data = await self._request("GET", "/knowledgebase/all")
        rows = data.get("data")
        if not isinstance(rows, list):
            rows = data.get("knowledgebases")
        if not isinstance(rows, list):
            return []
        handles: list[EngineKBRef] = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("agent_id") or "") != ref:
                continue
            rag_id = row.get("rag_id") or row.get("id")
            if isinstance(rag_id, str) and rag_id:
                handles.append(rag_id)
        return handles

    # --- reading the truth ---------------------------------------------------

    def _snapshot(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(payload.get("status") or "").lower()
        status = _STATUS_MAP.get(raw_status, "failed")
        call_id = str(payload.get("id") or payload.get("execution_id") or "")
        cost = self._cost(payload)
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
        started = _parse_dt(payload.get("created_at") or payload.get("started_at"))
        ended = _parse_dt(payload.get("ended_at") or payload.get("updated_at"))
        duration = payload.get("conversation_duration") or payload.get("duration")
        telephony = payload.get("telephony_data") or {}
        agent_ref = payload.get("agent_id")
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=str(agent_ref) if agent_ref else None,
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=status,
            raw_status=raw_status,
            terminal=raw_status in _TERMINAL_RAW,
            # The distinction that matters: terminal means "no more audio";
            # billable_ready means "cost, recording and transcript are populated".
            billable_ready=raw_status == "completed",
            started_at=started,
            ended_at=ended,
            duration_s=int(duration) if isinstance(duration, int | float) else None,
            from_e164=telephony.get("from_number") or payload.get("from_number"),
            to_e164=telephony.get("to_number") or payload.get("to_number"),
            recording_url=telephony.get("recording_url") or payload.get("recording_url"),
            transcript=turns,
            transcript_lines_unparsed=unparsed,
            cost=cost,
            # Their `completed` timestamp where they give one, else the instant we
            # OBSERVED it — which is what the poller's tick resolution actually buys and
            # is honest about being a ceiling. Absent until the execution is billable,
            # so it never reads as "ready at" for a call that is not.
            billable_ready_at=(
                _parse_dt(payload.get("completed_at")) or datetime.now(UTC)
                if raw_status == "completed"
                else None
            ),
            engine_extracted=payload.get("extracted_data") or {},
            engine="bolna",
        )

    def _cost(self, payload: dict[str, Any]) -> CostBreakdown | None:
        """USD cents -> INR, and an honest account of whether "USD cents" is a FACT.

        Bolna publishes no OpenAPI spec, so "costs arrive in USD cents" is a claim read
        off their docs, not a guarantee — and it is worth 83x. This used to write
        `source_currency="USD"` as a literal, which made the assumption unfalsifiable
        from inside: pilot gate 7's currency criterion read our own guess back and
        agreed with it (OPERATIONS §2). Three behaviours now, in order:

        * the payload NAMES a currency we can convert -> use it, `currency_stated=True`,
          and the gate has a fact to score;
        * the payload names a currency we have no rate for -> refuse. Returning a number
          converted at the USD rate would be a fabricated cost basis flowing into the
          margin panel and every invoice. An absent cost is a visible gap; a wrong one
          is not;
        * the payload names nothing -> convert on the house assumption, exactly as
          before, but stamp `currency_stated=False` so the row says which it is.

        The refusal logs at WARNING with the currency and the execution id — ids only,
        never the payload (hard rule 6).
        """
        total = payload.get("total_cost")
        if total is None:
            # SILENT UNTIL P1.2. `total_cost` is a HAND-MAINTAINED CLAIM about a vendor
            # that publishes no OpenAPI spec (TRD §5, pilot gate 7), so "the key is not
            # there" and "the key is spelled differently on the live account" are the same
            # observation from here — and the second one means every completed call meters
            # nothing, every usage panel reads ₹0.00, no cap ever arms and no wallet is
            # ever debited. Refusing to fabricate a cost is right; refusing to COUNT the
            # refusals is what made it undetectable. The pipeline turns this into an alert
            # (`_meter`); this line makes it visible in the adapter's own logs, where the
            # execution id is the thing an operator can look up. Ids only, never the
            # payload (hard rule 6).
            log.warning(
                "engine_cost_absent",
                extra={"engine": "bolna", "execution_id": str(payload.get("id") or "")},
            )
            return None

        stated = payload.get("currency") or payload.get("cost_currency")
        currency = str(stated).strip().upper() if stated else _ASSUMED_CURRENCY
        if currency not in _CONVERTIBLE_CURRENCIES:
            log.warning(
                "engine_cost_currency_unsupported",
                extra={
                    "engine": "bolna",
                    "currency": currency,
                    "engine_call_id": str(payload.get("id") or payload.get("execution_id") or ""),
                },
            )
            return None

        # INR needs no conversion, and multiplying it by the USD rate is precisely the
        # 83x error this branch exists to prevent.
        rate = Decimal(1) if currency == "INR" else self._fx_rate
        breakdown = payload.get("cost_breakdown") or {}
        total_inr = _to_inr(total, rate)
        if total_inr is None:
            return None
        return CostBreakdown(
            total_inr=total_inr,
            platform_inr=_to_inr(breakdown.get("platform"), rate),
            network_inr=_to_inr(breakdown.get("network"), rate),
            llm_inr=_to_inr(breakdown.get("llm"), rate),
            tts_inr=_to_inr(breakdown.get("synthesizer"), rate),
            stt_inr=_to_inr(breakdown.get("transcriber"), rate),
            source_currency=currency,
            currency_stated=stated is not None,
            source_amount=Decimal(str(total)) / Decimal(100),
            fx_rate=rate,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """Their execution, normalized — plus their own document, sealed as bytes.

        The document rides on `get_execution` and NOT on `_snapshot`, so `list_executions`
        does not build one per row: a twenty-page poll would serialize two thousand
        documents that nothing archives. This is the one path the archive runs on.
        """
        payload = await self._request("GET", f"/executions/{call_id}")
        return self._snapshot(payload).model_copy(
            update={"raw_document": engine_document(payload, engine=self.name)}
        )

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """The guarantee of record (D-31) — and an honest account of what it covered.

        See `_LISTING_PAGE_SIZES` for why completeness is inferred rather than known,
        and `_next_link` for the one continuation form this will follow.

        Three ways the LISTING can end, in order of how much we know:

        * a continuation link ran out -> `complete=True`, `pages_fetched` says how many;
        * the payload said there is more and named no link we can GET -> `explicit_more`;
        * no metadata at all and the row count looks like a page size ->
          `full_page_suspected`.

        And four ways the WALK itself can stop, kept apart because each sends an
        operator somewhere different (they were once one label, `next_link_loop`, which
        described only the first of them):

        * the continuation repeats a URL we already fetched -> `next_link_loop`;
        * a new continuation returns only executions we already had ->
          `next_link_no_progress`;
        * the page carried no executions at all and still offered a continuation ->
          `empty_page_with_next` (`pages_fetched == 1` = the first page was empty);
        * our own page bound stopped a walk that was still producing -> `page_cap_reached`.

        Rows are de-duplicated by execution id across pages: a vendor whose window
        shifts under us (executions keep arriving while we page) can legitimately repeat
        one, and re-driving the same execution twice is wasted engine load.
        """
        listing = await self._request(
            "GET", "/executions", params={"created_after": since.isoformat()}
        )
        snapshots: list[ExecutionSnapshot] = []
        seen_ids: set[str] = set()
        seen_links: set[str] = set()
        pages = 0
        reason: ListingIncompleteReason | None = None

        while True:
            pages += 1
            rows = _listing_rows(listing)
            new_rows = 0
            for row in rows:
                snapshot = self._snapshot(row)
                if snapshot.engine_call_id in seen_ids:
                    continue
                seen_ids.add(snapshot.engine_call_id)
                snapshots.append(snapshot)
                new_rows += 1

            link = self._next_link(listing)
            if link is None:
                # No link. Either the payload claims more (and we cannot fetch it), or
                # the count itself is the only evidence we will ever get.
                if _claims_more(listing, len(rows)):
                    reason = "explicit_more"
                elif len(rows) in _LISTING_PAGE_SIZES:
                    reason = "full_page_suspected"
                break
            if link in seen_links:
                # The continuation points back at a page we already fetched: walking on
                # re-reads it forever, the one failure mode where "follow the link"
                # becomes an outage against the vendor.
                reason = "next_link_loop"
                break
            if not rows:
                # No rows AND a continuation. This used to be reported as a loop, which
                # sent an operator hunting a pagination bug that is not there: nothing
                # repeated, the page was simply empty — most often the FIRST page of an
                # empty window, which `pages_fetched == 1` says outright.
                # We still stop. Following a continuation that produced nothing is a
                # guess that burns the page cap on empty responses; stopping with a
                # reason the operator can act on is the honest end (rejected
                # alternative: keep walking until the cap, which turns one quiet tick
                # into twenty requests and reports `page_cap_reached` — a WORSE label,
                # since it implies we found rows all the way to our bound).
                reason = "empty_page_with_next"
                break
            if new_rows == 0:
                # Rows came back, but every one was an execution we already had, under a
                # link we had not seen. Distinct from a loop (the URLs differ) and from
                # an empty page (rows exist): the vendor is re-serving content, so the
                # walk has stopped covering new window.
                reason = "next_link_no_progress"
                break
            if pages >= _LISTING_MAX_PAGES:
                reason = "page_cap_reached"
                break
            seen_links.add(link)
            listing = await self._request("GET", link)

        if reason is not None:
            # ids and counts only (hard rule 6) — and the reason is our word, not theirs.
            log.warning(
                "engine_listing_incomplete",
                extra={
                    "engine": "bolna",
                    "reason": reason,
                    "pages_fetched": pages,
                    "executions": len(snapshots),
                },
            )
        return ExecutionListing(
            snapshots=snapshots,
            complete=reason is None,
            incomplete_reason=reason,
            pages_fetched=pages,
        )

    def _next_link(self, payload: dict[str, Any]) -> str | None:
        """The ONE continuation form this adapter follows: a link it can GET as given.

        WHY NOT A CURSOR PARAMETER. Bolna publishes no OpenAPI spec, so `?page=`,
        `?offset=`, `?cursor=` are all guesses. A guessed parameter is ignored by the
        vendor, which yields the same page forever (an infinite loop, or with our cap, a
        listing that claims to have paged and did not) — the original defect wearing a
        fix. A link the payload itself hands us is self-describing: we invent no name and
        assume no encoding, and if the key is absent we simply do not page.

        SAME-ORIGIN ONLY. A `next` is vendor-controlled input that this code would turn
        into an outbound request carrying our `Authorization` header, which is the
        textbook SSRF/credential-leak shape (OWASP SSRF cheat sheet: validate the
        destination against an allowlist, never the input against a denylist). So a
        relative path is used as-is, an absolute URL is accepted only when its scheme is
        https and its host matches the configured API host, and anything else is dropped
        — dropping degrades to `explicit_more`, which is loud, rather than to a request
        at an attacker's host.
        """
        for key in ("next", "next_page_url", "next_url", "links"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("next")
            if not isinstance(value, str) or not value.strip():
                continue
            candidate = value.strip()
            if candidate.startswith("/"):
                return candidate
            try:
                parsed = httpx.URL(candidate)
            except httpx.InvalidURL:
                # A VENDOR-SUPPLIED STRING THAT IS NOT A URL AT ALL (P2.3), and the
                # docstring three lines above already promised this outcome: "anything
                # else is dropped — dropping degrades to `explicit_more`, which is loud".
                # It was not true, because `httpx.URL()` raises before any of the checks
                # below run.
                #
                # MEASURED, not assumed: `httpx.InvalidURL`'s MRO does NOT include
                # `httpx.HTTPError`, so `_request`'s handler would not have caught it even
                # if this call were inside one — and it is not. A zero-width space in a
                # host (`http://a​.com`) is enough to raise.
                #
                # `list_executions`' only caller is `reconcile_executions`, which under
                # D-31 IS the guarantee of record. An exception there retries three times
                # and DLQs, and every execution whose webhook was lost stops being
                # recoverable until somebody reads a dead-letter queue. Dropping the link
                # costs one page and reports `explicit_more`, which is exactly what the
                # poller is built to see.
                log.warning(
                    "engine_listing_next_link_rejected",
                    extra={"engine": "bolna", "reason": "unparseable"},
                )
                continue
            if parsed.scheme == "https" and parsed.host == httpx.URL(self._base_url).host:
                return candidate
            log.warning(
                "engine_listing_next_link_rejected",
                extra={"engine": "bolna", "reason": "off_origin"},
            )
        return None

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """No signature exists to check (D-31). The source IP is the only control, and
        it is deliberately reported as `source_ip` rather than dressed up as proof —
        the caller must keep treating the payload as a hint.

        THE ALLOWLIST IS CONFIGURATION, NOT A CONSTANT HERE. This used to match a module
        constant while the receiver that actually answers deliveries
        (`apps/voice-runtime/engine_intake.verify_source`) matched
        `BOLNA_WEBHOOK_SOURCE_IPS`; the two agreed only while the setting held its
        default, so the first operator to follow the documented recovery path — the
        vendor renumbers, rotate the variable, restart, no deploy — made this verdict
        disagree with the door it describes, silently and in the trust direction.

        Why settings won rather than this constant. The vendor's egress ADDRESS is not a
        vendor payload shape: hard rule 2 puts SDKs and wire formats behind this
        boundary, and an IPv4 literal has no schema to leak — it is a deployment fact
        about which peers may reach us, of a kind with `webhook_base_url`. And the
        enforcing half physically cannot live here: the receiver is forbidden from
        importing `apps.api.engine` at all (hard rule 3, proved by
        `tests/voice_runtime_import_surface_test.py`), so a constant in this module could
        never have been the thing the network is judged against. Settings is the only
        place both halves can read, and the only place an incident can change without a
        deploy of the latency-critical service.
        """
        if source_ip in bolna_source_ips(get_settings()):
            return WebhookVerdict(ok=True, method="source_ip")
        return WebhookVerdict(
            ok=False, method="source_ip", reason="source ip not in the engine allowlist"
        )

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Webhooks and Get Execution share one shape, so this reuses the snapshot
        parser and drops to the event fields."""
        snapshot = self._snapshot(payload)
        agent_ref = payload.get("agent_id")
        # Their payload marks inbound explicitly; everything else on this platform is a
        # call WE placed. Defaulting to outbound is the compliance-safe direction —
        # outbound is the side that carries DNC/calling-hours obligations, so a
        # misclassified call is over-regulated rather than under-regulated.
        direction = "inbound" if payload.get("direction") == "inbound" else "outbound"
        return CallEvent(
            call_id=snapshot.engine_call_id,
            engine_agent_ref=str(agent_ref) if agent_ref else None,
            direction=direction,
            status=snapshot.status,
            raw_status=snapshot.raw_status,
            started_at=snapshot.started_at,
            ended_at=snapshot.ended_at,
            from_e164=snapshot.from_e164,
            to_e164=snapshot.to_e164,
            recording_url=snapshot.recording_url,
            cost_raw=str(payload.get("total_cost")) if payload.get("total_cost") else None,
            engine="bolna",
        )


__all__ = [
    "BASE_URL",
    "THROTTLE_MAX_ATTEMPTS",
    "THROTTLE_MAX_SLEEP_S",
    "THROTTLE_STATUS",
    "BolnaEngine",
    "parse_transcript",
    "throttle_delay_s",
]
