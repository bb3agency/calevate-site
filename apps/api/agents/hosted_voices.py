"""Voices an ENGINE hosts, curated by an operator and offered to clients (D-687, D-688).

On an engine that dictates the voice leg and hosts voices of its own (`engine/catalogue.
HostsVoices`, ThinnestAI today) the voice catalogue is NOT the cached `<model>:<speaker>`
catalogue. Its rows live in the same table (`platform_voice_catalog`) and are told apart by
their id, which is namespaced by where the voice comes from:

* `engine:<id>` — the engine's own voice, or a voice our account cloned on it. Every band the
  engine lists is cached with its band (`vendor_band`) so the operator sees the whole
  platform, but only the band sold as Clear (`Settings.thinnest_clear_voice_band`, see
  `sold_hosted_band`) can be added and offered. Our clones are in the ThinnestAI Studio band, so
  they are offerable only while Clear is sold on that band. Metered at that band's rate.
* `byok:<id>` — a voice of our Cartesia key, switched on as the voice-only own key (BYOK scope
  `voice`) in our developer workspace, where trial agents live (D-727), and in the customer
  workspace of each paying client that uses Studio (D-717). Metered at `byok_voice` plus
  Cartesia's own charge to our key, sold as STUDIO. Listed and previewed in the first of those
  that answers ready (`studio_listing_workspace`); the vendor refuses both in a workspace not
  on its own keys (`list-byok-voices.md:7`, `preview-byok-voice.md:396-397`).

Every agent says whether it speaks on our own voice key (D-688): Clear agents `byok: off`,
Studio agents `byok: workspace`.

Neither prefix is a member of `voices.TtsModel`, and the rows store the source in
`tts_model`, so `voice_sync.voice_from_row` drops them: the cached lookup catalogue
never sees a hosted row.

The rung is derived in ONE place: a row's rate key (`HostedVoiceRow.rate_key`: its band, or
`byok_voice`) -> rung (`billing/engine_minutes.client_rungs`), the same fact publish stamps
on the route.

A client may choose a voice in a sold band that an operator ADDED (`origin = operator`) AND
ENABLED, that the engine still lists, whose minute is priced, and — for Studio — once its
voices have been listed and the account's Studio publish would go through as the last checks
recorded (`studio_voices.studio_open_to`, D-806).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Set
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Final, Literal, cast, get_args
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import BUILT_LANGUAGES
from apps.api.agents.llm_models import LlmReasonAudience
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_curation import VoiceUse, use_of
from apps.api.agents.voices import (
    ARRIVAL_CURATION_STATE,
    CurationState,
    VoiceOrigin,
)
from apps.api.billing.engine_minutes import (
    BYOK_VOICE_RATE_KEY,
    OWN_VOICE_RATE_KEYS,
    EngineRateKey,
    client_voice_tier,
)
from apps.api.billing.rates import VoiceTier
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine.catalogue import (
    HostedVoice,
    HostedVoiceBand,
    HostedVoiceListing,
    HostedVoiceSource,
    HostsVoices,
    OwnVoiceKeyState,
)
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.tenancy.engine_workspace import studio_workspaces

log = get_logger(__name__)

HOSTED_SOURCES: Final[tuple[HostedVoiceSource, ...]] = get_args(HostedVoiceSource)
_SEPARATOR: Final = ":"

#: The one voice provider the Studio rung is sold on (D-687). An own voice key of another
#: provider would sell a voice nobody priced, so its voices are not synced.
STUDIO_VOICE_PROVIDER: Final = "cartesia"

#: The console's name for the setting that picks the band sold as Clear.
CLEAR_BAND_SETTING_LABEL: Final = "ThinnestAI voice band sold as Clear"

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

#: The band every clone is in (channels/voice-clone.md:10-12): a clone is offerable as Clear
#: only while Clear is sold on that band.
CLONE_BAND: Final[HostedVoiceBand] = "studio"

VoiceScope = Literal["added", "all"]


# --- ids, bands and rungs ------------------------------------------------------------


def hosted_voice_id(source: HostedVoiceSource, vendor_id: str) -> str:
    """Our catalogue id for an engine-hosted voice: `<source>:<vendor id>`."""
    return f"{source}{_SEPARATOR}{vendor_id}"


@dataclass(frozen=True, slots=True)
class HostedVoiceRef:
    source: HostedVoiceSource
    vendor_id: str


def parse_hosted_voice_id(voice_id: str | None) -> HostedVoiceRef | None:
    """The source and vendor id of a hosted catalogue id, or None for any other id."""
    if not voice_id:
        return None
    prefix, separator, vendor_id = voice_id.partition(_SEPARATOR)
    source = next((s for s in HOSTED_SOURCES if s == prefix), None)
    if not separator or source is None or not vendor_id:
        return None
    return HostedVoiceRef(source=source, vendor_id=vendor_id)


def sold_hosted_band() -> HostedVoiceBand:
    """The engine's voice band sold as Clear (`Settings.thinnest_clear_voice_band`, D-688)."""
    return get_settings().thinnest_clear_voice_band


