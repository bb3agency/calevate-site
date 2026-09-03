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

1. **Webhooks are unsigned**, so authenticity = source-IP allowlist + `(execution_id,
   status)` dedupe, payloads are HINTS, and the executions poller is the guarantee of
   record. **THERE ARE THREE DOCUMENTED EGRESS ADDRESSES AND THIS DOCSTRING SAID THERE
   WAS ONE (D-412)** — `13.203.39.153`, `13.126.9.249`, `13.202.133.53`, with the
   consequence stated on the page: *"Whitelist all three on your server to ensure you
   receive all webhook events"*
   (`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md`).
   Every source this file was written from named one address, and they were right when
   they were read; the vendor renumbered. `DEFAULT_BOLNA_SOURCE_IPS` held the stale set,
   and because that allowlist fails safe, two of three senders were being REJECTED.
   **They are NOT at-most-once, which is what this docstring claimed (D-352)**: the
   hosted platform "retries on non-2xx" and fires one delivery per status transition, so
   the receiver must ack 2xx and dedupe on the PAIR — never on the execution id alone, or
   the `completed` transition is discarded as a duplicate of `queued`. VERIFIED-VENDOR-
   REPO: `references/execution-payload.md` §"Webhook delivery" and
   `setup-webhook/SKILL.md` §"Idempotency". **THE HOSTED DOCS DO NOT CORROBORATE THE
   RETRY, and that is worth knowing rather than glossing**: their webhook page describes
   the URL, the payload shape and the source IPs and says nothing whatever about retries,
   signing or delivery guarantees. It does not contradict D-352 — it simply does not
   speak — so the retry claim still rests on the skills repo alone, and "payloads as
   hints, poller as truth" (TRD §5) remains the load-bearing design rather than an
   abundance of caution.
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

Per-turn timings ARE mapped here now, and this paragraph used to say they were not. Their
`latency_data` object on Get Execution — per-component `transcriber`/`llm`/`synthesizer`
timings, a first-audio number and a `region` code — is read by `parse_latency_data` into
`CallLatency`, and the post-call pipeline stores it (`call_engine_latency`). Three things
about that are worth the next reader's attention, because each was a reason not to:

* It is STILL NOT the voice-to-voice measurement the budget is written in, and nothing
  here turns it into one. Gate 4's stopwatch is the only thing that can say whether the
  sum of three components resembles what a caller hears; `scripts/pilot/latency.py` makes
  that comparison and reads its vendor half from this function.
* The transcriber entries carry recognised TEXT (hard rules 5/6). The reader takes numbers
  and a region code and nothing else — `CallLatency` has no field text could land in.
* It stopped being an unverified claim: the page is in the mirror
  (`bolna-findings/mirror/pages/concepts/call-latencies.md`), and D-410's South India
  language model behind a US orchestrator made `llm.time_to_first_token` the only evidence
  that exists for the largest unmeasured number in the product. D-449 removed that round
  trip (`eastus2`) without ever measuring it, which is why this reader stayed: the
  measurement is now the evidence for what the residency withdrawal bought.

