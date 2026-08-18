"""Bolna adapter — the ONLY place in the codebase that knows Bolna's payload shapes.

Adopted by D-31 (supersedes D-02's ThinnestAI pick), gated on the pilot scorecard.

**BOLNA PUBLISHES AN OPENAPI SPEC, AND THIS FILE SPENT ITS WHOLE LIFE SAYING THEY DO NOT
(D-350).** That sentence — "Bolna publishes no OpenAPI spec" — was the premise under the
pagination heuristic, the guessed KB body, the hand-maintained status list and half the
"STILL UNVERIFIED" marks in this file, and it was false. The spec is
`references/openapi.yml` in **`bolna-ai/skills`**, Bolna's own GitHub organisation,
described there as a "mirror of https://www.bolna.ai/docs/api-reference/openapi.yml" with
the instruction: *"Treat the YAML as the canonical schema if a SKILL.md and the spec
disagree."* It is reachable from this environment (github.com is not on the egress
proxy's deny list; `docs.bolna.ai`, `www.bolna.ai` and `api.bolna.ai` are). Pin,
checksum and how to re-fetch it: `docs/vendor/bolna/hosted-oas.md`.

Three properties of this vendor shape the whole design and are load-bearing:

1. **Webhooks are unsigned**, so authenticity = source-IP allowlist (a SINGLE documented
   address, `13.203.39.153`) + `(execution_id, status)` dedupe, payloads are HINTS, and
   the executions poller is the guarantee of record. **They are NOT at-most-once, which
   is what this docstring claimed (D-352)**: the hosted platform "retries on non-2xx"
   and fires one delivery per status transition, so the receiver must ack 2xx and dedupe
   on the PAIR — never on the execution id alone, or the `completed` transition is
   discarded as a duplicate of `queued`. The at-most-once reading came from the OSS
   framework's `aiohttp` one-shot delivery, which is a different program from the hosted
   deliverer. VERIFIED-VENDOR-REPO: `references/execution-payload.md` §"Webhook delivery"
   and `setup-webhook/SKILL.md` §"Idempotency".
2. **cost / recording_url / extracted_data populate only at `completed`**, roughly
   2-3 min after disconnect. The post-call pipeline therefore triggers on `completed`,
   never on a disconnect event — `billable_ready` encodes exactly that. VERIFIED-VENDOR-
   REPO: `references/call-statuses.md` — "`completed` is the terminal status ... after
   recordings, transcripts, and extractions have finished post-processing".
3. **Costs arrive with a five-key per-leg breakdown** (`llm`, `network`, `platform`,
   `synthesizer`, `transcriber`) — VERIFIED-OAS, `CostBreakdown`. **The UNIT is where the
   vendor contradicts itself and the money path lives, so it is still a marked assumption
   (hard rule 7).** The OAS says "in cents" on `total_cost` and on all five members;
   `references/execution-payload.md`, the same repo at the same commit, says `total_cost`
   is "Bolna cost in account currency" — major units. The vendor's own precedence rule
   ("treat the YAML as canonical", `references/bolna-core.md`) breaks the tie toward
   cents, which is what `_ASSUMED_MINOR_UNITS_PER_MAJOR` already encoded, so nothing
   changes — but a precedence rule is not an observation, and read that constant before
   touching anything here. The adapter converts to INR at capture and stamps the fx rate,
   so a ledger row can always be re-derived. WHICH currency is stated nowhere at all
   (OPERATIONS §2 gate 7, which now scores unit and currency both).

Where the evidence for each claim came from, and how much it is worth, is recorded once
in `docs/vendor/bolna/` rather than re-argued here. FOUR classes are used throughout this
file and they are not interchangeable:

* **VERIFIED-OAS** — read in the vendor's own pinned OpenAPI document. The strongest
  class available without an account: it is first-party, versioned and machine-checkable,
  and it describes the HOSTED contract rather than the self-hosted framework.
* **VERIFIED-VENDOR-REPO** — read in a prose file of `bolna-ai/skills` (the SKILL.md set
  and `references/`). First-party and current, but prose: where it and the OAS disagree
  the repo's own README says the OAS wins.
* **VERIFIED-OSS** — read in `bolna-ai/bolna`, the self-hosted framework. Authoritative
  for how the ENGINE behaves, and — as property 1 above shows — actively misleading about
  the hosted REST contract. Ranks BELOW the two above, never above them.
* **STILL UNVERIFIED** — needs a live account; each one is a named gate in OPERATIONS §2.
  `REPORTED-DOCS` (a WebSearch summary) is retired as a class: everything it used to
  carry is now readable first-hand in the two repos above.

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
from apps.api.engine.capabilities import (
    NO_CREDENTIALS_REASON,
    engine_not_configured,
    require_call_compliance_floor,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.document import engine_document
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

log = get_logger(__name__)

BASE_URL = "https://api.bolna.ai"
# --- Throttle handling (SURFACES §3.3) ---------------------------------------
# Bolna's rate limits ARE published, and this said they were not (D-350).
# VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa references/bolna-core.md` §"Rate limits",
# per organization (or per user when you belong to none):
#     GET /v2/agent/{agent_id}              500/min
#     GET /v2/agent/{agent_id}/executions   500/min
#     POST /call                            500/min
#     everything else                      1000/min
# Nothing here changes as a result, and that is worth saying rather than leaving as an
# omission: the ladder below is not a budget we could spend down to, it is what to do when
# a limit we do not track is hit, and 500/min is far above anything one process generates.
# What the numbers DO settle is that the reconciliation poller's fan-out — one listing
# request per agent per tick, see `list_executions` — is nowhere near a ceiling. Three
# deliberate limits on what we do about a 429:
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


# Their status values → our 8. Anything unmapped becomes `failed`, which is the safe
# direction: a call we cannot classify must not look successful.
#
# **THE LIST IS NO LONGER HAND-MAINTAINED — IT IS THE VENDOR'S ENUM, AND ONE MEMBER WAS
# MISSING (D-351).** This comment used to say nobody had read a status enum, which was
# true of the OSS framework (its enums are `HangupReason`, `LogComponent`, provider lists
# — `bolna/enums.py`, bolna-ai/bolna@cd2e192) and false of the hosted platform. VERIFIED-
# OAS: `AgentExecution.status` in the pinned spec enumerates exactly fifteen values, and
# the same fifteen appear as the `status` query filter on
# `GET /v2/agent/{agent_id}/executions`:
#
#     scheduled  queued  rescheduled  initiated  ringing  in-progress  call-disconnected
#     completed  balance-low  busy  no-answer  canceled  failed  stopped  error
#
# `_VENDOR_STATUSES` below is that enum, and `tests/bolna_snapshot_test.py` asserts every
# member of it is mapped — so a status the vendor adds cannot quietly become `failed`.
#
# **`rescheduled` WAS THE MISSING ONE AND IT MATTERED.** Bolna auto-reschedules a call
# placed outside an agent's `calling_guardrails` window to the next allowed window
# (`references/call-statuses.md`: "Outside calling guardrails — auto-rescheduled to the
# next allowed window"), which is the NORMAL outcome for an Indian outbound campaign that
# hits the 9am boundary. Unmapped, it fell through to the `failed` default: a call that is
# alive and waiting read as a dead one on the client's screen, and the campaign's failure
# rate counted a success as a loss. It maps to `queued` for the same reason `scheduled`
# does — the vendor is holding it and will dial it.
#
# `call-connected`, `cancelled` and `voicemail` are NOT in the vendor's enum. The first two
# are tolerated spellings and cost nothing. `voicemail` is different and is now ANSWERED
# rather than assumed (D-260 asked; VERIFIED-OAS says): there is no `voicemail` status, so
# that key is dead and `CallStatus.voicemail` is unreachable from this engine. Voicemail is
# reported as the boolean `answered_by_voice_mail` on an execution whose status is plain
# `completed`. The key stays mapped — removing it would change nothing except to make a
# hypothetical future spelling read as `failed` — and the FACT is recorded here so nobody
# re-derives it. Surfacing `answered_by_voice_mail` as a status is a product decision about
# what a client's screen says, not an adapter fix: OPERATIONS §2 gate 17 keeps it.
#: The vendor's own `status` enum, verbatim from the pinned OAS. Not iterated at runtime —
#: it exists so a test can prove `_STATUS_MAP` covers it.
_VENDOR_STATUSES: frozenset[str] = frozenset(
    {
        "scheduled",
        "queued",
        "rescheduled",
        "initiated",
        "ringing",
        "in-progress",
        "call-disconnected",
        "completed",
        "balance-low",
        "busy",
        "no-answer",
        "canceled",
        "failed",
        "stopped",
        "error",
    }
)

_STATUS_MAP: dict[str, CallStatus] = {
    "scheduled": "queued",
    "queued": "queued",
    "rescheduled": "queued",
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
#
# VERIFIED-OSS: `format_messages` in `bolna/helpers/utils.py` (bolna-ai/bolna@cd2e192) is
# the function that builds this string, and it emits exactly `"assistant: "`, `"user: "`,
# `"system: "`, `"assistant_tool_call: "` and `"tool_response: (<id>): "`, one per line.
# `agent`/`bot`/`human` below are not in that emitter — they are tolerated spellings, kept
# because tolerating one costs nothing and the hosted serializer is not this function.
_TURN_RE = re.compile(r"^\s*(assistant|agent|user|human|bot)\s*:\s*(.*)$", re.IGNORECASE)
_SPEAKER_MAP = {
    "assistant": "agent",
    "agent": "agent",
    "bot": "agent",
    "user": "caller",
    "human": "caller",
}

# Lines that ARE prefixed, by a role that is not a party to the conversation (D-260).
# From the same `format_messages` read: `system:` appears under `use_system_prompt`, and
# `assistant_tool_call:` / `tool_response:` under `include_tools`.
#
# WHY THIS SET HAS TO EXIST SEPARATELY. `_TURN_RE` does not match them — `assistant_tool_
# call` is not `assistant` followed by a colon — so before this they fell into the
# CONTINUATION branch below and were appended to the previous speaker's text. That is the
# worst of the three possible outcomes: a serialized tool call (`str(tool_call)`, i.e. the
# function name and its arguments) became part of what the transcript says the agent said,
# and the system prompt became part of whoever spoke last. Extraction reads that text, the
# console renders it, and nothing anywhere reported a problem.
#
# Counted as unparsed rather than dropped silently, for the reason the count exists at all:
# a transcript whose tool lines we discard is a transcript we did not fully read, and gate
# 7 scores that number.
_NON_DIALOGUE_PREFIX_RE = re.compile(
    r"^\s*(system|assistant_tool_call|tool_response)\b\s*[:(]", re.IGNORECASE
)

_PAISE = Decimal("0.0001")

# What the adapter treats a cost as when the payload does not say. Read off docs.bolna.ai
# and NOT confirmed against a live account — pilot gate 7 (OPERATIONS §2) is where it
# stops being an assumption. `CostBreakdown.currency_stated` carries the difference into
# every row, so a wrong guess is discoverable rather than baked in.
_ASSUMED_CURRENCY = "USD"
# Currencies this adapter can turn into INR. Anything else is refused rather than
# converted at the wrong rate — see `_cost`.
_CONVERTIBLE_CURRENCIES = frozenset({"USD", "INR"})

#: How many of the vendor's cost UNITS make one unit of `_ASSUMED_CURRENCY`. 100 = the
#: numbers are minor units (cents); 1 = they are major units (dollars).
#:
#: **STILL A MARKED ASSUMPTION (hard rule 7), BUT THE EVIDENCE NOW POINTS AT IT RATHER
#: THAN AWAY (D-350, supersedes the D-261 note that used to sit here).** VERIFIED-OAS,
#: `bolna-ai/skills@28b24aa references/openapi.yml`:
#:
#:   AgentExecution.total_cost   — "Total cost incurred by this execution **in cents**"
#:   AgentExecution.cost_breakdown — "Breakdown of the costs **in cents**"
#:   CostBreakdown.{llm,network,platform,synthesizer,transcriber} — "... **in cents**",
#:   with examples 4.2 / 1.2 / 2.0 / 6.8 / 0.7 (fractional cents, so the values are not
#:   integers and `_to_inr`'s `Decimal(str(...))` matters).
#:
#: That retires the OSS-framework reading the old note argued from
#: (`calculate_total_cost_of_llm_from_transcript` returning `round(dollars, 5)`, plus
#: published per-minute dollar pricing) — both were about a program that is not the hosted
#: biller. It does NOT retire the assumption itself, and saying it did would repeat the
#: exact mistake this file exists to prevent:
#:
#: **THE VENDOR CONTRADICTS ITSELF ON THIS FIELD, first-party against first-party.** The
#: same repo's `references/execution-payload.md` documents `total_cost` as "Bolna cost in
#: **account currency**" — a MAJOR-unit reading — while the OAS says "in cents". Both are
#: `bolna-ai/skills@28b24aa`. WHY THE CONSTANT STAYS 100 ANYWAY, and it is a rule the
#: vendor publishes rather than a preference of ours: `references/bolna-core.md` says
#: outright *"Treat the YAML as the canonical schema if a SKILL.md and the spec
#: disagree."* So the tiebreak is the vendor's own, it points at "cents", and it agrees
#: with the value that was already here. A reading that reconciles both — "minor units OF
#: the account currency" — is coherent and is probably the truth, but it is OUR synthesis
#: of two documents that disagree, not something either one says, so it is written here as
#: a hypothesis and not as a fact.
#:
#: STILL UNVERIFIED, and gate 7 now scores BOTH halves rather than one:
#:   (a) the UNIT — because a first-party document says major units and the only thing
#:       overriding it is a precedence rule, not an observation;
#:   (b) the CURRENCY — the OAS names none, and if the "account currency" reading is the
#:       true one then it is the ACCOUNT's, which for an Indian account may be INR and not
#:       `_ASSUMED_CURRENCY` at all. `CostBreakdown.currency_stated` carries the
#:       difference into every row so a later correction is re-derivable.
#: WHAT A WRONG VALUE COSTS: every `usage_event` under-values the call by 100x, so no
#: spend cap ever arms and every margin panel reads near zero — and the 83x currency error
#: sits on top of that, in the same direction.
_ASSUMED_MINOR_UNITS_PER_MAJOR = Decimal(100)


def _to_inr(amount: Any, fx_rate: Decimal) -> Decimal | None:
    """One vendor cost figure → INR, quantized to the ledger's NUMERIC(12,4).

    The vendor's figure is divided by `_ASSUMED_MINOR_UNITS_PER_MAJOR` first — read that
    constant before trusting the number this returns. Floats never touch money: the
    vendor value is stringified before it becomes a Decimal.
    """
    if amount is None:
        return None
    try:
        units = Decimal(str(amount))
    except (ArithmeticError, ValueError):
        return None
    major = units / _ASSUMED_MINOR_UNITS_PER_MAJOR
    return (major * fx_rate).quantize(_PAISE, rounding=ROUND_HALF_UP)


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


# --- Listing executions (D-31: this poller IS the guarantee of record) ----------------
#
# **THE ENDPOINT THIS USED TO CALL DOES NOT EXIST (D-353).** It issued
# `GET /executions?created_after=<iso>` — a global, time-filtered listing — and the pinned
# OAS has no `/executions` collection at all. Its execution routes are exactly two:
# `GET /executions/{execution_id}` and `GET /executions/{execution_id}/log`, both
# single-item. So the mechanism D-31 appointed the guarantee of record, the ONLY thing
# that recovers a call whose webhook was lost, would have returned 404 on its first live
# tick — and `vendor_request` turns that into a raised dependency error, which
# `reconcile_executions` catches and reports as `reconciliation_fetch_failed`. Ten minutes
# later, again. Every ten minutes, forever, with the console showing an engine fault
# rather than a wrong URL. Neither `created_after` nor any parameter like it exists either.
#
# WHAT THE VENDOR ACTUALLY OFFERS (VERIFIED-OAS, `bolna-ai/skills@28b24aa
# references/openapi.yml`, path `/v2/agent/{agent_id}/executions`): a PER-AGENT listing,
# "sorted by last run", with a real published pagination and filter contract —
#
#     page_number  integer, default 1, minimum 1
#     page_size    integer, default 20, minimum 1, "Maximum allowed is 50"
#     from         date-time, "created_at ... greater than or equal to this UTC datetime"
#     to           date-time, "created_at ... less than or equal to"
#     status / call_type / provider / batch_id / answered_by_voice_mail
#
# and the envelope `AgentExecutionV2List` = `{page_number, page_size, total, has_more,
# data[]}`. `references/bolna-core.md` adds the operating instruction: *"Loop until
# `has_more == false`. Don't try to compute pages from `total` — use the flag."*
#
# So the whole "we refuse to guess a pagination parameter, therefore we infer truncation
# from the row count landing on a conventional page size" apparatus is deleted, not
# repaired. It was the right call under a false premise and it is simply wrong under the
# true one: `_LISTING_PAGE_SIZES` would have reported `full_page_suspected` on every tick
# that happened to return 20 or 50 rows, which is what a healthy page of this endpoint
# looks like. `_next_link` is deleted for the same reason — this vendor hands out no
# continuation URL, it hands out a page number.
#
# THE COST OF THE CORRECT SHAPE is that the listing is now a FAN-OUT: one walk per agent
# on the account, discovered through `GET /v2/agent/all`. `references/bolna-core.md` puts
# `GET /v2/agent/{agent_id}/executions` at 500/min per organisation, so a fleet of a few
# hundred agents on a ten-minute tick is two orders of magnitude inside the limit. This is
# the same shape `CartesiaEngine.list_executions` already has for the same reason (its
# `agent_id` is required too) — one way per problem.

#: What we ask for per page. The vendor's stated maximum, because the fan-out cost is one
#: request per agent per page and a bigger page is strictly fewer requests.
_LISTING_PAGE_SIZE = 50
# A bound on paging, PER AGENT. 20 pages of 50 is 1000 executions for a single agent
# inside one reconciliation window; a bound is what keeps a vendor whose `has_more` sticks
# on True from turning the poller into an unbounded request loop.
_LISTING_MAX_PAGES = 20


def _listing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The execution rows in one listing response.

    `data` is the documented envelope key (`AgentExecutionV2List.data`). `executions` is a
    tolerated spelling that costs nothing, and `_request` wraps a bare top-level JSON array
    as `{"data": [...]}`, which is the third shape this has to survive — `GET
    /knowledgebase/all` and `GET /v2/agent/all` really do return bare arrays, so the
    wrapper is not hypothetical.
    """
    data = payload.get("data")
    rows = data if isinstance(data, list) else payload.get("executions")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


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
    `_agent_system_prompt`'s reason: `AgentV2`, the spec's own read-back schema, does NOT
    declare `agent_welcome_message` at all (it declares `id`, `agent_name`, `agent_type`,
    `agent_status`, `created_at`, `updated_at`, `tasks`, `ingest_source_config`,
    `agent_prompts`). Either the schema is incomplete — likely, since the vendor's PATCH
    example writes the field and the spec's provider enums are demonstrably not exhaustive
    — or the greeting genuinely cannot be read back, in which case the judge can never
    verify it and OPERATIONS §2 gate 2 is the only thing that will say so. If their read
    path spells it differently the honest outcome is `readable=False`, which the judge reports
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

    NOW VERIFIED-OAS RATHER THAN HAND-MAINTAINED: `AgentV2.tasks` is a `TasksConfigV2`
    array whose `tools_config` is `ToolsConfigV2`, so `synthesizer.provider`,
    `synthesizer.provider_config.voice`, `transcriber.provider`/`model` and
    `llm_agent.llm_config.model` are the spec's own names. If a live account names them
    differently the honest outcome is still `readable=False`, not a wrong answer.
    """
    # `agent_config` when the read-back echoes our request envelope, ROOT otherwise —
    # the same two-place lookup `_agent_name` and `_agent_greeting` already do, and it
    # was missing here (D-260). VERIFIED-OSS: their server stores
    # `agent_config.model_dump()` and `GET /agent/{id}` returns THAT, so `tasks` comes
    # back at the top level with no `agent_config` wrapper
    # (`local_setup/quickstart_server.py`, bolna-ai/bolna@cd2e192). Reading only the
    # wrapper reported `models_readable=False` for a perfectly readable agent — and
    # `False` here means "we could not find the synthesizer", which is exactly the
    # verdict this function's docstring says must not be produced by looking in the
    # wrong place.
    config = agent.get("agent_config")
    source = config if isinstance(config, dict) else agent
    tasks = source.get("tasks")
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

    # `llm_agent.llm_config.model` is where the v2 object keeps it (`LlmAgentV2` nests
    # `SimpleLlmAgent` under `llm_config`), and this read the FLAT v1 spelling — so on a
    # v2 agent, the one this adapter now creates, `llm_model` came back `None` while
    # `readable` said True (D-355). That is the worst combination the function can
    # produce and the docstring above says so: `readable=False` means "we could not find
    # the block", and a confident `None` instead means "this agent runs no configured
    # model", which is what the drift judge would have scored.
    #
    # BOTH SPELLINGS, v2 first. An account may still hold agents created through the v1
    # path (this adapter's own history, or the dashboard), and their read-back is flat.
    # Falling back costs one dict lookup and the alternative is calling a real, readable
    # agent unreadable.
    llm_model = leaf("llm_agent", "llm_config", "model") or leaf("llm_agent", "model")
    return (
        ModelConfig(
            stt_provider=leaf("transcriber", "provider"),
            stt_model=leaf("transcriber", "model"),
            llm_model=llm_model,
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
    dropped — long agent answers wrap. Three lines genuinely cannot be placed:

    * an unprefixed line arriving BEFORE any turn exists — there is no previous turn to
      append it to, and inventing a speaker for it would put words in someone's mouth;
    * a recognised prefix with an empty body;
    * a line tagged with a role that is not a party to the call (`system:`,
      `assistant_tool_call:`, `tool_response:`). These are NOT continuations, and
      treating them as such spliced tool-call arguments and the system prompt into
      whatever the previous speaker said — see `_NON_DIALOGUE_PREFIX_RE` (D-260).

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
            if _NON_DIALOGUE_PREFIX_RE.match(line):
                # A line the emitter tagged with a non-conversational role. It is not a
                # wrapped continuation of the previous turn and must never be glued onto
                # one — see `_NON_DIALOGUE_PREFIX_RE`.
                lost += 1
                continue
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
# actually sends (`llm_agent.llm_config.model`, `synthesizer.provider`,
# `transcriber.provider` all carry OUR strings). `webhook_auth="source_ip"` is D-31's
# finding that Bolna signs nothing, and the vendor names the one address it delivers from.
#
# WHAT IS A DELIBERATE *NO* RATHER THAN AN UNKNOWN:
# * `knowledge_base=False`. **THIS WAS `True` AND THE IMPLEMENTATION BEHIND IT COULD NEVER
#   HAVE WORKED (D-354).** Bolna has a knowledge base and this adapter called it — with a
#   JSON body of `{agent_id, name, text}`. VERIFIED-OAS: `POST /knowledgebase` is
#   `multipart/form-data` taking `file` (a PDF, max 20 MB) or `url`, "Provide either
#   `file` or `url`, not both", and it accepts NO agent id and NO raw text. Two separate
#   walls, and the second is the one that decides the flag:
#     (a) our `KBSourceRef` carries `text` — parsed, chunked, approved prose. There is no
#         field on this endpoint that takes prose. Rendering it to a PDF inside the
#         adapter to squeeze it through would be inventing a document format on the money-
#         adjacent side of a compliance feature, on a route nobody has ever called live.
#     (b) `Knowledgebase` has no `agent_id`, so a created KB is attached to NOTHING. The
#         link is made on the AGENT: `llm_agent.agent_type = "knowledgebase_agent"` plus
#         `llm_config.vector_store.provider_config.vector_ids = [...]`, keyed by the
#         knowledge base's `vector_id` — a DIFFERENT identifier from the `rag_id` this
#         adapter returned and deleted by. So `attach_kb` returning 2xx would have meant
#         "a document exists in the account", never "this agent can retrieve it", and
#         `list_kb`'s filter on a non-existent `row["agent_id"]` returned `[]` for every
#         agent forever — which `kb/reconciliation` reads as "the engine holds nothing",
#         i.e. permanent silent drift.
#   `False` is therefore the honest descriptor and the refusals below are the honest
#   behaviour: an absent capability produces a NAMED refusal, never a silent no-op, and
#   `require_capability` refuses at the KB publish path (`kb/service.py`) before a single
#   request goes out. WHAT WOULD REVERSE IT is ours, not the vendor's: `KBSourceRef` would
#   have to carry a PDF or a public URL instead of prose, and `attach_kb` would have to
#   PATCH the agent's `vector_ids` as its second half. That is a change to the KB tier
#   design (T0-T4, TRD §6) and to what `kb_sources` stores, so it is a decision and not a
#   flag flip — D-354 names it. In-call retrieval meanwhile is OURS (D-28's managed vector
#   service behind the RAG tool endpoint), which is where every KB tier above T0 already
#   lives, so nothing a client sees today depended on the engine built-in.
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
# * `transfer=False`. **The reason changed and the value did not (D-262).** This used to
#   say "Bolna may well support it; nobody has run the pilot gate". Bolna DOES support it,
#   read at source: `bolna/agent_manager/task_manager.py` (bolna-ai/bolna@cd2e192)
#   implements a `transfer_call` function the LLM invokes mid-conversation, guarded by a
#   `has_transfer` latch, with the destination supplied by CONFIG
#   (`transfer_call_params` / the tool's `call_transfer_number`) rather than by the model.
#   That is a different SHAPE from the one `VoiceEngine.transfer(call_id, to, warm)`
#   describes: ours is an out-of-band instruction to an execution already in flight,
#   theirs is an in-call tool the agent decides to fire at a number fixed when the agent
#   was configured. Nothing sourced exposes the former over REST.
#   So `False` remains correct — the capability our Protocol names is the one we cannot
#   do — and it is now a STATEMENT rather than a shrug. It also means the engine built-in
#   CLAUDE.md would have us prefer is reachable only by configuring a tool at publish
#   time, which is a design question (a per-agent escalation number becomes engine config,
#   not just our column) and not a flag flip. OPERATIONS §2 gate 18 asks the one thing
#   that decides it: does the hosted agent object accept a transfer tool, and is there any
#   REST route that transfers a live execution?
# * `agent_hosting="control_plane"` (D-280). Bolna is the shape this port was written
#   around and the reason it read as vendor-neutral for as long as it did: `POST /v2/agent`
#   creates the object, `PUT /v2/agent/{id}` edits it, `GET /v2/agent/{id}` answers what it
#   holds, and the system prompt — with hard rule 5's directive inside it — is agent-record
#   state (`agent_prompts.task_1.system_prompt` in `_agent_body`). Nothing about that is
#   assumed: it is the surface this adapter has always called. What the value BUYS is that
#   the assumption is now written down and refusable, so the engine that does NOT work this
#   way can say so instead of being discovered at a 404.
BOLNA_CAPABILITIES = EngineCapabilities(
    stt="ours",
    tts="ours",
    llm="ours",
    agent_hosting="control_plane",
    campaigns=False,
    knowledge_base=False,
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
                # THE shared refusal, not a third spelling of it (P2.6). Three sites used
                # to build this by hand — two adapters and a caller-ID check — under one
                # code with three different titles and details, one of which named the
                # vendor to the client. `engine_not_configured` exists precisely so every
                # surface says it identically; it had no callers while three lived beside
                # it. The vendor-specific sentence moves into the operator LOG, where the
                # engine name is ours to say.
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{self.name}")
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
        # THE LADDER ITSELF LIVES IN `vendor_http.vendor_request` (D-240): it was two
        # copies here that had drifted apart, and the divergence was invisible because
        # no fixture ever made a vendor misbehave.
        return await vendor_request(
            self._http(),
            method,
            path,
            engine=self.name,
            absent_is_success=absent_is_success,
            **kwargs,
        )

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
                        # REQUIRED, and we were not sending it (D-260). `Task.toolchain`
                        # has no default in their model (`bolna/models.py`), and the
                        # runtime dereferences it with a bare subscript in two places —
                        # `task["toolchain"]["pipelines"]` in
                        # `bolna/agent_manager/task_manager.py` and
                        # `get_required_input_types` in `bolna/helpers/utils.py`. So an
                        # omitted `toolchain` is a validation error at create time or a
                        # KeyError at dial time, not a defaulted field: the pipeline list
                        # is ALSO what tells the engine this task consumes audio rather
                        # than text, so there is nothing sensible for it to guess.
                        #
                        # These exact values are the ones their own builder emits for a
                        # transcriber+llm+synthesizer voice task (`bolna/assistant.py`)
                        # and the ones their API.md example carries.
                        #
                        # VERIFIED-OSS at bolna-ai/bolna@cd2e192 — the self-hosted
                        # framework the hosted platform is built on, which is strong
                        # evidence about the SHAPE and not proof of the hosted contract.
                        # If the hosted `/v2/agent` injects a default of its own, sending
                        # the documented value costs nothing; if it does not, this is the
                        # difference between an agent that dials and one that KeyErrors.
                        # docs/vendor/bolna/oss-harvest.md records the read.
                        "toolchain": {
                            "execution": "parallel",
                            "pipelines": [["transcriber", "llm", "synthesizer"]],
                        },
                        "tools_config": {
                            # **THIS BLOCK WAS THE V1 SHAPE POSTED AT THE V2 ENDPOINT
                            # (D-355).** `POST /v2/agent` binds `tools_config` to
                            # `ToolsConfigV2`, whose `llm_agent` is `LlmAgentV2` —
                            # `{agent_type, agent_flow_type, routes, llm_config}` — with the
                            # model settings NESTED under `llm_config`. What we sent was the
                            # flat legacy `SimpleLlmAgent` body, which is what `ToolsConfig`
                            # (v1) accepts. VERIFIED-OAS plus the vendor's own
                            # `create-agent/SKILL.md`, whose worked Indian-language example
                            # is exactly the nesting written below.
                            #
                            # `agent_type` is what selects the union arm: `simple_llm_agent`
                            # (this) or `knowledgebase_agent` (the arm that adds
                            # `vector_store` — see `BOLNA_CAPABILITIES.knowledge_base` for
                            # why we do not send it).
                            #
                            # MARKED ASSUMPTION RETAINED, AND NARROWED — `family` vs
                            # `provider` (D-260). Both fields exist on `SimpleLlmAgent` and
                            # both default to `"openai"`. VERIFIED-OSS says `family` is read
                            # by nothing and `provider` chooses the client
                            # (bolna-ai/bolna@cd2e192, `bolna/providers.py`), so both are
                            # sent, spelling the same thing, which is the only combination
                            # that cannot route somewhere we did not name.
                            # WHICH LLM PROVIDERS ARE REACHABLE — AND THE TWO SOURCES PROVE
                            # DIFFERENT THINGS, WHICH AN EARLIER VERSION OF THIS COMMENT RAN
                            # TOGETHER. `references/providers-matrix.md` (VERIFIED-VENDOR-REPO)
                            # lists OpenAI, Azure OpenAI, OpenRouter, Google Gemini and
                            # "Custom (LiteLLM-compatible)", and names no `sarvam`. That is
                            # a statement about what the vendor DOCUMENTS AND SUPPORTS.
                            #
                            # It is NOT a statement about what the API accepts, and this
                            # comment used to say Sarvam was reachable "only" as a custom
                            # model — a wall inferred from a prose table. The SPEC says
                            # otherwise, decisively: in this very schema `agent_flow_type`
                            # carries `enum: [streaming, preprocessed]` while `provider` and
                            # `family` carry NO enum, only `default: "openai"`, beside a
                            # settable `base_url` whose example is OpenAI's `/v1`. The spec's
                            # author uses `enum` when they mean a closed set — including on
                            # OTHER `provider` fields (telephony is `enum: ["twilio",
                            # "plivo"]`) — and deliberately did not here. An arbitrary
                            # OpenAI-compatible endpoint is therefore the DESIGNED extension
                            # point, not a workaround.
                            #
                            # So: `POST /user/model/custom` + `provider: "custom"` is the
                            # SUPPORTED route and probably the operationally correct one, and
                            # it remains D-356 (it needs `ModelConfig` to grow an
                            # `llm_provider` and somebody to register the model). But it is
                            # not the only route the contract permits, and nobody reading
                            # this should treat it as a wall. Which of the two actually works
                            # is a live question no document settles — gate 7's sibling in
                            # OPERATIONS §2. Until then this agent runs on whatever
                            # OpenAI-compatible model `cfg.models.llm_model` names.
                            #
                            # (D-36's Sarvam LLM leg is superseded anyway: the founder has
                            # moved the LLM to Gemini on GCP Vertex, paid and usage-billed.
                            # Gemini IS named in the matrix above, which is the friendliest
                            # of the possible answers — see the Vertex decision in ROADMAP.)
                            "llm_agent": {
                                "agent_type": "simple_llm_agent",
                                "agent_flow_type": "streaming",
                                "llm_config": {
                                    "agent_flow_type": "streaming",
                                    "provider": "openai",
                                    "family": "openai",
                                    "model": cfg.models.llm_model,
                                    # SENT EXPLICITLY, and the reason is that NOT sending them
                                    # was a decision nobody had taken (D-283).
                                    #
                                    # READ AT SOURCE, bolna-ai/bolna@cd2e192, `bolna/models.py`:
                                    # `Llm.max_tokens` defaults to **100** and
                                    # `Llm.temperature` to **0.1**, and
                                    # `task_manager.__setup_llm` reads both with bare
                                    # subscripts off `llm_agent_config`. Our body omitted
                                    # them, so the stored `agent_config.model_dump()` filled
                                    # the vendor's defaults and every agent on the platform
                                    # ran with a 100-token ceiling on each reply — a real
                                    # product knob, silently inherited.
                                    #
                                    # WHY 400 AND NOT 100. A cap is a SAFETY VALVE against a
                                    # runaway generation, not a style control: brevity is the
                                    # script's job, and a ceiling that bites mid-sentence does
                                    # not shorten a reply, it truncates one — the TTS then
                                    # speaks a fragment and hangs. 100 is close enough to a
                                    # normal turn to bite, and it is worse in OUR language than
                                    # the number suggests: token fertility (tokens per word) is
                                    # ~2.1-2.3 for Telugu against ~1.2-1.4 for English on
                                    # general tokenizers, and Sarvam's own reaches 1.4-2.1 for
                                    # Indic — so 100 tokens is roughly 45 Telugu words, and a
                                    # receptionist reading back three appointment slots passes
                                    # that. 400 clears every legitimate turn while still
                                    # bounding a monologue a caller would have to sit through.
                                    # (Fertility figures: FLORES-200 tokenizer comparisons,
                                    # searched 18 Aug 2026 — arxiv.org/pdf/2605.29379 and the
                                    # IndicSuperTokenizer report. REPORTED, NOT READ against
                                    # Sarvam's own tokenizer, and it does not need to be: the
                                    # decision is "leave headroom", and the direction is not in
                                    # doubt.) The LLM leg is Sarvam 105B, FREE PER TOKEN
                                    # (D-35/D-36, TRD §10), so the headroom costs nothing on the
                                    # money path — the only cost of a higher cap is a longer
                                    # worst-case utterance, which `max_call_duration_s` already
                                    # bounds from the other side.
                                    #
                                    # WHY 0.1 — THE VENDOR'S DEFAULT IS RIGHT, AND IS SENT
                                    # ANYWAY. This agent reads a client's script and carries
                                    # `TRUTHFUL_ANSWER_DIRECTIVE` underneath it; the failure we
                                    # care about is the model paraphrasing away a compliance
                                    # sentence or improvising a price, and low temperature is
                                    # the setting that makes that rarest. Raising it buys
                                    # "sounds more natural", which is a prompt-and-voice problem
                                    # on a phone call rather than a sampling one. It is written
                                    # here rather than inherited because a vendor default is
                                    # somebody else's release note: a compliance-bearing prompt
                                    # is not a thing to leave on a number that can change
                                    # without our deploying.
                                    "max_tokens": 400,
                                    "temperature": 0.1,
                                },
                            },
                            # MARKED ASSUMPTION, AND THE EVIDENCE IS AGAINST IT (D-358).
                            # `cfg.models.tts_voice` holds a MODEL string — `bulbul:v3` or
                            # `bulbul:v2`, per `agents/voices.py`, which says outright that
                            # it "offers a choice of MODEL ... and offers no named speakers"
                            # because no Sarvam speaker list was known. It is sent in the
                            # `voice` key.
                            #
                            # The vendor's own Sarvam example puts those in DIFFERENT keys:
                            # `"provider_config": {"model": "bulbul:v3", "voice": "Ashutosh",
                            # "voice_id": "ashutosh"}` (VERIFIED-VENDOR-REPO,
                            # `create-agent/SKILL.md`), and `GET /me/voices` exists to list
                            # the speakers once a TTS provider is configured. So we are
                            # very likely naming a model where a speaker belongs, and
                            # naming no model at all.
                            #
                            # NOT "FIXED" HERE, and the restraint is the point: moving the
                            # string to `model` leaves `voice` unset and the engine picks
                            # whichever speaker it likes, which changes what every client's
                            # caller HEARS on the strength of one example in a prose file.
                            # Splitting it properly needs `ModelConfig` to carry a
                            # `tts_model` beside `tts_voice`, and the voice catalog to carry
                            # real speaker ids — which come from `GET /me/voices` on a live
                            # account. Both halves are named in D-358; the second is the
                            # external blocker (an account), and OPERATIONS §2 gate 3
                            # already owns the question.
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
                            # **REQUIRED, AND WE WERE NOT SENDING THEM (D-355).**
                            # VERIFIED-OAS: `ToolsConfigV2.required` is
                            # `[llm_agent, synthesizer, transcriber, input, output]`, and
                            # `InputOutput` itself requires both `provider` and `format`.
                            # A create that omits them is a 400 — the agent never exists,
                            # so nothing downstream of publish can be right either.
                            #
                            # WHY `plivo`, WHICH IS THE VENDOR'S OWN DEFAULT
                            # (`InputOutput.provider.default: plivo`). These two blocks say
                            # which telephony leg carries the audio, and D-05 puts our
                            # Indian numbers on Plivo/Exotel/Vobiz rather than on Bolna's
                            # hosted pool — with Plivo the 160-series (transactional)
                            # carrier, which is the series every agent we publish today
                            # runs on. Naming it rather than inheriting it is the same
                            # argument `temperature` makes above: a vendor default is
                            # somebody else's release note.
                            #
                            # NOT DERIVED FROM `cfg`, and that is a gap named rather than
                            # papered over: `AgentConfig` carries no telephony provider,
                            # because until now nothing sent one. A 140-series promotional
                            # agent belongs on Vobiz and would need this to vary — which is
                            # a column, a UI control and a DLT-series decision, i.e. D-357,
                            # not a literal edited here. `format: "wav"` is the only value
                            # `InputOutput.format` enumerates.
                            "input": {"provider": "plivo", "format": "wav"},
                            "output": {"provider": "plivo", "format": "wav"},
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
        Protocol's idempotent success. Their hosted reference documents 200 and 400 and
        says nothing at all about a repeat.

        WHAT THE OSS SERVER ACTUALLY DOES, read at source (D-260, VERIFIED-OSS,
        bolna-ai/bolna@cd2e192 `local_setup/quickstart_server.py`): `delete_agent` checks
        `redis_client.exists` and raises `HTTPException(404)` for an absent id — so 404 IS
        the intent. But that raise sits INSIDE a `try` whose `except Exception` re-raises
        as a 500, and `HTTPException` is an `Exception`, so the server it is written in
        answers **500**, not 404. (`get_agent` has the identical defect.) This is the
        cleanest illustration in the whole harvest of why VERIFIED-OSS is not proof of the
        hosted contract: it tells us the intended semantics and simultaneously shows the
        implementation missing them. It moves this assumption from "guessed" to
        "OSS-backed intent"; it does not close it.
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
        # A NO-OP FOR THIS ENGINE, and here for the reason `_agent_body`'s speech guards
        # are (D-282): Bolna holds the agent, so hard rule 5's directive is agent-record
        # state that `publish_agent` wrote and `verification.judge` PROVED it is running,
        # and `ctx.system_prompt` is None. The guard reads the descriptor rather than the
        # vendor name, so narrowing `BOLNA_CAPABILITIES.agent_hosting` — which is what a
        # vendor deprecating its agent API would look like — changes what this adapter
        # will dial, instead of leaving a field that says one thing and a dial that does
        # another.
        #
        # `prompt_on_the_wire=None` is honest rather than a shrug: this body carries no
        # prompt because it does not need to, and the guard reads the capability to decide
        # whether that is a floor being dropped or a floor living somewhere better.
        require_call_compliance_floor(engine=self, prompt_on_the_wire=None)
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
        """`POST /call/{execution_id}/stop`.

        **THE PATH WAS WRONG (D-353).** This was `POST /executions/{id}/stop`, which is not
        a route the vendor has: the pinned OAS's only `/executions/...` entries are the two
        single-item GETs, and the stop route lives under `/call`. VERIFIED-OAS,
        `/call/{execution_id}/stop`: "Stop a queued or scheduled call".

        WHAT IT CANNOT DO, in the vendor's own words: *"This cannot stop a call already in
        progress"* (`make-call/SKILL.md`). So this method ends a call that has not started;
        it does not hang up on a live caller, and no route in the spec does. Nothing in
        this tree relies on the second meaning — `end_call` is the campaign path's way to
        pull a queued dial back after a DNC addition or the big red switch, which is
        exactly the queued/scheduled case. Recorded here rather than assumed, because the
        method's NAME suggests the stronger promise and the next reader will believe it.
        """
        await self._request("POST", f"/call/{call_id}/stop")

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        # NOT "unverified" any more — see `BOLNA_CAPABILITIES.transfer` for what was read
        # at source (D-262). Bolna transfers calls, but through an in-call tool the LLM
        # fires at a config-supplied number; no sourced route instructs an execution
        # already in flight, which is what THIS signature promises. So the refusal stands
        # on a shape mismatch rather than on missing evidence.
        # Failing loudly beats pretending a transfer happened — and it fails with the SAME
        # code a caller could have asked the descriptor for BEFORE calling, so a screen and
        # this method cannot disagree.
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
    # ALL THREE METHODS REFUSE. See `BOLNA_CAPABILITIES.knowledge_base` for the two walls
    # that decide it (D-354): the vendor's `POST /knowledgebase` takes a PDF or a URL over
    # multipart and cannot ingest our `KBSourceRef.text`, and a created knowledge base
    # carries no agent linkage — the link lives on the AGENT's `vector_ids`, keyed by a
    # `vector_id` this adapter never read.
    #
    # THE REFUSAL IS `require_capability`, NOT A BESPOKE `raise`, and that is the point: it
    # is the same code a caller gets from asking the descriptor BEFORE calling, so a screen
    # and these methods cannot disagree, and widening the flag without writing the client
    # makes them fail loudly here rather than fall off the end returning None.
    #
    # `list_kb` RETURNING `[]` WOULD HAVE BEEN THE WORST OF THE THREE and is why this is a
    # refusal rather than a stub: `kb/reconciliation` reads an empty list as "the engine
    # holds no documents for this agent", which is a positive claim about the engine, and
    # a refusal is the only answer that is not a lie about a system we cannot read.

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        require_capability("knowledge_base", engine=self)
        # Unreachable while the descriptor says False, and kept as a real refusal rather
        # than an `assert` for `provision_number`'s reason: the way this line gets reached
        # is somebody flipping the flag without writing the multipart upload and the agent
        # `vector_ids` patch, and that must fail loudly rather than return None.
        raise ProblemError(
            kind="dependency",
            code="engine_capability_unverified",
            title="This voice platform cannot hold this knowledge base",
            detail="The voice platform's knowledge base accepts documents, not text.",
        )

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        require_capability("knowledge_base", engine=self)

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        require_capability("knowledge_base", engine=self)
        return []

    # --- reading the truth ---------------------------------------------------

    def _snapshot(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(payload.get("status") or "").lower()
        status = _STATUS_MAP.get(raw_status, "failed")
        call_id = str(payload.get("id") or payload.get("execution_id") or "")
        cost = self._cost(payload)
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
        # THE VENDOR HAS EXACTLY TWO TIMESTAMPS ON AN EXECUTION, AND THEY ARE THE
        # FALLBACKS HERE RATHER THAN THE PRIMARIES (D-361). `AgentExecution` declares
        # `created_at` and `updated_at` and nothing else; `started_at`, `ended_at` and
        # `completed_at` appear in NEITHER the pinned OAS nor
        # `references/execution-payload.md`. Two of the three reads below therefore never
        # match on a real payload — which is harmless ONLY because the real field is the
        # other operand of each `or`, and that is luck rather than design.
        #
        # LEFT AS TWO-PLACE READS, deliberately. `created_at`/`updated_at` are FIRST for
        # `started` (already correct) and the invented `ended_at` is kept ahead of
        # `updated_at` for one reason: `updated_at` is "last updated", which on a row that
        # is still transitioning is NOT when the call ended. If the platform ever does
        # emit a real end instant under that name, it is strictly better than the
        # fallback. What is NOT acceptable is a fixture that carries the invented spelling
        # — that is how `direction` (D-359) hid, and the conformance fixture now uses
        # `updated_at` so the path a live payload takes is the path the suite exercises.
        started = _parse_dt(payload.get("created_at") or payload.get("started_at"))
        ended = _parse_dt(payload.get("ended_at") or payload.get("updated_at"))
        duration = payload.get("conversation_duration") or payload.get("duration")
        telephony = payload.get("telephony_data") or {}
        agent_ref = payload.get("agent_id")
        # **THE VENDOR HAS NO TOP-LEVEL `direction` AND THIS READ ONE (D-359).** It said
        # `payload.get("direction") == "inbound"`, and `AgentExecution` declares no such
        # field; the direction lives on `telephony_data.call_type`, enum
        # `["outbound", "inbound"]` (VERIFIED-OAS). So the test was never true and every
        # execution — inbound receptionist calls included — was normalized as `outbound`.
        # `telephony_data` first, the old spelling kept as a fallback because it costs
        # nothing and an unknown payload shape should degrade rather than flip.
        raw_direction = telephony.get("call_type") or payload.get("direction")
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=str(agent_ref) if agent_ref else None,
            direction="inbound" if raw_direction == "inbound" else "outbound",
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
            # ALWAYS THE INSTANT WE OBSERVED IT, and that is now a statement of fact
            # rather than a fallback nobody had checked (D-361): the vendor publishes NO
            # `completed_at` — not in the OAS, not in `execution-payload.md` — so the
            # left operand is always None and `datetime.now(UTC)` always wins. The read is
            # kept because it costs nothing and is right the day they add one, but nobody
            # should read this line as "their timestamp where they give one" and plan
            # around a precision we do not have. What we actually record is the poller's
            # tick resolution, which is honest about being a CEILING on when the execution
            # became billable. `updated_at` is deliberately NOT used here: on a `completed`
            # row it is the last write of any kind, which is close but is not the same
            # claim, and a wrong instant on the billing path is worse than a coarse one.
            # Absent until the execution is billable, so it never reads as "ready at" for
            # a call that is not.
            billable_ready_at=(
                _parse_dt(payload.get("completed_at")) or datetime.now(UTC)
                if raw_status == "completed"
                else None
            ),
            engine_extracted=payload.get("extracted_data") or {},
            engine="bolna",
        )

    def _cost(self, payload: dict[str, Any]) -> CostBreakdown | None:
        """Vendor cost figure -> INR, and an honest account of what is assumed on the way.

        NEITHER HALF IS A FACT, and `_ASSUMED_MINOR_UNITS_PER_MAJOR` carries the detail.
        The UNIT is the vendor's own OAS ("in cents") overriding the vendor's own prose
        ("account currency") by the vendor's own precedence rule — strong, but a document
        reconciliation rather than an observation, and worth 100x. The CURRENCY is named
        in no first-party source at all, and getting it wrong is worth 83x. This used to
        write
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
            # SILENT UNTIL P1.2. `total_cost` is now VERIFIED-OAS (`AgentExecution.
            # total_cost`), so a missing key is no longer plausibly a spelling we guessed
            # — but "the key is not there" and "this execution carries no cost yet" are
            # still the same observation from here, and the second one means a call meters
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
            source_amount=Decimal(str(total)) / _ASSUMED_MINOR_UNITS_PER_MAJOR,
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

    async def _agent_refs(self) -> list[str]:
        """Every agent id on this Bolna account. `GET /v2/agent/all` -> a bare JSON array
        of `AgentV2` objects, each with a top-level `id` (VERIFIED-OAS: `AgentListV2` is
        declared `type: array` of `AgentV2`, and `AgentV2.id` is the uuid).

        `_request` wraps a bare array as `{"data": [...]}`, which is why this reads
        `_listing_rows` rather than the payload directly. `agent_id` is accepted beside
        `id` because the v1 `GET /all` rows spell it that way and an account may still be
        answered by that shape; a row with neither is skipped rather than guessed at.

        THE ACCOUNT, NOT THE TENANT. One Bolna account holds every tenant's agents, so this
        is deliberately global — the poller's job is to find executions nobody told us
        about, and scoping it to agents we currently know about would hide exactly the call
        placed by an agent our routing table has lost.
        """
        payload = await self._request("GET", "/v2/agent/all")
        refs: list[str] = []
        for row in _listing_rows(payload):
            for key in ("id", "agent_id"):
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    refs.append(value.strip())
                    break
        return refs

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """The guarantee of record (D-31) — rewritten from the vendor's real contract.

        Read the block above `_LISTING_PAGE_SIZE` first: the endpoint this method used to
        call does not exist, and the completeness heuristic it used to run was built on the
        premise that Bolna publishes no pagination contract. It publishes one.

        WHAT THIS DOES NOW. `GET /v2/agent/all` for the account's agents, then for each
        agent `GET /v2/agent/{ref}/executions?from=<since>&page_number=n&page_size=50`,
        looping while `has_more` is True. `from` is the vendor's own `created_at >=` filter
        (sent as UTC ISO 8601 with an explicit offset — `references/bolna-core.md` warns
        that a datetime without one "is rejected or silently runs in UTC").

        HOW COMPLETENESS IS DECIDED, and `complete=True` stays a POSITIVE claim:

        * every agent's walk ended on a response that said `has_more: false`
          -> `complete=True`;
        * a response carried NO `has_more` at all and returned a full page
          -> `full_page_suspected`. The flag is documented, so its absence means we are
          not talking to the endpoint we think we are, and a full page under that
          uncertainty is the one shape that could be hiding rows;
        * our own per-agent bound stopped a walk that still said `has_more`
          -> `page_cap_reached`;
        * `has_more` stayed True but the page produced no execution we had not already
          seen -> `next_link_no_progress`. Without this a stuck flag burns the full cap
          on identical pages and then reports the wrong reason.

        THE FIRST REASON FOUND WINS AND THE WALK CONTINUES TO THE NEXT AGENT. A listing
        that is incomplete for one agent is still worth every row it can get for the
        others — the poller alerts once and repairs what it has, which is what
        `reconcile_executions` is written to do with a `complete=False` answer.

        Rows are de-duplicated by execution id across pages and across agents: the vendor's
        window shifts under a walk (executions keep arriving while we page), so a repeat is
        legitimate and re-driving one call twice is wasted engine load.
        """
        cutoff = since.astimezone(UTC)
        snapshots: list[ExecutionSnapshot] = []
        seen_ids: set[str] = set()
        # The `GET /v2/agent/all` response IS a response we read, so it counts:
        # `pages_fetched` is "how many responses were read", and understating it would make
        # a fan-out look like a single-page vendor in the one metric that shows the walk ran.
        pages = 1
        reason: ListingIncompleteReason | None = None

        for agent_ref in await self._agent_refs():
            page_number = 1
            while True:
                payload = await self._request(
                    "GET",
                    f"/v2/agent/{agent_ref}/executions",
                    params={
                        "from": cutoff.isoformat(),
                        "page_number": page_number,
                        "page_size": _LISTING_PAGE_SIZE,
                    },
                )
                pages += 1
                rows = _listing_rows(payload)
                new_rows = 0
                for row in rows:
                    snapshot = self._snapshot(row)
                    if snapshot.engine_call_id in seen_ids:
                        continue
                    seen_ids.add(snapshot.engine_call_id)
                    snapshots.append(snapshot)
                    new_rows += 1

                has_more = payload.get("has_more")
                if not isinstance(has_more, bool):
                    # The documented flag is missing. Believe the page instead: a SHORT page
                    # cannot be hiding anything (the vendor returned fewer rows than we
                    # asked for), a full one might be.
                    if len(rows) >= _LISTING_PAGE_SIZE:
                        reason = reason or "full_page_suspected"
                    break
                if not has_more:
                    break
                if new_rows == 0:
                    reason = reason or "next_link_no_progress"
                    break
                if page_number >= _LISTING_MAX_PAGES:
                    reason = reason or "page_cap_reached"
                    break
                page_number += 1

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
        # DIRECTION COMES FROM THE SNAPSHOT, and this was a SECOND COPY of the same wrong
        # read (D-359): `payload.get("direction")`, a field `AgentExecution` does not
        # declare. The vendor puts it on `telephony_data.call_type`, `_snapshot` reads it
        # there, and one way per problem means this line asks that answer rather than
        # re-deriving it — two spellings of one rule is where the drift starts, and this
        # is the pair that proves it. The DEFAULT is unchanged and deliberate: everything
        # we cannot classify is treated as a call WE placed, which is the compliance-safe
        # direction, because outbound is the side carrying DNC and calling-hours
        # obligations and a misclassified call is then over-regulated, never under.
        return CallEvent(
            call_id=snapshot.engine_call_id,
            engine_agent_ref=str(agent_ref) if agent_ref else None,
            direction=snapshot.direction,
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