def source_rate_key(source: HostedVoiceSource) -> EngineRateKey:
    """The minute rate a SOLD voice from `source` is metered at: the band sold as Clear for
    the engine's own voices, `byok_voice` for a voice of our own key."""
    return BYOK_VOICE_RATE_KEY if source == "byok" else sold_hosted_band()


def rung_of_source(engine: str, source: HostedVoiceSource) -> VoiceTier:
    """The client rung a sold voice from `source` is sold on, through the billing map. A
    source whose rate key is not sold raises: that is a code defect, not a state."""
    rung = client_voice_tier(engine, source_rate_key(source))
    if rung is None:
        raise ValueError(f"{engine} sells no rung for hosted voices from {source!r}")
    return rung


#: Raised when the engine listed voices but none in the band sold as Clear: on ThinnestAI the
#: account's plan does not list it (Studio needs Pro, list-voices.md:7). Distinct from
#: `voice_catalogue_empty`, which is the engine answering with nothing at all.
NO_SOLD_BAND_CODE: Final = "voice_catalogue_no_studio_band"

#: How the console names each of ThinnestAI's bands, admin screens only. Always prefixed and
#: suffixed, because our own Studio RUNG (Cartesia on our key) shares the word "Studio" and
#: not the mechanism (D-717); a client never sees these.
BAND_LABELS: Final[Mapping[HostedVoiceBand, str]] = {
    "standard": "ThinnestAI Standard band",
    "premium": "ThinnestAI Premium band",
    "studio": "ThinnestAI Studio band",
}


def band_is_sold(source: HostedVoiceSource, band: str | None) -> bool:
    """May a voice from `source` in the engine's `band` be added and offered? An own-key voice
    is priced by its own source; one of the engine's only in the band sold as Clear."""
    return source == "byok" or band == sold_hosted_band()


def no_sold_band_sentence(listed: int) -> str:
    """The operator's sentence for a listing with voices but none in the band sold as Clear."""
    band = sold_hosted_band()
    sentence = (
        f"ThinnestAI listed {listed} voice(s) but none in the {BAND_LABELS[band]}, the "
        f"band sold as Clear ('{CLEAR_BAND_SETTING_LABEL}' in the ops console)."
    )
    if band == "studio":
        return f"{sentence} {STUDIO_NEEDS_PRO}"
    return f"{sentence} Check the account on ThinnestAI, then refresh."


#: Why no ThinnestAI Studio-tier voice reaches us below Pro, including the one its console
#: lets every plan hear. `GET /voices` lists Studio only on Pro and above, and every id it
#: lists is one an agent can be set to (snapshots/2026-10-08/pages/api-reference/voices/
#: list-voices.md:7, docs.thinnest.ai read 10 Oct 2026); the free Studio voice "previews"
#: (guides/how-your-agent-sounds.md:132-134), it is not settable. The last sentence is there
#: because our own Studio rung (Cartesia on our key) shares the word and not the mechanism.
STUDIO_NEEDS_PRO: Final = (
    "ThinnestAI lists its Studio band voices and clones only on its Pro plan and above. The "
    "one Studio band voice its console lets every plan play is a listening sample: it is not "
    "in the voice list below Pro, so no agent can be set to it. Upgrade the ThinnestAI plan and "
    "press Refresh, or sell Clear on Premium. Switching on Studio voices (our Cartesia key) "
    "does not change this."
)


async def assert_clear_band_listed(session: AsyncSession, band: object) -> None:
    """Refuse selling Clear on a band the last sync proved this account is not listed.

    Decided on what the platform answered rather than on the plan setting, so it holds
    whichever way the vendor behaves: refused only while the cache holds the engine's voices
    and none in `band`. A deployment never synced, or one whose engine hosts no voices,
    proves nothing and the write is allowed."""
    bands = await count_listed_bands(session)
    listed = sum(bands.values())
    if not listed or bands.get(cast(HostedVoiceBand, band)):
        return
    label = BAND_LABELS.get(cast(HostedVoiceBand, band), str(band))
    detail = (
        f"The last voice refresh read {listed} ThinnestAI voice(s) ({_band_summary(bands)}) "
        f"and none in the {label}, so Clear would have no voice to sell."
    )
    raise ProblemError(
        kind="business_rule",
        code="voice_band_not_listed",
        title=f"No {label} voice is listed on this account",
        detail=f"{detail} {STUDIO_NEEDS_PRO}" if band == "studio" else detail,
        remediation=(
            "Upgrade the voice platform plan, press Refresh on the Voices page, then set this "
            "again."
        ),
    )