Resilience shipped here: a request timeout and jittered backoff on 429 (SURFACES §3.3).
The circuit breaker that section also describes is deliberately NOT built — see the
throttle block below for what is and is not retried, and why.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from time import monotonic
from types import MappingProxyType
from typing import Any, Final, NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from calevate_shared.config import bolna_source_ips
from calevate_shared.engine import (
    CALLER_MEMORY_VARIABLE,
    DECLARED_POSTURE,
    E164,
    LLM_TTFT_BUDGET_MS,
    AccountKBListing,
    AccountKBObject,
    AccountKBState,
    ActionToolSpec,
    AgentConfig,
    AgentSnapshot,
    CallContext,
    CallHandle,
    CallLatency,
    CostBreakdown,
    EngineAgentRef,
    EngineCapabilities,
    EngineKBRef,
    ExecutionListing,
    ExecutionSnapshot,
    KBSourceRef,
    ListingIncompleteReason,
    LlmCredentialPlacement,
    LlmProvider,
    ModelConfig,
    NumberSpec,
    ProvisionedNumber,
    RecallOutcome,
    TurnLatency,
    WebhookVerdict,
    compose_engine_prompt,
    openai_base_url,
    render_caller_memory,
)
from calevate_shared.events import CallEvent, CallStatus, Speaker, TranscriptTurn
from pydantic import ValidationError

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.fx import current_fx_quote
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
from apps.api.engine.violations import OPEN_STATUS, ViolationListing, walk_violations

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
# OAS: `AgentExecution.status` in the pinned spec enumerated fifteen values, and the same
# fifteen appeared as the `status` query filter on `GET /v2/agent/{agent_id}/executions`.
#
# **THE ENUM IS SIXTEEN, NOT FIFTEEN — `prepared` IS THE SIXTEENTH (D-351 AGAIN).** The
# pinned OAS is not the vendor's only statement of this enum and it was the narrower one.
# Their published errors page carries the SAME table with one more row (VERIFIED-DOCS,
# `bolna-findings/mirror/pages/api-reference/errors.md:42`):
#
#     | `prepared` | Intermediate | Execution record created and validated (recipient
#     number, from/to number assigned) but not yet handed off to the dial queue |
#
# So the list is:
#
#     scheduled  prepared  queued  rescheduled  initiated  ringing  in-progress
#     call-disconnected  completed  balance-low  busy  no-answer  canceled  failed
#     stopped  error
#
# `_VENDOR_STATUSES` below is that enum, and `tests/bolna_snapshot_test.py` asserts every
# member of it is mapped — so a status the vendor adds cannot quietly become `failed`.
#
# **`prepared` IS THE SAME DEFECT `rescheduled` WAS, ONE RUNG EARLIER.** It is labelled
# `Intermediate` by the vendor's own table — the execution exists, its numbers are
# assigned, and the dial has not been handed off yet — so it is a call that is ALIVE.
# Unmapped it took the `failed` default, which on the campaign path is not a cosmetic
# mislabel: `ExecutionSnapshot.terminal` follows the mapped status, so the dispatcher
# would have counted a contact as attempted-and-dead while the vendor was still holding
# it, freed the line, and left the real dial to land on a contact already marked failed.
# It maps to `queued` for the same reason `scheduled` and `rescheduled` do — the vendor
# has the call and will dial it.
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
#: The vendor's own `status` enum. Not iterated at runtime — it exists so a test can prove
#: `_STATUS_MAP` covers it.
_VENDOR_STATUSES: frozenset[str] = frozenset(
    {
        "scheduled",
        "prepared",
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

#: What their stop route answers when it caught a dial before it was executed.
#:
#: VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/api-reference/calls/stop_call.md:47`
#: prints it as the 200 body, and :7 states the route's scope — "stop a call when its
#: status is `queued` or `scheduled` … cancel pending calls before they are executed".
#: Both halves matter: the string is what we match, and the sentence is what makes
#: matching it mean "the phone did not ring".
#:
#: A CONSTANT rather than a literal at the one call site, because it is also a key of
#: `_STATUS_MAP` below — where it maps to `failed`, which is correct for a call ROW and is
#: exactly why `end_call` has to read it before that mapping erases the distinction.
_STOPPED_STATUS = "stopped"

_STATUS_MAP: dict[str, CallStatus] = {
    "scheduled": "queued",
    "prepared": "queued",
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


#: **OUR LEG VOCABULARY -> THE ENGINE'S WIRE VALUE.** The whole of hard rule 2 for the LLM
#: leg lives in this dict: `LlmProvider` is ours and closed, these three strings are theirs,
#: and nothing outside `apps/api/engine/` may name either side of the arrow.
#:
#: **TOTAL OVER `LlmProvider` ON PURPOSE, AND mypy PROVES IT.** Annotated
#: `Mapping[LlmProvider, str]`, so a fourth declared leg is a type error at this line rather
#: than a `KeyError` on the first publish after somebody adds one — which is the D-104
#: doctrine (a Literal and its value table derived together) applied to a table that cannot
#: be derived, because only the vendor knows how they spell it.
#:
#: VERIFIED-VENDOR-DOCS, hash-checked mirror, each value stated TWICE on its own provider
#: page — once in a copy-pasteable `llm_config` body under "Quick config" and once in the
#: "Key settings" table: `azure-openai` (`azure-openai.md:20,59`), `openai` (`openai.md:20,59`)
#: and `google` (`gemini.md:20,52`). Corroborated VERIFIED-OSS against the engine's own
#: `LLMProvider` enum (`bolna/enums.py:93-118`). Two classes of evidence, machine-readable
#: on both sides — see `_llm_routing` for what happens when a wire value is read off a
#: human-readable LABEL instead, which is the whole of D-417.
_WIRE_PROVIDER: Final[Mapping[LlmProvider, str]] = MappingProxyType(
    {"azure_openai": "azure-openai", "openai": "openai", "google": "google"}
)

#: THE WIRE VALUE -> OUR LEG, the inverse of `_WIRE_PROVIDER`, DERIVED rather than retyped
#: (D-104: a Literal and its value table are built together, not spelled twice). The read
#: half needs it: `_agent_models` identifies a leg WITH an endpoint from the endpoint
#: itself, but the `google` leg has none — its only identifier on the agent object is the
#: `provider` string the engine echoes, and this maps that string back to our vocabulary.
_OUR_PROVIDER: Final[Mapping[str, LlmProvider]] = MappingProxyType(
    {wire: ours for ours, wire in _WIRE_PROVIDER.items()}
)

#: THE vendor's spelling of "Azure OpenAI" in an agent's `llm_config.provider` — one
#: place, because `_llm_routing` writes it and `tests/in_call_llm_provider_test.py` pins
#: it, and a second literal is how a corrected value gets applied in one of them.
#:
#: VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/providers/llm-model/
#: azure-openai.md` states it as a copy-pasteable `llm_config` body and again in its Key
#: settings table. See `_llm_routing` for why that beats the two display labels D-410
#: chose `"azure"` from, and for the fallback order if the live platform disagrees.
_AZURE_LLM_PROVIDER: Final = _WIRE_PROVIDER["azure_openai"]

#: EVERY credential-store key Bolna's Azure OpenAI provider is documented to require, in
#: the vendor's own words. **This is the answer to the last marked assumption in D-410**
#: (OPERATIONS §2 gate 16f), and it is a fact rather than a derivation for the first time.
#:
#: VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/providers.md` (fetched 20 Aug 2026,
#: sha256 63231b2b7a0c5a338dd1d6342dc65ea4ac05546f7ddb6a28bc3c9a4ec24791b9), "LLMs" tab,
#: "Azure OpenAI" accordion, under the sentence *"All these keys **must** be added for the
#: respective provider."* The mapping below is that table verbatim.
#:
#: **THIS IS DATA FOR AN OPERATOR AND FOR THE GATE, NOT AN INSTALLER**, and the
#: distinction is deliberate rather than unfinished. `set_llm_credential` installs ONE
#: entry — the API key — because that is the only one of the four whose value this
#: repository can produce without inventing something:
#:
#:   * `AZURE_OPENAI_API_KEY`     — `Settings.azure_openai_api_key`. Ours, and secret.
#:   * `AZURE_OPENAI_API_BASE`    — `azure_openai_base_url(azure_openai_resource)`. Ours.
#:   * `AZURE_OPENAI_MODEL`       — `Settings.azure_openai_deployment` (NOT
#:     `azure_openai_model`; on Azure the API addresses the DEPLOYMENT). Ours.
#:   * `AZURE_OPENAI_API_VERSION` — ⚠ **NOBODY HERE KNOWS WHAT TO PUT HERE, AND THE
#:     VENDOR'S TWO PAGES DISAGREE ABOUT WHETHER IT IS NEEDED.** This table calls it
#:     required; `providers/llm-model/azure-openai.md` says the console connection needs
#:     *"your Azure endpoint URL, API key, and deployment name"* — three things, no
#:     api-version. And D-410 chose the **v1 surface** (`…/openai/v1`) precisely because
#:     it has no `api-version` at all; a dated string belongs to the CLASSIC surface. So
#:     the three readings are "vestigial for a v1 base URL", "their Azure client is the
#:     classic one and our endpoint choice is wrong", and "any date-shaped string is
#:     accepted and ignored". **A guessed date here would be exactly the defect gate 16f
#:     exists to prevent** (D-31/D-32/D-350), so nothing guesses it: the operator working
#:     the gate reads it off the vendor console, and what they learn settles which of the
#:     three readings is true — which is the same observation that settles whether the
#:     per-agent `base_url` in `_llm_routing` is read at all.
#:
#: `Settings.bolna_llm_credential_name` names the FIRST of these, and its default moved
#: from the derived guess `AZURE` to this table's `AZURE_OPENAI_API_KEY` in the same
#: change. It stays a setting rather than becoming a constant because it remains the one
#: value an operator may have to correct against a live account without a deploy.
_AZURE_PROVIDER_KEYS: Final[dict[str, str]] = {
    "AZURE_OPENAI_API_KEY": "Your Azure API key",
    "AZURE_OPENAI_MODEL": "Your Azure OpenAI model",
    "AZURE_OPENAI_API_BASE": "Your Azure URL",
    "AZURE_OPENAI_API_VERSION": "Your Azure Model API version",
}

#: **EVERY CREDENTIAL-STORE ENTRY EACH DECLARED LEG NEEDS, PER LEG.** The store is a FLAT
#: `provider_name -> provider_value` map with no per-provider object (VERIFIED-OAS,
#: `references/openapi.yml` md5 5597f7da080d47564696bc05c12e9112; restated
#: VERIFIED-VENDOR-DOCS at `bolna-findings/mirror/pages/api-reference/providers/add.md`), so
#: "install this leg" is N separate `POST /providers` calls and the count differs per leg.
#:
#: **THE ASYMMETRY IS THE USEFUL PART AND IT IS THE VENDOR'S, NOT OURS.** VERIFIED-VENDOR-DOCS,
#: `providers.md` "LLMs" tab, under *"All these keys **must** be added for the respective
#: provider"*: Azure OpenAI takes FOUR entries (`:96-102`) because its endpoint, its
#: deployment and an api-version are all per-account; OpenAI takes ONE, `OPENAI` (`:87`); and
#: Google Gemini takes ONE, `GOOGLE` (`:105-109`). **Neither of the single-entry legs has a
#: base-URL field at all**, which is the store-side confirmation of what `GOOGLE_DIRECT_LEG`
#: says from the other direction — the engine's Gemini client is `genai.Client(api_key=...)`
#: and reads no endpoint of ours.
#:
#: ⚠ **ONE NAME IS DISPUTED AND IT IS NOT INVENTED HERE.** Two of the vendor's own pages
#: disagree about whether the OpenAI entry is `OPENAI` or `OPENAI_API_KEY`. The root
#: `providers.md` table — the page that carries the "all these keys must be added" sentence
#: and the one every other value here comes from — says `OPENAI`, so `OPENAI` is what this
#: table carries, and `Settings.bolna_llm_credential_name` remains the live override an
#: operator uses to correct it against a real account without a deploy. That is the same
#: shape D-417 left the Azure name in, and the same gate closes it: install, `GET /providers`,
#: place one call (OPERATIONS §2 gate 16f).
#:
#: ⚠ **THIS IS DATA FOR AN OPERATOR AND FOR THE GATE, NOT AN INSTALLER.** `set_llm_credential`
#: pushes exactly ONE entry — the API key — because that is the only one of the four whose
#: value this repository can produce without inventing something, and because a key is the
#: one value that must never be typed into a console by a human. On the two single-entry legs
#: that ONE is the whole of it, so those legs are fully installable by us and Azure's is not.
_LLM_PROVIDER_KEYS: Final[Mapping[LlmProvider, tuple[str, ...]]] = MappingProxyType(
    {
        "azure_openai": tuple(_AZURE_PROVIDER_KEYS),
        "openai": ("OPENAI",),
        "google": ("GOOGLE",),
    }
)

#: The ONE entry per leg that holds the secret — the entry `set_llm_credential` pushes.
#: Derived by position from the table above rather than retyped: on every leg the vendor's own
#: table lists the key first, and a second literal is how a corrected name gets applied in one
#: place and not the other (D-104's argument, one level down).
_LLM_CREDENTIAL_KEY: Final[Mapping[LlmProvider, str]] = MappingProxyType(
    {provider: names[0] for provider, names in _LLM_PROVIDER_KEYS.items()}
)


def llm_provider_keys(provider: LlmProvider) -> tuple[str, ...]:
    """Every credential-store entry `provider`'s leg requires, in the vendor's own names.

    **THE ONE READER OUTSIDE THIS MODULE IS AN OPERATOR RUNBOOK, WHICH IS WHY IT IS A
    FUNCTION AND NOT AN EXPORTED DICT.** What an operator has to install is a question about
    THIS engine, so it is answered by THIS adapter (hard rule 2) — a caller that imported the
    table could iterate it and start believing the names are portable across engines, which
    is exactly the coupling the rule forbids. Returning a tuple rather than the mapping keeps
    it read-only at the call site as well as at the definition.
    """
    return _LLM_PROVIDER_KEYS[provider]


#: THE REPLY BUDGET, in tokens, and the one place it is written.
#:
#: A cap is a SAFETY VALVE against a runaway generation, not a style control: brevity is the
#: script's job, and a ceiling that bites mid-sentence does not shorten a reply, it truncates
#: one — the TTS then speaks a fragment and hangs. The vendor's own default is 100
#: (VERIFIED-OSS, `bolna/models.py` `Llm.max_tokens`), which is close enough to a real reply
#: to bite; 400 is roughly ten times a spoken turn at `REFERENCE_CALL`'s shape.
_MAX_REPLY_TOKENS: Final = 400

#: WHAT WE SEND FOR `temperature` ON A MODEL THAT ACCEPTS A CHOICE.
#:
#: This agent reads a client's script and carries `TRUTHFUL_ANSWER_DIRECTIVE` underneath it;
#: the failure we care about is the model paraphrasing away a compliance sentence or
#: improvising a price, and low temperature is the setting that makes that rarest. Raising it
#: buys "sounds more natural", which is a prompt-and-voice problem on a phone call rather
#: than a sampling one. Written here rather than inherited because a vendor default is
#: somebody else's release note.
_DEFAULT_TEMPERATURE: Final = 0.1

#: The ONE temperature a GPT-5-series model accepts. VERIFIED-VENDOR-DOCS,
#: `bolna-findings/mirror/pages/providers/llm-model/openai.md:29`: *"GPT-5-series models
#: require `"temperature": 1`. Any other value is rejected with `400 For GPT-5 models,
#: temperature must be 1`, and the field defaults to `0.1` when omitted, so send it
#: explicitly."* Restated in their agent-create schema (`create.md:826-835`).
_GPT5_TEMPERATURE: Final = 1

#: The reasoning budget we ask for on a model whose reasoning tokens share the reply budget.
#:
#: `"none"` is accepted by `gpt-5.4-mini` (VERIFIED-VENDOR-DOCS, `openai.md:87`; VERIFIED-OSS,
#: `bolna/constants.py:323`) and is the vendor's own advice for live calls — *"For live calls,
#: stay at `none` or `low`. Each step up adds reasoning tokens before the first spoken word,
#: which lands directly in time-to-first-token"* (`openai.md:96`).
_NO_REASONING: Final = "none"


def _synthesizer_config(models: ModelConfig) -> dict[str, str]:
    """`provider_config` for the Sarvam voice provider: the model and the speaker, in the
    three keys the vendor's own example carries.

    VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`:
    `"provider_config": {"model": "bulbul:v3", "voice": "Ashutosh", "voice_id":
    "ashutosh"}`. Three keys for two facts — the speaker appears twice, once as a display
    name and once as an id — and BOTH are sent, because the example sends both and
    guessing which one their provider actually reads is the guess this whole change exists
    to stop making. `voice` is the capitalised form and `voice_id` the lowercase one, which
    is the only relationship the example shows; deriving it here rather than carrying a
    label through `ModelConfig` keeps the vendor's casing convention inside the adapter
    (hard rule 2).

    ABSENT KEYS RATHER THAN NULLS, and that is the pre-existing behaviour preserved: an
    agent with no voice configured used to send `{"voice": null}` and now sends `{}`. The
    engine picking its own speaker for an agent that named none is the same outcome; what
    changed is that we no longer assert a null where the vendor expects a string, which is
    the shape a schema-validating endpoint rejects outright.

    A voice id we do not recognise arrives here as a speaker with NO model
    (`voices.speech_for_voice_id`), so it is sent in `voice`/`voice_id` alone — byte for
    byte what a legacy `bulbul:v3` row sent before this split, rather than a silent
    upgrade to a model slot on a value the catalogue cannot vouch for.
    """
    config: dict[str, str] = {}
    if models.tts_model is not None:
        config["model"] = models.tts_model
    if models.tts_voice is not None:
        config["voice"] = models.tts_voice.capitalize()
        config["voice_id"] = models.tts_voice
    return config


def _read_speaker(voice_id: str | None, voice: str | None) -> str | None:
    """The SPEAKER an agent object came back holding, from whichever of the two keys the
    engine echoed.

    `voice_id` FIRST because it is the one we can compare without touching it: our
    speakers are lowercase by the vendor's own enum, so a `voice_id` echo equals
    `ModelConfig.tts_voice` exactly and the drift verdict is a string equality.

    `voice` is the fallback and it is LOWERCASED, which is a normalisation and is named as
    one. We send that key capitalised (`_synthesizer_config`), so lowering recovers the id
    for the shape we send; for anything else it is identity on a value already lowercase.
    Without it, an engine that echoes only the display name would report a mismatch on
    every agent forever — a false drift alarm being exactly what `_agent_models` must not
    manufacture. WHICH of the two their platform stores is not settled here; OPERATIONS §2
    gate 3 observes it on the first live publish, and reading both is what makes the answer
    arrive as data rather than as a reviewer's guess.
    """
    if voice_id:
        return voice_id
    if voice:
        return voice.lower()
    return None


def _llm_trap_settings(models: ModelConfig) -> dict[str, object]:
    """The `llm_config` keys that make THIS model's request legal, from its declared traps.

    **THE DEFECT THIS CLOSES.** `ModelConfig.llm_traps` and `LlmModelSpec.traps` recorded
    every one of these behaviours in prose, at a named line of the vendor's own docs, and
    NOTHING READ THEM AT RUNTIME. The body below this function sent `temperature: 0.1` and
    `max_tokens: 400` unconditionally, which is correct for every model that had ever been
    selectable and is a **400 at agent-create time** for the first GPT-5 model that becomes
    one. A trap catalogue nobody consults is documentation wearing the shape of a control.

    ⚠ **THE CREATE-TIME REFUSAL IS THE ONE THAT MATTERS, AND IT IS NOT THE ONE THE ENGINE'S
    SOURCE PROTECTS AGAINST.** The engine force-overwrites temperature on its own
    Responses-API path at CALL time, so a reader of its OSS could conclude the trap is
    already handled. It is not: `POST /agent/v2` validates the raw body, so an agent carrying
    `temperature: 0.1` on a GPT-5 model is REFUSED BEFORE IT EXISTS — no call is ever placed,
    and the failure surfaces as `engine_rejected` on a publish rather than as anything a
    client hears. Mitigating at publish is therefore both necessary and free.

    **KEYED ON THE TRAP, NOT ON THE PROVIDER OR ON A MODEL-NAME PREFIX**, and that is the
    design decision worth defending. A `startswith("gpt-5")` here would be wrong twice: on the
    Azure leg `llm_model` is a DEPLOYMENT ID an operator named freely, so the string carries
    no family at all (the engine has its own `canonical_model` heuristic for exactly this and
    it is a heuristic); and a future non-GPT-5 model with the same requirement would need a
    second branch. The catalogue already knows which models carry which traps, `in_call_llm`
    resolves them where the real model name is in scope, and this function renders each one
    into the vendor's keys. Hard rule 2 is kept on both sides: the trap NAMES are ours, and
    every JSON key below appears only in this file.

    **THE GEMINI TRAP APPEARS HERE AS AN ABSENCE, AND IT IS DELIBERATE ENOUGH TO NAME.** On
    `gemini-2.5-flash` / `-flash-lite` the engine sends `ThinkingConfig(thinking_budget=0)`
    unconditionally, and Google's own docs say `thinkingBudget: 0` disables thinking — so the
    trap is already eliminated and there is nothing for us to add. What we must NOT do is send
    a `thinking_budget` of our own: a non-zero value switches thinking back ON through the
    first branch of the engine's `_get_thinking_config`, and the key is an undocumented
    passthrough whose acceptance by the hosted API is unverified anyway. So the mitigation for
    this trap is to send nothing, which is what the empty arm below does — written as a
    comment rather than as no code at all, because "nothing here" and "nobody thought about
    it" are indistinguishable otherwise.
    """
    settings: dict[str, object] = {
        "max_tokens": _MAX_REPLY_TOKENS,
        "temperature": _DEFAULT_TEMPERATURE,
    }
    traps = frozenset(models.llm_traps)
    if "temperature-must-be-one" in traps:
        settings["temperature"] = _GPT5_TEMPERATURE
    if "max-tokens-becomes-max-completion-tokens" in traps:
        # ⚠ WE DO NOT RENAME THE KEY, AND THAT IS CORRECT RATHER THAN AN OMISSION. The
        # ENGINE performs the rename — `max_tokens_key = "max_completion_tokens"` on any
        # GPT-5-prefixed model (VERIFIED-OSS, `bolna/llms/openai_llm.py:163-171` @
        # `0172347b601e`) — and their published `SimpleLlmAgent` schema has `max_tokens` and
        # no `max_completion_tokens` at all, so sending the renamed key would be sending a
        # field their validator does not know. What is OURS is the CONSEQUENCE the rename
        # brings with it: reasoning tokens are drawn from the same budget as the reply, so a
        # cap sized for a spoken turn truncates the turn instead. We close that by asking for
        # no reasoning at all rather than by raising the cap, because a raised cap costs
        # tail latency on every turn while `reasoning_effort: "none"` costs nothing and the
        # vendor recommends it for live calls.
        #
        # SENT EXPLICITLY THOUGH IT IS ALSO THE ENGINE'S DEFAULT (`default_reasoning_effort`
        # returns the lowest the model accepts, which is `none` for `gpt-5.4-mini`). A
        # default is somebody else's release note — the same argument `_llm_routing` makes
        # for sending `provider` when omitting it would also have worked.
        settings["reasoning_effort"] = _NO_REASONING
    # `thinking-tokens-share-the-reply-budget` intentionally adds NOTHING — see the docstring.
    return settings


def _llm_routing(models: ModelConfig) -> dict[str, str]:
    """The `provider`/`family`/`base_url` keys for one config's LLM leg (D-410).

    THE ONLY PLACE a Calevate LLM leg becomes a Bolna provider name (hard rule 2).

    UNSET REPRODUCES THE BODY WE ALREADY SEND — `provider: "openai"`, `family: "openai"`
    — which is what every agent row in this repository still resolves to, because whether
    the hosted platform honours `provider`/`base_url` at all is what gate 16 was opened to
    ask. Changing the wire body for live agents on an unanswered vendor question is the
    opposite of what this change is for.

    THAT LINE SAID `{"family": "openai"}` WHEN IT ARRIVED, AND THAT WAS A SILENT REVERT.
    D-400 was written against a tree whose body carried no `provider` at all; D-355 landed
    `"provider": "openai"` in between, arguing that sending both fields spelling the same
    thing "is the only combination that cannot route somewhere we did not name" — an
    omitted `provider` merely DEFAULTS to `openai` on their side (`Llm.provider`,
    `bolna/models.py`), so dropping it swaps an explicit choice for a vendor default that
    can change in a release note. Preserving it is what this docstring's own
    do-not-change-live-bodies rule asks for once "before" means D-355 rather than D-283.

    **`"azure-openai"`, AND IT WAS `"azure"` UNTIL THE VENDOR'S OWN DOCS WERE READ.**
    Their `LLMProvider` enum carries BOTH spellings (VERIFIED-OSS, `bolna/enums.py`,
    recorded in `docs/vendor/bolna/oss-harvest.md`), so this was never "is the name
    right" but "which of two real names". D-410 picked `azure` on the strongest evidence
    then available — a published provider matrix reading `Azure OpenAI` and a live agent
    dropdown offering `azure` (browser sweep, 19 Aug 2026) — and both of those are
    HUMAN-READABLE LABELS, which is exactly the class of evidence that cannot settle a
    wire value. The docs settle it:

        VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers/llm-model/
        azure-openai.md` (fetched 20 Aug 2026, sha256
        faeda3c225e378c77f4f8db558f5f8329eb691968610af0b2105ff9e96c63f30), which states
        it twice — once as a copy-pasteable agent body under "Quick config":

            "llm_agent": {
              "agent_type": "simple_llm_agent",
              "agent_flow_type": "streaming",
              "llm_config": {
                "provider": "azure-openai",
                "model": "gpt-5.4-mini",
                ...

        and once in the "Key settings" table:

            | `provider` | string | `"azure-openai"` | Provider name |

    THAT IS A MACHINE-READABLE VALUE AGAINST TWO DISPLAY LABELS, and it is corroborated
    structurally: every sibling provider page states `provider` the same way in the same
    two places, and each of those values (`openai`, `anthropic`, `google`, `deepseek`,
    `openrouter`) is a name this repository already treats as the wire spelling. `azure`
    is not deleted from this comment — it stays as the ONE-STRING FALLBACK if the live
    platform turns out to accept the label and not the documented value, which is the
    same shape the previous ordering had, inverted by evidence rather than by taste.

    **WHY NOT `"custom"`, WHICH WAS THE BETTER-EVIDENCED VALUE AND IS NOW WORSE.**
    `provider: "custom"` is VERIFIED-OSS to construct `AsyncOpenAI(base_url=…,
    api_key=llm_key)` (`bolna/providers.py`, `bolna/llms/openai_llm.py`) — literally the
    client our v1 endpoint wants — and that is what the Vertex leg sent. It was abandoned
    because the route it depends on is the one in doubt: a custom model's key is read from
    the credential store, the 19 Aug 2026 sweep found no Provider Keys page and no
    `custom` entry in the dropdown, and gate 16c records that sweep. **The docs make that
    verdict stronger, not weaker.** `customizations/using-custom-llm.md` documents the
    whole custom-LLM flow — dashboard dialog and `POST /user/model/custom` alike — as
    taking exactly TWO values, an LLM URL and an LLM NAME, and `api-reference/user/
    add_model.md`'s OpenAPI body requires precisely `custom_model_name` and
    `custom_model_url`. **There is no credential field anywhere in that flow**, and the
    root `providers.md` Custom-LLM accordion is the only provider entry in the file with
    no key table at all. So the custom route has no documented way to carry an API key,
    which is the thing our Azure endpoint requires on every request.

    ⚠ **ONE HALF OF THE MARKED ASSUMPTION SURVIVES, AND IT IS NOW A NARROWER QUESTION:
    does their `azure-openai` provider READ the per-agent `base_url` we send here?** The
    field names their credential store wants are no longer in doubt (see
    `_AZURE_PROVIDER_KEYS` below), and one of them is `AZURE_OPENAI_API_BASE` — "Your
    Azure URL". So the endpoint may be a PROVIDER-level value on their side, in which
    case the `base_url` we put in `llm_config` is inert and the leg reaches our resource
    only because the credential store points there. Note what that costs and what it does
    not: the residency chain grows a link (a value in THEIR store, not just ours), and no
    read-back of ours can see it — `_agent_models` reads the endpoint off the agent, and
    an agent whose endpoint is ignored would read back exactly the same either way.
    `base_url` is still SENT, because their `SimpleLlmAgent` schema has the field
    (VERIFIED-OAS, `openapi.yml` md5 5597f7da080d47564696bc05c12e9112) and a value that
    is read is worth more than a key that is ignored is harmful. **OPERATIONS §2 gate
    16f** is what closes it: install the four keys, publish one agent with this body,
    read it back (gate 16), place one call, and confirm in the Azure portal's own metrics
    that the request arrived at OUR resource. If it does not, the fallbacks are `azure`
    and then `custom` — in that order, and each is one string.

    **THE DEPLOYMENT IS WHAT TRAVELS IN `model`, AND THE MODEL NAME NEVER LEAVES US.**
    Azure serves a model under a deployment ID the operator chose and the v1 surface
    addresses THAT, so `ModelConfig.llm_model` carries the deployment on this leg (its
    own field comment says so) and `_agent_body` puts it in the one model slot their
    schema has. `Settings.azure_openai_model` — which model that deployment was made from
    — is read by the cost model and by nothing on the wire. On every other
    OpenAI-compatible provider the two strings are the same string, which is exactly why
    a leg that sent the model name would look right and 404 at dial time.

    `family` is cosmetic on their side — declared on `Llm` and read by nothing
    (VERIFIED-OSS) — and stays `openai` on every arm because `openai` is what the wire
    format IS, whoever is serving it.

    **`provider: "google"` IS REFUSED, NOT MISSING**, and the entry survives D-410
    because the temptation does. Bolna ships a first-party Gemini provider needing one
    static key named `GOOGLE`, and it is `genai.Client(api_key=…)` against
    `generativelanguage.googleapis.com` — the AI Studio Developer API
    (`bolna/llms/gemini_llm.py`), a global host with no region in it and no field in
    which to ask for one (D-127, D-401). There is no Google LLM leg in this product any
    more, so the only way that value gets sent now is by somebody wiring one back.
    """
    if models.llm_provider is None:
        return {"provider": "openai", "family": "openai"}
    body = {"provider": _WIRE_PROVIDER[models.llm_provider], "family": "openai"}
    if models.llm_base_url:
        # Proven by `ModelConfig` itself to be an endpoint `azure_openai_base_url()`
        # could have emitted, on a single-DNS-label resource — which is the only reason
        # this line may hand a model endpoint to a third party without re-checking it.
        # What that proof does NOT cover is the REGION: Azure hides it inside the
        # resource, so `AZURE_LOCATION` is asserted by config and confirmed by a human in
        # the portal. Read that constant before trusting this line further than it goes.
        #
        # NOR DOES IT COVER WHETHER THIS KEY IS READ AT ALL on an `azure-openai` leg:
        # their documented Azure config carries no `base_url` row and their credential
        # store has `AZURE_OPENAI_API_BASE`. See this function's docstring — the value is
        # sent because their schema has the field and an ignored key costs nothing.
        body["base_url"] = models.llm_base_url
    return body


# The Python `%`-format specifier one AI-inferred parameter type maps to, so Bolna
# substitutes the LLM's extracted value with the right coercion (VERIFIED-VENDOR-DOCS,
# custom-function-calls.md:276-280: `%(name)s` / `%(name)i` / `%(name)f`). A boolean has
# no specifier of its own in their table, so it rides the string form — the value still
# arrives, as `"true"`/`"false"`, and our execution layer reads it back.
_PARAM_FORMAT: Final[dict[str, str]] = {
    "string": "s",
    "integer": "i",
    "number": "f",
    "boolean": "s",
}

# The JSON-schema scalar type Bolna's `parameters` block wants per our param type. Boolean
# is a real JSON-schema type the vendor lists (custom-function-calls.md:222-233); the
# format specifier above is the separate question of how the substituted value is coerced.
_PARAM_JSON_TYPE: Final[dict[str, str]] = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
}


def _one_api_tool(tool: ActionToolSpec) -> tuple[dict[str, Any], dict[str, Any]]:
    """Render one `ActionToolSpec` into (function-definition, execution-params) for Bolna.

    Split into the two members `ApiTools` carries — `tools` (the OpenAI function-calling
    definition the LLM reads) and `tools_params[name]` (the Bolna execution block with
    `key: "custom_task"`) — because the vendor's own schema splits them that way
    (`create.md:690-706`, `ApiTools.tools` + `ApiTools.tools_params` "keyed by the tool's
    name"). The single-object console shape (`{name, description, parameters, key,
    value}`, custom-function-calls.md:147-172) is that same data before the split.

    Only `ai` params enter the `parameters` schema; `context` params are substituted by
    Bolna and never asked of the model, so they appear only in `value.param`. STATIC
    bindings appear in NEITHER — they are applied on our side, never sent to the vendor.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    param_map: dict[str, str] = {}
    for p in tool.params:
        if p.fill == "ai":
            properties[p.name] = {"type": _PARAM_JSON_TYPE[p.type], "description": p.description}
            if p.required:
                required.append(p.name)
            param_map[p.name] = f"%({p.name}){_PARAM_FORMAT[p.type]}"
        else:  # context — a Bolna system variable like {from_number}
            # `context_ref` is validated non-empty for a context param by `ActionToolSpec`'s
            # builder in `apps/api/actions`; the `or ""` keeps mypy honest and renders an
            # empty substitution rather than the string "None" if one ever slipped through.
            param_map[p.name] = p.context_ref or ""

    definition: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }
    # `value` in the console schema; carried under the tool's name in `tools_params`.
    exec_params: dict[str, Any] = {
        "method": tool.method,  # POST — see `ActionToolSpec.method`
        "url": tool.url,  # OUR voice-runtime endpoint, never the client's API
        "param": param_map,
        # POST body is JSON, so the receiver (`tool_routes`) can `json.loads` it. Their own
        # POST examples set this explicitly; it is not implied
        # (docs/evidence/bolna-tools-integrations.md §2.1).
        "headers": {"Content-Type": "application/json"},
        # Mandatory and fixed — the vendor says so twice (tools-tab.md:58,
        # custom-function-calls.md:176). NOT the credential: the external API's real
        # credential lives in `integration_credentials` and is applied by our endpoint, so
        # no `api_token` is sent to Bolna at all (the feature's whole point).
        "key": "custom_task",
    }
    if tool.pre_call_message:
        exec_params["pre_call_message"] = tool.pre_call_message
    return definition, exec_params


def _api_tools(cfg: AgentConfig) -> dict[str, Any] | None:
    """The `tools_config.api_tools` block for an agent's in-call actions, or None.

    None (not an empty object) when the agent exposes no actions, so `_agent_body` omits
    the key entirely and an actionless agent's body is byte-for-byte what it was before
    this feature — the "an omitted key is a field left as it was" rule the rest of this
    module lives by, used deliberately here to make actions a pure addition.

    ⚠ MARKED ASSUMPTION — OPERATIONS §2 gate 18 (the custom-function envelope), and the
    open half is named in `docs/evidence/bolna-tools-integrations.md §1.5`. The per-tool
    shape (`name`/`description`/`parameters`/`key: custom_task`/`value`) and the format
    specifiers are VERIFIED-VENDOR-DOCS. What is NOT verified against a live account is the
    ENVELOPE: `ApiTools.tools` is declared `type: array` while its own description says it
    "needs to be a JSON string" (`create.md:693-700`), a self-contradiction the vendor has
    not resolved, and the OAS `oneOf` only enumerates `TransferCallTools`, never a custom
    function. We follow the description over the type — `tools` is emitted as a JSON STRING
    of the function-definition array, `tools_params` as an object keyed by tool name —
    because the sibling `TransferCallToolParams.param` resolves the same contradiction the
    same way (a stringified nested blob), which is the strongest signal available. Whoever
    runs gate 18 sends one and reads it back; if the array form is right instead, this ONE
    function changes and nothing above it does. Failing LOUD is the safe direction: a wrong
    envelope is a 422 at publish (surfaced by `create_agent`), not a silently toolless
    agent that a caller discovers mid-call.
    """
    if not cfg.action_tools:
        return None
    definitions: list[dict[str, Any]] = []
    tools_params: dict[str, Any] = {}
    for tool in cfg.action_tools:
        definition, exec_params = _one_api_tool(tool)
        definitions.append(definition)
        tools_params[tool.name] = exec_params
    return {
        # A JSON STRING, per the field's own description — see the gate-18 note above.
        "tools": json.dumps(definitions, separators=(",", ":")),
        "tools_params": tools_params,
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

#: What an engine region code may look like: `in`, `us`, and the longer cloud-style codes
#: (`ap-south-1`) a vendor might switch to without telling anyone. Anchored and narrow so
#: that a free-form string in that field is REFUSED rather than stored — the field is only
#: ever grouped by, so anything that is not an identifier is not useful and is a liability.
_REGION_CODE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,15}")
#
# ANNOTATED WITH OUR OWN DOMAIN TYPE, NOT LEFT TO INFERENCE, and the difference is where a
# mistake surfaces. Bare, this literal infers `dict[str, str]`, so `.get(..., "caller")`
# hands a plain `str` to `TranscriptTurn.speaker`, which is `Literal["agent", "caller"]`.
# Adding one wrong value here — `"operator": "supervisor"`, or a typo like `"agnet"` —
# would then be caught by NOTHING until Pydantic raised a `ValidationError` at runtime,
# inside the post-call pipeline, on a real customer's call. Typed, the same mistake is a
# red squiggle on the line that makes it, and the `.get` default is checked too.
#
# Worth recording because it is a gap between our two type checkers rather than a slip:
# `mypy --strict` passes this file BOTH ways (measured), and Pyrefly rejects only the
# untyped form. Annotating the constant satisfies both and depends on neither, which is the
# reason to fix the DEFINITION rather than `cast()` at the call site — a cast would silence
# the checker while leaving the map itself unguarded, which is the opposite of the point.
_SPEAKER_MAP: Final[dict[str, Speaker]] = {
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
#: What `CostBreakdown.fx_source` says when no published rate was in force and the
#: conversion fell back to the operator's configured `USD_INR_RATE`. A NAMED constant
#: because it is a value written into an append-only ledger and read back by whoever is
#: reconciling it — a string spelled twice is a string that will eventually be spelled
#: two ways.
_CONFIGURED_FX_SOURCE = "configured:usd_inr_rate"

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
#: **THE UNIT IS NO LONGER A DOCUMENT RECONCILIATION — THE VENDOR PUBLISHES A WORKED
#: EXAMPLE AND ONLY ONE READING SURVIVES IT (D-412).** Everything above this paragraph
#: settles "cents" by a PRECEDENCE RULE ("treat the YAML as canonical"), which is a claim
#: about which document to believe and not a claim about the world. Their hosted API
#: reference now prints an actual completed execution
#: (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md`, "Completed
#: execution example"):
#:
#:     "conversation_duration": 16,
#:     "total_cost": 3.23,
#:     "cost_breakdown": {"platform": 2, "network": 1,
#:                        "transcriber": 0.23, "llm": 0, "synthesizer": 0}
#:
#: Two facts fall out of it that no amount of reading the prose could give:
#:
#:   1. **`total_cost` IS the sum of the five legs** — 2 + 1 + 0.23 + 0 + 0 = 3.23,
#:      exactly. `_cost` has always converted the total and the legs on one divisor and one
#:      rate so a row's parts reproduce its whole; that was a design choice defended on
#:      first principles, and it is now the vendor's arithmetic as well.
#:   2. **The MAJOR-unit reading is arithmetically absurd, so it is dead.** 3.23 over 16
#:      seconds is 12.1 units per minute. Read as minor units that is 12.1 US cents/min —
#:      sitting right on top of the flat rate the vendor publishes for the Voice AI leg,
#:      "$0.06/min (₹5.52/min)" plus telephony and platform fee
#:      (`bolna-findings/mirror/pages/pricing/preferred-models.md`). Read as MAJOR units it
#:      is $12.11/min — about ₹1,060 a minute for an Indian phone call, three orders of
#:      magnitude off every price either party publishes. The example also decomposes the
#:      way per-minute billing does: `network: 1` and `platform: 2` are whole units on a
#:      16-second call because telephony is "billed by call duration (rounded to minutes)"
#:      (`bolna-findings/mirror/pages/pricing/call-pricing.md`), while `transcriber: 0.23`
#:      is fractional because STT is "rounded to seconds" on the same page.
#:
#: So `_ASSUMED_MINOR_UNITS_PER_MAJOR` keeps its value and CHANGES CLASS: the divisor is
#: observed, not adjudicated. That is what the name still says "ASSUMED" for — the
#: constant is one number carrying two claims, and only the first of them moved.
#:
#: STILL UNVERIFIED, and gate 7 now scores the CURRENCY alone rather than both halves:
#:   (a) the UNIT — **settled**, above. A live capture can only confirm it.
#:   (b) the CURRENCY — still named in NO first-party source. The OAS says "cents"; the
#:       pricing page quotes "$0.06/min" and "6¢/min", so every price Bolna publishes is
#:       primary in dollars and "cent" means the US one. That is an inference from a price
#:       list, not a statement about this FIELD, and their own pricing page introduces a
#:       THIRD word for it — "see how many **credits** the conversation consumed"
#:       (`call-pricing.md`) — which is a wallet unit that need not be one US cent. So the
#:       house assumption stands and stays an assumption.
#:       `CostBreakdown.currency_stated` carries the difference into every row so a later
#:       correction is re-derivable.
#:       **A NEIGHBOURING RESOURCE SHOWS THE HOUSE CONVENTION SPELLED OUT THREE WAYS, AND
#:       IT IS THE ONE ASSUMED HERE.** The phone-number schemas describe ONE price —
#:       $5/month — three times, and the three reconcile only under "cents = USD minor
#:       units, divisor 100":
#:           search.md:124-127  "Price of the number in USD."              example 5
#:           buy.md:113-117     "Price for the phone number in cents."     example 500
#:           get_all.md:103-106 "Monthly rental price of the phone number" example $5.0
#:       (`bolna-findings/mirror/pages/api-reference/phone-numbers/`, VERIFIED-VENDOR-DOCS,
#:       `docs/evidence/bolna-telephony.md` §3b.) It is the same word, on the same vendor,
#:       resolving to the same divisor AND to dollars. It bears on (b) rather than on (a):
#:       (a) is already settled above by a worked execution, and this is a DIFFERENT schema
#:       on a DIFFERENT endpoint, so reading it as proof about `AgentExecution.total_cost`
#:       would be the D-350 mistake this block exists to prevent. What it does is put a
#:       dollar sign next to the word "cents" in the vendor's own hand — which is the one
#:       thing the execution example could not do, since it prints a bare number.
#:       **It still does not close (b)**, because the wallet the number is billed against
#:       is the one whose unit "credits" leaves open, and gate 7 still has to read an
#:       invoice.
#:
#: ONE THING THE GATE MUST NOT ASSUME IT WILL SEE: **`AgentExecution` declares no
#: `currency` field at all.** The full property list on the page above is id, agent_id,
#: batch_id, conversation_duration, total_cost, status, error_message,
#: answered_by_voice_mail, transcript, created_at, updated_at, cost_breakdown,
#: telephony_data, transfer_call_data, batch_run_details, extracted_data, context_details
#: — and nothing else. `_cost` reads `currency`/`cost_currency` defensively, which costs
#: nothing and is right to keep, but against the documented shape those keys are absent,
#: `currency_stated` is always False, and the INR refusal branch below is UNREACHABLE
#: without the vendor adding an undocumented key. An INR-billed account therefore does not
#: meter nothing today — it meters on the USD assumption — and gate 7 cannot settle the
#: currency by reading a payload. It has to read an INVOICE.
#: WHAT A WRONG VALUE COSTS: every `usage_event` under-values the call by 100x, so no
#: spend cap ever arms and every margin panel reads near zero — and the 83x currency error
#: sits on top of that, in the same direction.
_ASSUMED_MINOR_UNITS_PER_MAJOR = Decimal(100)

#: The divisor PER CURRENCY, and the reason it has to be per currency rather than one
#: number (D-411).
#:
#: **THE UNIT AND THE CURRENCY COME FROM THE SAME DOCUMENT AND MUST BE READ TOGETHER.**
#: Everything argued above `_ASSUMED_MINOR_UNITS_PER_MAJOR` is argued in USD: the OAS
#: sentence that carries the divisor says "in **cents**", and a cent is USD's minor unit.
#: That OAS names no currency at all, which is exactly why `_ASSUMED_CURRENCY` is a house
#: assumption sitting beside it. The OTHER first-party document — `references/execution-
#: payload.md`, "Bolna cost in **account currency**" — is the ONLY one that lets the
#: currency vary, and in the same breath it says MAJOR units. So the two readings are:
#:
#:     OAS         : no currency named  ->  USD (assumed) , minor units , divisor 100
#:     payload.md  : account currency   ->  whatever it is, MAJOR units , divisor 1
#:
#: `_cost` used to take the currency from the second document and the divisor from the
#: first. A payload STATING `currency: INR` was converted at `rate = 1` (right, and the
#: reason that branch exists) and then divided by 100 anyway — so an account Bolna bills
#: in RUPEES metered every call at one hundredth of its cost, on rows stamped
#: `currency_stated=True`, i.e. the rows that look MORE trustworthy than the assumed ones.
#: Every spend cap then arms at 100x the real spend and every margin panel reads as though
#: the engine were free.
#:
#: **WHY INR HAS NO ENTRY, rather than an entry of 1 or of 100.** The vendor's own
#: tiebreak — `references/bolna-core.md`, *"Treat the YAML as the canonical schema if a
#: SKILL.md and the spec disagree"* — is what rescues the USD reading, and it does not
#: reach INR: the YAML's word is "cents", which is not a denomination an INR-billed
#: account has. Applying it to rupees is extrapolation from a sentence about dollars, and
#: the only sentence that speaks generally says major units. Nothing has ever observed
#: Bolna quoting INR at all.
#:
#: **A MISSING ENTRY MEANS REFUSE**, and `_cost` refuses. That is the rule this file
#: already applies one axis over (`_CONVERTIBLE_CURRENCIES`, "an absent cost is a visible
#: gap; a wrong one is not") and the two are deliberately separate constants because they
#: answer different questions: "can we price it in INR at all" (a rate) and "what unit is
#: their number in" (a denomination). A refusal costs one unpriced call and pages
#: `call_billable_without_cost` from `pipeline._meter`; a confident 1/100th reaches the
#: margin panel and every invoice with nothing downstream able to tell.
#:
#: THE DAY GATE 7 READS AN INR-BILLED EXECUTION this table gets one entry, which is a
#: one-line change HERE — beside `_ASSUMED_CURRENCY` and `_CONVERTIBLE_CURRENCIES`, which
#: are module constants for the same reason. A `Settings` field for this one and not for
#: those two would be a second way to state one class of assumption. Rows metered before
#: that flip are restated by `scripts/correct_cost_unit.py`, which is why the change is
#: safe to make: it is recoverable by append (hard rule 4), not by edit.
_MINOR_UNITS_PER_MAJOR: dict[str, Decimal] = {
    _ASSUMED_CURRENCY: _ASSUMED_MINOR_UNITS_PER_MAJOR,
}


def _to_inr(amount: Any, fx_rate: Decimal, *, minor_units_per_major: Decimal) -> Decimal | None:
    """One vendor cost figure → INR, quantized to the ledger's NUMERIC(12,4).

    `minor_units_per_major` is KEYWORD-ONLY AND UNDEFAULTED on purpose: the divisor is a
    property of the currency the figure is quoted in (`_MINOR_UNITS_PER_MAJOR`), and a
    default here is precisely how a divisor argued in USD reached a rupee figure. Every
    call site now has to say which unit story it is applying. Floats never touch money:
    the vendor value is stringified before it becomes a Decimal.
    """
    if amount is None:
        return None
    try:
        units = Decimal(str(amount))
    except (ArithmeticError, ValueError):
        return None
    major = units / minor_units_per_major
    return (major * fx_rate).quantize(_PAISE, rounding=ROUND_HALF_UP)


# --- is this number the right SIZE? (the alarm the unit assumptions needed) ------------
#
# Everything above decides the unit and the currency from documents. Both are still
# assumptions, and the way an assumption of this shape fails is not by a few percent — it
# fails by 100x (the divisor) or by 83-96x (the fx rate applied to a figure already in
# rupees). Neither shows up as an exception, a 4xx or a failing test: a call meters, a row
# lands, and every panel downstream is quietly wrong in the direction that flatters us.
# `CostBreakdown.currency_stated` records WHICH assumptions were used; nothing recorded
# whether the number they produced was the right SIZE.
#
# So the adapter now scores its own output against what a minute of a phone call costs
# this business, and pages when it is orders of magnitude out. This is a smoke detector,
# not a price check — the band is deliberately three orders of magnitude wide.
#
# WHERE THE BAND COMES FROM. BRD §"Unit economics": all-in variable cost ₹3.0-3.6/min on
# the launch stack, falling to ₹1.7-2.3/min in phase 2; telephony alone ₹0.4-0.9/min
# inbound and ₹0.6-1.8/min outbound; the competitor platform fees surveyed in the same
# section run ₹1.5-6/min. `cost.total_inr` is the ENGINE's charge to us, a subset of the
# all-in figure, so the honest expectation is roughly ₹0.5-6/min.
#
# The floor is ~5x below the cheapest plausible minute and the ceiling ~15x above the
# dearest. A tenfold vendor price rise still passes; a hundredfold unit error cannot. That
# asymmetry is the design — this alarm must never cry wolf about a re-pricing, because an
# alarm an operator learns to ignore is worse than no alarm, and it must never miss the
# one failure mode that motivated it.
_PLAUSIBLE_INR_PER_MIN_FLOOR = Decimal("0.10")
_PLAUSIBLE_INR_PER_MIN_CEILING = Decimal("100")

#: Below this, an implied per-minute rate is not a measurement of anything. A call that
#: rang, connected and dropped inside a few seconds is routinely billed at ZERO or at
#: whatever the vendor rounds a fraction of a second to — so its ₹/min lands far below the
#: floor while nothing is wrong, and this alarm would page on the noisiest, most common
#: call shape there is. An alarm that pages on healthy calls gets muted, and a muted alarm
#: is how the 100x error it exists for would go past.
#:
#: 30 s rather than 5 or 10 because the floor has to hold with room to spare: at half a
#: minute even a vendor minimum charge implies a rate inside the band, so what is excluded
#: is only the shapes where the charge is a stub rather than a price. The cost of the
#: exclusion is stated rather than hidden — a fleet metered 100x wrong on nothing but
#: sub-30-second calls would not page — and it is acceptable because such a fleet is not a
#: thing: the same divisor prices every call, and any call at all over 30 s pages.
_PLAUSIBILITY_MIN_DURATION_S = 30


def _implied_inr_per_minute(total_inr: Decimal, duration_s: int) -> Decimal:
    """What one minute of this call cost us, per the figure we just derived.

    `Decimal(60)` inline rather than a named constant: `billing/service.py` already owns a
    `_SECONDS_PER_MINUTE` for the money path, and a second module-level one here would be
    a name a reader has to check for divergence. This is arithmetic on a diagnostic, not a
    figure any ledger stores.
    """
    return total_inr * Decimal(60) / Decimal(duration_s)


def _check_cost_plausibility(
    cost: CostBreakdown | None, duration_s: int | None, *, engine_call_id: str
) -> None:
    """Page when a per-call cost is orders of magnitude away from what a minute costs.

    Silent on the three cases it cannot judge rather than guessing at them: no cost (that
    is `call_billable_without_cost`'s alarm, raised by `pipeline._meter` where
    `billable_ready` is known and this function's caller does not decide), no duration,
    and a call too short for the implied rate to mean anything. A zero total on a real
    call IS judged — it is the 100x error's limit case once quantization eats the rest.

    Ids only in the alert, never the payload (hard rule 6). The implied rate and the
    duration are OUR derived numbers, not client data.
    """
    if cost is None or duration_s is None or duration_s < _PLAUSIBILITY_MIN_DURATION_S:
        return
    per_min = _implied_inr_per_minute(cost.total_inr, duration_s)
    if _PLAUSIBLE_INR_PER_MIN_FLOOR <= per_min <= _PLAUSIBLE_INR_PER_MIN_CEILING:
        return
    alert(
        "CORE_LOGIC",
        "engine_cost_implausible",
        detail=(
            f"one call metered at INR {per_min} per minute over {duration_s}s, outside the "
            f"plausible band {_PLAUSIBLE_INR_PER_MIN_FLOOR}-{_PLAUSIBLE_INR_PER_MIN_CEILING}. "
            f"The adapter read the vendor figure as {cost.source_currency} "
            f"(stated by the payload: {cost.currency_stated}) at fx {cost.fx_rate}. "
            "A ratio near 100 is the minor-unit assumption; near 90 is the currency one."
        ),
        engine_call_id=engine_call_id,
    )


# --- did a SECOND call leg happen that we are not carrying? ---------------------------
#
# `BOLNA_CAPABILITIES.transfer=False`, so nothing this tree publishes configures a transfer
# tool and no execution we produce should carry a transfer leg. That is a statement about
# OUR publish path, not about the account — and the two can diverge without a deploy. The
# vendor's Transfer Call built-in is enabled from the agent's Tools tab
# (`bolna-findings/mirror/pages/agent-setup/tools-tab.md`: "Click **+ Add** next to any
# tool to enable it"), i.e. a console toggle a client or an operator can flip on an agent
# we published. The drift sweep proves the PROMPT still carries hard rule 5's directive;
# it does not enumerate the agent's tools.
#
# What that costs, if it happens silently, is exactly the two things this repo has hard
# rules about. The vendor models the transferred leg as its own object with its own
# fields — `TransferCallData` in the pinned OAS
# (`bolna-findings/mirror/pages/api-reference/agent/v2/get_agent_execution.md:270-328`):
#
#   * `recording_url` — "Recording URL for the transferred call", a SECOND recording of the
#     same caller. `pipeline`'s recording copy reads `ExecutionSnapshot.recording_url`,
#     which is `telephony_data.recording_url` and nothing else, so that audio is never
#     copied, never retained under our policy, and never reached by a DPDP erasure. The
#     vendor even serves it from its own route — `GET /recordings/transfer/{execution-id}`,
#     "Use the `transfer` variant if the call included a transfer leg"
#     (`bolna-findings/mirror/pages/changelog/may-2026.md:100-103`).
#   * `cost` — "Total cost incurred for this transferred call". A per-call cost outside
#     `total_cost`/`cost_breakdown` is a cost hard rule 7 never meters.
#
# So this is an ALARM and not a handler, deliberately. Carrying the leg properly needs new
# members on `ExecutionSnapshot` (a shared model), a decision on whether the transfer leg
# is separately metered and separately retained, and an answer to whether the recording
# notice a caller already heard covers a human they are handed to — none of which is a
# thing an adapter may decide on its own. OPERATIONS §2 gate 18 is where it is settled.
# Until then the failure mode this converts is the dangerous one: silent loss becomes a
# named page, on the first call that does it, from every path that snapshots an execution.
#
# HARD RULE 6 GOVERNS WHAT THIS MAY SAY. `TransferCallData` carries `to_number` and
# `from_number` in E.164 and a URL that resolves to caller audio; none of the three appears
# here. What is reported is the execution id, the leg's vendor status, and two booleans we
# derived — enough for an operator to know which execution to open and what is at stake.
def _check_transfer_leg(payload: dict[str, Any], *, engine_call_id: str) -> None:
    """Page when an execution carries a transfer leg this adapter drops on the floor."""
    leg = payload.get("transfer_call_data")
    if not isinstance(leg, dict) or not leg:
        return
    alert(
        "CORE_LOGIC",
        "engine_transfer_leg_unhandled",
        detail=(
            "this execution carries a transfer leg, which this adapter does not normalize: "
            f"vendor status {leg.get('status') or 'unknown'!r}, "
            f"second recording present: {bool(leg.get('recording_url'))}, "
            f"separate cost present: {leg.get('cost') is not None}. "
            "The leg's recording is NOT copied, retained or reachable by erasure, and its "
            "cost is NOT metered. An agent we published has had the Transfer Call tool "
            "enabled outside this tree — OPERATIONS §2 gate 18."
        ),
        engine_call_id=engine_call_id,
    )


# --- the semantic routing layer, which answers WITHOUT the model ----------------------
#
# **A SECOND PROMPT BYPASS, AND IT IS QUIETER THAN THE TRANSFER LEG.** `LlmAgentV2` carries
# `routes` — `{embedding_model, routes: [{route_name, utterances, response,
# score_threshold}]}` — described by the vendor as *"predefined routes that can be used to
# answer FAQs, or set basic guardrails, or do a static function call"*, matched on SEMANTIC
# SIMILARITY of what the caller said (default threshold 0.85) and answered with a STATIC
# STRING (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`, schemas `Routes`
# and `Route`).
#
# WHY THAT IS A COMPLIANCE PROBLEM AND NOT A FEATURE WE HAVE NOT ADOPTED. Hard rule 5's
# floor lives in the SYSTEM PROMPT (`TRUTHFUL_ANSWER_DIRECTIVE`), and every instrument this
# repository has for it — the publish read-back, `verification.judge`, the half-hourly drift
# sweep — scores the prompt. A route never consults the model at all: an utterance close
# enough to *"are you a robot"* is answered from config, so the directive that overrides
# every instruction above it is not in the path. **A console click can therefore make a
# published agent deny being an AI, and the prompt would still read back perfect.**
#
# WHY THIS IS AN ALARM ON THE READ-BACK AND NOT A FIELD IN `_agent_body`. We do not send
# `routes` and must not start: it is not nullable and has no default in their schema, so
# guessing `null` or `[]` risks 400ing every publish on this platform for a field we have no
# use for — the same reasoning that keeps `allow_multiple` and `ivr_config` off the inbound
# body. The exposure is a console edit, which is precisely what a READ-BACK sees and a
# request body cannot. So this is `_check_transfer_leg`'s shape, deliberately: one adapter,
# one way of reporting a vendor-side configuration nobody here decided.
#
# HARD RULE 6 GOVERNS WHAT IT MAY SAY. A route's `utterances` are what a caller says and its
# `response` is what the agent says back — conversation content. Neither is reported. What
# is reported is the agent ref, how many routes exist and their `route_name`s, which are
# operator-authored labels ("politics", "pricing") and the only handle for finding them in
# the console.
_ROUTE_NAME_SAMPLE = 5


def _check_semantic_routes(agent: dict[str, Any], *, ref: EngineAgentRef) -> None:
    """Page when a read-back agent carries routes that answer callers without the LLM."""
    config = agent.get("agent_config")
    source = config if isinstance(config, dict) else agent
    tasks = source.get("tasks")
    if not isinstance(tasks, list):
        return
    names: list[str] = []
    count = 0
    for task in tasks:
        tools = task.get("tools_config") if isinstance(task, dict) else None
        llm_agent = tools.get("llm_agent") if isinstance(tools, dict) else None
        block = llm_agent.get("routes") if isinstance(llm_agent, dict) else None
        # `Routes` is an OBJECT wrapping the array; a bare array is accepted too because a
        # dashboard-written agent is not obliged to match the create schema's nesting, and
        # reading only one shape would make the check silently blind to the other.
        rows = block.get("routes") if isinstance(block, dict) else block
        if not isinstance(rows, list):
            continue
        for row in rows:
            count += 1
            name = row.get("route_name") if isinstance(row, dict) else None
            if isinstance(name, str) and name and len(names) < _ROUTE_NAME_SAMPLE:
                names.append(name)
    if count == 0:
        return
    alert(
        "CORE_LOGIC",
        "engine_agent_semantic_routes_present",
        detail=(
            f"this agent carries {count} semantic route(s) that answer a caller from a "
            "static string without consulting the model, so the platform rules in its "
            "system prompt are not in the path for anything one of them matches — "
            "including a caller asking whether they are talking to an AI. Route names: "
            f"{', '.join(names) or 'unnamed'}. Nothing in this tree sends routes; they "
            "were added in the vendor console."
        ),
        engine_agent_ref=ref,
    )


#: How many languages one alert names before it stops listing them, for
#: `_ROUTE_NAME_SAMPLE`'s reason: the count is the severity and the codes are the handle
#: for finding them in the console. A language code is an ISO 639-1 label, not content
#: (hard rule 6) — what the entry's prompt SAYS is never reported here, and
#: `_agent_alternate_prompts` carries that to a verdict instead.
_MULTILINGUAL_SAMPLE = 5


def _check_multilingual_speech(agent: dict[str, Any], *, ref: EngineAgentRef) -> None:
    """Page when a console-added language brings its own VOICE or its own transcriber.

    **THE HALF OF THE + Add Language CLICK THAT `alternate_prompts` CANNOT CARRY.** That
    field answers the compliance question — does every prompt the engine will run carry
    `TRUTHFUL_ANSWER_DIRECTIVE` — and `verification.judge` refuses a publish when one does
    not. This is the OTHER thing the same click does, and nothing in `AgentSnapshot` has a
    place for it: `MultilingualLanguageEntry` declares `synthesizer` as **required** and
    `transcriber` as optional (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/
    api-reference/agent/v2/get.md:1064-1120`), so a language added in their console
    NECESSARILY carries a text-to-speech provider of its own, and their own worked example
    for the field puts `elevenlabs` on one language and `sarvam` on the other
    (`get.md:616-634`).

    TWO THINGS GO WRONG AT ONCE AND BOTH ARE INVISIBLE TODAY.

    * `_agent_models` reads the CONVERSATION TASK's `synthesizer`/`transcriber` and
      nothing else, so `holds_speech("tts")` answers about the base language and
      `judge`'s `voice_applied` reads True while a caller who switches language hears a
      voice this product never published — the ACCEPTED-versus-APPLIED gap that the
      snapshot exists to close, reopened one level down.
    * Speech is the leg that carries the AUDIO. `docs/legal` names Sarvam as the speech
      sub-processor; a console-added `elevenlabs` entry sends a client's callers' voices
      to a vendor no DPA of ours mentions, and it is a config change nobody here
      deployed. That is a disclosure question, which is why this pages rather than logs.

    NOT A REFUSAL, and the asymmetry with the prompt is deliberate. The floor in every
    prompt is ours, is a `Final`, and its absence is a proven compliance failure worth
    rolling a publish back for. A per-language voice is a legitimate thing for an operator
    to want the day this product supports multilingual agents; what is not legitimate is
    it happening where no instrument can see it. So the control is `_check_semantic_routes`'
    shape — one alarm, on the read-back path every publish and every half-hourly sweep
    already takes, naming the language codes and the providers so an operator can go and
    look.
    """
    overridden: list[str] = []
    providers: set[str] = set()
    for code, entry in _multilingual_languages(agent):
        legs = [entry.get(leg) for leg in ("synthesizer", "transcriber")]
        if not any(isinstance(leg, dict) for leg in legs):
            continue
        overridden.append(code)
        for leg in legs:
            provider = leg.get("provider") if isinstance(leg, dict) else None
            if isinstance(provider, str) and provider:
                providers.add(provider)
    if not overridden:
        return
    named = ", ".join(overridden[:_MULTILINGUAL_SAMPLE])
    alert(
        "CORE_LOGIC",
        "engine_agent_multilingual_speech_override",
        detail=(
            f"this agent runs a per-language speech configuration for {len(overridden)} "
            f"language(s) ({named}), so a caller who switches language is heard and "
            "answered on a transcriber and a voice this product never published and no "
            "read-back of ours scores — including, if the provider is not our own, by a "
            "speech vendor no client agreement names. Providers: "
            f"{', '.join(sorted(providers)) or 'unnamed'}. Nothing in this tree sends "
            "`multilingual_config`; it was added in the vendor console."
        ),
        engine_agent_ref=ref,
    )


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


def _first_e164(*candidates: Any) -> str | None:
    """The first candidate that is a non-blank string. Nothing is logged: every one of
    these values is a phone number (hard rule 6)."""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _party_numbers(
    payload: dict[str, Any], telephony: dict[str, Any], *, inbound: bool
) -> tuple[str | None, str | None]:
    """`(from_e164, to_e164)` for one execution, across every spelling the vendor prints.

    **THE SCHEMA AND THE VENDOR'S OWN WORKED EXAMPLES DISAGREE ABOUT WHERE THE TWO PHONE
    NUMBERS LIVE, AND WE READ ONLY THE SCHEMA'S ANSWER.** `TelephonyData` declares
    `to_number` ("Phone number of the recipient") and `from_number` ("Phone number of the
    sender") — `bolna-findings/mirror/pages/api-reference/executions/get_execution.md`
    lines 285-294 — and one payload example carries them there
    (`guides/post-call/list-phone-call-status.md:122-123`). But that example is
    schema-shaped: every property in schema order, `"id": 7432382142914`, `"transcript":
    "<string>"`. The THREE examples that read like captured traffic put the numbers at the
    TOP LEVEL under different names and carry NEITHER inside `telephony_data`:

      * `api-reference/executions/get_execution.md:41-42` — the "Completed execution
        example" for the exact endpoint `get_execution` calls:
        `"user_number": "+919876543210", "agent_number": "+918035739222"`, with a
        `telephony_data` holding only duration/recording/call_type/provider/hangup;
      * `quickstarts/api.md:246-247` — the same pair, same shape;
      * `quickstarts/batch.md:138` — `"user_number"` alone (no `agent_number`) on a batch
        execution row.

    **WHAT IT COSTS TO READ ONLY THE SCHEMA'S SPELLING, if the captures are the live
    shape: nothing raises and three obligations quietly stop working.**
    `ExecutionSnapshot.from_e164`/`to_e164` become permanently `None`, and downstream
    `apps/workers/optout.py` has no subject to add to DNC when a caller asks to be
    removed, `apps/api/compliance/export.py`'s erasure matches `calls` on those two
    columns and finds nothing, and the pipeline's redaction is handed an empty phone list.
    That is the shape of defect this reading exists to prevent: silently absent forever.

    **THE VENDOR'S NAMES ARE ROLE-BASED, WHICH IS WHY THE FALLBACK NEEDS THE DIRECTION.**
    `user_number` is the HUMAN end and `agent_number` ours, stated first-party outside any
    example: *"`recipient_data.user_number` — Referencing the **caller's** phone number"*
    (`graph-agent/variables.md:82`). Their `from`/`to` are dial-based. So the two systems
    only line up once you know which way the call went, and `call_type` is what says.
    Corroboration for the outbound arm is direct rather than inferred: the same literals
    appear as `recipient_phone_number: "+919876543210"` and `from_phone_number:
    "+918035739222"` in `api-reference/calls/make.md:18,38`, on an example whose
    `call_type` is `outbound`.

    ORDER IS THE POINT AND MAKES THIS PURELY ADDITIVE: the documented `telephony_data`
    keys win, then the top-level `from_number`/`to_number` spelling this adapter already
    tolerated, and only then the captured spelling. A payload of either shape gets the
    same answer it gets today; a payload of the captured shape stops answering `None`.
    No branch here can OVERWRITE a number the schema path already produced, so the worst
    case if the role mapping is ever wrong is a swap on payloads that today yield nothing
    at all — and the pilot closes it by reading one live INBOUND execution and saying
    which spelling carried the numbers (OPERATIONS §2, "where the two phone numbers
    live"; proposed as gate 29 in `docs/evidence/bolna-response-contract.md`, which is
    also where the three captures and the schema are set side by side).
    """
    documented_from = _first_e164(telephony.get("from_number"), payload.get("from_number"))
    documented_to = _first_e164(telephony.get("to_number"), payload.get("to_number"))
    human = payload.get("user_number")
    ours = payload.get("agent_number")
    # An inbound call is dialled BY the human TO our agent, so the roles swap sides.
    captured_from, captured_to = (human, ours) if inbound else (ours, human)
    return (
        documented_from or _first_e164(captured_from),
        documented_to or _first_e164(captured_to),
    )


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

#: The widest `from`..`to` span the listing will serve, and the reason the walk sends a
#: `to` at ALL (D-412).
#:
#: **WE WERE SENDING ONLY HALF OF A REQUIRED PAIR.** D-353 correctly moved the poller onto
#: `GET /v2/agent/{agent_id}/executions` and correctly spelled its lower bound `from` — and
#: stopped there, because the pinned OAS at `bolna-ai/skills@28b24aa` declares neither
#: bound required. The vendor's own hosted API reference does, twice over
#: (`bolna-findings/mirror/pages/api-reference/executions/get_executions.md`):
#:
#:   > The `from` and `to` query parameters are **required** to filter executions by date.
#:   > * Both `from` and `to` are **required** and must be passed **together**.
#:   > * The maximum allowed range between `from` and `to` is **7 days**.
#:
#: and its OpenAPI block on that page marks both `required: true`. A `from` with no `to`
#: is therefore a 400 on EVERY tick: `vendor_request` raises, `reconcile_executions`
#: reports `reconciliation_fetch_failed`, and the mechanism D-31 appointed the guarantee of
#: record never runs — the identical failure shape D-353 was opened to fix, one parameter
#: further along.
#:
#: **THE VENDOR CONTRADICTS ITSELF AND IT DOES NOT MATTER HERE, which is why this is not a
#: guess.** `bolna-findings/mirror/pages/guides/fetch-agent-executions.md` calls the same
#: query parameters "(all optional unless noted)", lists `from`/`to` with no note, and
#: prints a worked example that omits them. So one first-party page says required and
#: another says optional. Unlike the cost unit — where the two readings produce different
#: NUMBERS and a wrong pick corrupts the ledger, so the adapter refuses — both readings
#: here accept the same request: `from`+`to` is a valid filtered listing whether or not
#: the pair is mandatory. Sending both is the INTERSECTION of the two readings, not a bet
#: on one of them. Only omitting `to` depends on which page is right.
#:
#: SEVEN DAYS IS A REFUSAL, NOT A CLAMP. Silently narrowing a caller's window would make
#: `complete=True` a lie about a period nobody asked us to skip, and `ListingIncomplete
#: Reason` has no member for "our own bound moved the window" — its four values are all
#: claims about VENDOR truncation, and emitting one of them for our arithmetic would put a
#: word in an operator's alert that the runbook defines as something else. A caller asking
#: for a window the vendor will not serve is a bug in the caller, so it fails there with a
#: message naming the limit rather than becoming an opaque vendor 400.
_LISTING_MAX_WINDOW = timedelta(days=7)


class _AgentRoster(NamedTuple):
    """The account's agents, plus what the walk that found them may honestly claim.

    A bare `list[str]` is what this used to be, and it could not say "there may be more"
    — which is precisely how a truncated roster reported a complete listing (see
    `BolnaEngine._agent_refs`). The three fields travel together because
    `ExecutionListing` needs all three to be one coherent answer: the rows, how many
    responses were read to get them, and the reason the walk stopped if it stopped early.
    """

    refs: list[str]
    #: Responses read. At least 1 — the walk always issues its first page.
    pages_fetched: int
    incomplete_reason: ListingIncompleteReason | None


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

#: Field names that hold the agent's knowledge-base reference.
#:
#: **THE DOCUMENTED NAME WAS MISSING AND EVERY NAME HERE WAS A GUESS.** This set shipped
#: as "pure guesswork — nothing in their published documentation says the agent object
#: carries one at all", and that premise is retired: `AgentV2.tasks[].tools_config
#: .llm_agent.llm_config` is a `KnowledgebaseAgent` whose `vector_store.provider_config`
#: is a `LanceDbConfig` declaring exactly two — `vector_id` ("Vector id of a single
#: knowledgebase (legacy, use `vector_ids` for multiple)") and `vector_ids` ("Array of
#: vector ids to use multiple knowledgebases simultaneously")
#: (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:806-817,1164-1195`).
#:
#: NEITHER WAS IN THIS SET, and the adapter's own KB block already named both in prose
#: while looking for five other spellings — so `_agent_kb_refs` answered
#: `readable=False` on every agent that HAS a knowledge base, forever, and D-41's
#: question ("does deleting a knowledge base leave the agent pointing at a dead handle?")
#: could not be answered even from a payload that contained the answer. Note the shape of
#: that failure: not a wrong ref, an unreadable one — which is the honest verdict for the
#: wrong key and a useless one for the right question.
#:
#: The five guessed spellings stay. A guess that costs one set membership per key is not
#: worth removing, an account may still hold agents written by the older `rag_id` path
#: this adapter itself used, and `found_key` is a disjunction — an extra name can only
#: turn "we could not find it" into an answer, never the reverse. Present-but-empty is an
#: answer ("this agent references nothing"); absent everywhere is NOT, and
#: `_agent_kb_refs` reports the difference.
_AGENT_KB_REF_KEYS = frozenset(
    {
        "vector_id",
        "vector_ids",
        "rag_id",
        "rag_ids",
        "knowledgebase_id",
        "knowledge_base_id",
        "vector_store_id",
    }
)

#: How deep the KB-reference search walks. The bound stops a pathological or hostile
#: payload from turning a read-back into a hang.
#:
#: TEN RATHER THAN EIGHT, and eight was not "four or five levels" with room to spare — it
#: was EXACTLY the documented path with none. The reference lives at
#: `agent_config → tasks[] → [item] → tools_config → llm_agent → llm_config →
#: vector_store → provider_config → vector_ids`, which is depth 8 counting the list as a
#: level of its own (it is: `walk` recurses through it). So the bound landed on the last
#: dict it had to open, and one more envelope — the `agent_config` wrapper their write
#: path uses and their read schema does not, or a `provider_config` gaining a nested
#: block — would have made a present reference read as an ABSENT one. That is the same
#: silent-`readable=False` this key set was just widened to fix, arriving by arithmetic
#: instead of by spelling.
_AGENT_WALK_MAX_DEPTH = 10


# --- the knowledge base's wire constants (D-488) ---------------------------------
#
# EVERY VALUE HERE IS READ FROM THE HASH-PINNED MIRROR, page and line, because each one
# is either a limit the vendor enforces or a default that silently decides how a client's
# approved text gets cut up.

#: `POST /knowledgebase` `file`: *"PDF file to upload (max 20 MB)"*
#: (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:40-45`). Checked
#: BEFORE the upload so an oversized document is one named refusal rather than a vendor
#: 400 the ladder would treat as a transient fault and retry three times.
KB_MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

#: The three retrieval knobs, sent EXPLICITLY at their documented defaults
#: (`create.md:53-69`). Sent rather than omitted for `_agent_body`'s reason: a default we
#: do not send is a default the vendor may change under us, and these three decide what a
#: retrieved chunk CONTAINS. They are also the honest boundary of the approval gate — a
#: human approves the CONTENT, and these numbers are the only part of the chunking we
#: control. Where the vendor then places a boundary inside that content is theirs.
#:
#: ⚠ `kb/pdf_render.RECOMMENDED_CHUNK_SIZE` IS 768 AND THIS IS 512, ON PURPOSE. The
#: renderer lays out one approved chunk per block and our chunks are capped at 700
#: characters, so 512 splits every block if the unit is characters. The vendor never
#: states the unit for `chunk_size` (it does for `overlapping`), so 768 is right under
#: one reading and worse under the other, and neither has been observed from here. The
#: default stays until gate 43g reads back what the vendor actually stored. Move both
#: constants together or neither — a renderer laying out for one number while the wire
#: asks for another is the silent-drift failure this file exists to avoid.
KB_CHUNK_SIZE = 512
KB_OVERLAPPING = 128
KB_SIMILARITY_TOP_K = 15

#: `language_support`, and the enum has exactly ONE member: `multilingual`, which
#: *"enables cross-lingual retrieval across 100+ languages ... you can upload documents in
#: any language and query them in any language"*; omitting it selects *"the default
#: English-optimized configuration"* (`create.md:70-80`).
#:
#: WE SEND IT ALWAYS, AND FOR THIS PRODUCT THAT IS NOT A PREFERENCE. Calevate is
#: Telugu-first: the caller speaks Telugu, Saaras transcribes Telugu, and a client's
#: approved knowledge is routinely a mixture — Telugu prose with English product names,
#: prices and clinic hours, often typed in Latin script. An English-optimized index asked
#: a Telugu question is the failure that looks like working software: retrieval returns
#: the wrong chunk, the model answers confidently from it, and nothing in the call is
#: marked wrong.
#:
#: **IT CANNOT BE CHANGED AFTERWARDS.** *"Existing knowledge bases cannot be switched
#: between default and multilingual — you'll need to create a new one"*
#: (`bolna-findings/mirror/pages/getting-started/knowledge-base.md`). So this constant is
#: not a tunable: flipping it later does not migrate anything, it silently means every
#: knowledge base created before the flip is indexed one way and every one after it the
#: other, and the only fix is re-uploading every client's documents. Being wrong in the
#: multilingual direction costs an unmeasured amount of retrieval precision on
#: English-only content; being wrong in the other direction breaks the primary language of
#: the product. ⚠ WHAT IS NOT KNOWN is the size of that first cost — the vendor publishes
#: no comparison — and no number is invented for it here (OPERATIONS §2 gate 43f).
KB_LANGUAGE_SUPPORT = "multilingual"

#: How long `attach_kb` waits for `processing` → `processed`, and how often it looks.
#:
#: THE WAIT EXISTS BECAUSE THE CREATE RESPONSE IS NOT THE ANSWER. `POST /knowledgebase`
#: returns `status` *"Initially the status would be `processing`"* and NO `vector_id`
#: (`create.md:105-127` — the response's declared properties are `rag_id`, `file_name`,
#: `source_type`, `status`, `language_support`); the `vector_id` an agent must reference
#: appears only on `GET /knowledgebase/{rag_id}`
#: (`.../get_knowledgebase.md:81-93`). So an adapter that returned on the create has
#: uploaded a document nothing can retrieve from.
#:
#: THE BUDGET IS OURS AND IS AN ESTIMATE, NOT A VENDOR FIGURE — nothing published says how
#: long ingestion takes for a document of our size. Three minutes is chosen against what
#: the caller does with a timeout: `publish_source` compensates by deleting the half-made
#: knowledge base and refusing, so an over-short budget costs a retry and an over-long one
#: holds a publish request open. It is deliberately far longer than any other vendor call
#: in this adapter, which is why it is a named constant instead of `REQUEST_TIMEOUT_S`.
KB_READY_TIMEOUT_S = 180.0
KB_READY_POLL_INTERVAL_S = 2.0

#: `status` on a knowledge base. `processing` and `processed` are declared on every one of
#: the three read/write schemas; `error` is declared on the CREATE response only
#: (`create.md:110-113`) and is absent from `Knowledgebase` (`get_knowledgebase.md:87-92`,
#: `get_knowledgebases.md:95-101`) — which is a gap in their spec rather than a promise
#: that a read can never report one, so both are handled wherever a status is read.
KB_STATUS_PROCESSED = "processed"
KB_STATUS_PROCESSING = "processing"
KB_STATUS_ERROR = "error"


def _kb_filename(source: KBSourceRef) -> str:
    """The `file_name` the vendor echoes back and shows in its console.

    OURS, NOT THE CLIENT'S, AND DELIBERATELY DULL. The vendor stores this string, returns
    it on every listing row and prints it in a dashboard we do not control, so it is a
    place caller data could leak by accident (hard rule 6). `kb_id` is a uuid of ours and
    the title is not used at all -- a client's own source title can carry a person's name
    ("Ravi's clinic timings") and there is no reason a vendor console needs it.
    """
    return f"calevate-kb-{source.kb_id}.pdf"


#: Their status vocabulary -> ours. See `list_account_kb` on why `error` is mapped from a
#: listing whose own enum does not declare it.
_KB_STATES: dict[str, AccountKBState] = {
    KB_STATUS_PROCESSED: "ready",
    KB_STATUS_PROCESSING: "pending",
    KB_STATUS_ERROR: "failed",
}

#: The file name `_kb_filename` writes, read back. Anchored at both ends: a name that
#: merely CONTAINS a uuid is not one this code wrote, and treating it as ours would
#: attribute a stranger's upload to one of our sources.
_KB_FILENAME_RE = re.compile(r"^calevate-kb-([0-9a-fA-F-]{32,36})\.pdf$")


def _source_id_from_kb_filename(file_name: Any) -> UUID | None:
    """Our source id out of the vendor's `file_name`, or None if it is not ours.

    THE ONLY ATTRIBUTION AN UNRECORDED OBJECT HAS. Every other field on their listing row
    belongs to them; this one we chose, and it is what makes a knowledge base created by a
    publish whose transaction rolled back attributable rather than anonymous for ever.

    None is returned for anything that does not match EXACTLY: an upload made by hand in
    the vendor console, a name from a build older than this convention, or a value that
    looks close. `kb/orphans.py` treats those as unclaimed and asks a human, which is the
    only safe verdict — an object we cannot attribute may still be a client's document.
    """
    if not isinstance(file_name, str):
        return None
    matched = _KB_FILENAME_RE.match(file_name)
    if matched is None:
        return None
    try:
        return UUID(matched.group(1))
    except ValueError:
        # A 32-36 character hex-and-dash string that is not a uuid. Their store would
        # happily hold one; our sources are uuid7 and nothing else, so this is not ours.
        return None


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


def _multilingual_languages(agent: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """`(language code, entry)` for every language an ENABLED multilingual config holds.

    ONE TRAVERSAL FOR THE TWO QUESTIONS ASKED OF THIS BLOCK — which prompts run
    (`_agent_alternate_prompts`) and which SPEECH legs run (`_check_multilingual_speech`).
    They were one function's worth of walking written twice until this existed, and the
    two would have drifted at the `enabled` test, which is the half that decides whether
    any of it is in the path at all.

    `enabled` GATES IT, because the vendor says it does: *"Must be `true` for multilingual
    to take effect. When `false` or omitted, the agent runs single-language and this object
    is ignored"* (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/api-reference/agent/v2/
    get.md:594-599`). A stored-but-disabled config is not running, and convicting an agent
    over one would be a refusal an operator cannot act on.

    Sorted by code within each task so the result is stable across read-backs: it reaches a
    verdict and a log line, and a dict-order-dependent one would make two identical sweeps
    look like a change.
    """
    root = agent.get("agent_config") if isinstance(agent.get("agent_config"), dict) else agent
    tasks = root.get("tasks") if isinstance(root, dict) else None
    if not isinstance(tasks, list):
        return []
    found: list[tuple[str, dict[str, Any]]] = []
    for task in tasks:
        tools = task.get("tools_config") if isinstance(task, dict) else None
        block = tools.get("multilingual_config") if isinstance(tools, dict) else None
        if not isinstance(block, dict) or block.get("enabled") is not True:
            continue
        languages = block.get("languages")
        if not isinstance(languages, dict):
            continue
        for code in sorted(languages):
            entry = languages[code]
            if isinstance(entry, dict):
                found.append((code, entry))
    return found


def _agent_alternate_prompts(agent: dict[str, Any]) -> tuple[str, ...]:
    """Every OTHER system prompt this agent will run, read at the documented path.

    **THE SECOND PROMPT BYPASS, AND UNLIKE THE SEMANTIC ROUTES THIS ONE IS SCORABLE.**
    `_agent_body` sends `multilingual_config: None` on every write and the comment there
    explains why — a per-language prompt carries none of `TRUTHFUL_ANSWER_DIRECTIVE`, so
    an agent with multilingual on would run, for every language but the base one, a prompt
    with no compliance floor in it. That defends the WRITE. It does nothing about the
    console, which ships **+ Add Language** as one click on the Agent Tab with a prompt
    editor per language (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/agent-setup/
    agent-tab.md:5,41-70`) — and a console edit is precisely what a read-back sees and a
    request body cannot.

    Until this function existed, that click was invisible to every instrument in this
    repository: `_agent_system_prompt` reads `agent_prompts.task_1.system_prompt`,
    `verification.judge` scored the floor off exactly that, and both the publish read-back
    and the half-hourly drift sweep answered `truthful_answer_applied=True` about a prompt
    that is not the one in use for the language the caller switched into. A caller
    speaking Telugu to an agent whose Telugu tab was written in the console could be told
    it is a human, with every gate green.

    THE PATH IS THE VENDOR'S OWN: `tasks[].tools_config.multilingual_config`, whose
    `languages` maps a language code to a `MultilingualLanguageEntry` carrying
    `system_prompt` — *"Prompt activated while the agent speaks this language"*
    (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:229-237,589-660,1064-1120`).

    `enabled` gates it — argued at `_multilingual_languages`, which does the walking for
    this function and for the speech check beside it.

    RETURNS ONLY WHAT WAS POSITIVELY FOUND, with no `readable` twin: an empty tuple means
    "no other prompt is in the path", which is the true answer for every agent this tree
    publishes. An entry with no `system_prompt` of its own falls back to the base prompt
    on their side, so it is not a gap and is not reported.
    """
    prompts: list[str] = []
    for _code, entry in _multilingual_languages(agent):
        prompt = entry.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            prompts.append(prompt)
    return tuple(prompts)


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


def _provider_of_endpoint(base_url: str) -> LlmProvider | None:
    """Which declared leg's builder could have emitted this read-back endpoint, or None.

    THE READ-BACK'S RESIDENCY CHECK, AND IT COVERS EVERY LEG THAT HAS AN ENDPOINT — not
    only Azure. The endpoint is what identifies a leg that names one: an `azure_openai`
    leg names ONE resource (the one in `AZURE_LOCATION`), an `openai` leg pins the `us`
    data-residency host in the authority — so an agent aimed at somebody else's resource,
    or at OpenAI's region-less `global` host, is exactly the drift this read exists to
    catch.

    RECOGNISING ONLY AZURE WAS A LIVE DEFECT ONCE THE OPENAI LEG SHIPPED AN ENDPOINT
    (D-456). It was correct while Azure was the only leg with a base URL (D-410): the whole
    of `_agent_models`'s residency story was "some Azure resource, and is it OURS". But
    `in_call_llm` now sends `openai_base_url()` on a `gpt-5.4-mini` agent and `_llm_routing`
    puts it on the wire, so a legitimately-published OpenAI-direct agent read back through
    the Azure-only predecessor logged `engine_llm_endpoint_unrecognised` against
    `us.api.openai.com` and DISCARDED it — a false drift alarm on our own endpoint, which is
    how an operator learns to ignore the real one, and the loss of the very residency proof
    this read exists to confirm (the `us` host is that proof — see `openai_base_url`).

    THE `google` LEG NEVER REACHES HERE, and that is not a gap. Its client is built from an
    API key alone and reads no base URL of ours (`GOOGLE_DIRECT_LEG`), so a google agent
    carries no endpoint — `_agent_models` finds no `base_url`, this function is not called,
    and `llm_base_url` stays None with nothing to verify.

    OpenAI is an EXACT match against the one endpoint its builder emits — there is only one
    OpenAI-direct endpoint this product may address. Azure is asked of its own validator,
    because that leg's endpoint is per-resource and there is nothing to compare a single
    label against without it (`ModelConfig._llm_endpoint_is_coherent`).
    """
    if base_url == openai_base_url():
        return "openai"
    try:
        ModelConfig(llm_provider="azure_openai", llm_base_url=base_url)
    except ValidationError:
        return None
    return "azure_openai"


def _agent_models(agent: dict[str, Any]) -> tuple[ModelConfig | None, bool]:
    """`(selections, readable)` — the BYOK choices the agent is RUNNING, in our terms.

    The read half of the `EngineCapabilities` BYOK claim (D-93). `update_agent` sends
    `llm_agent.model`, `synthesizer.provider`/`provider_config.{model,voice,voice_id}` and
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
    # THE CONVERSATION TASK, NOT WHICHEVER TASK IS FIRST. `TasksConfigV2.task_type` is an
    # enum of `conversation` / `extraction` / `summarization`
    # (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:109-116`) and every task
    # carries its OWN required `tools_config` with its own `llm_agent`, `synthesizer` and
    # `transcriber`. `_agent_body` sends exactly one task and it is the conversation one,
    # so index 0 is right for every agent this tree publishes — and wrong the moment a
    # console adds a second, because an extraction task's LLM is not the model the caller
    # is talking to and its synthesizer is not the voice they hear. That would be a
    # CONFIDENT WRONG answer with `readable=True` beside it, which the docstring above
    # names as the one outcome this function must never produce; index 0 stays as the
    # fallback for a task list that declares no types at all, where a wrong guess is the
    # only guess available and `readable` is the honest part.
    chosen = next(
        (
            task
            for task in tasks
            if isinstance(task, dict) and task.get("task_type") == "conversation"
        ),
        tasks[0],
    )
    tools = chosen.get("tools_config") if isinstance(chosen, dict) else None
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

    # WHERE THE LLM LEG IS RUNNING, read back rather than assumed (D-400, re-aimed by
    # D-410, widened to the multi-provider legs by D-456). THE ENDPOINT IS WHAT IDENTIFIES
    # A LEG THAT NAMES ONE, AND THE PROVIDER NAME ALONE DOES NOT. Under Vertex both of our
    # arms rendered to `"custom"`, so there was no choice; now three legs are declared and
    # two of them build an endpoint whose region is the whole of the residency claim —
    # `azure-openai` points at SOME Azure OpenAI resource (our guarantee is about ONE, in
    # `AZURE_LOCATION`), and `openai` at OpenAI direct (our guarantee is the `us` host in
    # the authority). An agent aimed at somebody else's resource, or at OpenAI's region-less
    # `global` host, is exactly the drift a read-back exists to catch — and only the
    # endpoint carries that fact, which is why `_provider_of_endpoint` reads the endpoint
    # rather than trusting the `provider` string beside it. The `google` leg is the one
    # exception, and it proves the rule: it builds NO endpoint (its client is an API key
    # alone), so there is no host to identify it by and none to verify — its only handle on
    # the agent object is the `provider` string, read back below when no base URL is present.
    #
    # DUAL-SPELLED FOR THE SAME REASON `llm_model` IS, and it did not arrive that way.
    # D-400 wrote this read against a FLAT `llm_agent` because the branch it came from
    # also wrote a flat body; D-355 is what the write path actually does, and
    # `_llm_routing`'s keys go INSIDE `llm_config`. Reading only the flat key would
    # report every v2 agent's endpoint as ABSENT — the same confident-wrong answer the
    # paragraph above rejects, on the one field that carries residency.
    #
    # WHICH DECLARED LEG'S ENDPOINT THIS IS — azure_openai OR openai — via the ONE
    # predicate that knows both (`_provider_of_endpoint`). A base URL that matches no leg
    # this product builds is reported as no provider and LOGGED, never normalised away and
    # never raised: letting the ValidationError escape would turn a read-back into a failed
    # publish, the one shape D-260 says a snapshot must never take, and a recognised-but-
    # wrong endpoint is exactly the drift the log line exists to surface. It carries the
    # HOST only — a vendor's endpoint, not transcript text, and the whole of what an
    # operator needs to see that something is off.
    base_url = leaf("llm_agent", "llm_config", "base_url") or leaf("llm_agent", "base_url")
    provider_wire = leaf("llm_agent", "llm_config", "provider") or leaf("llm_agent", "provider")
    llm_provider: LlmProvider | None = None
    if base_url is not None:
        llm_provider = _provider_of_endpoint(base_url)
        if llm_provider is None:
            log.warning(
                "engine_llm_endpoint_unrecognised",
                extra={"engine": "bolna", "host": urlsplit(base_url).netloc},
            )
            base_url = None
    elif provider_wire is not None:
        # A LEG WITH NO IN-CALL ENDPOINT (google) can only be identified by the `provider`
        # string the engine echoes — there is no host to read a region off, and none to
        # verify — so it is reverse-mapped from the vendor's wire value. Accepted ONLY for a
        # leg whose in-call endpoint is not ours, and both halves of that guard matter: an
        # endpoint leg seen with no base URL cannot be reported (its `ModelConfig` requires
        # one — the construction below would raise), and the UNSET/passthrough body also
        # carries `provider: "openai"` with no base URL (`_llm_routing`), which must read
        # back as NO leg rather than as OpenAI-direct.
        #
        # ⚠ `not in_call_endpoint_is_ours`, NOT `builder is None` (D-478). The google leg
        # NOW CARRIES A BUILDER — but it is the DASHBOARD copilot's `google_openai_compat_
        # base_url`, and the in-call google leg still names no endpoint, so `builder is None`
        # stopped separating it from azure/openai. `in_call_endpoint_is_ours` is the property
        # that still does: False for google, True for the two endpoint legs, so both halves
        # above hold unchanged. Same line `ModelConfig` and `service.in_call_llm` moved to.
        # The `provider` echo is the same evidence class as the `model` and `base_url` reads
        # above — their server returns the stored agent object (`get_agent`'s docstring) —
        # and is settled against a live account by the same gate.
        mapped = _OUR_PROVIDER.get(provider_wire)
        if mapped is not None and not DECLARED_POSTURE.leg(mapped).in_call_endpoint_is_ours:
            llm_provider = mapped
    return (
        ModelConfig(
            stt_provider=leaf("transcriber", "provider"),
            stt_model=leaf("transcriber", "model"),
            llm_model=llm_model,
            llm_provider=llm_provider,
            llm_base_url=base_url,
            tts_provider=leaf("synthesizer", "provider"),
            tts_model=leaf("synthesizer", "provider_config", "model"),
            # BOTH SPEAKER KEYS, via one reader — see `_read_speaker`. Reading `voice`
            # alone (which is what this line did while `voice` held a MODEL) would compare
            # a display name against our lowercase speaker id and report drift on every
            # agent; reading `voice_id` alone would report None on an engine that echoes
            # only the other one.
            tts_voice=_read_speaker(
                leaf("synthesizer", "provider_config", "voice_id"),
                leaf("synthesizer", "provider_config", "voice"),
            ),
        ),
        True,
    )


def _agent_kb_refs(agent: dict[str, Any]) -> tuple[list[EngineKBRef], bool]:
    """`(handles, readable)` — the agent's own knowledge references, and whether we
    actually found the field that would hold them.

    `readable=False` is the honest answer when we cannot see the place a reference would
    live, and it is NOT the same as an empty list: D-41 asks whether a deleted knowledge
    base leaves the agent pointing at a dead handle, and "we could not find the field"
    recorded as "the reference was cleared" would close the question in the direction that
    adds no work to our code, on no evidence.

    **WHAT COUNTS AS "WE CAN SEE IT" CHANGED WHEN THE LOCATION WAS READ (D-488), AND THIS
    IS THE HALF THAT MATTERS.** It used to be "some candidate key is present somewhere",
    which meant an agent with NO knowledge — no `vector_store` block at all — read as
    `readable=False`, i.e. "cannot tell". That is exactly the state a successful
    `detach_kb` leaves behind, so the one question D-41 asks could never be answered YES:
    an adapter that correctly cleared the reference was indistinguishable from one that
    could not find it.

    Now the test is whether `llm_config` — the block the reference lives INSIDE
    (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:806-817,1164-1195`) — is
    present. If it is, an absent `vector_store` is a fact about the agent: it references
    nothing. If it is not, the payload is not a shape we understand and "cannot tell"
    remains the only honest answer. The tolerant walk stays alongside for the older
    spellings this adapter itself once wrote, and can only ever turn a "cannot tell" into
    an answer.
    """
    handles: list[EngineKBRef] = _agent_vector_ids(agent)
    found_key = bool(_llm_configs(agent))

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


def _llm_configs(agent: dict[str, Any]) -> list[dict[str, Any]]:
    """Every task's `llm_config` block, at the DOCUMENTED path and nowhere else.

    Separate from `_agent_kb_refs`'s tolerant walk on purpose, and the two are not
    duplicates. That one answers "is there a knowledge reference anywhere in this
    payload", tolerantly, because its job is to avoid reporting a dangling handle as
    cleared. THIS one answers "where do I WRITE the reference", and a write may not be
    tolerant: guessing a location would put `vector_ids` somewhere the engine ignores,
    which is a silent no-attach — the exact defect class D-354 found.

    The path is `agent_config.tasks[].tools_config.llm_agent.llm_config`
    (`bolna-findings/mirror/pages/api-reference/agent/v2/update.md:243-247,532-551`),
    with `agent_config` present on the WRITE body and absent from the READ schema
    (`.../get.md:54-97` declares `tasks` at the top level), so both are accepted.
    """
    root = agent.get("agent_config") if isinstance(agent.get("agent_config"), dict) else agent
    tasks = root.get("tasks") if isinstance(root, dict) else None
    if not isinstance(tasks, list):
        return []
    configs: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        tools = task.get("tools_config")
        llm_agent = tools.get("llm_agent") if isinstance(tools, dict) else None
        llm_config = llm_agent.get("llm_config") if isinstance(llm_agent, dict) else None
        if isinstance(llm_config, dict):
            configs.append(llm_config)
    return configs


def _agent_vector_ids(agent: dict[str, Any]) -> list[EngineKBRef]:
    """The vector ids this agent references, read at the documented path.

    Order-preserving and de-duplicated: the list goes back on the wire on the next write,
    and a set would reshuffle it on every publish, turning a no-op update into a diff
    nobody made.

    `vector_id` (singular) is read as well as `vector_ids`. Their own schema calls it
    *"Vector id of a single knowledgebase (legacy, use `vector_ids` for multiple)"*
    (`update.md:1224-1233`), so an agent configured in their console — or by an older
    build of ours — can be carrying one, and a preserve-on-update that only understood
    the plural would DELETE it.
    """
    handles: list[EngineKBRef] = []
    for llm_config in _llm_configs(agent):
        store = llm_config.get("vector_store")
        provider_config = store.get("provider_config") if isinstance(store, dict) else None
        if not isinstance(provider_config, dict):
            continue
        raw = provider_config.get("vector_ids")
        candidates = raw if isinstance(raw, list) else []
        single = provider_config.get("vector_id")
        if isinstance(single, str) and single:
            candidates = [*candidates, single]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate and candidate not in handles:
                handles.append(candidate)
    return handles


def _apply_vector_store(body: dict[str, Any], vector_ids: Sequence[EngineKBRef]) -> None:
    """Put the knowledge linkage into an agent body we are about to WRITE.

    TWO FIELDS MOVE TOGETHER AND THAT IS THE WHOLE FUNCTION. `vector_store` lives on the
    `KnowledgebaseAgent` arm of `llm_config`'s `oneOf`, and the arm is selected by
    `llm_agent.agent_type` (`update.md:532-551,848-860`). Writing `vector_store` while
    leaving `agent_type: "simple_llm_agent"` posts a body whose union arm has no such
    property — at best ignored, which is a silent no-attach.

    Empty restores the simple arm rather than sending `vector_ids: []`: an agent with no
    knowledge is a `simple_llm_agent`, which is what `_agent_body` already builds, and a
    knowledgebase agent pointed at nothing is a shape nothing documents.
    """
    for task in body["agent_config"]["tasks"]:
        llm_agent = task["tools_config"]["llm_agent"]
        if not vector_ids:
            llm_agent["agent_type"] = "simple_llm_agent"
            llm_agent["llm_config"].pop("vector_store", None)
            continue
        llm_agent["agent_type"] = "knowledgebase_agent"
        llm_agent["llm_config"]["vector_store"] = {
            # `provider` has one enum member, `lancedb`, and it is also the declared
            # default (`update.md:1205-1211`). Sent explicitly for `_agent_body`'s
            # standing reason: a default we do not send is one the vendor may move.
            "provider": "lancedb",
            "provider_config": {"vector_ids": list(vector_ids)},
        }


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


# --- what the engine's own pipeline cost, per turn -------------------------------------
#
# `latency_data` on Get Execution. VERIFIED-VENDOR-DOCS throughout:
# `bolna-findings/mirror/pages/concepts/call-latencies.md` — the top-level block at :22-45
# (`time_to_first_audio`, `region`, "e.g. `in` for India, `us` for United States"), the
# three component blocks at :57-155, and their own bottleneck thresholds at :164-200.
#
# THIS USED TO BE DROPPED ON THE FLOOR, and the module docstring above said why: an
# unverified claim with no captured payload, so a pilot gate rather than a mapper. Two
# things changed. Their page is now in the read-only mirror, so the shape is first-party
# evidence rather than a search summary. And D-410 put the language model in South India
# while their orchestrator stayed in the US (`mirror/pages/concepts/security.md:29`), which
# made `llm.time_to_first_token` the measurement of a round trip WE chose and nobody ever
# took — TRD §4 budgets it at 150ms (350ms until the 500ms voice-to-voice target landed on
# 27 Aug 2026) and TRD §4a records that every latency figure in this repo is a target with
# zero measurements behind it. D-449 has since co-located the model
# with the orchestrator (`eastus2`), so what this field now measures is whether that was
# worth the India residency claim it cost.
#
# WHAT IS STILL NOT CLAIMED. These are not voice-to-voice numbers and this reader does not
# turn them into any: gate 4's stopwatch is the only thing that can say whether their sum
# resembles what a caller experiences, and `scripts/pilot/latency.py` is where that
# comparison is made. Capturing them makes gate 4 runnable; it does not settle it.
#
# UNITS ARE ASSUMED MILLISECONDS and the assumption is not uniform across the payload.
# Their own examples read as ms for `time_to_first_token` and `time_to_connect`, but
# `audio_to_text_latency: 20.12` (:73) does not read as a millisecond transcription
# latency at all. So `stt_ms` is the one leg whose unit is a live question — which is why
# `TurnLatency.component_sum_ms` refuses a partial sum, and why the alarm below judges the
# LLM leg alone rather than the sum.

#: Free-text keys inside `latency_data`. Read for NOTHING and never carried out of this
#: function: `transcriber.turns[].turn_latency[].text` is recognised CALLER SPEECH
#: (`call-latencies.md:73`), and hard rules 5/6 apply wherever it lands. `CallLatency` has
#: nowhere to put text, which is the structural half of the same guarantee — this constant
#: is here so the next reader learns that the key exists rather than discovering it in a
#: payload.
_LATENCY_TEXT_KEYS: Final = frozenset({"text"})

#: The vendor's OWN definition of a broken LLM leg: *"High LLM Time to First Token
#: (>1000ms)"* (`call-latencies.md:178`). Deliberately NOT `LLM_TTFT_BUDGET_MS` (150ms,
#: ours): that is the target a report measures against, and paging on it would page on the
#: geography we already know about, and the gap only widened when the budget fell to
#: 150ms. This is the number at which the vendor themselves say
#: something is wrong, i.e. the one an operator can act on.
_LLM_TTFT_ALARM_MS: Final = 1000.0

#: Below this many timed turns a call says nothing about a trend. Their own worked example
#: has turn 1 at 1633.04ms and turn 2 at 737.80ms (`call-latencies.md:99-108`): the first
#: turn carries connection setup, so a one-turn or two-turn call is a cold start wearing a
#: distribution's clothes.
_LATENCY_ALARM_MIN_TURNS: Final = 3


def _latency_float(value: Any) -> float | None:
    """A number, or ABSENT. Never 0 for a missing key — a zero would read as instant.

    `bool` is excluded explicitly because it is an `int` in Python and `True` would become
    1.0ms, which is both wrong and plausible-looking.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _latency_turn_value(entry: Any, key: str) -> float | None:
    """One component's number for one turn, tolerating the transcriber's nested list.

    The LLM and synthesizer blocks put the number directly on the turn entry. The
    transcriber block nests a `turn_latency` LIST per turn, one entry per incremental
    refinement of the same utterance (`call-latencies.md:87`: "The final sequence is the
    most accurate"), so the LAST sequence is the one taken — the earlier ones are guesses
    the recogniser itself revised.
    """
    if not isinstance(entry, dict):
        return None
    direct = _latency_float(entry.get(key))
    if direct is not None:
        return direct
    nested = entry.get("turn_latency")
    if isinstance(nested, list) and nested:
        last = nested[-1]
        if isinstance(last, dict):
            return _latency_float(last.get(key))
    return None


def parse_latency_data(raw: Any) -> CallLatency | None:
    """`latency_data` -> OUR `CallLatency`. Timings and a region code; never text.

    `None` when the payload carried no `latency_data` object at all — which is a real
    answer (a listing row does not carry one) and must not be confused with an object we
    read nothing out of. The latter is a `CallLatency` whose `parse_warnings` say what.

    SHAPE-TOLERANT rather than a typed mapping, and that is a decision rather than
    laziness: every block is optional, an unrecognised block becomes a warning instead of
    an exception, and a missing number stays `None`. A payload change must not be able to
    fail a call's post-call pipeline — the lead is worth more than the measurement.
    """
    if not isinstance(raw, dict):
        return None
    warnings: list[str] = []
    ttfa = _latency_float(raw.get("time_to_first_audio"))
    if ttfa is None and "time_to_first_audio" in raw:
        warnings.append("time_to_first_audio present but not numeric")

    # A CODE, NOT A MESSAGE. Kept only when it looks like the short region identifier the
    # vendor documents (`in`, `us`); anything longer is not a region and is refused rather
    # than stored, because the one thing that must never happen to a free-form vendor
    # string is that it gets stored and later rendered.
    region_raw = raw.get("region")
    region: str | None = None
    if isinstance(region_raw, str):
        candidate = region_raw.strip().lower()
        if _REGION_CODE_RE.fullmatch(candidate):
            region = candidate
        elif candidate:
            warnings.append("region present but not a region code")

    per_turn: dict[int, dict[str, float | None]] = {}
    blocks: tuple[tuple[str, str, str], ...] = (
        ("transcriber", "stt_ms", "audio_to_text_latency"),
        ("llm", "llm_ttft_ms", "time_to_first_token"),
        ("synthesizer", "tts_ttfa_ms", "time_to_first_token"),
    )
    for block_name, field, key in blocks:
        block = raw.get(block_name)
        if block is None:
            warnings.append(f"{block_name} block absent")
            continue
        if not isinstance(block, dict):
            warnings.append(f"{block_name} block is not an object")
            continue
        entries = block.get("turns")
        if not isinstance(entries, list):
            warnings.append(f"{block_name}.turns absent or not a list")
            continue
        for position, entry in enumerate(entries, start=1):
            number = entry.get("turn") if isinstance(entry, dict) else None
            index = number if isinstance(number, int) and not isinstance(number, bool) else position
            per_turn.setdefault(index, {})[field] = _latency_turn_value(entry, key)

    return CallLatency(
        region=region,
        time_to_first_audio_ms=ttfa,
        turns=[
            TurnLatency(
                turn=index,
                stt_ms=fields.get("stt_ms"),
                llm_ttft_ms=fields.get("llm_ttft_ms"),
                tts_ttfa_ms=fields.get("tts_ttfa_ms"),
            )
            for index, fields in sorted(per_turn.items())
        ],
        parse_warnings=warnings,
    )


def _check_llm_ttft(latency: CallLatency | None, *, engine_call_id: str) -> None:
    """Page when a whole call's language-model leg is broken — never when one turn is slow.

    THE THRESHOLD IS THE VENDOR'S, NOT OURS, and the difference is what keeps this
    actionable. Our budget is 150ms (`LLM_TTFT_BUDGET_MS`, TRD §4 — 350ms until the 500ms
    voice-to-voice target) and we already expect to miss it: this is a rented audio path
    with a transcriber, a model and a synthesiser in it, and until D-449 the model sat a
    US->India->US round trip away from the orchestrator besides. An alarm on the budget
    would fire on the known geography, on every call, forever —
    which is how an alarm gets muted. 1000ms is the
    number the vendor's own bottleneck guide calls a problem (`call-latencies.md:178`), and
    at 1000ms sustained the agent is audibly broken.

    MEDIAN OVER THE CALL'S TURNS, over a minimum of three of them. The first turn carries
    connection setup and runs long in the vendor's own example (1633.04ms, :99), so a mean
    would let one cold start speak for a healthy call and a max would fire on every call.

    The per-turn budget breaches are NOT alarmed at all — they are counted, stored, and
    read by the report (`ops.engine_latency`). That is the split the brief asks for: a
    number an operator reads when they go looking, and a page only when going looking is
    too late.

    Ids and numbers only (hard rule 6). The region code is the vendor's own identifier;
    everything else here is arithmetic over milliseconds.
    """
    if latency is None:
        return
    samples = sorted(latency.llm_ttft_samples)
    if len(samples) < _LATENCY_ALARM_MIN_TURNS:
        return
    middle = len(samples) // 2
    median = samples[middle] if len(samples) % 2 else (samples[middle - 1] + samples[middle]) / 2
    if median <= _LLM_TTFT_ALARM_MS:
        return
    alert(
        "CORE_LOGIC",
        "engine_llm_ttft_degraded",
        detail=(
            f"median LLM time-to-first-token {median:.0f}ms over {len(samples)} turns, "
            f"above the {_LLM_TTFT_ALARM_MS:.0f}ms the engine's own guide calls a "
            f"bottleneck (our budget is {LLM_TTFT_BUDGET_MS:.0f}ms). "
            f"Engine region: {latency.region or 'unreported'}."
        ),
        engine_call_id=engine_call_id,
    )


#: The two keys that mark a leaf of the vendor's `extracted_data` tree. A category's
#: values are RESULT OBJECTS carrying these; a flat field's value is the answer itself.
#: Matching on the leaf rather than on nesting depth is what lets one function read both
#: shapes without a version flag we would have to keep current.
_EXTRACTION_LEAF_KEYS: Final = ("subjective", "objective")

#: What the vendor returns for EVERY extraction on a call in which the caller never spoke,
#: from 18 September 2026. Voicemail, an immediate hangup, a ring nobody answered — the
#: model has nothing to work from, so rather than let it invent an answer the platform
#: substitutes this literal.
#:
#: **EVIDENCE CLASS: VENDOR-PUBLISHED, AND NOT FROM A PAGE ANYONE HERE HAS READ.** It comes
#: from Bolna's deprecation email of 3 Sep 2026, relayed by the founder. It is NOT in
#: `bolna-findings/mirror/` — that mirror predates the announcement — and `www.bolna.ai` is
#: egress-blocked from this container, so the migration guide behind that email has not
#: been opened here. OPERATIONS §2 gate 43h is the re-verification.
#:
#: THE MATCH IS CASE- AND SPACE-INSENSITIVE FOR EXACTLY THAT REASON. The casing in an email
#: is not a wire contract, and a sentinel we fail to recognise is worse than one we
#: over-match: an unrecognised one becomes a client's data.
NO_USER_TURN_SENTINEL: Final = "no user turn detected"


def _is_no_user_turn(value: Any) -> bool:
    """Is this the vendor's "nobody spoke" marker rather than something a caller said?

    **IT MUST NEVER BE TREATED AS AN EXTRACTED VALUE.** On a silent call every field comes
    back carrying it, so a passthrough writes the sentence into every CRM column the
    client configured — a lead whose name is "No User Turn Detected", a callback number
    that is a sentence, an outcome tag that is an apology. It would also make pilot gate 7
    PASS a call in which nothing was said, because that gate compares field NAMES and the
    names would all be present. A false pass on a fidelity gate is worse than a false
    fail: it is read as the vendor working.
    """
    return isinstance(value, str) and value.strip().lower() == NO_USER_TURN_SENTINEL


def flatten_extracted_data(raw: Any) -> dict[str, Any]:
    """The vendor's `extracted_data` -> OUR flat `{field_name: value}`.

    **THE VENDOR NESTS BY CATEGORY AND THIS ADAPTER PASSED THE NESTING STRAIGHT THROUGH.**
    `ExecutionSnapshot.engine_extracted` is a FLAT map of field name to value — that is
    what every consumer above reads it as, and what `tests/pilot_fidelity_test.py` pins
    (`engine_extracted={"lead_name": "Ravi Kumar"}`). Bolna's is two levels deep:
    `extracted_data -> "<Category>" -> "<Disposition>" -> {subjective, objective, ...}`,
    stated three times in their own documentation — "Results are nested by category and
    extraction name under `extracted_data`", the worked `GET /executions/{id}` example,
    and `POST /v2/agent/{id}/dispositions/test`'s "grouped by category and disposition
    name, in the same format as post-call execution data".

    So `sorted(engine_extracted)` — the one thing every consumer does with it — returned
    the tenant's CATEGORY names under the label "field names". Pilot gate 7 compares that
    tuple against the field names an operator lists as `expects_extracted_fields`, so a
    call in which every field came back scored `fail` and named every one of them as
    absent. A false FAIL on a gate is worse than no gate: it is read as the vendor
    failing, on evidence produced by us.

    THE FLATTENING BELONGS HERE, not in the consumer, and that is hard rule 2 rather than
    tidiness. `scripts/pilot/fidelity.py` learning that a value keyed `subjective` means
    the parent key is a category is this file's knowledge leaking into a caller that must
    keep working when the engine is not Bolna.

    BOTH SHAPES, because the vendor says there are two: Extractions is "the NEW ...
    feature ... powered by the Dispositions API", so an account may still hold agents
    whose payload is flat. A top-level entry is a CATEGORY only when its value is a
    mapping whose own values carry `subjective` or `objective`; anything else is a field
    and passes through untouched. Matching on the leaf keys rather than on depth means a
    flat field whose value happens to be a dict is not mistaken for a category.

    THE VALUE IS `objective` FIRST, THEN `subjective`. Both are documented as the answer;
    `objective` is the pre-defined selection — the CRM-column-shaped one — and
    `subjective` the free text. `confidence`, `reasoning_*` and `validation` are dropped:
    they are the vendor's account of ITSELF, not the extracted value, and the reasoning
    fields are free text the model wrote about what the caller said (hard rule 6).

    A CALL IN WHICH NOBODY SPOKE YIELDS NO FIELDS AT ALL. From 18 Sep 2026 the vendor
    answers every extraction on such a call with a fixed sentence rather than letting the
    model invent one (`NO_USER_TURN_SENTINEL`); passing it through would write that
    sentence into every CRM column a client configured. It is dropped here, at the
    boundary, so the vendor's vocabulary for "nothing happened" never becomes our
    vocabulary for a value (hard rule 2).

    A DUPLICATE FIELD NAME ACROSS TWO CATEGORIES KEEPS ITS CATEGORY. Bolna scopes
    uniqueness to the category, so two categories may both carry "Notes"; a bare
    last-wins would silently drop one extracted value. The second and later spellings
    become `"<Category> / <Name>"`, which is visible rather than lost — the first keeps
    the bare name so the common case still matches what an operator lists.
    """
    if not isinstance(raw, dict):
        # Not an object at all — an absent key, a null, or a shape nothing here models.
        # `{}` is what "no extraction ran" already means to every consumer, and inventing
        # a field from an unreadable payload would be worse than reporting none.
        return {}
    flat: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if _is_extraction_category(value):
            for leaf_name, leaf in value.items():
                extracted = _extraction_value(leaf)
                # DROPPED, NOT RECORDED AS None. `{}` is what "no extraction ran" already
                # means to every consumer of this map, and a present key with no value
                # would tell pilot gate 7 the field came back when it did not.
                if _is_no_user_turn(extracted):
                    continue
                _place(flat, category=name, name=str(leaf_name), value=extracted)
            continue
        if _is_no_user_turn(value):
            continue
        flat[name] = value
    return flat


def _is_extraction_category(value: Any) -> bool:
    """Is `value` a CATEGORY — a non-empty mapping of names to result objects?

    EVERY member must look like a result, not merely one: a flat field whose value is a
    dict with an unrelated `objective` key inside would otherwise swallow its siblings.
    """
    if not isinstance(value, dict) or not value:
        return False
    return all(
        isinstance(leaf, dict) and any(marker in leaf for marker in _EXTRACTION_LEAF_KEYS)
        for leaf in value.values()
    )


def _extraction_value(leaf: dict[str, Any]) -> Any:
    """The answer out of one result object: the pre-defined value, else the free text.

    **AN EMPTY `objective` IS THE UNCONFIGURED HALF, NOT AN ANSWER, AND `is not None` READ
    IT AS ONE.** A Bolna disposition is `is_subjective` and/or `is_objective`
    (`bolna-findings/mirror/pages/api-reference/dispositions/get.md:112,117`), so one of
    the two leaf fields belongs to a half the operator never turned on — and the vendor
    demonstrably emits that half as an EMPTY STRING rather than omitting it:

        Escalation:
          Agent Handover Needed:
            subjective: ''
            objective: 'No'

    (`api-reference/dispositions/test.md:127-129`, whose response schema is documented as
    "the same format as post-call execution data".) That example is the objective-only
    case; the subjective-only one is its mirror, `{"subjective": "…", "objective": ""}`,
    and on it a bare `is not None` returned `""` — so the free text the model actually
    extracted never reached the CRM column, on every call, with the field still PRESENT in
    `engine_extracted` so nothing downstream could tell. Pilot gate 7 compares field NAMES
    and would have passed it.

    Blank is treated as absent for the string case only. `False` and `0` are answers and
    stay answers: they are what the older flat shape carries
    (`extracted_data: {"user_interested": true, "callback_user": false}`), and a truthiness
    test here would drop them — the same defect one type over.
    """
    objective = leaf.get("objective")
    if objective is not None and not (isinstance(objective, str) and not objective.strip()):
        return objective
    return leaf.get("subjective")


def _place(flat: dict[str, Any], *, category: str, name: str, value: Any) -> None:
    """Write one field, qualifying the name rather than overwriting a taken one."""
    flat[name if name not in flat else f"{category} / {name}"] = value


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
# * `knowledge_base=True` (D-488). **IT WAS `True`, THEN `False`, AND IT IS NOW `True`
#   FOR THE FIRST TIME WITH A PATH BEHIND IT — read all three states before trusting any
#   sentence that survives from an earlier one.**
#
#   THE FIRST `True` (pre-D-354) WAS A LIE THAT COULD NEVER HAVE WORKED. This adapter
#   called `POST /knowledgebase` with a JSON body of `{agent_id, name, text}`. The route
#   is `multipart/form-data` taking `file` (a PDF, max 20 MB) or `url` — "Provide either
#   `file` or `url`, not both" — and accepts NO agent id and NO raw text
#   (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:29-80`). And a
#   created knowledge base carries no agent linkage at all, so `list_kb`'s filter on
#   `row["agent_id"]` matched a field the `Knowledgebase` schema does not declare
#   (`.../knowledgebase/get_knowledgebases.md:63-121`) and answered `[]` for every agent
#   forever — which `kb/reconciliation` reads as "the engine holds nothing", i.e. silent
#   drift by construction.
#
#   `False` WAS THE HONEST DESCRIPTOR OF THAT, AND IT RESTED ON ONE PREMISE THAT WAS
#   WRONG. D-354 recorded the blocker as ours-but-unreachable: `KBSourceRef` carries
#   prose and "rendering it to a PDF inside the adapter would be inventing a document
#   format on the money-adjacent side of a compliance feature". That reasoning is intact
#   and is why the renderer is NOT here — it lives in `apps/api/kb/`, on the side of hard
#   rule 2's wall where the approval gate can see it, and `KBSourceRef.document` carries
#   the bytes. What was wrong was the wider inference that grew around it, corrected in
#   `docs/evidence/kb-retrieval-bakeoff.md` §3.1e: that the engine could not do in-call
#   retrieval at all. It does, per turn — *"On each turn the latest user message
#   retrieves the most relevant chunks, which are added to the prompt before the response
#   is generated"* (`bolna-findings/mirror/pages/graph-agent/tools-and-rag.md`).
#
#   WHAT ACTUALLY CHANGED TO EARN THE `True`, none of it a flag flip:
#     (a) `KBSourceRef` gained a rendered `document` and a `content_sha256`, so the thing
#         uploaded is an artefact a human approved, rendered by the publisher.
#     (b) `attach_kb` is the real four-step sequence — multipart create, wait for
#         `processed` (the create returns `processing` and NO `vector_id`; the vector id
#         exists only on `GET /knowledgebase/{rag_id}`, `.../get_knowledgebase.md:81-93`),
#         read the agent's current vector ids, then PUT the agent with the new one added.
#     (c) `detach_kb` un-references BEFORE it deletes, and raises on a handle the account
#         does not hold. `list_kb` reads the AGENT, which is where the linkage has always
#         lived.
#     (d) The handle is the VECTOR ID, so `AgentSnapshot.references_kb` compares like with
#         like and D-41's dangling-handle question is answerable from a payload instead of
#         being closed by an unreadable field.
#     (e) `update_agent` reads the agent's vector ids back and re-sends them, because
#         `PUT` replaces the whole configuration and `AgentConfig` carries none — without
#         it, every T0 recompile would silently delete the client's knowledge.
#
#   ⚠ WHAT IS STILL NOT MEASURED, AND WHY `True` IS STILL THE HONEST VALUE. Not one of
#   these calls has been made against a live account: `api.bolna.ai` is unreachable from
#   this container and no credential exists here. `True` is the claim that the ROUTES
#   exist as the pinned mirror documents them and that this adapter calls them correctly;
#   it is not a measurement. Every unmeasured half is a named gate in OPERATIONS §2
#   (43a-43f), each of which fails LOUD — a vendor 4xx surfaced as `engine_rejected`, or
#   a timeout surfaced as `engine_kb_processing_timeout` — rather than degrading to a
#   green tick. That is strictly better than the state D-354 left, where the capability
#   was absent and the step was not attempted at all.
# * `campaigns=False`. Bolna HAS campaign objects; TRD §5 records them and CLAUDE.md
#   prefers configuring engine built-ins over rebuilding them. We do not use them — every
#   campaign in this system is dispatched by `apps/api/campaigns` + `apps/workers`,
#   through the compliance gate, which is not something an engine-side campaign object
#   can be trusted to run (hard rule 5 forbids a bypass). So the honest value of this
#   field, whose meaning is "is there an engine-side campaign object OUR code depends
#   on", is False. If that ever changes it is a decision-log entry, not a flag flip.
# * `number_series=frozenset()`. Nobody buys a number through this product: the client
#   holds the connection on their own carrier account (Model B — `campaigns/
#   provisioning.py`, `docs/legal/LEGAL-OPS-PLAYBOOK.md` §9). This adapter's
#   `provision_number` has always raised; now it says so before being called.
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
#   not just our column) and not a flag flip.
#   **THE HOSTED CONTRACT NOW CONFIRMS BOTH HALVES, so the evidence class rises from
#   VERIFIED-OSS to VERIFIED-VENDOR-DOCS and gate 18's first question is answered.** The
#   hosted create body carries `ToolsConfigV2.api_tools` → `ApiTools.tools[]` `oneOf`
#   `TransferCallTools`, whose `key` is `transfer_call` and whose destination is
#   `TransferCallToolParams.param`, a stringified `{"call_transfer_number": "+1…",
#   "call_sid": "%(call_sid)s"}` — a number fixed WHEN THE AGENT IS CONFIGURED, exactly the
#   OSS shape (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`); the console
#   equivalent is the Tools tab's Transfer Call card
#   (`bolna-findings/mirror/pages/agent-setup/tools-tab.md`: "Route the call to a human
#   agent or another phone number"). And the whole v2 agent surface is
#   `POST /v2/agent`, `GET /v2/agent/{id}`, `GET /v2/agent/all`, `PUT`/`PATCH
#   /v2/agent/{id}`, `DELETE /v2/agent/{id}`, `POST /v2/agent/{id}/stop` and the two
#   executions reads — **no route transfers a live execution**, and `stop` cancels QUEUED
#   calls ("This stops **ALL** the queued calls for a given agent",
#   `bolna-findings/mirror/pages/api-reference/agent/v2/stop.md`), not an in-flight one.
#   What is left for gate 18 is the DESIGN question, not the vendor one: whether a
#   per-agent escalation number becomes engine config, and who is metered and retained for
#   the transferred leg (`_check_transfer_leg` above pages on the first one that happens).
# * `agent_hosting="control_plane"` (D-280). Bolna is the shape this port was written
#   around and the reason it read as vendor-neutral for as long as it did: `POST /v2/agent`
#   creates the object, `PUT /v2/agent/{id}` edits it, `GET /v2/agent/{id}` answers what it
#   holds, and the system prompt — with hard rule 5's directive inside it — is agent-record
#   state (`agent_prompts.task_1.system_prompt` in `_agent_body`). Nothing about that is
#   assumed: it is the surface this adapter has always called. What the value BUYS is that
#   the assumption is now written down and refusable, so the engine that does NOT work this
#   way can say so instead of being discovered at a 404.
# * `caller_id=True` (D-420). VERIFIED-VENDOR-DOCS: `POST /call` takes
#   `from_phone_number` — *"Add your purchased phone number or your own connected phone
#   number in `from_phone_number` field"* — and OMITTING IT IS NOT NEUTRAL: the same page
#   says the call then goes out on their centralised pool, which for an Indian callee is
#   *"a `+91` prefix phone"*
#   (`bolna-findings/mirror/pages/guides/outbound/making-outgoing-calls.md`). This adapter
#   sent no such field until D-420, so every campaign call presented Bolna's number while
#   `campaigns.service._channel_blockers` reported the client's registered header approved.
# * `inbound_binding=True` (D-420). VERIFIED-VENDOR-DOCS: `POST /inbound/setup`
#   `{agent_id, phone_number_id}` and `POST /inbound/unlink {phone_number_id}`
#   (`bolna-findings/mirror/pages/api-reference/inbound/agent.md`, `.../unlink.md`), which
#   the inbound guide makes mandatory — *"You will need to assign a phone number to your
#   Bolna Voice AI agent for automatically answering all incoming calls on that phone
#   number"*.
#   ⚠ **MARKED ASSUMPTION — OPERATIONS §2 GATE 25.** The same vendor also writes
#   *"Inbound Agent functionality using APIs currently requires connecting your **Twilio
#   account**"* (`guides/telephony/twilio-inbound-calls.md`), and `allow_multiple` /
#   `ivr_config` on the setup body are documented Plivo-only. Those cannot both be current,
#   and Plivo is the carrier for the 160-series numbers our agents run on. `True` is the
#   claim that the ROUTE exists and that this adapter calls it correctly; whether a
#   non-Twilio Indian number binds through it is gate 25's single API call. It fails LOUD
#   if not — a 400 from the vendor, surfaced as `engine_rejected` by `bind_inbound_number`'s
#   caller and alarmed — which is the safe direction to be wrong in, and strictly better
#   than the state D-420 found, where the step was not attempted at all.
BOLNA_CAPABILITIES = EngineCapabilities(
    stt="ours",
    tts="ours",
    llm="ours",
    agent_hosting="control_plane",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    caller_id=True,
    inbound_binding=True,
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

    def _conversion_rate(self, currency: str) -> tuple[Decimal, str | None, date | None]:
        """The rate this costing converts at, and where it came from.

        THREE ANSWERS, and which one you get is a fact worth recording (it is, on the row):

        * `INR` — no conversion at all. Rate 1, no source, and multiplying by the USD rate
          here is the 83x error `_cost`'s branch exists to prevent.
        * a PUBLISHED rate is installed and inside `core/fx.MAX_QUOTE_AGE` — use it. This
          is the normal path once `workers/fx_pull.py` has ticked, and inside a worker job
          it is pinned for the whole job by `fx_scope()`, so a rate that changes between
          the fetch and the ledger write cannot split one call across two numbers.
        * nothing published, or it has aged out — fall back to `self._fx_rate`, the
          operator's configured `USD_INR_RATE` captured when this adapter was built. That
          is exactly what this adapter did before the pull existed, so the failure
          direction is "the platform bills as it did last release", never "the platform
          stops billing". The fallback is not silent: `ops/fx_rates.refresh_fx_snapshot`
          alarms on a rate past its ceiling and `workers/fx_pull` alarms on a puller that
          has gone quiet, so an operator hears about it before a month closes.

        Reading `current_fx_quote()` rather than a database is what keeps this legal on
        `parse_webhook`'s path (hard rule 3): it is one in-memory read and no IO.
        """
        if currency == "INR":
            return Decimal(1), None, None
        quote = current_fx_quote()
        if quote is None:
            return self._fx_rate, _CONFIGURED_FX_SOURCE, None
        return quote.rate, quote.source, quote.as_of

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

    def _agent_body(
        self, cfg: AgentConfig, *, vector_ids: Sequence[EngineKBRef] = ()
    ) -> dict[str, Any]:
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
        # The in-call ACTION tools, or None for an agent with none — see `_api_tools`. Held
        # in a local so the `tools_config` literal below can add the key ONLY when there is
        # one, keeping an actionless agent's body identical to what it was before actions.
        api_tools = _api_tools(cfg)
        body: dict[str, Any] = {
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
                            # THE D-260 MARKED ASSUMPTION IS SETTLED, AND IT WENT THE WAY
                            # IT FEARED (D-400). It read: `family` is ASSUMED to select
                            # the LLM client, CONTRADICTED BY the OSS server where
                            # `family` is declared on `Llm` and read by NOTHING while
                            # `provider` chooses the class out of `SUPPORTED_LLM_PROVIDERS`
                            # — so a config naming no `provider` routes to OpenAI whatever
                            # `model` says. Re-read at source 18 Aug 2026 on `master`
                            # (`bolna/providers.py`, `bolna/enums.py::LLMProvider`,
                            # `bolna/llms/openai_llm.py`): unchanged, and `provider:
                            # "custom"` maps to `OpenAiLLM`, which constructs
                            # `AsyncOpenAI(base_url=…, api_key=…)`. Their published
                            # OpenAPI agrees by omission — `provider` and `family` carry
                            # NO enum while `agent_flow_type` in the same block does, and
                            # the spec's author uses `enum` when they mean a closed set
                            # (telephony is `enum: ["twilio", "plivo"]`). An arbitrary
                            # OpenAI-compatible endpoint is the DESIGNED extension point,
                            # not a workaround.
                            #
                            # So we now SEND `provider`, from `_llm_routing` above, and
                            # `family` stays only because it is free and their own examples
                            # carry it. D-356 ("it needs `ModelConfig` to grow an
                            # `llm_provider` and somebody to register the model") is closed
                            # by that function's existence. What is still not settled is
                            # what the HOSTED platform STORES (gate 16 asked exactly this) —
                            # `_snapshot` reads both back so the answer arrives as data
                            # from the first publish rather than as a reviewer's guess.
                            "llm_agent": {
                                "agent_type": "simple_llm_agent",
                                "agent_flow_type": "streaming",
                                "llm_config": {
                                    "agent_flow_type": "streaming",
                                    # `provider`/`family`/`base_url` from the ONE
                                    # function that turns a Calevate LLM leg into a
                                    # Bolna provider name (D-400). It sits INSIDE
                                    # `llm_config` because that is where `LlmAgentV2`
                                    # keeps the model settings (D-355) — the branch
                                    # that introduced `_llm_routing` spread it at the
                                    # flat v1 level, which the v2 endpoint ignores.
                                    **_llm_routing(cfg.models),
                                    # ONE MODEL SLOT, AND ON AN AZURE LEG IT HOLDS THE
                                    # DEPLOYMENT ID (D-410). Their `SimpleLlmAgent` has
                                    # exactly this one string for the thing to run
                                    # (VERIFIED-OAS) and Azure's v1 surface addresses a
                                    # DEPLOYMENT rather than a model, so what belongs
                                    # here is `Settings.azure_openai_deployment` — which
                                    # is what `agents/service.py::in_call_llm` puts in
                                    # `ModelConfig.llm_model` for this leg.
                                    # `Settings.azure_openai_model` is a different string
                                    # that never reaches the wire; see `_llm_routing`.
                                    "model": cfg.models.llm_model,
                                    # SENT EXPLICITLY, and the reason is that NOT sending
                                    # them was a decision nobody had taken (D-283).
                                    #
                                    # READ AT SOURCE, bolna-ai/bolna@cd2e192,
                                    # `bolna/models.py`: `Llm.max_tokens` defaults to **100**
                                    # and `Llm.temperature` to **0.1**, and
                                    # `task_manager.__setup_llm` reads both with bare
                                    # subscripts off `llm_agent_config`. Our body omitted
                                    # them, so the stored `agent_config.model_dump()` filled
                                    # the vendor's defaults and every agent on the platform
                                    # ran with a 100-token ceiling on each reply — a real
                                    # product knob, silently inherited.
                                    #
                                    # **PER MODEL SINCE THE CATALOGUE OPENED, AND THE PAIR OF
                                    # LITERALS THAT USED TO SIT HERE WAS THE DEFECT.** They
                                    # were right for every Azure model and are a 400 at
                                    # agent-create time on a GPT-5 one, which requires
                                    # `temperature: 1` exactly. `_llm_trap_settings` renders
                                    # this config's declared traps into the vendor's keys and
                                    # carries the defaults (400 tokens, 0.1) for a model with
                                    # none — read it for why the branch is on the TRAP and not
                                    # on a model-name prefix, which on the Azure leg would be
                                    # reading a deployment id an operator named freely.
                                    **_llm_trap_settings(cfg.models),
                                },
                            },
                            # THE MODEL AND THE SPEAKER, IN THE TWO KEYS THE VENDOR
                            # READS THEM FROM — and until D-358's second half landed we
                            # sent one string in the wrong one of them.
                            #
                            # `cfg.models.tts_voice` used to hold a MODEL (`bulbul:v3`)
                            # and it was sent as `provider_config.voice`, so every agent
                            # named a model where a speaker belongs and named no model at
                            # all. The vendor's own worked example is unambiguous:
                            # `"provider_config": {"model": "bulbul:v3", "voice":
                            # "Ashutosh", "voice_id": "ashutosh"}` (VERIFIED-VENDOR-REPO,
                            # `bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`).
                            #
                            # WHAT UNBLOCKED IT was a speaker list. The comment that used
                            # to sit here declined to move the string because "moving it
                            # to `model` leaves `voice` unset and the engine picks
                            # whichever speaker it likes" — correct at the time, and dead
                            # now: Sarvam's own SDK enumerates all 44 speakers
                            # (VERIFIED-VENDOR-SDK: sarvamai==0.1.31 (PyPI wheel),
                            # `types/text_to_speech_speaker.py`, read 27 Aug 2026), so a
                            # speaker CAN be named. `agents/voices.py` carries them and
                            # `agents/service.py::in_call_speech` splits our catalogue id
                            # into the pair; this adapter never parses that id (hard
                            # rule 2 — the id spelling is ours, not a payload shape).
                            "synthesizer": {
                                "provider": cfg.models.tts_provider,
                                "provider_config": _synthesizer_config(cfg.models),
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
                            # **STATED, BECAUSE IT IS THE ONE DOCUMENTED WAY THE RUNNING
                            # PROMPT CAN STOP BEING THE PROMPT WE PUBLISHED** (hard rule
                            # 5). `MultilingualConfig` keeps a `system_prompt` PER
                            # LANGUAGE and, in the vendor's own words, *"switches them,
                            # along with the active system prompt, during the call"*
                            # (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/
                            # api-reference/agent/v2/create.md`,
                            # `ToolsConfigV2.multilingual_config` →
                            # `MultilingualConfig.description`; the per-language field is
                            # `MultilingualLanguageEntry.system_prompt`, *"Prompt
                            # activated while the agent speaks this language"*).
                            #
                            # `compose_engine_prompt` puts `TRUTHFUL_ANSWER_DIRECTIVE`
                            # into `agent_prompts.task_1.system_prompt` and nowhere else,
                            # and `verification.judge` reads it back from exactly there.
                            # So an agent with multilingual switched on would run, for
                            # every language but the base one, a prompt carrying none of
                            # the floor — while the read-back scored
                            # `truthful_answer_applied=True` off a prompt that is not the
                            # one in use. That is precisely the shape hard rule 5 forbids:
                            # a config row withdrawing the directive.
                            #
                            # WHY EXPLICIT NULL RATHER THAN OMISSION, which is the same
                            # argument `agent_welcome_message` makes above: an omitted key
                            # is a field left as it was. Their PATCH page describes `PUT`
                            # as replacing "the entire agent configuration", but nobody
                            # here has observed that against a live account (OPERATIONS §2
                            # gate 2), and a compliance floor is not a thing to rest on an
                            # unobserved merge semantics. `null` is the vendor's OWN
                            # value for this key — `default: null`, `nullable: true` on
                            # `ToolsConfigV2.multilingual_config` — so stating it cannot
                            # be rejected and cannot mean anything but single-language.
                            #
                            # NOT THE SAME TREATMENT FOR `LlmAgentV2.routes`, and the
                            # asymmetry is evidence, not inconsistency. `Routes` is the
                            # OTHER config surface that can speak without the LLM — its
                            # `Route.response` is a *"static response"* returned when a
                            # caller's utterance matches, so a route matching "are you an
                            # AI?" would answer from config with the prompt never
                            # consulted. But `routes` is declared `$ref: Routes` with NO
                            # `nullable` and NO default, so sending `null` is not a
                            # documented value and an empty `{"routes": []}` is a guess
                            # about what their semantic router does with an empty layer.
                            # Guessing there could break every publish, so it is a
                            # REPORTED gap (docs/evidence/bolna-agent-lifecycle.md) with
                            # a read-back proposal, not a literal invented here.
                            "multilingual_config": None,
                        },
                        "task_config": {
                            "hangup_after_silence": 10,
                            "call_terminate": cfg.max_call_duration_s,
                            # **THE TWO CONVERSATION FLAGS THAT CAN PLACE A CALL, OR
                            # RECORD A SECRET, WITHOUT US (D-413).** Both are
                            # `ConversationConfig` booleans defaulting to `false`
                            # (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/
                            # api-reference/agent/v2/create.md`, the same schema
                            # `hangup_after_silence` and `call_terminate` above come
                            # from), so this states what we would otherwise inherit.
                            # WHY STATED RATHER THAN OMITTED is `multilingual_config`'s
                            # argument one block up — an omitted key is a field left as
                            # it was — with one addition that makes it sharper here:
                            # BOTH have a dashboard toggle. `agent-setup/call-tab.md`
                            # ships "Auto Reschedule" and "Keypad Input (DTMF)" as
                            # switches on the Call Tab, so a console click can turn
                            # either on for a live agent without our deploying, and
                            # neither is in anything `get_agent` reads back.
                            #
                            # `auto_reschedule` — *"Automatically reschedule the call
                            # when the user asks to be called back at a later time"*.
                            # A callback scheduled inside the call is placed by THEIR
                            # scheduler, so it never passes
                            # `compliance.service.check_dispatch`: the platform halt,
                            # the tenant's spend cap, the agent gate and — decisively —
                            # the DNC list are evaluated once, at the first call, and
                            # never again. Hard rule 5 requires DNC additions to take
                            # effect before the next dispatch tick, and a
                            # vendor-scheduled callback has no tick.
                            # WORSE, THE WINDOW IT WOULD VALIDATE AGAINST IS THE
                            # CLIENT'S SCRIPT. `guides/outbound/calling-guardrails.md`
                            # §"In-Call Reschedule Validation" ranks the sources:
                            # `calling_guardrails` first (we send none — see the
                            # evidence note), then *"the LLM reads time restrictions
                            # from the system prompt"*, then a 9AM-9PM default. Priority
                            # 2 is a tenant-authored string, so a script saying "we're
                            # available round the clock" would have the model book a
                            # 23:00 callback — a TCCCPR breach placed on Calevate's own
                            # telemarketer registration. Hard rule 5 forbids a
                            # client-authored script withdrawing a compliance invariant;
                            # `False` is what makes that true rather than hoped.
                            # THE VENDOR CONTRADICTS ITSELF ABOUT WHAT THE TOGGLE DOES
                            # and `False` refuses both readings, so the contradiction
                            # does not have to be settled before we are safe: the OAS
                            # says in-call callback (above), while the dashboard page
                            # calls the same switch *"Automatically retry failed calls
                            # later"* (`agent-setup/call-tab.md`) — which would be a
                            # SECOND retry ladder stacked on
                            # `workers/campaign_dispatch._record_failure`, i.e. a double
                            # dial to one person. Reported, not guessed
                            # (docs/evidence/bolna-call-flows.md).
                            #
                            # `dtmf_enabled` — keypad digits are not a side channel,
                            # they are delivered INTO THE CONVERSATION as the message
                            # `dtmf_number: <digits>` (`guides/inbound/dtmf.md`). So
                            # they land in the transcript this platform stores, redacts
                            # and exports — and the vendor's own use cases for the
                            # feature are *"PIN or OTP verification"*, an account
                            # number, and *"a password or card number"*. MEASURED
                            # AGAINST OUR OWN REDACTOR RATHER THAN ASSUMED: a
                            # keypad-entered 4-digit PIN arrives as `dtmf_number: 1234`,
                            # which is too short for `redaction._PHONE_SPAN_RE`'s
                            # numbering-plan validator, too short for `_CARD_RE`, and
                            # invisible to `_OTP_RE` because that one needs the literal
                            # word otp/code/pin/password within 20 characters and the
                            # vendor's prefix is `dtmf_number`. Nothing in this product
                            # asks a caller to press a key, so the feature is all edge
                            # and no upside until an IVR product exists to want it.
                            "auto_reschedule": False,
                            "dtmf_enabled": False,
                        },
                    }
                ],
            },
            "agent_prompts": {"task_1": {"system_prompt": prompt}},
        }
        if api_tools is not None:
            # Added rather than always-present so an agent with no actions sends no
            # `api_tools` at all — see `_api_tools`. `tasks[0].tools_config` is the block
            # built above; this is the one place actions touch the vendor body.
            tasks = body["agent_config"]["tasks"]
            tasks[0]["tools_config"]["api_tools"] = api_tools
        # THE KNOWLEDGE LINKAGE, AND IT IS A PARAMETER RATHER THAN A FIELD OF `AgentConfig`
        # (D-488). What an agent KNOWS is our state; which VECTOR IDS the engine minted for
        # it is the engine's, and the two are related only by handles this adapter recorded.
        # Threading it through `AgentConfig` would put vendor-minted identifiers into the
        # model every caller builds, and every caller that did not know to populate them
        # would silently publish an agent with its knowledge removed. Every writer here
        # reads them from the ENGINE instead, which cannot be forgotten.
        _apply_vector_store(body, vector_ids)
        return body

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
        """`PUT /v2/agent/{id}` — a FULL REPLACEMENT, which is why it reads first.

        **THE READ IS NOT AN OPTIMISATION, IT IS WHAT STOPS EVERY REPUBLISH FROM WIPING
        THE AGENT'S KNOWLEDGE (D-488).** `PUT` *"replaces the entire agent
        configuration"* (`bolna-findings/mirror/pages/api-reference/agent/v2/
        patch_update.md:9`), and `AgentConfig` carries no vector ids — deliberately, see
        `_agent_body`. So a body built from `cfg` alone omits `vector_store`, and this
        method is reached by a T0 recompile, a voice change, a call-cap change and the
        drift repair: an agent whose knowledge silently vanished the next time anybody
        renamed it would look exactly like an engine that lost the document.

        THE ALTERNATIVE — `PATCH` — CANNOT DO THIS JOB AT ALL, and that is worth stating
        because it is the obvious reach. `PATCH /v2/agent/{id}` updates a CLOSED list of
        attributes (`agent_name`, `agent_welcome_message`, `webhook_url`, `synthesizer`,
        `ingest_source_config`, `telephony_provider`, `calling_guardrails`,
        `agent_prompts`) and *"Any other field in the body is ignored"*
        (`patch_update.md:9,20-31`). `tasks` is not on it, and `vector_store` lives inside
        `tasks[].tools_config`. A PATCH carrying it would answer 200 and change nothing.

        The cost is one extra GET per publish. That is the honest price of a
        full-replacement write on an object whose other writer is `attach_kb`.
        """
        preserved = _agent_vector_ids(_agent_object(await self._request("GET", f"/v2/agent/{ref}")))
        await self._request(
            "PUT", f"/v2/agent/{ref}", json=self._agent_body(cfg, vector_ids=preserved)
        )

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """`DELETE /v2/agent/{agent_id}` — the orphan compensator's one instrument.

        **THE PATH AND THE VERB ARE DOCUMENTED, and this is a stronger footing than the
        rest of this adapter's agent lifecycle stands on.** Bolna's API reference publishes
        the route as `DELETE https://api.bolna.ai/v2/agent/{agent_id}` with a
        `Authorization: Bearer` header, `agent_id` as a required path parameter, a 200
        answering `{"message": "success", "state": "deleted"}`, and 400 as the only other
        documented status. The OSS server's own `API.md` documents the same route shape
        (`DELETE /agent/{agent_id}` → `{"agent_id": ..., "state": "deleted"}`).
        **THAT SENTENCE WAS REPORTED-NOT-READ AND IS NOW VERIFIED-VENDOR-DOCS**, which is
        worth correcting in place rather than leaving a stale evidence class on a
        destructive verb. It used to end "retrieved 2026-08-15 via search summary of
        docs.bolna.ai ... the hosted docs host itself is refused by this environment's
        egress proxy". The host is still refused; the PAGE is mirrored, and it says exactly
        what the summary claimed: `bolna-findings/mirror/pages/api-reference/agent/v2/
        delete.md:32-55` declares `/v2/agent/{agent_id}` `delete:`, `agent_id` as a path
        parameter with `required: true`, a 200 example of `{message: success, state:
        deleted}`, and 400 as the only other response. The OSS half stays READ AT SOURCE
        at https://github.com/bolna-ai/bolna/blob/master/API.md.

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
        * VERIFIED-VENDOR-DOCS, AND THIS BULLET USED TO SAY THE OPPOSITE TWICE. It read
          "NOT READ, ONLY REPORTED ... the page ITSELF could not be fetched" and "Bolna
          publishes no OpenAPI spec (module docstring)" — the second contradicted this
          file's own module docstring, which D-350 rewrote to say they publish one. Both
          halves are now first-hand: the page is mirrored at
          `bolna-findings/mirror/pages/api-reference/agent/v2/get.md`, it declares
          `GET /v2/agent/{agent_id}` returning `AgentV2`, and `AgentV2` declares
          `agent_prompts` — so **the published system prompt IS readable back**, which is
          the property the publish read-back and the drift sweep are built on
          (`_agent_system_prompt`). `tasks[].tools_config` is declared too, which is what
          `_agent_models` reads.
        * **`agent_welcome_message` IS NOT IN `AgentV2` — read the greeting bullet below
          before treating an `unreadable` verdict as a defect of ours.** The schema's own
          property list is `id`, `agent_name`, `agent_type`, `agent_status`, `created_at`,
          `updated_at`, `tasks`, `ingest_source_config`, `agent_prompts`, and the greeting
          is in none of them. `_agent_greeting` already answers `readable=False` for that,
          which the judge scores `unreadable` — so on this engine EVERY publish carrying an
          opening line lands `unreadable` rather than `applied` until a live account says
          otherwise. That is the honest verdict, not a bug to code around, and it is what
          OPERATIONS §2 gate 2 exists to settle.
        * **THE KNOWLEDGE REFERENCE IS FOUND, AND THIS BULLET SAID THE OPPOSITE UNTIL THE
          MIRROR WAS READ.** It read "NOT FOUND AT ALL — the loudest gap. Nothing found
          anywhere says where a knowledge base reference lives inside the agent object".
          It does: `tasks[].tools_config.llm_agent.llm_config` is a `KnowledgebaseAgent`
          whose `vector_store.provider_config` is a `LanceDbConfig` declaring `vector_id`
          and `vector_ids` (`bolna-findings/mirror/pages/api-reference/agent/v2/
          get.md:806-817,1164-1195`). `_agent_vector_ids` reads exactly that path and
          `_agent_kb_refs` tolerates the older spellings around it.
          WHAT DOES NOT CHANGE is `knowledge_base_refs_readable`'s asymmetry: an agent
          with no knowledge carries no `vector_store` at all, so absence still reads as
          "we could not find it" rather than "the reference was cleared". D-41's question
          is now ANSWERABLE from a payload — which is the change — and the answer is still
          a live-account observation (OPERATIONS §2 gate 8), not a premise.

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
        # BEFORE the snapshot is assembled, for `_check_transfer_leg`'s reason: this is a
        # fact about the agent nothing in `AgentSnapshot` can carry, and the read-back is
        # the only place it is visible. Every publish and every half-hourly drift sweep
        # comes through here, so a console-added route is paged on within the sweep
        # interval rather than on the call where it first answers for us.
        _check_semantic_routes(agent, ref=ref)
        # The same argument one line up, for the other console switch that changes what a
        # caller gets without changing anything `AgentSnapshot` can hold. The PROMPT half
        # of a console-added language reaches `judge` as `alternate_prompts` and refuses
        # the publish; the SPEECH half has no carrier and pages instead.
        _check_multilingual_speech(agent, ref=ref)
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
            # The prompts a CONSOLE-added language would run beside it — see
            # `_agent_alternate_prompts`. Empty for every agent this tree publishes,
            # because `_agent_body` sends `multilingual_config: None`.
            alternate_prompts=_agent_alternate_prompts(agent),
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
        # WHAT WE REMEMBER ABOUT THIS PERSON (D-513), under the ONE key the contract names.
        #
        # VERIFIED-VENDOR-DOCS, read 2 Sep 2026: *"Pass `user_data` to inject variables into
        # your agent's prompt and welcome message (e.g. `{customer_name}` in the prompt
        # becomes 'Asha')"* — `bolna-findings/mirror/pages/api-reference/calls/
        # make.md:32`, with the worked example at `:34-44`.
        # So `CALLER_MEMORY_SLOT` (`{caller_memory}`), which `compose_engine_prompt` put in
        # the agent's prompt at publish, is filled by this entry at dial time.
        #
        # **SENT EVEN WHEN EMPTY, and that is not tidiness.** The token is IN the published
        # prompt for every agent that remembers callers, and the vendor's substitution
        # behaviour for a key their `user_data` does not carry is not documented anywhere in
        # the pinned mirror (OPERATIONS §2 gate 8b). The failure it would produce is the
        # worst-shaped one available: an agent reading the literal string "{caller_memory}"
        # aloud to a first-time caller. An empty string substitutes to nothing on any
        # plausible implementation, so it is what a caller we do not know is worth.
        # ALWAYS PRESENT, empty when there is nothing to say. An agent that does not
        # remember callers carries no token in its prompt, so the key is inert there and
        # costs one short string on the wire; an agent that does carries the token on EVERY
        # call, including the first one from a stranger.
        user_data[CALLER_MEMORY_VARIABLE] = render_caller_memory(ctx.caller_memory)
        # THE CALLER ID, AND THE FIELD'S ABSENCE IS WHAT D-420 IS (symptom 1). Their own
        # outbound guide: *"Add your purchased phone number or your own connected phone
        # number in `from_phone_number` field"*, and omitting it dials from their
        # centralised pool — for an Indian callee, *"a `+91` prefix phone"*
        # (`bolna-findings/mirror/pages/guides/outbound/making-outgoing-calls.md`). So the
        # DLT-registered 140/160-series header the campaign gate approves reached nothing,
        # and the callee, the TSP and the complaint trail saw the vendor's number.
        #
        # OMITTED RATHER THAN SENT NULL when there is none. The field is optional in their
        # documented body and a null on an optional string is the shape a vendor validator
        # is most likely to reject; "no caller ID" is what an ABSENT key already means here,
        # and it is what a single-lead callback from an account with no registered header
        # legitimately wants.
        body: dict[str, Any] = {
            "agent_id": ref,
            "recipient_phone_number": to,
            "user_data": user_data,
        }
        if ctx.from_e164:
            body["from_phone_number"] = ctx.from_e164
        data = await self._request("POST", "/call", json=body)
        handle = data.get("execution_id") or data.get("id")
        if not isinstance(handle, str):
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a call id.",
            )
        return handle

    async def end_call(self, call_id: str) -> RecallOutcome:
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

        **THE VERDICT COMES FROM THEIR RESPONSE, and this method used to throw it away.**
        The route answers `{"status": "stopped", "execution_id": ...}` and its own summary
        says it cancels "pending calls before they are executed"
        (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/api-reference/calls/
        stop_call.md:7,47`). That is the vendor adjudicating the exact question a DNC
        suppression has to answer, and it is available for free on a call we already make —
        no second read, no race with one.

        It is read HERE and nowhere else because it is a vendor payload shape (hard rule
        2), and because after this point the answer is unrecoverable: `_STATUS_MAP` folds
        `stopped` into our `failed` beside `canceled`, `error` and a genuine post-ring
        failure, so a caller inspecting `calls.status` later cannot tell which happened.

        ANY OTHER BODY IS `UNKNOWN`, not `PREVENTED`. A 200 whose `status` we did not
        recognise means the request succeeded and told us nothing about what it caught,
        and silence is not a denial that the phone rang. `_request` raises on a 4xx, so
        the vendor's refusal of an already-running call reaches the caller as the
        exception D-187's clause requires rather than as a verdict.
        """
        data = await self._request("POST", f"/call/{call_id}/stop")
        answered = str(data.get("status") or "").strip().lower() if isinstance(data, dict) else ""
        return RecallOutcome.PREVENTED if answered == _STOPPED_STATUS else RecallOutcome.UNKNOWN

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
        # Nobody buys a number through this product. Model B: the CLIENT holds the
        # connection on their own Exotel / Plivo / Vobiz account and we connect it
        # (`campaigns/provisioning.py`; `docs/legal/LEGAL-OPS-PLAYBOOK.md` §9).
        # `BOLNA_CAPABILITIES.number_series` is empty, so this refuses every series
        # rather than only the DLT ones.
        require_capability("numbers", engine=self)
        # Unreachable while `number_series` is empty. Kept as a real refusal rather than
        # an `assert`, because the way this line gets reached is somebody widening the
        # descriptor without writing the client — and that must fail loudly here rather
        # than fall off the end of the function returning None.
        raise ProblemError(
            kind="dependency",
            code="engine_capability_unverified",
            title="The voice platform does not supply numbers",
            detail=(
                "The client's calling number is taken on their own operator account and "
                "connected to the platform; nothing here buys one."
            ),
        )

    # --- inbound routing (D-420) ---------------------------------------------
    #
    # WHAT THE VENDOR DOCUMENTS AND WHAT IS STILL OPEN, in one place so neither method
    # repeats it. `POST /inbound/setup` binds `{agent_id, phone_number_id}` and
    # `POST /inbound/unlink` releases `{phone_number_id}`; both answer with an
    # `InboundAgentResponse` we deliberately do not read — the postcondition is a fact about
    # the engine's routing table, not a body, and the next drift sweep is what would catch a
    # 200 that changed nothing (`bolna-findings/mirror/pages/api-reference/inbound/agent.md`,
    # `.../unlink.md`).
    #
    # ⚠ **`phone_number_id` HAS THREE DOCUMENTED SHAPES AND WE DO NOT PICK ONE.** Their
    # inbound page types it a dashed UUID, `phone-numbers/get_all.md` types the SAME field
    # `^[0-9a-fA-F]{32}$` (bare hex), and `byot-setup.md` returns a ULID-looking
    # `01HQNUMBER111222333`. So this adapter sends `engine_number_ref` VERBATIM and asserts
    # nothing about its format: whatever the vendor's own listing hands back is what
    # `phone_numbers.engine_number_ref` holds and what goes back out. A validator here would
    # be this repository inventing a vendor contract, and would refuse the very value the
    # vendor issued. OPERATIONS §2 gate 25 settles the format and whether a non-Twilio
    # Indian number binds at all.

    def _inbound_number_id(self, number: ProvisionedNumber) -> str:
        """The vendor's handle for `number`, or a refusal naming what is missing.

        A NUMBER WITH NO `engine_number_ref` IS NOT AN ERROR TO RETRY — it is the ordinary
        state of every number today, because D-05 buys numbers FROM THE TELEPHONY VENDOR
        directly and nothing has ever introduced one to the engine (this adapter's
        `provision_number` refuses, `BOLNA_CAPABILITIES.number_series` is empty). So the
        refusal names the missing onboarding step and carries a remediation a person can
        act on, rather than POSTing a null the vendor would answer 400 to.

        Its own code rather than `engine_capability_absent`: the engine HAS inbound
        binding, and this deployment has not given it the number — different cause,
        different fix, different person, exactly the split `engine_caller_id_not_configured`
        already makes against `engine_not_configured`.
        """
        if number.engine_number_ref:
            return number.engine_number_ref
        raise ProblemError(
            kind="dependency",
            code="engine_number_not_linked",
            title="This number is not known to the voice platform",
            # Hard rule 6: the number's identity is the vendor handle we do NOT have, and
            # the E.164 never appears in a message, a log line or an alarm.
            detail=(
                "The voice platform has no record of this phone number, so no agent can be "
                "set to answer it."
            ),
            remediation=(
                "Connect the number to the voice platform account first, then assign the "
                "agent again."
            ),
        )

    async def bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None:
        """`POST /inbound/setup` — make `ref` the agent that answers this number.

        `allow_multiple` and `ivr_config` are NOT sent. Both are documented Plivo-only
        options and neither is a thing this product has decided: `allow_multiple` widens a
        binding we deliberately keep one-to-one (`phone_numbers.agent_id` is a single
        column, and a number answered by two agents has no answer to "which script ran"),
        and an IVR menu in front of an AI receptionist is a product decision with a
        disclosure question attached, not a default. Omitting them takes the vendor's own
        defaults, which is the same discipline `_agent_body` applies everywhere else.
        """
        require_capability("inbound_binding", engine=self)
        await self._request(
            "POST",
            "/inbound/setup",
            json={"agent_id": ref, "phone_number_id": self._inbound_number_id(number)},
        )

    async def unbind_inbound_number(self, number: ProvisionedNumber) -> None:
        """`POST /inbound/unlink` — nothing of ours answers this number any more.

        `absent_is_success=True`: the postcondition is that no agent answers, and a number
        the platform does not hold already satisfies it. The Protocol says so; the reason it
        is spelled here as well is that this is an OFFBOARDING path, and a step that raises
        on "there was nothing to undo" is a step that blocks the release of a number the
        client has stopped paying for.
        """
        require_capability("inbound_binding", engine=self)
        await self._request(
            "POST",
            "/inbound/unlink",
            absent_is_success=True,
            json={"phone_number_id": self._inbound_number_id(number)},
        )

    # --- the LLM credential (D-404, no longer rotating since D-410) -----------
    #
    # THE OPERATION SURVIVED THE SCHEDULE. It was built for a Vertex bearer that expired
    # in twelve hours and was replaced every four by a cron of ours; Azure OpenAI takes a
    # STATIC key, so the refresher, its dead man and its runbook are deleted and the
    # caller is now a person rotating a key. Nothing below changes for that — see the
    # Protocol's note on `set_llm_credential` — but two things read differently and are
    # corrected in place rather than left to a reader to reconcile: "the refresher" is an
    # operator, and append semantics went from bad to WORSE, because a superseded bearer
    # at least expired on its own and a superseded API key does not.

    async def _llm_credential_ids(self, name: str) -> set[str]:
        """The `provider_id`s the store currently holds under `name`.

        `GET /providers` returns a `ProviderList` — an array, which `vendor_request`
        wraps as `{"data": [...]}` — of `{provider_id, provider_name, provider_value}`
        where **`provider_value` is MASKED** (the spec's own example is `xxxxxxxaz`).
        That masking is why identity is read off `provider_id` and never off the value:
        the store will not tell us which bearer it is holding, only how many.
        """
        listing = await self._request("GET", "/providers")
        rows = listing.get("data")
        if not isinstance(rows, list):
            return set()
        return {
            str(row["provider_id"])
            for row in rows
            if isinstance(row, dict)
            and row.get("provider_name") == name
            and row.get("provider_id") is not None
        }

    @staticmethod
    def _credential_entry_name(provider: LlmProvider) -> str:
        """The store entry name this leg's secret goes under.

        **ONE LEG HAS A LIVE OVERRIDE AND TWO DO NOT, AND THAT ASYMMETRY IS EVIDENCE-SHAPED
        RATHER THAN ARBITRARY.** `Settings.bolna_llm_credential_name` exists because D-417
        found the Azure name had been guessed (`AZURE`) and shipped wrong, and the operator
        who discovers a live account wants something else is looking at a broken leg while
        they correct it — a deploy is the wrong length of loop for that. It defaults to the
        vendor's documented `AZURE_OPENAI_API_KEY` and stays a setting for that reason.

        ⚠ **IT DOES NOT COVER THE OTHER TWO LEGS, AND MUST NOT BE MADE TO.** It is ONE
        string; three legs need three names, and a single override applied to whichever leg
        happened to call would rename the wrong entry. `OPENAI` and `GOOGLE` come straight
        from the vendor's table. **The OpenAI one is disputed** — two of their pages say
        `OPENAI` and `OPENAI_API_KEY` — and the ground for taking `OPENAI` is written at
        `_LLM_PROVIDER_KEYS`; if a live account disagrees, the fix is that table, one string,
        with the reading that settled it. That is a smaller and more honest surface than a
        per-leg settings field nobody has needed yet.

        Read per call rather than copied at construction: the adapter is cached per process,
        so a constructor copy would make the setting's `applies: live` classification a lie.
        This runs once per key rotation; the read costs nothing.
        """
        if provider == "azure_openai":
            return get_settings().bolna_llm_credential_name
        return _LLM_CREDENTIAL_KEY[provider]

    async def set_llm_credential(
        self, secret: str, *, provider: LlmProvider
    ) -> LlmCredentialPlacement:
        """Write ONE leg's in-call LLM credential into Bolna's credential store (D-404/D-410).

        VERIFIED-OAS (`bolna-ai/skills@28b24aa`, `references/openapi.yml`, md5
        5597f7da080d47564696bc05c12e9112 — re-downloaded and re-hashed 18 Aug 2026, so
        the pin is a re-read rather than a citation): `POST /providers` takes
        `{provider_name, provider_value}`, `GET /providers` lists them with the value
        MASKED, and `DELETE /providers/{provider_key_name}` removes one. **The vendor's
        own published OpenAPI now says the same thing** (VERIFIED-VENDOR-DOCS,
        `bolna-findings/mirror/pages/api-reference/providers/{overview,add,get,remove}.md`):
        the store is a FLAT `provider_name` → `provider_value` map with no per-provider
        object and no way to write several fields in one call, which is what makes the
        four-key requirement below four separate installs rather than one structured one.

        **WHICH ENTRY IT WRITES DEPENDS ON THE LEG, AND SO DOES HOW MUCH OF THE LEG IT
        FINISHES** — `_LLM_PROVIDER_KEYS` is the table and `llm_provider_keys()` is what an
        operator runbook reads. The vendor's own store wants FOUR entries for Azure OpenAI
        (`AZURE_OPENAI_API_KEY`, `_MODEL`, `_API_BASE`, `_API_VERSION`, and "all these keys
        must be added"), ONE named `OPENAI` for OpenAI direct, and ONE named `GOOGLE` for
        Gemini. This method writes exactly the FIRST of each — the secret — which means:

        * on the two single-entry legs it installs the WHOLE leg, and there is nothing left
          for a human to do in the vendor's console;
        * on Azure it installs one of four, deliberately. Three of the four are values this
          repository holds, but the fourth (`AZURE_OPENAI_API_VERSION`) has no derivable
          value and the vendor's two pages disagree about whether it is needed at all — so
          installing three of four automatically would leave the provider incomplete while
          REPORTING success, which is the failure this method's whole count-before/count-after
          design exists to avoid. The key is the one value that must never be typed into a
          console by a human, so it is the one that is pushed; the rest are the operator's,
          and gate 16f is where they are recorded once the account exists.

        **THE ARGUMENT IS REQUIRED AND HAS NO DEFAULT** (see the Protocol). One store, three
        legs, three entry names: a caller who did not say which leg they were rotating would
        overwrite one leg's key with another leg's secret and get a green result for it.

        **WHY THIS IS A THREE-CALL DANCE AND NOT ONE POST**, which is the whole design
        question here. The POST response's `status` enum has exactly one member,
        `"added"` — there is no `"updated"` — so the spec DOCUMENTS an add and says
        nothing about what a second add under the same name does. Three behaviours are
        possible and they are not equally survivable:

        * **Replace in place.** The happy case, and what a credential store usually does.
        * **Append.** The store ends up holding the fresh credential AND every superseded
          one, and WHICH of them a call authenticates with is the vendor's choice.
          **D-410 made this the worst of the three rather than the middle one.** Under a
          rotating Vertex bearer the stale copies expired on their own, so append cost us
          a confusing outage twelve hours later; under a STATIC Azure key a superseded
          copy an operator believes they revoked goes on authenticating our spend
          indefinitely, and the revocation they performed in the Azure portal is the only
          thing that ends it.
        * **Refuse the duplicate.** Loud, and handled by the ladder as `engine_rejected`.

        So we COUNT BEFORE AND AFTER and clean up what we find, using only documented
        routes. The reward is that the answer to "which semantics does the live platform
        have" arrives as DATA from the first install instead of as a reviewer's guess —
        the same move `_snapshot` makes for gate 16. `LlmCredentialPlacement` is how it
        reaches the log.

        WHY POST-THEN-DELETE AND NEVER DELETE-THEN-POST. The obvious spec-clean order is
        "remove the old entry, add the new one". It is wrong on the only axis that
        matters: between the two calls the engine holds NO credential, so a POST that
        fails after a successful DELETE takes the LLM leg down IMMEDIATELY — and with a
        static key there is no expiry deadline making the other order urgent, so the
        argument only got stronger. Post-first is strictly safer: the worst case is a
        duplicate we then remove, and the second-worst is a duplicate we log.

        THE SECRET IS NEVER LOGGED, and nothing here puts it in an exception: the ladder
        in `vendor_http` logs status and route only, and this method's own log lines carry
        a name, two counts and a verdict. `extra=` never sees the value (hard rule 6 is
        about PII; a credential is the one thing whose leak is worse).
        """
        # An engine whose LLM leg it DICTATES has no credential of ours to hold, and a
        # silent no-op there would be an install reporting green forever about somebody
        # else's model. `has("llm")` is `is_ours("llm")` — see the Protocol's note on why
        # this is that gate rather than a capability flag of its own.
        require_capability("llm", engine=self)
        # See `_credential_entry_name` for why the Azure leg alone consults a setting.
        name = self._credential_entry_name(provider)
        before = await self._llm_credential_ids(name)
        await self._request(
            "POST", "/providers", json={"provider_name": name, "provider_value": secret}
        )
        after = await self._llm_credential_ids(name)

        superseded = before & after
        if not superseded:
            # Replace-in-place (or a first install): the ids under our name did not
            # survive the write, so the store swapped the entry.
            log.info(
                "engine_llm_credential_installed",
                extra={"engine": self.name, "credential": name, "held": len(after)},
            )
            return LlmCredentialPlacement(replaced_in_place=True)

        # APPEND SEMANTICS. Every id that was there before AND is still there is a
        # superseded copy, because the entry we just wrote cannot be one of them. Removal
        # is by NAME — the vendor's delete is `/providers/{provider_key_name}`, which
        # addresses the name and not the id — so we cannot remove them individually, and
        # deleting by name would take our fresh one with them.
        #
        # NOT SILENTLY TOLERATED. This is an alarm rather than a cleanup, and the reason
        # is the docstring's second bullet: a store holding several keys under one name
        # authenticates calls with one of them at its own discretion, so the leg's health
        # stops being a function of anything we do. It is reported as a REFUSAL of the
        # install, which is exactly right — the install did not achieve its purpose.
        log.warning(
            "engine_llm_credential_appended",
            extra={
                "engine": self.name,
                "credential": name,
                "superseded": len(superseded),
                "held": len(after),
            },
        )
        raise ProblemError(
            kind="dependency",
            code="engine_credential_not_replaced",
            title="The voice platform kept the superseded LLM credential",
            detail=(
                "The credential store appended the new value beside the old one instead "
                "of replacing it, so which credential a call uses is no longer ours to "
                "decide."
            ),
            remediation=(
                "Remove the stale entry in the vendor console, then install the key "
                "again. Revoke the superseded key in the Azure portal as well — a static "
                "key the store kept goes on working until it is revoked at the source."
            ),
            failure_stage="CORE_LOGIC",
        )

    # --- knowledge base ------------------------------------------------------
    #
    # THE SHAPE OF THIS FEATURE IN ONE PARAGRAPH, because it is not the shape the port
    # suggests. The vendor's knowledge base is an ACCOUNT-LEVEL object with four routes
    # and no agent field (`bolna-findings/mirror/pages/api-reference/knowledgebase/
    # overview.md:11-16`); the LINKAGE is a list of `vector_ids` on the AGENT. So an
    # attach is two writes to two objects, a detach is the same two in reverse, and the
    # handle this adapter hands back is the identifier BOTH halves can be addressed by.
    # See `attach_kb` for why that is the vector id and not the `rag_id` a create returns.

    async def _kb_row(self, rag_id: str) -> dict[str, Any]:
        """`GET /knowledgebase/{rag_id}` -> the row, which is the only place `vector_id`
        appears (`.../knowledgebase/get_knowledgebase.md:81-93`)."""
        return await self._request("GET", f"/knowledgebase/{rag_id}")

    async def _await_kb_processed(self, rag_id: str) -> EngineKBRef:
        """Poll until the upload is `processed`, then answer its `vector_id`.

        THE THREE OUTCOMES ARE ALL NAMED, and the middle one is why this is a loop rather
        than a second GET. `processing` is what a create RETURNS, so the vector id does
        not exist yet; `error` is a real vendor verdict on a document we uploaded and must
        never be read as "not ready yet"; and a `processed` row with no `vector_id` is a
        response we cannot use, not an empty result.

        `asyncio.sleep` between looks, deliberately not a backoff ladder: this is one
        object becoming ready on a clock we do not control, not a contended resource, and
        a doubling interval would spend most of a three-minute budget asleep past the
        moment it became usable.
        """
        deadline = monotonic() + KB_READY_TIMEOUT_S
        while True:
            row = await self._kb_row(rag_id)
            status = str(row.get("status") or "").lower()
            if status == KB_STATUS_ERROR:
                raise ProblemError(
                    kind="dependency",
                    code="engine_kb_processing_failed",
                    title="The voice platform could not read that knowledge document",
                    detail=(
                        "The voice platform accepted the document and then failed to "
                        "index it, so the agent would not be able to answer from it."
                    ),
                    remediation=(
                        "Nothing is live from this version. Check the wording for "
                        "anything unusual and submit it again; if it happens twice the "
                        "platform is rejecting the document itself and support must look."
                    ),
                    failure_stage="CORE_LOGIC",
                )
            if status == KB_STATUS_PROCESSED:
                vector_id = row.get("vector_id")
                if isinstance(vector_id, str) and vector_id:
                    return vector_id
                # PROCESSED AND UNADDRESSABLE. Not a wait: their own schema declares
                # `vector_id` on this row, so its absence is a response we cannot use, and
                # sleeping on it would burn the whole budget to report the wrong cause.
                raise ProblemError(
                    kind="dependency",
                    code="engine_bad_response",
                    title="Voice engine returned an unusable response",
                    detail="The voice platform indexed the document but named no vector id.",
                    failure_stage="CORE_LOGIC",
                )
            if monotonic() >= deadline:
                raise ProblemError(
                    kind="dependency",
                    code="engine_kb_processing_timeout",
                    title="The voice platform is still indexing that knowledge",
                    detail=(
                        "The document was uploaded but the platform has not finished "
                        "indexing it, so it cannot be attached yet."
                    ),
                    remediation=(
                        "Nothing changed: the previously approved version is still live. "
                        "Try publishing again in a few minutes."
                    ),
                    failure_stage="CORE_LOGIC",
                )
            await asyncio.sleep(KB_READY_POLL_INTERVAL_S)

    async def _kb_account_rows(self) -> tuple[list[dict[str, Any]], ListingIncompleteReason | None]:
        """Every knowledge base on the ACCOUNT, walked to the end of its pages.

        **THIS LISTING IS PAGINATED AND `_rag_id_of` ASKED FOR ONE PAGE (D-519), WHICH IS
        D-421'S DEFECT ON A SECOND ROUTE.** The same two first-party pages govern it:

            `bolna-findings/mirror/pages/api-reference/pagination.md:9,13-14` — "The
            endpoints also support pagination using the `page_number` and `page_size`
            query parameters ... `page_number` ... Defaults to `1` ... `page_size` ...
            Defaults to `20`. You can request up to `50` results per page."

        and the route's own OpenAPI block, which declares NO parameters and answers a
        bare `KnowledgebaseList` array with no `has_more` and no `total`
        (`.../knowledgebase/get_knowledgebases.md:29-51,63-121`).

        WHY IT WAS WORSE HERE THAN ON THE AGENT ROSTER. One Bolna account holds every
        tenant's knowledge bases and each PUBLISHED VERSION of each named source is its
        own object (there is no update route — `.../knowledgebase/overview.md:11-16`), so
        the 21st object is a handful of documents rather than a handful of clients. Past
        it, `_rag_id_of` answered `None` for a knowledge base the account really holds,
        `detach_kb` raised "the voice platform does not hold that knowledge base" — a
        false statement about a live object — and `kb/service._detach_superseded` turned
        it into `kb_detach_failed`, whose remediation is "try publishing again". Every
        retry would fail the same way, and the account's oldest documents are the ones
        that stop being addressable first. That is a client's knowledge frozen with a
        message that says otherwise.

        SAFE UNDER BOTH READINGS, exactly as `_agent_refs` is: if the platform honours
        `page_number` this walks to the end; if it IGNORES it, page two repeats page one,
        the de-duplication sees no new `rag_id` and the walk stops. De-duplication is on
        `rag_id` because that is the object's own id and the one field their listing
        schema declares as the ID (`get_knowledgebases.md:63-70`); `vector_id` is absent
        from a row that is still `processing`.

        The verdict is returned rather than swallowed: a caller that must not mistake
        "we could not finish looking" for "the account does not hold it" needs the
        difference, and `_rag_id_of` is exactly that caller.
        """
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        reason: ListingIncompleteReason | None = None
        page_number = 1
        while True:
            payload = await self._request(
                "GET",
                "/knowledgebase/all",
                params={"page_number": page_number, "page_size": _LISTING_PAGE_SIZE},
            )
            page = _listing_rows(payload)
            new_rows = 0
            for row in page:
                # DEDUPED ON `rag_id` WHERE THERE IS ONE, ON `vector_id` WHERE THERE IS
                # NOT — AND A ROW WITH NEITHER IS STILL RETURNED. Skipping a row for
                # having no usable `rag_id` (which this loop did) put D-516's defect back
                # one layer down: the row never reached `_rag_id_of`, so a match on
                # `vector_id` came back as "the account does not hold it", the publisher
                # was told the document was already gone, and nothing was deleted. The
                # dedupe key is an implementation detail of walking pages; it may not
                # decide what a caller is allowed to see.
                rag_id = row.get("rag_id")
                vector_id = row.get("vector_id")
                key = (
                    rag_id
                    if isinstance(rag_id, str) and rag_id
                    else vector_id
                    if isinstance(vector_id, str) and vector_id
                    else None
                )
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                rows.append(row)
                new_rows += 1
            # A short page ends the account and cannot be hiding anything — the vendor
            # returned fewer rows than we asked for. The only exit that claims completeness.
            if len(page) < _LISTING_PAGE_SIZE:
                break
            if new_rows == 0:
                reason = "next_link_no_progress"
                break
            if page_number >= _LISTING_MAX_PAGES:
                reason = "page_cap_reached"
                break
            page_number += 1
        return rows, reason

    async def _rag_id_of(self, vector_id: EngineKBRef) -> str | None:
        """Our handle -> the id the DELETE route takes, or None if the account holds no
        such knowledge base.

        `GET /knowledgebase/all` is the ONLY route carrying both identifiers on one row
        (`bolna-findings/mirror/pages/api-reference/knowledgebase/
        get_knowledgebases.md:63-94`), and there is no route that reads a knowledge base
        BY vector id, which is the whole reason a listing is fetched here rather than a
        row.

        None is a real answer and the caller must treat it as one: it means the engine
        does not hold that knowledge base, which for `detach_kb` is the 404 the Protocol
        says must RAISE rather than pass quietly.

        **AND THAT IS PRECISELY WHY AN UNFINISHED WALK MAY NOT ANSWER `None` (D-519).**
        A listing we could not finish is not evidence of absence, and turning it into one
        deletes a client's ability to republish (see `_kb_account_rows`). So a miss on a
        walk that stopped early RAISES a dependency error naming the cause, which
        `_detach_superseded` reports as a refusal to publish — the client keeps the
        version a human approved and loses only the update.
        """
        rows, reason = await self._kb_account_rows()
        for row in rows:
            if row.get("vector_id") == vector_id:
                rag_id = row.get("rag_id")
                if isinstance(rag_id, str) and rag_id:
                    return rag_id
                # A MATCH CARRYING NO USABLE `rag_id` IS A BAD RESPONSE, NOT AN ABSENCE
                # (D-516). `rag_id` is declared on this row
                # (`.../knowledgebase/get_knowledgebases.md:65-70`), so a match without
                # one is the vendor answering something we cannot act on. Returning
                # `None` here — which this line did — reported it to the publisher as
                # "already gone" and then deleted nothing: the second of the two lies
                # D-516 found in these six lines, and the one that survives an unpaged
                # walk being fixed.
                raise ProblemError(
                    kind="dependency",
                    code="engine_bad_response",
                    title="The voice platform described a knowledge base it cannot identify",
                    detail=(
                        "The platform listed this knowledge base without the identifier "
                        "needed to remove it, so it cannot be detached right now."
                    ),
                    remediation="Try again in a few minutes.",
                    failure_stage="CORE_LOGIC",
                )
        if reason is not None:
            log.error("kb_account_listing_incomplete", extra={"reason": reason})
            raise ProblemError(
                kind="dependency",
                code="engine_kb_listing_incomplete",
                title="The voice platform's knowledge list could not be read to the end",
                detail=(
                    "The platform did not finish listing the knowledge bases on this "
                    "account, so we cannot tell whether it still holds this one."
                ),
                remediation="Try again in a few minutes.",
                failure_stage="CORE_LOGIC",
            )
        return None

    async def _current_vector_ids(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        """What the AGENT references right now. The engine's answer, not our records."""
        return _agent_vector_ids(_agent_object(await self._request("GET", f"/v2/agent/{ref}")))

    async def _write_vector_ids(
        self, ref: EngineAgentRef, cfg: AgentConfig, vector_ids: Sequence[EngineKBRef]
    ) -> None:
        """The agent half of an attach or a detach: one full-replacement PUT.

        `cfg` IS THE CALLER'S AND CANNOT BE DERIVED HERE, which is the whole reason the
        port carries it (D-488). `PATCH` cannot write `tasks` at all (see `update_agent`),
        so the write is a `PUT` -- and a `PUT` body assembled from `GET /v2/agent/{id}`
        would drop `agent_welcome_message` and `webhook_url`, neither of which is declared
        on the `AgentV2` response (`.../agent/v2/get.md:54-97`). The first is the sentence
        the agent VOLUNTEERS, the AI disclosure and the recording notice (hard rule 5,
        D-163); the second is how we ever hear that a call happened. Publishing knowledge
        is not permitted to cost either.
        """
        await self._request(
            "PUT", f"/v2/agent/{ref}", json=self._agent_body(cfg, vector_ids=vector_ids)
        )

    def _kb_agent_config(self, agent: AgentConfig | None) -> AgentConfig:
        """The caller's configuration, or a named refusal.

        A DEFAULT IS UNTHINKABLE HERE and the check is free, so this is a guard rather
        than an `assert`: the way it gets reached is a caller that has not been taught the
        linkage is an agent write, and the failure it prevents is an adapter publishing an
        agent body it made up.
        """
        if agent is not None:
            return agent
        raise ProblemError(
            kind="dependency",
            code="engine_kb_agent_config_required",
            title="This voice platform needs the agent's configuration",
            detail=(
                "The voice platform stores knowledge attachments on the agent itself, "
                "so attaching or removing one is a change to the agent."
            ),
            failure_stage="CORE_LOGIC",
        )

    async def _delete_kb_quietly(self, rag_id: str) -> None:
        """Best-effort removal of a knowledge base we created and could not use.

        SWALLOWS, AND SAYS SO AT ERROR. It runs on a path that is already failing, and
        raising here would replace a diagnosable cause with a cleanup error. What it must
        never do is disappear: the residue is a billed document nothing of ours can reach,
        so an operator is told by name and the drift sweep reports the agent as holding
        knowledge we cannot account for.
        """
        try:
            await self._request("DELETE", f"/knowledgebase/{rag_id}", absent_is_success=True)
        except Exception as exc:  # the caller's failure is the one to report, not this cleanup's
            log.error("kb_orphan_left_on_engine", extra={"engine_error": type(exc).__name__})

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        """Upload the approved document, wait for it, and make the agent reference it.

        **THIS CAPABILITY WAS `False` AND THE IMPLEMENTATION BEHIND IT COULD NEVER HAVE
        WORKED (D-354). D-488 BUILT THE REAL ONE.** Four steps, and the order is the
        design:

        1. `POST /knowledgebase`, `multipart/form-data`, `file` = the RENDERED DOCUMENT
           (`.../knowledgebase/create.md:29-80`). The old body was JSON `{agent_id, name,
           text}`; the route accepts neither an agent id nor prose.
        2. Wait for `processed` and read `vector_id` (`_await_kb_processed`). The create
           response carries no vector id at all, so this is not a nicety: it is where the
           usable identifier comes from.
        3. PUT the agent with the new vector id ADDED to the ones it already references.
           Read-then-write, and the read is the ENGINE's list rather than our records --
           our records can be stale, the engine's list is what the caller hears.
        4. Return the VECTOR ID as the handle.

        WHY THE VECTOR ID AND NOT THE `rag_id`, which is what a create returns and what
        `DELETE` takes. The handle's whole job is to answer "is this still attached", and
        the only thing an AGENT carries is a vector id -- so a `rag_id` handle would make
        `AgentSnapshot.references_kb` compare two different namespaces and answer False
        for every attached document, reporting "the reference is cleared" on no evidence.
        That is D-41's question answered the comfortable way, which is a failure this
        adapter has already shipped once. The `rag_id` is recoverable when it is needed
        (`_rag_id_of`), and it is needed exactly once, in `detach_kb`.

        NOTHING IS LEFT BEHIND WHEN A LATER STEP FAILS. Steps 2 and 3 can both fail after
        the upload has succeeded, and a knowledge base nothing references is billed for as
        long as the account exists. So the upload is compensated: the document is deleted
        and the ORIGINAL failure re-raised, never replaced by the cleanup's.

        WHAT THIS METHOD DOES NOT DO IS DE-DUPLICATE. There is no update route on this
        object (`.../knowledgebase/overview.md:11-16`), so every call is a CREATE and the
        engine has no idea two uploads describe one source of ours. Not re-uploading
        unchanged content is the publisher's job and is keyed on `KBSourceRef
        .content_sha256`; an adapter cannot do it, because the only account-wide thing it
        could compare is `file_name`, which is ours and identical across versions.
        """
        require_capability("knowledge_base", engine=self)
        cfg = self._kb_agent_config(agent)
        document = source.document
        if not document:
            # THE ONE THING THIS ADAPTER MAY NOT DO IS RENDER ONE ITSELF. What a human
            # approved is text; turning it into a document is a decision about an approved
            # artefact, and hard rule 2 puts everything on this side of the wall out of
            # reach of the gates that check approvals. See `KBSourceRef`.
            raise ProblemError(
                kind="dependency",
                code="engine_kb_document_missing",
                title="This voice platform needs a document, not text",
                detail=(
                    "The voice platform's knowledge base ingests documents, and nothing "
                    "rendered one for this version."
                ),
                failure_stage="CORE_LOGIC",
            )
        if len(document) > KB_MAX_DOCUMENT_BYTES:
            # Refused here rather than at the vendor: a 400 would go through the throttle
            # ladder as a transient fault and be retried, three times, with the same
            # oversized body.
            raise ProblemError(
                kind="validation",
                code="kb_document_too_large",
                title="That knowledge source is too large to publish",
                detail=(
                    f"The rendered document is {len(document) // (1024 * 1024)} MB and the "
                    f"voice platform accepts at most "
                    f"{KB_MAX_DOCUMENT_BYTES // (1024 * 1024)} MB."
                ),
                remediation="Split it into two knowledge sources and publish them separately.",
                status=422,
            )
        created = await self._request(
            "POST",
            "/knowledgebase",
            # `files=` not `json=`: the route is `multipart/form-data`. The filename is
            # OURS and carries no caller data -- the vendor echoes it back as `file_name`
            # and shows it in their console, so it names the source, never a client's data.
            #
            # THE PART IS `bytes`, NOT A FILE OBJECT, AND THAT IS LOAD-BEARING RATHER THAN
            # convenient: `vendor_request` retries through the throttle ladder, and a file
            # object is consumed by the first attempt — the retry would upload ZERO bytes
            # and the vendor would index an empty document without either side erroring.
            #
            # ⚠ WHAT THE LADDER CAN STILL DO, and it has no fix at this layer: a create
            # that SUCCEEDED and whose response was lost is retried, and the account ends
            # up with two knowledge bases where one is referenced. There is no idempotency
            # key on this route to prevent it. The second is an orphan — money, invisible
            # to `list_kb`, and gate 43e's subject.
            files={"file": (_kb_filename(source), document, "application/pdf")},
            data={
                "chunk_size": str(KB_CHUNK_SIZE),
                "overlapping": str(KB_OVERLAPPING),
                "similarity_top_k": str(KB_SIMILARITY_TOP_K),
                "language_support": KB_LANGUAGE_SUPPORT,
            },
        )
        rag_id = created.get("rag_id")
        if not isinstance(rag_id, str) or not rag_id:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a knowledge base id.",
                failure_stage="CORE_LOGIC",
            )
        if str(created.get("status") or "").lower() == KB_STATUS_ERROR:
            # Answered on the create itself: their create response declares `error` in its
            # status enum, and treating it as "not ready" would poll a dead object for
            # three minutes and then report a timeout instead of the refusal it is.
            await self._delete_kb_quietly(rag_id)
            raise ProblemError(
                kind="dependency",
                code="engine_kb_processing_failed",
                title="The voice platform could not read that knowledge document",
                detail="The voice platform rejected the document as unreadable.",
                failure_stage="CORE_LOGIC",
            )
        try:
            vector_id = await self._await_kb_processed(rag_id)
            await self._write_vector_ids(
                ref, cfg, [*await self._current_vector_ids(ref), vector_id]
            )
        except Exception:
            # COMPENSATE, THEN RE-RAISE THE ORIGINAL. The document is uploaded and nothing
            # references it; leaving it is a permanent line on the bill for text no agent
            # can reach. The compensation must not become the reported error -- the caller
            # needs to know the attach failed, not that a cleanup did.
            await self._delete_kb_quietly(rag_id)
            raise
        return vector_id

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        """Stop the agent referencing this knowledge, then delete it. In that order.

        THE ORDER IS THE ONE THING THAT CANNOT BE GOT WRONG TWICE. Delete first and a
        crash before the agent write leaves the agent pointing at a vector that no longer
        exists -- D-41's dangling handle, on a live call path, with no route that repairs
        it except a republish nobody knows is needed. Un-reference first and a crash
        leaves an unreferenced document: money, visible to the drift sweep, and removable
        at any later time.

        A HANDLE THE ENGINE DOES NOT HOLD RAISES, as the Protocol requires. The
        publisher's next act is to attach a replacement, and "the old text is gone" is a
        claim it is entitled to have proven rather than inferred from a 200.
        """
        require_capability("knowledge_base", engine=self)
        cfg = self._kb_agent_config(agent)
        rag_id = await self._rag_id_of(kb)
        if rag_id is None:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform does not hold that knowledge base.",
                failure_stage="CORE_LOGIC",
            )
        remaining = [handle for handle in await self._current_vector_ids(ref) if handle != kb]
        await self._write_vector_ids(ref, cfg, remaining)
        # `absent_is_success` for `delete_agent`'s reason and no other: the reference is
        # already gone, so a knowledge base that vanished between the listing above and
        # this call has reached this method's postcondition by another route.
        await self._request("DELETE", f"/knowledgebase/{rag_id}", absent_is_success=True)

    async def list_account_kb(self) -> AccountKBListing:
        """Every knowledge base on the account, with our own source id where we can read it.

        `GET /knowledgebase/all`, walked (`_kb_account_rows`). The account is shared by
        every tenant and the row carries no owner of any kind — `Knowledgebase` declares
        `rag_id`, `file_name`, `humanized_created_at`, `created_at`, `updated_at`,
        `vector_id`, `status`, `chunk_size`, `similarity_top_k` and `language_support`
        (`.../knowledgebase/get_knowledgebases.md:63-121`) — so the attribution has to
        come from something WE put on the object.

        **THAT SOMETHING IS THE FILE NAME, AND IT IS OURS RATHER THAN THE CLIENT'S.**
        `_kb_filename` sends `calevate-kb-<our source id>.pdf` and the vendor echoes it
        back on every listing row, which turns their flat pool into something attributable
        even when the transaction that should have recorded the handle rolled back. It is
        a claim and not proof, which is why it crosses as `claimed_source_id` and why
        `kb/orphans.py` still checks it against our own rows: a name is not a record.

        `vector_id` is absent from a row that is still `processing`, so `handle` is None
        there rather than invented — an object with no reference-able id is exactly what a
        publish in flight looks like, and reporting it as attachable would be a lie the
        orphan report acts on.

        THE STATUS ENUM ON THIS ROUTE IS `processing | processed` AND `error` IS NOT IN IT
        (`get_knowledgebases.md:95-101`), while the single-row read and the create both
        declare `error` as well. Both are mapped: a state their listing schema does not
        promise is still a state their platform has a name for, and dropping it here would
        turn a failed upload into `unknown` on the one surface that has to explain what is
        lying around.
        """
        require_capability("knowledge_base", engine=self)
        rows, reason = await self._kb_account_rows()
        objects = [
            AccountKBObject(
                handle=row["vector_id"] if isinstance(row.get("vector_id"), str) else None,
                claimed_source_id=_source_id_from_kb_filename(row.get("file_name")),
                state=_KB_STATES.get(str(row.get("status") or "").lower(), "unknown"),
                created_at=_parse_dt(row.get("created_at")),
            )
            for row in rows
        ]
        return AccountKBListing(objects=objects, complete=reason is None, incomplete_reason=reason)

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        """The vector ids this AGENT references -- one `GET /v2/agent/{id}`.

        **IT USED TO READ THE ACCOUNT LISTING AND FILTER ON `row["agent_id"]`, WHICH THE
        VENDOR'S ROW DOES NOT HAVE (D-354).** `Knowledgebase` declares `rag_id`,
        `file_name`, `humanized_created_at`, `created_at`, `updated_at`, `vector_id`,
        `status`, `chunk_size`, `similarity_top_k` and `language_support`, and nothing
        else (`.../knowledgebase/get_knowledgebases.md:63-121`). So the filter matched
        nothing, every agent listed `[]` forever, and `kb/reconciliation` read that as the
        positive claim "the engine holds no documents for this agent" -- silent drift by
        construction, and the reason this method was made to refuse rather than answer.

        The linkage was never on the knowledge base; it is on the agent. Reading it THERE
        is both correct and one round trip instead of an account-wide listing that grows
        with every source every client publishes.
        """
        require_capability("knowledge_base", engine=self)
        return await self._current_vector_ids(ref)

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
        inbound = raw_direction == "inbound"
        duration_s = int(duration) if isinstance(duration, int | float) else None
        from_e164, to_e164 = _party_numbers(payload, telephony, inbound=inbound)
        # SCORED HERE RATHER THAN INSIDE `_cost`, because the judgement needs the call's
        # LENGTH and `_cost` sees only the cost keys. Every path that produces a snapshot
        # runs it — the poller's listing as well as `get_execution` — which is what makes
        # it an alarm rather than a check somebody has to remember to call. Repeats are
        # bounded by `alerting`'s per-fingerprint suppression, so a fleet metering wrong
        # pages once per 15 minutes with the count riding along, not once per call.
        _check_cost_plausibility(cost, duration_s, engine_call_id=call_id)
        _check_transfer_leg(payload, engine_call_id=call_id)
        # THE ENGINE'S OWN TIMINGS, read on every snapshot path rather than only on
        # `get_execution`: a listing row carries no `latency_data` today and `parse_latency_data`
        # answers `None` for it, so reading here costs a dict lookup and means the day they
        # add it to a listing we are already capturing it. The alarm rides along for the
        # same reason `_check_cost_plausibility` does — it is a judgement about a number
        # this function just produced, and a check somebody has to remember to call is a
        # check that eventually is not called.
        latency = parse_latency_data(payload.get("latency_data"))
        _check_llm_ttft(latency, engine_call_id=call_id)
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
            duration_s=duration_s,
            # Both numbers, across every spelling the vendor prints — see
            # `_party_numbers` for why the documented one is not the only one that has to
            # be read, and for what goes silently missing when it is.
            from_e164=from_e164,
            to_e164=to_e164,
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
            # FLATTENED, never passed through: the vendor nests by CATEGORY and
            # `engine_extracted` is a flat field->value map. See `flatten_extracted_data`.
            engine_extracted=flatten_extracted_data(payload.get("extracted_data")),
            latency=latency,
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
        agreed with it (OPERATIONS §2). Four behaviours now, in order:

        * the payload NAMES a currency we can convert AND whose UNIT we have evidence for
          -> use it, `currency_stated=True`, and the gate has a fact to score;
        * the payload names a currency we have no rate for -> refuse. Returning a number
          converted at the USD rate would be a fabricated cost basis flowing into the
          margin panel and every invoice. An absent cost is a visible gap; a wrong one
          is not;
        * the payload names a currency we can convert and whose UNIT nothing tells us —
          today that is `INR`, and it is a live hole rather than a hypothetical one
          (D-411) -> refuse, for the same reason one line up. This branch used to convert
          at `rate = 1` (right, and why the branch exists) and then divide by
          `_ASSUMED_MINOR_UNITS_PER_MAJOR` anyway — a constant argued end to end in USD —
          so an account billed in RUPEES metered every call at 1/100th of cost.
          `_MINOR_UNITS_PER_MAJOR` carries why the vendor's own tiebreak does not reach
          here;
        * the payload names nothing -> convert on the house assumption, exactly as
          before, but stamp `currency_stated=False` so the row says which it is.

        Both refusals log at WARNING with the currency and the execution id — ids only,
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
        #
        # READ ONCE, HERE, AND CARRIED AS A LOCAL FOR THE WHOLE BREAKDOWN. Every leg below
        # multiplies by THIS `rate`, and it is stamped onto the row as `fx_rate`, so a
        # costing cannot straddle a rate change: the total and its parts are converted at
        # one number, and that number is on the row that used it. A second read anywhere
        # in this function would be a few paise of disagreement between a total and its
        # own legs, which is the kind of defect that gets dismissed rather than found.
        rate, fx_source, fx_as_of = self._conversion_rate(currency)
        divisor = _MINOR_UNITS_PER_MAJOR.get(currency)
        if divisor is None:
            # THE UNIT IS NOT KNOWN FOR THIS CURRENCY, so there is no honest number to
            # return (D-411). The alternative weighed and rejected was "meter at the more
            # likely divisor and correct it later": on this branch there is no more-likely
            # divisor — the vendor's own tiebreak says "cents", which is not a
            # denomination rupees have — so it would be a coin flip wearing a cost basis,
            # on rows stamped `currency_stated=True`. Refusing costs the row and pages
            # `call_billable_without_cost` from `pipeline._meter` on the first such call;
            # a confident 1/100th costs every margin panel and every spend cap with
            # nothing downstream able to tell.
            log.warning(
                "engine_cost_unit_unknown",
                extra={
                    "engine": "bolna",
                    "currency": currency,
                    "engine_call_id": str(payload.get("id") or payload.get("execution_id") or ""),
                },
            )
            return None
        breakdown = payload.get("cost_breakdown") or {}
        total_inr = _to_inr(total, rate, minor_units_per_major=divisor)
        if total_inr is None:
            return None

        def leg(key: str) -> Decimal | None:
            """Every leg on the SAME currency's unit story and the same rate — a breakdown
            mixing two is a row whose parts do not sum to its whole."""
            return _to_inr(breakdown.get(key), rate, minor_units_per_major=divisor)

        return CostBreakdown(
            total_inr=total_inr,
            platform_inr=leg("platform"),
            network_inr=leg("network"),
            llm_inr=leg("llm"),
            tts_inr=leg("synthesizer"),
            stt_inr=leg("transcriber"),
            source_currency=currency,
            currency_stated=stated is not None,
            # THE SAME DIVISOR AS THE LEGS, and it used to be
            # `_ASSUMED_MINOR_UNITS_PER_MAJOR` spelled a second time. That is what makes
            # this field re-derivable: `usage_events.meta.source_amount` times
            # `meta.fx_rate` must reproduce the row's rupees, and it could not when the
            # two halves used different divisors.
            source_amount=Decimal(str(total)) / divisor,
            fx_rate=rate,
            # WHICH rate, not just what it was. `fx_rate` alone answers "at what number
            # was this converted"; six months into a reconciliation the question is
            # "and why THAT number" — was the feed live, which publication date did it
            # carry, or was this one of the hours we spent on the configured fallback?
            # That is the same distinction `currency_stated` draws for the currency, and
            # it is not re-derivable from the row: a rate history can say what was
            # published, never which of the two doors a given call came through.
            fx_source=fx_source,
            fx_as_of=fx_as_of,
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

    async def _agent_refs(self) -> _AgentRoster:
        """Every agent id on this Bolna account, and whether that roster is all of them.

        `GET /v2/agent/all` -> a bare JSON array of `AgentV2` objects, each with a
        top-level `id` (VERIFIED-OAS: `AgentListV2` is declared `type: array` of
        `AgentV2`, and `AgentV2.id` is the uuid).

        `_request` wraps a bare array as `{"data": [...]}`, which is why this reads
        `_listing_rows` rather than the payload directly. `agent_id` is accepted beside
        `id` because the v1 `GET /all` rows spell it that way and an account may still be
        answered by that shape; a row with neither is skipped rather than guessed at.

        THE ACCOUNT, NOT THE TENANT. One Bolna account holds every tenant's agents, so this
        is deliberately global — the poller's job is to find executions nobody told us
        about, and scoping it to agents we currently know about would hide exactly the call
        placed by an agent our routing table has lost.

        **THE ROSTER IS PAGINATED AND THIS METHOD ASKED FOR ONE PAGE (D-421).** It sent
        `GET /v2/agent/all` with no parameters and treated whatever came back as the whole
        account. Two first-party pages say that is a page, not an account:

            `bolna-findings/mirror/pages/api-reference/pagination.md:9,13-14` — "The
            endpoints also support pagination using the `page_number` and `page_size`
            query parameters ... `page_number` ... Defaults to `1` ... `page_size` ...
            Defaults to `20`. You can request up to `50` results per page."

            `bolna-findings/mirror/pages/cli/commands/agents-list.md:9,24-25` — the
            vendor's OWN CLI client for this route: "List every agent on the account
            **with pagination**", `--page int` default `1`, `--page-size int` default
            `20`.

        WHY THIS WAS WORSE THAN THE TWO FAILURES BEFORE IT (D-353's wrong route, D-412's
        missing `to`): both of those were 400s or 404s — loud, every tick, with
        `reconcile_executions` reporting `reconciliation_fetch_failed`. This one is
        SILENT. On the 21st agent the fan-out simply stops asking about the rest, and
        `list_executions` still answers `complete=True`, because completeness was decided
        per agent and never about the agent list itself. An execution belonging to agent
        21 produces no lead, no usage event, no recording and no alarm — the exact
        sentence D-31 wrote this poller to make false. One Bolna account holds EVERY
        tenant's agents, so 20 is a handful of clients, not a distant ceiling.

        WHAT MAKES THIS SAFE UNDER BOTH READINGS OF THE VENDOR, which is the same
        intersection discipline `_LISTING_MAX_WINDOW` uses. The route's own OpenAPI block
        declares NO parameters and answers a bare array with no `has_more` and no `total`
        (`api-reference/agent/v2/get_all.md:29-51`), so truncation is not detectable from
        the response and the two pages above are the only evidence paging exists here.
        If the platform HONOURS `page_number`, this walks the roster to its end. If it
        IGNORES the parameter — the shape a FastAPI handler with no declared query model
        has, and their OSS server is FastAPI — page one already carried every agent, page
        two repeats it, the walk sees no new id and stops. Either way the roster returned
        is right; only the VERDICT differs, and an ambiguous verdict may not claim
        completeness (`ExecutionListing._verdict_and_reason_agree`).

        THE REASONS ARE THE ONES THE POLLER ALREADY ALERTS ON, deliberately: a roster the
        walk could not finish is the same operator event as a listing it could not finish,
        and inventing a fifth `ListingIncompleteReason` for it would add a runbook entry
        for a distinction nobody acts on differently. `next_link_no_progress` is a full
        page that yielded no agent we had not already seen; `page_cap_reached` is our own
        bound. Both are wired to OPERATIONS §2 gate 30, which settles with one live
        account whether `page_number=2` returns different agents at all.
        """
        refs: list[str] = []
        seen: set[str] = set()
        reason: ListingIncompleteReason | None = None
        page_number = 1
        pages = 0
        while True:
            payload = await self._request(
                "GET",
                "/v2/agent/all",
                params={"page_number": page_number, "page_size": _LISTING_PAGE_SIZE},
            )
            pages += 1
            rows = _listing_rows(payload)
            new_refs = 0
            for row in rows:
                for key in ("id", "agent_id"):
                    value = row.get(key)
                    if isinstance(value, str) and value.strip():
                        ref = value.strip()
                        if ref not in seen:
                            seen.add(ref)
                            refs.append(ref)
                            new_refs += 1
                        break
            # A SHORT PAGE ENDS THE ROSTER and cannot be hiding anything — the vendor
            # returned fewer rows than we asked for. This is the only exit that claims
            # completeness, and it is the one every account below the page size takes.
            if len(rows) < _LISTING_PAGE_SIZE:
                break
            if new_refs == 0:
                reason = "next_link_no_progress"
                break
            if page_number >= _LISTING_MAX_PAGES:
                reason = "page_cap_reached"
                break
            page_number += 1
        return _AgentRoster(refs=refs, pages_fetched=pages, incomplete_reason=reason)

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """The guarantee of record (D-31) — rewritten from the vendor's real contract.

        Read the block above `_LISTING_PAGE_SIZE` first: the endpoint this method used to
        call does not exist, and the completeness heuristic it used to run was built on the
        premise that Bolna publishes no pagination contract. It publishes one.

        WHAT THIS DOES NOW. `GET /v2/agent/all` for the account's agents, then for each
        agent `GET /v2/agent/{ref}/executions?from=<since>&to=<now>&page_number=n&
        page_size=50`, looping while `has_more` is True. `from`/`to` are the vendor's own
        `created_at >=` / `created_at <=` filters, sent as UTC ISO 8601 with an explicit
        offset (`references/bolna-core.md` warns that a datetime without one "is rejected
        or silently runs in UTC"). **`to` is REQUIRED and this method used to omit it** —
        read `_LISTING_MAX_WINDOW` for the vendor sentences and for why sending both is
        the intersection of two contradictory vendor pages rather than a bet on one.

        `to` IS EVALUATED ONCE, before the fan-out, not per agent. A bound recomputed per
        request would give each agent a different window, so "the walk covered
        `since`..`to`" would not be a single true statement about the listing — and the
        rows created during a multi-agent walk are picked up by the next tick anyway,
        which overlaps this one by 20 minutes (`reconcile_executions` polls every 10 with
        a 30-minute window).

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
        until = datetime.now(UTC)
        if until - cutoff > _LISTING_MAX_WINDOW:
            # The caller, not the vendor, is what is wrong here — see `_LISTING_MAX_WINDOW`
            # for why this refuses instead of quietly moving `cutoff` forward.
            raise ProblemError(
                kind="dependency",
                code="engine_listing_window_too_wide",
                title="That reconciliation window is wider than the engine will serve",
                detail=(
                    "The voice platform serves at most "
                    f"{_LISTING_MAX_WINDOW.days} days of call history per listing request."
                ),
                remediation=(
                    "Ask for a narrower window and repeat it to cover the period, rather "
                    "than widening this one."
                ),
                failure_stage="CORE_LOGIC",
            )
        snapshots: list[ExecutionSnapshot] = []
        seen_ids: set[str] = set()
        # The `GET /v2/agent/all` responses ARE responses we read, so they count:
        # `pages_fetched` is "how many responses were read", and understating it would make
        # a fan-out look like a single-page vendor in the one metric that shows the walk ran.
        # The roster is itself a paginated walk (D-421), so it contributes its own count
        # AND its own incompleteness — a roster we could not finish makes the listing
        # incomplete no matter how cleanly every agent in it answered.
        roster = await self._agent_refs()
        pages = roster.pages_fetched
        reason: ListingIncompleteReason | None = roster.incomplete_reason

        for agent_ref in roster.refs:
            page_number = 1
            while True:
                payload = await self._request(
                    "GET",
                    f"/v2/agent/{agent_ref}/executions",
                    params={
                        "from": cutoff.isoformat(),
                        "to": until.isoformat(),
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

    # --- compliance flags ----------------------------------------------------

    async def list_violations(self, *, status: str = OPEN_STATUS) -> ViolationListing:
        """The account's compliance flags — `SupportsViolations`, this vendor's answer.

        Everything about the shape, the four statuses, the fields deliberately dropped and
        the reason there is no `submit` counterpart is in `engine/violations.py`. This
        method is the seam and nothing more: the adapter owns the credential, the base URL
        and `_parse_dt`'s tolerance for the vendor's date spellings, and the walk is shared
        so a second engine that grows this surface reuses it rather than copying it.
        """
        return await walk_violations(self._request, status=status, parse_dt=_parse_dt)

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
        # A STATED ZERO IS A COST AND THE TRUTHINESS TEST ERASED IT. This read the key
        # TWICE and gated on the value, so `total_cost: 0` — which the vendor's own worked
        # example produces per LEG on a short call, and which a whole execution can carry
        # when nothing billable happened — reported the same `None` as a payload with no
        # cost key at all. Those are different facts: "the engine says this call cost
        # nothing" versus "the engine has not said yet", and `billable_ready` is what
        # separates them everywhere else in this adapter. Read once, and let `is None` be
        # the question — the same shape `_cost` above already uses on the same key.
        total_cost = payload.get("total_cost")
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
            cost_raw=str(total_cost) if total_cost is not None else None,
            engine="bolna",
        )


__all__ = [
    "BASE_URL",
    "THROTTLE_MAX_ATTEMPTS",
    "THROTTLE_MAX_SLEEP_S",
    "THROTTLE_STATUS",
    "BolnaEngine",
    "parse_latency_data",
    "parse_transcript",
    "throttle_delay_s",
]
