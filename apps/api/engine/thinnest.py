"""ThinnestAI adapter: a `control_plane` engine reached over its REST API (D-678).

ThinnestAI hosts the agent and the call. We create and edit the agent over
`https://app.thinnest.ai/api/v1`, dial with `POST /calls`, and read results from their call
endpoints and signed webhooks. The plan is `docs/THINNEST-INTEGRATION.md`; every vendor fact
below cites the hash-pinned mirror `thinnest-findings/mirror/pages/` (VERIFIED-VENDOR-DOCS)
as `path:line`. No request has been made against a live ThinnestAI account from this tree.

Where the mirror is silent the value is marked UNVERIFIED at the line and the adapter either
sends nothing or refuses by name. The open items: the shape of a `call.completed` body, and
which number `from` names on an inbound call.

ONE CUSTOMER WORKSPACE PER CLIENT (D-693). A client's agents, calls, numbers and webhooks live
in its own ThinnestAI customer workspace; every request about them carries the workspace
header, derived in one place (`engine/thinnest_workspace.py`) from the object's handle
(`<raw>@<org_…>`, `calevate_shared.engine_scope`). An unscoped handle is an object created
in our developer workspace before D-693; it is addressed there until its next publish
recreates it. Customer workspaces inherit the developer workspace's voice-only BYOK with
our Cartesia key (`snapshots/2026-10-08/pages/api-reference/bring-your-own-keys.md:128-133`),
and each agent says whether it follows that (D-688):
`byok: "workspace"` speaks a Cartesia voice (Studio), `byok: "off"` stays on ThinnestAI's own
voices and models at their normal rate (Clear). The field is sent on every create and update,
never left to its `workspace` default (LIVE-DOCS `docs.thinnest.ai/api-reference/agents/
update-agent`, read 8 Oct 2026; evaluation §12 item 1).

Three properties of the vendor shape the adapter more than any field name does:

* An agent made by `POST /agents` is a new object every time (agents.md:74-82), so
  `create_agent` finds an agent it made earlier by a tag in the name before creating one.
  Without that a publish retried after a lost response leaves a second live agent.
* `GET /calls/{id}` answers 404 for calls the API did not place (get-call.md:50-52), so an
  inbound call's transcript and recording reach us only in the signed `call.analysed`
  delivery. `snapshot_from_delivery` builds the snapshot from that body.
* Calls carry no cost field (get-call.md:199-204). `ExecutionSnapshot.cost` is always None;
  the minute is priced from an operator-attested rate in billing, never here.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, cast, get_args
from urllib.parse import quote, urlsplit

import httpx
from calevate_shared.call_script import business_line_of, substitute_variables
from calevate_shared.engine import (
    E164,
    AccountKBListing,
    AccountKBObject,
    AgentConfig,
    AgentSnapshot,
    AvailableNumber,
    ByokVoiceTuning,
    CallContext,
    CallHandle,
    EngineAgentRef,
    EngineCapabilities,
    EngineKBRef,
    EngineVoiceListing,
    ExecutionListing,
    ExecutionSnapshot,
    KBSourceRef,
    ListingIncompleteReason,
    LlmCredentialPlacement,
    LlmProvider,
    NumberSearch,
    NumberSpec,
    ProvisionedNumber,
    RecallOutcome,
    WebhookVerdict,
    compose_engine_prompt,
    compose_first_utterance,
)
from calevate_shared.engine_scope import raw_of, scoped_handle
from calevate_shared.events import (
    CallBilling,
    CallDirection,
    CallEvent,
    CallKeys,
    CallLlmUsage,
    CallQuality,
    CallStatus,
    CallVoicePlan,
    EngineByokChange,
    EngineByokChanged,
    EngineContactErased,
    EngineNotice,
    EngineNoticeKind,
    EngineOptOut,
    EngineProblem,
    EngineProblemKind,
    Speaker,
    TranscriptTurn,
)
from calevate_shared.webhook_signature import (
    signed_time_is_fresh,
    timestamped_sha256_signature_matches,
)

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.capabilities import (
    NO_CREDENTIALS_REASON,
    engine_lacks,
    engine_not_configured,
    require_call_compliance_floor,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.catalogue import (
    CatalogueModel,
    EngineCatalogue,
    HostedVoice,
    HostedVoiceBand,
    HostedVoiceListing,
    OwnVoiceKeyState,
    PreviewAudio,
    VoiceClone,
    VoiceCloneSample,
)
from apps.api.engine.charges import EngineCharge, EngineChargeListing
from apps.api.engine.document import engine_document
from apps.api.engine.forwarding_probe import (
    FORWARDING_TEST_AGENT_NAMES,
    TEST_CALL_INSTRUCTIONS,
    TEST_CALL_MAX_SECONDS,
    TEST_CALL_PURPOSE,
    ForwardingLegReport,
)
from apps.api.engine.health import PlatformStatus
from apps.api.engine.recording_source import EngineRecordingSource, RecordingFetchRules
from apps.api.engine.test_chat import TEST_CHAT_UNAVAILABLE, TestChatTool, TestChatTurn
from apps.api.engine.text_split import split_for_text_cap
from apps.api.engine.thinnest_workspace import (
    trial_agent_allowed,
    trial_agent_in_developer_workspace,
    workspace_headers,
    workspace_not_provisioned,
    workspace_of,
)
from apps.api.engine.trial_line import TRIAL_LINE_AGENT_NAME, TrialLineAgent
from apps.api.engine.vendor_http import (
    REQUEST_TIMEOUT_S,
    SCOPE_NOT_FOUND_CODES,
    EngineRejectedError,
    recipient_opted_out_error,
    vendor_audio_request,
    vendor_request,
)

log = get_logger(__name__)

# api-reference/introduction.md:24-28; authentication.md:10 (`Authorization: Bearer ta_live_…`).
BASE_URL: Final = "https://app.thinnest.ai/api/v1"
AUTH_HEADER: Final = "Authorization"
AUTH_SCHEME: Final = "Bearer"
# snapshots/2026-10-08/pages/api-reference/webhooks.md:100-108: `sha256=<hex>` HMAC-SHA256 of
# `<delivered-at>.<raw body>` under the endpoint's `signingSecret`, with the attempt's send time.
SIGNATURE_HEADER: Final = "x-thinnest-signature-v2"
DELIVERED_AT_HEADER: Final = "x-thinnest-delivered-at"
#: How far a delivery time may be from our clock (webhooks.md:129-131).
DELIVERY_TOLERANCE: Final = timedelta(minutes=5)
IDEMPOTENCY_HEADER: Final = "Idempotency-Key"
#: The 409 code for an `Idempotency-Key` whose first request is still being processed: it
#: may yet succeed, so it is never a refusal (snapshots/2026-10-08/pages/api-reference/
#: errors.md:164).
IDEMPOTENCY_IN_PROGRESS_CODE: Final = "idempotency_in_progress"
# customers.md:68-91: any request runs inside the customer this header names.

# Every list takes `limit` (up to 100) and `cursor` and answers `{items, nextCursor}`
# (introduction.md:55-57; list-calls.md:56-61). The page cap is ours: a walk with no bound
# is an outage against the vendor the first time a cursor misbehaves.
_LISTING_PAGE_SIZE: Final = 100
_LISTING_MAX_PAGES: Final = 20

#: The reply latency ThinnestAI's own agent model dropdown shows for each model, in
#: milliseconds, keyed by the model's console name (`GET /models` `name` is "its name as the
#: console shows it", list-models.md:483-485). FOUNDER-RELAYED reading of the console,
#: 10 Oct 2026, confirmed unchanged 11 Oct 2026; the API returns no latency
#: (snapshots/2026-10-08/pages/api-reference/models/list-models.md:463-505). Shown to
#: operators only. The per-minute BAND that prices a model is not here: an operator records
#: it in the ops console (`agents/engine_model_bands.py`). The adapter returns the vendor's
#: own `callTier` beside it only so a disagreement can be shown, so nothing here can make a
#: model sellable.
_MODEL_CONSOLE_LATENCY_MS: Final[dict[str, int]] = {
    "Prana": 154,
    "GPT-OSS 120B": 221,
    "Prana [Voice]": 560,
    "GPT-4.1 Nano": 578,
    "GPT-5.4 Nano": 734,
    "GPT-5 Mini": 823,
    "GPT-5 Nano": 915,
    "GPT-5.6 Luna": 1072,
}


def _catalogue_model(model_id: str, label: str, row: dict[str, Any]) -> CatalogueModel:
    return CatalogueModel(
        model_id=model_id,
        label=label,
        call_capable=row.get("voice") is True,
        plan_allows=row.get("available") is True,
        voice_only_byok=row.get("voiceOnlyByok") is True,
        console_latency_ms=_MODEL_CONSOLE_LATENCY_MS.get(label),
        listed_call_tier=_CALL_TIERS.get(str(row.get("callTier"))),
        listed_price_per_minute=_micro_amount(row.get("callPricePerMinuteMicro")),
        listed_currency=_str(row.get("currency")),
    )


#: `GET /models` `callTier`: the tier a call on the model bills at with a standard voice;
#: `callPricePerMinuteMicro` is that tier's minute in millionths of `currency`, plan discount
#: included, null when it cannot be worked out (docs.thinnest.ai api-reference/models/
#: list-models, read 12 Oct 2026). Read for operators to check the recorded band against;
#: never billed from (hard rule 7).
_CALL_TIERS: Final[dict[str, Literal["standard", "premium"]]] = {
    "standard": "standard",
    "premium": "premium",
}


def _micro_amount(value: Any) -> Decimal | None:
    """Integer millionths as a `Decimal` amount, or None for anything that is not one."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return Decimal(value) / _MICRO_PER_UNIT


# Field limits the vendor enforces with a 400 (agents.md:88-99, :161; place-call.md:70,
# :96-100, :203-204; knowledge.md:52). Checked here so a publish is refused with a sentence
# an operator can act on rather than a generic `engine_rejected`, and never truncated:
# a truncated prompt loses its tail, which is where the truthful-answer rule sits.
# `instructions`: 20,000 characters everywhere, API, console save and MCP (ThinnestAI's email
# of 12 Oct 2026, VENDOR-STATED; the 8,000 their console once showed was only its text box;
# docs.thinnest.ai api-reference/agents/update-agent, read 12 Oct 2026, says 20,000). The
# script's stages go to the native `steps` field (`_steps_body`), counted separately.
# `greeting` 200 (create-agent.md:434); `purpose` "under 300 characters" (snapshots/
# 2026-10-07/pages/api-reference/calls/place-call.md:7).
INSTRUCTIONS_MAX_CHARS: Final = 20_000
#: `businessDescription`, "One line about what the business is" (snapshots/2026-10-08/pages/
#: api-reference/agents/update-agent.md:531-534).
BUSINESS_DESCRIPTION_MAX_CHARS: Final = 200
GREETING_MAX_CHARS: Final = 200
PURPOSE_MAX_CHARS: Final = 300
NAME_MAX_CHARS: Final = 60
KB_TEXT_MAX_CHARS: Final = 200_000
# Ours, not the vendor's: a source longer than this is refused rather than sent as a pile of
# documents. Ten parts covers any document our own chunker accepts with room to spare.
KB_MAX_PARTS: Final = 10
KB_TOTAL_MAX_CHARS: Final = KB_TEXT_MAX_CHARS * KB_MAX_PARTS
CALL_SECONDS_MIN: Final = 60
CALL_SECONDS_MAX: Final = 1200
#: How long a call the agent places rings before it is given up: fixed at the vendor's own
#: default (`voice.ringSeconds`, 10-60, default 30; docs.thinnest.ai api-reference/agents/
#: update-agent, read 10 Oct 2026) and stated on every publish so a console edit is repaired.
RING_SECONDS: Final = 30
#: `voice.turnDetection` on every agent: a stretch of silence ends the caller's turn.
TURN_DETECTION: Final = "timer"
#: Where an agent answers besides the phone (`voice.surfaces`), as the drift panel names
#: each place. We send phone only (`_agent_body`), so any of these is drift and is repaired
#: (founder decision F1, 12 Oct 2026, superseding D-720's "information only").
SURFACE_NAMES: Final[dict[str, str]] = {"web": "website call button", "whatsapp": "WhatsApp"}
#: How an agent takes turns and fills pauses, the same on every agent (founder decisions F3,
#: F4, F10, 12 Oct 2026): sent on every publish, so a console change reads as drift and is
#: repaired. A caller interrupts after 3 words, short words over the agent are kept and
#: answered, the greeting may be interrupted, no acknowledgement before every reply, and no
#: end phrases, because the vendor matches them anywhere in what the caller says and a short
#: one could end a call mid-sentence. Filler timings are the vendor's defaults, stated. Names,
#: ranges and defaults: docs.thinnest.ai api-reference/agents/update-agent `voice`, read
#: 12 Oct 2026 (`interruptWords` 1-6, `thinkingDelayMs` 200-5000, `thinkingRepeatMs`
#: 1000-10000, `endPhrases` up to 12).
PLATFORM_VOICE_VALUES: Final[dict[str, Any]] = {
    "interruptWords": 3,
    "holdShortSpeech": True,
    "neverInterrupt": False,
    "greetingUninterruptible": False,
    "thinkingAtTurnEnd": False,
    "thinkingDelayMs": 900,
    "thinkingRepeatMs": 2500,
    "endPhrases": [],
}
CALL_VARIABLES_MAX: Final = 20
#: `name` on a placed call (place-call.md:895-899).
LEAD_NAME_MAX: Final = 120
#: `text` on `POST /byok/voices/preview` (snapshots/2026-10-07b/pages/api-reference/
#: bring-your-own-keys/preview-byok-voice.md:453-458).
BYOK_PREVIEW_TEXT_MAX_CHARS: Final = 200
#: `handOver.line` and `voice.unavailableMessage` (snapshots/2026-10-08/pages/api-reference/
#: tools/update-built-in-tools.md:612-621; agents/update-agent.md:999-1016). Both refuse
#: longer with a 400 rather than cutting.
HANDOVER_LINE_MAX_CHARS: Final = 300
UNAVAILABLE_MESSAGE_MAX_CHARS: Final = 300
#: What a caller hears while an agent's line is paused (`override_call_script`). The same
#: words as `agents.service.CREDIT_STOP_MESSAGE` (`tests/thinnest_sync_test.py` holds them
#: equal): no reason, no claim about the business, English so the carrier's voice can read it.
PAUSED_LINE_MESSAGE: Final = "Sorry, we cannot take your call right now. Please try again later."
#: `costMicro` is integer micro-units: 1,000,000 is one rupee
#: (snapshots/2026-10-07/pages/api-reference/usage/list-call-log.md:533-540).
_MICRO_PER_UNIT: Final = Decimal(1_000_000)

#: Every agent's `language`, one language or several: `auto` ("Match the customer") replies in
#: whatever language the caller speaks (founder, 19 Oct 2026: follow the caller). The
#: trade-off is the vendor's own: auto works the language out afresh for every sentence, so a
#: short or mixed reply can be heard as another language, where one fixed language would also
#: tell the recogniser what to listen for (snapshots/2026-10-18/pages/agent/
#: behaviour.md:89-103). The opening line is still composed in the main language, so a call
#: starts in it. `languages`, the list that would restrict replies to the agent's own, is not
#: sent: under auto it would be `[]`, which `language: auto` already says.
_AUTO_LANGUAGE: Final = "auto"
#: The console's 37 English language names (snapshots/2026-10-08/pages/api-reference/agents/
#: create-agent.md:603-614) by our BCP-47 primary subtag, for reading a language back by name
#: or tag.
_DOCUMENTED_LANGUAGES: Final[dict[str, str]] = {
    "en": "English",
    "hi": "Hindi",
    "as": "Assamese",
    "bn": "Bengali",
    "brx": "Bodo",
    "doi": "Dogri",
    "fr": "French",
    "de": "German",
    "gu": "Gujarati",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ks": "Kashmiri",
    "kok": "Konkani",
    "ko": "Korean",
    "mai": "Maithili",
    "ml": "Malayalam",
    "mni": "Manipuri",
    "mr": "Marathi",
    "ne": "Nepali",
    "or": "Odia",
    "pl": "Polish",
    "pt": "Portuguese",
    "pa": "Punjabi",
    "ru": "Russian",
    "sa": "Sanskrit",
    "sat": "Santali",
    "sd": "Sindhi",
    "es": "Spanish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "ur": "Urdu",
    "vi": "Vietnamese",
}

# Call `status` and `hangup` vocabularies (get-call.md:134-144). `missed` is refined by the
# hangup reason; `cancelled` (never rang, get-call.md:136-137) has no member of ours and
# lands in `failed`, which is terminal and never billable as a success.
_STATUS_MAP: Final[dict[str, CallStatus]] = {
    "scheduled": "queued",
    "ringing": "ringing",
    "connected": "in_progress",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
}
_MISSED_BY_HANGUP: Final[dict[str, CallStatus]] = {
    "busy": "busy",
    "voicemail": "voicemail",
}
_TERMINAL_RAW: Final = frozenset({"completed", "missed", "failed", "cancelled"})
_LIVE_RAW: Final = frozenset({"ringing", "connected"})

# Transcript speakers (get-call.md:157-160). `team` is a teammate who joined from their
# console: neither our agent nor the caller, so it is not filed under either and is counted
# in `transcript_lines_unparsed` instead of being attributed to the AI.
_SPEAKERS: Final[dict[str, Speaker]] = {"agent": "agent", "customer": "caller"}

# The suffix that lets `create_agent` find an agent it already made. A digest of OUR ids,
# never a client-visible string and never PII; 48 bits keeps collisions out of reach for
# the agent counts one account holds.
_NAME_TAG_PREFIX: Final = " #cv-"
_NAME_TAG_RE: Final = re.compile(r" #cv-[0-9a-f]{12}$")

# The code `agents.service.DIAL_NOT_PLACED_CODES` already treats as "refused before any
# request was sent".
DIAL_PRECONDITION_FAILED: Final = "carrier_dial_precondition_failed"

#: The 403 codes that say our key's level is too low for the request (errors.md:89-90 in
#: snapshots/2026-10-15). Another 403 is about the person, the number or the workspace.
KEY_SCOPE_CODES: Final = frozenset({"key_scope_build", "key_scope_read"})

#: The vendor's 409 code when `voice.surfaces` names phone on an agent with no number
#: (docs.thinnest.ai api-reference/agents/update-agent, read 12 Oct 2026).
PHONE_NUMBER_REQUIRED: Final = "phone_number_required"

#: Logged when the LLM key slot refuses: no language-model key of ours is installed on this
#: engine. Only the VOICE key is ours (D-688).
LLM_KEY_NOT_INSTALLED: Final = "llm_key_not_installed"

#: `GET /voices` `tier` -> our band word (snapshots/2026-10-07b/pages/api-reference/voices/
#: list-voices.md:436-442). A row in a band not named here cannot be priced or sold, so it is
#: not read. Which band is sold is `Settings.thinnest_clear_voice_band`; clones are Studio
#: (channels/voice-clone.md:10-12).
_VOICE_BANDS: Final[dict[str, HostedVoiceBand]] = {band: band for band in get_args(HostedVoiceBand)}

# Capability profile. Each line's evidence:
# * stt/tts/llm `engine`: the engine dictates every leg. Voices and models are chosen from
#   what it hosts (`GET /voices`, `GET /models`, and the voices of
#   our own voice key, `GET /byok/voices`); `ModelConfig`'s legs never reach it.
# * `control_plane`: agents are created, read, edited and deleted over REST (agents.md:74-82)
#   and `GET /agents/{id}` returns `instructions` and `greeting` for the read-back.
# * `records_audio`: we send `recordCalls: true` (agents.md:160) and phone calls are
#   recorded on every number (channels/voice.md:426-438).
# * `knowledge_base`: agent-scoped text documents (knowledge.md:38-52).
# * `number_series` empty, `inbound_binding` False: renting and attaching a number are done
#   in their console (voices-and-models.md:85-87; agents.md:167-168).
# * `caller_id` True: `from` names which of the agent's numbers rings, and a number that is
#   not the agent's is refused rather than swapped (place-call.md:178-192, :260-263).
# * `transfer` False: nothing outside a running call can move it to a person.
#   `in_call_handoff` True: the agent puts a caller through itself to the `handOver` phone
#   fixed at publish, with `tools.escalate_to_human` on (snapshots/2026-10-08/pages/
#   channels/voice.md:483-492; api-reference/tools/update-built-in-tools.md:553-637). It
#   transfers on numbers rented from ThinnestAI and on Plivo or Telnyx numbers; on any other
#   carrier the platform falls back to a chat hand-over (its team is told, and the agent says
#   somebody will follow up).
# * `action_tools` True (D-700): a CLIENT's own during-call actions (D-615,
#   `AgentConfig.action_tools`) are vendor custom actions on the agent, in its own workspace,
#   registered and kept in shape beside our four platform tools by
#   `reliability/engine_actions.py` (converge by name, the agent's sealed secret, the drift
#   sweep) and executed by `actions/in_call.py`. This adapter renders nothing for them: the
#   agent body carries no tool list, so the capability is the promise the sync keeps.
# * `script_override` True: `PATCH /agents/{id}` changes "any subset" (agents.md:81), so the
#   greeting and instructions move without rewriting the rest of the agent.
# * `webhook_auth` `hmac`: see SIGNATURE_HEADER.
THINNEST_CAPABILITIES = EngineCapabilities(
    records_audio=True,
    stt="engine",
    tts="engine",
    llm="engine",
    agent_hosting="control_plane",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    caller_id=True,
    inbound_binding=False,
    transfer=False,
    in_call_handoff=True,
    action_tools=True,
    script_override=True,
    webhook_auth="hmac",
)