def band_not_sold(row: HostedVoiceRow) -> ProblemError:
    sold = BAND_LABELS[sold_hosted_band()]
    tier = f"the {BAND_LABELS[row.band]}" if row.band is not None else "no band we sell"
    return ProblemError(
        kind="business_rule",
        code="voice_band_not_sold",
        title=f"Only {sold} voices are sold as Clear",
        detail=(
            f"Only {sold} voices are sold as Clear on this platform, and {row.label} is in {tier}."
        ),
        remediation=(
            f"Choose a {sold} voice, or change '{CLEAR_BAND_SETTING_LABEL}' in the ops "
            "console and attest that band's rate."
        ),
    )


def own_voice_key_ready(state: OwnVoiceKeyState) -> bool:
    """Does the workspace speak on our Cartesia key, for the voice only? The one test of the
    vendor's own report, used by the sync, the publish gate and the console."""
    return state.speaks_on_own_voice and state.voice_provider == STUDIO_VOICE_PROVIDER


_STUDIO_VOICES_LISTED_SQL: Final = (
    "SELECT EXISTS (SELECT 1 FROM platform_voice_catalog WHERE tts_model = 'byok' "
    "AND provider = :provider AND withdrawn_at IS NULL)"
)


_LIVE_STUDIO_ROUTES_SQL: Final = (
    "SELECT count(*) FROM engine_agent_routes WHERE active AND engine = :engine "
    "AND engine_rate_key = ANY(:studio_keys)"
)


async def live_studio_agents(session: AsyncSession, *, engine: str) -> int:
    """Published vendor agents on a Studio voice (their route carries the own-voice-key rate
    key), experiment arms included: what our voice key being off strands."""
    return int(
        (
            await session.execute(
                text(_LIVE_STUDIO_ROUTES_SQL),
                {"engine": engine, "studio_keys": sorted(OWN_VOICE_RATE_KEYS)},
            )
        ).scalar_one()
    )


async def studio_voices_listed(session: AsyncSession) -> bool:
    """Has a ready workspace listed our own-key voices (`sync_hosted_voices`)? Necessary for
    offering Studio, not sufficient: whether an account's Studio publish would go through is
    `studio_voices.studio_open_to`."""
    return bool(
        (
            await session.execute(
                text(_STUDIO_VOICES_LISTED_SQL), {"provider": STUDIO_VOICE_PROVIDER}
            )
        ).scalar_one()
    )


def rungs_awaiting_setup(engine: str, *, studio_ready: bool) -> frozenset[VoiceTier]:
    """The rungs `engine` sells whose voices cannot be spoken until a setup step is done:
    the own-voice-key rung until Studio is open (`studio_voices.studio_open_to`)."""
    rung = client_voice_tier(engine, BYOK_VOICE_RATE_KEY)
    return frozenset({rung}) if rung is not None and not studio_ready else frozenset()


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
        return list(BUILT_LANGUAGES)
    base = (tag or "").split("-")[0].lower()
    return [language for language in BUILT_LANGUAGES if language.split("-")[0] == base]


# --- the sync ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HostedSyncResult:
    """`voice_sync.VoiceSyncResult`'s four numbers for one hosted sync."""

    seen: int
    written: int
    pruned: int
    #: Why the Studio half was not read, or None when it was.
    studio_skipped_reason: str | None = None
    #: How many voices the engine's own listing held, and how many of them per band.
    engine_listed: int = 0
    bands: Mapping[HostedVoiceBand, int] = field(default_factory=dict)
    #: Voices the engine listed in a tier we do not read, by the engine's word.
    unread_bands: Mapping[str, int] = field(default_factory=dict)

    @property
    def sold_band_missing(self) -> bool:
        """The engine listed voices of its own, none of them in the band sold as Clear."""
        return self.engine_listed > 0 and not self.bands.get(sold_hosted_band())


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
        "vendor_band": voice.band,
        "gender": voice.gender,
        "synced_at": stamp,
    }


def _still_listed(source: HostedVoiceSource) -> ColumnElement[bool]:
    return PlatformVoiceCatalogEntry.voice_id.startswith(
        f"{source}{_SEPARATOR}"
    ) & PlatformVoiceCatalogEntry.withdrawn_at.is_(None)


async def _apply_listing(
    session: AsyncSession,
    listing: HostedVoiceListing,
    *,
    source: HostedVoiceSource,
    provider: str,
    stamp: datetime,
) -> tuple[int, int]:
    """Upsert one listing's voices and, when the listing is whole, withdraw this source's rows
    it no longer names. Curation and origin are never written here, and an empty listing is
    refused upstream."""
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
                "vendor_band": statement.excluded.vendor_band,
                "gender": statement.excluded.gender,
                "synced_at": statement.excluded.synced_at,
                "withdrawn_at": None,
            },
        )
    )
    # A short listing (`complete` False: the own-key list when the voice provider was slow)
    # leaves out voices that still exist, and withdrawing them would take voices clients
    # chose off their agents; the caller alarms instead.
    if not listing.complete:
        return len(rows), 0
    result = await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(
            _still_listed(source),
            PlatformVoiceCatalogEntry.voice_id.not_in([str(row["voice_id"]) for row in rows]),
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
            "list is still standing. Check the engine credential and run "
            "POST /v1/ops/voices/refresh."
        ),
        engine=engine,
        source=source,
    )


