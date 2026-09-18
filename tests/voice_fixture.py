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
engine account returned, VENDOR-PUBLISHED (live API read by the founder, 11 Sep 2026,
relayed; `api.bolna.ai` is egress-blocked from this container and was not read here). They
were `voices.SEED_SPEAKERS` until D-588 deleted the seed.

They are kept HERE, in the test tree, precisely because they are a REPORTED sample of one
account's list at one moment and must never again be a claim this product makes about what
it offers. A fixture may hold such a sample; `apps/` may not.

⚠ **THEY WERE SARVAM `bulbul:v3` VOICES UNTIL 18 Sep 2026 AND ARE NOW CARTESIA
`sonic-3.5`.** The founder withdrew the Sarvam TEXT-TO-SPEECH leg (Sarvam still transcribes
every call). The NAMES are deliberately unchanged — they are fixture identity, named in
assertions across dozens of modules, and a fake platform's voice ids were never a claim
about any vendor's catalogue. What had to change is the MODEL, because `voice_sync` drops a
row whose model this build does not offer and the fixture would otherwise enumerate nothing.

**AND THE DEPLOYMENT NOW HAS TO BE UNLOCKED, WHICH IS THE REAL CHANGE.** A Sarvam voice was
offerable with nothing installed: the engine held the leg and the price was on our own rate
card, so `voice_offer` short-circuited it. Both surviving providers are BYOK and priced by
an operator's attestation (hard rule 7), so a test database is now a deployment on which
NOTHING is offerable until somebody does what a real operator must do — install the key and
attest the price. `platform_can_speak()` below is that act, and it is deliberately a
separate, named call rather than something `seed_platform_voices` does quietly: a suite
asserting the LOCKED behaviour must be able to have the voices without the unlock.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Final

from apps.api.agents.voice_offer import install_tts_price_reader
from apps.api.agents.voices import CARTESIA_TTS_MODEL, Voice, catalogue_note, voice_id_for
from apps.api.core.settings import get_settings
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
TEST_VOICE_ID: Final = voice_id_for(CARTESIA_TTS_MODEL, TEST_SPEAKER)

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
        id=voice_id_for(CARTESIA_TTS_MODEL, speaker),
        label=speaker.capitalize(),
        provider="cartesia",
        tts_model=CARTESIA_TTS_MODEL,
        speaker=speaker,
        languages=("te-IN", "hi-IN", "en-IN"),
        gender=None,
        verified=True,
        note=catalogue_note("cartesia"),
    )


#: The catalogue in force for the suite, in the picker order `voice_sync._ordered` produces.
TEST_VOICES: Final[tuple[Voice, ...]] = tuple(
    sorted((make_voice(speaker) for speaker in TEST_SPEAKERS), key=lambda v: v.label)
)

_ROW_SQL: Final = (
    "INSERT INTO platform_voice_catalog "
    "(voice_id, engine_voice_id, label, tts_model, provider, languages, is_custom, "
    " synced_at, curation_state, curated_at) "
    "VALUES (:voice_id, :speaker, :label, :model, 'cartesia', :languages, false, :now, "
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


def platform_can_speak(monkeypatch: object | None = None) -> None:
    """Make this process a deployment on which the fixture's voices may actually be OFFERED
    — key installed, price attested. Idempotent; process-scoped.

    ⚠ **NOTHING LIKE THIS WAS NEEDED WHILE THE VOICES WERE SARVAM'S (before 18 Sep 2026).**
    `voice_offer._operator_unofferable_reason` short-circuited a Sarvam voice to offerable
    after curation, because the engine held that leg and its cost was on our own rate card.
    Both surviving providers are BYOK with an operator-attested price (hard rule 7), so the
    two grounds below are real work a real operator does — and a suite that wants agents to
    be publishable has to do it too, rather than have a gate softened for it.

    It installs a TTS price reader rather than writing `platform_tts_prices` rows because
    the picker reads a PROCESS SNAPSHOT (`ops/pricing_snapshot.install_pricing_readers`
    fills it from the table in production, off the request path). A test that wants the
    table itself drives `ops/model_pricing.attest_tts_price` directly.
    """
    del monkeypatch  # accepted so a caller can pass one; nothing here needs it
    os.environ.setdefault("CARTESIA_API_KEY", "fixture-cartesia-key")
    # AND THE CAP RAISED, which is the third thing a real operator does and the one that
    # bites hardest now that every offerable voice is Cartesia's: `cartesia_agent_cap`
    # defaults to 2 LIVE AGENTS PLATFORM-WIDE (the founder's rule, struck while Sarvam
    # served the value rung and this capped only the dearer tier). A suite that left it at 2
    # would start refusing voices on the third agent any test happened to publish — a
    # failure that lands in whichever test ran third and names the cap, not the cause.
    # Raised rather than removed: the cap is still exercised, by the clauses that pass
    # `cartesia_live_agents` explicitly, which is the only way to drive it deterministically.
    os.environ.setdefault("CARTESIA_AGENT_CAP", "10000")
    get_settings.cache_clear()
    install_tts_price_reader(FIXTURE_TTS_PRICE_READER)


def _fixture_tts_price_is_billable(provider: str) -> bool:
    """The fixture deployment has attested Cartesia and NOT Gnani, which is the real
    platform's state on 18 Sep 2026 and the one the offer seam must be exercised against.

    Gnani deliberately answers False: the value rung is unsellable until somebody attests a
    Gnani price, the founder's decision is that it stays that way for now, and a fixture
    that quietly attested one would make every suite pass against a platform this product
    does not have.
    """
    return provider == "cartesia"


#: THE suite's price predicate, as one object, so `conftest` can tell "the fixture's
#: reader" from "whatever this test installed" by identity rather than by calling it.
FIXTURE_TTS_PRICE_READER: Final = _fixture_tts_price_is_billable
