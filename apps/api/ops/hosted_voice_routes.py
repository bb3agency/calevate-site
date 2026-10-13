"""The Voices panel on an engine that HOSTS its voices (D-687) — admin realm, `ops:manage`.

    GET    /v1/ops/voices/hosted              the hosted voices (`?scope=all` for every synced
                                              one), each with state, rung and preview status
    POST   /v1/ops/voices/hosted              ADD one synced voice (audited); arrives disabled
    PATCH  /v1/ops/voices/hosted              enable | disable | archive one (audited)
    GET    /v1/ops/voices/hosted/agents       the agents set to one voice, in every account
    PATCH  /v1/ops/voices/hosted/display-name  the name clients see (audited)
    PATCH  /v1/ops/voices/hosted/person-clone  mark a cloned voice of a real person (step-up,
                                              audited; D-721)
    POST   /v1/ops/voices/hosted/clone-consent  record that person's consent (step-up, audited)
    GET    /v1/ops/voices/hosted/clone-consent/document  the signed consent (audited)
    POST   /v1/ops/voices/clones              clone a voice from a recording (step-up, audited)
    DELETE /v1/ops/voices/clones              delete one of our clones (step-up, audited)
    GET    /v1/ops/voices/hosted/preview      play any hosted voice's stored preview
    POST   /v1/ops/voices/hosted/preview      upload a preview clip for a voice (audited)
    POST   /v1/ops/voices/hosted/preview/fetch  store the platform's own preview (audited)
    GET    /v1/ops/voices/studio-voices       Studio readiness and the client workspaces on it
    POST   /v1/ops/voices/studio-voices/enable   Studio ready: switch our key on in the developer
                                              workspace, optionally one client too
                                              (step-up, audited; D-727)

The operator plays a preview from `GET /v1/ops/voices/hosted/preview`, for any hosted voice
added or not; a client plays an offered one from `GET /v1/agents/engine-catalogue/preview`.
Both read through `engine_catalogue_routes.stored_preview_response`. On an engine that does not
host voices every route here answers that it does not apply.

Voice ids travel in the body or the query, never the path: half of a catalogue id is a
vendor's alphabet.

STEP-UP ON THE CLONE AND THE STUDIO SWITCH, NOT ON CURATION. A clone carries the operator's two
legal promises about a person's voice and spends a plan slot; deleting one cannot be undone
and moves every agent on it to a standard voice (delete-voice-clone.md:7); the Studio switch
installs a credential and changes which voice every agent speaks. Adding, enabling and
previewing touch no agent and no call and are reversible in a click.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Final, Literal, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.clone_copies import forget_clone, keep_clone_sample
from apps.api.agents.engine_catalogue_routes import PREVIEW_RESPONSES, stored_preview_response
from apps.api.agents.hosted_voices import (
    MAX_AGENTS_ON_VOICE,
    CloneConsent,
    HostedVoiceRow,
    VoiceScope,
    accent_name,
    add_hosted_voice,
    agents_on_hosted_voice,
    band_not_sold,
    clone_offer_refusal,
    consent_document_key,
    count_hosted_voices,
    count_listed_bands,
    list_hosted_voices,
    live_studio_agents,
    no_sold_band_sentence,
    read_hosted_voice,
    record_clone,
    record_clone_consent,
    record_preview,
    rung_of_source,
    set_display_label,
    set_hosted_curation,
    set_person_clone,
    sold_hosted_band,
    studio_listing_workspace,
    studio_voices_ready,
    sync_hosted_voices,
    withdraw_hosted_voice,
)
from apps.api.agents.studio_voices import (
    StudioReadiness,
    prepare_studio,
    studio_readiness,
)
from apps.api.agents.voice_consent import (
    accept_document,
    keep_consent_document,
    open_consent_document,
)
from apps.api.agents.voice_curation import count_live_agents_by_engine_voice
from apps.api.agents.voices import CurationState
from apps.api.billing.plans import IST
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.disposition import attachment_disposition
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import admin_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import (
    HostedVoiceBand,
    HostsVoices,
    OwnVoiceKeyState,
    VoiceCloneSample,
)
from apps.api.engine.thinnest_workspace import in_workspace

log = get_logger(__name__)

router = APIRouter(prefix="/v1/ops/voices", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
VoiceCurator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

#: The confirmation strings (`core/stepup.py`). Fixed rather than per-voice for the clone and
#: the Studio switch, which name no voice; per-voice for the delete.
CLONE_CONFIRMATION: Final = "clone_voice"
STUDIO_ENABLE_CONFIRMATION: Final = "enable_studio_voices"


def delete_clone_confirmation(voice_id: str) -> str:
    return f"delete_voice_clone:{voice_id}"


def consent_confirmation(voice_id: str) -> str:
    """Recording a person's consent is an attestation about one voice, so the confirmation
    names it: a header captured for one voice cannot be replayed against another."""
    return f"record_voice_consent:{voice_id}"


def person_clone_confirmation(voice_id: str) -> str:
    return f"set_voice_person_clone:{voice_id}"


#: What a recording may be (create-voice-clone.md:530-536): WAV, MP3, M4A or WebM. The vendor
#: takes up to 10 MB; our API takes a request of at most `core/middleware.MAX_BODY_BYTES`
#: (2 MiB), which every upload here is held to, so the smaller bound is the one that applies
#: (a 30-second compressed or mono recording fits). The seconds (5-30) are the vendor's to
#: measure; it refuses a recording outside them.
CLONE_SAMPLE_TYPES: Final = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/x-m4a",
        "audio/m4a",
        "audio/webm",
    }
)
#: An uploaded preview is played by a browser `<audio>`; MP3 and WAV play everywhere.
_READ_CHUNK_BYTES: Final = 64 * 1024
#: `name` and `description` limits (create-voice-clone.md:537-544).
CLONE_NAME_MAX: Final = 40
CLONE_DESCRIPTION_MAX: Final = 200
#: A language tag such as `te-IN` (preview-byok-voice.md:462-465).
LANGUAGE_TAG: Final = r"^[A-Za-z]{2,3}([-_][A-Za-z]{2,4})?$"
_UPLOAD_THEN_ENABLE: Final = "Upload a preview, then enable it."
_CLONE_NOT_ON_PLAN: Final = (
    " The voice platform's plan does not yet let a clone be put on an agent."
)


PreviewSource = Literal["vendor", "upload"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CloneConsentOut(Strict):
    """The speaker's recorded consent to a cloned voice being offered (D-721)."""

    speaker_name: str
    statement: str
    consented_on: date
    #: What the consent covers; the same sentence on every record.
    scope: str
    recorded_by: str
    #: The operator's name, when it could be read.
    recorded_by_name: str | None
    recorded_at: datetime
    #: A signed document is stored with it.
    has_document: bool


