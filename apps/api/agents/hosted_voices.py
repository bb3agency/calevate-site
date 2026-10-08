"""Voices an ENGINE hosts, curated by an operator and offered to clients (D-687).

On an engine that dictates the voice leg and hosts voices of its own (`engine/catalogue.
HostsVoices`, ThinnestAI today) the voice catalogue is NOT Pipecat's `<model>:<speaker>`
catalogue. Its rows live in the same table (`platform_voice_catalog`) and are told apart by
their id, which is namespaced by where the voice comes from:

* `engine:<id>` — the engine's own voice in the band we sell, or a voice our account cloned
  on it. Spoken in our own (developer) workspace, billed at the `studio` band rate, sold as
  the CLEAR rung.
* `byok:<id>` — a voice of the Cartesia key installed in the Studio workspace (BYOK scope
  `voice`). Billed at `byok_voice` plus Cartesia's own charge to our key, sold as STUDIO.

Neither prefix is a member of `voices.TtsModel`, and the rows store the source in
`tts_model`, so `voice_sync.voice_from_row` drops them: Pipecat's lookup catalogue, picker
and curation table never see a hosted row, and nothing here changes what they do.

The rung is derived in ONE place: source -> rate key (`RATE_KEY_OF_SOURCE`) -> rung
(`billing/engine_minutes.CLIENT_RUNG_OF_RATE_KEY`), the same fact publish stamps on the route.

A client may choose a voice an operator ADDED (`origin = operator`) AND ENABLED, that the
engine still lists, whose minute is priced, and — for Studio — whose workspace is set up.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, cast, get_args
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import PRODUCT_LANGUAGES
from apps.api.agents.llm_models import LlmReasonAudience
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voices import (
    ARRIVAL_CURATION_STATE,
    CurationState,
    VoiceOrigin,
)
from apps.api.billing.engine_minutes import (
    BYOK_VOICE_RATE_KEY,
    EngineRateKey,
    client_voice_tier,
)
from apps.api.billing.rates import VALUE_VOICE_TIER, VoiceTier
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine.catalogue import (
    HostedVoice,
    HostedVoiceListing,
    HostedVoiceSource,
    HostsVoices,
)
from apps.api.engine.vendor_http import EngineRejectedError

log = get_logger(__name__)

HOSTED_SOURCES: Final[tuple[HostedVoiceSource, ...]] = get_args(HostedVoiceSource)
_SEPARATOR: Final = ":"

#: The minute rate each source is metered at (`billing/engine_minutes`). The engine's own
#: voices we offer are all in its Studio band (`engine/thinnest.SOLD_VOICE_TIER`).
RATE_KEY_OF_SOURCE: Final[Mapping[HostedVoiceSource, EngineRateKey]] = {
    "engine": "studio",
    "byok": BYOK_VOICE_RATE_KEY,
}

#: The one voice provider the Studio rung is sold on (D-687). A Studio workspace whose key is
#: another provider's would sell a voice nobody priced, so its voices are not synced.
STUDIO_VOICE_PROVIDER: Final = "cartesia"

#: Language tags a listing names, as a client reads them. A tag not here is shown as given.
_LANGUAGE_NAMES: Final[dict[str, str]] = {
    "te": "Telugu",
    "hi": "Hindi",
    "en": "English",
    "en-in": "Indian English",
    "ta": "Tamil",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
}

VoiceScope = Literal["added", "all"]


# --- ids and rungs -------------------------------------------------------------------


def hosted_voice_id(source: HostedVoiceSource, vendor_id: str) -> str:
    """Our catalogue id for an engine-hosted voice: `<source>:<vendor id>`."""
    return f"{source}{_SEPARATOR}{vendor_id}"


@dataclass(frozen=True, slots=True)
class HostedVoiceRef:
    source: HostedVoiceSource
    vendor_id: str

    @property
    def rate_key(self) -> EngineRateKey:
        return RATE_KEY_OF_SOURCE[self.source]


def parse_hosted_voice_id(voice_id: str | None) -> HostedVoiceRef | None:
    """The source and vendor id of a hosted catalogue id, or None for any other id."""
    if not voice_id:
        return None
    prefix, separator, vendor_id = voice_id.partition(_SEPARATOR)
    source = next((s for s in HOSTED_SOURCES if s == prefix), None)
    if not separator or source is None or not vendor_id:
        return None
    return HostedVoiceRef(source=source, vendor_id=vendor_id)


def rung_of_source(engine: str, source: HostedVoiceSource) -> VoiceTier:
    """The client rung a voice from `source` is sold on, through the billing map. A source
    whose rate key is not sold raises: that is a code defect, not a state."""
    rung = client_voice_tier(engine, RATE_KEY_OF_SOURCE[source])
    if rung is None:
        raise ValueError(f"{engine} sells no rung for hosted voices from {source!r}")
    return rung


def thinnest_workspace_for(tenant_id: UUID | str, rung: VoiceTier) -> str | None:
    """THE workspace an agent on `rung` lives in, for `tenant_id`; None is our own.

    Clear agents live in our developer workspace, where our clones are; Studio agents in the
    one customer workspace whose own voice key is our Cartesia key (`Settings.
    thinnest_studio_workspace_id`). A workspace per (tenant, rung) is a change to this one
    function. Refuses when Studio is asked for and no Studio workspace is set up.
    """
    del tenant_id  # one shared Studio workspace today (D-687)
    if rung == VALUE_VOICE_TIER:
        return None
    workspace = get_settings().thinnest_studio_workspace_id
    if not workspace:
        raise studio_workspace_missing()
    return workspace


def studio_workspace_missing() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="engine_studio_workspace_missing",
        title="Studio voices are not set up yet",
        detail="Studio voices run in a part of the voice platform that has not been set up "
        "for this deployment, so no agent can be put on one yet.",
        remediation="Choose a Clear voice, or contact us to have Studio voices set up.",
    )


def studio_workspace_ready() -> bool:
    """Is a Studio workspace configured? The cheap answer the rate card and the picker read;
    the publish path asks the engine for the live key state as well."""
    return bool(get_settings().thinnest_studio_workspace_id)


def rungs_awaiting_setup(engine: str) -> frozenset[VoiceTier]:
    """The rungs `engine` sells whose voices cannot be spoken until a setup step is done:
    the own-voice-key rung while no Studio workspace is set up (D-687)."""
    rung = client_voice_tier(engine, BYOK_VOICE_RATE_KEY)
    return frozenset({rung}) if rung is not None and not studio_workspace_ready() else frozenset()


def language_note(row: PlatformVoiceCatalogEntry) -> str:
    """A client's sentence about what language the voice speaks, from the listing's tag."""
    tag = (row.accent or "").strip()
    name = _LANGUAGE_NAMES.get(tag.lower(), _LANGUAGE_NAMES.get(tag.split("-")[0].lower(), tag))
    ref = parse_hosted_voice_id(row.voice_id)
    if ref is not None and ref.source == "engine":
        # list-voices.md:7: "Every voice speaks every supported language; the agent's
        # language decides which." The tag is the accent the voice carries.
        return (
            f"Speaks the agent's language, with an accent: {name}."
            if name
            else "Speaks the agent's language."
        )
    return f"Speaks {name}." if name else "The voice provider does not say which language."


def _product_languages(source: HostedVoiceSource, tag: str | None) -> list[str]:
    if source == "engine":
        return list(PRODUCT_LANGUAGES)
    base = (tag or "").split("-")[0].lower()
    return [language for language in PRODUCT_LANGUAGES if language.split("-")[0] == base]


# --- the sync ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HostedSyncResult:
    """`voice_sync.VoiceSyncResult`'s four numbers for one hosted sync."""

    seen: int
    written: int
    pruned: int
    #: Why the Studio half was not read, or None when it was.
    studio_skipped_reason: str | None = None