#: A listing the engine marked as possibly short was applied without withdrawing anything.
PARTIAL_LISTING_CODE: Final = "voice_catalogue_partial"


def _alert_partial(engine: str, source: HostedVoiceSource, *, listed: int) -> None:
    alert(
        "CORE_LOGIC",
        PARTIAL_LISTING_CODE,
        detail=(
            f"the voice platform said its {source} voice list may be short ({listed} listed), "
            "so the voices it named were refreshed and none was withdrawn. The next hourly "
            "sync asks again; if this repeats, run POST /v1/ops/voices/refresh."
        ),
        engine=engine,
        source=source,
    )


def _band_summary(bands: Mapping[HostedVoiceBand, int]) -> str:
    """Counts per ThinnestAI band, e.g. "ThinnestAI bands 1 Standard, 1 Premium, 0 Studio"."""
    counts = ", ".join(
        f"{bands.get(band, 0)} {band.capitalize()}" for band in get_args(HostedVoiceBand)
    )
    return f"ThinnestAI bands {counts}"


def hosted_refresh_note(result: HostedSyncResult, *, offered: int) -> str:
    """The one sentence the console prints after a refresh on an engine that hosts its voices.
    The engine answered (a refused credential raises before this), so no branch here sends
    the operator to the credential."""
    sold = BAND_LABELS[sold_hosted_band()]
    if result.engine_listed == 0:
        note = (
            "The voice platform accepted the request but listed no voices at all, so nothing "
            f"was changed and the cached voices stand ({offered} offered to clients). Check the "
            "account on the voice platform, then refresh again."
        )
    elif result.sold_band_missing:
        note = (
            f"{no_sold_band_sentence(result.engine_listed)} Listed: "
            f"{_band_summary(result.bands)}. They are cached under 'Every voice on the "
            f"platform', but none can be offered as Clear ({offered} offered to clients)."
        )
    else:
        note = (
            f"ThinnestAI listed {result.engine_listed} voice(s): "
            f"{_band_summary(result.bands)}. Only {sold} voices can be offered as Clear. "
            f"{result.pruned} withdrawn by the platform; {offered} offered to clients. A newly "
            "seen voice must be added and enabled before a client can choose it."
        )
    if result.unread_bands:
        unread = ", ".join(f"{n} in '{tier}'" for tier, n in sorted(result.unread_bands.items()))
        note = f"{note} Also listed in a tier we do not read, so not cached or sellable: {unread}."
    if result.studio_skipped_reason is not None:
        return f"{note} Studio voices: {result.studio_skipped_reason}."
    return note


#: Why the Studio half was not read: no client workspace runs Studio yet, or none answered.
STUDIO_KEY_OFF_REASON: Final = (
    "no client workspace runs Studio and answers ready, so Studio voices were not re-read "
    "(the last listing is kept); name the first Studio client under Voices, Studio ready"
)


@dataclass(frozen=True, slots=True)
class StudioListingWorkspace:
    """Where Studio voices are listed and previewed: a customer workspace id, or None for
    our developer workspace."""

    workspace: str | None


async def studio_listing_workspace(engine: HostsVoices) -> StudioListingWorkspace | None:
    """The workspace that answers ready on our Cartesia key, where Studio voices are listed
    and previewed: our developer workspace first (switched on since D-727), else the
    earliest Studio client workspace. None when none is ready; the vendor answers `409` in
    a workspace not on its own keys (`list-byok-voices.md:7`, `preview-byok-voice.md:396-397`).
    """
    try:
        if own_voice_key_ready(await engine.own_key_state()):
            return StudioListingWorkspace(workspace=None)
    except ProblemError as exc:
        log.warning("studio_listing_workspace_unreadable", extra={"reason": exc.code})
    for row in await studio_workspaces():
        try:
            with in_workspace(row.workspace_id):
                state = await engine.own_key_state()
        except ProblemError as exc:
            log.warning("studio_listing_workspace_unreadable", extra={"reason": exc.code})
            continue
        if own_voice_key_ready(state):
            return StudioListingWorkspace(workspace=row.workspace_id)
    return None


async def _studio_listing(engine: HostsVoices) -> HostedVoiceListing | None:
    """Our own-key voices as a ready workspace lists them, or None when none is ready (a
    set-up state, not an outage, so the hourly job does not alarm on it)."""
    found = await studio_listing_workspace(engine)
    if found is None:
        return None
    try:
        with in_workspace(found.workspace):
            return await engine.list_own_key_voices()
    except EngineRejectedError as exc:
        if exc.vendor_status != 409:
            raise
        return None