#: Resolves an agent ref to that agent's webhook signing secret, or None when none is held.
#: The secret is returned once by `POST /webhooks` (webhooks.md:36-39) and stored sealed by
#: the webhook registration path; this adapter only reads it.
SigningSecretResolver = Callable[[str], str | None]


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _test_chat_tool(item: dict[str, Any], name: str) -> TestChatTool:
    """One `TestChatToolUse` (test-chat.md:616-635: `name`, `output` when it succeeded,
    `error` when it failed). `output` is whatever the tool answered; for one of our actions
    that is our `{status, say}` object, as an object or as its JSON text."""
    output = item.get("output")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            output = None
    status = output.get("status") if isinstance(output, dict) else None
    return TestChatTool(
        name=name,
        ok=item.get("error") is None,
        status=status[:40] if isinstance(status, str) and status else None,
    )


def _tidy_spoken(text: str) -> str:
    """A sentence with an unfilled `{{name}}` removed, without the gap it leaves.

    "Hello {{lead_name}}, calling from …" with no name becomes "Hello, calling from …"
    rather than "Hello , calling", which a voice reads as a pause in the wrong place.
    """
    collapsed = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"[ \t]+([,.!?])", r"\1", collapsed).strip()


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _e164(value: Any) -> str | None:
    """Their numbers come with or without `+` (place-call.md:60-63, get-call.md:23-24)."""
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return f"+{digits}" if digits else None


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("items")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _our_status(raw_status: str, hangup: str | None) -> CallStatus:
    if raw_status == "missed":
        return _MISSED_BY_HANGUP.get(hangup or "", "no_answer")
    return _STATUS_MAP.get(raw_status, "failed")


def _scoped(raw: str | None, workspace: str | None) -> str | None:
    """A vendor id read from a response, as our handle in the workspace it was read from."""
    return scoped_handle(raw, workspace) if raw else None


def _agent_ref_of(payload: dict[str, Any]) -> str | None:
    """The engine agent id: `agent: {id, name}` on call objects (get-call.md:25). A bare
    string `agent`, and `agent_id`, are read as well because the conformance suite feeds
    every adapter one neutral payload; neither is a ThinnestAI field."""
    agent = payload.get("agent")
    if isinstance(agent, dict):
        return _str(agent.get("id"))
    return _str(agent) or _str(payload.get("agent_id"))


def _call_id_of(payload: dict[str, Any]) -> str | None:
    """The id Get Call takes. `id` is the place-call id (`out_…`/`sch_…`) that dispatch
    stored; `call.completed` sends it only for a call placed through the API and `callRef`
    on every call, so an inbound call is named by `callRef` (docs.thinnest.ai
    api-reference/webhooks "call.completed", read 11 Oct 2026)."""
    return _str(payload.get("id")) or _str(payload.get("callRef"))


def _whole(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if value >= 0 else None


def _spread(value: Any) -> tuple[int | None, int | None, int | None]:
    """`{median, p90, max}` in milliseconds; any part may be null."""
    if not isinstance(value, dict):
        return None, None, None
    return _whole(value.get("median")), _whole(value.get("p90")), _whole(value.get("max"))


def parse_quality(value: Any) -> CallQuality | None:
    """The call's `quality` block (docs.thinnest.ai api-reference/webhooks "Call quality",
    read 11 Oct 2026) in our names, or None when the engine measured nothing. Numbers only:
    a field that is not a non-negative number is read as not measured."""
    if not isinstance(value, dict):
        return None
    reply = _spread(value.get("responseMs"))
    first = _spread(value.get("firstTokenMs"))
    silence = value.get("longestSilenceSeconds")
    longest = (
        float(silence)
        if isinstance(silence, int | float) and not isinstance(silence, bool) and silence >= 0
        else None
    )
    return CallQuality(
        turns=_whole(value.get("turns")),
        reply_ms_median=reply[0],
        reply_ms_p90=reply[1],
        reply_ms_max=reply[2],
        first_token_ms_median=first[0],
        first_token_ms_p90=first[1],
        first_token_ms_max=first[2],
        long_silences=_whole(value.get("longSilences")),
        longest_silence_s=longest,
        interruptions=_whole(value.get("interruptions")),
        model_errors=_whole(value.get("modelErrors")),
        backup_answers=_whole(value.get("rescues")),
    )


def parse_llm_usage(value: Any) -> CallLlmUsage | None:
    """The call's `usage` block in our names, or None when the engine sent none: `inputTokens`,
    `outputTokens`, `cachedInputTokens` and `inputTokensEstimated`, each null when not
    recorded, our own model key's tokens included (`thinnest-findings/mirror/snapshots/
    2026-10-15/pages/api-reference/calls/get-call.md:1171-1217`; `call.analysed` carries the
    same object, `api-reference/webhooks/create-webhook.md:330-340`)."""
    if not isinstance(value, dict):
        return None
    estimated = value.get("inputTokensEstimated")
    return CallLlmUsage(
        input_tokens=_whole(value.get("inputTokens")),
        output_tokens=_whole(value.get("outputTokens")),
        cached_input_tokens=_whole(value.get("cachedInputTokens")),
        input_tokens_estimated=estimated if isinstance(estimated, bool) else None,
    )


def parse_tts_characters(value: Any) -> int | None:
    """`usage.ttsCharacters`: characters sent to the voice, text cut off by the caller
    included, on our own voice key too; null when nothing was sent (snapshots/2026-10-15/
    pages/api-reference/calls/get-call.md:1218-1227)."""
    return _whole(value.get("ttsCharacters")) if isinstance(value, dict) else None


_CALL_KEYS: Final[frozenset[str]] = frozenset(get_args(CallKeys))
_VOICE_PLANS: Final[frozenset[str]] = frozenset(get_args(CallVoicePlan))


#: The call's `hangup` when it ended before the agent spoke (snapshots/2026-10-18/pages/
#: api-reference/calls/get-call.md:918-933; the console's "Ended before the agent spoke",
#: channels/voice.md:443). Such a call, like a forwarded one, is charged the phone carrier's
#: fee only, in 30-second blocks (get-call.md:1236-1243); what that fee is reaches money
#: only as the operator-attested `carrier` rate (`billing/engine_minutes.CARRIER_RATE_KEY`).
_BEFORE_AGENT_HANGUP: Final = "before_agent"


def parse_billing(
    value: Any, *, hangup: str | None = None, forwarded: bool = False
) -> CallBilling | None:
    """The call's `billing` object in our names (snapshots/2026-10-18/pages/api-reference/
    calls/get-call.md:1228-1310; List Calls rows and `call.analysed` carry the same one,
    calls/list-calls.md:769-773, api-reference/webhooks/create-webhook.md:330-340). None for a
    booked call that has not rung (get-call.md:1228-1233), and for a `keys` outside the
    documented enum (:1257-1269), which is no billing we can read. `voicePlan` is lower case
    (:1270-1282); `ratePerMinuteMicro` is millionths of `currency` (:1283-1292), read as
    rupees only; `billedSeconds` is null until a charge was taken and on a free trial call
    (:1293-1302). A call that ended before the agent spoke (`hangup`) or was `forwarded`
    without an agent is carrier-only: its plan and rate are the ones it was set up on, not
    what was charged (:1236-1243)."""
    if not isinstance(value, dict):
        return None
    keys = value.get("keys")
    if keys not in _CALL_KEYS:
        return None
    plan = value.get("voicePlan")
    currency = value.get("currency")
    micro = _whole(value.get("ratePerMinuteMicro"))
    return CallBilling(
        keys=keys,
        voice_plan=plan if plan in _VOICE_PLANS else None,
        rate_inr_per_min=Decimal(micro) / _MICRO_PER_UNIT
        if micro is not None and _is_rupees(value)
        else None,
        currency=currency if currency in ("INR", "USD") else None,
        billed_seconds=_whole(value.get("billedSeconds")),
        carrier_only=forwarded or hangup == _BEFORE_AGENT_HANGUP,
    )


#: The one value of the status read's parts that means healthy.
STATUS_OPERATIONAL: Final = "operational"
#: The status read sits inside the healer's tick; a slow answer is no answer.
STATUS_TIMEOUT_S: Final = 3.0
_STATUS_WORD_RE: Final = re.compile(r"^[a-z_]{1,24}$")


def _status_word(value: Any) -> str:
    """A status part fit for an operator's alarm line: a short lower-case word or `other`."""
    word = value if isinstance(value, str) else ""
    return word if _STATUS_WORD_RE.match(word) else "other"


#: `call.problem`'s `kind` in our vocabulary (webhooks "Problems on a live call").
#: `byok_failed` is "your own model key failed", so it is named for the key, not the voice.
_PROBLEM_KINDS: Final[dict[str, EngineProblemKind]] = {
    "no_answer_from_model": "no_answer_from_model",
    "byok_failed": "own_key_failed",
    "slow_reply": "slow_reply",
    "voice_failed": "voice_failed",
}

#: `byok.changed`'s `change` values (snapshots/2026-10-15/pages/api-reference/
#: webhooks.md:565-597), the same words as ours.
_BYOK_CHANGES: Final = frozenset(get_args(EngineByokChange))


def _content_deleted(call: dict[str, Any]) -> bool:
    """`contentDeleted` on Get Call and List Calls: true once a call's recording and
    transcript were deleted (snapshots/2026-10-15/pages/api-reference/calls/
    get-call.md:1014-1027)."""
    return call.get("contentDeleted") is True


#: The most of the vendor's problem sentence an operator alarm carries.
PROBLEM_DETAIL_MAX_CHARS: Final = 240
#: Six or more digits in a row could be a phone number or an account id, which the alarm
#: line must not carry (hard rule 6); a key failure needs neither.
_LONG_DIGITS_RE: Final = re.compile(r"\d[\d\s-]{4,}\d")


def problem_detail(value: Any) -> str | None:
    """`call.problem`'s `detail` fit for an operator alarm: one line, long digit runs
    masked, at most `PROBLEM_DETAIL_MAX_CHARS`; None when there is no sentence."""
    if not isinstance(value, str):
        return None
    line = " ".join(value.split())
    line = _LONG_DIGITS_RE.sub(
        lambda m: "[number]" if sum(ch.isdigit() for ch in m.group()) >= 6 else m.group(), line
    )
    if len(line) > PROBLEM_DETAIL_MAX_CHARS:
        line = line[: PROBLEM_DETAIL_MAX_CHARS - 1].rstrip() + "…"
    return line or None


def _turn_start_ms(
    entry: dict[str, Any], *, started: datetime | None, answered: datetime | None
) -> int | None:
    """Where a turn roughly falls in the recording, in ms, or None when nothing places it.

    ThinnestAI gives each turn `at` (get-call.md:385-390) and, on the transcript endpoint,
    `offset`: "Whole seconds from the start of the call to `at` — for order and rough
    position, not audio sync" (get-call-transcript.md:635-642), and "when it was written
    down, not where it falls in the audio" (:7). So the result is approximate by the
    vendor's own account and every turn built from it says so (`start_approximate`).

    Measured from `answeredAt`, not `startedAt`: in the vendor's example `seconds` (182) is
    `endedAt - answeredAt`, not `endedAt - startedAt` (189.8), so talk time, and we assume
    the recording, begin at the answer. UNVERIFIED against a real recording; the screen
    seeks a couple of seconds early to absorb the error either way.
    """
    origin = answered or started
    at = _parse_dt(entry.get("at"))
    if at is not None and origin is not None:
        return max(int((at - origin).total_seconds() * 1000), 0)
    offset = entry.get("offset")
    if isinstance(offset, int | float) and not isinstance(offset, bool) and offset >= 0:
        ring_ms = (
            int((answered - started).total_seconds() * 1000)
            if answered is not None and started is not None
            else 0
        )
        return max(int(offset * 1000) - ring_ms, 0)
    return None


def parse_transcript(
    raw: Any,
    call_id: str,
    *,
    started: datetime | None = None,
    answered: datetime | None = None,
) -> tuple[list[TranscriptTurn], int]:
    """`[{speaker, text, at}]` (get-call.md:35-38) to our turns, and how many we could not
    place. Counted rather than kept: transcript text is hard rule 6.

    Each turn carries its approximate place in the recording (`_turn_start_ms`) so key
    moments and the transcript can point at the audio at all; without it every turn on
    this engine had `start_ms = None` and no moment could be anchored.
    """
    if not isinstance(raw, list):
        return [], 0
    turns: list[TranscriptTurn] = []
    lost = 0
    for entry in raw:
        if not isinstance(entry, dict):
            lost += 1
            continue
        speaker = _SPEAKERS.get(str(entry.get("speaker") or "").lower())
        text = entry.get("text")
        if speaker is None or not isinstance(text, str) or not text.strip():
            lost += 1
            continue
        start_ms = _turn_start_ms(entry, started=started, answered=answered)
        turns.append(
            TranscriptTurn(
                call_id=call_id,
                idx=len(turns),
                speaker=speaker,
                text=text.strip(),
                start_ms=start_ms,
                start_approximate=start_ms is not None,
            )
        )
    return turns, lost


# A knowledge source sent as several documents. The handle is the prefix and the parts'
# ids in order; each part's title carries `[cv-part i/n group]` so `list_kb` can rebuild the
# same handle from the vendor's list. `group` is per upload, so two copies of one source
# never merge.
_COMPOSITE_PREFIX: Final = "cv-parts:"
_PART_MARKER: Final = " [cv-part {i}/{n} {g}]"
_PART_MARKER_RE: Final = re.compile(r" \[cv-part (\d+)/(\d+) ([0-9a-f]{12})\]$")


class _KnowledgeIngestFailedError(Exception):
    """A document the vendor stored and could not index; `handle` is its id."""

    def __init__(self, handle: str) -> None:
        super().__init__(handle)
        self.handle = handle


def _ingest_failed() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_kb_ingest_failed",
        title="The voice platform could not index this knowledge",
        detail="The knowledge was uploaded and the voice platform could not index it.",
        remediation="Try publishing the knowledge again. If it keeps failing, contact us.",
    )


def _parts_of(handle: EngineKBRef) -> list[str]:
    if handle.startswith(_COMPOSITE_PREFIX):
        return [part for part in handle.removeprefix(_COMPOSITE_PREFIX).split(",") if part]
    return [handle]


def _rebuild_composites(rows: Sequence[dict[str, Any]]) -> list[EngineKBRef]:
    """Document ids, with every complete set of parts folded back into its handle. A set
    with a part missing is listed part by part, so the caller sees loose documents rather
    than a handle that would claim the whole source is held."""
    handles: list[EngineKBRef] = []
    groups: dict[tuple[str, int], dict[int, str]] = {}
    for row in rows:
        handle = _str(row.get("id"))
        if handle is None:
            continue
        marker = _PART_MARKER_RE.search(_str(row.get("title")) or "")
        if marker is None:
            handles.append(handle)
            continue
        index, total, group = int(marker[1]), int(marker[2]), marker[3]
        groups.setdefault((group, total), {})[index] = handle
    for (_group, total), parts in groups.items():
        if sorted(parts) == list(range(1, total + 1)):
            handles.append(f"{_COMPOSITE_PREFIX}{','.join(parts[i] for i in sorted(parts))}")
        else:
            handles.extend(parts[i] for i in sorted(parts))
    return handles


def _business_refusal(code: str, *, title: str, detail: str, remediation: str) -> ProblemError:
    log.warning("thinnest_request_refused", extra={"code": code})
    return ProblemError(
        kind="business_rule", code=code, title=title, detail=detail, remediation=remediation
    )


def _bad_response(detail: str) -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_bad_response",
        title="Voice engine returned an unusable response",
        detail=detail,
    )


def _dial_precondition_failed(*, missing: str) -> ProblemError:
    log.warning("thinnest_dial_precondition_failed", extra={"missing": missing})
    return ProblemError(
        kind="dependency",
        code=DIAL_PRECONDITION_FAILED,
        title="The call could not be started",
        detail=f"The voice platform could not start this call: the {missing} is missing.",
        remediation="Publish the agent again. If it keeps failing, contact us.",
    )


#: `POST /calls` refusals the vendor documents as "the call was not placed", whatever their
#: status (snapshots/2026-10-08/pages/api-reference/errors.md:109-134). A 5xx with one of
#: these codes is therefore a refusal and not "the phone may be ringing".
# `idempotency_in_progress` is absent: the first request may have placed it (`_dial_refusal`).
_DIAL_NOT_PLACED_CODES: Final = frozenset(
    {
        "opted_out",
        "do_not_call",
        "stop_list_unknown",
        "insufficient_balance",
        "outside_calling_hours",
        "number_never_callable",
        "call_in_progress",
        "call_already_scheduled",
        "calling_not_set_up",
        "carrier_unavailable",
        "agent_not_found",
        "agent_ambiguous",
        "from_number_invalid",
        "invalid_number",
        "needs_own_carrier_keys",
        "key_scope_build",
        "key_scope_read",
        "unauthorized",
    }
)
#: Refusals that are OUR configuration at the vendor, not the person or the moment: every
#: dial fails the same way until an operator acts, so each is alarmed by its code.
_DIAL_SETUP_CODES: Final = frozenset(
    {
        "calling_not_set_up",
        "agent_not_found",
        "agent_ambiguous",
        "from_number_invalid",
        "needs_own_carrier_keys",
    }
)


def _dial_refusal(exc: EngineRejectedError) -> ProblemError:
    """`POST /calls`' refusal in our vocabulary, branching on the vendor's `code` and never
    on its sentence (errors.md:18-37). A code we do not know keeps the status's generic
    meaning, which is the ladder's own reading of it."""
    code = exc.vendor_code
    setup = code in _DIAL_SETUP_CODES or (
        code == "carrier_unavailable" and exc.vendor_status == 502
    )
    if code == IDEMPOTENCY_IN_PROGRESS_CODE:
        # The first request with this key is still being processed (errors.md:164) and may
        # yet place the call, so this 409 proves nothing was placed: the dial is unconfirmed.
        return EngineRejectedError(
            status=exc.vendor_status,
            vendor_error=exc.vendor_error,
            refused_statuses=frozenset(),
            vendor_code=code,
            vendor_reason=exc.vendor_reason,
        )
    if code in ("opted_out", "do_not_call"):
        # The person, on the workspace's shared list. Whether the entry is this client's is
        # decided above the adapter (`compliance/platform_dnc.py`).
        return recipient_opted_out_error()
    if code in KEY_SCOPE_CODES:
        alert(
            "CORE_LOGIC",
            "engine_key_cannot_place_calls",
            detail=f"ThinnestAI refused a dial with {code}: THINNEST_API_KEY is not a full "
            "key, so every dial is refused; set it to a full-access key",
        )
    elif code == "insufficient_balance" or exc.vendor_status == 402:
        reason = f" ({exc.vendor_reason})" if exc.vendor_reason else ""
        alert(
            "CORE_LOGIC",
            "engine_balance_exhausted",
            detail=f"ThinnestAI refused a dial because the workspace balance cannot pay for "
            f"a call{reason}; no call is placed until it is topped up",
        )
    elif setup:
        alert(
            "CORE_LOGIC",
            "engine_dial_setup_refused",
            detail=f"ThinnestAI refused a dial with {code}: the agent, its number or the "
            "phone provider is not set up to place this call, so every such dial fails "
            "until it is fixed",
        )
    refusal = exc
    if code in _DIAL_NOT_PLACED_CODES and not exc.request_refused:
        refusal = EngineRejectedError(
            status=exc.vendor_status,
            vendor_error=exc.vendor_error,
            refused_statuses=frozenset({exc.vendor_status}),
            vendor_code=code,
            vendor_reason=exc.vendor_reason,
        )
    refusal.setup_refused = setup
    return refusal