def _row_values(voice: HostedVoice, *, provider: str, stamp: datetime) -> dict[str, object]:
    return {
        "voice_id": hosted_voice_id(voice.source, voice.voice_id),
        "engine_voice_id": voice.voice_id,
        "label": voice.label,
        "tts_model": voice.source,
        "provider": provider,
        "languages": _product_languages(voice.source, voice.language),
        "is_custom": voice.is_custom,
        "accent": voice.language,
        "description": voice.description,
        "synced_at": stamp,
    }


async def _apply_listing(
    session: AsyncSession,
    listing: HostedVoiceListing,
    *,
    source: HostedVoiceSource,
    provider: str,
    stamp: datetime,
) -> tuple[int, int]:
    """Upsert one listing's voices and withdraw this source's rows it no longer names.
    Curation and origin are never written here, and an empty listing is refused upstream."""
    rows = [_row_values(voice, provider=provider, stamp=stamp) for voice in listing.voices]
    statement = insert(PlatformVoiceCatalogEntry).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[PlatformVoiceCatalogEntry.voice_id],
            set_={
                "engine_voice_id": statement.excluded.engine_voice_id,
                "label": statement.excluded.label,
                "tts_model": statement.excluded.tts_model,
                "provider": statement.excluded.provider,
                "languages": statement.excluded.languages,
                "is_custom": statement.excluded.is_custom,
                "accent": statement.excluded.accent,
                "description": statement.excluded.description,
                "synced_at": statement.excluded.synced_at,
                "withdrawn_at": None,
            },
        )
    )
    # Both listings are single, unpaged answers (list-voices.md:346; list-byok-voices.md:
    # 340-379), so a listing that read is a whole one and may withdraw what it no longer names.
    result = await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(
            PlatformVoiceCatalogEntry.voice_id.startswith(f"{source}{_SEPARATOR}"),
            PlatformVoiceCatalogEntry.voice_id.not_in([str(row["voice_id"]) for row in rows]),
            PlatformVoiceCatalogEntry.withdrawn_at.is_(None),
        )
        .values(withdrawn_at=stamp)
    )
    pruned = int(result.rowcount or 0)  # type: ignore[attr-defined]
    return len(rows), pruned


