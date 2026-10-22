"""The voice catalogue: the engine-hosted sync, and the cached catalogue this process serves.

`sync_voice_catalogue` re-reads the voices an engine HOSTS (D-687, `agents/hosted_voices`)
into `platform_voice_catalog`. `load_voice_catalogue` installs the cached rows a build can
place as the process snapshot behind `voices.get_voice` and `voices.speech_for_voice_id`,
so an agent row naming a voice from an earlier catalogue still reads back as itself.

The two are separate on purpose: the API workers must be able to pick the catalogue up from
the TABLE without calling the vendor, and a process that cannot reach the engine must still
be able to serve the last good answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import get_args

from calevate_shared.engine import VoiceEngine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import HostedSyncResult, sync_hosted_voices
from apps.api.agents.languages import BUILT_LANGUAGES
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voices import (
    TtsModel,
    Voice,
    catalogue_note,
    install_voice_catalogue,
    provider_of_tts_model,
    voice_tier,
)
from apps.api.billing.rates import VOICE_TIERS
from apps.api.core.logging import get_logger
from apps.api.engine.catalogue import HostsVoices

log = get_logger(__name__)


def _offered_model(tts_model: str) -> TtsModel | None:
    """`tts_model` as a member of our catalogue's `TtsModel`, or None.

    An identity lookup through `get_args(TtsModel)` rather than a `cast`: what arrives here
    is a string a cached row written by an older build chose. This narrows on evidence.
    """
    return next((model for model in get_args(TtsModel) if model == tts_model), None)


@dataclass(frozen=True, slots=True)
class VoiceSyncResult:
    """What one sync did, in the four numbers an operator's console shows.

    `pruned is None` is not zero: it means the listing was INCOMPLETE and pruning was
    deliberately not attempted, which is a different fact from "nothing needed pruning" and
    the only one that explains a catalogue that keeps a voice the vendor withdrew.

    "Pruned" is still the right word for a number the console prints, and it is now a
    WITHDRAWAL rather than a delete (D-588): the rows leave the picker and keep their
    curation state. The count is of rows newly stamped, so a voice withdrawn last week is
    not counted again this week — an operator reading `pruned: 0` is reading "the platform
    dropped nothing since the last run", which is the question they are asking.
    """

    seen: int
    written: int
    pruned: int | None
    complete: bool
    incomplete_reason: str | None = None
    #: Why no sync was ATTEMPTED, or None if one was (D-615).
    #:
    #: NOT `written == 0`, which is this module's other zero and means the opposite thing:
    #: that the engine was asked and answered with nothing usable, which is an ALARM and a
    #: standing catalogue. This one means nobody was asked, because on this engine there is
    #: nobody to ask — see `sync_voice_catalogue`. The console and the cron read it to say
    #: so, and `installed` stays False either way because neither writes a catalogue.
    skipped_reason: str | None = None
    #: Something the sync did not read, said for the operator, or None (D-687: the Studio
    #: half of an engine-hosted catalogue while no Studio workspace is set up).
    note: str | None = None
    #: The hosted sync's own result on an engine that hosts its voices, None on any other.
    #: The refresh route words its answer from it (bands, the plan) rather than from the
    #: cached catalogue's numbers.
    hosted: HostedSyncResult | None = None

    @property
    def installed(self) -> bool:
        """Did this sync produce a catalogue the process can serve? False means the
        previous answer — or nothing at all, on a deployment that has never synced — is
        still standing, by design."""
        return self.written > 0


def _ordered(voices: list[Voice]) -> tuple[Voice, ...]:
    """Picker order, in one place: cheaper tier first (`VOICE_TIERS` is card order), then
    label."""
    return tuple(
        sorted(voices, key=lambda voice: (VOICE_TIERS.index(voice_tier(voice.id)), voice.label))
    )


async def sync_voice_catalogue(
    session: AsyncSession, engine: VoiceEngine, *, now: datetime | None = None
) -> VoiceSyncResult:
    """Re-read the voices this engine hosts into `platform_voice_catalog`. The caller COMMITS.

    An engine that hosts its voices (D-687) is read through its own list and the Studio
    workspace's own-key list. Any other engine has no catalogue of its own to re-read, and
    the result says so (`skipped_reason`) rather than reporting a zero that reads like a
    failed read.
    """
    if isinstance(engine, HostsVoices) and not engine.capabilities.is_ours("tts"):
        hosted = await sync_hosted_voices(session, engine, engine_name=engine.name, now=now)
        return VoiceSyncResult(
            seen=hosted.seen,
            written=hosted.written,
            pruned=hosted.pruned,
            complete=True,
            note=hosted.studio_skipped_reason,
            hosted=hosted,
        )
    log.info(
        "voice_catalogue_sync_skipped",
        extra={"engine": engine.name, "reason": "engine_hosts_no_voices"},
    )
    return VoiceSyncResult(
        seen=0,
        written=0,
        pruned=None,
        complete=True,
        skipped_reason="this voice platform hosts no voice catalogue to re-read",
    )


async def read_cached_catalogue(session: AsyncSession) -> tuple[Voice, ...]:
    """The cached rows as catalogue entries — no engine call.

    The `note` is COMPOSED from the provider rather than stored: it is a client-facing
    sentence that names the tier, so a copy frozen into a cache row would go stale the day
    the tier was renamed.

    EVERY ROW IS RETURNED, WITHDRAWN ONES INCLUDED, because this feeds the LOOKUP layer
    (`voices.get_voice`, `voices.speech_for_voice_id`) read on every publish and read-back:
    excluding a withdrawn voice left an agent still speaking it unnameable on its own screen
    and sent our composed id in the vendor's speaker slot on the next publish (D-617).
    """
    rows = (await session.execute(select(PlatformVoiceCatalogEntry))).scalars().all()
    return _ordered([voice for voice in map(voice_from_row, rows) if voice is not None])


def voice_from_row(row: PlatformVoiceCatalogEntry) -> Voice | None:
    """ONE CACHED ROW -> ONE CATALOGUE ENTRY, or None for a row this build cannot place.

    Public because `agents/voice_curation.py` renders the same voice, and a second
    translation there would be where the two came to describe one voice differently.

    TWO REASONS A ROW IS DROPPED. A model `TTS_MODEL_LIFECYCLE` cannot place has no
    provider, therefore no voice tier, therefore no price for a minute of it (hard rule 7).
    A row under none of the built languages is a voice no picker has a row for.
    """
    model = _offered_model(row.tts_model)
    provider = provider_of_tts_model(row.tts_model) if model is not None else None
    if model is None or provider is None:
        return None
    languages = tuple(language for language in BUILT_LANGUAGES if language in set(row.languages))
    if not languages:
        return None
    return Voice(
        id=row.voice_id,
        label=row.label,
        provider=provider,
        tts_model=model,
        speaker=row.engine_voice_id,
        languages=languages,
        gender=None,
        verified=True,
        note=catalogue_note(provider),
    )


async def load_voice_catalogue(session: AsyncSession) -> int:
    """Install the cached catalogue into THIS process. Returns how many voices are in force.

    Called at API and worker startup and after every sync. A miss is not an error: a
    deployment whose table holds no row this build can place has no voices in force.
    """
    voices = await read_cached_catalogue(session)
    if not voices:
        log.info("voice_catalogue_unsynced", extra={"reason": "no cached rows"})
        install_voice_catalogue(None)
        return 0
    install_voice_catalogue(voices)
    return len(voices)


__all__ = [
    "VoiceSyncResult",
    "load_voice_catalogue",
    "read_cached_catalogue",
    "sync_voice_catalogue",
    "voice_from_row",
]