def _clone_refusal(exc: EngineRejectedError) -> ProblemError:
    """`POST /voice-clones`' documented refusals in our words (create-voice-clone.md:
    384-460): `400` the recording or a field, `403` the plan, `409` the clone limit."""
    if exc.vendor_status == 403:
        return _business_refusal(
            "voice_clone_not_on_plan",
            title="Voice cloning needs ThinnestAI Pro",
            detail="Cloning a voice needs the ThinnestAI Pro plan or above, and this account is "
            "not on it. Clones are Studio-tier voices, so they can be sold as Clear only while "
            "Clear is sold on the Studio tier.",
            remediation="Upgrade the ThinnestAI account to Pro or above, then clone again.",
        )
    if exc.vendor_status == 409:
        return _business_refusal(
            "voice_clone_limit_reached",
            title="The voice platform holds as many clones as its plan allows",
            detail="The account already has its plan's number of cloned voices.",
            remediation="Delete a clone you no longer use, or ask the voice platform to "
            "raise the limit.",
        )
    if exc.vendor_status == 400:
        return _business_refusal(
            "voice_clone_sample_refused",
            title="The voice platform refused this recording",
            detail="The recording or one of its fields was not accepted: it must be 5 to 30 "
            "seconds of WAV, MP3, M4A or WebM audio, at most 10 MB, with a name of at most 40 "
            "characters and a language the platform offers.",
            remediation="Check the recording and the fields, then clone again.",
        )
    return exc


def _key_state(data: dict[str, Any]) -> OwnVoiceKeyState:
    """A `GET /byok` body (bring-your-own-keys.md:121-147). A body without a readable `using`
    is refused rather than read as "no", because the answer decides which rate a publish
    stamps."""
    using = _str(data.get("using"))
    if using not in {"own", "developer", "none"}:
        raise _bad_response("The voice platform did not say whose keys it is using.")
    credentials = data.get("credentials")
    listed = credentials if isinstance(credentials, list) else []
    rows = [row for row in listed if isinstance(row, dict)]
    voice = next((row for row in rows if row.get("kind") == "tts"), {})
    # `kind: llm` with its `model` and `verifiedAt` (bring-your-own-keys.md:196-222 in the
    # 2026-10-13 snapshot).
    llm = next((row for row in rows if row.get("kind") == "llm"), {})
    return OwnVoiceKeyState(
        enabled=data.get("enabled") is True,
        scope=_str(data.get("scope")),
        complete=data.get("complete") is True,
        using=using,
        voice_provider=_str(voice.get("provider")),
        llm_provider=_str(llm.get("provider")),
        llm_model=_str(llm.get("model")),
        llm_verified=_str(llm.get("verifiedAt")) is not None,
    )


def _byok_value(on: bool, own_model: str | None = None) -> str:
    """The agent's `byok` for our two switches. Without our model: `workspace` follows the
    workspace's voice-only BYOK (our Cartesia key, Studio) and `off` keeps the agent on
    ThinnestAI's own voices and models at their normal rate. With our model (D-764) the scope
    is named outright, whatever the workspace default: `llm_voice` (our model and our voice)
    or `llm` (our model, their voice) (`thinnest-findings/mirror/snapshots/2026-10-13/pages/
    api-reference/agents/update-agent.md:746-768`; bring-your-own-keys.md:80-90)."""
    if own_model:
        return "llm_voice" if on else "llm"
    return "workspace" if on else "off"


#: An agent's `byok` read back as (speaks on our voice key, answers on our model key).
#: `all` is the three-key mode `engine_choice` refuses to sell, so it reads as unknown.
#: `voice` is never sent, but it is a documented read-back (get-agent.md:658-673) with one
#: meaning, so an agent the vendor holds on it is compared, not left unread: sent `llm_voice`
#: and read back `voice` is the per-agent scope not kept, and refuses the publish.
_BYOK_SCOPES: Final[dict[str, tuple[bool, bool]]] = {
    "workspace": (True, False),
    "voice": (True, False),
    "off": (False, False),
    "llm": (False, True),
    "llm_voice": (True, True),
}


def _tools_not_pinned() -> ProblemError:
    return _business_refusal(
        "engine_tools_not_pinned",
        title="The voice platform did not take this agent's tool settings",
        detail="The voice platform did not save every one of the agent's built-in tool "
        "settings, so the agent was not published with tools we did not choose.",
        remediation="Publish the agent again. If it keeps failing, contact us.",
    )


def _digits(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return "".join(ch for ch in value if ch.isdigit()) or None


def _tools_drift(wanted: dict[str, Any], held: dict[str, Any]) -> list[str]:
    """Which of `built_in_tools_body`'s settings the vendor does NOT hold, by our names.

    `held` is a `GET`/`PATCH /agents/{id}/tools` answer: `tools` is a list of `{id, enabled}`
    and `handOver` is `{mode, phone, line}` (update-built-in-tools.md:705-790). A switch the
    answer does not report is drift, never "probably off": a tool we cannot see is one we
    cannot vouch for. The phone is compared by its digits, because the vendor stores what it
    was sent in E.164 and our value already is.
    """
    rows = held.get("tools")
    switches = {
        row.get("id"): row.get("enabled")
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
    }
    drifted = [
        f"tools.{tool}" for tool, on in wanted["tools"].items() if switches.get(tool) is not on
    ]
    want, have = wanted["handOver"], held.get("handOver")
    have = have if isinstance(have, dict) else {}
    if want["mode"] == "call":
        # A chat hand-over keeps whatever phone and line were saved before; only a live
        # transfer depends on them.
        if have.get("mode") != "call":
            drifted.append("handOver.mode")
        if _digits(have.get("phone")) != _digits(want["phone"]):
            drifted.append("handOver.phone")
        if (have.get("line") or None) != want["line"]:
            drifted.append("handOver.line")
    elif have.get("phone") is not None:
        drifted.append("handOver.phone")
    if have.get("agents") and not want.get("agents"):
        drifted.append("handOver.agents")
    return drifted


@dataclass(frozen=True, slots=True)
class HandoffTarget:
    """Another of the client's agents a live call may be passed to."""

    engine_agent_ref: str
    #: True for a Studio agent (our own voice key), False for Clear.
    own_voice_key: bool | None
    #: When to pass it, in a sentence the agent reads.
    when: str


def handoff_agents_body(
    source_own_voice_key: bool | None, targets: Sequence[HandoffTarget]
) -> list[dict[str, str]]:
    """`handOver.agents` for an agent, refusing a target on the other rung.

    ThinnestAI bills a handed call once, at the rate it started at, and keeps the call
    rather than pass it to an agent set to run on different keys (our own versus theirs) or
    on a premium model when the call started at the standard rate (docs.thinnest.ai
    channels/voice "Handing a call on", read 11 Oct 2026; ThinnestAI's email of 11 Oct 2026
    says the save is refused). A Clear agent is on their keys and a Studio agent on ours,
    so a Clear-Studio pair would never hand over: refused here, with a sentence a client
    can act on, rather than saved and silently ignored on a call.
    """
    for target in targets:
        if bool(target.own_voice_key) != bool(source_own_voice_key):
            raise ProblemError.business_rule(
                "handoff_across_voice_tiers",
                "A call can only be passed to an agent on the same voice as the agent that "
                "answered it: Clear to Clear, or Studio to Studio.",
                remediation="Choose an agent on the same voice, or change one agent's voice.",
            )
    return [{"agent": raw_of(t.engine_agent_ref), "when": t.when} for t in targets]


#: Our setting label (`agents/engine_settings.AGENT_SETTING_LABELS`) -> the agent field that
#: carries it (`voice.` for a field of the agent's `voice` object, update-agent.md:940-1016).
_SETTING_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "voice": ("voice.voice",),
    "model": ("model",),
    "language": ("language",),
    "call_language": ("voice.language",),
    "record_calls": ("voice.recordCalls",),
    "max_call_seconds": ("voice.maxCallSeconds",),
    "caller_memory": ("voice.pastConversations",),
    "machine_detection": ("voice.detectMachines",),
    "end_call_on_finish": ("voice.endCallOnFinish",),
    "turn_silence": ("voice.turnSilenceSeconds", "voice.turnDetection"),
    "do_not_call_tool": ("voice.recordDoNotCall",),
    "ring_seconds": ("voice.ringSeconds",),
    "call_summaries": ("voice.summariseCalls",),
    "escalation": ("escalation",),
    "scheduled_callbacks": ("scheduleCallbacks",),
    "lead_capture": ("captureLeads",),
    "collected_fields": ("collectFields",),
    "script_steps": ("steps",),
    "surfaces": ("voice.surfaces",),
    "silence_prompt": ("voice.nudgeAfterSeconds", "voice.nudges", "voice.nudgePhrase"),
    "end_after_silence": ("voice.endAfterSilenceSeconds",),
    "filler_lines": ("voice.thinking", "voice.thinkingLines"),
    "filler_timing": ("voice.thinkingDelayMs", "voice.thinkingRepeatMs", "voice.thinkingAtTurnEnd"),
    "background_sound": ("voice.ambience", "voice.ambienceVolume"),
    "interruptions": (
        "voice.interruptWords",
        "voice.holdShortSpeech",
        "voice.neverInterrupt",
        "voice.greetingUninterruptible",
    ),
    "end_phrases": ("voice.endPhrases",),
    "reply_length": ("maxReplyTokens",),
}
_LANGUAGE_KEYS: Final = frozenset({"language", "voice.language"})


def _same_language(wanted: Any, held: Any) -> bool:
    """A language may come back as its name or its tag (`hi-IN`, update-agent.md:962-970)."""
    if wanted is None or held is None:
        return wanted is held
    if not isinstance(held, str):
        return False
    name = _DOCUMENTED_LANGUAGES.get(_subtag(held), held)
    return str(wanted).lower() in {held.lower(), name.lower()}


def _field(body: dict[str, Any], key: str) -> tuple[bool, Any]:
    """`(present, value)` of `key` in an agent body; `voice.x` reads the voice object."""
    if key.startswith("voice."):
        voice = body.get("voice")
        if not isinstance(voice, dict):
            return False, None
        name = key.removeprefix("voice.")
        return name in voice, voice.get(name)
    return key in body, body.get(key)


#: ThinnestAI's step list (snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:
#: 588-595, AgentStepInput :865-905; read back as AgentStep, :1079-1110 and get-agent.md:
#: 709-743): at most 12 steps, each a title (cut to 80), a detail (cut to 600), branches
#: {when, action} and collect. Script v2 keeps every stage inside those limits
#: (`call_script.MAX_SCRIPT_STAGES`, `STAGE_TITLE_MAX`, `STAGE_DETAIL_MAX`).
STEPS_MAX: Final = 12


def _steps_body(cfg: AgentConfig) -> list[dict[str, Any]]:
    if len(cfg.script_steps) > STEPS_MAX:
        raise _business_refusal(
            "engine_too_many_steps",
            title="This script has too many stages for this voice platform",
            detail=(
                f"The script has {len(cfg.script_steps)} stages and the voice platform holds "
                f"at most {STEPS_MAX}."
            ),
            remediation=f"Combine stages until there are {STEPS_MAX} or fewer, then publish again.",
        )
    return [
        {
            "title": step.title.strip()[:80],
            "detail": step.detail.strip()[:600],
            "branches": [{"when": when, "action": action} for when, action in step.branches],
            "collect": list(step.collect),
        }
        for step in cfg.script_steps
    ]


def _steps_held(value: Any) -> list[dict[str, Any]] | None:
    """The step list as the vendor returned it, in `_steps_body`'s shape, or None when the
    answer is not a list of steps."""
    if not isinstance(value, list):
        return None
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        raw_branches, raw_collect = item.get("branches"), item.get("collect")
        branches: list[Any] = raw_branches if isinstance(raw_branches, list) else []
        collect: list[Any] = raw_collect if isinstance(raw_collect, list) else []
        out.append(
            {
                "title": str(item.get("title") or "").strip(),
                "detail": str(item.get("detail") or "").strip(),
                "branches": [
                    {"when": str(b.get("when") or ""), "action": str(b.get("action") or "")}
                    for b in branches
                    if isinstance(b, dict)
                ],
                "collect": [str(c) for c in collect],
            }
        )
    return out


def _refuse_unsaved_steps(wanted: dict[str, Any], saved: dict[str, Any]) -> None:
    """The publish read-back of the steps: the agent `PATCH`/`POST` answers with the whole
    agent (update-agent.md:7), and a step list that came back different from what was sent
    is refused rather than left live with a script we did not write."""
    if "steps" in saved and _steps_held(saved.get("steps")) != wanted["steps"]:
        log.warning("thinnest_steps_not_saved")
        raise _business_refusal(
            "engine_steps_not_saved",
            title="The voice platform did not save this script's stages",
            detail="The stages read back from the voice platform differ from the ones sent.",
            remediation="Publish again. If it keeps happening, contact us.",
        )


def _settings_drift(wanted: dict[str, Any], held: dict[str, Any]) -> list[str]:
    """The labels whose value in `held` (a `GET /agents/{id}` answer) is not `wanted`'s
    (an `_agent_body`). A setting `wanted` does not state is not ours to compare, and a
    voice or model left on the vendor default (`null` sent) comes back as the default's own
    id, so it is not compared either."""
    drifted: list[str] = []
    for label, keys in _SETTING_KEYS.items():
        for key in keys:
            stated, want = _field(wanted, key)
            if not stated or (key in ("voice.voice", "model") and want is None):
                continue
            present, have = _field(held, key)
            if key in _LANGUAGE_KEYS:
                same = present and _same_language(want, have)
            elif key == "escalation":
                same = isinstance(have, dict) and all(
                    have.get(flag) is value for flag, value in want.items()
                )
            elif key == "collectFields":
                same = isinstance(have, list) and have == want
            elif key == "steps":
                same = _steps_held(have) == want
            elif key == "voice.turnSilenceSeconds":
                same = _same_seconds(want, have)
            elif key == "maxReplyTokens":
                same = _same_whole_number(want, have)
            elif key == "voice.surfaces":
                same = _same_surfaces(want, have)
            elif key in ("voice.thinkingLines", "voice.endPhrases"):
                same = _same_words(want, have, ordered=True)
            elif key == "voice.nudgePhrase":
                same = present and (have or None) == want
            elif key == "voice.ambienceVolume":
                same = _same_hundredths(want, have)
            else:
                same = present and have == want and type(have) is type(want)
            if not same:
                drifted.append(label)
                break
    return drifted


def _same_seconds(wanted: Any, held: Any) -> bool:
    """A pause read back as the same whole milliseconds we sent. A JSON number may come back
    as `0.7` or `0.70`, an integer for whole seconds, or `null` after a console reset to
    the vendor default, which is drift: we always state the value."""
    if isinstance(held, bool) or not isinstance(held, int | float):
        return False
    return round(held * 1000) == round(float(wanted) * 1000)


def _same_whole_number(wanted: int, held: Any) -> bool:
    """A count read back as the one sent. The request schema types `maxReplyTokens` as a
    number the vendor rounds and the answer as an integer (update-agent.md:703-709,
    :839-845), so `300.0` is the same value; `null` or a boolean is drift."""
    if isinstance(held, bool) or not isinstance(held, int | float):
        return False
    return round(held) == wanted


def _refuse_unsaved_reply_length(wanted: dict[str, Any], saved: dict[str, Any]) -> None:
    """The publish read-back of the reply ceiling, from the agent the write answers with
    (update-agent.md:7): a ceiling that came back different would cut the agent's replies
    off somewhere we did not choose, so the publish is refused rather than left live."""
    if "maxReplyTokens" in saved and not _same_whole_number(
        wanted["maxReplyTokens"], saved.get("maxReplyTokens")
    ):
        log.warning("thinnest_reply_length_not_saved")
        raise _business_refusal(
            "engine_reply_length_not_saved",
            title="The voice platform did not save this agent's reply length",
            detail="The longest reply read back from the voice platform differs from the one sent.",
            remediation="Publish again. If it keeps happening, contact us.",
        )


def _same_words(wanted: list[str], held: Any, *, ordered: bool) -> bool:
    """A list of strings read back as the one we sent: surfaces as a set, filler lines and
    end phrases in order. Both lists read back as `[]` when empty (get-agent `voice`, read
    12 Oct 2026); `null` or a non-list is drift."""
    if not isinstance(held, list) or not all(isinstance(item, str) for item in held):
        return False
    have = [item.strip() for item in held]
    want = [item.strip() for item in wanted]
    return have == want if ordered else sorted(set(have)) == sorted(set(want))


def _same_surfaces(wanted: list[str], held: Any) -> bool:
    """`voice.surfaces` read back as the places we sent. A `phone` we did not send is not
    drift: the platform holds it only while the agent has a number to answer or call from
    (update-agent `voice.surfaces`), and an agent lent the shared trial number for a test
    call gets it at the dial (`call_out_on_phone`). Repairing it away would leave that agent
    unable to place its next call; F1 is about the website button and WhatsApp."""
    if isinstance(held, list) and "phone" not in wanted:
        held = [item for item in held if item != "phone"]
    return _same_words(wanted, held, ordered=False)


def _same_hundredths(wanted: Any, held: Any) -> bool:
    """A volume read back as the same hundredths we sent (`0.15` or `0.150`)."""
    if isinstance(held, bool) or not isinstance(held, int | float):
        return False
    return round(held * 100) == round(float(wanted) * 100)


#: Our tuning field -> the `byok-voice` request field (set-agent-byok-voice.md:587-627). The
#: agent's own model reads back as `agentModel`, because `model` there is the key's.
_TUNING_WIRE: Final[tuple[tuple[str, str, str], ...]] = (
    ("speed", "speed", "speed"),
    ("volume", "volume", "volume"),
    ("emotion", "emotion", "emotion"),
    ("model", "model", "agentModel"),
    ("dictionary_id", "pronunciationDictId", "pronunciationDictId"),
)
_TUNING_NUMBERS: Final = frozenset({"speed", "volume"})


def _tuning_wanted(tuning: ByokVoiceTuning | None) -> dict[str, Any]:
    """Every tuning field as the request names it, None where the provider's default is
    wanted. Numbers go as JSON numbers in hundredths; the stored value is NUMERIC(3,2)."""
    held = tuning or ByokVoiceTuning()
    out: dict[str, Any] = {}
    for ours, wire, _read in _TUNING_WIRE:
        value = getattr(held, ours)
        out[wire] = float(value) if isinstance(value, Decimal) else value
    return out


def _tuning_mismatches(wanted: dict[str, Any], held: dict[str, Any]) -> list[str]:
    """The request fields whose value in `held` (a `byok-voice` answer) is not `wanted`'s.
    A field the answer leaves out is a mismatch only when we want a value there: the docs
    give each as null while unset (bring-your-own-keys.md:390-392)."""
    out: list[str] = []
    for _ours, wire, read in _TUNING_WIRE:
        want = wanted[wire]
        if read not in held:
            if want is not None:
                out.append(wire)
            continue
        have = held[read]
        if wire in _TUNING_NUMBERS:
            same = (have is None) if want is None else _same_hundredths(want, have)
        else:
            same = have == want
        if not same:
            out.append(wire)
    return out


def _tuning_refusal(exc: EngineRejectedError) -> ProblemError | None:
    """A `400 validation_failed` naming one of the tuning fields, in our words, or None.
    Speed is refused on a voice cloned from a long recording (a Professional Voice Clone
    keeps its recorded pace), and speed, volume and emotion on the older voice model,
    which is the key's own when the agent names none (bring-your-own-keys.md:396-403)."""
    field = exc.vendor_field
    if exc.vendor_status != 400 or field not in {wire for _o, wire, _r in _TUNING_WIRE}:
        return None
    if field == "speed":
        return _business_refusal(
            "voice_speed_not_for_this_voice",
            title="This voice's speed cannot be changed",
            detail="The voice platform refused the agent's speed setting: this voice keeps "
            "the pace it was recorded at, or the voice model in use takes no speed.",
            remediation="Clear the speed in the agent's voice settings (How it sounds), or "
            "change the volume instead, then publish again. If you cannot, contact us.",
        )
    if field in ("volume", "emotion"):
        return _business_refusal(
            "voice_tuning_not_for_this_model",
            title="This voice model takes no volume or emotion setting",
            detail=f"The voice platform refused the agent's {field} setting for the voice "
            "model in use.",
            remediation="Clear it, or choose a newer voice model in the agent's voice "
            "settings (How it sounds), then publish again. If you cannot, contact us.",
        )
    return _business_refusal(
        "voice_tuning_refused",
        title="The voice platform refused this agent's voice settings",
        detail="The voice model or pronunciation dictionary chosen for this agent is not "
        "one the voice account can use.",
        remediation="Correct or clear it in the agent's voice settings (How it sounds), then "
        "publish again. If you cannot, contact us.",
    )