def _alert_empty(engine: str, source: HostedVoiceSource) -> None:
    alert(
        "CORE_LOGIC",
        "voice_catalogue_empty",
        detail=(
            f"the voice catalogue sync read no {source} voices from the engine, so the previous "
            "list is still standing. Check the engine credential, the plan (Studio voices are "
            "listed on Pro and above) and run POST /v1/ops/voices/refresh."
        ),
        engine=engine,
        source=source,
    )


async def _studio_listing(engine: HostsVoices, workspace: str) -> HostedVoiceListing | None:
    """The Studio workspace's own-key voices, or None when the engine says the workspace is
    not on its own keys (`409`, list-byok-voices.md:7): a set-up step, not an outage."""
    try:
        return await engine.list_own_key_voices(workspace=workspace)
    except EngineRejectedError as exc:
        if exc.vendor_status != 409:
            raise
        return None


async def sync_hosted_voices(
    session: AsyncSession, engine: HostsVoices, *, engine_name: str, now: datetime | None = None
) -> HostedSyncResult:
    """Read the engine's own voices, and the Studio workspace's own-key voices when it is
    set up, into `platform_voice_catalog`. IDEMPOTENT; the caller commits.

    A missing Studio workspace is a stated skip, not a failure, so the hourly job does not
    alarm on a deployment that has not set Studio up.
    """
    name = engine_name
    stamp = now or datetime.now(UTC)
    seen = written = pruned = 0
    own = await engine.list_hosted_voices()
    seen += len(own.voices)
    if own.voices:
        added, dropped = await _apply_listing(
            session, own, source="engine", provider=name, stamp=stamp
        )
        written += added
        pruned += dropped
    else:
        _alert_empty(name, "engine")

    workspace = get_settings().thinnest_studio_workspace_id
    skipped: str | None = None
    if not workspace:
        skipped = "the Studio workspace is not set up, so there are no Studio voices to read"
    else:
        studio = await _studio_listing(engine, workspace)
        seen += len(studio.voices) if studio is not None else 0
        if studio is None:
            skipped = (
                "the Studio workspace is not running on our voice key yet, so its voices "
                "cannot be read; run the Studio workspace set-up again"
            )
        elif studio.provider != STUDIO_VOICE_PROVIDER:
            skipped = (
                f"the Studio workspace's voice key is {studio.provider or 'not installed'}, "
                f"not {STUDIO_VOICE_PROVIDER}, so its voices are not offered"
            )
            alert(
                "CORE_LOGIC",
                "studio_voice_key_wrong_provider",
                detail=skipped,
                engine=name,
            )
        elif studio.voices:
            added, dropped = await _apply_listing(
                session, studio, source="byok", provider=STUDIO_VOICE_PROVIDER, stamp=stamp
            )
            written += added
            pruned += dropped
        else:
            _alert_empty(name, "byok")
    log.info(
        "hosted_voices_synced",
        extra={"engine": name, "seen": seen, "written": written, "pruned": pruned},
    )
    return HostedSyncResult(
        seen=seen, written=written, pruned=pruned, studio_skipped_reason=skipped
    )