async def sync_hosted_voices(
    session: AsyncSession, engine: HostsVoices, *, engine_name: str, now: datetime | None = None
) -> HostedSyncResult:
    """Read the engine's own voices, and our own-key voices from a Studio client workspace,
    into `platform_voice_catalog`. IDEMPOTENT; the caller commits.

    No Studio workspace ready is a stated skip that KEEPS the Studio rows last listed: not
    being able to read the list is not the list being empty, and every Studio workspace
    holds the same key, so the voices it reaches are the same. A per-workspace fault is the
    hourly Studio check's alarm (`workers/studio_voice_key.sweep_studio_workspaces`).

    Every band the engine lists is cached. A listing with voices but none in the band sold as
    Clear is applied (it is the vendor's whole, true answer, and the ids it stops listing are
    ones an agent can no longer be set to) and raises `NO_SOLD_BAND_CODE`, an `attention`
    alarm rather than `voice_catalogue_empty`: the credential works, and the fix is the plan
    or the setting.
    """
    name = engine_name
    stamp = now or datetime.now(UTC)
    seen = written = pruned = 0
    own = await engine.list_hosted_voices()
    seen += len(own.voices)
    bands: dict[HostedVoiceBand, int] = dict(
        Counter(voice.band for voice in own.voices if voice.band is not None)
    )
    if own.voices:
        added, dropped = await _apply_listing(
            session, own, source="engine", provider=name, stamp=stamp
        )
        written += added
        pruned += dropped
        if not bands.get(sold_hosted_band()):
            alert(
                "CORE_LOGIC",
                "voice_catalogue_no_studio_band",
                detail=no_sold_band_sentence(len(own.voices)),
                engine=name,
            )
    else:
        _alert_empty(name, "engine")

    skipped: str | None = None
    studio = await _studio_listing(engine)
    if studio is None:
        skipped = STUDIO_KEY_OFF_REASON
    else:
        seen += len(studio.voices)
        if studio.provider != STUDIO_VOICE_PROVIDER:
            skipped = (
                f"our own voice key is {studio.provider or 'not installed'}, not "
                f"{STUDIO_VOICE_PROVIDER}, so its voices are not offered"
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
            if not studio.complete:
                _alert_partial(name, "byok", listed=len(studio.voices))
        else:
            _alert_empty(name, "byok")
    log.info(
        "hosted_voices_synced",
        extra={
            "engine": name,
            "seen": seen,
            "written": written,
            "pruned": pruned,
            "bands": dict(bands),
            "unread_bands": dict(own.unread_bands),
        },
    )
    return HostedSyncResult(
        seen=seen,
        written=written,
        pruned=pruned,
        studio_skipped_reason=skipped,
        engine_listed=len(own.voices),
        bands=bands,
        unread_bands=dict(own.unread_bands),
    )


# --- curation --------------------------------------------------------------------------


def _hosted_rows() -> ColumnElement[bool]:
    return PlatformVoiceCatalogEntry.tts_model.in_(HOSTED_SOURCES)


#: What a consent record covers (D-721): the founder's decision, recorded on every record so
#: a later change of wording cannot silently widen an old consent.
CLONE_CONSENT_SCOPE: Final = "Calls made by Calevate clients' agents."


@dataclass(frozen=True, slots=True)
class CloneConsent:
    """A real person's recorded consent to their cloned voice being offered (D-721)."""

    speaker_name: str
    statement: str
    given_on: date
    scope: str
    recorded_by: UUID
    recorded_at: datetime
    has_document: bool


@dataclass(frozen=True, slots=True)
class HostedVoiceRow:
    """One hosted catalogue row, in our words."""

    voice_id: str
    source: HostedVoiceSource
    vendor_id: str
    #: What clients see: the operator's `display_label` when set, else the provider's name.
    label: str
    #: The provider's own name for the voice, as the sync last read it.
    vendor_label: str
    display_label: str | None
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
    #: The engine's price band for one of its own voices; None for an own-key voice.
    band: HostedVoiceBand | None
    gender: str | None
    languages: tuple[str, ...]
    #: Marked by an operator as a clone of a real person's voice.
    person_clone: bool
    consent: CloneConsent | None

    @property
    def clone_cleared(self) -> bool:
        """Not a person's clone, or one with both a consent record and a name of our own
        (`clone_offer_refusal`)."""
        return not self.person_clone or (
            self.consent is not None and self.display_label is not None
        )

    @property
    def rate_key(self) -> EngineRateKey:
        """The minute rate this voice is metered at: its own band (an engine voice), or
        `byok_voice`. A band-less engine row is never sold, so its key is the sold band's."""
        if self.source == "byok":
            return BYOK_VOICE_RATE_KEY
        return self.band or sold_hosted_band()

    @property
    def added(self) -> bool:
        return self.origin == "operator"

    @property
    def sold(self) -> bool:
        """In a band we sell: an own-key voice, or one of the engine's in the sold band."""
        return band_is_sold(self.source, self.band)

    @property
    def keepable(self) -> bool:
        """An agent already on this voice may keep it and be republished on it (D-880):
        sold, still listed, and, for a person's clone, consented to and renamed. Whether an
        operator still OFFERS it does not matter to an agent that chose it while it was."""
        return self.sold and self.withdrawn_at is None and self.clone_cleared

    @property
    def offered(self) -> bool:
        """Ground zero of the client offer: keepable, and added and enabled."""
        return self.keepable and self.added and self.state == "enabled"


def row_of(entry: PlatformVoiceCatalogEntry) -> HostedVoiceRow:
    """One hosted row. Every caller reads rows filtered to the hosted sources (`_hosted_rows`
    or an id `parse_hosted_voice_id` accepted), and a hosted row stores its source in
    `tts_model`."""
    consent = None
    if (
        entry.consent_speaker_name is not None
        and entry.consent_statement is not None
        and entry.consent_given_on is not None
        and entry.consent_scope is not None
        and entry.consent_recorded_by is not None
        and entry.consent_recorded_at is not None
    ):
        consent = CloneConsent(
            speaker_name=entry.consent_speaker_name,
            statement=entry.consent_statement,
            given_on=entry.consent_given_on,
            scope=entry.consent_scope,
            recorded_by=entry.consent_recorded_by,
            recorded_at=entry.consent_recorded_at,
            has_document=entry.consent_document_key is not None,
        )
    return HostedVoiceRow(
        voice_id=entry.voice_id,
        source=cast(HostedVoiceSource, entry.tts_model),
        vendor_id=entry.engine_voice_id,
        label=entry.display_label or entry.label,
        vendor_label=entry.label,
        display_label=entry.display_label,
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
        # The CHECK `ck_platform_voice_catalog_vendor_band` holds the vocabulary.
        band=cast("HostedVoiceBand | None", entry.vendor_band),
        gender=entry.gender,
        languages=tuple(entry.languages or ()),
        person_clone=entry.person_clone,
        consent=consent,
    )


async def list_hosted_voices(
    session: AsyncSession, *, scope: VoiceScope = "added"
) -> tuple[HostedVoiceRow, ...]:
    """The hosted rows: those an operator added (default) or every synced one. Still-listed
    first, then Clear before Studio, then the sold band before the rest, then label."""
    statement = select(PlatformVoiceCatalogEntry).where(_hosted_rows())
    if scope == "added":
        statement = statement.where(PlatformVoiceCatalogEntry.origin == "operator")
    rows = [row_of(entry) for entry in (await session.execute(statement)).scalars().all()]
    return tuple(
        sorted(
            rows,
            key=lambda r: (
                r.withdrawn_at is not None,
                HOSTED_SOURCES.index(r.source),
                not r.sold,
                r.label,
            ),
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


async def count_listed_bands(session: AsyncSession) -> dict[HostedVoiceBand, int]:
    """How many of the engine's own voices it still lists, per band."""
    rows = await session.execute(
        select(PlatformVoiceCatalogEntry.vendor_band, func.count())
        .where(
            PlatformVoiceCatalogEntry.tts_model == "engine",
            PlatformVoiceCatalogEntry.withdrawn_at.is_(None),
            PlatformVoiceCatalogEntry.vendor_band.is_not(None),
        )
        .group_by(PlatformVoiceCatalogEntry.vendor_band)
    )
    return {cast(HostedVoiceBand, band): int(count) for band, count in rows.all()}


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
    if not row.sold:
        raise band_not_sold(row)
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
    if state == "enabled" and not row.sold:
        # Added while in the sold band, then moved out of it by the engine (a re-tiered voice).
        raise band_not_sold(row)
    if state == "enabled" and (refusal := clone_offer_refusal(row)) is not None:
        raise refusal
    if state == "archived" and row.state != "archived":
        await _refuse_archive_in_use(row)
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(curation_state=state, curated_at=now or datetime.now(UTC))
    )
    return await read_hosted_voice(session, voice_id)


VOICE_IN_USE: Final = "voice_in_use"
#: How many agents the archive refusal names before "and N more"; the drawer lists them all.
_NAMED_IN_REFUSAL: Final = 3


async def _refuse_archive_in_use(row: HostedVoiceRow) -> None:
    """Archiving takes a voice out of every list, so an agent on it would show its client no
    selected voice and leave an operator nothing to find it by. Disabling is the step that
    stops new choices; archiving waits until no agent uses the voice (D-880)."""
    agents = await agents_on_hosted_voice(row.voice_id)
    if not agents:
        return
    named = ", ".join(f"{a.agent_name} ({a.tenant_name})" for a in agents[:_NAMED_IN_REFUSAL])
    more = len(agents) - _NAMED_IN_REFUSAL
    raise ProblemError(
        kind="business_rule",
        code=VOICE_IN_USE,
        title="Agents still use this voice",
        detail=(
            f"{len(agents)} agent(s) use {row.label}: {named}"
            + (f" and {more} more" if more > 0 else "")
            + ". An archived voice is hidden from every list, so these agents would show no voice."
        ),
        remediation=(
            "Move these agents to another voice first, then archive it. To stop new agents "
            "choosing it now, switch off Offered to clients instead."
        ),
    )


VOICE_CLONE_CONSENT_MISSING: Final = "voice_clone_consent_missing"


def clone_consent_missing() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code=VOICE_CLONE_CONSENT_MISSING,
        title="Record the speaker's consent before offering this voice",
        detail="This voice is marked as a cloned voice of a real person, and no record of "
        "that person's consent is on file.",
        remediation="Open the voice, record the speaker's consent, then offer it.",
    )


def clone_offer_refusal(row: HostedVoiceRow) -> ProblemError | None:
    """Why a voice marked as a person's clone cannot be offered yet, or None (D-721). The
    consent comes first; then a name of our own, because clients see `label` and are not told
    whose voice it is."""
    if not row.person_clone:
        return None
    if row.consent is None:
        return clone_consent_missing()
    if row.display_label is None:
        return ProblemError(
            kind="business_rule",
            code="voice_clone_name_missing",
            title="Give this voice the name clients will see",
            detail="Clients see a cloned voice under a name we give it, never the speaker's.",
            remediation="Set the name clients see, then offer it.",
        )
    return None


def name_reveals_speaker(label: str, speaker_name: str) -> bool:
    """Does `label` contain a word of the speaker's name? Words under three letters
    (initials) are ignored, so "Dr" or "K" does not refuse every name."""
    folded = label.casefold()
    return any(len(word) >= 3 and word in folded for word in speaker_name.casefold().split())


def _speaker_named(label: str, speaker_name: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="voice_clone_name_reveals_speaker",
        title="This name says whose voice it is",
        detail=f"Clients see this name, and it contains part of {speaker_name}'s name.",
        remediation="Choose a name that does not identify the speaker.",
    )


async def set_display_label(
    session: AsyncSession, *, voice_id: str, display_label: str | None
) -> HostedVoiceRow:
    """Set or clear the name clients see. The caller commits and audits."""
    row = await read_hosted_voice(session, voice_id)
    cleaned = (display_label or "").strip() or None
    if cleaned is None and row.person_clone and row.state == "enabled":
        raise ProblemError(
            kind="business_rule",
            code="voice_clone_name_missing",
            title="An offered cloned voice keeps its own name",
            detail="Clients would see the speaker's provider name for this voice.",
            remediation="Stop offering the voice first, or give it another name.",
        )
    if (
        cleaned is not None
        and row.consent is not None
        and name_reveals_speaker(cleaned, row.consent.speaker_name)
    ):
        raise _speaker_named(cleaned, row.consent.speaker_name)
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(display_label=cleaned)
    )
    return await read_hosted_voice(session, voice_id)


