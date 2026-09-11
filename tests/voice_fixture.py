"""THE VOICES THE TEST DATABASE'S PLATFORM OFFERS — one set, for the whole suite (D-588).

WHY THIS FILE EXISTS
--------------------
Until D-588 `agents/voices.py` compiled a catalogue into the source, so every test that
needed a voice id could import a constant and every process had voices the moment it
booted. That constant was the defect the founder asked us to remove: a voice nobody
enabled, offered to clients, on a deployment nobody had looked at.

What replaced it is a CACHE plus an operator decision — `platform_voice_catalog` rows and a
`curation_state` on each — so "this platform offers some voices" is now a FACT ABOUT A
DEPLOYMENT rather than a property of the code. A test database is a deployment. Supplying
that fact once, here, is the same call `conftest.platform_tm_registration_is_live` makes for
the platform's telemarketer registration, and for the same three reasons: there is exactly
one row set for the whole platform, no per-tenant fixture can invent it, and a suite that
forgot would pass or fail depending on which other suite had run first.

**IT SUPPLIES THE FACT AND DOES NOT SOFTEN ANY GATE.** Nothing here touches offerability's
other three grounds, and nothing here makes an unsynced deployment behave like a synced one:
`voice_catalogue_sync_test.py` and `agent_voice_test.py` take these rows away again inside
their own transactions and assert the empty-catalogue behaviour directly.

WHERE THESE NINE IDS COME FROM, AND WHAT THEY ARE NOT
------------------------------------------------------
They are the speakers a live `GET /api/v1/voice-config/tts/voices` against the founder's own
engine account returned for provider `sarvam` / model `bulbul:v3` — VENDOR-PUBLISHED (live
API read by the founder, 11 Sep 2026, relayed; `api.bolna.ai` is egress-blocked from this
container and was not read here). They were `voices.SEED_SPEAKERS` until D-588 deleted the
seed.

They are kept HERE, in the test tree, precisely because they are a REPORTED sample of one
account's list at one moment and must never again be a claim this product makes about what
it offers. A fixture may hold such a sample; `apps/` may not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from apps.api.agents.voices import DEFAULT_TTS_MODEL, Voice, catalogue_note, voice_id_for
from apps.api.db.session import untenanted_session
from sqlalchemy import text

#: The speaker on every voice this suite's default agent speaks in. `ashutosh` because it is
#: the speaker in the ENGINE vendor's own worked example (VERIFIED-VENDOR-REPO,
#: `bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`) — the one id for which an end-to-end
#: request naming it has been seen — and because the ids that replaced a hand-written list
#: should not be chosen by a test author's preference either.
TEST_SPEAKER: Final = "ashutosh"

#: THE voice id the suite writes onto agents. Named once so a test asserting what reached
#: the engine and a test asserting what was stored cannot disagree.
TEST_VOICE_ID: Final = voice_id_for(DEFAULT_TTS_MODEL, TEST_SPEAKER)

#: The nine — see the module docstring for their provenance and their standing.
TEST_SPEAKERS: Final[tuple[str, ...]] = (
    "shubh",
    "priya",
    "suhani",
    TEST_SPEAKER,
    "ritu",
    "amit",
    "sumit",
    "pooja",
    "manan",
)


def make_voice(speaker: str) -> Voice:
    """One catalogue entry, built the way `voice_sync.voice_from_row` builds one — so a test
    that installs the snapshot directly and a test that goes through the database see the
    same object.

    NOT named `test_voice`: a helper imported into a `*_test.py` module is collected there
    as a test case, and one taking a `speaker` argument fails collection asking for a
    fixture of that name.
    """
    return Voice(
        id=voice_id_for(DEFAULT_TTS_MODEL, speaker),
        label=speaker.capitalize(),
        provider="sarvam",
        tts_model=DEFAULT_TTS_MODEL,
        speaker=speaker,
        languages=("te-IN", "hi-IN", "en-IN"),
        gender=None,
        verified=True,
        note=catalogue_note("sarvam"),
    )


#: The catalogue in force for the suite, in the picker order `voice_sync._ordered` produces.
TEST_VOICES: Final[tuple[Voice, ...]] = tuple(
    sorted((make_voice(speaker) for speaker in TEST_SPEAKERS), key=lambda v: v.label)
)

_ROW_SQL: Final = (
    "INSERT INTO platform_voice_catalog "
    "(voice_id, engine_voice_id, label, tts_model, provider, languages, is_custom, "
    " synced_at, curation_state, curated_at) "
    "VALUES (:voice_id, :speaker, :label, :model, 'sarvam', :languages, false, :now, "
    " 'enabled', :now) "
    "ON CONFLICT (voice_id) DO UPDATE SET curation_state = 'enabled', withdrawn_at = NULL"
)


async def seed_platform_voices() -> None:
    """Make the test database's platform offer these nine, ENABLED. Idempotent.

    `ON CONFLICT ... DO UPDATE` rather than an insert-if-absent, and only ever in the
    PERMISSIVE direction, for `platform_tm_registration_is_live`'s reason: concurrent suites
    must not queue on the rows, and a suite that disabled a voice inside a transaction it
    rolled back must not be able to leave the next session's platform offering nothing.
    """
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        for voice in TEST_VOICES:
            await session.execute(
                text(_ROW_SQL),
                {
                    "voice_id": voice.id,
                    "speaker": voice.speaker,
                    "label": voice.label,
                    "model": voice.tts_model,
                    "languages": list(voice.languages),
                    "now": now,
                },
            )


__all__ = [
    "TEST_SPEAKER",
    "TEST_SPEAKERS",
    "TEST_VOICES",
    "TEST_VOICE_ID",
    "make_voice",
    "seed_platform_voices",
]