# --- curation --------------------------------------------------------------------------


def _hosted_rows() -> ColumnElement[bool]:
    return PlatformVoiceCatalogEntry.tts_model.in_(HOSTED_SOURCES)


@dataclass(frozen=True, slots=True)
class HostedVoiceRow:
    """One hosted catalogue row, in our words."""

    voice_id: str
    source: HostedVoiceSource
    vendor_id: str
    label: str
    provider: str
    accent: str | None
    description: str | None
    language_note: str
    is_custom: bool
    state: CurationState
    origin: VoiceOrigin
    synced_at: datetime
    curated_at: datetime | None
    withdrawn_at: datetime | None
    preview_available: bool
    preview_source: str | None
    clone_id: str | None

    @property
    def rate_key(self) -> EngineRateKey:
        return RATE_KEY_OF_SOURCE[self.source]

    @property
    def added(self) -> bool:
        return self.origin == "operator"

    @property
    def offered(self) -> bool:
        """Ground zero of the client offer: added, enabled and still listed."""
        return self.added and self.state == "enabled" and self.withdrawn_at is None


def row_of(entry: PlatformVoiceCatalogEntry) -> HostedVoiceRow:
    """One hosted row. Every caller reads rows filtered to the hosted sources (`_hosted_rows`
    or an id `parse_hosted_voice_id` accepted), and a hosted row stores its source in
    `tts_model`."""
    return HostedVoiceRow(
        voice_id=entry.voice_id,
        source=cast(HostedVoiceSource, entry.tts_model),
        vendor_id=entry.engine_voice_id,
        label=entry.label,
        provider=entry.provider,
        accent=entry.accent,
        description=entry.description,
        language_note=language_note(entry),
        is_custom=entry.is_custom,
        state=cast("CurationState", entry.curation_state),
        origin=cast("VoiceOrigin", entry.origin),
        synced_at=entry.synced_at,
        curated_at=entry.curated_at,
        withdrawn_at=entry.withdrawn_at,
        preview_available=entry.preview_object_key is not None,
        preview_source=entry.preview_source,
        clone_id=entry.engine_clone_id,
    )


async def list_hosted_voices(
    session: AsyncSession, *, scope: VoiceScope = "added"
) -> tuple[HostedVoiceRow, ...]:
    """The hosted rows: those an operator added (default) or every synced one. Still-listed
    first, then Clear before Studio, then label."""
    statement = select(PlatformVoiceCatalogEntry).where(_hosted_rows())
    if scope == "added":
        statement = statement.where(PlatformVoiceCatalogEntry.origin == "operator")
    rows = [row_of(entry) for entry in (await session.execute(statement)).scalars().all()]
    return tuple(
        sorted(
            rows,
            key=lambda r: (r.withdrawn_at is not None, HOSTED_SOURCES.index(r.source), r.label),
        )
    )


async def count_hosted_voices(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(PlatformVoiceCatalogEntry).where(_hosted_rows())
            )
        ).scalar_one()
    )