async def set_person_clone(
    session: AsyncSession, *, voice_id: str, person_clone: bool
) -> HostedVoiceRow:
    """Mark or unmark a voice as a clone of a real person. Marking an offered voice without a
    consent record is refused rather than silently taking it off the picker. Unmarking keeps
    the consent record and its document: they are evidence of what was agreed, and a mark
    set again finds them. The caller commits and audits."""
    row = await read_hosted_voice(session, voice_id)
    if person_clone and row.state == "enabled":
        refusal = clone_offer_refusal(replace(row, person_clone=True))
        if refusal is not None:
            raise refusal
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(person_clone=person_clone)
    )
    return await read_hosted_voice(session, voice_id)


async def record_clone_consent(
    session: AsyncSession,
    *,
    voice_id: str,
    speaker_name: str,
    statement: str,
    given_on: date,
    recorded_by: UUID,
    document_key: str | None,
    now: datetime | None = None,
) -> tuple[HostedVoiceRow, CloneConsent | None]:
    """Record (or replace) the speaker's consent and mark the voice as a person's clone.
    Returns the record it replaced, for the audit row. `document_key` None keeps any document
    already stored, so correcting a typo does not drop the signed copy. The caller commits
    and audits."""
    row = await read_hosted_voice(session, voice_id)
    if row.display_label is not None and name_reveals_speaker(row.display_label, speaker_name):
        raise _speaker_named(row.display_label, speaker_name)
    await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(
            person_clone=True,
            consent_speaker_name=speaker_name,
            consent_statement=statement,
            consent_given_on=given_on,
            consent_scope=CLONE_CONSENT_SCOPE,
            consent_recorded_by=recorded_by,
            consent_recorded_at=now or datetime.now(UTC),
            **({"consent_document_key": document_key} if document_key is not None else {}),
        )
    )
    return await read_hosted_voice(session, voice_id), row.consent


