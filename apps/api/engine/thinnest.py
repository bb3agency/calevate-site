"""ThinnestAI adapter: a `control_plane` engine reached over its REST API (D-678).

ThinnestAI hosts the agent and the call. We create and edit the agent over
`https://app.thinnest.ai/api/v1`, dial with `POST /calls`, and read results from their call
endpoints and signed webhooks. The plan is `docs/THINNEST-INTEGRATION.md`; every vendor fact
below cites the hash-pinned mirror `thinnest-findings/mirror/pages/` (VERIFIED-VENDOR-DOCS)
as `path:line`. No request has been made against a live ThinnestAI account from this tree.

Where the mirror is silent the value is marked UNVERIFIED at the line and the adapter either
sends nothing or refuses by name. The open items: the shape of a `call.completed` body, and
which number `from` names on an inbound call.

TWO WORKSPACES (D-687). Clear-rung agents live in our developer workspace; Studio-rung agents
live in one customer workspace whose own voice key is our Cartesia key (BYOK scope `voice`,
`thinnest-findings/mirror/snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:
13-24`). Every request inside a customer carries `Thinnest-Workspace` (`customers.md:68-89`),
and every id issued there is held by us as `<id>@<workspace>` (`calevate_shared.engine_scope`),
so a handle always says where it lives and nothing outside this package needs to know.

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
from calevate_shared.engine_scope import scoped_handle, split_handle
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
from apps.api.engine.catalogue import (
    CatalogueModel,
    EngineCatalogue,
    HostedVoice,
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
# webhooks.md:37-39, get-call.md:68-69: HMAC-SHA256 of the raw body under the endpoint's
# `signingSecret`, sent as `sha256=<hex>` (mcp/own-database.md:75-86 prints the verifier).
SIGNATURE_HEADER: Final = "x-thinnest-signature"
IDEMPOTENCY_HEADER: Final = "Idempotency-Key"
# customers.md:68-91: any request runs inside the customer this header names.
WORKSPACE_HEADER: Final = "Thinnest-Workspace"

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

#: Logged when the LLM key slot refuses: no language-model key of ours is installed on this
#: engine. Only the VOICE key is ours, and only in the Studio workspace (D-687).
LLM_KEY_NOT_INSTALLED: Final = "llm_key_not_installed"

#: `GET /voices` `tier` of the voices sold on this engine, as the Clear rung (D-687). Studio
#: voices and the account's own clones carry it (snapshots/2026-10-07b/pages/api-reference/
#: voices/list-voices.md:7, :441-447; channels/voice-clone.md:10-12).
SOLD_VOICE_TIER: Final = "studio"

# Capability profile. Each line's evidence:
# * stt/tts/llm `engine`: the engine dictates every leg. Voices and models are chosen from
#   what it hosts (`GET /voices`, `GET /models`, and in the Studio workspace the voices of
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


def _clone_refusal(exc: EngineRejectedError) -> ProblemError:
    """`POST /voice-clones`' documented refusals in our words (create-voice-clone.md:
    384-460): `400` the recording or a field, `403` the plan, `409` the clone limit."""
    if exc.vendor_status == 403:
        return _business_refusal(
            "voice_clone_not_on_plan",
            title="Voice cloning is not on the voice platform's plan",
            detail="The voice platform account's plan does not include cloning.",
            remediation="Upgrade the voice platform account to Pro or above.",
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
        studio_workspace: Callable[[], str | None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client
        self._signing_secret_for = signing_secret_for
        #: The customer workspace Studio agents live in, read per use because an operator
        #: sets it in the console while the process runs (`Settings.thinnest_studio_workspace_id`).
        self._studio_workspace = studio_workspace or (lambda: None)
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
            # No default `Content-Type`: `json=` sets it per request, and a client-wide one
            # would override the boundary of the one multipart upload (`create_voice_clone`).
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}"},
            )
        return self._client

    @staticmethod
    def _workspace_headers(workspace: str | None, headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(headers or {})
        if workspace:
            merged[WORKSPACE_HEADER] = workspace
        return merged

    async def _request(
        self,
        method: str,
        path: str,
        *,
        route: str,
        workspace: str | None = None,
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
            headers=self._workspace_headers(workspace, headers),
            **kwargs,
        )

    def _workspaces(self) -> tuple[str | None, ...]:
        """Every workspace our agents live in: ours, and the Studio one when it is set."""
        studio = self._studio_workspace()
        return (None, studio) if studio else (None,)

    async def _walk(
        self,
        path: str,
        *,
        route: str,
        params: dict[str, Any] | None = None,
        workspace: str | None = None,
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
                "GET", path, route=route, params=query, workspace=workspace
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
        if cfg.engine_voice_id and cfg.engine_byok_voice_id:
            raise _business_refusal(
                "engine_voice_choice_conflict",
                title="This agent names two voices",
                detail="An agent speaks either a voice of the platform or a voice of our own "
                "voice provider, never both.",
                remediation="Choose one voice for the agent, then publish again.",
            )
        # A voice of our own voice key is not set here: it goes to `PUT /agents/{id}/byok-voice`
        # after the write (`_apply_own_key_voice`).
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

    async def _find_agent(self, cfg: AgentConfig) -> str | None:
        """The vendor id of an agent this adapter already made for `cfg` in its workspace,
        found by its name tag."""
        tag = _name_tag(cfg)
        rows, reason, _ = await self._walk(
            "/agents", route="/agents", workspace=cfg.engine_workspace
        )
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
                workspace=cfg.engine_workspace,
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
        workspace = cfg.engine_workspace
        raw = await self._find_agent(cfg)
        if raw is not None:
            await self._request(
                "PATCH", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace, json=body
            )
        else:
            data = await self._request(
                "POST", "/agents", route="/agents", workspace=workspace, json=body
            )
            raw = _str(data.get("id"))
            if raw is None:
                raise _bad_response("The voice platform did not return an agent id.")
        await self._apply_own_key_voice(raw, cfg)
        return scoped_handle(raw, workspace)

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        raw, workspace = split_handle(ref)
        if workspace != cfg.engine_workspace:
            # An agent cannot move between workspaces (evaluation §10 item 2b, VENDOR-STATED):
            # the publish path re-creates it instead, and reaching here is that path's bug.
            raise _business_refusal(
                "engine_agent_workspace_mismatch",
                title="This agent lives in another part of the voice platform",
                detail="The agent's voice needs it to run elsewhere on the voice platform, "
                "and an agent cannot be moved there.",
                remediation="Publish the agent again. If it keeps failing, contact us.",
            )
        await self._request(
            "PATCH",
            f"/agents/{raw}",
            route="/agents/{ref}",
            workspace=workspace,
            json=self._agent_body(cfg),
        )
        await self._apply_own_key_voice(raw, cfg)

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
        raw, workspace = split_handle(ref)
        await self._request(
            "PATCH", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace, json=body
        )

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """`GET /agents/{id}` (agents.md:80), with the agent's documents from its knowledge
        list: documents are agent-scoped here, so that list IS what the agent references."""
        raw, workspace = split_handle(ref)
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
        raw, workspace = split_handle(ref)
        await self._request(
            "DELETE",
            f"/agents/{raw}",
            route="/agents/{ref}",
            workspace=workspace,
            absent_is_success=True,
        )

    # --- calls ---------------------------------------------------------------

    async def _outbound_opening(self, ref: EngineAgentRef) -> str:
        """The agent's greeting as the engine holds it, which the publish read-back verified.

        `purpose` is required and spoken first on an outbound call (place-call.md:66-72), so
        it carries the same opening line the agent greets inbound callers with (D-669).
        Read per dial: a cached copy would speak a superseded disclosure after a republish.
        Any failure here is before `POST /calls`, so it is reported as not placed.
        """
        raw, workspace = split_handle(ref)
        try:
            data = await self._request(
                "GET", f"/agents/{raw}", route="/agents/{ref}", workspace=workspace
            )
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
        raw_agent, workspace = split_handle(ref)
        body: dict[str, Any] = {
            "to": to,
            "purpose": purpose,
            "agent": raw_agent,
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
                workspace=workspace,
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
        return scoped_handle(handle, workspace)

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
        raw_call, workspace = split_handle(call_id)
        try:
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
    # Renting a number and attaching it to an agent are console steps
    # (voices-and-models.md:85-87), so every write refuses by name.

    async def search_numbers(self, query: NumberSearch) -> Sequence[AvailableNumber]:
        raise engine_lacks("numbers", engine=self.name)

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        raise engine_lacks("numbers", engine=self.name)

    async def release_number(self, number: ProvisionedNumber) -> None:
        raise engine_lacks("numbers", engine=self.name)

    async def list_engine_numbers(self) -> Sequence[ProvisionedNumber]:
        """`GET /phone-numbers` (voices-and-models.md:67-87) in every workspace our agents
        live in. The number string is the engine's handle for it (it is what `from` takes).
        `rented` is a number we pay ThinnestAI for; `brought` is one on our own carrier
        account. `agent` is the agent answering it, or null while unassigned or lent only for
        calling out (:84-86)."""
        numbers: list[ProvisionedNumber] = []
        for workspace in self._workspaces():
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
                agent = _str(row.get("agent"))
                numbers.append(
                    ProvisionedNumber(
                        e164=e164,
                        provider=_str(row.get("provider")),
                        engine_number_ref=raw,
                        engine_owned=row.get("source") == "rented",
                        answering_agent_ref=(
                            scoped_handle(agent, workspace) if agent is not None else None
                        ),
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
        that for the VOICE leg only, in the Studio workspace (`install_own_voice_key`, D-687):
        a voice-only workspace runs on their speech-to-text and their model (:13-17). No
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
            f"/agents/{split_handle(ref)[0]}/knowledge",
            route="/agents/{ref}/knowledge",
            workspace=split_handle(ref)[1],
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
                    f"/agents/{split_handle(ref)[0]}/knowledge/{handle}",
                    route="/agents/{ref}/knowledge/{kb}",
                    workspace=split_handle(ref)[1],
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
                    f"/agents/{split_handle(ref)[0]}/knowledge/{handle}",
                    route="/agents/{ref}/knowledge/{kb}",
                    workspace=split_handle(ref)[1],
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
        raw, workspace = split_handle(ref)
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
        no account-level list to ask. A failure on one agent makes the answer incomplete."""
        objects: list[AccountKBObject] = []
        reason: ListingIncompleteReason | None = None
        pages = 0
        for workspace in self._workspaces():
            agents, listed, walked = await self._walk(
                "/agents", route="/agents", workspace=workspace
            )
            reason = reason or listed
            pages += walked
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
    # The voices this engine speaks are its own (`GET /voices`), and in the Studio workspace
    # the voices of the voice key we installed there (`GET /byok/voices`). Which of them a
    # client may choose is an operator's decision, kept in `platform_voice_catalog` and
    # synced by `agents/hosted_voices.py`; nothing here decides it.

    async def list_voices(self) -> EngineVoiceListing:
        """Refuses: this engine speaks the voices it hosts, not ours (`list_hosted_voices`)."""
        raise engine_lacks("tts", engine=self.name)

    async def list_hosted_voices(self) -> HostedVoiceListing:
        """`GET /voices` in our own workspace, keeping only the band we sell (`tier:
        studio`). Not paged; Studio voices and our clones (`mine: true`) are listed on the Pro
        plan and above, and "every voice speaks every supported language"
        (snapshots/2026-10-07b/pages/api-reference/voices/list-voices.md:7, :346-347,
        :417-451)."""
        data = await self._request("GET", "/voices", route="/voices")
        voices = [
            HostedVoice(
                voice_id=voice_id,
                label=label,
                source="engine",
                is_custom=row.get("mine") is True,
                language=_str(row.get("accent")),
                description=_str(row.get("description")),
            )
            for row in _items(data)
            if (voice_id := _str(row.get("id")))
            and (label := _str(row.get("name")))
            and row.get("tier") == SOLD_VOICE_TIER
        ]
        return HostedVoiceListing(voices=voices)

    async def list_own_key_voices(self, *, workspace: str) -> HostedVoiceListing:
        """`GET /byok/voices` inside `workspace`: the voices our installed voice key reaches,
        with the provider's own sample when it hosts one. `409` when the workspace is not on
        its own keys (snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys/
        list-byok-voices.md:7, :344-379, :452-485)."""
        data = await self._request("GET", "/byok/voices", route="/byok/voices", workspace=workspace)
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
        self, *, workspace: str, voice_id: str, text: str | None, language: str | None
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
            headers=self._workspace_headers(workspace, None),
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
        """`POST /voice-clones`, multipart, in our own workspace (Clear agents live there).
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

    # --- own keys (BYOK) and workspaces ---------------------------------------

    async def own_keys_in_use(self) -> bool:
        """`GET /byok` in our own workspace: do calls there run on our own keys? `using` is
        `own`, `developer` (a customer on its developer's keys) or `none`
        (snapshots/2026-10-07/pages/api-reference/bring-your-own-keys/get-byok-status.md:
        247-350). A body without a readable `using` is refused rather than read as "no",
        because the answer decides which rate a publish stamps."""
        return (await self.own_key_state(workspace=None)).using != "none"

    async def own_key_state(self, *, workspace: str | None) -> OwnVoiceKeyState:
        """`GET /byok` in `workspace` (snapshots/2026-10-07b/pages/api-reference/
        bring-your-own-keys.md:115-147)."""
        data = await self._request("GET", "/byok", route="/byok", workspace=workspace)
        return _key_state(data)

    async def install_own_voice_key(
        self, *, workspace: str, provider: str, api_key: str, model: str | None
    ) -> None:
        """`PUT /byok/credentials` with `kind: tts` inside `workspace`. The provider checks
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
                workspace=workspace,
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

    async def enable_own_voice_key(self, *, workspace: str) -> OwnVoiceKeyState:
        """`PATCH /byok {enabled: true, scope: "voice"}` inside `workspace`, then the state
        as read back. `409` until the voice key is added, checked and has a model
        (bring-your-own-keys.md:186-198)."""
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
        return await self.own_key_state(workspace=workspace)

    async def create_workspace(self, *, name: str, external_id: str) -> str:
        """`POST /customers` from our own workspace, idempotent twice over: the
        `Idempotency-Key` returns the same customer on a retry, and a `409` on `externalId`
        (one we made earlier) is answered by finding it (customers.md:18-66, :93-102)."""
        try:
            data = await self._request(
                "POST",
                "/customers",
                route="/customers",
                json={"name": name, "externalId": external_id},
                headers={IDEMPOTENCY_HEADER: f"calevate-workspace-{external_id}"},
                extra_refused_statuses=frozenset({402, 409}),
            )
        except EngineRejectedError as exc:
            if exc.vendor_status == 402:
                raise _business_refusal(
                    "engine_workspace_limit_reached",
                    title="The voice platform's plan allows no more workspaces",
                    detail="The voice platform account has reached its plan's customer limit.",
                    remediation="Raise the limit with the voice platform, then try again.",
                ) from exc
            if exc.vendor_status != 409:
                raise
            rows, _, _ = await self._walk(
                "/customers", route="/customers", params={"externalId": external_id}
            )
            found = next((ref for row in rows if (ref := _str(row.get("id")))), None)
            if found is None:
                raise
            return found
        workspace = _str(data.get("id"))
        if workspace is None:
            raise _bad_response("The voice platform did not return a workspace id.")
        return workspace

    async def list_call_charges(self, *, since: date) -> EngineChargeListing:
        """`GET /usage/calls?from=` in every workspace our agents live in — the billing view:
        what each call was charged, as `costMicro` (integer micro-units of `currency`, null
        when nothing was charged) (snapshots/2026-10-07/pages/api-reference/usage/
        list-call-log.md:247-300, :456-459, :533-547). `from` is a date in the workspace's
        time zone, so callers ask from a day early. Converted to rupees here as `Decimal`,
        never through a float.
        """
        charges: list[EngineCharge] = []
        other_currency = 0
        complete = True
        for workspace in self._workspaces():
            rows, reason, _pages = await self._walk(
                "/usage/calls",
                route="/usage/calls",
                params={"from": since.isoformat()},
                workspace=workspace,
            )
            complete = complete and reason is None
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
                agent_id = _str(agent.get("id")) if isinstance(agent, dict) else None
                charges.append(
                    EngineCharge(
                        engine_call_id=scoped_handle(call_id, workspace),
                        engine_agent_ref=(
                            scoped_handle(agent_id, workspace) if agent_id is not None else None
                        ),
                        charged_inr=charged,
                    )
                )
        return EngineChargeListing(
            charges=charges,
            complete=complete and other_currency == 0,
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

    def _snapshot(
        self, payload: dict[str, Any], *, fallback_id: str = "", workspace: str | None = None
    ) -> ExecutionSnapshot:
        """A call object (get-call.md:14-47, :110-197) as our snapshot, its call and agent ids
        scoped to the workspace it was read in.

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
        call_id = scoped_handle(call_id, workspace) if call_id else call_id
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
        fields = payload.get("fields")
        analysed = payload.get("analysedAt") is not None or hangup == "not_placed"
        agent = _agent_ref_of(payload)
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=scoped_handle(agent, workspace) if agent is not None else None,
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
        raw, workspace = split_handle(call_id)
        payload = await self._request(
            "GET", f"/calls/{raw}", route="/calls/{id}", workspace=workspace
        )
        return self._snapshot(payload, fallback_id=raw, workspace=workspace).model_copy(
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
        raw, workspace = split_handle(snapshot.engine_call_id)
        return EngineRecordingSource(
            url=f"{self._base_url.rstrip('/')}/calls/{quote(raw, safe='')}/recording",
            rules=RecordingFetchRules(
                allowed_hosts=frozenset({host}),
                content_types=frozenset({"audio/mpeg"}),
                not_ready_status=404,
                gone_status=410,
            ),
            auth_headers=self._workspace_headers(
                workspace, {AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}"}
            ),
            auth_hosts=frozenset({host}),
        )

    def snapshot_from_delivery(
        self, payload: dict[str, Any], *, workspace: str | None = None
    ) -> ExecutionSnapshot:
        """The snapshot a VERIFIED `call.analysed` delivery carries: "exactly the object
        above" (get-call.md:56-65), the only source of an inbound call's transcript and
        recording. Call it after `verify_webhook` has passed, never before. `workspace` is the
        one the delivering endpoint lives in, which the receiver knows from the agent handle
        its url names; without it, the body's own `workspaceId` is read (`_delivery_workspace`)."""
        data = payload.get("data")
        call = data if isinstance(data, dict) else {}
        return self._snapshot(
            call, workspace=workspace or self._delivery_workspace(call)
        ).model_copy(update={"raw_document": engine_document(call, engine=self.name)})

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
        pages = 0
        for workspace in self._workspaces():
            rows, listed, walked = await self._walk(
                "/calls", route="/calls", params={"since": instant}, workspace=workspace
            )
            reason = reason or listed
            pages += walked
            for row in rows:
                snapshot = self._snapshot(row, workspace=workspace)
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

    def _delivery_workspace(self, call: dict[str, Any]) -> str | None:
        """The Studio workspace when a delivery names it in `data.workspaceId`, else None.

        `workspaceId` is documented on deliveries to an `includeCustomers` endpoint
        (snapshots/2026-10-07b/pages/api-reference/webhooks.md:62-66); whether a per-agent
        endpoint inside a customer carries it is UNKNOWN, which is why voice-runtime scopes a
        delivery from the agent handle in its url and passes it in instead. Only a workspace
        our agents live in is honoured; any other value is read as our own."""
        named = _str(call.get("workspaceId"))
        return named if named is not None and named in self._workspaces() else None

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
        agent = _agent_ref_of(data) if isinstance(data, dict) else None
        ref = (
            scoped_handle(agent, self._delivery_workspace(data))
            if agent is not None and isinstance(data, dict)
            else None
        )
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
        workspace = self._delivery_workspace(call)
        call_id = _str(call.get("id"))
        agent = _agent_ref_of(call)
        return CallEvent(
            call_id=scoped_handle(call_id, workspace) if call_id is not None else "",
            engine_agent_ref=scoped_handle(agent, workspace) if agent is not None else None,
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
    "LLM_KEY_NOT_INSTALLED",
    "SIGNATURE_HEADER",
    "SOLD_VOICE_TIER",
    "THINNEST_CAPABILITIES",
    "WORKSPACE_HEADER",
    "SigningSecretResolver",
    "ThinnestEngine",
    "parse_transcript",
    "vendor_agent_name",
]