class HostedVoiceAgentOut(Strict):
    tenant_id: str
    tenant_name: str
    agent_id: str
    agent_name: str
    status: str


class HostedVoiceAgentsOut(Strict):
    voice_id: str
    #: Every agent set to this voice, in every account, live ones first.
    agents: list[HostedVoiceAgentOut]


class SetDisplayLabelIn(Strict):
    voice_id: str = Field(min_length=1, max_length=255)
    #: The name clients see; null or blank goes back to the provider's own name.
    display_label: str | None = Field(default=None, max_length=60)


class SetPersonCloneIn(Strict):
    voice_id: str = Field(min_length=1, max_length=255)
    person_clone: bool


class HostedVoiceOut(Strict):
    """One hosted voice as the operator's table shows it."""

    voice_id: str
    label: str
    #: `engine` — the platform's own voice or our clone; `byok` — a voice of our Cartesia
    #: key (Studio).
    source: Literal["engine", "byok"]
    #: The rung it is sold on, or null for a voice in a band we do not sell.
    rung: Literal["clear", "studio"] | None
    #: The voice platform's own price band for one of its voices (`standard`, `premium`,
    #: `studio`); null for a Studio (own-key) voice.
    band: HostedVoiceBand | None
    #: In a band we sell. Only such a voice can be added and offered.
    sold: bool
    #: Why it cannot be added, for a voice in a band we do not sell; null otherwise.
    not_sold_reason: str | None
    is_custom: bool
    accent: str | None
    description: str | None
    language_note: str
    #: `enabled` | `disabled` | `archived`.
    state: CurationState
    #: Added by an operator: only added voices can be enabled and offered.
    added: bool
    #: Added, enabled and still listed: on the client picker (subject to its price).
    offered: bool
    synced_at: datetime
    curated_at: datetime | None
    #: When the platform stopped listing it (a deleted clone), or null.
    withdrawn_at: datetime | None
    preview_available: bool
    #: `vendor` (the platform's own clip) | `upload` (an operator's), or null.
    preview_source: PreviewSource | None
    #: Our clone: it can be deleted from here.
    deletable_clone: bool
    #: LIVE agents across every account set to this voice.
    live_agents: int
    #: The provider's own id for the voice, for an operator to copy; never shown to a client.
    vendor_id: str
    #: The provider's own name. `label` is what clients see: `display_label` when set.
    vendor_label: str
    display_label: str | None
    #: The accent or language tag (`accent`) as a person reads it.
    accent_label: str | None
    #: The provider's word for its gender, when its listing gives one.
    gender: str | None
    #: The product languages the voice is offered for.
    languages: list[str]
    #: Marked as a cloned voice of a real person (D-721).
    person_clone: bool
    clone_consent: CloneConsentOut | None
    #: Why this voice cannot be offered while it is a person's clone, or null.
    clone_blocker: str | None

    @classmethod
    def of(
        cls,
        row: HostedVoiceRow,
        *,
        engine: str,
        live_agents: int,
        admin_names: Mapping[UUID, str] | None = None,
    ) -> HostedVoiceOut:
        refusal = clone_offer_refusal(row)
        consent = row.consent
        return cls(
            vendor_id=row.vendor_id,
            vendor_label=row.vendor_label,
            display_label=row.display_label,
            accent_label=accent_name(row.accent),
            gender=row.gender,
            languages=list(row.languages),
            person_clone=row.person_clone,
            clone_consent=(
                None
                if consent is None
                else CloneConsentOut(
                    speaker_name=consent.speaker_name,
                    statement=consent.statement,
                    consented_on=consent.given_on,
                    scope=consent.scope,
                    recorded_by=str(consent.recorded_by),
                    recorded_by_name=(admin_names or {}).get(consent.recorded_by),
                    recorded_at=consent.recorded_at,
                    has_document=consent.has_document,
                )
            ),
            clone_blocker=None if refusal is None else refusal.title,
            voice_id=row.voice_id,
            label=row.label,
            source=row.source,
            rung=rung_of_source(engine, row.source) if row.sold else None,
            band=row.band,
            sold=row.sold,
            not_sold_reason=None if row.sold else band_not_sold(row).detail,
            is_custom=row.is_custom,
            accent=row.accent,
            description=row.description,
            language_note=row.language_note,
            state=row.state,
            added=row.added,
            offered=row.offered,
            synced_at=row.synced_at,
            curated_at=row.curated_at,
            withdrawn_at=row.withdrawn_at,
            preview_available=row.preview_available,
            # The CHECK `ck_platform_voice_catalog_preview_source` holds the vocabulary.
            preview_source=cast("PreviewSource | None", row.preview_source),
            deletable_clone=row.clone_id is not None and row.withdrawn_at is None,
            live_agents=live_agents,
        )


class OwnVoiceKeyOut(Strict):
    enabled: bool
    scope: str | None
    complete: bool
    using: str
    voice_provider: str | None
    #: Calls there speak on our own voice key, and only the voice is ours.
    speaks_on_own_voice: bool

    @classmethod
    def of(cls, state: OwnVoiceKeyState) -> OwnVoiceKeyOut:
        return cls(
            enabled=state.enabled,
            scope=state.scope,
            complete=state.complete,
            using=state.using,
            voice_provider=state.voice_provider,
            speaks_on_own_voice=state.speaks_on_own_voice,
        )


