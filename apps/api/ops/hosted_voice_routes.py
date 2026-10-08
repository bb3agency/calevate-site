"""The Voices panel on an engine that HOSTS its voices (D-687) — admin realm, `ops:manage`.

    GET    /v1/ops/voices/hosted              the hosted voices (`?scope=all` for every synced
                                              one), each with state, rung and preview status
    POST   /v1/ops/voices/hosted              ADD one synced voice (audited); arrives disabled
    PATCH  /v1/ops/voices/hosted              enable | disable | archive one (audited)
    POST   /v1/ops/voices/clones              clone a voice from a recording (step-up, audited)
    DELETE /v1/ops/voices/clones              delete one of our clones (step-up, audited)
    GET    /v1/ops/voices/hosted/preview      play any hosted voice's stored preview
    POST   /v1/ops/voices/hosted/preview      upload a preview clip for a voice (audited)
    POST   /v1/ops/voices/hosted/preview/fetch  store the platform's own preview (audited)
    GET    /v1/ops/voices/studio-voices       whether our Cartesia key is on in the workspace
    POST   /v1/ops/voices/studio-voices/enable   switch it on, Clear agents kept off first
                                              (step-up, audited)
    POST   /v1/ops/voices/studio-voices/disable  switch it off (step-up, audited)

The operator plays a preview from `GET /v1/ops/voices/hosted/preview`, for any hosted voice
added or not; a client plays an offered one from `GET /v1/agents/engine-catalogue/preview`.
Both read through `engine_catalogue_routes.stored_preview_response`. The Pipecat panel
(`ops/voice_curation_routes.py`) is unchanged; on an engine that does not host voices
every route here answers that it does not apply.

Voice ids travel in the body or the query, never the path, for `voice_curation_routes`'
reason: half of a catalogue id is a vendor's alphabet.

STEP-UP ON THE CLONE AND THE STUDIO SWITCH, NOT ON CURATION. A clone carries the operator's two
legal promises about a person's voice and spends a plan slot; deleting one cannot be undone
and moves every agent on it to a standard voice (delete-voice-clone.md:7); the Studio switch
installs a credential and changes which voice every agent speaks. Adding, enabling and
previewing touch no agent and no call and are reversible in a click, for
`voice_curation_routes`' argument.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal, cast

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
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.engine_catalogue_routes import PREVIEW_RESPONSES, stored_preview_response
from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    HostedVoiceRow,
    VoiceScope,
    add_hosted_voice,
    band_not_sold,
    count_hosted_voices,
    count_listed_bands,
    list_hosted_voices,
    live_studio_agents,
    no_sold_band_sentence,
    own_voice_key_ready,
    read_hosted_voice,
    record_clone,
    record_preview,
    rung_of_source,
    set_hosted_curation,
    sold_hosted_band,
    studio_voices_ready,
    sync_hosted_voices,
    withdraw_hosted_voice,
)
from apps.api.agents.studio_voices import disable_studio_voices, enable_studio_voices
from apps.api.agents.voice_curation import count_live_agents_by_engine_voice
from apps.api.agents.voices import CurationState
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUpGate
from apps.api.engine import get_engine
from apps.api.engine.catalogue import (
    HostedVoiceBand,
    HostsVoices,
    OwnVoiceKeyState,
    VoiceCloneSample,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/ops/voices", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
VoiceCurator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

#: The confirmation strings (`core/stepup.py`). Fixed rather than per-voice for the clone and
#: the Studio switch, which name no voice; per-voice for the delete.
CLONE_CONFIRMATION: Final = "clone_voice"
STUDIO_ENABLE_CONFIRMATION: Final = "enable_studio_voices"
STUDIO_DISABLE_CONFIRMATION: Final = "disable_studio_voices"


def delete_clone_confirmation(voice_id: str) -> str:
    return f"delete_voice_clone:{voice_id}"


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

    @classmethod
    def of(cls, row: HostedVoiceRow, *, engine: str, live_agents: int) -> HostedVoiceOut:
        return cls(
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


class StudioVoicesOut(Strict):
    #: The engine's own report of the workspace's keys.
    key: OwnVoiceKeyOut
    #: Studio voices can be spoken: our Cartesia key is on, for the voice only.
    ready: bool
    #: A Cartesia key is set in our ops console to install.
    cartesia_key_configured: bool
    #: Published agents on a Studio voice: what switching off would move.
    live_studio_agents: int
    #: Why switching on keeps every Clear agent off our key first.
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
    #: usual one. Ignored when the workspace already holds a Cartesia key.
    model: str | None = Field(default=None, max_length=64)


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


async def _out(session: AsyncSession, row: HostedVoiceRow, *, engine: str) -> HostedVoiceOut:
    live = await count_live_agents_by_engine_voice()
    return HostedVoiceOut.of(row, engine=engine, live_agents=live.get(row.voice_id, 0))


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
    voices = [
        HostedVoiceOut.of(row, engine=engine.name, live_agents=live.get(row.voice_id, 0))
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
    # The consents are the operator's legal attestations: who, when, and the two promises,
    # in the same transaction as the row. The recording itself is not kept here.
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


# --- Studio voices: our Cartesia key in the workspace ---------------------------------


#: What switching Studio voices on does to agents, said where the operator decides.
STUDIO_SWITCH_EXPLAINED: Final = (
    "Studio voices are our Cartesia key, switched on in the voice platform workspace for the "
    "voice only. Switching it on would move every agent that is not set to stay on the "
    "platform's own voices onto Cartesia at the Studio rate, so every published Clear agent "
    "is set to stay off it first, and nothing is switched on unless all of them are."
)


def _studio_out(state: OwnVoiceKeyState, *, live_studio_agents: int) -> StudioVoicesOut:
    ready = own_voice_key_ready(state)
    if ready:
        note = "On: Studio agents speak on our Cartesia key; Clear agents stay off it."
    elif state.voice_provider == STUDIO_VOICE_PROVIDER:
        note = "Off: our Cartesia key is installed but not switched on for the voice."
    else:
        note = "Off: our Cartesia key is not installed in the workspace yet."
    return StudioVoicesOut(
        key=OwnVoiceKeyOut.of(state),
        ready=ready,
        cartesia_key_configured=bool(get_settings().cartesia_api_key),
        live_studio_agents=live_studio_agents,
        explanation=STUDIO_SWITCH_EXPLAINED,
        note=note,
    )


@router.get(
    "/studio-voices",
    response_model=StudioVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Whether Studio voices (our Cartesia key) are switched on in the workspace",
)
async def studio_voices(session: GlobalSession, _: VoiceCurator) -> StudioVoicesOut:
    engine = _hosting_engine()
    return _studio_out(
        await engine.own_key_state(),
        live_studio_agents=await live_studio_agents(session, engine=engine.name),
    )


@router.post(
    "/studio-voices/enable",
    response_model=StudioVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Switch Studio voices on: Clear agents kept off first (step-up confirmed, audited)",
    description=(
        "In order: sets every published agent that is not on a Studio voice to stay on the "
        "platform's own voices and reads each back, refusing with `studio_agents_not_kept_off` "
        "if any is not; installs our Cartesia key as the workspace's voice key unless one is "
        "already there; switches own keys on for the voice only; reads the state back and "
        "re-reads the Studio voices. Idempotent. Requires `X-Confirm-Action: "
        "enable_studio_voices`."
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
    result = await enable_studio_voices(session, engine, model=payload.model)
    try:
        # The Studio voices become readable now; a failed read leaves them to the next
        # refresh rather than undoing a switch the platform has already made.
        await sync_hosted_voices(session, engine, engine_name=engine.name)
    except ProblemError as exc:
        log.warning("studio_voices_sync_after_enable_failed", extra={"reason": exc.code})
    await _audit(
        session,
        request,
        principal,
        action="ops.studio_voices_enabled",
        voice_id=None,
        summary={
            "agents_kept_off": result.agents_kept_off,
            "key_installed": result.key_installed,
            "voice_provider": result.state.voice_provider,
            "speaks_on_own_voice": result.state.speaks_on_own_voice,
        },
    )
    return _studio_out(
        result.state, live_studio_agents=await live_studio_agents(session, engine=engine.name)
    )


@router.post(
    "/studio-voices/disable",
    response_model=StudioVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Switch Studio voices off (step-up confirmed, audited)",
    description=(
        "Switches the workspace's own keys off and takes every Studio voice off offer. Agents "
        "on a Studio voice speak the platform's default voice from their next call, so this is "
        "refused with `studio_voices_in_use` while any is published, unless `confirm=true`. "
        "Requires `X-Confirm-Action: disable_studio_voices`."
    ),
)
async def disable_studio(
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
    step_up: StepUpGate,
    confirm: Annotated[bool, Query()] = False,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> StudioVoicesOut:
    step_up.require(x_confirm_action, STUDIO_DISABLE_CONFIRMATION)
    engine = _hosting_engine()
    live = await live_studio_agents(session, engine=engine.name)
    if live and not confirm:
        raise ProblemError(
            kind="conflict",
            code="studio_voices_in_use",
            title="Published agents are speaking Studio voices",
            detail=(
                f"{live} published agent(s) speak a Studio voice. Switching Studio voices off "
                "moves them to the voice platform's default voice on their next call."
            ),
            remediation="Move those agents to a Clear voice first, or switch off with "
            "confirm=true.",
        )
    state = await disable_studio_voices(session, engine)
    await _audit(
        session,
        request,
        principal,
        action="ops.studio_voices_disabled",
        voice_id=None,
        summary={"live_studio_agents": live, "speaks_on_own_voice": state.speaks_on_own_voice},
    )
    return _studio_out(state, live_studio_agents=live)


__all__ = [
    "CLONE_CONFIRMATION",
    "STUDIO_DISABLE_CONFIRMATION",
    "STUDIO_ENABLE_CONFIRMATION",
    "delete_clone_confirmation",
    "router",
    "sniff_preview_type",
]