def other_surfaces(agent: dict[str, Any]) -> list[str]:
    """The places besides the phone a `GET /agents/{id}` answer says the agent answers, by
    our name for each; a value we have no name for is shown as the vendor wrote it."""
    voice = agent.get("voice")
    surfaces = voice.get("surfaces") if isinstance(voice, dict) else None
    if not isinstance(surfaces, list):
        return []
    return [
        SURFACE_NAMES.get(s, s)
        for s in sorted(str(s) for s in surfaces if isinstance(s, str))
        if s != "phone"
    ]


def _is_rupees(row: dict[str, Any]) -> bool:
    """A charge in rupees: `currency` is `INR`, or absent, which is the account's one
    currency, fixed at rupees once there is a customer unless dollars were chosen before
    (snapshots/2026-10-08/pages/api-reference/customers.md:219-223; we bill in rupees)."""
    currency = row.get("currency")
    return currency is None or currency == "INR"


def _charged_inr(row: dict[str, Any]) -> Decimal | None:
    """What a call cost the workspace in rupees, the ONE reading of a charge for the call
    object and the usage log alike: `costMicro` is integer millionths of `currency`
    (6370000 is 6.37), null until the call is settled (snapshots/2026-10-08/pages/
    api-reference/calls/get-call.md:498-523; usage/list-call-log.md). Divided as `Decimal`,
    never through a float. Not rupees, not an integer, or negative is not a charge here: a
    negative figure would breach the ledger's CHECK and a foreign one is not converted."""
    micro = row.get("costMicro")
    if not isinstance(micro, int) or isinstance(micro, bool) or micro < 0:
        return None
    if not _is_rupees(row):
        return None
    return Decimal(micro) / _MICRO_PER_UNIT


def _handover_destinations(tools: dict[str, Any]) -> tuple[tuple[str, ...], bool]:
    """The numbers this agent puts callers through to, from `GET /agents/{id}/tools`, and
    whether the answer could be read. A live transfer needs `escalate_to_human` on AND
    `handOver.mode` `call` with a phone; anything else transfers nobody
    (update-built-in-tools.md:705-790; channels/voice.md:483-492)."""
    rows = tools.get("tools")
    hand_over = tools.get("handOver")
    if not isinstance(rows, list) or not isinstance(hand_over, dict):
        return (), False
    escalates = any(
        isinstance(row, dict)
        and row.get("id") == "escalate_to_human"
        and row.get("enabled") is True
        for row in rows
    )
    phone = _e164(hand_over.get("phone"))
    if escalates and hand_over.get("mode") == "call" and phone is not None:
        return (phone,), True
    return (), True


def _own_voice_key_of(agent: dict[str, Any]) -> bool | None:
    """An Agent's `byok` read back as ours; None when absent or not a documented value."""
    value = agent.get("byok")
    scope = _BYOK_SCOPES.get(value) if isinstance(value, str) else None
    return None if scope is None else scope[0]


def _own_model_scope_of(agent: dict[str, Any]) -> bool | None:
    """Does the agent's `byok` put it on our language-model key? None when unreported."""
    value = agent.get("byok")
    scope = _BYOK_SCOPES.get(value) if isinstance(value, str) else None
    return None if scope is None else scope[1]


def _name_tag(cfg: AgentConfig) -> str:
    digest = hashlib.sha256(f"{cfg.tenant_id}:{cfg.agent_id}".encode()).hexdigest()[:12]
    return f"{_NAME_TAG_PREFIX}{digest}"


def vendor_agent_name(cfg: AgentConfig) -> str:
    """Our agent's name with the tag `create_agent` finds it by, inside the 60-character
    limit (agents.md:88-90). The visible part is shortened, never the tag."""
    tag = _name_tag(cfg)
    visible = cfg.name.strip()[: NAME_MAX_CHARS - len(tag)].rstrip()
    return f"{visible}{tag}"


def _our_name(vendor_name: str | None) -> str | None:
    return _NAME_TAG_RE.sub("", vendor_name) if vendor_name is not None else None


def _subtag(tag: str) -> str:
    return tag.split("-")[0].lower()


