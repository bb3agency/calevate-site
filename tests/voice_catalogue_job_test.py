"""The hourly `refresh_voice_catalogue` job, run whole against the test database.

The functions it calls have their own tests (`voice_catalogue_sync_test`,
`hosted_voice_routes_test`); what only this file can catch is how the JOB holds its
sessions. It once committed inside `untenanted_session` and then read again, which
SQLAlchemy refuses inside `session.begin()`, so every tick failed in production while every
unit test passed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_sync import VoiceSyncResult
from apps.api.agents.voices import catalogue, catalogue_source
from apps.api.db.session import untenanted_session
from apps.workers import voice_catalogue
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from tests.voice_fixture import TEST_VOICES, seed_platform_voices

#: A voice no fixture seeds, so finding it in the installed catalogue proves the install
#: read what the sync committed.
NEW_VOICE_ID = "sonic-3.5:job-test-new-voice"


@pytest.fixture(autouse=True)
async def _platform_voices() -> AsyncIterator[None]:
    await seed_platform_voices()
    yield
    async with untenanted_session() as session:
        await session.execute(
            delete(PlatformVoiceCatalogEntry).where(
                PlatformVoiceCatalogEntry.voice_id == NEW_VOICE_ID
            )
        )
    await seed_platform_voices()


async def test_the_job_succeeds_and_installs_the_cached_catalogue() -> None:
    """The real job on the engine tests resolve to (the fake, which hosts no catalogue):
    the sync is skipped, and the install still reads the table and reports it."""
    summary = json.loads(await voice_catalogue.refresh_voice_catalogue({"job_try": 1}))

    assert summary["skipped"] is True
    assert summary["in_force"] >= len(TEST_VOICES)
    assert catalogue_source() == "engine"
    assert {voice.id for voice in TEST_VOICES} <= {voice.id for voice in catalogue()}


async def test_the_install_reads_what_the_sync_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sync that writes a row: the install runs in a fresh session, so the row is in
    force only if leaving the sync's block committed it."""

    async def _sync_writing_one_voice(session: AsyncSession, engine: object) -> VoiceSyncResult:
        session.add(
            PlatformVoiceCatalogEntry(
                voice_id=NEW_VOICE_ID,
                engine_voice_id="job-test-new-voice",
                label="Job test voice",
                tts_model="sonic-3.5",
                provider="cartesia",
                languages=["te-IN", "en-IN"],
                is_custom=False,
                synced_at=datetime.now(UTC),
            )
        )
        return VoiceSyncResult(seen=1, written=1, pruned=0, complete=True)

    monkeypatch.setattr(voice_catalogue, "sync_voice_catalogue", _sync_writing_one_voice)

    summary = json.loads(await voice_catalogue.refresh_voice_catalogue({"job_try": 1}))

    assert summary["written"] == 1
    assert summary["in_force"] >= len(TEST_VOICES) + 1
    assert NEW_VOICE_ID in {voice.id for voice in catalogue()}