async def consent_document_key(session: AsyncSession, *, voice_id: str) -> str | None:
    return (
        await session.execute(
            select(PlatformVoiceCatalogEntry.consent_document_key).where(
                PlatformVoiceCatalogEntry.voice_id == voice_id
            )
        )
    ).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class AgentOnVoice:
    tenant_id: UUID
    tenant_name: str
    agent_id: UUID
    agent_name: str
    status: str
    use: VoiceUse


#: One tenant's agents set to one hosted voice, live first. Read on the tenant's own session.
_AGENTS_ON_VOICE_SQL: Final = (
    "SELECT id, name, status, engine_agent_ref FROM agents "
    "WHERE engine_voice_id = :v AND deleted_at IS NULL "
    "ORDER BY status = 'live' DESC, name LIMIT :cap"
)
_USE_ORDER: Final[dict[VoiceUse, int]] = {"live": 0, "ready": 1, "not_published": 2}
_LIVE_TENANTS_SQL: Final = "SELECT id, name FROM organizations WHERE deleted_at IS NULL"
#: The most agents the operator's drawer lists for one voice.
MAX_AGENTS_ON_VOICE: Final = 200


async def agents_on_hosted_voice(
    voice_id: str, *, limit: int = MAX_AGENTS_ON_VOICE
) -> list[AgentOnVoice]:
    """Agents across every live tenant set to `voice_id`, at most `limit`, for the operator's
    drawer. The directory-then-tenant walk RLS requires
    (`voice_curation.count_agents_by_engine_voice`); asked for one voice at a time, on demand,
    never on a picker or call path."""
    async with admin_session() as directory:
        tenants = (await directory.execute(text(_LIVE_TENANTS_SQL))).all()
    found: list[AgentOnVoice] = []
    for tenant_id, tenant_name in tenants:
        remaining = limit - len(found)
        if remaining <= 0:
            break
        async with tenant_session(tenant_id) as scoped:
            rows = (
                await scoped.execute(text(_AGENTS_ON_VOICE_SQL), {"v": voice_id, "cap": remaining})
            ).all()
        found.extend(
            AgentOnVoice(
                tenant_id=tenant_id,
                tenant_name=str(tenant_name),
                agent_id=agent_id,
                agent_name=str(name),
                status=str(status),
                use=use_of(str(status), ref),
            )
            for agent_id, name, status, ref in rows
        )
    return sorted(found, key=lambda a: (_USE_ORDER[a.use], a.tenant_name, a.agent_name))


