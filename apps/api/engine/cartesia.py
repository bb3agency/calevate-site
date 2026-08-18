"""Cartesia Line adapter — the second REAL vendor, and the first that disagrees with us.

Adopted as a build-for-the-switch exercise under TRD §10.5 ("make switching a
configuration change"), NOT as an adoption decision. D-31 still rents Bolna.

READ THIS BEFORE WIRING IT TO A LIVE ACCOUNT
=============================================
There is no Cartesia account behind this deployment and no request has ever been made
against their API from this repository. `docs.cartesia.ai` and `www.cartesia.ai` are both
refused by this environment's egress proxy (CONNECT → 403), so **their API reference has
not been read by anyone here.** This module therefore follows `apps/api/billing/
payments.py` exactly: what is corroborated is cited at the line, what is not is marked
UNVERIFIED at the line, and nothing is made to look finished that is not.

**THE HARVESTED EVIDENCE LIVES IN `docs/vendor/cartesia/`.** Read it before changing a
field name here. It carries the source, the file and the line for every claim below, so
the next reader inherits the evidence rather than this docstring's conclusions.

EVIDENCE LADDER USED THROUGHOUT — four standings, never blurred:

* **READ AT SOURCE** — taken from Cartesia's own published code. Two tiers of it, and the
  difference matters: `github.com/cartesia-ai/line` (commit
  `3062c978a2408152c6338679baf57aa230c63596`) is the in-call agent RUNTIME, so it is
  authoritative about the websocket protocol and the KB query endpoint and says nothing
  about the control plane; `cartesia-ai/cartesia-python` and `cartesia-ai/cartesia-js`
  are **generated from Cartesia's OpenAPI spec** ("File generated from our OpenAPI spec by
  Stainless" heads every file), so they ARE the control plane, and two generators agreeing
  is the spec speaking rather than a generator quirk.
* **REPORTED, NOT READ** — a search engine's summary of a docs page that could not be
  fetched. Weaker: nobody here has seen the page. Bolna's `GET /v2/agent/{agent_id}`
  carries this same standing and says so.
* **INFERRED** — a RESTful sibling of a path that IS sourced. Weakest. Every inference
  below fails LOUDLY (a 404 becomes `engine_rejected`), never quietly.
* **CONTRADICTED** — new, and the reason D-270 exists. The generated clients show the
  operation is not there. An inference that has been checked and failed is not the same
  animal as one nobody has checked, and it may not keep wearing the same label.

WHAT THE SDK CHANGED ABOUT OUR OWN UNDERSTANDING — report this upward
----------------------------------------------------------------------
TRD §10.5's capability table says Cartesia Line has **no built-in KB** and lists
"Built-in KB (`rag_id`) | yes (D-33) | no". **The SDK contradicts that.** `line/
knowledge_base.py` is a first-class client for `GET /agents/{agent_id}/documents/query`,
and `line.llm_agent.knowledge_base` is a shipped built-in tool documented in their README
as "Looks up information from the agent's knowledge base via natural-language query". So
Line has agent-scoped documents with retrieval. That is READ AT SOURCE and it is a
material correction to the doc: the "T0 retrieval would need our own path" consequence
does not follow. `CARTESIA_CAPABILITIES.knowledge_base` is True on that evidence.

THE INTEGRATION MODEL IS GENUINELY DIFFERENT, AND THE PORT DOES **NOT** SURVIVE IT
----------------------------------------------------------------------------------
This paragraph used to end "and the port mostly survives it". Reading the generated
control-plane client settled it the other way, and the correction is the single most
important thing in this file (D-270).

Bolna is a hosted agent object: POST a JSON config, they run it. Line is a DEPLOYED AGENT
PROGRAM built from a git repository through the `cartesia` CLI. The consequence is not
stylistic:

* **There is no `POST /agents`.** `cartesia-python`'s `AgentsResource` has `retrieve`,
  `update`, `list`, `delete`, `list_phone_numbers`, `list_templates` — and no `create`.
  `cartesia-js` matches. A Stainless client emits one method per operation in the spec,
  so an absent method is an absent operation.
* **The agent object holds no prompt, no greeting and no model.** `AgentSummary` is
  `{id, name, description, created_at, updated_at, deleted_at, deployment_count,
  has_text_to_agent_run, tts_language, tts_voice, git_repository, git_deploy_branch,
  phone_numbers, webhook_id}` and nothing else. `PATCH /agents/{id}` accepts exactly
  `{description, name, tts_language, tts_voice}`.
* The prompt travels as **per-call data or deployed code**: `CallRequest.agent.
  system_prompt` on the websocket start message, or `LlmConfig(system_prompt=...)` inside
  the program. Never agent-record state.

So `create_agent`, the prompt half of `update_agent`, and the prompt/greeting/model half
of `get_agent` describe a platform Cartesia does not run. They are LEFT IN PLACE and
relabelled CONTRADICTED rather than deleted, for one reason: the `VoiceEngine` port and
its conformance suite require them, `EngineCapabilities` has no way to say "this engine
cannot host an agent of ours", and inventing one is a port change with an admin console
and a publish path hanging off it — not a change to make on the same afternoon the
evidence arrives. What the relabelling buys is that nobody reads this file again and
believes the round trip works. OPERATIONS §2 gate 19(a) is what closes it.

The parts of the port that DO survive are now verified rather than assumed: reading an
agent, renaming it, deleting it, reading a call, and listing calls.

WHAT IS DELIBERATELY NOT HERE
------------------------------
* **No Cartesia SDK dependency.** `cartesia-line` is their in-call agent RUNTIME, meant to
  run inside their harness; it is not a client for the control plane and adding it would
  be a supply-chain decision (hard rule 9) buying nothing this module needs.
* **No invented Indian telephony story.** `number_series` is empty and
  `provision_number` refuses by name. Line's number paths are Cartesia-provisioned,
  imported Twilio, or Voximplant, none of which yields a DLT-registered 140/160-series
  Indian number, and **whether Line accepts BYOC SIP from an Indian carrier is the single
  UNVERIFIED question that decides whether this exit exists at all** (TRD §10.5). It is
  not resolved here by assumption; it is a gate.
* **No invented signature scheme, and no longer an unsourced claim that they sign.**
  What IS read at source: an agent carries a `webhook_id` (`AgentSummary`), so webhooks
  exist. What is NOT anywhere in `line`, `cartesia-python`, `cartesia-js` or
  `cartesia-mcp`: a signing helper, a verifier, a header name or an event enum. The only
  evidence about the scheme is one search snippet (REPORTED, NOT READ) saying a handler
  should check an `x-webhook-secret` header — which would be a SHARED SECRET, not an HMAC.
  `verify_webhook` therefore FAILS CLOSED with an authored reason rather than guessing a
  header and a digest. Wrong-and-fail-closed refuses real deliveries; wrong-and-fail-open
  is an unauthenticated write endpoint wearing the word "verified".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx
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
from apps.api.engine.capabilities import (
    NO_CREDENTIALS_REASON,
    engine_not_configured,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.document import engine_document
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

log = get_logger(__name__)

# READ AT SOURCE: `line/knowledge_base.py:13` — `DEFAULT_BASE_URL = "https://api.cartesia.ai"`,
# corroborated by `cartesia-python/src/cartesia/_client.py:127-130`.
BASE_URL: Final = "https://api.cartesia.ai"

# READ AT SOURCE, THREE CARTESIA REPOS: `cartesia-python/src/cartesia/_client.py:244` and
# `:527` put `"cartesia-version": "2026-08-14"` in `default_headers`;
# `cartesia-js/src/client.ts:801` does the same; `cartesia-mcp/cartesia_mcp/api_version.py`
# defaults `CARTESIA_VERSION` to it under the comment "Latest stable version in docs
# (docs.json API Reference tab)".
#
# THIS REPLACED `2026-04-03`, WHICH WAS NOT AN API VERSION AT ALL (D-270). That value is
# `line/voice_agent_app.py:129`, and its only use (`:217`) is the body our agent PROGRAM
# returns to Cartesia's harness from `POST /chats` — `{"websocket_url", "cartesia_version",
# "metadata"}`. It versions the in-call websocket protocol, travels agent→harness, and is
# a body field rather than a header. Pinning it as `Cartesia-Version` asked the REST API
# for a version of a different thing.
#
# PINNED DELIBERATELY rather than left to the vendor's default: an unpinned date-versioned
# API is a silent breaking change on somebody else's release schedule, and the failure
# mode is a field quietly disappearing from a response we parse rather than an error we
# can see. If a live account rejects the value, the error names the header — which is why
# it is a header and not a URL segment.
API_VERSION: Final = "2026-08-14"

# READ AT SOURCE: `cartesia-python/src/cartesia/_client.py:232-236` builds
# `{"Authorization": f"Bearer {api_key}"}`, and `cartesia-js/src/client.ts:353` builds the
# same. That is the client `client.agents.*` runs through, so it is evidence about THIS
# surface and not only about TTS.
#
# `X-API-Key` IS ALSO PUBLISHED and was what this module sent: `cartesia-ai/skills`,
# `skills/line-voice-agent/references/calls-api.md:18-19` uses it against
# `POST /agents/access-token`, and the outbound-dialing summary uses it too. Both sightings
# sit beside OLDER `Cartesia-Version` values (`2025-04-16`, `2026-03-01`), which is what a
# superseded auth form looks like. Bearer wins because the generated clients track the
# current spec. Sending BOTH was rejected: two credential-bearing headers for one secret
# hides which one the vendor honoured, at exactly the moment we need to know.
AUTH_HEADER: Final = "Authorization"
AUTH_SCHEME: Final = "Bearer"
VERSION_HEADER: Final = "Cartesia-Version"

# READ AT SOURCE: `cartesia-python/src/cartesia/types/agents/call_list_params.py` — `limit`
# is "(Pagination option) The number of calls to return per page, ranging between 1 and
# 100". We ask for the maximum: fewer, larger pages is fewer round trips for the same
# window, and the walk below stops on time rather than on page count.
_LISTING_PAGE_SIZE: Final = 100

# Our own bound on how many call pages one reconciliation tick will read, across ALL
# agents. `BolnaEngine._LISTING_MAX_PAGES` is the same idea for the same reason: a walk
# with no bound is an outage against the vendor the first time their cursor misbehaves.
# Hitting it is reported as `page_cap_reached`, never as completeness.
_LISTING_MAX_PAGES: Final = 20

# READ AT SOURCE: `cartesia-python/src/cartesia/types/agents/agent_call.py` — the call
# object's identifier is `id`. `agent_call_id` is kept behind it because the outbound
# create response is REPORTED to return one per number dialled, and `call_id` because
# `line/_harness_types.py::StartInput` carries both on the wire. First match wins, so the
# verified name leads.
_CALL_ID_KEYS: Final = ("id", "agent_call_id", "call_id")

# READ AT SOURCE: `agent_call.py:34` types `status` as
# `Literal["active", "completed", "failed", "cancelled"]`. That is the WHOLE vocabulary;
# the other entries below are kept because they cost nothing and cover the enum growing.
#
# `cancelled` has no member in `calevate_shared.events.CallStatus`, and `failed` is where
# it lands: terminal, and never billable as a success. It was already reaching `failed`
# through the unmapped-degrades-to-failed default — the DEFECT was `_TERMINAL_RAW`, which
# did not contain it, so a cancelled call stayed non-terminal for ever, was re-read on
# every reconciliation tick, and never reached the post-call pipeline.
_STATUS_MAP: Final[dict[str, CallStatus]] = {
    "queued": "queued",
    "pending": "queued",
    "ringing": "ringing",
    "initiated": "ringing",
    "in_progress": "in_progress",
    "in-progress": "in_progress",
    "active": "in_progress",
    "completed": "completed",
    "ended": "completed",
    "failed": "failed",
    "error": "failed",
    "cancelled": "failed",
    "canceled": "failed",
    "no_answer": "no_answer",
    "no-answer": "no_answer",
    "busy": "busy",
    "voicemail": "voicemail",
}

_TERMINAL_RAW: Final = frozenset(
    {
        "completed",
        "ended",
        "failed",
        "error",
        "cancelled",
        "canceled",
        "no_answer",
        "no-answer",
        "busy",
        "voicemail",
    }
)

# Cartesia Line's capability profile (D-93). Each line's evidence:
#
# * `stt="engine"`, `tts="engine"` — READ AT SOURCE. `line/_harness_types.py:132` defines
#   `TTSConfig(voice_id, pronunciation_dict_id, language)` and `STTConfig(language)`.
#   There is NO provider field on either: the speech stack is Cartesia's product (Sonic /
#   Ink), and our Sarvam Bulbul catalogue addresses nothing on this engine. This is the
#   whole reason `SpeechControl` is per-leg.
# * `llm="ours"` — READ AT SOURCE. `line/llm_agent/provider.py:5` routes through LiteLLM
#   ("See https://docs.litellm.ai/docs/providers"), and their README's own quick start is
#   `LlmAgent(model=..., api_key=os.getenv(...))`. Sarvam is a first-class LiteLLM
#   provider, so D-36's free-per-token LLM leg survives the move. One leg of three.
# * `campaigns=False` — no campaign object appears anywhere in the SDK, and ours are
#   dispatched in our own layer through the compliance gate regardless.
# * `knowledge_base=True` — READ AT SOURCE, and a CORRECTION to TRD §10.5 (module
#   docstring). `line/knowledge_base.py` queries `/agents/{agent_id}/documents/query`.
# * `number_series=frozenset()` — Line has no Indian DLT path (TRD §10.5), and whether
#   BYOC SIP from an Indian carrier is even possible is THE open question. Empty is the
#   only answer that is not a guess, and it makes `provision_number` refuse by name.
# * `transfer=False` — and this one was WRONG in a first draft, caught by the conformance
#   suite, and is the best evidence in this slice that the descriptor is worth checking.
#   The draft said True on real evidence: READ AT SOURCE, `transfer_call` is a shipped
#   built-in tool and the agent yields `AgentTransferCall(target_phone_number,
#   interruptible)` (`line/events.py:58`). Line can transfer calls.
#   But `EngineCapabilities.transfer` does not ask "can this vendor transfer a call"; it
#   asks whether `VoiceEngine.transfer(call_id, to, warm)` — a CONTROL-PLANE COMMAND
#   issued from outside the call — will work. On Line the transfer is initiated BY THE
#   DEPLOYED AGENT MID-CALL, and no endpoint to command one from outside is sourced. So
#   through this port the answer is False, and a True would have had the console offer an
#   escalation control that refuses every time.
#   The vendor feature is not lost by saying so: it is reachable the way Line intends,
#   from inside the agent program, which is a different integration and would arrive as a
#   different capability if we ever need it named.
# * `webhook_auth="hmac"` — READ AS "AUTHENTICATED BY SOMETHING WE CANNOT CHECK YET",
#   which is what this field can express and not more. What is READ AT SOURCE is only
#   that webhooks exist (`AgentSummary.webhook_id`). Nothing in any Cartesia SDK carries
#   a signing scheme; one search snippet (REPORTED, NOT READ) describes an
#   `x-webhook-secret` SHARED SECRET header, which is not an HMAC at all — a shared
#   secret proves the sender knows a token and says nothing about the bytes.
#   `WebhookAuthMethod` is `hmac | source_ip | none`, so there is no truthful third
#   answer available, and widening that Literal is a behavioural change to two
#   deployables on the strength of one snippet. `hmac` is kept because it is the only
#   value that fails CLOSED in both halves (`verify_webhook` here, `WEBHOOK_AUTH_BY_ENGINE`
#   in the voice-runtime receiver) — `source_ip` and `none` would both be weaker claims
#   than the evidence supports. FALSIFIED BY: reading their webhook page. If it is a
#   shared secret, a `shared_secret` method lands in `WebhookAuthMethod` and in both
#   halves together. Gate 19(e).
CARTESIA_CAPABILITIES = EngineCapabilities(
    stt="engine",
    tts="engine",
    llm="ours",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    transfer=False,
    webhook_auth="hmac",
)

#: Authored reason for the one thing we know is signed and cannot yet check. Never vendor
#: prose; it names OUR state.
SIGNATURE_UNIMPLEMENTED_REASON: Final = "signature_scheme_unverified"


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


#: READ AT SOURCE: `cartesia-python/src/cartesia/types/agents/agent_transcript.py:62-68` —
#: "Roles are `user`, `assistant`, or `system`. `assistant` is the agent. `system` is used
#: to indicate logs during the conversation such as `log_event` or `log_metric`."
#:
#: A `system` row is therefore NOT an utterance. It is instrumentation the deployed agent
#: emitted, and the previous mapping — everything that is not the agent is the caller —
#: would have written a `log_event` into a client's transcript as something the caller
#: said. It is skipped, and it is NOT counted as unparsed: `transcript_lines_unparsed` is
#: "speech we could not read", and inflating it with rows that are not speech would make
#: the one instrument that detects a broken parser fire on every healthy call.
_NON_SPEECH_ROLES: Final = frozenset({"system"})

#: The engine side of a turn. `assistant` is READ AT SOURCE; `agent`/`bot` are kept as
#: cheap tolerance for the same reason the status map keeps names Cartesia does not use.
_AGENT_ROLES: Final = frozenset({"assistant", "agent", "bot"})


def parse_transcript(raw: Any, call_id: str) -> tuple[list[TranscriptTurn], int]:
    """Their transcript → our turns, AND how many entries we could not place.

    Counted rather than kept: transcript TEXT is hard rule 6, and a count is not text. The
    count is the same instrument `ExecutionSnapshot.transcript_lines_unparsed` gives the
    Bolna adapter — a parser that silently drops what it does not recognise reports an
    empty transcript and a healthy call identically.

    READ AT SOURCE (`agent_transcript.py`): an entry is
    `{role, text, start_timestamp, end_timestamp, end_reason?, text_chunks?, tool_calls?,
    log_event?, log_metric?, tts_ttfb?, vad_buffer_ms?}`. **The utterance is `text`.**
    This parser read `content` first and `text` only as a fallback, which was not merely
    untidy: `content` is never populated, so on a real Cartesia payload every turn fell
    through to the fallback — and had the fallback not existed, every real transcript
    would have parsed to zero turns while reporting the whole call as unparsed.

    Only the timestamps and the ordering are dropped deliberately: `TranscriptTurn` orders
    by `idx`, and the vendor already hands the entries in order.
    """
    if not isinstance(raw, list):
        return [], 0
    turns: list[TranscriptTurn] = []
    lost = 0
    for entry in raw:
        if not isinstance(entry, dict):
            lost += 1
            continue
        role = str(entry.get("role") or entry.get("speaker") or "").lower()
        if role in _NON_SPEECH_ROLES:
            continue
        text = entry.get("text") or entry.get("content")
        if not isinstance(text, str) or not text.strip():
            lost += 1
            continue
        speaker = "agent" if role in _AGENT_ROLES else "caller"
        turns.append(
            TranscriptTurn(call_id=call_id, idx=len(turns), speaker=speaker, text=text.strip())
        )
    return turns, lost


class CartesiaEngine:
    """Implements `VoiceEngine` against Cartesia Line's control plane.

    Constructed per process; the httpx client is reused. Every method states its own
    evidence standing — read those before trusting a response shape.
    """

    name = "cartesia"
    capabilities = CARTESIA_CAPABILITIES
    #: `CARTESIA_API_KEY` only, matching `holds_credentials` exactly.
    #: `CARTESIA_FROM_NUMBER_ID` is deliberately NOT here: without it this adapter can
    #: still reach the vendor and serve every read, and only `start_outbound_call`
    #: refuses — with its own named reason. Listing it would make one missing dialling
    #: detail read as "this deployment cannot take traffic".
    credential_env_keys: tuple[str, ...] = ("CARTESIA_API_KEY",)

    def __init__(
        self,
        *,
        api_key: str | None,
        from_number_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        api_version: str = API_VERSION,
    ) -> None:
        self._api_key = api_key
        #: The vendor's id for the number outbound calls originate from. Required by the
        #: outbound-dialing shape and NOT derivable from anything we hold: our
        #: `phone_numbers` rows carry E.164 and a DLT series, not a Cartesia number id.
        #: None is the honest default and makes `start_outbound_call` refuse rather than
        #: dial from whatever the account happens to have first.
        self._from_number_id = from_number_id
        self._base_url = base_url
        self._api_version = api_version
        self._client = client

    def holds_credentials(self) -> bool:
        """No `CARTESIA_API_KEY` ⇒ this deployment cannot reach Line at all.

        THE ANSWER TODAY IS FALSE ON EVERY DEPLOYMENT — there is no Cartesia account
        behind this repository. That is the point: the capability seam reports the engine
        unavailable with OUR reason code before any surface offers anything, instead of
        each request discovering it separately at the vendor boundary.
        """
        return bool(self._api_key) or self._client is not None

    # --- plumbing ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                # The credential check is HERE as well as in readiness, because a
                # deployment can be misconfigured after readiness ran. Through the shared
                # builder for the reason `bolna._http` states (P2.6).
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{self.name}")
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={
                    AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}",
                    # Pinned on EVERY request, not just the one the docs showed it on:
                    # a date-versioned API that defaults when the header is absent is
                    # exactly how a response shape changes without anybody deploying.
                    VERSION_HEADER: self._api_version,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _request(
        self, method: str, path: str, *, absent_is_success: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        """One round trip. `absent_is_success` is `delete_agent`'s and nothing else's —
        see `BolnaEngine._request`, which carries the argument for why it is opt-in per
        call site rather than a blanket 404 policy."""
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
        """Our `AgentConfig` → their agent object.

        **CONTRADICTED IN PART, AND THE PART THAT IS CONTRADICTED IS THE COMPLIANCE HALF
        (D-270).** READ AT SOURCE, `cartesia-python/src/cartesia/types/agent_update_params.py`:
        `PATCH /agents/{id}` accepts exactly `{description, name, tts_language, tts_voice}`.
        Of what this method used to send, `name` is accepted, `language` was the wrong name
        for `tts_language`, and `system_prompt`, `introduction`, `model` and `webhook_url`
        are not fields of the agent at all — the agent is a deployed program, and
        `AgentSummary` carries `git_repository`/`git_deploy_branch` where a hosted platform
        would carry a prompt.

        WHAT IS FIXED HERE: `language` → `tts_language`, and the invented `webhook_url` is
        gone (a webhook is its own resource on this platform; the agent carries a read-only
        `webhook_id`).

        WHAT IS DELIBERATELY NOT FIXED: `system_prompt`, `introduction` and `model` are
        still sent. Removing them would leave `create_agent` posting an object with no
        behaviour in it, and would make the conformance suite's hard-rule-5 read-back
        clauses fail for a reason that has nothing to do with our mapping. They stay,
        labelled, until the port grows a way to say "this engine cannot host our agent" —
        OPERATIONS §2 gate 19(a). Against a real account they will be ignored or rejected,
        and either way it is loud rather than silent.

        READ AT SOURCE for what the names WOULD be if the platform took them:
        `line/voice_agent_app.py:88-96` defines the per-call payload the harness delivers
        as `AgentConfig(id, system_prompt, introduction)`, and `cartesia-ai/skills`
        `calls-api.md:64-67` shows a caller supplying `agent: {system_prompt, introduction}`
        on a single call's `start` event. So the NAMES are right and the PLACE is wrong:
        on Cartesia these are per-call data, not agent state.

        HARD RULE 5. The opening line is PREPENDED to the prompt AND is the
        `introduction`, so it is spoken first on every call whichever way the agent opens.
        Sending it only as the introduction would be a compliance control resting on an
        engine field we have never observed; sending it only in the prompt would let a
        model paraphrase it. Both, deliberately. Since D-163 that line is composed from
        the agent's two notice toggles and may be EMPTY — sent as "" rather than omitted,
        because an omitted key leaves the vendor holding the greeting it already has, and
        a withdrawn notice that keeps being spoken is a screen that lies about a phone
        line. `TRUTHFUL_ANSWER_DIRECTIVE` rides at the END of the prompt through
        `compose_engine_prompt` and is not toggleable by anything.

        NO SPEECH CONFIG IS SENT. `TTSConfig`/`STTConfig` take no provider and Sonic/Ink
        are the product, so there is nothing of ours to put there — and `require_speech_leg`
        refuses a caller that tries, rather than dropping it silently.
        """
        require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
        require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
        require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)
        body: dict[str, Any] = {
            # ACCEPTED — READ AT SOURCE, `agent_update_params.py`.
            "name": cfg.name,
            # ACCEPTED under THIS name. It was `language`, which is not a field.
            "tts_language": cfg.language_primary,
            # CONTRADICTED: not fields of the agent object. See the docstring.
            "system_prompt": compose_engine_prompt(cfg),
            "introduction": cfg.opening_line,
        }
        if cfg.models.llm_model:
            # The one BYOK leg, and CONTRADICTED as an agent field: LiteLLM's
            # provider-prefixed form (`sarvam/...`) is READ AT SOURCE as the SDK's own
            # `LlmAgent(model=...)` argument — which lives in the DEPLOYED PROGRAM, not on
            # the agent record. Kept because the conformance suite requires a BYOK leg it
            # can read back and `llm="ours"` is a true statement about the vendor.
            body["model"] = cfg.models.llm_model
        return body

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        """`POST /agents` — **CONTRADICTED. THIS ENDPOINT DOES NOT EXIST** (D-270).

        This was the weakest claim in the module, labelled INFERRED. It has now been
        checked and it failed. READ AT SOURCE: `cartesia-python`'s `AgentsResource` exposes
        `retrieve`, `update`, `list`, `delete`, `list_phone_numbers` and `list_templates`,
        and `cartesia-js/src/resources/agents/agents.ts` matches. Both are generated from
        Cartesia's OpenAPI spec, which emits one method per operation — so no `create`
        method means no create operation. Corroborated by how agents are actually made:
        `cartesia create` / `cartesia init` / `cartesia deploy` (their own
        `skills/line-voice-agent/SKILL.md:60-86`), and by `AgentSummary` identifying an
        agent by `git_repository` + `git_deploy_branch`.

        LEFT IN PLACE, NOT DELETED, and the reason is in the module docstring: the
        `VoiceEngine` port requires this method, `EngineCapabilities` cannot yet say "this
        engine does not host agents of ours", and inventing that capability is a port
        change with a console and a publish path hanging off it. What was in our power was
        to stop the file claiming this might work.

        Against a real account it now fails LOUDLY on the 404 rather than plausibly: an
        agent ref we invented would be stored in `agents.engine_agent_ref`, join no webhook
        to any tenant, and turn a broken integration into a silently broken one.

        WHAT THE REAL PATH LOOKS LIKE, for whoever closes gate 19(a): an agent already
        exists (deployed from a repository) and `create_agent` becomes "adopt the agent
        whose `name` matches" via `GET /agents` — which is a real endpoint returning
        `{"summaries": [...]}`. That is a port change, not a rename, because nothing in
        our publish flow can create the deployment the agent IS.
        """
        data = await self._request("POST", "/agents", json=self._agent_body(cfg))
        ref = _first_str(data, ("id", "agent_id"))
        if ref is None:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return an agent id.",
            )
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        """`PATCH /agents/{id}` — **PATH AND VERB READ AT SOURCE; the BODY is half wrong.**

        `cartesia-python/src/cartesia/resources/agents/agents.py:157` issues exactly
        `PATCH /agents/{agent_id}`, so the guess that PATCH rather than PUT was their verb
        was right for the right reason (a partial agent must not clear fields we never
        named). What the request body may contain is `{description, name, tts_language,
        tts_voice}` and nothing else — see `_agent_body`, which now sends `tts_language`
        under its real name and no longer invents `webhook_url`.

        The prompt does not travel this way on this platform, so a publish here cannot be
        the thing that makes an agent say the disclosure. Hard rule 5's enforcement point
        on Cartesia is the deployed program, which is outside this repository. Gate 19(a).
        """
        await self._request("PATCH", f"/agents/{ref}", json=self._agent_body(cfg))

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """`DELETE /agents/{id}` — **READ AT SOURCE. The route exists.**

        This carried "NO PUBLIC DOCUMENTATION FOUND" and stood or fell with the
        non-existent `POST /agents`. It stands on its own:
        `cartesia-python/src/cartesia/resources/agents/agents.py` issues
        `DELETE /agents/{agent_id}` returning no body, and `cartesia-js` matches. The
        finding is withdrawn — it was true of the docs and false of the API.

        **THE MARKED ASSUMPTION THAT REMAINS IS NARROWER AND STILL REAL**: what a REPEAT
        delete answers. The generated client types the response as `None` and says nothing
        about a second call, and `AgentSummary` carries a `deleted_at` — which hints at
        soft deletion, i.e. at a second delete that might succeed rather than 404.
        ASSUMED: 404 for an id the account does not hold, which `absent_is_success` folds
        into the Protocol's idempotent success.
        FALSIFIED BY: any non-404 refusal on a repeat delete, and by a 404/405 on the
        FIRST delete — which is the same falsifier `create_agent` and `update_agent`
        already carry, and it fails loudly rather than degrading: an orphan we could not
        remove is reported by the compensator exactly as it was before this method
        existed, which is a log line naming the ref, not a claim that it is gone.
        MEASURED BY: OPERATIONS §2 gate 2's `delete_agent` sub-check, run against whichever
        vendor the deployment is configured for.
        """
        await self._request("DELETE", f"/agents/{ref}", absent_is_success=True)

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """`GET /agents/{id}` → our `AgentSnapshot`. **PATH READ AT SOURCE; three of the
        four things we read back are not on the object** (D-270).

        `cartesia-python/src/cartesia/resources/agents/agents.py` issues
        `GET /agents/{agent_id}` and types the response as `AgentSummary`:
        `{id, name, description, created_at, updated_at, deleted_at, deployment_count,
        has_text_to_agent_run, tts_language, tts_voice, git_repository, git_deploy_branch,
        phone_numbers, webhook_id}`. There is no `system_prompt`, no `introduction`, no
        `model` and no `documents`.

        So against a real account this method reports `system_prompt_readable=False`,
        `greeting_readable=False`, `models_readable=False` and
        `knowledge_base_refs_readable=False` — every publish through
        `apps/api/agents/verification.py` fails closed as `unreadable`, which is the
        correct direction and is also a live integration that does not work. It is left
        reading the fields it reads because the tolerant lookups cost nothing and because
        the conformance suite's stub is the only thing that answers them today; what
        changed is that the file no longer calls the arrangement INFERRED, as though the
        next reader might find it works.

        ONLY THE LLM LEG IS REPORTED, because only the LLM leg is ours. STT and TTS are
        Cartesia's to dictate, so there is no selection of ours to read back for them, and
        reporting the engine's own `voice_id` would put a vendor string where every caller
        expects one of ours — reading, to everything above, exactly like an applied BYOK
        selection (`AgentSnapshot.models`).

        The LLM leg IS read back, and the conformance suite requires it: an adapter that
        claims a leg is ours and cannot show what the engine holds for it is asserting
        BYOK on faith. `model` is the field `_agent_body` sends (READ AT SOURCE as the
        SDK's own `LlmAgent(model=...)` argument); whether the agent object echoes it under
        that name on a GET is INFERRED, and if it does not, `models_readable` is False and
        the suite fails us — loudly, which is correct, rather than letting the claim stand
        unchecked.

        The prompt half IS attempted, because that is what pilot gate 2's
        ACCEPTED-versus-APPLIED question needs, and `system_prompt_readable` reports
        honestly when the field cannot be found.
        """
        payload = await self._request("GET", f"/agents/{ref}")
        # An `{"agent": {...}}` envelope is tolerated as well as a bare object: their
        # in-call start message wraps the agent (`StartInput.agent`), so a control-plane
        # response that does the same would otherwise read as an agent with no fields —
        # i.e. as "the prompt was never applied", on no evidence.
        inner = payload.get("agent")
        agent: dict[str, Any] = inner if isinstance(inner, dict) else payload
        prompt = agent.get("system_prompt")
        prompt_text = prompt if isinstance(prompt, str) and prompt else None
        # THE GREETING, on the `(value, readable)` pair `bolna._agent_greeting` argues
        # for: a key present and EMPTY is an agent that speaks nothing first — a real
        # compliance failure — while an ABSENT key is us looking in the wrong place, and
        # only the first may fail a publish (P3.3). `introduction` is the field
        # `_agent_body` sends and the SDK's own `AgentConfig(introduction=...)` argument;
        # that the GET echoes it is INFERRED, like the rest of this method.
        greeting_readable = "introduction" in agent
        raw_greeting = agent.get("introduction")
        greeting = None
        if greeting_readable:
            greeting = raw_greeting if isinstance(raw_greeting, str) else ""
        returned_id = _first_str(agent, ("id", "agent_id"))
        name = agent.get("name")
        # UNVERIFIED: that the agent object lists its documents, or under what key. An
        # absent key reads as "we could not tell" (`readable=False`), never as "it
        # references none" — the D-41 tri-state, for the same reason.
        raw_docs = agent.get("documents") or agent.get("document_ids")
        docs_readable = raw_docs is not None
        handles = [str(item) for item in raw_docs if item] if isinstance(raw_docs, list) else []
        held_model = agent.get("model")
        model_text = held_model if isinstance(held_model, str) and held_model else None
        return AgentSnapshot(
            engine_agent_ref=returned_id or ref,
            name=name if isinstance(name, str) and name else None,
            system_prompt=prompt_text,
            system_prompt_readable=prompt_text is not None,
            greeting=greeting,
            greeting_readable=greeting_readable,
            knowledge_base_refs=handles,
            knowledge_base_refs_readable=docs_readable,
            # The LLM leg only. STT/TTS stay None because they are not ours to set — a
            # dictated leg has no selection of ours to report (`AgentSnapshot.models`).
            models=ModelConfig(llm_model=model_text),
            models_readable=model_text is not None,
            engine=self.name,
        )

    # --- calls ---------------------------------------------------------------

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """`POST /agents/calls`.

        **REPORTED, NOT READ** — a search summary of `docs.cartesia.ai/line/integrations/
        telephony/outbound-dialing`, which the egress proxy refuses. What that summary
        states, and what is implemented below: `from_number_id`, `agent_id`,
        `ringing_timeout_seconds`, and an `outbound_calls` array of `{to_number,
        metadata}`, returning an `agent_call_id` per number.

        `from_number_id` IS REQUIRED BY THAT SHAPE AND WE HAVE NO VALUE FOR IT. The port's
        `start_outbound_call(ref, to, ctx)` carries no caller-id argument — on Bolna the
        number is bound to the agent, so the signature never needed one. Rather than
        invent a field or dial from an arbitrary number, this refuses when no number is
        configured. Which number a tenant dials FROM is a DLT 140/160 decision in our
        schema (`phone_numbers.series`), not something to guess at the vendor boundary.

        `ctx` rides in `metadata`, which the summary names as a per-call object. Only
        non-PII context is sent: `lead_id` is an id, and the note is business text the
        operator wrote. The lead's NAME and NUMBER are not put in metadata (hard rule 6) —
        the number is already the dial target.
        """
        if self._from_number_id is None:
            # ITS OWN CODE, and it did not have one: this reused `engine_not_configured`,
            # which is the credential refusal (P2.6). One code for two causes means an
            # operator reading a problem+json `type` cannot tell "we hold no API key" from
            # "we hold an API key and no outbound number" — different fixes, different
            # people. The remediation was already saying so in prose while the machine
            # field said otherwise.
            raise ProblemError(
                kind="dependency",
                code="engine_caller_id_not_configured",
                title="No caller ID is configured",
                detail="No outbound number is configured for the voice platform.",
                remediation="Contact us to attach a verified outbound number to this account.",
            )
        metadata: dict[str, Any] = {}
        if ctx.lead_id:
            metadata["lead_id"] = ctx.lead_id
        if ctx.context_note:
            metadata["context_note"] = ctx.context_note
        data = await self._request(
            "POST",
            "/agents/calls",
            json={
                "agent_id": ref,
                "from_number_id": self._from_number_id,
                "ringing_timeout_seconds": 30,
                "outbound_calls": [{"to_number": to, "metadata": metadata}],
            },
        )
        rows = data.get("outbound_calls") or data.get("calls") or data.get("data")
        candidate = rows[0] if isinstance(rows, list) and rows else data
        handle = _first_str(candidate, _CALL_ID_KEYS) if isinstance(candidate, dict) else None
        if handle is None:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a call id.",
            )
        return handle

    async def end_call(self, call_id: str) -> None:
        """`POST /agents/calls/{id}/end` — **INFERRED, and now the weakest path in the
        module.**

        The generated clients expose exactly three call operations —
        `GET /agents/calls/{id}`, `GET /agents/calls`, `GET /agents/calls/{id}/audio` — and
        no way to terminate one. Nothing in `line` does either: an agent ends its own call
        from inside, by yielding `EndCallOutput` over the websocket
        (`line/_harness_types.py:109-115`), which is the same shape as `transfer` and for
        the same reason (see `CartesiaEngine.transfer`).

        So a control-plane hang-up may simply not exist on this platform. It is left as an
        inference rather than made to refuse, because unlike `transfer` there is no
        capability flag for it: `VoiceEngine.end_call` has no `EngineCapabilities` member,
        so refusing here would be a private code disagreeing with a descriptor that says
        nothing — the divergence D-93 exists to remove. It fails loudly on a 404/405.
        Gate 19(b).
        """
        await self._request("POST", f"/agents/calls/{call_id}/end")

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        """Refuses by name: Line's transfer is the AGENT's to perform, not ours to command.

        READ AT SOURCE: `transfer_call` is a shipped built-in tool and the agent yields
        `AgentTransferCall(target_phone_number, interruptible)` over the live websocket
        (`line/events.py:58`). The vendor feature exists. What does not exist — nothing
        sourced describes one — is a control-plane endpoint to transfer a call from
        OUTSIDE it, which is what this method is.

        So `CARTESIA_CAPABILITIES.transfer` is False and this refuses through the one
        capability refusal, rather than raising a private code that disagreed with the
        descriptor. The whole point is that a caller can ask BEFORE calling and get the
        same answer; a console that offered the control and a method that refused it is
        the divergence D-93 exists to remove.

        WARM transfer is not distinguished by `AgentTransferCall` at all, which is its own
        finding: `warm` has nowhere to go on this engine even from inside the call.
        """
        require_capability("transfer", engine=self)
        raise AssertionError(  # unreachable while `transfer` is False
            "transfer was declared available but no control-plane endpoint is implemented"
        )

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        """Refuses every series, by name.

        Not a gap to be filled later by reading a docs page: Line's number paths are
        Cartesia-provisioned, imported Twilio, or Voximplant, and none of those yields a
        DLT-registered 140/160-series Indian number. **Whether Line accepts BYOC SIP from
        an Indian DLT-registered carrier is the single question that decides whether this
        engine is usable for us at all, and it is UNVERIFIED** (TRD §10.5). Until it is
        answered in writing, an Indian number on this engine is not a feature that is
        missing — it is a premise that has never been established.
        """
        require_capability("numbers", engine=self)
        raise ProblemError(  # unreachable while `number_series` is empty
            kind="dependency",
            code="engine_capability_unverified",
            title="Number provisioning is not available",
            detail="Numbers are provisioned with the telephony provider directly.",
        )

    # --- knowledge base ------------------------------------------------------
    #
    # Agent-scoped documents. The QUERY path is READ AT SOURCE
    # (`line/knowledge_base.py:86`: `GET /agents/{agent_id}/documents/query`, query params
    # `query`/`top_k`/`filters`, response `{"results": [{"content": …}]}`); the CRUD
    # siblings under `/agents/{id}/documents` are INFERRED from it.
    #
    # THAT INFERENCE IS NOW WEAKER THAN IT LOOKED, and the weakening is worth recording:
    # `cartesia-python` and `cartesia-js` have NO documents resource at all, so the CRUD
    # siblings are not merely undocumented — they are absent from the generated client
    # that does contain every other agent operation. The only support for them is a search
    # snippet describing "a knowledge base of documents and folders" (REPORTED, NOT READ).
    #
    # NOTE ALSO THE CREDENTIAL. The query path authenticates with `Authorization: Bearer
    # {agent_token}`, an agent-scoped JWT the harness hands the RUNNING AGENT on the
    # websocket start message (`line/_harness_types.py:192-199`) — not the account API key
    # this adapter holds. So even the sourced path is not one this client could call, which
    # is a hint that ingestion lives somewhere else entirely. Gate 19(f).
    #
    # `CARTESIA_CAPABILITIES.knowledge_base` stays True: agent-scoped retrieval
    # demonstrably exists. What is unknown is how a document gets IN.

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        require_capability("knowledge_base", engine=self)
        data = await self._request(
            "POST",
            f"/agents/{ref}/documents",
            json={"title": source.title, "content": source.text, "language": source.language},
        )
        handle = _first_str(data, ("id", "document_id"))
        if handle is None:
            # A document we cannot address is a document that can never be superseded —
            # the KB would only ever grow, and `detach_kb` would have nothing to name.
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a knowledge base id.",
            )
        return handle

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        """No swallowing of a 404: an id we cannot delete is an id we cannot prove is
        gone, and the caller's next act is to publish a replacement."""
        require_capability("knowledge_base", engine=self)
        await self._request("DELETE", f"/agents/{ref}/documents/{kb}")

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        require_capability("knowledge_base", engine=self)
        data = await self._request("GET", f"/agents/{ref}/documents")
        rows = data.get("documents") or data.get("data")
        if not isinstance(rows, list):
            return []
        handles: list[EngineKBRef] = []
        for row in rows:
            if isinstance(row, dict):
                handle = _first_str(row, ("id", "document_id"))
                if handle:
                    handles.append(handle)
        return handles

    # --- reading the truth ---------------------------------------------------

    def _cost(self, payload: dict[str, Any]) -> CostBreakdown | None:
        """Their cost → INR.

        **NOT IMPLEMENTED, AND IT IS NO LONGER A DEFERRAL — IT IS THE ANSWER (D-270).**
        This used to say "nothing sourced says what currency Line reports, at what
        granularity, or under which key", with a pilot gate to go and read it off a call.
        There is nothing to read. READ AT SOURCE, twice:

        * `cartesia-python/src/cartesia/types/agents/agent_call.py` — the call object has
          no cost, price, credit or currency field of any kind.
        * `cartesia-mcp/cartesia_mcp/extra_api.py:54-79` — usage is an ACCOUNT-level meter,
          `GET /usage/credits`, whose finest interval is a **day** and whose `group_by` is
          `{capability, model, voice, api_key}` (`:20-21`). There is no `call` or `agent`
          member.

        So no route exists from a Cartesia response to a per-call rupee figure at the
        granularity `usage_events` needs. Hard rule 7 and `CostBreakdown`'s contract
        require converting at capture and STAMPING the rate so a ledger row can be
        re-derived; there is no vendor number to convert. `CostBreakdown.currency_stated`
        exists precisely because a house assumption once became indistinguishable from a
        vendor fact, and inventing one here would be that defect on purpose.

        Returning None means `charge_for_call` records no cost rows for this engine. That
        hole is now a COMMERCIAL question — a rate card and a plan, per D-94's $0.014/min
        Scale tier — not an endpoint anybody can go and find. Gate 19(c).
        """
        return None

    def _snapshot(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        """Their `AgentCall` → our `ExecutionSnapshot`.

        READ AT SOURCE: `cartesia-python/src/cartesia/types/agents/agent_call.py` types the
        object as `{id, agent_id, status, deployment_id?, start_time?, end_time?,
        error_message?, summary?, telephony_params?{from,to}, transcript?}`. Four field
        names below were invented and are corrected here (D-270): the id is `id` not
        `agent_call_id`, the times are `start_time`/`end_time` not `started_at`/`ended_at`,
        and the numbers are NESTED under `telephony_params` rather than at the top level —
        so the previous mapping produced a snapshot with no timestamps and no numbers on
        every real payload, silently.

        The previously-assumed names are kept as fallbacks after the verified ones. They
        cost one dict lookup and they are what the outbound-create response is REPORTED to
        use, so removing them would trade a verified fix for a new blind spot.
        """
        raw_status = str(payload.get("status") or "").lower()
        call_id = _first_str(payload, _CALL_ID_KEYS) or ""
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
        started = _parse_dt(
            payload.get("start_time") or payload.get("started_at") or payload.get("created_at")
        )
        ended = _parse_dt(payload.get("end_time") or payload.get("ended_at"))
        # DERIVED, because `AgentCall` has no duration field at all. Deriving it from two
        # instants we DID read is not an invention — it is the same number, computed — and
        # it stays None unless both ends are present, so a running call reports no
        # duration rather than a made-up one. The explicit keys are still preferred if the
        # vendor ever adds one.
        duration = payload.get("duration_seconds") or payload.get("duration")
        duration_s = int(duration) if isinstance(duration, int | float) else None
        if duration_s is None and started is not None and ended is not None:
            duration_s = max(int((ended - started).total_seconds()), 0)
        # NESTED. `telephony_params` is documented as `from` = "The phone number of the
        # agent" and `to` = "The phone number of the caller", which matches our
        # from/to on an OUTBOUND call and reads inverted on an inbound one. There is no
        # `direction` field to key off and nothing sourced says the meanings flip, so this
        # maps straight through rather than inventing a swap. Gate 19(d).
        telephony = payload.get("telephony_params")
        telephony_params: dict[str, Any] = telephony if isinstance(telephony, dict) else {}
        recording = payload.get("recording_url")
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=_first_str(payload, ("agent_id",)),
            direction="outbound" if payload.get("direction") == "outbound" else "inbound",
            status=_STATUS_MAP.get(raw_status, "failed"),
            raw_status=raw_status or "unknown",
            terminal=raw_status in _TERMINAL_RAW,
            # Same as `terminal` for now, and that is a CLAIM about this vendor we cannot
            # yet make well. Bolna's cost/recording/transcript arrive ~2-3 min AFTER the
            # call ends, which is why `billable_ready` exists as a separate flag. Whether
            # Line populates at disconnect or later is unsourced; equating them is the
            # optimistic answer and it is marked so rather than hidden. Since `_cost`
            # returns None regardless, nothing bills on it today.
            billable_ready=raw_status in _TERMINAL_RAW,
            started_at=started,
            ended_at=ended,
            duration_s=duration_s,
            from_e164=_first_str(telephony_params, ("from", "from_number"))
            or _first_str(payload, ("from_number", "from")),
            to_e164=_first_str(telephony_params, ("to", "to_number"))
            or _first_str(payload, ("to_number", "to")),
            # NOT INVENTED FROM `/agents/calls/{id}/audio`. That endpoint exists (READ AT
            # SOURCE, `resources/agents/calls.py:172`) but it is an authenticated download
            # rather than a fetchable link, and `recording_url` is handed to a fetcher that
            # holds no engine credential. A URL that 401s is worse than no URL. Gate 19(b).
            recording_url=recording if isinstance(recording, str) and recording else None,
            transcript=turns,
            transcript_lines_unparsed=unparsed,
            cost=self._cost(payload),
            engine_extracted={},
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """`GET /agents/calls/{id}` — **READ AT SOURCE**
        (`cartesia-python/src/cartesia/resources/agents/calls.py:73`).

        No query parameters: the generated client sends none, and `expand` is a parameter
        of the LIST operation only. So whether a single retrieve includes the transcript is
        the vendor's choice (`AgentCall.transcript` is optional) and not ours to force by
        guessing a parameter onto a path that does not declare one. Gate 19(b).

        Carries the vendor's own document out as bytes for D-126's archive, on this path
        only — `list_executions` builds no document per row, for `BolnaEngine`'s reason.
        """
        payload = await self._request("GET", f"/agents/calls/{call_id}")
        return self._snapshot(payload).model_copy(
            update={"raw_document": engine_document(payload, engine=self.name)}
        )

    @staticmethod
    def _listing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """The rows out of a listing envelope.

        READ AT SOURCE: `cartesia-python/src/cartesia/pagination.py:49-57` — the page model
        is `SyncCursorIDPage` with a single field `data`. `calls`/`results` follow it only
        as tolerance; they cost one lookup each and they are what an envelope rename would
        land as.
        """
        for key in ("data", "calls", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    async def _agent_refs(self) -> list[str]:
        """Every agent id on the account. `GET /agents` → `{"summaries": [AgentSummary]}`.

        READ AT SOURCE: `resources/agents/agents.py` (`list`) and
        `types/agent_list_response.py` (`summaries: List[AgentSummary]`). Unpaginated in
        the generated client — it returns a bare object rather than a page model, which is
        the one place in this file where "the generator emitted no cursor" is taken as
        "there is no cursor".
        """
        payload = await self._request("GET", "/agents")
        summaries = payload.get("summaries")
        rows = summaries if isinstance(summaries, list) else self._listing_rows(payload)
        return [ref for row in rows if isinstance(row, dict) if (ref := _first_str(row, ("id",)))]

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """The guarantee of record (D-31) — against a listing that is neither global nor
        time-filtered. **Rewritten from the real contract under D-270.**

        WHAT THE VENDOR ACTUALLY OFFERS, READ AT SOURCE
        (`cartesia-python/src/cartesia/resources/agents/calls.py:95-98` and
        `types/agents/call_list_params.py`):

            "Lists calls sorted by start time in descending order for a specific agent.
             `agent_id` is required and if you want to include `transcript` in the
             response, add `expand=transcript` to the request. This endpoint is paginated."

        Three facts, each of which the previous implementation got wrong:

        * **`agent_id` is REQUIRED** (`Required[str]` in the params TypedDict). A listing
          without one is a 4xx, so the previous global `GET /agents/calls` could never have
          returned a row. This fans out over `GET /agents` instead.
        * **There is NO time filter.** No `since`, `created_after` or `start_time`
          parameter exists; the `start_time` we were sending was invented. `since` is
          therefore applied HERE — cheaply, because the vendor's own ordering (start time
          DESC) means the walk for an agent can stop at the first row older than the
          window instead of reading the agent's whole history.
        * **Pagination is a real, published contract**: `limit` (1-100), `starting_after`,
          `ending_before`, cursoring on the call id, envelope `{"data": [...]}`, and
          crucially **no `has_more`** (`pagination.py:60-73` derives the next cursor from
          the last row's id). So "was that the last page?" is answered by the page being
          short, and the old `full_page_suspected` guess is replaced by a walk.

        HOW COMPLETENESS IS DECIDED NOW, and `complete=True` remains a POSITIVE claim:

        * every agent's walk ended on a short page or on a row older than `since`
          ⇒ `complete=True`;
        * our own `_LISTING_MAX_PAGES` bound stopped a walk that was still producing
          ⇒ `page_cap_reached`;
        * a cursor came back pointing at rows we already had ⇒ `next_link_no_progress`,
          because a cursor that does not advance would otherwise spin to the page cap and
          report the wrong reason.

        A call placed against an agent this account no longer holds is invisible to this
        method — the listing is per agent and a deleted agent lists nothing. That is a
        property of the vendor's model, not of this code, and it is why `raw_document` on
        `get_execution` matters more here than on Bolna.
        """
        cutoff = since.astimezone(UTC)
        snapshots: list[ExecutionSnapshot] = []
        seen_ids: set[str] = set()
        # The `GET /agents` response IS a page we read, so it counts: `pages_fetched` is
        # "how many responses were read", and understating it would make a fan-out look
        # like a single-page vendor in the one metric that shows the walk ran.
        pages = 1
        reason: ListingIncompleteReason | None = None

        for agent_ref in await self._agent_refs():
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {
                    "agent_id": agent_ref,
                    "limit": _LISTING_PAGE_SIZE,
                    # Without this the vendor returns no transcript at all, and the
                    # reconciliation path is the one with no webhook behind it to supply
                    # one — a repaired call would land with an empty transcript that looks
                    # exactly like a silent call.
                    "expand": "transcript",
                }
                if cursor is not None:
                    params["starting_after"] = cursor
                payload = await self._request("GET", "/agents/calls", params=params)
                pages += 1
                rows = self._listing_rows(payload)
                new_rows = 0
                reached_window_edge = False
                for row in rows:
                    snapshot = self._snapshot(row)
                    if snapshot.started_at is not None and snapshot.started_at < cutoff:
                        # DESC order: this row and everything after it is outside the
                        # window, so the walk for this agent is finished and complete.
                        reached_window_edge = True
                        break
                    if not snapshot.engine_call_id or snapshot.engine_call_id in seen_ids:
                        continue
                    seen_ids.add(snapshot.engine_call_id)
                    snapshots.append(snapshot)
                    new_rows += 1
                if reached_window_edge or len(rows) < _LISTING_PAGE_SIZE:
                    break
                if new_rows == 0:
                    # A full page that added nothing: the cursor is not advancing. Walking
                    # on would burn the page cap and then report `page_cap_reached`, which
                    # tells an operator to look for a big window when the problem is a
                    # stuck cursor.
                    reason = "next_link_no_progress"
                    break
                if pages >= _LISTING_MAX_PAGES:
                    reason = "page_cap_reached"
                    break
                cursor = str(rows[-1].get("id") or "") or None
                if cursor is None:
                    # No id to cursor on. Nothing to follow and no grounds to claim we saw
                    # the whole window.
                    reason = "explicit_more"
                    break
            if reason is not None:
                break

        if reason is not None:
            return ExecutionListing(
                snapshots=snapshots, complete=False, incomplete_reason=reason, pages_fetched=pages
            )
        return ExecutionListing(snapshots=snapshots, complete=True, pages_fetched=pages)

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """FAILS CLOSED. Their webhooks are signed; the scheme is not sourced.

        This is the one place in this module where guessing would be actively dangerous
        rather than merely wrong. A signature check is three independent guesses — the
        header name, the canonical string, the digest — and getting any of them wrong in
        the OTHER direction produces an endpoint that accepts anything while reporting
        `method="hmac"`, i.e. a public unauthenticated write endpoint wearing the word
        "verified". `test_a_claimed_verification_method_actually_rejects_somebody` exists
        for exactly that failure.

        So: `ok=False`, always, with an authored reason. Every delivery is refused until
        somebody reads their webhook documentation and implements the real scheme. That is
        a visibly unfinished integration — the reconciliation poller remains the guarantee
        of record — rather than a plausible-looking wrong one.

        THE OTHER HALF OF THE REFUSAL IS NOT IN THIS FILE (D-103). This method is what the
        WORKER acts on; the receiver that actually answers the delivery is
        `apps/voice-runtime/engine_intake.verify_source`, which cannot import this module
        (hard rule 3 forbids the heavy import on the ack path) and instead reads
        `WEBHOOK_AUTH_BY_ENGINE["cartesia"] == "hmac"` and refuses on the same grounds. So
        both halves fail closed independently, and neither can be softened by a change to
        the other. `tests/engine_name_drift_test.py` asserts they still agree — including
        the case that matters most, a deployment actually running `ENGINE=cartesia`, where
        the temptation to let the delivery through is at its strongest.

        WHEN THE SCHEME IS SOURCED, both halves change together or the conformance clause
        `test_the_declared_webhook_method_is_the_one_actually_reported` fails: the verifier
        lands here, the receiver grows the matching check, and only then does either stop
        returning `ok=False`.
        """
        return WebhookVerdict(ok=False, method="hmac", reason=SIGNATURE_UNIMPLEMENTED_REASON)

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Their event → OUR normalized event. UNVERIFIED field names.

        No tenant_id/agent_id is invented (hard rule 1): a vendor cannot know ours, and a
        guessed tenant is a cross-tenant write. An unknown status degrades to `failed`,
        never to a success.
        """
        raw_status = str(payload.get("status") or payload.get("event") or "").lower()
        return CallEvent(
            call_id=_first_str(payload, _CALL_ID_KEYS) or "",
            engine_agent_ref=_first_str(payload, ("agent_id",)),
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=_STATUS_MAP.get(raw_status, "failed"),
            raw_status=raw_status or "unknown",
            from_e164=_first_str(payload, ("from_number", "from")),
            to_e164=_first_str(payload, ("to_number", "to")),
            recording_url=_first_str(payload, ("recording_url",)),
            engine=self.name,
        )


__all__ = [
    "API_VERSION",
    "BASE_URL",
    "CARTESIA_CAPABILITIES",
    "SIGNATURE_UNIMPLEMENTED_REASON",
    "CartesiaEngine",
    "parse_transcript",
]