class ThinnestEngine:
    """Implements `VoiceEngine` against ThinnestAI's REST API. One httpx client per process."""

    name = "thinnest"
    capabilities = THINNEST_CAPABILITIES
    credential_env_keys: tuple[str, ...] = ("THINNEST_API_KEY",)

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        signing_secret_for: SigningSecretResolver | None = None,
        status_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client
        self._signing_secret_for = signing_secret_for
        #: The status read goes out without our key, so it never uses `client`.
        self._status_transport = status_transport

    def holds_credentials(self) -> bool:
        return bool(self._api_key) or self._client is not None

    # --- plumbing ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{self.name}")
            # No default `Content-Type`: `json=` sets it per request, and a client-wide one
            # would override the boundary of the one multipart upload (`create_voice_clone`).
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}"},
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        route: str,
        workspace: str | None,
        absent_is_success: bool = False,
        extra_refused_statuses: frozenset[int] = frozenset(),
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """`workspace` is required and has no default, so no call site can drop it by
        omission: every request states which workspace it acts in."""
        return await vendor_request(
            self._http(),
            method,
            path,
            engine=self.name,
            route=route,
            absent_is_success=absent_is_success,
            extra_refused_statuses=extra_refused_statuses,
            headers={**(headers or {}), **workspace_headers(method, route, workspace)},
            **kwargs,
        )

    @staticmethod
    def _at(handle: str) -> tuple[str, str | None]:
        """`(the vendor's id, the workspace it lives in)` for one of our handles."""
        return raw_of(handle), workspace_of(handle)

    async def _write_agent(
        self, method: str, path: str, route: str, workspace: str | None, body: dict[str, Any]
    ) -> dict[str, Any]:
        """`POST /agents` or `PATCH /agents/{id}`. A 409 `phone_number_required` (phone named
        as a place to answer while the vendor holds no number for the agent; nothing was
        saved, docs.thinnest.ai api-reference/errors, read 12 Oct 2026) is refused in words:
        our record says a number is attached and the platform's does not."""
        try:
            return await self._request(
                method,
                path,
                route=route,
                workspace=workspace,
                json=body,
            )
        except EngineRejectedError as exc:
            # `voice.surfaces: []` on an agent with no number is accepted (ThinnestAI's
            # email of 18 Oct 2026); only adding `phone` without a number is refused, with
            # the 409 below (snapshots/2026-10-18/pages/api-reference/agents/
            # update-agent.md:608-622).
            if exc.vendor_status != 409 or exc.vendor_code != PHONE_NUMBER_REQUIRED:
                raise
            log.warning("thinnest_agent_phone_number_missing", extra={"route": route})
            raise _business_refusal(
                "engine_agent_number_missing",
                title="The agent's phone number is not attached on the voice platform",
                detail=(
                    "The agent was not changed: it should answer its phone number, but the "
                    "voice platform has no number attached to it."
                ),
                remediation=(
                    "Attach the number to the agent again from its Numbers page, then publish. "
                    "If it keeps failing, contact us."
                ),
            ) from exc

    async def _walk(
        self,
        path: str,
        *,
        route: str,
        workspace: str | None,
        params: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], ListingIncompleteReason | None, int]:
        """Every row of a cursor-paged list, the reason it is short if it is, and the page
        count. A `nextCursor` of null is the vendor saying there is no further page."""
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor: str | None = None
        pages = 0
        while True:
            query: dict[str, Any] = {**(params or {}), "limit": _LISTING_PAGE_SIZE}
            if cursor is not None:
                query["cursor"] = cursor
            payload = await self._request(
                "GET", path, route=route, workspace=workspace, params=query
            )
            pages += 1
            rows.extend(_items(payload))
            following = _str(payload.get("nextCursor"))
            if following is None:
                return rows, None, pages
            if following in seen:
                return rows, "next_link_no_progress", pages
            if pages >= _LISTING_MAX_PAGES:
                return rows, "page_cap_reached", pages
            seen.add(following)
            cursor = following

    # --- agents --------------------------------------------------------------

    def _refuse_what_this_engine_cannot_carry(self, cfg: AgentConfig) -> None:
        """Refuse, rather than drop, any part of our config that would not reach a call."""
        require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
        require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
        require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)
        if cfg.handoff is not None:
            require_capability("in_call_handoff", engine=self)

    @staticmethod
    def _within(value: str, limit: int, *, code: str, what: str) -> str:
        if len(value) > limit:
            raise _business_refusal(
                code,
                title=f"The {what} is too long for this voice platform",
                detail=(
                    f"The {what} is {len(value)} characters and the voice platform accepts "
                    f"at most {limit}."
                ),
                remediation=f"Shorten the {what} and publish again.",
            )
        return value

    def _agent_body(self, cfg: AgentConfig) -> dict[str, Any]:
        self._refuse_what_this_engine_cannot_carry(cfg)
        instructions = self._within(
            compose_engine_prompt(cfg),
            INSTRUCTIONS_MAX_CHARS,
            code="engine_prompt_too_long",
            what="agent's script, with the platform rules added",
        )
        # The greeting field is the whole first utterance on this engine: the notices the
        # agent's switches turn on, then its own opening line (D-708). With both notices off
        # it is the opening line alone, never empty because a switch is off.
        greeting = self._within(
            compose_first_utterance(cfg),
            GREETING_MAX_CHARS,
            code="engine_greeting_too_long",
            what="opening line",
        )
        seconds = cfg.max_call_duration_s
        if not CALL_SECONDS_MIN <= seconds <= CALL_SECONDS_MAX:
            raise _business_refusal(
                "engine_call_cap_out_of_range",
                title="This call length is not available on this voice platform",
                detail=(
                    f"The agent's longest call is {seconds} seconds and the voice platform "
                    f"accepts {CALL_SECONDS_MIN} to {CALL_SECONDS_MAX}."
                ),
                remediation=(
                    f"Set the longest call to between {CALL_SECONDS_MIN // 60} and "
                    f"{CALL_SECONDS_MAX // 60} minutes, then publish again."
                ),
            )
        # snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:940-1016.
        # `answersCalls` true and `unavailableMessage` null on every publish: a publish is
        # what lifts a pause (`override_call_script`), so it must switch the line back on.
        # `detectMachines` is the client's answering-machine switch (founder decision 14,
        # default off) and `ringSeconds` is fixed at 30. `collectFields` empty: our own
        # extraction pass is the record. `summariseCalls` on (founder decision 12, 10 Oct
        # 2026): the vendor's summary is the call's summary of first resort
        # (`workers/pipeline` decides the precedence); "a small charge per call"
        # (create-agent.md:1024-1026), inside the `costMicro` we reconcile. Its language is
        # not settable (no field for it, mirror 2026-10-08 and docs.thinnest.ai read 10 Oct
        # 2026).
        # `pastConversations`: `recap` for an agent whose client switched caller memory on
        # (D-507's notice and gates are on OUR switch, `agents.publishing.set_caller_memory`),
        # `fresh` otherwise; never the vendor default `quiet`, which uses earlier
        # conversations without saying so (founder, 8 Oct 2026). Memory is the vendor's and
        # per agent; our own distillation does not run for this engine.
        voice: dict[str, Any] = {
            "answersCalls": True,
            "unavailableMessage": None,
            # Null follows the agent's `language`; `auto` here is a 400
            # (update-agent.md:1219-1227).
            "language": None,
            "recordCalls": True,
            "maxCallSeconds": seconds,
            "detectMachines": cfg.detect_machines,
            "ringSeconds": RING_SECONDS,
            "summariseCalls": True,
            "pastConversations": "recap" if cfg.caller_memory_enabled else "fresh",
            # Release the line when the agent ends the conversation: a boolean, and a new
            # agent starts with it OFF, so the line stays open, billed, until the caller
            # hangs up (docs.thinnest.ai api-reference/agents/update-agent and create-agent
            # `voice.endCallOnFinish`, read 11 Oct 2026). The client's setting, on unless
            # they switch it off (D-749, D-751). When to end is the prompt's rule.
            "endCallOnFinish": cfg.end_call_on_finish,
            # Seconds of quiet that end the caller's turn, a number 0.2 to 3 that reads back
            # null until set, "0.25 s on most lines" (same pages, read 11 Oct 2026). Always
            # stated, so a console reset to null reads as drift. Whole milliseconds on our
            # side (`agents/call_handling`), divided only here.
            "turnSilenceSeconds": cfg.turn_silence_ms / 1000,
            # The mode that makes that number "the silence that ends a turn": `timer`, the
            # platform's own choice today, stated so a change of their default cannot change
            # what the client's pause means (`null` follows the platform, and `smart` turns
            # the same number into a ceiling; snapshots/2026-10-13/pages/api-reference/agents/
            # update-agent.md:1349-1381, channels/voice.md:871-895).
            "turnDetection": TURN_DETECTION,
            # The platform's own do-not-call tool stays on beside our opt-out action (founder
            # decision, 13 Oct 2026): a missed opt-out costs more than a false one. Stated,
            # because it is a boolean defaulting to true (update-agent.md:1168-1175) and a
            # console switch-off would otherwise go unnoticed. Its additions reach our list
            # through `contact.opted_out`.
            "recordDoNotCall": True,
            # Phone only (founder decision F1, 12 Oct 2026): never the website call button or
            # WhatsApp, which a new agent answers on unless told otherwise. `phone` only once
            # a number is attached, because adding it to an agent that answers calls and has
            # no number is a 409 `phone_number_required`; while a number is attached the
            # vendor keeps `phone` on whatever we send (docs.thinnest.ai api-reference/
            # agents/update-agent `voice.surfaces`, read 12 Oct 2026).
            "surfaces": ["phone"] if cfg.has_phone_number else [],
            # The client's "are you still there?" settings (founder decisions F3, F9).
            "nudgeAfterSeconds": cfg.nudge_after_seconds,
            "nudges": cfg.nudge_count,
            "nudgePhrase": cfg.nudge_phrase or None,
            "endAfterSilenceSeconds": cfg.end_after_silence_seconds,
            # The client's filler lines; empty is the vendor's own, in the caller's language.
            "thinking": True,
            "thinkingLines": list(cfg.filler_lines),
            # The client's background office sound. Volume is a fraction with at most two
            # decimals, 0.05-1 (same page); we hold whole percent.
            "ambience": cfg.ambience,
            "ambienceVolume": round(cfg.ambience_volume_pct / 100, 2),
            **PLATFORM_VOICE_VALUES,
        }
        if cfg.engine_voice_id and cfg.engine_byok_voice_id:
            raise _business_refusal(
                "engine_voice_choice_conflict",
                title="This agent names two voices",
                detail="An agent speaks either a voice of the platform or a voice of our own "
                "voice provider, never both.",
                remediation="Choose one voice for the agent, then publish again.",
            )
        body: dict[str, Any] = {
            "name": vendor_agent_name(cfg),
            "instructions": instructions,
            "greeting": greeting,
            # One line about the business (update-agent.md:531-534, at most 200 characters),
            # from the script's [BUSINESS] section; empty for a script without one.
            "businessDescription": self._within(
                business_line_of(cfg.system_prompt),
                BUSINESS_DESCRIPTION_MAX_CHARS,
                code="engine_business_line_too_long",
                what="business line",
            ),
            # Every agent follows the caller (`_AUTO_LANGUAGE`); `language` alone also clears
            # any `languages` list an earlier publish sent (update-agent.md:754-768).
            "language": _AUTO_LANGUAGE,
            "voice": voice,
            # Stated, not left to the defaults: the vendor's own call-back would ring the
            # caller from their side, outside our dial gate and our DNC list, and its lead
            # capture would collect details our extraction already records. Our call-back is
            # an in-call action (`reliability/engine_actions.py`). The hand-over to a person
            # happens only when a destination is on duty (`cfg.handoff`, D-533), and then on
            # request only; the built-in tools that carry it are pinned separately
            # (`built_in_tools_body`).
            "scheduleCallbacks": False,
            "captureLeads": False,
            "escalation": {"onNoAnswer": False, "onRequest": cfg.handoff is not None},
            "collectFields": [],
            # The script's stages as the agent's own step list (`_steps_body`); `[]` when
            # the script has none to send, which removes any script held there
            # (update-agent.md:588-595), so the outline is only ever in one place.
            "steps": _steps_body(cfg),
            # The reply ceiling (D-769), an integer 100-800, default 300, for calls and chat
            # alike; a reply that reaches it is cut off there (thinnest-findings/mirror/
            # snapshots/2026-10-13/pages/api-reference/agents/update-agent.md:839-845,
            # create-agent.md:760-768). Always stated, so a console edit reads as drift.
            "maxReplyTokens": cfg.max_reply_tokens,
        }
        # Ids from `GET /voices` and `GET /models`, checked against the catalogue before
        # publish (`agents/engine_choice.py`). A voice of our own voice key goes to
        # `PUT /agents/{id}/byok-voice` after the write instead (`_apply_own_key_voice`).
        if cfg.engine_voice_id:
            voice["voice"] = cfg.engine_voice_id
        if cfg.engine_model_id:
            body["model"] = cfg.engine_model_id
        if cfg.engine_own_voice_key is None:
            # Never left to the vendor's default, `workspace` (bring-your-own-keys.md:304-306):
            # in a workspace whose voice-only switch is on, an agent that omitted it would
            # speak on our Cartesia key at the Clear price (:69-79, :128-133). Publish always
            # resolves it (`agents/service._engine_voice_fields`, and `engine_choice`
            # refuses the all-own-keys mode where it would not), so this is a config built
            # some other way.
            raise ProblemError(
                kind="internal",
                code="engine_agent_byok_unstated",
                title="This agent's voice settings are incomplete",
                detail=(
                    "The agent was not published because its settings did not say whose "
                    "voice key it speaks on. Nothing changed for its callers."
                ),
                remediation="Publish the agent again. If it keeps failing, contact us.",
            )
        body["byok"] = _byok_value(cfg.engine_own_voice_key, cfg.engine_own_model)
        # A choice that was cleared is sent as `null`, which puts the agent back on the
        # vendor's default (voice Kavya, model Prana [Voice]) (update-agent.md:536-545,
        # :951-961). Kavya bills at the Premium band; publish refuses an agent with no voice
        # chosen (`agents/engine_choice.VOICE_REQUIRED`), so a published agent never runs on
        # it, and the drift sweep repairs one found there. Not sent for a voice of our own key.
        if not cfg.engine_byok_voice_id:
            voice.setdefault("voice", None)
        body.setdefault("model", None)
        return body

    @staticmethod
    def built_in_tools_body(cfg: AgentConfig) -> dict[str, Any]:
        """`PATCH /agents/{id}/tools` for this agent: every switchable built-in tool stated.

        Off: `call_them_now` (it would dial outside our dial gate and DNC list), the three
        that message a customer on another channel, `capture_lead` and `schedule_callback`
        (ours are the extraction pass and the call-back action). `escalate_to_human` is on
        only when a hand-over destination is on duty (D-533), with `handOver` naming that
        phone and the line the agent says first; otherwise it is off and `handOver` is
        cleared, so a number entered in the vendor console cannot receive our callers
        (snapshots/2026-10-08/pages/api-reference/tools/update-built-in-tools.md:553-637).

        `handOver.agents`, passing a live call to another of the client's agents, is sent
        empty: the product offers no agent-to-agent hand-off. The empty list also clears one
        typed in the vendor console, and the read-back reports one it finds
        (`handOver.agents`). Any list goes through `handoff_agents_body`.
        """
        handoff = cfg.handoff
        agents = handoff_agents_body(cfg.engine_own_voice_key, ())
        return {
            "tools": {
                "call_them_now": False,
                "send_sms": False,
                "send_whatsapp": False,
                "reply_by_email": False,
                "capture_lead": False,
                "schedule_callback": False,
                "escalate_to_human": handoff is not None,
            },
            "handOver": (
                {
                    "mode": "call",
                    "phone": handoff.destination_e164,
                    "line": ThinnestEngine._within(
                        handoff.spoken_line.strip(),
                        HANDOVER_LINE_MAX_CHARS,
                        code="engine_handover_line_too_long",
                        what="hand-over line",
                    )
                    or None,
                    "agents": agents,
                }
                if handoff is not None
                else {"mode": "chat", "phone": None, "line": None, "agents": agents}
            ),
        }

    async def _apply_built_in_tools(
        self, raw: str, workspace: str | None, cfg: AgentConfig
    ) -> None:
        """Pin the built-in tools, then read what was saved. The vendor applies a change in
        order and stops at the first refusal, keeping what came before, so a refusal or a
        saved state that differs from what was sent is a partial apply: the publish is
        refused rather than left live with a tool we did not choose."""
        wanted = self.built_in_tools_body(cfg)
        try:
            saved = await self._request(
                "PATCH",
                f"/agents/{raw}/tools",
                route="/agents/{ref}/tools",
                workspace=workspace,
                json=wanted,
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 400:
                raise
            raise _tools_not_pinned() from exc
        drifted = _tools_drift(wanted, saved)
        if drifted:
            log.warning("thinnest_tools_not_pinned", extra={"fields": ",".join(drifted)})
            raise _tools_not_pinned()

    async def _find_agent(self, cfg: AgentConfig, workspace: str | None) -> str | None:
        """The vendor id of an agent this adapter already made for `cfg` in `workspace`,
        found by its name tag."""
        tag = _name_tag(cfg)
        rows, reason, _ = await self._walk("/agents", route="/agents", workspace=workspace)
        for row in rows:
            name = _str(row.get("name"))
            if name is not None and name.endswith(tag):
                return _str(row.get("id"))
        if reason is not None:
            # Creating now could make a second agent for one of ours; refusing costs a retry.
            log.warning("thinnest_agent_listing_incomplete", extra={"reason": reason})
            raise ProblemError(
                kind="dependency",
                code="engine_listing_incomplete",
                title="The voice platform's agent list could not be read in full",
                detail="We could not confirm whether this agent already exists on the platform.",
                remediation="Try publishing again. If it keeps failing, contact us.",
            )
        return None

    # --- the shared trial number's line ------------------------------------------------

    async def read_trial_line_agent(self) -> TrialLineAgent | None:
        """The developer workspace's agent named `TRIAL_LINE_AGENT_NAME`, or None."""
        rows, reason, _ = await self._walk("/agents", route="/agents", workspace=None)
        for row in rows:
            if _str(row.get("name")) == TRIAL_LINE_AGENT_NAME:
                voice = row.get("voice")
                held = voice if isinstance(voice, dict) else {}
                return TrialLineAgent(
                    ref=_str(row.get("id")) or "",
                    answers_calls=held.get("answersCalls") is True,
                    message=_str(held.get("unavailableMessage")),
                    message_note=_str(held.get("unavailableMessageNote")),
                )
        if reason is not None:
            raise ProblemError(
                kind="dependency",
                code="engine_listing_incomplete",
                title="The voice platform's agent list could not be read in full",
                detail="We could not confirm whether the trial line's agent already exists.",
                remediation="Try again in a few minutes.",
            )
        return None

    async def converge_trial_line_agent(self, message: str) -> TrialLineAgent:
        """Make the developer workspace hold one agent that never answers and speaks
        `message` to whoever rings the shared trial number (D-742). Found by its fixed name,
        so a repeat finds it rather than making a second; repaired when found answering or
        saying something else.

        `voice.answersCalls: false` with `voice.unavailableMessage` (≤300 characters, a
        longer one is a 400, never cut) is read by the phone provider's own Indian-English
        voice on Plivo and Twilio numbers (docs.thinnest.ai api-reference/agents/create-agent
        `AgentVoiceInput`, channels/voice "When Answer calls is off", read 11 Oct 2026).
        Sending any voice field on create makes a voice channel switched OFF. `byok: off`:
        it is no Studio agent, and the developer workspace runs our voice key (D-727).
        """
        wanted_voice = {"answersCalls": False, "unavailableMessage": message}
        held = await self.read_trial_line_agent()
        if held is None:
            with trial_agent_in_developer_workspace():
                row = await self._request(
                    "POST",
                    "/agents",
                    route="/agents",
                    workspace=None,
                    json={"name": TRIAL_LINE_AGENT_NAME, "byok": "off", "voice": wanted_voice},
                )
            ref = _str(row.get("id"))
            if ref is None:
                raise _bad_response("a created agent without its id")
            log.info("thinnest_trial_line_agent_created")
        elif held.answers_calls or held.message != message:
            ref = held.ref
            await self._request(
                "PATCH",
                f"/agents/{ref}",
                route="/agents/{ref}",
                workspace=None,
                json={"voice": wanted_voice},
            )
            log.info("thinnest_trial_line_agent_repaired")
        else:
            return held
        after = await self.read_trial_line_agent()
        if after is None or after.answers_calls or after.message != message:
            raise ProblemError(
                kind="dependency",
                code="trial_line_agent_not_held",
                title="The trial line's agent did not take its settings",
                detail="The voice platform did not keep the trial number's message.",
                remediation="Try again; if it repeats, check the agent in the platform console.",
            )
        return after

    async def set_line_answering(self, ref: str, *, on: bool) -> None:
        """Switch a developer-workspace agent's Answer calls on or off, nothing else."""
        await self._request(
            "PATCH",
            f"/agents/{ref}",
            route="/agents/{ref}",
            workspace=None,
            json={"voice": {"answersCalls": on}},
        )

    async def call_out_on_phone(self, ref: str) -> None:
        """Give an agent that has just been lent a number the `phone` surface, so the
        platform counts it as an agent that "answers the phone" and lets it place a call.

        `POST /calls` refuses with 409 `calling_not_set_up` ("No agent in this workspace
        answers the phone") or 404 `agent_not_found` when the agent it names does not
        (calls/place-call, docs.thinnest.ai read 15 Oct 2026). An agent with no number of its
        own is published with `surfaces: []` (F1), and the platform accepts `phone` only once
        it has "a number to answer or call from" (agents/update-agent `voice.surfaces`, same
        day), so this runs after the lend. It answers nothing inbound: the number's line is
        another agent, and the lent agent "calls out on it without answering it"
        (phone-numbers/update-phone-number `callingAgent`)."""
        raw, workspace = self._at(ref)
        row = await self._request(
            "PATCH",
            f"/agents/{raw}",
            route="/agents/{ref}",
            workspace=workspace,
            json={"voice": {"surfaces": ["phone"]}},
        )
        voice = row.get("voice")
        surfaces = voice.get("surfaces") if isinstance(voice, dict) else None
        if not isinstance(surfaces, list) or "phone" not in surfaces:
            raise ProblemError(
                kind="dependency",
                code="engine_agent_phone_not_held",
                title="The agent could not be set to place phone calls",
                detail="The voice platform did not keep the phone line on the calling agent.",
                remediation="Try again; if it repeats, check the agent in the platform console.",
            )
        # Place Call also needs the borrower's Answer calls ON (ThinnestAI's email of
        # 18 Oct 2026; `voice.answersCalls`, snapshots/2026-10-18/pages/api-reference/agents/
        # update-agent.md:1206-1208). A
        # publish always sends it on, so off is our own pause (`override_call_script`) or a
        # console edit; it is reported rather than switched on, which would lift that pause.
        if not isinstance(voice, dict) or voice.get("answersCalls") is not True:
            raise ProblemError(
                kind="dependency",
                code="engine_agent_not_answering",
                title="The agent is not taking calls on the voice platform",
                detail="The calling agent's line is switched off, so it cannot place a call.",
                remediation="Publish the agent again; if it repeats, check it in the platform "
                "console.",
            )

    # --- the forwarding verification call (D-746) --------------------------------------

    async def converge_forwarding_test_agent(self, leg: int) -> str:
        """The developer-workspace agent that places test leg `leg` (1 or 2), made once and
        found by its fixed name. Voice is switched on so it may call out; it is never a
        number's answering agent, so it answers nothing. `byok: off` for the trial line's
        reason. Whether an agent with no instructions of its own places a call carrying only
        `purpose` and `overrides.callInstructions` is UNVERIFIED (OPERATIONS gate F-5)."""
        name = FORWARDING_TEST_AGENT_NAMES[leg - 1]
        rows, reason, _ = await self._walk("/agents", route="/agents", workspace=None)
        for row in rows:
            if _str(row.get("name")) == name:
                ref = _str(row.get("id"))
                if ref is not None:
                    return ref
        if reason is not None:
            raise ProblemError(
                kind="dependency",
                code="engine_listing_incomplete",
                title="The voice platform's agent list could not be read in full",
                detail="We could not confirm whether the test-call agent already exists.",
                remediation="Try again in a few minutes.",
            )
        with trial_agent_in_developer_workspace():
            row = await self._request(
                "POST",
                "/agents",
                route="/agents",
                workspace=None,
                json={"name": name, "byok": "off", "voice": {"answersCalls": True}},
            )
        ref = _str(row.get("id"))
        if ref is None:
            raise _bad_response("a created agent without its id")
        await self.set_line_answering(ref, on=True)
        log.info("thinnest_forwarding_test_agent_created", extra={"leg": leg})
        return ref

    async def place_forwarding_test_call(
        self, *, agent_ref: str, from_e164: str, to_e164: str, reference: str
    ) -> str:
        """`POST /calls` from a platform number to a client's published number, in the
        developer workspace. `purpose` is what a person hears first; the shortest per-call
        limit (60 s) bounds a leg we fail to hang up. `ifOutsideHours: refuse`, so a request
        outside 09:00-21:00 is a 409 rather than a call queued for later. The idempotency key
        is the leg's own id, so a retried request places no second call."""
        body: dict[str, Any] = {
            "to": to_e164,
            "purpose": TEST_CALL_PURPOSE,
            "agent": agent_ref,
            "from": from_e164,
            "ifOutsideHours": "refuse",
            "overrides": {
                "maxCallSeconds": TEST_CALL_MAX_SECONDS,
                "callInstructions": TEST_CALL_INSTRUCTIONS,
            },
            "metadata": {"calevate_forwarding_leg": reference},
            "reference": reference,
        }
        try:
            data = await self._request(
                "POST",
                "/calls",
                route="/calls",
                workspace=None,
                json=body,
                headers={IDEMPOTENCY_HEADER: f"calevate-fwd-{reference}"},
                extra_refused_statuses=frozenset({402, 409}),
            )
        except EngineRejectedError as exc:
            refusal = _dial_refusal(exc)
            if refusal is exc:
                raise
            raise refusal from exc
        handle = _str(data.get("id"))
        if handle is None:
            raise _bad_response("The voice platform did not return a call id.")
        return handle

    async def read_forwarding_leg(self, handle: str) -> ForwardingLegReport:
        snapshot = await self.get_execution(handle)
        seconds = snapshot.duration_s
        return ForwardingLegReport(
            ended=snapshot.terminal,
            answered=None if seconds is None else seconds > 0,
            seconds=seconds,
        )

    async def hang_up_forwarding_leg(self, handle: str) -> None:
        """`DELETE /calls/{id}` whatever its state: a ringing or connected call "is ended on
        the line" (cancel-call.md:7, 384-385). Unlike `end_call` a connected leg IS ended:
        nobody is talking on a test leg. A 409 is a call already over."""
        raw_call, workspace = self._at(handle)
        try:
            await self._request(
                "DELETE", f"/calls/{raw_call}", route="/calls/{id}", workspace=workspace
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 409:
                raise

    async def _apply_own_key_voice(self, raw: str, workspace: str | None, cfg: AgentConfig) -> None:
        """`PUT /agents/{id}/byok-voice` for an agent speaking a voice of our own voice key,
        with how it sounds (`cfg.engine_byok_voice_tuning`), then the answer read back.

        The route is a partial PUT: a field left out keeps what is saved, `null` resets it
        (snapshots/2026-10-13/pages/api-reference/bring-your-own-keys.md:388-395). So the
        first request names the voice and every setting we hold, and a second resets only
        what the answer still holds that we cleared; nulls are never sent for settings the
        platform does not hold, which keeps an untuned agent's write what it always was. A
        setting read back different from what was sent refuses the publish rather than leave
        a voice live that sounds unlike what was chosen. A `409` is the workspace not on its
        own keys, or the agent with no voice channel."""
        if not cfg.engine_byok_voice_id:
            return
        wanted = _tuning_wanted(cfg.engine_byok_voice_tuning)
        saved = await self._put_own_key_voice(
            raw,
            workspace,
            {
                "voice": cfg.engine_byok_voice_id,
                **{k: v for k, v in wanted.items() if v is not None},
            },
        )
        held_reads = {wire: read for _o, wire, read in _TUNING_WIRE}
        stale = {
            wire: None
            for wire, value in wanted.items()
            if value is None and saved.get(held_reads[wire]) is not None
        }
        if stale:
            saved = await self._put_own_key_voice(raw, workspace, stale)
        if _tuning_mismatches(wanted, saved):
            log.warning("thinnest_voice_tuning_not_saved")
            raise _business_refusal(
                "engine_voice_tuning_not_saved",
                title="The voice platform did not save this agent's voice settings",
                detail="The voice settings read back from the voice platform differ from the "
                "ones sent.",
                remediation="Publish again. If it keeps happening, contact us.",
            )

    async def _put_own_key_voice(
        self, raw: str, workspace: str | None, body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return await self._request(
                "PUT",
                f"/agents/{raw}/byok-voice",
                route="/agents/{ref}/byok-voice",
                workspace=workspace,
                json=body,
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status not in (400, 409):
                raise
            tuning = _tuning_refusal(exc)
            if tuning is not None:
                raise tuning from exc
            raise _business_refusal(
                "engine_byok_voice_unavailable",
                title="This voice cannot be set on the voice platform",
                detail=(
                    "The voice platform would not put this agent on the chosen voice: the "
                    "voice is not offered by the voice provider, or the workspace is not "
                    "running on our own voice key."
                ),
                remediation="Choose another voice. If it keeps failing, contact us.",
            ) from exc

    async def _apply_own_model(self, raw: str, workspace: str | None, cfg: AgentConfig) -> None:
        """`PUT /agents/{id}/byok-model` for an agent answering on our model key (D-764): the
        model must be one the key reaches, and the agent then runs it rather than the key's
        own (`thinnest-findings/mirror/snapshots/2026-10-18/pages/api-reference/agents/
        set-agent-byok-model.md:443-525`). Always sent, so the agent never silently follows
        the workspace key's model.

        `409` means the WORKSPACE's default scope brings no language-model key, `voice` or
        none (snapshots/2026-10-18, same page :514-518). Our developer workspace is on `voice`
        (D-727), so every free-trial agent on our model meets it, Clear and Studio alike
        (D-834). The agent's own scope still runs on our key (bring-your-own-keys.md:82-90),
        on the key's own model, so the `409` is accepted when that model, read from
        `GET /byok` in the same workspace, is the one wanted; otherwise the publish is
        refused, because the minute would be metered at a model the agent does not run."""
        if not cfg.engine_own_model:
            return
        await self._put_own_model(
            raw, workspace, cfg.engine_own_model, own_voice=bool(cfg.engine_own_voice_key)
        )

    async def _put_own_model(
        self, raw: str, workspace: str | None, model: str, *, own_voice: bool
    ) -> None:
        """The `PUT /agents/{id}/byok-model` of `_apply_own_model`, also used by the drift
        repair (`set_agent_own_keys`), so both read a `409` the same way. `own_voice` is
        kept for the callers' signature; the `409` reading does not depend on it."""
        try:
            await self._request(
                "PUT",
                f"/agents/{raw}/byok-model",
                route="/agents/{ref}/byok-model",
                workspace=workspace,
                json={"model": model},
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status not in (400, 409):
                raise
            if exc.vendor_status == 409 and await self._key_model(workspace) == model:
                log.info("thinnest_own_model_runs_key_model")
                return
            raise _business_refusal(
                "engine_own_model_unavailable",
                title="This language model cannot be set on the voice platform",
                detail=(
                    "The voice platform would not put this agent on the chosen language "
                    "model: our model key does not reach it, or the workspace is not "
                    "running on our model key."
                ),
                remediation="Choose another model. If it keeps failing, contact us.",
            ) from exc

    async def _held_own_model(
        self, raw: str, workspace: str | None, agent: dict[str, Any]
    ) -> tuple[str | None, bool]:
        """The model of our key the agent runs, and whether that was read. `GET
        /agents/{id}/byok-model` answers `model` (null: the key's own); an agent whose `byok`
        uses no model key has none (set-agent-byok-model.md:399-418, bring-your-own-keys.md:
        328-330)."""
        on_own_model = _own_model_scope_of(agent)
        if on_own_model is None:
            return None, False
        if not on_own_model:
            return None, True
        try:
            data = await self._request(
                "GET",
                f"/agents/{raw}/byok-model",
                route="/agents/{ref}/byok-model",
                workspace=workspace,
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 409:
                raise
            # In a workspace whose default brings no model key (our developer workspace,
            # `voice`), an agent on our key runs the key's own model and has no choice of its
            # own to read (`_apply_own_model`).
            return await self._key_model(workspace) or "", True
        return _str(data.get("model")) or "", True

    async def _key_model(self, workspace: str | None) -> str | None:
        """The model our language-model key runs by default in `workspace` (`GET /byok`,
        `credentials[kind=llm].model`), or None when no such key is listed."""
        data = await self._request("GET", "/byok", route="/byok", workspace=workspace)
        return _key_state(data).llm_model

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        """A new agent in the client's OWN workspace (`cfg.engine_workspace`, D-693). Never
        in the developer workspace: without a customer workspace this refuses before any
        request, and the handle returned carries the workspace."""
        workspace = cfg.engine_workspace
        # A free-trial account's agent is the one exception (D-697): it is made in the
        # developer workspace, beside the shared trial number it calls from.
        if workspace is None and not trial_agent_allowed():
            raise workspace_not_provisioned()
        body = self._agent_body(cfg)
        # Built (and so checked) before any write, so a refusal leaves nothing behind.
        self.built_in_tools_body(cfg)
        raw = await self._find_agent(cfg, workspace)
        if raw is not None:
            data = await self._write_agent(
                "PATCH", f"/agents/{raw}", "/agents/{ref}", workspace, body
            )
        else:
            data = await self._write_agent("POST", "/agents", "/agents", workspace, body)
            raw = _str(data.get("id"))
            if raw is None:
                raise _bad_response("The voice platform did not return an agent id.")
        _refuse_unsaved_steps(body, data)
        _refuse_unsaved_reply_length(body, data)
        await self._apply_own_key_voice(raw, workspace, cfg)
        await self._apply_own_model(raw, workspace, cfg)
        await self._apply_built_in_tools(raw, workspace, cfg)
        return scoped_handle(raw, workspace)

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        raw, workspace = self._at(ref)
        body = self._agent_body(cfg)
        self.built_in_tools_body(cfg)
        saved = await self._write_agent("PATCH", f"/agents/{raw}", "/agents/{ref}", workspace, body)
        _refuse_unsaved_steps(body, saved)
        _refuse_unsaved_reply_length(body, saved)
        await self._apply_own_key_voice(raw, workspace, cfg)
        await self._apply_own_model(raw, workspace, cfg)
        await self._apply_built_in_tools(raw, workspace, cfg)

    async def override_call_script(
        self, ref: EngineAgentRef, *, opening_line: str, system_prompt: str
    ) -> None:
        """PAUSE the agent's line rather than rewrite what it says: `answersCalls: false`
        with `voice.unavailableMessage` (snapshots/2026-10-08/pages/api-reference/agents/
        update-agent.md:940-1016; channels/voice.md:696-725). The agent's greeting and
        instructions are untouched, and the restoring publish switches the line back on.

        Rewriting the script instead answered every call with a 60-second AI conversation
        that ThinnestAI billed and nobody paid for. A paused line is not answered: the phone
        provider's own voice reads one sentence and the call ends, so no AI speaks and
        nothing is recorded. That is why the message is NOT `opening_line`: the opening
        carries the AI disclosure and the recording notice, and on a call no agent answers
        and nothing records, "this call is recorded" would be false. The message is the
        reasonless sentence the empty-wallet path already speaks (`PAUSED_LINE_MESSAGE`),
        which is true in both a maintenance window and an empty wallet and gives a caller no
        reason that would harm our client. It is read on Plivo and Twilio numbers, in
        English; other carriers decline or give a busy tone, and the vendor plays its own
        standard sentence where it cannot read ours.

        The greeting and instructions are still replaced with the ones we were handed, as the
        Protocol requires: nothing speaks them while the line is off, and they keep the agent
        holding the maintenance words rather than its ordinary ones should any surface reach
        it before the restoring publish.
        """
        body: dict[str, Any] = {
            "greeting": self._within(
                opening_line.strip(),
                GREETING_MAX_CHARS,
                code="engine_greeting_too_long",
                what="maintenance opening line",
            ),
            "instructions": self._within(
                system_prompt,
                INSTRUCTIONS_MAX_CHARS,
                code="engine_prompt_too_long",
                what="maintenance script",
            ),
            "voice": {"answersCalls": False, "unavailableMessage": PAUSED_LINE_MESSAGE},
        }
        raw, workspace = self._at(ref)
        await self._request(
            "PATCH", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace, json=body
        )

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """`GET /agents/{id}` (agents.md:80), with the agent's documents from its knowledge
        list: documents are agent-scoped here, so that list IS what the agent references."""
        raw, workspace = self._at(ref)
        data = await self._request(
            "GET", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace
        )
        returned = _str(data.get("id"))
        if returned is not None and returned != raw:
            raise _bad_response("The voice platform described a different agent.")
        instructions = data.get("instructions")
        greeting = data.get("greeting")
        # A present-but-null greeting is an agent with none; an absent key is unread.
        greeting_readable = "greeting" in data and (greeting is None or isinstance(greeting, str))
        destinations, destinations_readable = _handover_destinations(
            await self._request(
                "GET", f"/agents/{raw}/tools", route="/agents/{ref}/tools", workspace=workspace
            )
        )
        own_model, own_model_readable = await self._held_own_model(raw, workspace, data)
        return AgentSnapshot(
            engine_agent_ref=ref,
            name=_our_name(_str(data.get("name"))),
            system_prompt=instructions if isinstance(instructions, str) else None,
            system_prompt_readable=isinstance(instructions, str),
            greeting=greeting if isinstance(greeting, str) else "",
            greeting_readable=greeting_readable,
            knowledge_base_refs=await self.list_kb(ref),
            knowledge_base_refs_readable=True,
            engine_own_voice_key=_own_voice_key_of(data),
            engine_own_model=own_model,
            engine_own_model_readable=own_model_readable,
            handoff_destinations=destinations,
            handoff_destinations_readable=destinations_readable,
            engine=self.name,
        )

    async def settings_drift(self, ref: EngineAgentRef, cfg: AgentConfig) -> list[str]:
        """The call settings `GET /agents/{id}` and `GET /agents/{id}/tools` hold that differ
        from what a publish of `cfg` sends (`apps/api/agents/engine_settings.py`), and for a
        Studio voice the settings `GET /agents/{id}/byok-voice` holds.

        Not compared: the script and greeting (`verify_publish` scores them), `byok` (the
        sweep's own-voice-key leg repairs it), and `answersCalls` / `unavailableMessage`,
        which a pause sets on purpose. A voice or model we leave on the vendor's default is
        not compared either: the default comes back as its own id, which we do not hold."""
        raw, workspace = self._at(ref)
        agent = await self._request(
            "GET", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace
        )
        tools = await self._request(
            "GET", f"/agents/{raw}/tools", route="/agents/{ref}/tools", workspace=workspace
        )
        drifted = _settings_drift(self._agent_body(cfg), agent)
        tool_drift = _tools_drift(self.built_in_tools_body(cfg), tools)
        if any(name.startswith("tools.") for name in tool_drift):
            drifted.append("built_in_tools")
        if any(name.startswith("handOver.") for name in tool_drift):
            drifted.append("hand_over")
        if cfg.engine_byok_voice_id:
            # A Studio voice's settings live on their own route (`GET` returns each, null
            # while unset; bring-your-own-keys.md:390-392).
            held = await self._request(
                "GET",
                f"/agents/{raw}/byok-voice",
                route="/agents/{ref}/byok-voice",
                workspace=workspace,
            )
            if _tuning_mismatches(_tuning_wanted(cfg.engine_byok_voice_tuning), held):
                drifted.append("voice_tuning")
        return drifted

    async def answer_surfaces(self, ref: EngineAgentRef) -> list[str]:
        """Where else besides the phone the agent answers (`other_surfaces`), for the drift
        panel. Any such place is drift: the settings sweep compares and repairs `surfaces`."""
        raw, workspace = self._at(ref)
        agent = await self._request(
            "GET", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace
        )
        return other_surfaces(agent)

    async def repair_settings(
        self, ref: EngineAgentRef, cfg: AgentConfig, drifted: Sequence[str]
    ) -> None:
        """`PATCH /agents/{id}` with only the drifted settings, and the built-in tools again
        when they or the hand-over drifted. The script, greeting and line state are not
        sent, so a repair cannot lift a pause or overwrite an emergency console edit of the
        script, which is a human's decision (`agents/publishing.engine_drift_for`)."""
        raw, workspace = self._at(ref)
        wanted = self._agent_body(cfg)
        body: dict[str, Any] = {}
        voice: dict[str, Any] = {}
        for label in drifted:
            for key in _SETTING_KEYS.get(label, ()):
                if key.startswith("voice."):
                    field_name = key.removeprefix("voice.")
                    if field_name in wanted["voice"]:
                        voice[field_name] = wanted["voice"][field_name]
                elif key in wanted:
                    body[key] = wanted[key]
        if voice:
            body["voice"] = voice
        if body:
            await self._write_agent("PATCH", f"/agents/{raw}", "/agents/{ref}", workspace, body)
        if {"built_in_tools", "hand_over"} & set(drifted):
            await self._apply_built_in_tools(raw, workspace, cfg)
        if "voice_tuning" in drifted:
            await self._apply_own_key_voice(raw, workspace, cfg)

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """`DELETE /agents/{id}`, 204; it takes the agent's knowledge with it (agents.md:82)."""
        raw, workspace = self._at(ref)
        await self._request(
            "DELETE",
            f"/agents/{raw}",
            route="/agents/{ref}",
            workspace=workspace,
            absent_is_success=True,
        )

    async def test_chat(
        self, ref: EngineAgentRef, message: str, *, session: str | None = None
    ) -> TestChatTurn:
        """`POST /agents/{id}/test-chat` (snapshots/2026-10-08/pages/api-reference/agents/
        test-chat.md:328-460): the real agent through its website chat, in a sandbox where
        anything that would contact a person is switched off, billed like the console's
        Playground (the rate is not published). Our own actions still run; with no call
        behind them they write nothing, and the opt-out answers as on a real call while a
        test is open for the agent (`agents/test_window`). `409` is an agent whose website
        chat is off or absent, which we report as not testable rather than as an error."""
        raw, workspace = self._at(ref)
        body: dict[str, Any] = {"message": message[:4000]}
        if session:
            body["session"] = session
        try:
            data = await self._request(
                "POST",
                f"/agents/{raw}/test-chat",
                route="/agents/{ref}/test-chat",
                workspace=workspace,
                json=body,
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 409:
                raise
            raise _business_refusal(
                TEST_CHAT_UNAVAILABLE,
                title="This agent cannot be tested here",
                detail="The voice platform has no chat channel switched on for this agent.",
                remediation="Contact us to switch on test conversations for this agent.",
            ) from exc
        tools_raw = data.get("tools")
        results = tuple(
            _test_chat_tool(item, name)
            for item in (tools_raw if isinstance(tools_raw, list) else [])
            if isinstance(item, dict) and (name := _str(item.get("name")))
        )
        return TestChatTurn(
            session=_str(data.get("session")) or "",
            reply=_str(data.get("reply")) or "",
            tools=tuple(tool.name for tool in results),
            failed_part_way=data.get("error") is not None,
            tool_results=results,
        )

    # --- calls ---------------------------------------------------------------

    async def _outbound_opening(self, ref: EngineAgentRef, variables: dict[str, str]) -> str:
        """The agent's greeting as the engine holds it, with this call's variables filled in.

        `purpose` is required and spoken first on an outbound call (place-call.md:66-72), so
        it carries the same first words the agent greets inbound callers with: the notices
        switched on, then the opening line (D-669, D-708). Read per dial: a cached copy would
        speak a superseded disclosure after a republish. The `{{name}}` fields of the opening
        line are filled here from the dial's own variables, unfilled ones dropped, because
        the vendor documents its substitution for the agent's greeting and instructions
        (`snapshots/2026-10-08/pages/channels/voice-campaigns.md:165-209`), not for
        `purpose`. Any failure here is before `POST /calls`, so it is reported as not placed.
        """
        try:
            raw, workspace = self._at(ref)
            data = await self._request(
                "GET", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace
            )
        except ProblemError as exc:
            raise _dial_precondition_failed(missing="published agent") from exc
        greeting = _str(data.get("greeting"))
        values: dict[str, str | None] = {**variables}
        spoken = _tidy_spoken(substitute_variables(greeting or "", values))
        if not spoken:
            raise _dial_precondition_failed(missing="agent's opening line")
        return self._within(
            spoken, PURPOSE_MAX_CHARS, code="engine_greeting_too_long", what="opening"
        )

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """`POST /calls` (place-call.md).

        Not sent, deliberately: `retry` (our campaign ladder owns retries), `callingHours`
        (our compliance gate owns the window; their 09:00-21:00 check runs regardless,
        place-call.md:103-113), `extract` (our own extraction is the record), `summary` (left
        out so the call follows the agent's own `summariseCalls`, place-call.md:942-946).
        `ifOutsideHours: refuse` makes an out-of-hours request a 409 rather than a call
        queued for tomorrow behind our back (place-call.md:115-121).
        """
        # The truthful-answer rule is agent-record state on this engine, verified at publish.
        require_call_compliance_floor(engine=self, prompt_on_the_wire=None)
        variables: dict[str, str] = dict(ctx.fields)
        if ctx.lead_name:
            variables["lead_name"] = ctx.lead_name
        if len(variables) > CALL_VARIABLES_MAX:
            raise _dial_precondition_failed(missing=f"room for {len(variables)} call variables")
        raw_agent, workspace = self._at(ref)
        purpose = await self._outbound_opening(ref, variables)
        body: dict[str, Any] = {
            "to": to,
            "purpose": purpose,
            "agent": raw_agent,
            "ifOutsideHours": "refuse",
        }
        if ctx.from_e164:
            body["from"] = ctx.from_e164
        if ctx.lead_name:
            # "The lead's name": a number that is not yet a contact in the agent's workspace
            # becomes one with it, and an existing contact's name is never overwritten
            # (snapshots/2026-10-08/pages/api-reference/calls/place-call.md:895-899).
            body["name"] = ctx.lead_name.strip()[:LEAD_NAME_MAX]
        if ctx.max_call_seconds is not None:
            # "Changes to the agent for this call only", 60..1200 seconds
            # (snapshots/2026-10-08/pages/api-reference/calls/place-call.md:1103-1126).
            body["overrides"] = {"maxCallSeconds": ctx.max_call_seconds}
        if variables:
            body["variables"] = variables
        metadata = {
            key: value
            for key, value in (("calevate_call_id", ctx.call_id), ("calevate_lead_id", ctx.lead_id))
            if value
        }
        if metadata:
            body["metadata"] = metadata
        headers: dict[str, str] = {}
        if ctx.call_id:
            body["reference"] = ctx.call_id
            # A repeat of the key places no second call (place-call.md:299-310), which is
            # what makes the ladder's 429 retry safe on this route.
            headers[IDEMPOTENCY_HEADER] = f"calevate-call-{ctx.call_id}"
        try:
            data = await self._request(
                "POST",
                "/calls",
                route="/calls",
                workspace=workspace,
                json=body,
                headers=headers,
                # A 409 on this route is a call that was not placed: outside hours, a call
                # already waiting or live for this person, no answering agent, a number
                # without carrier credentials (place-call.md:272-286). The one exception,
                # the same key still in flight, is made unconfirmed by `_dial_refusal`.
                # 402 is "your balance cannot pay for a call", nothing created
                # (snapshots/2026-10-07/pages/api-reference/calls/place-call.md:379-389).
                extra_refused_statuses=frozenset({402, 409}),
            )
        except EngineRejectedError as exc:
            refusal = _dial_refusal(exc)
            if refusal is exc:
                raise
            raise refusal from exc
        handle = _str(data.get("id"))
        if handle is None:
            raise _bad_response("The voice platform did not return a call id.")
        if data.get("status") == "scheduled":
            log.warning("thinnest_call_scheduled_not_placed", extra={"engine_call_id": handle})
        return scoped_handle(handle, workspace)

    async def end_call(self, call_id: str) -> RecallOutcome:
        """`DELETE /calls/{id}`: 200 with `status: cancelled` for a call still waiting, 202 for
        one ringing or live, 409 for one already ended or on a number we cannot end
        (get-call.md:89-108). The 409 body is not exposed by the shared ladder, so the call
        is read back to tell the two 409s apart.

        A CONNECTED call is left alone. Its callers (the big red switch, a DNC recall) pull
        back dials that have not been answered, and on the carrier path they reach only
        `queued`/`ringing` rows. Here our row stays `queued` until the call ends (nothing
        is sent while it talks), so the vendor's own status is read first; without it a
        recall would end a live conversation mid-sentence
        (snapshots/2026-10-07/pages/api-reference/calls/cancel-call.md:7)."""
        try:
            current = await self.get_execution(call_id)
        except ProblemError:
            current = None
        if current is not None and current.raw_status == "connected":
            return RecallOutcome.ALREADY_RUNNING
        try:
            raw_call, workspace = self._at(call_id)
            report = await self._request(
                "DELETE", f"/calls/{raw_call}", route="/calls/{id}", workspace=workspace
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 409:
                raise
            snapshot = await self.get_execution(call_id)
            if not snapshot.terminal:
                raise
            return (
                RecallOutcome.PREVENTED
                if snapshot.raw_status == "cancelled"
                else RecallOutcome.ALREADY_RUNNING
            )
        status = _str(report.get("status"))
        if status == "cancelled":
            return RecallOutcome.PREVENTED
        if status in _LIVE_RAW:
            return RecallOutcome.ALREADY_RUNNING
        return RecallOutcome.UNKNOWN

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        raise engine_lacks("transfer", engine=self.name)

    # --- numbers -------------------------------------------------------------
    # Renting, attaching and releasing a number go through `engine/thinnest_numbers.py` and
    # `campaigns/engine_numbers.py`, per workspace (D-693); the Protocol writes refuse here.

    async def search_numbers(self, query: NumberSearch) -> Sequence[AvailableNumber]:
        raise engine_lacks("numbers", engine=self.name)

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        raise engine_lacks("numbers", engine=self.name)

    async def release_number(self, number: ProvisionedNumber) -> None:
        raise engine_lacks("numbers", engine=self.name)

    async def list_engine_numbers(self) -> Sequence[ProvisionedNumber]:
        """`GET /phone-numbers` (voices-and-models.md:67-87). The number string is the
        engine's handle for it (it is what `from` takes).
        `rented` is a number we pay ThinnestAI for; `brought` is one on our own carrier
        account. `agent` is the agent answering it, or null while unassigned or lent only for
        calling out (:84-86). In the workspace the caller opened with `in_workspace`; both
        handles come back scoped to it."""
        workspace = workspace_of(None)
        numbers: list[ProvisionedNumber] = []
        rows, reason, _ = await self._walk(
            "/phone-numbers", route="/phone-numbers", workspace=workspace
        )
        if reason is not None:
            log.warning("thinnest_number_listing_incomplete", extra={"reason": reason})
        for row in rows:
            raw = _str(row.get("number"))
            e164 = _e164(raw)
            if raw is None or e164 is None:
                continue
            numbers.append(
                ProvisionedNumber(
                    e164=e164,
                    provider=_str(row.get("provider")),
                    engine_number_ref=scoped_handle(raw, workspace),
                    engine_owned=row.get("source") == "rented",
                    label=_str(row.get("label")),
                    answering_agent_ref=_scoped(_str(row.get("agent")), workspace),
                    calling_agent_ref=_scoped(_str(row.get("callingAgent")), workspace),
                )
            )
        return numbers

    async def bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None:
        raise engine_lacks("inbound_binding", engine=self.name)

    async def unbind_inbound_number(self, number: ProvisionedNumber) -> None:
        raise engine_lacks("inbound_binding", engine=self.name)

    async def set_llm_credential(
        self, secret: str, *, provider: LlmProvider
    ) -> LlmCredentialPlacement:
        """THE LANGUAGE-MODEL KEY SLOT, which this engine never fills. ThinnestAI does take
        our own keys per workspace through its API (`PUT /byok/credentials`,
        snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:149-170), and we use
        that for the VOICE leg only (`install_own_voice_key`, D-688): a voice-only workspace
        runs on their speech-to-text and their model (:13-17). No
        language-model key of ours is installed, so this refuses on the LLM capability."""
        log.warning(LLM_KEY_NOT_INSTALLED, extra={"engine": self.name, "provider": provider})
        raise engine_lacks("llm", engine=self.name)

    # --- knowledge base ------------------------------------------------------
    # One document's `text` is capped at 200,000 characters (knowledge.md:52). A longer
    # source is split on our chunk boundaries and sent as several documents; the handle we
    # return names all of them (`_COMPOSITE_PREFIX`), and `list_kb` rebuilds that handle
    # from the part marker in each title, so the KB publish path and the drift sweep compare
    # one handle per source exactly as they do on every other engine.

    async def _post_knowledge(self, ref: EngineAgentRef, title: str, text: str) -> str:
        raw, workspace = self._at(ref)
        data = await self._request(
            "POST",
            f"/agents/{raw}/knowledge",
            route="/agents/{ref}/knowledge",
            workspace=workspace,
            json={"title": title, "text": text},
        )
        handle = _str(data.get("id"))
        if handle is None:
            raise _bad_response("The voice platform did not return a knowledge base id.")
        if data.get("status") == "failed":
            # Indexed before the response (knowledge.md:46-50): `failed` means it never will
            # be. The document exists, so the caller is handed its id to remove.
            raise _KnowledgeIngestFailedError(handle)
        return handle

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        """`POST /agents/{id}/knowledge` with `{title, text}` (knowledge.md:9-36). Text only:
        files are console uploads (knowledge.md:52), so `source.document` is not sent."""
        text = self._within(
            source.text, KB_TOTAL_MAX_CHARS, code="engine_kb_text_too_long", what="knowledge text"
        )
        parts = split_for_text_cap(text, KB_TEXT_MAX_CHARS) or (text,)
        if len(parts) > KB_MAX_PARTS:
            # Only reachable through a pathological split; the total bound above is the
            # rule an operator reads.
            raise _business_refusal(
                "engine_kb_text_too_long",
                title="The knowledge text is too long for this voice platform",
                detail=f"The knowledge would need {len(parts)} documents; at most "
                f"{KB_MAX_PARTS} are sent for one source.",
                remediation="Split the source into smaller documents and publish again.",
            )
        if len(parts) == 1:
            try:
                return await self._post_knowledge(ref, source.title, parts[0])
            except _KnowledgeIngestFailedError as failed:
                log.warning("thinnest_kb_ingest_failed", extra={"kb_handle": failed.handle})
                raise _ingest_failed() from None
        group = uuid.uuid4().hex[:12]
        added: list[str] = []
        for index, part in enumerate(parts, start=1):
            title = f"{source.title}{_PART_MARKER.format(i=index, n=len(parts), g=group)}"
            try:
                added.append(await self._post_knowledge(ref, title, part))
            except Exception as exc:
                if isinstance(exc, _KnowledgeIngestFailedError):
                    added.append(exc.handle)
                await self._remove_parts(ref, added)
                log.warning(
                    "thinnest_kb_part_failed",
                    extra={"part": index, "parts": len(parts), "removed": len(added)},
                )
                raise ProblemError(
                    kind="dependency",
                    code="engine_kb_part_failed",
                    title="The voice platform could not take all of this knowledge",
                    detail=(
                        f"The knowledge was sent as {len(parts)} parts and part {index} was "
                        "not accepted. The parts already sent were removed, so the agent "
                        "holds none of it."
                    ),
                    remediation="Try publishing the knowledge again. If it keeps failing, "
                    "contact us.",
                ) from None
        return f"{_COMPOSITE_PREFIX}{','.join(added)}"

    async def _remove_parts(self, ref: EngineAgentRef, handles: Sequence[str]) -> None:
        """Best effort: a part left behind is counted by `list_kb` as a loose document,
        which the KB publish path reports as out of sync."""
        raw, workspace = self._at(ref)
        for handle in handles:
            try:
                await self._request(
                    "DELETE",
                    f"/agents/{raw}/knowledge/{handle}",
                    route="/agents/{ref}/knowledge/{kb}",
                    workspace=workspace,
                    absent_is_success=True,
                )
            except Exception as exc:
                log.error(
                    "thinnest_kb_part_orphaned",
                    extra={"kb_handle": handle, "reason": exc.__class__.__name__},
                )

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        """`DELETE /agents/{id}/knowledge/{documentId}` (knowledge.md:44); a handle it does
        not hold is a 404, which raises. A composite handle removes every part: a part
        already gone is skipped, any other failure raises once the rest were tried, and
        the 404 is raised only when no part was there at all."""
        raw, workspace = self._at(ref)
        handles = _parts_of(kb)
        absent: EngineRejectedError | None = None
        failure: Exception | None = None
        removed = 0
        for handle in handles:
            try:
                await self._request(
                    "DELETE",
                    f"/agents/{raw}/knowledge/{handle}",
                    route="/agents/{ref}/knowledge/{kb}",
                    workspace=workspace,
                )
            except EngineRejectedError as exc:
                if exc.vendor_status != 404:
                    failure = failure or exc
                    continue
                absent = exc
                continue
            except ProblemError as exc:
                failure = failure or exc
                continue
            removed += 1
        if failure is not None:
            raise failure
        if removed == 0 and absent is not None:
            raise absent

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        raw, workspace = self._at(ref)
        rows, reason, _ = await self._walk(
            f"/agents/{raw}/knowledge", route="/agents/{ref}/knowledge", workspace=workspace
        )
        if reason is not None:
            raise ProblemError(
                kind="dependency",
                code="engine_listing_incomplete",
                title="The voice platform's knowledge list could not be read in full",
                detail="We could not read every document this agent holds.",
                remediation="Try again. If it keeps failing, contact us.",
            )
        return _rebuild_composites(rows)

    async def list_account_kb(self) -> AccountKBListing:
        """The union over the account's agents: knowledge here is agent-scoped, so there is
        no account-level list to ask. A failure on one agent makes the answer incomplete. In the
        workspace the caller opened with `in_workspace` (each sweep walks every workspace)."""
        workspace = workspace_of(None)
        objects: list[AccountKBObject] = []
        agents, reason, pages = await self._walk("/agents", route="/agents", workspace=workspace)
        for row in agents:
            raw = _str(row.get("id"))
            if raw is None:
                continue
            try:
                handles = await self.list_kb(scoped_handle(raw, workspace))
            except ProblemError:
                reason = reason or "partial_fan_out"
                continue
            pages += 1
            objects.extend(AccountKBObject(handle=handle, state="ready") for handle in handles)
        return AccountKBListing(
            objects=objects,
            complete=reason is None,
            incomplete_reason=reason,
            pages_fetched=max(1, pages),
        )

    # --- voices --------------------------------------------------------------
    # The voices this engine speaks are its own (`GET /voices`), and the voices of the voice
    # key we installed (`GET /byok/voices`). Which of them a
    # client may choose is an operator's decision, kept in `platform_voice_catalog` and
    # synced by `agents/hosted_voices.py`; nothing here decides it.

    async def list_voices(self) -> EngineVoiceListing:
        """Refuses: this engine speaks the voices it hosts, not ours (`list_hosted_voices`)."""
        raise engine_lacks("tts", engine=self.name)

    async def list_hosted_voices(self) -> HostedVoiceListing:
        """`GET /voices` in the workspace the caller opened (`in_workspace`; our developer
        workspace by default): every voice, with its price band. Not paged;
        Studio voices and our clones (`mine: true`) are listed on the Pro plan and above only,
        so a lower plan answers standard and premium voices and no Studio ones; "every voice
        speaks every supported language" (snapshots/2026-10-07b/pages/api-reference/voices/
        list-voices.md:7, :346-347, :417-451; unchanged in snapshots/2026-10-08 and on
        docs.thinnest.ai, read 10 Oct 2026). The one Studio voice the vendor's guide says
        "previews free on every plan" (snapshots/2026-10-08/pages/guides/
        how-your-agent-sounds.md:132-134) is a console listening sample: the schema has no
        preview or lock field and every id listed is one an agent can be set to, so it is not
        expected here below Pro. A row in a tier we do not read is counted in `unread_bands`
        rather than dropped silently. Which band may be sold is the caller's decision
        (`agents/hosted_voices.py`).

        In a customer workspace our clones are listed with `sharedFromDeveloper: true`
        instead of `mine` (snapshots/2026-10-15/pages/api-reference/voices/
        list-voices.md:442-453, :579-589), so either marks one of ours."""
        data = await self._request("GET", "/voices", route="/voices", workspace=workspace_of(None))
        voices: list[HostedVoice] = []
        unread: Counter[str] = Counter()
        for row in _items(data):
            voice_id, label = _str(row.get("id")), _str(row.get("name"))
            if voice_id is None or label is None:
                continue
            band = _VOICE_BANDS.get(str(row.get("tier")))
            if band is None:
                unread[str(row.get("tier"))] += 1
                continue
            shared = row.get("sharedFromDeveloper") is True
            voices.append(
                HostedVoice(
                    voice_id=voice_id,
                    label=label,
                    source="engine",
                    is_custom=row.get("mine") is True or shared,
                    shared_from_developer=shared,
                    language=_str(row.get("accent")),
                    description=_str(row.get("description")),
                    band=band,
                )
            )
        return HostedVoiceListing(voices=voices, unread_bands=dict(unread))

    async def list_own_key_voices(self) -> HostedVoiceListing:
        """`GET /byok/voices`: the voices our installed voice key reaches, with the
        provider's own sample when it hosts one. `409` when the workspace is not on its own
        keys (snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys/
        list-byok-voices.md:7, :344-379, :452-485) — so it is read in a client workspace that
        runs Studio, never in our developer workspace, whose switch stays off (D-717).

        One request, no paging parameters: on Cartesia the answer is our own clones first,
        then the library up to 2,000 voices, and `complete` is false when the provider was
        slow and the list may be short (docs.thinnest.ai api-reference/bring-your-own-keys/
        list-byok-voices, read 12 Oct 2026). Anything but `complete: true` is reported as
        short, so the sync withdraws nothing on it. `own` marks a voice of our own provider
        account (on Cartesia, the voices our account owns) rather than its library, and is
        `is_custom` here (snapshots/2026-10-15/pages/api-reference/bring-your-own-keys/
        list-byok-voices.md:731-739)."""
        data = await self._request(
            "GET", "/byok/voices", route="/byok/voices", workspace=workspace_of(None)
        )
        provider = data.get("provider")
        voices = [
            HostedVoice(
                voice_id=voice_id,
                label=label,
                source="byok",
                is_custom=row.get("own") is True,
                language=_str(row.get("language")),
                # `gender` is "its gender, when the provider says" (list-byok-voices.md:576-580).
                gender=_str(row.get("gender")),
                sample_url=_str(row.get("sample")),
            )
            for row in _items(data)
            if (voice_id := _str(row.get("id"))) and (label := _str(row.get("name")))
        ]
        return HostedVoiceListing(
            voices=voices,
            provider=_str(provider.get("id")) if isinstance(provider, dict) else None,
            complete=data.get("complete") is True,
        )

    async def preview_own_key_voice(
        self,
        *,
        voice_id: str,
        text: str | None,
        language: str | None,
        tuning: ByokVoiceTuning | None = None,
    ) -> PreviewAudio:
        """`POST /byok/voices/preview`: one spoken line as audio, charged by the provider per
        character, so `text` is capped at 200 (snapshots/2026-10-07b/pages/api-reference/
        bring-your-own-keys/preview-byok-voice.md:7, :350-360, :442-470). `409` outside a
        workspace on its own keys (:396-397), so it runs where `list_own_key_voices` does."""
        body: dict[str, Any] = {"voice": voice_id}
        if text:
            body["text"] = self._within(
                text,
                BYOK_PREVIEW_TEXT_MAX_CHARS,
                code="engine_preview_text_too_long",
                what="preview line",
            )
        if language:
            body["language"] = language
        # How the voice should sound, heard before it is saved: only the fields sent are
        # spoken and the agent's saved settings are not read (snapshots/2026-10-13/pages/
        # api-reference/bring-your-own-keys.md:409-419).
        body.update({k: v for k, v in _tuning_wanted(tuning).items() if v is not None})
        try:
            audio, content_type = await vendor_audio_request(
                self._http(),
                "POST",
                "/byok/voices/preview",
                engine=self.name,
                route="/byok/voices/preview",
                headers=workspace_headers("POST", "/byok/voices/preview", workspace_of(None)),
                json=body,
            )
        except EngineRejectedError as exc:
            refusal = _tuning_refusal(exc)
            if refusal is None:
                raise
            raise refusal from exc
        return PreviewAudio(data=audio, content_type=content_type)

    @staticmethod
    def _clone(row: dict[str, Any]) -> VoiceClone | None:
        clone_id = _str(row.get("id"))
        voice_id = _str(row.get("voiceId"))
        label = _str(row.get("name"))
        if clone_id is None or voice_id is None or label is None:
            return None
        return VoiceClone(
            clone_id=clone_id,
            voice_id=voice_id,
            label=label,
            language=_str(row.get("language")),
            preview_url=_str(row.get("previewUrl")),
            usable_on_agents=row.get("usableOnAgents") is True,
        )

    async def create_voice_clone(self, sample: VoiceCloneSample) -> VoiceClone:
        """`POST /voice-clones`, multipart, in our own workspace.
        Both consents are sent as the string `"true"`, the only value the vendor accepts;
        without them nothing is stored (snapshots/2026-10-07b/pages/api-reference/
        voice-clones/create-voice-clone.md:7, :341-349, :530-588). `403` is the plan, `409`
        the clone limit, `400` the recording or a field."""
        if not (sample.consent_own_voice and sample.consent_no_impersonation):
            raise _business_refusal(
                "voice_clone_consent_missing",
                title="Both promises are needed to clone a voice",
                detail="Cloning needs both attestations: that the recording is the speaker's "
                "own voice or held with their permission, and that it will not be used to "
                "impersonate anyone.",
                remediation="Confirm both statements, then clone again.",
            )
        form: dict[str, str] = {
            "name": sample.name,
            "removeNoise": "true" if sample.remove_noise else "false",
            "consentOwnVoice": "true",
            "consentNoImpersonation": "true",
        }
        if sample.description:
            form["description"] = sample.description
        if sample.language:
            form["language"] = sample.language
        try:
            data = await self._request(
                "POST",
                "/voice-clones",
                route="/voice-clones",
                workspace=workspace_of(None),
                data=form,
                files={"sample": (sample.filename, sample.data, sample.content_type)},
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            refusal = _clone_refusal(exc)
            if refusal is exc:
                raise
            raise refusal from exc
        clone = self._clone(data)
        if clone is None:
            raise _bad_response("The voice platform did not describe the cloned voice.")
        return clone

    async def list_voice_clones(self) -> list[VoiceClone]:
        """Every clone of the workspace the caller opened with `in_workspace`, from
        `GET /voice-clones` (snapshots/2026-10-07b/pages/api-reference/voice-clones/
        list-voice-clones.md:7). Refuses rather than answering a partial list."""
        rows, reason, _ = await self._walk(
            "/voice-clones", route="/voice-clones", workspace=workspace_of(None)
        )
        if reason is not None:
            raise ProblemError(
                kind="dependency",
                code="engine_listing_incomplete",
                title="The voice platform's clone list could not be read in full",
                detail="We could not confirm which voices this workspace has cloned.",
                remediation="Try again. If it keeps failing, contact us.",
            )
        return [clone for row in rows if (clone := self._clone(row)) is not None]

    async def find_voice_clone(self, voice_id: str) -> VoiceClone | None:
        """The clone whose `voiceId` is `voice_id`, from `GET /voice-clones`, or None
        (snapshots/2026-10-07b/pages/api-reference/voice-clones/list-voice-clones.md:7)."""
        rows, reason, _ = await self._walk(
            "/voice-clones", route="/voice-clones", workspace=workspace_of(None)
        )
        for row in rows:
            clone = self._clone(row)
            if clone is not None and clone.voice_id == voice_id:
                return clone
        if reason is not None:
            raise ProblemError(
                kind="dependency",
                code="engine_listing_incomplete",
                title="The voice platform's clone list could not be read in full",
                detail="We could not confirm whether this voice is one of our clones.",
                remediation="Try again. If it keeps failing, contact us.",
            )
        return None

    async def delete_voice_clone(self, clone_id: str) -> int:
        """`DELETE /voice-clones/{id}`: forgets the voice everywhere and moves every agent on
        it back to a standard voice; answers how many it moved (snapshots/2026-10-07b/pages/
        api-reference/voice-clones/delete-voice-clone.md:7, :345-355)."""
        data = await self._request(
            "DELETE",
            f"/voice-clones/{quote(clone_id, safe='')}",
            route="/voice-clones/{id}",
            workspace=workspace_of(None),
        )
        moved = data.get("movedAgents")
        return moved if isinstance(moved, int) and not isinstance(moved, bool) else 0

    # --- own keys (BYOK) -----------------------------------------------------

    async def own_keys_in_use(self) -> bool:
        """`GET /byok`: do calls run on ALL THREE of our own keys? `using` is `own`,
        `developer` (a customer on its developer's keys) or `none`, and `scope` is `all` or
        `voice` (snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:115-147).
        Voice-only is not this: it is how the Studio rung is sold, per agent (D-688). A body
        without a readable `using` is refused rather than read as "no", because the answer
        decides which rate a publish stamps."""
        state = await self.own_key_state()
        return state.using != "none" and state.scope == "all"

    async def own_key_state(self) -> OwnVoiceKeyState:
        """`GET /byok` (snapshots/2026-10-07b/pages/api-reference/
        bring-your-own-keys.md:115-147)."""
        data = await self._request("GET", "/byok", route="/byok", workspace=workspace_of(None))
        return _key_state(data)

    async def install_own_voice_key(
        self, *, provider: str, api_key: str, model: str | None
    ) -> None:
        """`PUT /byok/credentials` with `kind: tts`. The provider checks
        the key before it is stored; `400` is a key or model it rejected, `502` a provider it
        could not reach (bring-your-own-keys.md:149-170). The key is never logged."""
        credentials: dict[str, str] = {"apiKey": api_key}
        if model:
            credentials["model"] = model
        try:
            await self._request(
                "PUT",
                "/byok/credentials",
                route="/byok/credentials",
                workspace=workspace_of(None),
                json={"kind": "tts", "provider": provider, "credentials": credentials},
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 400:
                raise
            raise _business_refusal(
                "engine_voice_key_rejected",
                title="The voice provider rejected our key",
                detail="The voice platform checked the voice key with the provider, which "
                "refused it or does not offer the chosen model on it.",
                remediation="Check the voice provider key and model, then try again.",
            ) from exc

    async def enable_own_voice_key(self) -> OwnVoiceKeyState:
        """`PATCH /byok {enabled: true, scope: "voice"}`, then the state as read back. `409`
        until the voice key is added, checked and has a model
        (bring-your-own-keys.md:186-198). In the ambient workspace: ours (D-727) or a Studio
        client's (D-717); `agents/studio_voices` sets every agent that would follow the switch
        `off` first."""
        workspace = workspace_of(None)
        try:
            await self._request(
                "PATCH",
                "/byok",
                route="/byok",
                workspace=workspace,
                json={"enabled": True, "scope": "voice"},
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 409:
                raise
            raise _business_refusal(
                "engine_voice_key_not_ready",
                title="The voice key is not ready yet",
                detail="The voice platform will not switch on our own voice key until it is "
                "added, checked and has a model.",
                remediation="Install the voice key first, then switch it on.",
            ) from exc
        return await self.own_key_state()

    async def install_own_model_key(self, *, provider: str, api_key: str, model: str) -> None:
        """`PUT /byok/credentials` with `kind: llm` and the model the key runs by default
        (`thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/
        bring-your-own-keys.md:224-245`). `400` is a key or model the provider rejected,
        `502` a provider the platform could not reach. Replacing a key of the same provider
        keeps its model (:239). The key is never logged."""
        try:
            await self._request(
                "PUT",
                "/byok/credentials",
                route="/byok/credentials",
                workspace=workspace_of(None),
                json={
                    "kind": "llm",
                    "provider": provider,
                    "credentials": {"apiKey": api_key, "model": model},
                },
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 400:
                raise
            raise _business_refusal(
                "engine_model_key_rejected",
                title="The model provider rejected our key",
                detail="The voice platform checked the language-model key with the provider, "
                "which refused it or does not offer the chosen model on it.",
                remediation="Check the Google key and the model, then try again.",
            ) from exc

    async def enable_own_model_key(self) -> OwnVoiceKeyState:
        """`PATCH /byok {enabled: true, scope: "llm"}` in a workspace whose own keys are off,
        then the state as read back. `409` until the model key is added, checked and has a
        model (bring-your-own-keys.md:261-274). The default scope matters only to an agent
        that follows the workspace; every agent we publish names its own (`_byok_value`)."""
        try:
            await self._request(
                "PATCH",
                "/byok",
                route="/byok",
                workspace=workspace_of(None),
                json={"enabled": True, "scope": "llm"},
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 409:
                raise
            raise _business_refusal(
                "engine_model_key_not_ready",
                title="The model key is not ready yet",
                detail="The voice platform will not switch on our own model key until it is "
                "added, checked and has a model.",
                remediation="Install the Google key first, then switch it on.",
            ) from exc
        return await self.own_key_state()

    async def set_agent_own_keys(
        self, ref: EngineAgentRef, *, own_voice: bool, own_model: str | None
    ) -> None:
        """`PATCH /agents/{id} {byok}` and, on our model key, `PUT /agents/{id}/byok-model`:
        the agent's two key switches put back without touching any other field."""
        raw, workspace = self._at(ref)
        await self._request(
            "PATCH",
            f"/agents/{raw}",
            route="/agents/{ref}",
            workspace=workspace,
            json={"byok": _byok_value(own_voice, own_model)},
        )
        if own_model:
            await self._put_own_model(raw, workspace, own_model, own_voice=own_voice)

    async def disable_own_voice_key(self) -> OwnVoiceKeyState:
        """`PATCH /byok {enabled: false}`, then the state as read back. Every agent on
        `byok: workspace` returns to the platform's own voices at their next call
        (bring-your-own-keys.md:186-198)."""
        await self._request(
            "PATCH",
            "/byok",
            route="/byok",
            workspace=workspace_of(None),
            json={"enabled": False},
        )
        return await self.own_key_state()

    async def agent_own_voice_key(self, ref: EngineAgentRef) -> bool | None:
        """The agent's `byok` as `GET /agents/{id}` holds it, as ours; None when unreported."""
        return _own_voice_key_of(
            await self._request(
                "GET", f"/agents/{raw_of(ref)}", route="/agents/{ref}", workspace=workspace_of(ref)
            )
        )

    async def set_agent_own_voice_key(self, ref: EngineAgentRef, *, on: bool) -> None:
        """`PATCH /agents/{id} {byok}` alone, leaving every other field as it is. The vendor
        reads it once when a call starts, so a ringing call keeps the old value (evaluation
        §12 item 1)."""
        raw, workspace = self._at(ref)
        await self._request(
            "PATCH",
            f"/agents/{raw}",
            route="/agents/{ref}",
            workspace=workspace,
            json={"byok": _byok_value(on)},
        )

    async def list_call_charges(self, *, since: date) -> EngineChargeListing:
        """`GET /usage/calls?from=` — the billing view:
        what each call was charged, as `costMicro` (integer micro-units of `currency`, null
        when nothing was charged) (snapshots/2026-10-07/pages/api-reference/usage/
        list-call-log.md:247-300, :456-459, :533-547). `from` is a date in the workspace's
        time zone, so callers ask from a day early. Converted to rupees here as `Decimal`,
        never through a float. Per workspace: the one the caller opened with `in_workspace`,
        whose call and agent ids come back scoped to it.
        """
        workspace = workspace_of(None)
        charges: list[EngineCharge] = []
        other_currency = 0
        rows, reason, _pages = await self._walk(
            "/usage/calls",
            route="/usage/calls",
            workspace=workspace,
            params={"from": since.isoformat()},
        )
        for row in rows:
            call_id = _str(row.get("id"))
            if call_id is None:
                continue
            if not _is_rupees(row):
                other_currency += 1
                continue
            charged = _charged_inr(row)
            agent = row.get("agent")
            charges.append(
                EngineCharge(
                    engine_call_id=scoped_handle(call_id, workspace),
                    engine_agent_ref=_scoped(
                        _str(agent.get("id")) if isinstance(agent, dict) else None, workspace
                    ),
                    charged_inr=charged,
                )
            )
        return EngineChargeListing(
            charges=charges,
            complete=reason is None and other_currency == 0,
            other_currency=other_currency,
        )

    async def read_catalogue(self) -> EngineCatalogue:
        """`GET /models` (snapshots/2026-10-07b/pages/api-reference/models/list-models.md:7):
        `voice` says a model is fast enough for calls, `available` that this plan may pick
        it, and `voiceOnlyByok` that a call may run on it while only the voice is our own key
        (`bring-your-own-keys.md:44-63`); `callTier` and the minute price as `_CALL_TIERS`
        says. Not paged (live docs, read 12 Oct 2026), so the walk reads one page."""
        model_rows, model_reason, _ = await self._walk("/models", route="/models", workspace=None)
        models = [
            _catalogue_model(model_id, label, row)
            for row in model_rows
            if (model_id := _str(row.get("id"))) and (label := _str(row.get("name")))
        ]
        return EngineCatalogue(models=models, complete=model_reason is None)

    # --- reading the truth ---------------------------------------------------

    def _snapshot(
        self, payload: dict[str, Any], *, workspace: str | None, fallback_id: str = ""
    ) -> ExecutionSnapshot:
        """A call object (get-call.md:14-47, :110-197) as our snapshot.

        `billable_ready` waits for `analysedAt` (results final, get-call.md:190-193) and NOT for
        the recording: an inbound call's only copy of its transcript is the `call.analysed`
        delivery, which may say `ready: false` (get-call.md:170-174), and holding it back would
        lose that transcript. The link is valid before the audio lands (it answers 404 for a
        minute or so), so it is passed on and the recording copy retries.
        """
        raw_call = _call_id_of(payload)
        call_id = scoped_handle(raw_call, workspace) if raw_call else fallback_id
        raw_status = (_str(payload.get("status")) or "").lower()
        hangup = _str(payload.get("hangup"))
        terminal = raw_status in _TERMINAL_RAW
        direction: CallDirection = (
            "inbound" if payload.get("direction") == "inbound" else "outbound"
        )
        customer = _e164(payload.get("phone"))
        ours = _e164(payload.get("from"))
        recording = payload.get("recording")
        recording_url = _str(recording.get("url")) if isinstance(recording, dict) else None
        started = _parse_dt(payload.get("startedAt"))
        ended = _parse_dt(payload.get("endedAt"))
        seconds = payload.get("seconds")
        duration_s: int | None = None
        if isinstance(seconds, int | float) and not isinstance(seconds, bool):
            duration_s = int(seconds)
        if duration_s is None and started is not None and ended is not None:
            duration_s = max(int((ended - started).total_seconds()), 0)
        turns, unparsed = parse_transcript(
            payload.get("transcript"),
            call_id,
            started=started,
            answered=_parse_dt(payload.get("answeredAt")),
        )
        fields = payload.get("fields")
        analysed = payload.get("analysedAt") is not None or hangup == "not_placed"
        agent = _scoped(_agent_ref_of(payload), workspace)
        # `forwardedTo` is the phone a number forward put the call through to, absent or
        # null otherwise (api-reference/webhooks "call.completed", read 11 Oct 2026).
        forwarded = bool(_str(payload.get("forwardedTo")))
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=agent,
            direction=direction,
            status=_our_status(raw_status, hangup),
            raw_status=raw_status or "unknown",
            terminal=terminal,
            billable_ready=terminal and analysed,
            started_at=started,
            ended_at=ended,
            duration_s=duration_s,
            # `phone` is the customer and `from` our number (get-call.md:125-132). On an
            # inbound call the customer dialled us, so they swap. UNVERIFIED: the mirror only
            # describes `from` on calls we placed.
            from_e164=customer if direction == "inbound" else ours,
            to_e164=ours if direction == "inbound" else customer,
            recording_url=recording_url,
            transcript=turns,
            transcript_lines_unparsed=unparsed,
            cost=None,
            engine_charged_inr=_charged_inr(payload),
            engine_extracted=fields if isinstance(fields, dict) else {},
            # "Two or three sentences about the call, when summarised" (get-call.md:766-770);
            # final once `analysedAt` is set, so a summary on an unanalysed row is not read.
            engine_summary=((_str(payload.get("summary")) or "").strip() or None)
            if analysed
            else None,
            quality=parse_quality(payload.get("quality")),
            llm_usage=parse_llm_usage(payload.get("usage")),
            tts_characters=parse_tts_characters(payload.get("usage")),
            billing=parse_billing(payload.get("billing"), hangup=hangup, forwarded=forwarded),
            # List Calls rows carry `billing` once the vendor's release of 17 Oct 2026 is live
            # (snapshots/2026-10-18/pages/whats-new/index.md:20-23); a row from before it has
            # no key at all, which `billing_reported` tells apart from `billing: null`.
            billing_reported="billing" in payload,
            forwarded=forwarded,
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """`GET /calls/{id}`; always the newest try (get-call.md:76). Takes any id the call
        list hands out, inbound calls included (snapshots/2026-10-07/pages/api-reference/
        calls/get-call.md:7); the first docs said it answered 404 for calls the API did not
        place, and `workers/engine_delivery` keeps its fallbacks for when it does."""
        raw_call, workspace = self._at(call_id)
        payload = await self._request(
            "GET", f"/calls/{raw_call}", route="/calls/{id}", workspace=workspace
        )
        return self._snapshot(payload, workspace=workspace, fallback_id=call_id).model_copy(
            update={
                "raw_document": engine_document(payload, engine=self.name),
                "content_deleted": _content_deleted(payload),
            }
        )

    def recording_source(self, snapshot: ExecutionSnapshot) -> EngineRecordingSource | None:
        """The authenticated `GET /calls/{id}/recording` for a finished call, or None.

        That endpoint rather than the signed `recording.url`: it serves every id the call
        list hands out, inbound calls included, where a call settled from the list carries
        no link at all; MP3, `404` with `Retry-After` until the audio lands, `404` without
        one when the call was not recorded, `410` once the plan deleted it (30 days on
        pay-as-you-go) (snapshots/2026-10-07/pages/api-reference/recordings/
        get-call-recording.md:247-300). Only our API host may be fetched, with or without the
        key. Asked for a call that ended normally or that carries a link; a missed or failed
        call has nothing to fetch, and neither has a call whose content was deleted.
        """
        if not self._api_key or not snapshot.engine_call_id or not snapshot.terminal:
            return None
        if snapshot.content_deleted:
            return None
        if snapshot.recording_url is None and snapshot.raw_status != "completed":
            return None
        host = (urlsplit(self._base_url).hostname or "").lower()
        raw, workspace = self._at(snapshot.engine_call_id)
        return EngineRecordingSource(
            url=f"{self._base_url.rstrip('/')}/calls/{quote(raw, safe='')}/recording",
            rules=RecordingFetchRules(
                allowed_hosts=frozenset({host}),
                content_types=frozenset({"audio/mpeg"}),
                not_ready_status=404,
                gone_status=410,
                # `Workspace not found.` is a 404 too (get-call-recording.md:551).
                misaddressed_codes=SCOPE_NOT_FOUND_CODES,
            ),
            auth_headers={
                AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}",
                **workspace_headers("GET", "/calls/{id}/recording", workspace),
            },
            auth_hosts=frozenset({host}),
        )

    def snapshot_from_delivery(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        """The snapshot a VERIFIED `call.analysed` delivery carries: "exactly the object
        above" (get-call.md:56-65), the only source of an inbound call's transcript and
        recording. Call it after `verify_webhook` has passed, never before, inside
        `in_workspace` of the delivering agent's workspace so the ids come back scoped."""
        data = payload.get("data")
        call = data if isinstance(data, dict) else {}
        return self._snapshot(call, workspace=workspace_of(None)).model_copy(
            update={"raw_document": engine_document(call, engine=self.name)}
        )

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """`GET /calls?since=` with the cursor (list-calls.md:56-61). `since` filters on
        when the call started, which is the Protocol's anchor.

        Rows are summaries: no transcript and no recording (list-calls.md:44-46). A call
        with retries is listed once per try under one id (list-calls.md:48-49); the list
        is newest first, so the first row seen for an id is its newest try.
        """
        instant = since.astimezone(UTC).isoformat().replace("+00:00", "Z")
        snapshots: list[ExecutionSnapshot] = []
        seen: set[str] = set()
        reason: ListingIncompleteReason | None = None
        workspace = workspace_of(None)
        rows, reason, pages = await self._walk(
            "/calls", route="/calls", workspace=workspace, params={"since": instant}
        )
        for row in rows:
            snapshot = self._snapshot(row, workspace=workspace).model_copy(
                update={"content_deleted": _content_deleted(row)}
            )
            if not snapshot.engine_call_id or snapshot.engine_call_id in seen:
                continue
            seen.add(snapshot.engine_call_id)
            snapshots.append(snapshot)
        if reason is not None:
            return ExecutionListing(
                snapshots=snapshots, complete=False, incomplete_reason=reason, pages_fetched=pages
            )
        return ExecutionListing(snapshots=snapshots, complete=True, pages_fetched=pages)

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """`x-thinnest-signature-v2`: HMAC-SHA256 of `<delivered-at>.<raw body>` under the
        agent's own endpoint secret, and the delivery time within five minutes of our clock
        (`snapshots/2026-10-08/pages/api-reference/webhooks.md:100-147`). The v1 header,
        which signs no time, is not accepted; `apps/voice-runtime/signed_intake.py` argues it.

        The agent named in the body only selects WHICH secret to check against; a sender
        naming another agent still needs that agent's secret.
        """
        lowered = {key.lower(): value for key, value in headers.items()}
        signature = lowered.get(SIGNATURE_HEADER)
        delivered_at = lowered.get(DELIVERED_AT_HEADER)
        if not signature or not delivered_at:
            return WebhookVerdict(ok=False, method="hmac", reason="signature_missing")
        try:
            payload = json.loads(body)
        except ValueError:
            return WebhookVerdict(ok=False, method="hmac", reason="body_unreadable")
        data = payload.get("data") if isinstance(payload, dict) else None
        agent = _agent_ref_of(data) if isinstance(data, dict) else None
        ref = _scoped(agent, workspace_of(None))
        if ref is None:
            return WebhookVerdict(ok=False, method="hmac", reason="agent_unidentified")
        secret = self._signing_secret_for(ref) if self._signing_secret_for else None
        if secret is None:
            return WebhookVerdict(ok=False, method="hmac", reason="signing_secret_unavailable")
        if not timestamped_sha256_signature_matches(
            body, signature, secret, signed_at=delivered_at
        ):
            return WebhookVerdict(ok=False, method="hmac", reason="signature_mismatch")
        if not signed_time_is_fresh(
            delivered_at, now=datetime.now(UTC), tolerance=DELIVERY_TOLERANCE
        ):
            return WebhookVerdict(ok=False, method="hmac", reason="delivery_stale")
        return WebhookVerdict(ok=True, method="hmac")

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """`{event, sentAt, data}` (mcp/own-database.md:75-76) to our event. A body without
        the envelope is read as the call object itself. An unknown or absent status degrades
        to `failed`, an unstated direction to outbound, and no tenant is ever read from it.

        UNVERIFIED: the `call.completed` body is described only as "outcome and duration"
        (webhooks.md:74); it is read with the call object's field names."""
        data = payload.get("data")
        call: dict[str, Any] = data if isinstance(data, dict) else payload
        raw_status = (_str(call.get("status")) or "").lower()
        hangup = _str(call.get("hangup"))
        direction: CallDirection = "inbound" if call.get("direction") == "inbound" else "outbound"
        customer = _e164(call.get("phone"))
        ours = _e164(call.get("from"))
        recording = call.get("recording")
        recording_url = _str(recording.get("url")) if isinstance(recording, dict) else None
        return CallEvent(
            call_id=_scoped(_call_id_of(call), workspace_of(None)) or "",
            engine_agent_ref=_scoped(_agent_ref_of(call), workspace_of(None)),
            direction=direction,
            status=_our_status(raw_status, hangup),
            raw_status=raw_status or "unknown",
            started_at=_parse_dt(call.get("startedAt")),
            ended_at=_parse_dt(call.get("endedAt")),
            from_e164=customer if direction == "inbound" else ours,
            to_e164=ours if direction == "inbound" else customer,
            recording_url=recording_url,
            engine=self.name,
        )

    def parse_notice(self, payload: dict[str, Any]) -> EngineNotice | None:
        """A VERIFIED `lead.captured` or `conversation.escalated` delivery as our notice, or
        None for any other event. Call it after `verify_webhook` has passed.

        `data.agentId` is the agent that ran the tool (on a handed call, the agent the call
        was handed to) and `data.callId` the call it was on, null off a call
        (docs.thinnest.ai api-reference/webhooks "lead.captured" and
        "conversation.escalated", read 11 Oct 2026). Nothing else in `data` is read: the
        lead's name and number are the caller's personal data and our extraction pass is
        the record.
        """
        kind = _NOTICE_KINDS.get(str(payload.get("event")))
        notice_id = _str(payload.get("id"))
        if kind is None or notice_id is None:
            return None
        data = payload.get("data")
        body: dict[str, Any] = data if isinstance(data, dict) else {}
        return EngineNotice(
            kind=kind,
            notice_id=notice_id,
            engine_agent_ref=_scoped(
                _agent_ref_of(body) or _str(body.get("agentId")), workspace_of(None)
            ),
            engine_call_id=_scoped(_str(body.get("callId")), workspace_of(None)),
            occurred_at=_parse_dt(payload.get("sentAt")),
            engine=self.name,
        )

    def parse_opt_out(self, payload: dict[str, Any]) -> EngineOptOut | None:
        """A VERIFIED `contact.opted_out` delivery as our opt-out, or None for any other event.

        `data` is `{phone, callId, source, optedOutAt, reason}`; `reason` is what the caller
        said, up to 160 characters in their language, or null when the agent kept no words
        (snapshots/2026-10-13/pages/api-reference/webhooks.md:85, :496-513). A missing phone
        stays None so the receiver can say the opt-out could not be filed."""
        if payload.get("event") != "contact.opted_out":
            return None
        data = payload.get("data")
        body: dict[str, Any] = data if isinstance(data, dict) else {}
        reason = body.get("reason")
        return EngineOptOut(
            phone=_str(body.get("phone")),
            engine_call_id=_scoped(_str(body.get("callId")), workspace_of(None)),
            reason=reason.strip() or None if isinstance(reason, str) else None,
            engine=self.name,
        )

    def parse_problem(self, payload: dict[str, Any]) -> EngineProblem | None:
        """A VERIFIED `call.problem` delivery as our problem, or None for any other event, an
        unknown `kind` or a delivery naming no call (docs.thinnest.ai api-reference/webhooks
        "call.problem", read 11 Oct 2026). `detail`, the vendor's own sentence ("a sentence
        you can show a person", snapshots/2026-10-13/pages/api-reference/webhooks.md:131-132),
        is read for `byok_failed` alone, for the operator alarm (`problem_detail`)."""
        if payload.get("event") != "call.problem":
            return None
        problem_id = _str(payload.get("id"))
        data = payload.get("data")
        body: dict[str, Any] = data if isinstance(data, dict) else {}
        kind = _PROBLEM_KINDS.get(str(body.get("kind")))
        call = _scoped(_str(body.get("callId")), workspace_of(None))
        if problem_id is None or kind is None or call is None:
            return None
        return EngineProblem(
            kind=kind,
            problem_id=problem_id,
            engine_agent_ref=_scoped(_str(body.get("agentId")), workspace_of(None)),
            engine_call_id=call,
            occurred_at=_parse_dt(body.get("at")) or _parse_dt(payload.get("sentAt")),
            engine=self.name,
            operator_detail=problem_detail(body.get("detail"))
            if kind == "own_key_failed"
            else None,
        )

    def parse_contact_erased(self, payload: dict[str, Any]) -> EngineContactErased | None:
        """A VERIFIED `contact.erased` delivery, or None for any other event or one naming no
        contact. `data` is `{contactId, erasedAt}`, sent once when the last recording of an
        erased contact is gone; a developer-wide endpoint also gets `data.workspaceId`
        (snapshots/2026-10-15/pages/api-reference/webhooks.md:286, :536-563)."""
        if payload.get("event") != "contact.erased":
            return None
        event_id = _str(payload.get("id"))
        data = payload.get("data")
        body: dict[str, Any] = data if isinstance(data, dict) else {}
        contact = _str(body.get("contactId"))
        if event_id is None or contact is None:
            return None
        return EngineContactErased(
            event_id=event_id,
            contact_id=contact,
            workspace=_str(body.get("workspaceId")),
            erased_at=_parse_dt(body.get("erasedAt")),
            engine=self.name,
        )

    def parse_byok_changed(self, payload: dict[str, Any]) -> EngineByokChanged | None:
        """A VERIFIED `byok.changed` delivery, or None for any other event or an unknown
        `change`. `data` is `{change, kind, provider, byokEnabled, scope}`, the state AFTER the
        change, and never any part of a key (snapshots/2026-10-15/pages/api-reference/
        webhooks.md:565-597)."""
        if payload.get("event") != "byok.changed":
            return None
        event_id = _str(payload.get("id"))
        data = payload.get("data")
        body: dict[str, Any] = data if isinstance(data, dict) else {}
        change = _str(body.get("change"))
        if event_id is None or change not in _BYOK_CHANGES:
            return None
        enabled = body.get("byokEnabled")
        return EngineByokChanged(
            event_id=event_id,
            change=cast(EngineByokChange, change),
            kind=_str(body.get("kind")),
            provider=_str(body.get("provider")),
            byok_enabled=enabled if isinstance(enabled, bool) else None,
            scope=_str(body.get("scope")),
            workspace=_str(body.get("workspaceId")),
            engine=self.name,
        )

    async def platform_status(self) -> PlatformStatus:
        """ThinnestAI's own reading of its health: `GET {origin}/api/status`, no key.

        UNDOCUMENTED: named in ThinnestAI's email of 11 Oct 2026 and absent from
        docs.thinnest.ai (searched 11 Oct 2026). The shape is the one the endpoint answered
        on 11 Oct 2026, `{checkedAt, database, voiceEngine}` with `"operational"`; any other
        value of either part is read as not operational, and no answer as unknown.
        """
        if self._api_key is None and self._status_transport is None:
            # An adapter with no key is not talking to the platform at all.
            return PlatformStatus(reachable=False)
        origin = self._base_url.rstrip("/").removesuffix("/v1")
        try:
            async with httpx.AsyncClient(
                timeout=STATUS_TIMEOUT_S, transport=self._status_transport
            ) as client:
                response = await client.get(f"{origin}/status")
            body = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            body = None
        if not isinstance(body, dict):
            return PlatformStatus(reachable=False)
        calls, data = body.get("voiceEngine"), body.get("database")
        return PlatformStatus(
            reachable=True,
            calls_operational=calls == STATUS_OPERATIONAL,
            data_operational=data == STATUS_OPERATIONAL,
            reported=f"voice {_status_word(calls)}, data {_status_word(data)}",
        )


#: The vendor events that become an `EngineNotice` (webhooks.md:79-80).
_NOTICE_KINDS: Final[dict[str, EngineNoticeKind]] = {
    "lead.captured": "lead_captured",
    "conversation.escalated": "conversation_escalated",
}
#: Every event a ThinnestAI endpoint of ours should be subscribed to for the notices above.
NOTICE_EVENTS: Final = tuple(_NOTICE_KINDS)


__all__ = [
    "BASE_URL",
    "KEY_SCOPE_CODES",
    "LLM_KEY_NOT_INSTALLED",
    "NOTICE_EVENTS",
    "PAUSED_LINE_MESSAGE",
    "SIGNATURE_HEADER",
    "THINNEST_CAPABILITIES",
    "SigningSecretResolver",
    "ThinnestEngine",
    "parse_transcript",
    "vendor_agent_name",
]