def accent_name(tag: str | None) -> str | None:
    """A listing's language tag as an operator reads it ("Indian English"), or the tag."""
    if not tag:
        return None
    clean = tag.strip()
    return _LANGUAGE_NAMES.get(
        clean.lower(), _LANGUAGE_NAMES.get(clean.split("-")[0].lower(), clean)
    )


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
        # Clones are in the Studio band (channels/voice-clone.md:10-12).
        band=CLONE_BAND,
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
                "vendor_band": CLONE_BAND,
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
    voice_key_priced: bool,
    platform: str,
    audience: LlmReasonAudience,
) -> str | None:
    """Why an ADDED, ENABLED voice cannot be chosen right now, or None. Grounds in order of
    whose problem they are: the minute not priced, then — for Studio — our voice provider's
    own synthesis not priced, which is a second cost on that minute (hard rule 7;
    `voice_offer.tts_price_is_billable`).
    Whether this account's Studio publish would go through is not here: it is per account,
    not per voice, and the picker asks `studio_voices.studio_open_to`. A publish asks the
    vendor live (`agents/service._studio_in_client_workspace`)."""
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
    "BAND_LABELS",
    "CLEAR_BAND_SETTING_LABEL",
    "CLONE_BAND",
    "CLONE_CONSENT_SCOPE",
    "HOSTED_SOURCES",
    "MAX_AGENTS_ON_VOICE",
    "NO_SOLD_BAND_CODE",
    "PARTIAL_LISTING_CODE",
    "STUDIO_KEY_OFF_REASON",
    "STUDIO_NEEDS_PRO",
    "STUDIO_VOICE_PROVIDER",
    "VOICE_CLONE_CONSENT_MISSING",
    "VOICE_IN_USE",
    "AgentOnVoice",
    "CloneConsent",
    "HostedSyncResult",
    "HostedVoiceRef",
    "HostedVoiceRow",
    "StudioListingWorkspace",
    "VoiceScope",
    "accent_name",
    "add_hosted_voice",
    "agent_voice_withdrawn",
    "agents_on_hosted_voice",
    "assert_clear_band_listed",
    "band_is_sold",
    "band_not_sold",
    "clone_consent_missing",
    "clone_offer_refusal",
    "consent_document_key",
    "count_hosted_voices",
    "count_listed_bands",
    "hosted_refresh_note",
    "hosted_voice_id",
    "hosted_voice_unofferable_reason",
    "language_note",
    "list_hosted_voices",
    "live_studio_agents",
    "name_reveals_speaker",
    "no_sold_band_sentence",
    "offered_hosted_voices",
    "own_voice_key_ready",
    "parse_hosted_voice_id",
    "preview_object",
    "read_hosted_voice",
    "record_clone",
    "record_clone_consent",
    "record_preview",
    "rung_of_source",
    "rungs_awaiting_setup",
    "set_display_label",
    "set_hosted_curation",
    "set_person_clone",
    "sold_hosted_band",
    "source_rate_key",
    "studio_listing_workspace",
    "studio_voices_listed",
    "sync_hosted_voices",
    "withdraw_hosted_voice",
]
