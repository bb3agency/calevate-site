"""The cached voice catalogue: the process snapshot, the table round trip and the tier.

`platform_voice_catalog` is filled by the hosted-voice sync (`tests/hosted_voice_routes_test.py`
covers that half); this file holds the read side — `voice_sync.load_voice_catalogue`
installing the cached rows as the process snapshot behind `voices.get_voice` — and the money
property that the tier never depends on what that snapshot holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from apps.api.agents import voices as voices_module
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_sync import load_voice_catalogue, read_cached_catalogue, voice_from_row
from apps.api.agents.voices import (
    catalogue,
    catalogue_source,
    install_voice_catalogue,
    voice_tier,
)
from apps.api.db.session import untenanted_session
from sqlalchemy import delete, text
from tests.voice_fixture import TEST_VOICES, seed_platform_voices


@pytest.fixture(autouse=True)
async def _restore_the_platforms_voices() -> AsyncIterator[None]:
    """The DB clauses here mutate the shared `platform_voice_catalog` rows, so every clause
    puts them back. The snapshot half is `conftest._voice_catalogue_snapshot_is_restored`'s
    job."""
    yield
    await seed_platform_voices()


def _row(**overrides: object) -> PlatformVoiceCatalogEntry:
    fields: dict[str, object] = {
        "voice_id": "sonic-3.5:shubh",
        "engine_voice_id": "shubh",
        "label": "Shubh",
        "tts_model": "sonic-3.5",
        "provider": "cartesia",
        "languages": ["te-IN", "hi-IN", "en-IN"],
        "is_custom": False,
        "synced_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return PlatformVoiceCatalogEntry(**fields)


# --- the money derivation ---------------------------------------------------------


def test_a_cartesia_id_outside_the_catalogue_still_bills_as_cartesia() -> None:
    """Absent is ordinary for a cached catalogue — not yet synced, withdrawn, renamed — and
    a membership lookup would price every one of those on the cheaper rung, silently, on an
    append-only ledger (hard rule 7)."""
    stranger = "sonic-3.5:a-voice-no-catalogue-here-has-ever-held"
    assert voices_module.get_voice(stranger) is None, "the premise: this id is not catalogued"
    assert voice_tier(stranger) == "studio"


# --- one cached row -> one catalogue entry -----------------------------------------


def test_a_cached_row_reads_back_with_its_own_name_and_speaker() -> None:
    """A clone's label cannot be derived from its id, so the cached label is carried."""
    voice = voice_from_row(
        _row(
            voice_id="sonic-3.5:sXlZ9Juk5Ji8sZiFjRUV",
            engine_voice_id="sXlZ9Juk5Ji8sZiFjRUV",
            label="my-custom-voice",
            is_custom=True,
        )
    )
    assert voice is not None
    assert voice.label == "my-custom-voice"
    assert voice.speaker == "sXlZ9Juk5Ji8sZiFjRUV"
    assert voice.provider == "cartesia"
    assert voice.verified


def test_a_row_on_a_model_we_do_not_offer_is_dropped() -> None:
    """A model no registry can place is a minute nothing can price (hard rule 7)."""
    assert voice_from_row(_row(tts_model="eleven_turbo_v2_5")) is None


def test_a_row_in_no_product_language_is_dropped() -> None:
    """We sell Telugu, Hindi and Indian English; a voice under none of them has no row in
    this product's picker."""
    assert voice_from_row(_row(languages=["fr-FR"])) is None


# --- the snapshot ------------------------------------------------------------------


@pytest.mark.parametrize("installed", [None, ()])
def test_nothing_is_in_force_until_something_is_installed(installed: tuple[()] | None) -> None:
    """NO COMPILED FALLBACK (D-588). A process that has installed nothing offers nothing,
    and says which of the two empty states it is in."""
    install_voice_catalogue(installed)
    assert catalogue() == ()
    assert catalogue_source() == "unsynced"


def test_an_unrecognised_id_still_reads_back_as_itself() -> None:
    """`agents.tts_voice` is free text and a value we no longer offer must read back as
    itself rather than be dropped or guessed at."""
    install_voice_catalogue(TEST_VOICES)
    assert catalogue_source() == "engine"
    assert voices_module.speech_for_voice_id("some-legacy-value") == (None, "some-legacy-value")


# --- the table round trip ------------------------------------------------------------


async def test_the_cached_rows_become_the_process_catalogue() -> None:
    """Rows -> snapshot, which is the path an API worker takes at boot, without calling the
    engine."""
    await seed_platform_voices()
    async with untenanted_session() as session:
        installed = await load_voice_catalogue(session)

    assert installed >= len(TEST_VOICES)
    assert catalogue_source() == "engine"
    assert {voice.id for voice in TEST_VOICES} <= {voice.id for voice in catalogue()}


async def test_a_withdrawn_voice_still_resolves_for_the_agent_speaking_it() -> None:
    """The lookup layer returns withdrawn rows too (D-617): excluding one left an agent still
    speaking it unnameable on its own screen."""
    await seed_platform_voices()
    withdrawn = TEST_VOICES[0].id
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = now() WHERE voice_id = :id"),
            {"id": withdrawn},
        )
        await session.commit()
    async with untenanted_session() as session:
        cached = await read_cached_catalogue(session)

    assert withdrawn in {voice.id for voice in cached}


async def test_a_deployment_that_never_synced_offers_nothing_and_says_so() -> None:
    """An empty table installs NOTHING and reports `"unsynced"`, so every picker can say
    which of the two empty states it is in."""
    async with untenanted_session() as session:
        await session.execute(delete(PlatformVoiceCatalogEntry))
        await session.commit()
    async with untenanted_session() as session:
        installed = await load_voice_catalogue(session)

    assert installed == 0
    assert catalogue_source() == "unsynced"
    assert catalogue() == ()