class StudioWorkspaceOut(Strict):
    """A client workspace where our Cartesia key was confirmed on (D-717)."""

    tenant_id: str
    #: The client's name, for the operator; null when it could not be read.
    tenant_name: str | None
    enabled_at: datetime
    #: The last time its own-keys state was read and matched.
    checked_at: datetime | None
    #: Our code for the last failure to switch on or verify, or null.
    error_code: str | None


class StudioVoicesOut(Strict):
    #: The engine's own report of OUR developer workspace's keys, switched on for the voice
    #: since D-727 so trial agents can speak Studio.
    key: OwnVoiceKeyOut
    #: Studio can be sold: key in the console and held, both prices attested, voices listed.
    ready: bool
    #: A Cartesia key is set in our ops console to install.
    cartesia_key_configured: bool
    #: The developer workspace holds a Cartesia voice key.
    developer_holds_key: bool
    #: The developer workspace speaks on that key for the voice: on, scope voice, complete
    #: and in use. Studio ready switches it on (D-727).
    developer_switch_on: bool
    #: The `byok_voice` per-minute rate is attested.
    minute_attested: bool
    #: The Cartesia TTS price is attested.
    synthesis_priced: bool
    #: Studio voices are listed in the catalogue.
    voices_listed: bool
    #: What an operator still has to do, in order.
    missing: list[str]
    #: Client workspaces running Studio.
    workspaces: list[StudioWorkspaceOut]
    #: Published agents on a Studio voice.
    live_studio_agents: int
    #: How Studio works on this platform, said where the operator decides.
    explanation: str
    note: str


class HostedVoicesOut(Strict):
    #: Does the selected voice platform host its own voices? False: this panel does not apply.
    available: bool
    scope: VoiceScope
    voices: list[HostedVoiceOut]
    #: Hosted voices synced altogether, added or not.
    cached: int
    offered: int
    #: Studio voices are switched on (our Cartesia key on in the workspace), as last read.
    studio_ready: bool
    #: The engine's band sold as Clear (`thinnest_clear_voice_band`), or null on an engine
    #: that does not host voices.
    clear_band: HostedVoiceBand | None
    note: str
    #: Voices the platform currently lists of its own, per band (withdrawn ones excluded).
    bands: dict[str, int]
    #: Set when the platform lists voices but none in the band we sell, saying why.
    plan_note: str | None


class AddHostedVoiceIn(Strict):
    voice_id: str = Field(min_length=1, max_length=255)


class SetHostedCurationIn(Strict):
    voice_id: str = Field(min_length=1, max_length=255)
    state: CurationState


class HostedVoiceWriteOut(Strict):
    voice: HostedVoiceOut
    next_step: str


class CloneOut(Strict):
    voice: HostedVoiceOut
    #: The platform's plan lets a clone be put on an agent (create-voice-clone.md:621-623).
    usable_on_agents: bool
    next_step: str


class DeleteCloneOut(Strict):
    voice_id: str
    #: Agents the platform moved to a standard voice, across its workspace.
    moved_agents: int
    next_step: str


class FetchPreviewIn(Strict):
    voice_id: str = Field(min_length=1, max_length=255)
    #: For a Studio voice: the line it speaks (charged per character by the provider).
    text: str | None = Field(default=None, max_length=200)
    #: A language tag such as `te-IN` for the spoken line.
    language: str | None = Field(default=None, max_length=12, pattern=LANGUAGE_TAG)


class StudioEnableIn(Strict):
    #: The Cartesia model the key runs, when it is installed now; omitted, the provider's
    #: usual one. Ignored where the workspace already holds a Cartesia key.
    model: str | None = Field(default=None, max_length=64)
    #: Also switch Studio on in this client's own workspace now, so Studio voices can be
    #: listed before any client has published a Studio agent. Omitted: the developer
    #: workspace only.
    tenant_id: UUID | None = None


def _hosting_engine() -> HostsVoices:
    engine = get_engine()
    if not isinstance(engine, HostsVoices) or engine.capabilities.is_ours("tts"):
        raise ProblemError(
            kind="business_rule",
            code="voices_not_hosted",
            title="This voice platform does not host its own voices",
            detail="Voices on this deployment come from Calevate's own catalogue.",
            remediation="Manage voices from the Voices panel instead.",
        )
    return engine


async def _admin_names(session: AsyncSession, rows: list[HostedVoiceRow]) -> dict[UUID, str]:
    """The names of the operators who recorded the consents on `rows`."""
    ids = list({row.consent.recorded_by for row in rows if row.consent is not None})
    if not ids:
        return {}
    found = await session.execute(
        text("SELECT id, name FROM admin_users WHERE id = ANY(:ids)"), {"ids": ids}
    )
    return {UUID(str(r[0])): str(r[1]) for r in found.all() if r[1]}


async def _out(session: AsyncSession, row: HostedVoiceRow, *, engine: str) -> HostedVoiceOut:
    live = await count_live_agents_by_engine_voice()
    return HostedVoiceOut.of(
        row,
        engine=engine,
        live_agents=live.get(row.voice_id, 0),
        admin_names=await _admin_names(session, [row]),
    )


async def _audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    *,
    action: str,
    voice_id: str | None,
    summary: dict[str, object],
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        object_type="platform_voice_catalog",
        object_id=voice_id,
        ip=client_request_ip(request),
        summary=summary,
    )


async def _read_upload(file: UploadFile, *, what: str) -> bytes:
    """The upload body. Its size is already bounded by the API's request limit
    (`core/middleware.BodyLimitMiddleware`, which counts a chunked body too)."""
    chunks: list[bytes] = []
    while chunk := await file.read(_READ_CHUNK_BYTES):
        chunks.append(chunk)
    if not chunks:
        raise ProblemError(
            kind="validation",
            code="voice_upload_empty",
            title=f"The {what} is empty",
            detail=f"No audio was received for the {what}.",
            remediation=f"Choose the {what} file again.",
        )
    return b"".join(chunks)