async def read_hosted_voice(session: AsyncSession, voice_id: str) -> HostedVoiceRow:
    """One hosted row, or 404 for an id that is not a hosted voice we hold."""
    if parse_hosted_voice_id(voice_id) is None:
        raise ProblemError.not_found("Voice", voice_id)
    entry = (
        await session.execute(
            select(PlatformVoiceCatalogEntry).where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise ProblemError.not_found("Voice", voice_id)
    return row_of(entry)


async def add_hosted_voice(session: AsyncSession, *, voice_id: str) -> HostedVoiceRow:
    """Mark a synced voice as ADDED by an operator. It stays in the state it was in (a new
    one arrives disabled), so enabling it is a second, deliberate act after its preview is
    checked. IDEMPOTENT; the caller commits and audits."""
    row = await read_hosted_voice(session, voice_id)
    if row.withdrawn_at is not None:
        raise ProblemError(
            kind="business_rule",
            code="voice_withdrawn",
            title="The voice platform no longer lists this voice",
            detail="A voice the platform has stopped listing cannot be added.",
            remediation="Refresh the voice list, then choose a voice it still lists.",
        )
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(origin="operator")
    )
    return await read_hosted_voice(session, voice_id)


async def set_hosted_curation(
    session: AsyncSession, *, voice_id: str, state: CurationState, now: datetime | None = None
) -> HostedVoiceRow:
    """Enable, disable or archive one hosted voice. Enabling needs it ADDED first, so a
    voice a sync merely read can never reach a picker by a stray click. The caller commits
    and audits."""
    row = await read_hosted_voice(session, voice_id)
    if state == "enabled" and not row.added:
        raise ProblemError(
            kind="business_rule",
            code="voice_not_added",
            title="Add this voice before enabling it",
            detail="Only a voice an operator has added can be offered to clients.",
            remediation="Add the voice, check its preview, then enable it.",
        )
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(curation_state=state, curated_at=now or datetime.now(UTC))
    )
    return await read_hosted_voice(session, voice_id)


async def record_clone(
    session: AsyncSession,
    *,
    engine: str,
    vendor_voice_id: str,
    clone_id: str,
    label: str,
    language: str | None,
    description: str | None,
    now: datetime | None = None,
) -> HostedVoiceRow:
    """Write a clone we just made as an ADDED, not yet enabled catalogue row. An existing
    row (a sync saw it first) is adopted, keeping its curation state."""
    stamp = now or datetime.now(UTC)
    voice = HostedVoice(
        voice_id=vendor_voice_id,
        label=label,
        source="engine",
        is_custom=True,
        language=language,
        description=description,
    )
    values = {
        **_row_values(voice, provider=engine, stamp=stamp),
        "origin": "operator",
        "curation_state": ARRIVAL_CURATION_STATE,
        "engine_clone_id": clone_id,
    }
    statement = insert(PlatformVoiceCatalogEntry).values(values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[PlatformVoiceCatalogEntry.voice_id],
            set_={
                "origin": "operator",
                "engine_clone_id": clone_id,
                "label": statement.excluded.label,
                "is_custom": True,
                "withdrawn_at": None,
            },
        )
    )
    return await read_hosted_voice(session, hosted_voice_id("engine", vendor_voice_id))


async def withdraw_hosted_voice(
    session: AsyncSession, *, voice_id: str, now: datetime | None = None
) -> None:
    """Stamp a voice as no longer on the platform (a deleted clone) and take it off offer."""
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(withdrawn_at=now or datetime.now(UTC), curation_state="archived")
    )


async def record_preview(
    session: AsyncSession, *, voice_id: str, object_key: str, content_type: str, source: str
) -> HostedVoiceRow:
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(
            preview_object_key=object_key,
            preview_content_type=content_type,
            preview_source=source,
        )
    )
    return await read_hosted_voice(session, voice_id)


