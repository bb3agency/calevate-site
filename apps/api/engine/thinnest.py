"""ThinnestAI adapter: a `control_plane` engine reached over its REST API (D-678).

ThinnestAI hosts the agent and the call. We create and edit the agent over
`https://app.thinnest.ai/api/v1`, dial with `POST /calls`, and read results from their call
endpoints and signed webhooks. The plan is `docs/THINNEST-INTEGRATION.md`; every vendor fact
below cites the hash-pinned mirror `thinnest-findings/mirror/pages/` (VERIFIED-VENDOR-DOCS)
as `path:line`. No request has been made against a live ThinnestAI account from this tree.

Where the mirror is silent the value is marked UNVERIFIED at the line and the adapter either
sends nothing or refuses by name. The open items: the shape of a `call.completed` body, and
which number `from` names on an inbound call.

ONE WORKSPACE, TWO RUNGS (D-688). Every agent lives in our developer workspace, which runs on
voice-only BYOK with our Cartesia key (`thinnest-findings/mirror/snapshots/2026-10-07b/pages/
api-reference/bring-your-own-keys.md:13-24`). Each agent says whether it follows that:
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
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, get_args
from urllib.parse import quote, urlsplit

import httpx
from calevate_shared.engine import (
    E164,
    AccountKBListing,
    AccountKBObject,
    AgentConfig,
    AgentSnapshot,
    AvailableNumber,
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
    LlmTier,
    NumberSearch,
    NumberSpec,
    ProvisionedNumber,
    RecallOutcome,
    WebhookVerdict,
    compose_engine_prompt,
)
from calevate_shared.events import (
    CallDirection,
    CallEvent,
    CallStatus,
    EngineNotice,
    EngineNoticeKind,
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
from apps.api.engine.recording_source import EngineRecordingSource, RecordingFetchRules
from apps.api.engine.text_split import split_for_text_cap
from apps.api.engine.vendor_http import (
    REQUEST_TIMEOUT_S,
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
# customers.md:68-91: any request runs inside the customer this header names.

# Every list takes `limit` (up to 100) and `cursor` and answers `{items, nextCursor}`
# (introduction.md:55-57; list-calls.md:56-61). The page cap is ours: a walk with no bound
# is an outage against the vendor the first time a cursor misbehaves.
_LISTING_PAGE_SIZE: Final = 100
_LISTING_MAX_PAGES: Final = 20

#: Our tier for each model id the engine lists (D-680), so a client is shown "Standard" and
#: never the vendor's model name. The ordering is read from the engine's own catalogue
#: (`thinnest-findings/mirror/pages/api-reference/voices-and-models.md:55-57`): its own
#: voice-native model and `gpt-5-mini` are on the free plan, `gpt-4.1` only from `payg` up.
#: A model missing here is still offered, as an unnamed additional model.
_MODEL_TIERS: Final[dict[str, LlmTier]] = {
    "prana-voice": "standard",
    "gpt-5-mini": "plus",
    "gpt-4.1": "pro",
}

# Field limits the vendor enforces with a 400 (agents.md:88-99, :161; place-call.md:70,
# :96-100, :203-204; knowledge.md:52). Checked here so a publish is refused with a sentence
# an operator can act on rather than a generic `engine_rejected`, and never truncated:
# a truncated prompt loses its tail, which is where the truthful-answer rule sits.
# `instructions` and `greeting` are from the 7 Oct snapshot
# (`thinnest-findings/mirror/snapshots/2026-10-07/pages/api-reference/agents/
# update-agent.md:426-436`, create-agent.md:434): 20,000 and 200 characters. The 6 Oct pages
# said 8,000; the vendor raised it. The facts still go to knowledge (`agents/engine_facts.py`)
# because `instructions` is "re-sent on every reply, so every character costs on every turn"
# (update-agent.md:430-431). `purpose` is "under 300 characters" (snapshots/2026-10-07/pages/
# api-reference/calls/place-call.md:7).
INSTRUCTIONS_MAX_CHARS: Final = 20_000
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
CALL_VARIABLES_MAX: Final = 20
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

# The agent's `language` is `auto` or one of the 37 English names the console offers
# (snapshots/2026-10-08/pages/api-reference/agents/create-agent.md:603-614); keyed here by our
# BCP-47 primary subtag. A tag outside this map is sent as `auto` (follow the caller).
_AUTO_LANGUAGE: Final = "auto"
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
# request was sent", shared with the owned runtime's dial for the same situation.
DIAL_PRECONDITION_FAILED: Final = "carrier_dial_precondition_failed"

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
# * `action_tools` False: a CLIENT's own during-call actions (D-615, `AgentConfig.action_tools`)
#   are not sent by this adapter. Our platform's in-call tools (opt-out, call-back, call-back
#   cancel, handoff) ARE vendor custom actions, registered beside the agent by
#   `reliability/engine_actions.py`; they are not what this capability describes.
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
    action_tools=False,
    script_override=True,
    webhook_auth="hmac",
)

#: Resolves an agent ref to that agent's webhook signing secret, or None when none is held.
#: The secret is returned once by `POST /webhooks` (webhooks.md:36-39) and stored sealed by
#: the webhook registration path; this adapter only reads it.
SigningSecretResolver = Callable[[str], str | None]


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


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


def _agent_ref_of(payload: dict[str, Any]) -> str | None:
    """The engine agent id: `agent: {id, name}` on call objects (get-call.md:25). A bare
    string `agent`, and `agent_id`, are read as well because the conformance suite feeds
    every adapter one neutral payload; neither is a ThinnestAI field."""
    agent = payload.get("agent")
    if isinstance(agent, dict):
        return _str(agent.get("id"))
    return _str(agent) or _str(payload.get("agent_id"))


def parse_transcript(raw: Any, call_id: str) -> tuple[list[TranscriptTurn], int]:
    """`[{speaker, text, at}]` (get-call.md:35-38) to our turns, and how many we could not
    place. Counted rather than kept: transcript text is hard rule 6."""
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
        turns.append(
            TranscriptTurn(call_id=call_id, idx=len(turns), speaker=speaker, text=text.strip())
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
# `idempotency_in_progress` is deliberately absent: the first request may have placed it.
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
    if code in ("opted_out", "do_not_call"):
        # The person, on the workspace's shared list. Whether the entry is this client's is
        # decided above the adapter (`compliance/platform_dnc.py`).
        return recipient_opted_out_error()
    if code in ("key_scope_build", "key_scope_read"):
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
    elif code in _DIAL_SETUP_CODES or (code == "carrier_unavailable" and exc.vendor_status == 502):
        alert(
            "CORE_LOGIC",
            "engine_dial_setup_refused",
            detail=f"ThinnestAI refused a dial with {code}: the agent, its number or the "
            "phone provider is not set up to place this call, so every such dial fails "
            "until it is fixed",
        )
    if code in _DIAL_NOT_PLACED_CODES and not exc.request_refused:
        return EngineRejectedError(
            status=exc.vendor_status,
            vendor_error=exc.vendor_error,
            refused_statuses=frozenset({exc.vendor_status}),
            vendor_code=code,
            vendor_reason=exc.vendor_reason,
        )
    return exc


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
    voice_provider = next(
        (
            _str(row.get("provider"))
            for row in (credentials if isinstance(credentials, list) else [])
            if isinstance(row, dict) and row.get("kind") == "tts"
        ),
        None,
    )
    return OwnVoiceKeyState(
        enabled=data.get("enabled") is True,
        scope=_str(data.get("scope")),
        complete=data.get("complete") is True,
        using=using,
        voice_provider=voice_provider,
    )


def _byok_value(on: bool) -> str:
    """Our "speaks on our own voice key" as the agent's `byok`: `workspace` follows the
    workspace's voice-only BYOK (our Cartesia key), `off` keeps the agent on ThinnestAI's own
    voices and models at their normal rate (LIVE-DOCS `docs.thinnest.ai/api-reference/
    agents/update-agent`, 8 Oct 2026)."""
    return "workspace" if on else "off"


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
    return drifted


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
    "call_summaries": ("voice.summariseCalls",),
    "escalation": ("escalation",),
    "scheduled_callbacks": ("scheduleCallbacks",),
    "lead_capture": ("captureLeads",),
    "collected_fields": ("collectFields",),
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
            else:
                same = present and have == want and type(have) is type(want)
            if not same:
                drifted.append(label)
                break
    return drifted


def _charged_inr(call: dict[str, Any]) -> Decimal | None:
    """What the call cost the workspace in rupees: `costMicro` is integer millionths of
    `currency` (6370000 is 6.37), null until the call is settled
    (snapshots/2026-10-08/pages/api-reference/calls/get-call.md:498-523). Divided as
    `Decimal`, never through a float; a currency other than INR is not converted here."""
    micro = call.get("costMicro")
    if not isinstance(micro, int) or isinstance(micro, bool) or micro < 0:
        return None
    if call.get("currency") != "INR":
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
    return {"workspace": True, "off": False}.get(value) if isinstance(value, str) else None


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


def language_fields(cfg: AgentConfig) -> tuple[str, str | None]:
    """`(language, voice.language)` for an agent.

    An agent has ONE language: a fixed one is the only language it answers in, and on a call
    it also tells the speech recogniser what to listen for; `auto` ("Match the customer")
    works the language out per sentence. "To serve two, leave the agent on Match the
    customer" — there is no second-language setting, and `secondLanguage` is retired and
    ignored (snapshots/2026-10-08/pages/channels/voice.md:225-239; agent/behaviour.md:51-60;
    api-reference/agents/update-agent.md:560-573). `voice.language` takes a language name or
    null to follow `language`; `auto` there is a 400 (:962-970).

    So a Telugu agent with English as a second language is sent `auto` with the call language
    following it: a fixed Telugu would refuse English replies and mis-hear English callers.
    Its opening line is still the Telugu greeting we compose, so the call starts in Telugu.
    A one-language agent is fixed to that language on both fields, which gives the recogniser
    the language rather than leaving it to guess. A primary tag outside the console's list
    is `auto` as well, because no fixed value we could send would be the agent's language.
    """
    primary = _DOCUMENTED_LANGUAGES.get(_subtag(cfg.language_primary))
    others = {_subtag(tag) for tag in cfg.languages_extra} - {_subtag(cfg.language_primary)}
    if primary is None or others:
        return _AUTO_LANGUAGE, None
    return primary, primary


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
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client
        self._signing_secret_for = signing_secret_for

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
        absent_is_success: bool = False,
        extra_refused_statuses: frozenset[int] = frozenset(),
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await vendor_request(
            self._http(),
            method,
            path,
            engine=self.name,
            route=route,
            absent_is_success=absent_is_success,
            extra_refused_statuses=extra_refused_statuses,
            headers=headers,
            **kwargs,
        )

    async def _walk(
        self,
        path: str,
        *,
        route: str,
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
            payload = await self._request("GET", path, route=route, params=query)
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
        if cfg.action_tools:
            require_capability("action_tools", engine=self)

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
        greeting = self._within(
            cfg.opening_line.strip(),
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
        language, call_language = language_fields(cfg)
        # snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:940-1016.
        # `answersCalls` true and `unavailableMessage` null on every publish: a publish is
        # what lifts a pause (`override_call_script`), so it must switch the line back on.
        # `detectMachines` off (plan §2). `summariseCalls` off and `collectFields` empty: our
        # own extraction pass is the record, and theirs is billed per call.
        # `pastConversations`: `recap` for an agent whose client switched caller memory on
        # (D-507's notice and gates are on OUR switch, `agents.publishing.set_caller_memory`),
        # `fresh` otherwise; never the vendor default `quiet`, which uses earlier
        # conversations without saying so (founder, 8 Oct 2026). Memory is the vendor's and
        # per agent; our own distillation does not run for this engine.
        voice: dict[str, Any] = {
            "answersCalls": True,
            "unavailableMessage": None,
            "language": call_language,
            "recordCalls": True,
            "maxCallSeconds": seconds,
            "detectMachines": False,
            "summariseCalls": False,
            "pastConversations": "recap" if cfg.caller_memory_enabled else "fresh",
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
            "language": language,
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
        }
        # Ids from `GET /voices` and `GET /models`, checked against the catalogue before
        # publish (`agents/engine_choice.py`). A voice of our own voice key goes to
        # `PUT /agents/{id}/byok-voice` after the write instead (`_apply_own_key_voice`).
        if cfg.engine_voice_id:
            voice["voice"] = cfg.engine_voice_id
        if cfg.engine_model_id:
            body["model"] = cfg.engine_model_id
        if cfg.engine_own_voice_key is not None:
            # Always stated, never left to the vendor's `workspace` default: with voice-only
            # BYOK on in the workspace, an agent that omitted it would speak Cartesia.
            body["byok"] = _byok_value(cfg.engine_own_voice_key)
            # A choice that was cleared is sent as `null`, which puts the agent back on the
            # vendor's default (voice Kavya, model Prana [Voice]) (update-agent.md:536-545,
            # :951-961). Kavya bills at the Premium band; publish refuses an agent with no
            # voice chosen (`agents/engine_choice.VOICE_REQUIRED`), so a published agent never
            # runs on it, and the drift sweep repairs one found there. Not sent while the
            # workspace runs on all three of its own keys (`engine_own_voice_key` None), where
            # no per-agent voice or model applies, nor for a voice of our own key.
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
        """
        handoff = cfg.handoff
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
                }
                if handoff is not None
                else {"mode": "chat", "phone": None, "line": None}
            ),
        }

    async def _apply_built_in_tools(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        """Pin the built-in tools, then read what was saved. The vendor applies a change in
        order and stops at the first refusal, keeping what came before, so a refusal or a
        saved state that differs from what was sent is a partial apply: the publish is
        refused rather than left live with a tool we did not choose."""
        wanted = self.built_in_tools_body(cfg)
        try:
            saved = await self._request(
                "PATCH", f"/agents/{ref}/tools", route="/agents/{ref}/tools", json=wanted
            )
        except EngineRejectedError as exc:
            if exc.vendor_status != 400:
                raise
            raise _tools_not_pinned() from exc
        drifted = _tools_drift(wanted, saved)
        if drifted:
            log.warning("thinnest_tools_not_pinned", extra={"fields": ",".join(drifted)})
            raise _tools_not_pinned()

    async def _find_agent(self, cfg: AgentConfig) -> str | None:
        """The vendor id of an agent this adapter already made for `cfg`, found by its name
        tag."""
        tag = _name_tag(cfg)
        rows, reason, _ = await self._walk("/agents", route="/agents")
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

    async def _apply_own_key_voice(self, raw: str, cfg: AgentConfig) -> None:
        """`PUT /agents/{id}/byok-voice` for an agent speaking a voice of our own voice key
        (snapshots/2026-10-07b/pages/api-reference/agents/set-agent-byok-voice.md:322-460).
        A `409` is the workspace not on its own keys, or the agent with no voice channel."""
        if not cfg.engine_byok_voice_id:
            return
        try:
            await self._request(
                "PUT",
                f"/agents/{raw}/byok-voice",
                route="/agents/{ref}/byok-voice",
                json={"voice": cfg.engine_byok_voice_id},
                extra_refused_statuses=frozenset({409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status not in (400, 409):
                raise
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

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        body = self._agent_body(cfg)
        # Built (and so checked) before any write, so a refusal leaves nothing behind.
        self.built_in_tools_body(cfg)
        raw = await self._find_agent(cfg)
        if raw is not None:
            await self._request("PATCH", f"/agents/{raw}", route="/agents/{ref}", json=body)
        else:
            data = await self._request("POST", "/agents", route="/agents", json=body)
            raw = _str(data.get("id"))
            if raw is None:
                raise _bad_response("The voice platform did not return an agent id.")
        await self._apply_own_key_voice(raw, cfg)
        await self._apply_built_in_tools(raw, cfg)
        return raw

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        body = self._agent_body(cfg)
        self.built_in_tools_body(cfg)
        await self._request("PATCH", f"/agents/{ref}", route="/agents/{ref}", json=body)
        await self._apply_own_key_voice(ref, cfg)
        await self._apply_built_in_tools(ref, cfg)

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
        await self._request("PATCH", f"/agents/{ref}", route="/agents/{ref}", json=body)

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """`GET /agents/{id}` (agents.md:80), with the agent's documents from its knowledge
        list: documents are agent-scoped here, so that list IS what the agent references."""
        data = await self._request("GET", f"/agents/{ref}", route="/agents/{ref}")
        returned = _str(data.get("id"))
        if returned is not None and returned != ref:
            raise _bad_response("The voice platform described a different agent.")
        instructions = data.get("instructions")
        greeting = data.get("greeting")
        # A present-but-null greeting is an agent with none; an absent key is unread.
        greeting_readable = "greeting" in data and (greeting is None or isinstance(greeting, str))
        destinations, destinations_readable = _handover_destinations(
            await self._request("GET", f"/agents/{ref}/tools", route="/agents/{ref}/tools")
        )
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
            handoff_destinations=destinations,
            handoff_destinations_readable=destinations_readable,
            engine=self.name,
        )

    async def settings_drift(self, ref: EngineAgentRef, cfg: AgentConfig) -> list[str]:
        """The call settings `GET /agents/{id}` and `GET /agents/{id}/tools` hold that differ
        from what a publish of `cfg` sends (`apps/api/agents/engine_settings.py`).

        Not compared: the script and greeting (`verify_publish` scores them), `byok` (the
        sweep's own-voice-key leg repairs it), and `answersCalls` / `unavailableMessage`,
        which a pause sets on purpose. A voice or model we leave on the vendor's default is
        not compared either: the default comes back as its own id, which we do not hold."""
        agent = await self._request("GET", f"/agents/{ref}", route="/agents/{ref}")
        tools = await self._request("GET", f"/agents/{ref}/tools", route="/agents/{ref}/tools")
        drifted = _settings_drift(self._agent_body(cfg), agent)
        tool_drift = _tools_drift(self.built_in_tools_body(cfg), tools)
        if any(name.startswith("tools.") for name in tool_drift):
            drifted.append("built_in_tools")
        if any(name.startswith("handOver.") for name in tool_drift):
            drifted.append("hand_over")
        return drifted

    async def repair_settings(
        self, ref: EngineAgentRef, cfg: AgentConfig, drifted: Sequence[str]
    ) -> None:
        """`PATCH /agents/{id}` with only the drifted settings, and the built-in tools again
        when they or the hand-over drifted. The script, greeting and line state are not
        sent, so a repair cannot lift a pause or overwrite an emergency console edit of the
        script, which is a human's decision (`agents/publishing.engine_drift_for`)."""
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
            await self._request("PATCH", f"/agents/{ref}", route="/agents/{ref}", json=body)
        if {"built_in_tools", "hand_over"} & set(drifted):
            await self._apply_built_in_tools(ref, cfg)

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """`DELETE /agents/{id}`, 204; it takes the agent's knowledge with it (agents.md:82)."""
        await self._request(
            "DELETE", f"/agents/{ref}", route="/agents/{ref}", absent_is_success=True
        )

    # --- calls ---------------------------------------------------------------

    async def _outbound_opening(self, ref: EngineAgentRef) -> str:
        """The agent's greeting as the engine holds it, which the publish read-back verified.

        `purpose` is required and spoken first on an outbound call (place-call.md:66-72), so
        it carries the same opening line the agent greets inbound callers with (D-669).
        Read per dial: a cached copy would speak a superseded disclosure after a republish.
        Any failure here is before `POST /calls`, so it is reported as not placed.
        """
        try:
            data = await self._request("GET", f"/agents/{ref}", route="/agents/{ref}")
        except ProblemError as exc:
            raise _dial_precondition_failed(missing="published agent") from exc
        greeting = _str(data.get("greeting"))
        if greeting is None or not greeting.strip():
            raise _dial_precondition_failed(missing="agent's opening line")
        return self._within(
            greeting.strip(), PURPOSE_MAX_CHARS, code="engine_greeting_too_long", what="opening"
        )

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """`POST /calls` (place-call.md).

        Not sent, deliberately: `retry` (our campaign ladder owns retries), `callingHours`
        (our compliance gate owns the window; their 09:00-21:00 check runs regardless,
        place-call.md:103-113), `extract`/`summary` (our own extraction is the record).
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
        purpose = await self._outbound_opening(ref)
        body: dict[str, Any] = {
            "to": to,
            "purpose": purpose,
            "agent": ref,
            "ifOutsideHours": "refuse",
        }
        if ctx.from_e164:
            body["from"] = ctx.from_e164
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
                json=body,
                headers=headers,
                # Every 409 on this route is a call that was not placed: outside hours, a
                # call already waiting or live for this person, no answering agent, a number
                # without carrier credentials, or the same key in flight
                # (place-call.md:272-286).
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
        return handle

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
            report = await self._request("DELETE", f"/calls/{call_id}", route="/calls/{id}")
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
    # Renting a number and attaching it to an agent are console steps
    # (voices-and-models.md:85-87), so every write refuses by name.

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
        calling out (:84-86)."""
        numbers: list[ProvisionedNumber] = []
        rows, reason, _ = await self._walk("/phone-numbers", route="/phone-numbers")
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
                    engine_number_ref=raw,
                    engine_owned=row.get("source") == "rented",
                    answering_agent_ref=_str(row.get("agent")),
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
        data = await self._request(
            "POST",
            f"/agents/{ref}/knowledge",
            route="/agents/{ref}/knowledge",
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
        for handle in handles:
            try:
                await self._request(
                    "DELETE",
                    f"/agents/{ref}/knowledge/{handle}",
                    route="/agents/{ref}/knowledge/{kb}",
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
        handles = _parts_of(kb)
        absent: EngineRejectedError | None = None
        failure: Exception | None = None
        removed = 0
        for handle in handles:
            try:
                await self._request(
                    "DELETE",
                    f"/agents/{ref}/knowledge/{handle}",
                    route="/agents/{ref}/knowledge/{kb}",
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
        rows, reason, _ = await self._walk(
            f"/agents/{ref}/knowledge", route="/agents/{ref}/knowledge"
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
        no account-level list to ask. A failure on one agent makes the answer incomplete."""
        objects: list[AccountKBObject] = []
        agents, reason, pages = await self._walk("/agents", route="/agents")
        for row in agents:
            raw = _str(row.get("id"))
            if raw is None:
                continue
            try:
                handles = await self.list_kb(raw)
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
        """`GET /voices` in our own workspace: every voice, with its price band. Not paged;
        Studio voices and our clones (`mine: true`) are listed on the Pro plan and above only,
        so a lower plan answers standard and premium voices and no Studio ones; "every voice
        speaks every supported language" (snapshots/2026-10-07b/pages/api-reference/voices/
        list-voices.md:7, :346-347, :417-451). Which band may be sold is the caller's
        decision (`agents/hosted_voices.py`)."""
        data = await self._request("GET", "/voices", route="/voices")
        voices = [
            HostedVoice(
                voice_id=voice_id,
                label=label,
                source="engine",
                is_custom=row.get("mine") is True,
                language=_str(row.get("accent")),
                description=_str(row.get("description")),
                band=band,
            )
            for row in _items(data)
            if (voice_id := _str(row.get("id")))
            and (label := _str(row.get("name")))
            and (band := _VOICE_BANDS.get(str(row.get("tier")))) is not None
        ]
        return HostedVoiceListing(voices=voices)

    async def list_own_key_voices(self) -> HostedVoiceListing:
        """`GET /byok/voices`: the voices our installed voice key reaches, with the
        provider's own sample when it hosts one. `409` when the workspace is not on its own
        keys (snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys/
        list-byok-voices.md:7, :344-379, :452-485)."""
        data = await self._request("GET", "/byok/voices", route="/byok/voices")
        provider = data.get("provider")
        voices = [
            HostedVoice(
                voice_id=voice_id,
                label=label,
                source="byok",
                language=_str(row.get("language")),
                sample_url=_str(row.get("sample")),
            )
            for row in _items(data)
            if (voice_id := _str(row.get("id"))) and (label := _str(row.get("name")))
        ]
        return HostedVoiceListing(
            voices=voices,
            provider=_str(provider.get("id")) if isinstance(provider, dict) else None,
        )

    async def preview_own_key_voice(
        self, *, voice_id: str, text: str | None, language: str | None
    ) -> PreviewAudio:
        """`POST /byok/voices/preview`: one spoken line as audio, charged by the provider per
        character, so `text` is capped at 200 (snapshots/2026-10-07b/pages/api-reference/
        bring-your-own-keys/preview-byok-voice.md:7, :350-360, :442-470)."""
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
        audio, content_type = await vendor_audio_request(
            self._http(),
            "POST",
            "/byok/voices/preview",
            engine=self.name,
            route="/byok/voices/preview",
            json=body,
        )
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

    async def find_voice_clone(self, voice_id: str) -> VoiceClone | None:
        """The clone whose `voiceId` is `voice_id`, from `GET /voice-clones`, or None
        (snapshots/2026-10-07b/pages/api-reference/voice-clones/list-voice-clones.md:7)."""
        rows, reason, _ = await self._walk("/voice-clones", route="/voice-clones")
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
            "DELETE", f"/voice-clones/{quote(clone_id, safe='')}", route="/voice-clones/{id}"
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
        data = await self._request("GET", "/byok", route="/byok")
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
        (bring-your-own-keys.md:186-198)."""
        try:
            await self._request(
                "PATCH",
                "/byok",
                route="/byok",
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

    async def disable_own_voice_key(self) -> OwnVoiceKeyState:
        """`PATCH /byok {enabled: false}`, then the state as read back. Every agent on
        `byok: workspace` returns to the platform's own voices at their next call
        (bring-your-own-keys.md:186-198)."""
        await self._request("PATCH", "/byok", route="/byok", json={"enabled": False})
        return await self.own_key_state()

    async def agent_own_voice_key(self, ref: EngineAgentRef) -> bool | None:
        """The agent's `byok` as `GET /agents/{id}` holds it, as ours; None when unreported."""
        return _own_voice_key_of(
            await self._request("GET", f"/agents/{ref}", route="/agents/{ref}")
        )

    async def set_agent_own_voice_key(self, ref: EngineAgentRef, *, on: bool) -> None:
        """`PATCH /agents/{id} {byok}` alone, leaving every other field as it is. The vendor
        reads it once when a call starts, so a ringing call keeps the old value (evaluation
        §12 item 1)."""
        await self._request(
            "PATCH", f"/agents/{ref}", route="/agents/{ref}", json={"byok": _byok_value(on)}
        )

    async def list_call_charges(self, *, since: date) -> EngineChargeListing:
        """`GET /usage/calls?from=` — the billing view:
        what each call was charged, as `costMicro` (integer micro-units of `currency`, null
        when nothing was charged) (snapshots/2026-10-07/pages/api-reference/usage/
        list-call-log.md:247-300, :456-459, :533-547). `from` is a date in the workspace's
        time zone, so callers ask from a day early. Converted to rupees here as `Decimal`,
        never through a float.
        """
        charges: list[EngineCharge] = []
        other_currency = 0
        rows, reason, _pages = await self._walk(
            "/usage/calls", route="/usage/calls", params={"from": since.isoformat()}
        )
        for row in rows:
            call_id = _str(row.get("id"))
            if call_id is None:
                continue
            if (_str(row.get("currency")) or "INR") != "INR":
                other_currency += 1
                continue
            micro = row.get("costMicro")
            charged = (
                Decimal(micro) / _MICRO_PER_UNIT
                if isinstance(micro, int) and not isinstance(micro, bool)
                else None
            )
            agent = row.get("agent")
            charges.append(
                EngineCharge(
                    engine_call_id=call_id,
                    engine_agent_ref=_str(agent.get("id")) if isinstance(agent, dict) else None,
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
        (`bring-your-own-keys.md:44-63`)."""
        model_rows, model_reason, _ = await self._walk("/models", route="/models")
        models = [
            CatalogueModel(
                model_id=model_id,
                label=label,
                call_capable=row.get("voice") is True,
                plan_allows=row.get("available") is True,
                tier=_MODEL_TIERS.get(model_id),
                voice_only_byok=row.get("voiceOnlyByok") is True,
            )
            for row in model_rows
            if (model_id := _str(row.get("id"))) and (label := _str(row.get("name")))
        ]
        return EngineCatalogue(models=models, complete=model_reason is None)

    # --- reading the truth ---------------------------------------------------

    def _snapshot(self, payload: dict[str, Any], *, fallback_id: str = "") -> ExecutionSnapshot:
        """A call object (get-call.md:14-47, :110-197) as our snapshot.

        `billable_ready` waits for `analysedAt` (results final, get-call.md:190-193) and NOT for
        the recording: an inbound call's only copy of its transcript is the `call.analysed`
        delivery, which may say `ready: false` (get-call.md:170-174), and holding it back would
        lose that transcript. The link is valid before the audio lands (it answers 404 for a
        minute or so), so it is passed on and the recording copy retries.
        """
        call_id = _str(payload.get("id")) or fallback_id
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
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
        fields = payload.get("fields")
        analysed = payload.get("analysedAt") is not None or hangup == "not_placed"
        agent = _agent_ref_of(payload)
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
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """`GET /calls/{id}`; always the newest try (get-call.md:76). Takes any id the call
        list hands out, inbound calls included (snapshots/2026-10-07/pages/api-reference/
        calls/get-call.md:7); the first docs said it answered 404 for calls the API did not
        place, and `workers/engine_delivery` keeps its fallbacks for when it does."""
        payload = await self._request("GET", f"/calls/{call_id}", route="/calls/{id}")
        return self._snapshot(payload, fallback_id=call_id).model_copy(
            update={"raw_document": engine_document(payload, engine=self.name)}
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
        call has nothing to fetch.
        """
        if not self._api_key or not snapshot.engine_call_id or not snapshot.terminal:
            return None
        if snapshot.recording_url is None and snapshot.raw_status != "completed":
            return None
        host = (urlsplit(self._base_url).hostname or "").lower()
        raw = snapshot.engine_call_id
        return EngineRecordingSource(
            url=f"{self._base_url.rstrip('/')}/calls/{quote(raw, safe='')}/recording",
            rules=RecordingFetchRules(
                allowed_hosts=frozenset({host}),
                content_types=frozenset({"audio/mpeg"}),
                not_ready_status=404,
                gone_status=410,
            ),
            auth_headers={AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}"},
            auth_hosts=frozenset({host}),
        )

    def snapshot_from_delivery(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        """The snapshot a VERIFIED `call.analysed` delivery carries: "exactly the object
        above" (get-call.md:56-65), the only source of an inbound call's transcript and
        recording. Call it after `verify_webhook` has passed, never before."""
        data = payload.get("data")
        call = data if isinstance(data, dict) else {}
        return self._snapshot(call).model_copy(
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
        rows, reason, pages = await self._walk("/calls", route="/calls", params={"since": instant})
        for row in rows:
            snapshot = self._snapshot(row)
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
        ref = agent
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
            call_id=_str(call.get("id")) or "",
            engine_agent_ref=_agent_ref_of(call),
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
        None for any other event (`{id, event, sentAt, data}`, snapshots/2026-10-08/pages/
        api-reference/webhooks.md:70-99). Call it after `verify_webhook` has passed.

        UNVERIFIED: the mirror prints these two bodies as `data: { … }`. The agent is read
        the way a call object carries it (`agent: {id}`, or `agentId`), and the call from
        `callId`, the field `contact.opted_out` documents (:85); either may be absent, and
        a chat escalation has no call. Nothing else in `data` is read: the lead's name and
        number are the caller's personal data and our extraction pass is the record.
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
            engine_agent_ref=_agent_ref_of(body) or _str(body.get("agentId")),
            engine_call_id=_str(body.get("callId")),
            occurred_at=_parse_dt(payload.get("sentAt")),
            engine=self.name,
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