def sniff_preview_type(data: bytes) -> str | None:
    """The content type a clip is served with, decided from its leading bytes, or None for
    a clip a browser cannot be trusted to play (MP3 and WAV only)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    return None


async def _store_preview(
    session: AsyncSession, *, voice_id: str, data: bytes, source: str
) -> HostedVoiceRow:
    content_type = sniff_preview_type(data)
    if content_type is None:
        raise ProblemError(
            kind="validation",
            code="voice_preview_format",
            title="This preview is not MP3 or WAV audio",
            detail="A preview must be an MP3 or WAV clip so every browser can play it.",
            remediation="Convert the clip to MP3 or WAV and upload it again.",
        )
    from apps.workers.storage import store_voice_preview, voice_preview_key

    key = await store_voice_preview(
        key=voice_preview_key(voice_id), data=data, content_type=content_type
    )
    return await record_preview(
        session, voice_id=voice_id, object_key=key, content_type=content_type, source=source
    )


# --- the table -------------------------------------------------------------------------


@router.get(
    "/hosted",
    response_model=HostedVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The voices the voice platform hosts, as curated here (admin realm)",
    description=(
        "On a voice platform that hosts its own voices: by default the voices an operator "
        "added; `?scope=all` adds every voice the last sync read, in every band the platform "
        "lists, with `band` and `sold`. Only ADDED and ENABLED voices in a sold band are offered "
        "to clients; `plan_note` says why when the platform lists none in the band we sell. "
        "`available` is false on a platform whose voices come from Calevate's own catalogue."
    ),
)
async def list_hosted(
    session: GlobalSession,
    _: VoiceCurator,
    scope: Annotated[VoiceScope, Query()] = "added",
) -> HostedVoicesOut:
    engine = get_engine()
    if not isinstance(engine, HostsVoices) or engine.capabilities.is_ours("tts"):
        return HostedVoicesOut(
            available=False,
            scope=scope,
            voices=[],
            cached=0,
            offered=0,
            studio_ready=False,
            clear_band=None,
            note="Voices on this deployment come from Calevate's own catalogue.",
            bands={},
            plan_note=None,
        )
    rows = await list_hosted_voices(session, scope=scope)
    live = await count_live_agents_by_engine_voice()
    names = await _admin_names(session, list(rows))
    voices = [
        HostedVoiceOut.of(
            row, engine=engine.name, live_agents=live.get(row.voice_id, 0), admin_names=names
        )
        for row in rows
    ]
    offered = sum(1 for v in voices if v.offered)
    bands = await count_listed_bands(session)
    listed = sum(bands.values())
    return HostedVoicesOut(
        available=True,
        scope=scope,
        voices=voices,
        cached=await count_hosted_voices(session),
        offered=offered,
        studio_ready=await studio_voices_ready(session),
        clear_band=sold_hosted_band(),
        note=(
            f"{offered} voice(s) offered to clients. Add a voice from the full list, check "
            "its preview, then enable it."
        ),
        bands={str(band): count for band, count in bands.items()},
        plan_note=(
            no_sold_band_sentence(listed) if listed and not bands.get(sold_hosted_band()) else None
        ),
    )


@router.post(
    "/hosted",
    response_model=HostedVoiceWriteOut,
    status_code=201,
    openapi_extra=permission_meta("ops:manage"),
    summary="Add one synced voice to the voices that can be offered (audited)",
    description=(
        "Marks a voice the last sync read as ADDED. It arrives disabled, so a client cannot "
        "choose it until it is enabled; give it a preview first. Only a voice in a band we sell "
        "(the platform's band sold as Clear, or a Studio voice of our own key) can be added: "
        "any other is refused with `voice_band_not_sold`. Idempotent."
    ),
)
async def add_hosted(
    payload: AddHostedVoiceIn, session: GlobalSession, request: Request, principal: VoiceCurator
) -> HostedVoiceWriteOut:
    engine = _hosting_engine()
    row = await add_hosted_voice(session, voice_id=payload.voice_id)
    await _audit(
        session,
        request,
        principal,
        action="ops.hosted_voice_added",
        voice_id=row.voice_id,
        summary={"voice_id": row.voice_id, "source": row.source},
    )
    return HostedVoiceWriteOut(
        voice=await _out(session, row, engine=engine.name),
        next_step=(
            f"{row.label} was added. "
            + (
                "Enable it to offer it to clients."
                if row.preview_available
                else "Give it a preview, then enable it to offer it to clients."
            )
        ),
    )


@router.patch(
    "/hosted",
    response_model=HostedVoiceWriteOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Enable, disable or archive one hosted voice for every client (audited)",
    description=(
        "Only an ADDED voice can be enabled. It changes no agent and no call: an agent on "
        "this voice keeps speaking it; disabling only takes it off the picker. Idempotent."
    ),
)
async def set_hosted_state(
    payload: SetHostedCurationIn,
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
) -> HostedVoiceWriteOut:
    engine = _hosting_engine()
    row = await set_hosted_curation(session, voice_id=payload.voice_id, state=payload.state)
    out = await _out(session, row, engine=engine.name)
    await _audit(
        session,
        request,
        principal,
        action="ops.hosted_voice_curation_set",
        voice_id=row.voice_id,
        summary={"voice_id": row.voice_id, "state": row.state, "live_agents": out.live_agents},
    )
    if row.state == "enabled":
        step = f"{row.label} can now be chosen for an agent."
    else:
        step = (
            f"{row.label} can no longer be chosen. {out.live_agents} live agent(s) on it keep "
            "speaking it until each is moved."
        )
    return HostedVoiceWriteOut(voice=out, next_step=step)


@router.get(
    "/hosted/agents",
    response_model=HostedVoiceAgentsOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The agents set to one hosted voice, in every account (admin realm)",
    description=(
        "Every agent, live or not, whose voice is this hosted voice, with its account, live "
        "ones first. Read one voice at a time, for the voice's detail."
    ),
)
async def hosted_voice_agents(
    session: GlobalSession,
    _: VoiceCurator,
    voice_id: Annotated[str, Query(min_length=1, max_length=255)],
    limit: Annotated[int, Query(ge=1, le=MAX_AGENTS_ON_VOICE)] = MAX_AGENTS_ON_VOICE,
) -> HostedVoiceAgentsOut:
    _hosting_engine()
    await read_hosted_voice(session, voice_id)
    agents = await agents_on_hosted_voice(voice_id, limit=limit)
    return HostedVoiceAgentsOut(
        voice_id=voice_id,
        agents=[
            HostedVoiceAgentOut(
                tenant_id=str(a.tenant_id),
                tenant_name=a.tenant_name,
                agent_id=str(a.agent_id),
                agent_name=a.agent_name,
                status=a.status,
            )
            for a in agents
        ],
    )


@router.patch(
    "/hosted/display-name",
    response_model=HostedVoiceWriteOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Set the name clients see for one hosted voice (audited)",
    description=(
        "Clients see this name instead of the provider's; null or blank goes back to the "
        "provider's name. The sync never changes it. For a cloned voice of a real person it "
        "may not contain the speaker's name (`voice_clone_name_reveals_speaker`)."
    ),
)
async def set_hosted_display_name(
    payload: SetDisplayLabelIn, session: GlobalSession, request: Request, principal: VoiceCurator
) -> HostedVoiceWriteOut:
    engine = _hosting_engine()
    before = await read_hosted_voice(session, payload.voice_id)
    row = await set_display_label(
        session, voice_id=payload.voice_id, display_label=payload.display_label
    )
    await _audit(
        session,
        request,
        principal,
        action="ops.hosted_voice_display_name_set",
        voice_id=row.voice_id,
        summary={
            "voice_id": row.voice_id,
            "display_label": row.display_label,
            "previous": before.display_label,
        },
    )
    return HostedVoiceWriteOut(
        voice=await _out(session, row, engine=engine.name),
        next_step=f"Clients see this voice as {row.label}.",
    )


def _consent_summary(consent: CloneConsent | None) -> dict[str, object] | None:
    """A consent record for the audit stream. The name and the wording are fingerprinted, not
    copied: the stream is a log (hard rule 6), and the row holds the record itself; a
    fingerprint still proves which record an entry was about."""
    if consent is None:
        return None
    return {
        "speaker_sha256": hashlib.sha256(consent.speaker_name.encode()).hexdigest(),
        "statement_sha256": hashlib.sha256(consent.statement.encode()).hexdigest(),
        "consented_on": consent.given_on.isoformat(),
        "scope": consent.scope,
        "recorded_by": str(consent.recorded_by),
        "recorded_at": consent.recorded_at.isoformat(),
        "document": consent.has_document,
    }


@router.patch(
    "/hosted/person-clone",
    response_model=HostedVoiceWriteOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Mark or unmark a voice as a cloned voice of a real person (step-up, audited)",
    description=(
        "A voice marked as a person's clone cannot be offered until the speaker's consent is "
        "recorded (D-721). Marking an offered voice that could not stay offered is refused "
        "(`voice_clone_consent_missing`, `voice_clone_name_missing`). Unmarking keeps the "
        "consent record and its document. Requires "
        "`X-Confirm-Action: set_voice_person_clone:<voice_id>`."
    ),
)
async def set_hosted_person_clone(
    payload: SetPersonCloneIn,
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> HostedVoiceWriteOut:
    step_up.require(x_confirm_action, person_clone_confirmation(payload.voice_id))
    engine = _hosting_engine()
    row = await set_person_clone(
        session, voice_id=payload.voice_id, person_clone=payload.person_clone
    )
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_person_clone_set",
        voice_id=row.voice_id,
        summary={
            "voice_id": row.voice_id,
            "person_clone": row.person_clone,
            "consent": _consent_summary(row.consent),
        },
    )
    return HostedVoiceWriteOut(
        voice=await _out(session, row, engine=engine.name),
        next_step=(
            "Marked as a cloned voice of a real person. Record the speaker's consent before "
            "offering it."
            if row.person_clone and row.consent is None
            else "Marked as a cloned voice of a real person."
            if row.person_clone
            else "No longer marked as a cloned voice of a real person."
        ),
    )


@router.post(
    "/hosted/clone-consent",
    response_model=HostedVoiceWriteOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Record a real person's consent to their cloned voice (step-up, audited)",
    description=(
        "Records the speaker's name, the statement they consented to, the date, and the "
        "operator recording it, with an optional signed document (PDF, JPEG or PNG, at most "
        "2 MB, stored sealed), and marks the voice as a person's clone. Replaces an earlier "
        "record; without a new document the stored one is kept. The scope is fixed: calls "
        "made by Calevate clients' agents. Requires "
        "`X-Confirm-Action: record_voice_consent:<voice_id>`."
    ),
)
async def record_hosted_clone_consent(
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    step_up: StepUpGate,
    voice_id: Annotated[str, Form(min_length=1, max_length=255)],
    speaker_name: Annotated[str, Form(min_length=1, max_length=120)],
    statement: Annotated[str, Form(min_length=1, max_length=2000)],
    consented_on: Annotated[date, Form()],
    document: Annotated[UploadFile | None, File()] = None,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> HostedVoiceWriteOut:
    step_up.require(x_confirm_action, consent_confirmation(voice_id))
    engine = _hosting_engine()
    if consented_on > datetime.now(IST).date():
        raise ProblemError(
            kind="validation",
            code="voice_consent_date_future",
            title="The consent date is in the future",
            detail="Consent is recorded on or after the day it was given.",
            remediation="Enter the date the speaker gave their consent.",
        )
    speaker, wording = speaker_name.strip(), statement.strip()
    if not speaker or not wording:
        raise ProblemError(
            kind="validation",
            code="voice_consent_incomplete",
            title="The speaker's name and the consent statement are both needed",
            detail="A consent record names the person and says what they agreed to.",
            remediation="Fill in both, then record the consent again.",
        )
    await read_hosted_voice(session, voice_id)
    key: str | None = None
    if document is not None and document.filename:
        accepted = accept_document(
            filename=document.filename, data=await _read_upload(document, what="document")
        )
        key = await keep_consent_document(voice_id=voice_id, document=accepted)
    if principal.user_id is None:
        # A consent record names the operator who recorded it; an admin principal always has
        # an id, so this is a sentence for an impossible state rather than a CHECK failure.
        raise ProblemError(
            kind="auth",
            code="voice_consent_actor_unknown",
            title="This session has no admin identity",
            detail="A consent record has to name the operator who recorded it.",
        )
    row, replaced = await record_clone_consent(
        session,
        voice_id=voice_id,
        speaker_name=speaker,
        statement=wording,
        given_on=consented_on,
        recorded_by=principal.user_id,
        document_key=key,
    )
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_clone_consent_recorded",
        voice_id=row.voice_id,
        summary={
            "voice_id": row.voice_id,
            "consent": _consent_summary(row.consent),
            "replaced": _consent_summary(replaced),
        },
    )
    return HostedVoiceWriteOut(
        voice=await _out(session, row, engine=engine.name),
        next_step=(
            "The speaker's consent is recorded. "
            + (
                "Give the voice the name clients will see, then offer it."
                if row.display_label is None
                else "The voice can now be offered."
            )
        ),
    )


@router.get(
    "/hosted/clone-consent/document",
    response_class=Response,
    openapi_extra=permission_meta("ops:manage"),
    summary="Download the signed consent for one cloned voice (admin realm, audited)",
    responses={
        200: {
            "description": "The signed consent document.",
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in ("application/pdf", "image/jpeg", "image/png")
            },
        }
    },
)
async def hosted_clone_consent_document(
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    voice_id: Annotated[str, Query(min_length=1, max_length=255)],
) -> Response:
    key = await consent_document_key(session, voice_id=voice_id)
    document = None if key is None else await open_consent_document(voice_id=voice_id, key=key)
    if document is None:
        raise ProblemError.not_found("Consent document")
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_clone_consent_document_read",
        voice_id=voice_id,
        summary={"voice_id": voice_id},
    )
    return Response(
        content=document.data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": attachment_disposition(document.filename, fallback="consent"),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- clones ----------------------------------------------------------------------------


@router.post(
    "/clones",
    response_model=CloneOut,
    status_code=201,
    openapi_extra=permission_meta("ops:manage"),
    summary="Clone a voice from a recording (step-up confirmed, audited)",
    description=(
        "Sends a 5-30 second recording (WAV, MP3, M4A or WebM, at most 2 MB, the API's "
        "request limit) to the voice platform to clone. Both consents are the operator's "
        "own attestations and are recorded with who gave them and when. The clone is saved "
        "ADDED and DISABLED, with the platform's preview stored here. Requires "
        "`X-Confirm-Action: clone_voice`."
    ),
)
async def create_clone(
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    step_up: StepUpGate,
    sample: Annotated[UploadFile, File()],
    name: Annotated[str, Form(min_length=1, max_length=CLONE_NAME_MAX)],
    consent_own_voice: Annotated[bool, Form()],
    consent_no_impersonation: Annotated[bool, Form()],
    description: Annotated[str | None, Form(max_length=CLONE_DESCRIPTION_MAX)] = None,
    language: Annotated[str | None, Form(max_length=12, pattern=LANGUAGE_TAG)] = None,
    remove_noise: Annotated[bool, Form()] = True,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> CloneOut:
    step_up.require(x_confirm_action, CLONE_CONFIRMATION)
    engine = _hosting_engine()
    if not (consent_own_voice and consent_no_impersonation):
        raise ProblemError(
            kind="validation",
            code="voice_clone_consent_missing",
            title="Both promises are needed to clone a voice",
            detail="Confirm that the recording is the speaker's own voice or held with "
            "their permission, and that it will not be used to impersonate anyone.",
            remediation="Tick both statements, then clone again.",
        )
    content_type = (sample.content_type or "").split(";")[0].strip().lower()
    if content_type not in CLONE_SAMPLE_TYPES:
        raise ProblemError(
            kind="validation",
            code="voice_clone_sample_format",
            title="This recording is not WAV, MP3, M4A or WebM audio",
            detail="The voice platform clones from WAV, MP3, M4A or WebM recordings only.",
            remediation="Record or convert the sample to one of those formats.",
        )
    data = await _read_upload(sample, what="recording")
    clone = await engine.create_voice_clone(
        VoiceCloneSample(
            filename=sample.filename or "sample",
            content_type=content_type,
            data=data,
            name=name.strip(),
            description=description.strip() if description else None,
            language=language,
            remove_noise=remove_noise,
            consent_own_voice=True,
            consent_no_impersonation=True,
        )
    )
    row = await record_clone(
        session,
        engine=engine.name,
        vendor_voice_id=clone.voice_id,
        clone_id=clone.clone_id,
        label=clone.label,
        language=clone.language or language,
        description=description,
    )
    # The recording is kept, sealed, so the clone can be made again in a client's own voice
    # workspace (D-693): a clone belongs to the workspace that made it.
    # Best effort: the clone exists at the platform and must be recorded either way. Without
    # the sample it can still be spoken in our workspace; a client workspace is then refused
    # by name (`voice_clone_sample_missing`) until the voice is cloned again.
    try:
        await keep_clone_sample(
            session,
            voice_id=row.voice_id,
            filename=sample.filename or "sample",
            content_type=content_type,
            language=language,
            data=data,
        )
    except Exception as exc:
        log.warning("voice_clone_sample_not_kept", extra={"reason": type(exc).__name__})
    # The consents are the operator's legal attestations: who, when, and the two promises,
    # in the same transaction as the row.
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_cloned",
        voice_id=row.voice_id,
        summary={
            "voice_id": row.voice_id,
            "clone_id": clone.clone_id,
            "consent_own_voice": True,
            "consent_no_impersonation": True,
            "sample_bytes": len(data),
        },
    )
    stored = False
    if clone.preview_url:
        stored = await _try_vendor_preview(session, voice_id=row.voice_id, url=clone.preview_url)
        row = await read_hosted_voice(session, row.voice_id)
    return CloneOut(
        voice=await _out(session, row, engine=engine.name),
        usable_on_agents=clone.usable_on_agents,
        next_step=(
            f"{row.label} was cloned and added, disabled. "
            + (
                "Listen to its preview, then enable it."
                if stored
                else "Upload a preview, then enable it."
            )
            + (
                ""
                if clone.usable_on_agents
                else " The voice platform's plan does not yet let a clone be put on an agent."
            )
        ),
    )


async def _try_vendor_preview(session: AsyncSession, *, voice_id: str, url: str) -> bool:
    """Store the platform's 60-second preview link's audio, best effort: the clone already
    exists, so a failed fetch is a missing preview the operator can upload, not a failure."""
    from apps.workers.storage import fetch_voice_preview

    try:
        data = await fetch_voice_preview(url)
        await _store_preview(session, voice_id=voice_id, data=data, source="vendor")
    except Exception as exc:
        log.warning("voice_preview_fetch_failed", extra={"reason": type(exc).__name__})
        return False
    return True


@router.delete(
    "/clones",
    response_model=DeleteCloneOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Delete one of our cloned voices (step-up confirmed, audited)",
    description=(
        "Deletes the clone on the voice platform, which forgets it everywhere and moves "
        "every agent on it to a standard voice; it cannot be undone. Refused with "
        "`voice_clone_in_use` while live agents here are on it, unless `confirm=true`. "
        "Requires `X-Confirm-Action: delete_voice_clone:<voice_id>`."
    ),
)
async def delete_clone(
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    step_up: StepUpGate,
    voice_id: Annotated[str, Query(min_length=1, max_length=255)],
    confirm: Annotated[bool, Query()] = False,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> DeleteCloneOut:
    step_up.require(x_confirm_action, delete_clone_confirmation(voice_id))
    engine = _hosting_engine()
    row = await read_hosted_voice(session, voice_id)
    if row.clone_id is None:
        raise ProblemError(
            kind="business_rule",
            code="voice_not_a_clone",
            title="This voice is not one of our clones",
            detail="Only a voice cloned from this console can be deleted from it.",
            remediation="Disable or archive the voice instead.",
        )
    live = (await count_live_agents_by_engine_voice()).get(voice_id, 0)
    if live and not confirm:
        raise ProblemError(
            kind="conflict",
            code="voice_clone_in_use",
            title="Live agents are speaking this voice",
            detail=(
                f"{live} live agent(s) are on this voice. Deleting it moves them to the "
                "platform's standard voice on their next call."
            ),
            remediation="Move those agents to another voice first, or delete with confirm=true.",
        )
    moved = await engine.delete_voice_clone(row.clone_id)
    await withdraw_hosted_voice(session, voice_id=voice_id)
    # Its copies in clients' own workspaces and the kept recording go with it (D-693).
    sample_key = (
        await session.execute(
            text("SELECT sample_object_key FROM platform_voice_catalog WHERE voice_id = :v"),
            {"v": voice_id},
        )
    ).scalar()
    await forget_clone(engine, voice_id=voice_id, sample_key=sample_key)
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_clone_deleted",
        voice_id=voice_id,
        summary={"voice_id": voice_id, "moved_agents": moved, "live_agents": live},
    )
    return DeleteCloneOut(
        voice_id=voice_id,
        moved_agents=moved,
        next_step=(
            f"The clone was deleted. The voice platform moved {moved} agent(s) to its standard "
            "voice; move them to another voice and republish them."
            if moved
            else "The clone was deleted. No agent was on it."
        ),
    )


# --- previews --------------------------------------------------------------------------


@router.post(
    "/hosted/preview",
    response_model=HostedVoiceWriteOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Upload a preview clip for one hosted voice (audited)",
    description=(
        "For a voice the platform gives no sample of: an MP3 or WAV clip, at most 2 MB, "
        "stored here and played to clients from Calevate. Replaces any earlier preview."
    ),
)
async def upload_preview(
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    voice_id: Annotated[str, Form(min_length=1, max_length=255)],
    sample: Annotated[UploadFile, File()],
) -> HostedVoiceWriteOut:
    engine = _hosting_engine()
    await read_hosted_voice(session, voice_id)
    data = await _read_upload(sample, what="preview")
    row = await _store_preview(session, voice_id=voice_id, data=data, source="upload")
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_preview_uploaded",
        voice_id=voice_id,
        summary={"voice_id": voice_id, "bytes": len(data)},
    )
    return HostedVoiceWriteOut(
        voice=await _out(session, row, engine=engine.name),
        next_step=f"{row.label} now has a preview.",
    )


@router.post(
    "/hosted/preview/fetch",
    response_model=HostedVoiceWriteOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Store the voice platform's own preview of one hosted voice (audited)",
    description=(
        "For a Studio voice, the platform speaks one line on our voice key (charged per "
        "character by the provider; `text` at most 200 characters). For one of our clones, "
        "the platform's preview is fetched. A platform voice with no sample is refused: "
        "upload one instead."
    ),
)
async def fetch_preview(
    payload: FetchPreviewIn, session: GlobalSession, request: Request, principal: VoiceCurator
) -> HostedVoiceWriteOut:
    engine = _hosting_engine()
    row = await read_hosted_voice(session, payload.voice_id)
    if row.source == "byok":
        # Spoken where our key is switched on; elsewhere the vendor refuses a preview with
        # 409 (preview-byok-voice.md:396-397).
        found = await studio_listing_workspace(engine)
        if found is None:
            raise ProblemError(
                kind="business_rule",
                code="studio_preview_no_workspace",
                title="No workspace runs Studio yet",
                detail="A Studio voice is spoken on our key in a workspace where it is "
                "switched on, and none answers as ready.",
                remediation="Run Studio ready, then try again.",
            )
        with in_workspace(found.workspace):
            audio = await engine.preview_own_key_voice(
                voice_id=row.vendor_id,
                text=payload.text,
                language=payload.language,
            )
        data = audio.data
    else:
        clone = await engine.find_voice_clone(row.vendor_id)
        if clone is None or clone.preview_url is None:
            raise ProblemError(
                kind="business_rule",
                code="voice_preview_unavailable",
                title="The voice platform has no sample of this voice",
                detail="Only our own clones and Studio voices have a preview on the platform.",
                remediation="Upload a short sample clip for this voice instead.",
            )
        from apps.workers.storage import fetch_voice_preview

        data = await fetch_voice_preview(clone.preview_url)
    row = await _store_preview(session, voice_id=row.voice_id, data=data, source="vendor")
    await _audit(
        session,
        request,
        principal,
        action="ops.voice_preview_fetched",
        voice_id=row.voice_id,
        summary={"voice_id": row.voice_id, "bytes": len(data)},
    )
    return HostedVoiceWriteOut(
        voice=await _out(session, row, engine=engine.name),
        next_step=f"{row.label} now has a preview.",
    )


@router.get(
    "/hosted/preview",
    response_class=Response,
    openapi_extra=permission_meta("ops:manage"),
    summary="Play any hosted voice's stored preview (admin realm)",
    description=(
        "The stored preview audio for one hosted voice, added or not and in any state, "
        "served by Calevate. A voice with no stored preview is a 404."
    ),
    responses=PREVIEW_RESPONSES,
)
async def hosted_voice_preview(
    _: VoiceCurator, voice_id: Annotated[str, Query(min_length=1, max_length=255)]
) -> Response:
    return await stored_preview_response(voice_id, offered_only=False)


# --- Studio voices: our Cartesia key, in the developer workspace and each Studio client's ---


#: What Studio is on this platform, said where the operator decides.
STUDIO_SWITCH_EXPLAINED: Final = (
    "Studio voices are our Cartesia key, switched on for the voice only. Studio ready "
    "switches it on in our developer workspace, where free-trial agents speak Studio and "
    "where the voices are listed; every agent that is not on a Studio voice is set to stay "
    "off it first. A paying client's workspace is switched on automatically at its first "
    "Studio publish, after its Clear agents are set to stay off. This is not ThinnestAI's "
    "own Studio band."
)


async def _tenant_names(tenant_ids: list[UUID]) -> dict[UUID, str]:
    if not tenant_ids:
        return {}
    async with admin_session() as session:
        rows = (
            await session.execute(
                text("SELECT id, name FROM organizations WHERE id = ANY(:ids)"),
                {"ids": tenant_ids},
            )
        ).all()
    return {UUID(str(r[0])): str(r[1]) for r in rows}


async def _studio_out(
    session: AsyncSession, engine: HostsVoices, readiness: StudioReadiness, state: OwnVoiceKeyState
) -> StudioVoicesOut:
    names = await _tenant_names([w.tenant_id for w in readiness.workspaces])
    if readiness.ready:
        note = (
            "Ready: Studio is on in our developer workspace for trial agents and in "
            f"{len(readiness.workspaces)} client workspace(s), and switches on in a paying "
            "client's workspace at its first Studio publish."
        )
    else:
        note = "Not ready: " + " ".join(readiness.missing())
    return StudioVoicesOut(
        key=OwnVoiceKeyOut.of(state),
        ready=readiness.ready,
        cartesia_key_configured=readiness.console_key,
        developer_holds_key=readiness.developer_holds_key,
        developer_switch_on=readiness.developer_switch_on,
        minute_attested=readiness.minute_attested,
        synthesis_priced=readiness.synthesis_priced,
        voices_listed=readiness.voices_listed,
        missing=readiness.missing(),
        workspaces=[
            StudioWorkspaceOut(
                tenant_id=str(w.tenant_id),
                tenant_name=names.get(w.tenant_id),
                enabled_at=w.enabled_at,
                checked_at=w.checked_at,
                error_code=w.error_code,
            )
            for w in readiness.workspaces
        ],
        live_studio_agents=await live_studio_agents(session, engine=engine.name),
        explanation=STUDIO_SWITCH_EXPLAINED,
        note=note,
    )


@router.get(
    "/studio-voices",
    response_model=StudioVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Whether Studio voices are ready, and which client workspaces run them",
)
async def studio_voices(session: GlobalSession, _: VoiceCurator) -> StudioVoicesOut:
    engine = _hosting_engine()
    state = await engine.own_key_state()
    readiness = await studio_readiness(session, engine, developer=state)
    return await _studio_out(session, engine, readiness, state)


@router.post(
    "/studio-voices/enable",
    response_model=StudioVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Studio ready: switch our Cartesia key on in our developer workspace (step-up)",
    description=(
        "Switches our Cartesia key on, for the voice only, in the developer workspace, where "
        "free-trial agents publish Studio voices: every published agent not on a Studio voice "
        "that would follow the switch is set to stay off and read back first, then the key, "
        "the switch and a read-back. With `tenant_id`, also switches Studio on in that paying "
        "client's own workspace the same way. Then re-reads the voices. Idempotent. Requires "
        "`X-Confirm-Action: enable_studio_voices`."
    ),
)
async def enable_studio(
    payload: StudioEnableIn,
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> StudioVoicesOut:
    step_up.require(x_confirm_action, STUDIO_ENABLE_CONFIRMATION)
    engine = _hosting_engine()
    result = await prepare_studio(session, engine, model=payload.model, tenant_id=payload.tenant_id)
    try:
        # A failed read leaves the voices to the next refresh rather than undoing a switch
        # the platform has already made.
        await sync_hosted_voices(session, engine, engine_name=engine.name)
    except ProblemError as exc:
        log.warning("studio_voices_sync_after_enable_failed", extra={"reason": exc.code})
    await _audit(
        session,
        request,
        principal,
        action="ops.studio_voices_prepared",
        voice_id=None,
        summary={
            "developer_switched_on": result.developer_switched_on,
            "tenant_id": str(payload.tenant_id) if payload.tenant_id else None,
            "developer_switch_on": result.readiness.developer_switch_on,
        },
    )
    state = await engine.own_key_state()
    readiness = await studio_readiness(session, engine, developer=state)
    return await _studio_out(session, engine, readiness, state)


__all__ = [
    "CLONE_CONFIRMATION",
    "STUDIO_ENABLE_CONFIRMATION",
    "consent_confirmation",
    "delete_clone_confirmation",
    "person_clone_confirmation",
    "router",
    "sniff_preview_type",
]