async def preview_object(
    session: AsyncSession, *, voice_id: str, offered_only: bool
) -> tuple[str, str]:
    """`(object key, content type)` of a voice's stored preview. A client reaches only a
    voice on offer; anything else, and a voice with no preview, is a 404, so the route does
    not say which voices exist off the picker."""
    if parse_hosted_voice_id(voice_id) is None:
        raise ProblemError.not_found("Voice preview")
    entry = (
        await session.execute(
            select(PlatformVoiceCatalogEntry).where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        )
    ).scalar_one_or_none()
    if (
        entry is None
        or entry.preview_object_key is None
        or entry.preview_content_type is None
        or (offered_only and not row_of(entry).offered)
    ):
        raise ProblemError.not_found("Voice preview")
    return entry.preview_object_key, entry.preview_content_type


# --- the offer -------------------------------------------------------------------------


def hosted_voice_unofferable_reason(
    row: HostedVoiceRow,
    *,
    attested: Set[str],
    studio_ready: bool,
    voice_key_priced: bool,
    platform: str,
    audience: LlmReasonAudience,
) -> str | None:
    """Why an ADDED, ENABLED voice cannot be chosen right now, or None. Grounds in order of
    whose problem they are: Studio not set up, the minute not priced, then — for Studio —
    our voice provider's own synthesis not priced, which is a second cost on that minute
    (hard rule 7; `voice_offer.tts_price_is_billable`, the same door Pipecat's Cartesia
    voices go through)."""
    if row.source == "byok" and not studio_ready:
        if audience == "client":
            return "Not available yet: Studio voices are being set up."
        return (
            "The Studio workspace is not set up, so no agent can speak a Studio voice. Set "
            "it up under Voices, Studio workspace."
        )
    if row.rate_key not in attested:
        if audience == "client":
            return "Not available yet: this voice has not been priced."
        return (
            f"No rupee-per-minute rate is attested for {platform}'s {row.rate_key!r} minute, "
            "so a call on this voice cannot be metered. Attest it in the ops console."
        )
    if row.source == "byok" and not voice_key_priced:
        if audience == "client":
            return "Not available yet: this voice has not been priced."
        return (
            "No per-character price is attested for our Cartesia key, and a Studio minute "
            "carries its synthesis as a second cost. Attest the Cartesia TTS price in the ops "
            "console."
        )
    return None


#: The agent's chosen hosted voice, when the catalogue says the engine no longer has it.
#: `agents` is read on the caller's tenant session; the catalogue has no tenant.
_AGENT_VOICE_WITHDRAWN_SQL: Final = (
    "SELECT 1 FROM agents a JOIN platform_voice_catalog c ON c.voice_id = a.engine_voice_id "
    "WHERE a.id = :aid AND c.withdrawn_at IS NOT NULL"
)


async def agent_voice_withdrawn(session: AsyncSession, *, agent_id: UUID) -> bool:
    """Is this agent set to a hosted voice the engine no longer lists (a deleted clone)?"""
    return (
        await session.execute(text(_AGENT_VOICE_WITHDRAWN_SQL), {"aid": agent_id})
    ).first() is not None


async def offered_hosted_voices(session: AsyncSession) -> tuple[HostedVoiceRow, ...]:
    """Every voice on the client picker's list: added, enabled, still listed."""
    return tuple(row for row in await list_hosted_voices(session) if row.offered)


__all__ = [
    "HOSTED_SOURCES",
    "RATE_KEY_OF_SOURCE",
    "STUDIO_VOICE_PROVIDER",
    "HostedSyncResult",
    "HostedVoiceRef",
    "HostedVoiceRow",
    "VoiceScope",
    "add_hosted_voice",
    "agent_voice_withdrawn",
    "count_hosted_voices",
    "hosted_voice_id",
    "hosted_voice_unofferable_reason",
    "language_note",
    "list_hosted_voices",
    "offered_hosted_voices",
    "parse_hosted_voice_id",
    "preview_object",
    "read_hosted_voice",
    "record_clone",
    "record_preview",
    "rung_of_source",
    "rungs_awaiting_setup",
    "set_hosted_curation",
    "studio_workspace_missing",
    "studio_workspace_ready",
    "sync_hosted_voices",
    "thinnest_workspace_for",
    "withdraw_hosted_voice",
]
