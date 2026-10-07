"""ThinnestAI adapter: a `control_plane` engine reached over its REST API (D-678).

ThinnestAI hosts the agent and the call. We create and edit the agent over
`https://app.thinnest.ai/api/v1`, dial with `POST /calls`, and read results from their call
endpoints and signed webhooks. The plan is `docs/THINNEST-INTEGRATION.md`; every vendor fact
below cites the hash-pinned mirror `thinnest-findings/mirror/pages/` (VERIFIED-VENDOR-DOCS)
as `path:line`. No request has been made against a live ThinnestAI account from this tree.

Where the mirror is silent the value is marked UNVERIFIED at the line and the adapter either
sends nothing or refuses by name. The open items: BYOK through the API (`set_llm_credential`;
BYOK exists only in their console, see there), the shape of a `call.completed` body, and
which number `from` names on an inbound call.

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
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final
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
from calevate_shared.events import CallDirection, CallEvent, CallStatus, Speaker, TranscriptTurn
from calevate_shared.webhook_signature import sha256_signature_matches

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
from apps.api.engine.catalogue import CatalogueModel, CatalogueVoice, EngineCatalogue
from apps.api.engine.charges import EngineCharge, EngineChargeListing
from apps.api.engine.document import engine_document
from apps.api.engine.recording_source import EngineRecordingSource, RecordingFetchRules
from apps.api.engine.text_split import split_for_text_cap
from apps.api.engine.vendor_http import (
    REQUEST_TIMEOUT_S,
    EngineRejectedError,
    recipient_opted_out_error,
    vendor_request,
)

log = get_logger(__name__)

# api-reference/introduction.md:24-28; authentication.md:10 (`Authorization: Bearer ta_live_…`).
BASE_URL: Final = "https://app.thinnest.ai/api/v1"
AUTH_HEADER: Final = "Authorization"
AUTH_SCHEME: Final = "Bearer"
# webhooks.md:37-39, get-call.md:68-69: HMAC-SHA256 of the raw body under the endpoint's
# `signingSecret`, sent as `sha256=<hex>` (mcp/own-database.md:75-86 prints the verifier).
SIGNATURE_HEADER: Final = "x-thinnest-signature"
IDEMPOTENCY_HEADER: Final = "Idempotency-Key"

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
#: `costMicro` is integer micro-units: 1,000,000 is one rupee
#: (snapshots/2026-10-07/pages/api-reference/usage/list-call-log.md:533-540).
_MICRO_PER_UNIT: Final = Decimal(1_000_000)

# Language values the mirror actually prints: `"auto"` plus "a language the console
# offers — "Hindi", "English", "Tamil"…" (agents.md:120-123) and "Marathi"
# (channels/voice.md:198-201). "Telugu" is the console's exact option (FOUNDER-RELAYED console
# reading, 6 Oct 2026; its "Match the customer" is the API's `auto`). A tag outside this map is
# sent as `auto` (follow the caller).
_AUTO_LANGUAGE: Final = "auto"
_DOCUMENTED_LANGUAGES: Final[dict[str, str]] = {
    "hi": "Hindi",
    "en": "English",
    "ta": "Tamil",
    "mr": "Marathi",
    "te": "Telugu",
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

#: The call id the key-level probe cancels. Not an id the vendor issues (theirs are `out_…`,
#: `sch_…` or a call reference, snapshots/2026-10-07/pages/api-reference/calls/
#: get-call.md:7), so it can only ever answer 403 or 404.
_KEY_PROBE_CALL_ID: Final = "cv-key-scope-probe"

#: Logged when the BYOK slot refuses. BYOK is a workspace setting in their console only
#: (`/settings/byok`); `set_llm_credential` is the one place that changes if an API lands.
BYOK_NOT_DOCUMENTED: Final = "byok_not_documented"

# Capability profile. Each line's evidence:
# * stt/tts/llm `engine`: models and voices come from their catalogue (`GET /models`,
#   `GET /voices`, voices-and-models.md:9-65); no key of ours reaches a call through the API
#   (BYOK is console-only and workspace-wide; `Settings.thinnest_byok_enabled`).
# * `control_plane`: agents are created, read, edited and deleted over REST (agents.md:74-82)
#   and `GET /agents/{id}` returns `instructions` and `greeting` for the read-back.
# * `records_audio`: we send `recordCalls: true` (agents.md:160) and phone calls are
#   recorded on every number (channels/voice.md:426-438).
# * `knowledge_base`: agent-scoped text documents (knowledge.md:38-52).
# * `number_series` empty, `inbound_binding` False: renting and attaching a number are done
#   in their console (voices-and-models.md:85-87; agents.md:167-168).
# * `caller_id` True: `from` names which of the agent's numbers rings, and a number that is
#   not the agent's is refused rather than swapped (place-call.md:178-192, :260-263).
# * `transfer` and `in_call_handoff` False: "The agent cannot put a caller through to a
#   person" (channels/voice.md:420-424).
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
    in_call_handoff=False,
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


def _language_fields(cfg: AgentConfig) -> dict[str, str | None]:
    primary = _DOCUMENTED_LANGUAGES.get(cfg.language_primary.split("-")[0].lower())
    if primary is None:
        # `secondLanguage` is ignored under `auto` (agents.md:125-128); null clears a stale one.
        return {"language": _AUTO_LANGUAGE, "secondLanguage": None}
    extras = [
        name
        for tag in cfg.languages_extra
        if (name := _DOCUMENTED_LANGUAGES.get(tag.split("-")[0].lower())) and name != primary
    ]
    return {"language": primary, "secondLanguage": extras[0] if extras else None}


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
        #: Whether this key may place calls, learned once (a key's level never changes,
        #: `authentication.md:29-31`). None until a 403 makes the question matter.
        self._key_places_calls: bool | None = None

    def holds_credentials(self) -> bool:
        return bool(self._api_key) or self._client is not None

    # --- plumbing ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{self.name}")
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={
                    AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}",
                    "Content-Type": "application/json",
                },
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
            **kwargs,
        )

    async def _walk(
        self, path: str, *, route: str, params: dict[str, Any] | None = None
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
        if cfg.caller_memory_enabled:
            # The memory slot is per-call data and agent state here is shared by every
            # caller, so the facts have nowhere to ride; their own cross-channel memory is
            # switched off (`pastConversations: "fresh"`) because it remembers without the
            # notice D-507 requires.
            raise _business_refusal(
                "engine_caller_memory_unsupported",
                title="Caller memory is not available on this voice platform",
                detail=(
                    "This agent is set to remember its callers, and the voice platform in use "
                    "cannot be given what it remembers."
                ),
                remediation="Switch caller memory off for this agent, then publish again.",
            )

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
        # agents.md:152-169. `detectMachines` off (plan §2). `summariseCalls` off and
        # `collectFields` empty: our own extraction pass is the record, and theirs is
        # billed per call (get-call.md:199-204). `pastConversations: fresh`: see
        # `_refuse_what_this_engine_cannot_carry`.
        voice: dict[str, Any] = {
            "recordCalls": True,
            "maxCallSeconds": seconds,
            "detectMachines": False,
            "summariseCalls": False,
            "pastConversations": "fresh",
        }
        # Ids from `GET /voices` and `GET /models` (voices-and-models.md:9-10; agents.md:105,
        # :156), checked against the catalogue before publish (`agents/engine_choice.py`).
        # None sends nothing, so the agent keeps the engine's default. UNVERIFIED: no value is
        # documented that resets a previously set `voice.voice` or `model` to the default —
        # the request schema types both as a plain string (snapshots/2026-10-07/pages/
        # api-reference/agents/update-agent.md:442-450, :731-735); the `null`s at :552-558
        # and :931-934 are the RESPONSE describing a retired model or an absent voice
        # channel. So clearing a choice leaves the last one sent in place on their side.
        if cfg.engine_voice_id:
            voice["voice"] = cfg.engine_voice_id
        body: dict[str, Any] = {
            "name": vendor_agent_name(cfg),
            "instructions": instructions,
            "greeting": greeting,
            **_language_fields(cfg),
            "voice": voice,
            # Stated, not left to the defaults (agents.md:43-45): the vendor's own call-back
            # would ring the caller from their side, outside our dial gate and our DNC list,
            # and its escalation promises "a person will follow up" that nobody here
            # receives. Our call-back and handoff are in-call actions
            # (`reliability/engine_actions.py`).
            "scheduleCallbacks": False,
            "escalation": {"onNoAnswer": False, "onRequest": False},
            "collectFields": [],
        }
        if cfg.engine_model_id:
            body["model"] = cfg.engine_model_id
        return body

    async def _find_agent(self, cfg: AgentConfig) -> EngineAgentRef | None:
        """An agent this adapter already made for `cfg`, found by its name tag."""
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

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        body = self._agent_body(cfg)
        existing = await self._find_agent(cfg)
        if existing is not None:
            await self._request("PATCH", f"/agents/{existing}", route="/agents/{ref}", json=body)
            return existing
        data = await self._request("POST", "/agents", route="/agents", json=body)
        ref = _str(data.get("id"))
        if ref is None:
            raise _bad_response("The voice platform did not return an agent id.")
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await self._request(
            "PATCH", f"/agents/{ref}", route="/agents/{ref}", json=self._agent_body(cfg)
        )

    async def override_call_script(
        self, ref: EngineAgentRef, *, opening_line: str, system_prompt: str
    ) -> None:
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
            # The shortest call the vendor allows (60 s) while the agent can only say it
            # cannot take the call: every minute here is billed to us by ThinnestAI and to
            # nobody by us, since a script override runs when a wallet is empty or the
            # platform is in maintenance. `voice` takes any subset, so the rest of the
            # agent's call settings are untouched (snapshots/2026-10-07/pages/api-reference/
            # agents/update-agent.md:725), and the restoring publish sends the agent's own
            # cap back.
            "voice": {"maxCallSeconds": CALL_SECONDS_MIN},
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
        return AgentSnapshot(
            engine_agent_ref=ref,
            name=_our_name(_str(data.get("name"))),
            system_prompt=instructions if isinstance(instructions, str) else None,
            system_prompt_readable=isinstance(instructions, str),
            greeting=greeting if isinstance(greeting, str) else "",
            greeting_readable=greeting_readable,
            knowledge_base_refs=await self.list_kb(ref),
            knowledge_base_refs_readable=True,
            engine=self.name,
        )

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
            if exc.vendor_status == 402:
                alert(
                    "CORE_LOGIC",
                    "engine_balance_exhausted",
                    detail="ThinnestAI refused a dial because the workspace balance cannot "
                    "pay for a call; no call is placed until it is topped up",
                )
            # 403 is the person (opted out, or on the workspace's do-not-call list) OR a key
            # that is not a full key (snapshots/2026-10-07/pages/api-reference/calls/
            # place-call.md:390-410), told apart only by the message, which the ladder does
            # not hand back. The key is asked once; only a full key's 403 is the person's.
            if exc.vendor_status == 403 and await self._key_places_calls_probe():
                raise recipient_opted_out_error() from exc
            raise
        handle = _str(data.get("id"))
        if handle is None:
            raise _bad_response("The voice platform did not return a call id.")
        if data.get("status") == "scheduled":
            log.warning("thinnest_call_scheduled_not_placed", extra={"engine_call_id": handle})
        return handle

    async def _key_places_calls_probe(self) -> bool:
        """May this API key place calls? Answered by cancelling a call id that cannot exist:
        a key without call rights is refused `403`, a full key is told `404` "no call you
        placed with that id" (snapshots/2026-10-07/pages/api-reference/calls/
        cancel-call.md:336-347). Cached once known, since a key's level never changes.

        UNVERIFIED: that the vendor checks the key's level before looking the id up. Any
        answer other than those two is not cached and reads as "not proven", so a 403 is
        never taken as the person's on a guess — the dial is refunded instead.
        """
        if self._key_places_calls is not None:
            return self._key_places_calls
        try:
            await self._request("DELETE", f"/calls/{_KEY_PROBE_CALL_ID}", route="/calls/{id}")
        except EngineRejectedError as exc:
            if exc.vendor_status in (403, 404):
                self._key_places_calls = exc.vendor_status == 404
                if not self._key_places_calls:
                    alert(
                        "CORE_LOGIC",
                        "engine_key_cannot_place_calls",
                        detail="the ThinnestAI API key is not a full key, so every dial "
                        "is refused; set THINNEST_API_KEY to a full-access key",
                    )
                return self._key_places_calls
            return False
        except ProblemError:
            return False
        return False

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
        engine's handle for it (it is what `from` takes). `rented` is a number we pay
        ThinnestAI for; `brought` is one on our own carrier account. `agent` is the agent
        answering it, or null while unassigned or lent only for calling out (:84-86)."""
        rows, reason, _ = await self._walk("/phone-numbers", route="/phone-numbers")
        if reason is not None:
            log.warning("thinnest_number_listing_incomplete", extra={"reason": reason})
        numbers: list[ProvisionedNumber] = []
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
        """THE BYOK SLOT. ThinnestAI's BYOK is a WORKSPACE setting made in their console at
        Settings → Your keys (`/settings/byok`), all three legs (speech-to-text, language
        model, voice) each with a model, and it has no API field (FOUNDER-RELAYED console
        reading, 6 Oct 2026; the mirror documents none). So no key of ours can be installed
        from here and this refuses on the LLM capability; an operator configures the keys in
        that console and then sets `Settings.thinnest_byok_enabled`. If an API appears, `llm`
        becomes `ours` in the descriptor and this method performs the install."""
        log.warning(BYOK_NOT_DOCUMENTED, extra={"engine": self.name, "provider": provider})
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
        agents, reason, pages = await self._walk("/agents", route="/agents")
        objects: list[AccountKBObject] = []
        for row in agents:
            ref = _str(row.get("id"))
            if ref is None:
                continue
            try:
                handles = await self.list_kb(ref)
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

    async def list_voices(self) -> EngineVoiceListing:
        """Refuses: the voices are the engine's catalogue, not ours (see `read_catalogue`)."""
        raise engine_lacks("tts", engine=self.name)

    async def own_keys_in_use(self) -> bool:
        """`GET /byok`: do calls run on the workspace's own keys right now? `using` is `own`,
        `developer` (a customer on its developer's keys) or `none`
        (snapshots/2026-10-07/pages/api-reference/bring-your-own-keys/get-byok-status.md:
        247-350). A body without a readable `using` is refused rather than read as "no",
        because the answer decides which rate a publish stamps."""
        data = await self._request("GET", "/byok", route="/byok")
        using = _str(data.get("using"))
        if using not in {"own", "developer", "none"}:
            raise _bad_response("The voice platform did not say whose keys it is using.")
        return using != "none"

    async def list_call_charges(self, *, since: date) -> EngineChargeListing:
        """`GET /usage/calls?from=` — the billing view: what each call was charged, as
        `costMicro` (integer micro-units of `currency`, null when nothing was charged)
        (snapshots/2026-10-07/pages/api-reference/usage/list-call-log.md:247-300,
        :456-459, :533-547). `from` is a date in the workspace's time zone, so callers ask
        from a day early. Converted to rupees here as `Decimal`, never through a float.
        """
        rows, reason, _pages = await self._walk(
            "/usage/calls", route="/usage/calls", params={"from": since.isoformat()}
        )
        charges: list[EngineCharge] = []
        other_currency = 0
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
        """`GET /voices` and `GET /models` (voices-and-models.md:13-65). `tier` is the price
        band a call is billed at; `mine: true` marks a cloned voice and is omitted otherwise;
        `voice` on a model says it is fast enough for calls; `available` says this plan may
        pick it."""
        voice_rows, voice_reason, _ = await self._walk("/voices", route="/voices")
        model_rows, model_reason, _ = await self._walk("/models", route="/models")
        voices = [
            CatalogueVoice(
                voice_id=voice_id, label=label, price_band=band, is_custom=row.get("mine") is True
            )
            for row in voice_rows
            if (voice_id := _str(row.get("id")))
            and (label := _str(row.get("name")))
            and (band := _str(row.get("tier")))
        ]
        models = [
            CatalogueModel(
                model_id=model_id,
                label=label,
                call_capable=row.get("voice") is True,
                plan_allows=row.get("available") is True,
                tier=_MODEL_TIERS.get(model_id),
            )
            for row in model_rows
            if (model_id := _str(row.get("id"))) and (label := _str(row.get("name")))
        ]
        return EngineCatalogue(
            voices=voices, models=models, complete=voice_reason is None and model_reason is None
        )

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
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=_agent_ref_of(payload),
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
        return EngineRecordingSource(
            url=f"{self._base_url.rstrip('/')}/calls/"
            f"{quote(snapshot.engine_call_id, safe='')}/recording",
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
        rows, reason, pages = await self._walk("/calls", route="/calls", params={"since": instant})
        snapshots: list[ExecutionSnapshot] = []
        seen: set[str] = set()
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
        """HMAC-SHA256 of the raw body under the agent's own endpoint secret.

        The agent named in the body only selects WHICH secret to check against; a sender
        naming another agent still needs that agent's secret. There is no timestamp in the
        scheme (webhooks.md:36-39), so replay protection is the inbox's dedupe.
        """
        signature = next(
            (value for key, value in headers.items() if key.lower() == SIGNATURE_HEADER), None
        )
        if not signature:
            return WebhookVerdict(ok=False, method="hmac", reason="signature_missing")
        try:
            payload = json.loads(body)
        except ValueError:
            return WebhookVerdict(ok=False, method="hmac", reason="body_unreadable")
        data = payload.get("data") if isinstance(payload, dict) else None
        ref = _agent_ref_of(data) if isinstance(data, dict) else None
        if ref is None:
            return WebhookVerdict(ok=False, method="hmac", reason="agent_unidentified")
        secret = self._signing_secret_for(ref) if self._signing_secret_for else None
        if secret is None:
            return WebhookVerdict(ok=False, method="hmac", reason="signing_secret_unavailable")
        if not sha256_signature_matches(body, signature, secret):
            return WebhookVerdict(ok=False, method="hmac", reason="signature_mismatch")
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


__all__ = [
    "BASE_URL",
    "BYOK_NOT_DOCUMENTED",
    "SIGNATURE_HEADER",
    "THINNEST_CAPABILITIES",
    "SigningSecretResolver",
    "ThinnestEngine",
    "parse_transcript",
    "vendor_agent_name",
]
