"""The engine-derived voice catalogue (D-585): normalisation, fallback and the tier.

WHAT THIS FILE IS DEFENDING. Our voice list was compiled from SARVAM's SDK enum while we
publish through the ENGINE, whose Sarvam provider offers a different subset — proved by a
live `400 POST /v2/agent`, "Provided voice: Anushka is not available for the provider:
sarvam" (11 Sep 2026). And a CLONED voice cannot be in a compiled list at all. So the
catalogue is read from the engine and cached; these are the clauses that hold the
translation, the fallback and the money derivation to what that change promised.

PURE UNIT — no database and no network. The DB half (the upsert, the prune-only-on-complete
rule) is exercised where a session exists; the ADAPTER half is exercised by the conformance
suite against the pinned vendor payload shapes.
"""

from __future__ import annotations

import pytest
from apps.api.agents import voices as voices_module
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_sync import (
    catalogue_from_listing,
    load_voice_catalogue,
    read_cached_catalogue,
    sync_voice_catalogue,
    voice_from_engine,
)
from apps.api.agents.voices import (
    DEFAULT_VOICE_ID,
    SEED_CATALOG,
    catalogue,
    catalogue_source,
    install_voice_catalogue,
    voice_tier,
)
from apps.api.db.session import untenanted_session
from calevate_shared.engine import EngineVoice, EngineVoiceListing
from sqlalchemy import delete


@pytest.fixture(autouse=True)
def _restore_seed() -> object:
    """Every clause installs into a process-wide snapshot, so every clause puts it back.
    Without this the first test to install leaks its catalogue into the rest of the run —
    and the catalogue decides what the voice picker offers."""
    yield
    install_voice_catalogue(None)


def _engine_voice(**overrides: object) -> EngineVoice:
    fields: dict[str, object] = {
        "voice_id": "shubh",
        "label": "Shubh",
        "tts_model": "bulbul:v3",
        "languages": ("te-IN", "hi-IN", "en-IN"),
    }
    fields.update(overrides)
    return EngineVoice(**fields)  # type: ignore[arg-type]


# --- the money derivation (constraint 2: `voice_tier` no longer reads the catalogue) ----


def test_a_cartesia_id_outside_the_catalogue_still_bills_as_cartesia() -> None:
    """THE CLAUSE THIS WHOLE CHANGE TURNS ON (hard rule 7, plan §2.3 invariant 7).

    `voice_tier` used to look the id up in the compiled catalogue and answer `sarvam` when
    it was absent. Absent was impossible then. It is ordinary now — a cache that has not
    synced, a voice the vendor withdrew, a clone renamed — and every one of those would
    have priced a Cartesia minute at the Sarvam rate, silently, on an append-only ledger.
    """
    stranger = "sonic-3.5:a-voice-no-catalogue-here-has-ever-held"
    assert voices_module.get_voice(stranger) is None, "the premise: this id is not catalogued"
    assert voice_tier(stranger) == "cartesia"


def test_the_tier_survives_a_catalogue_that_holds_only_the_other_provider() -> None:
    """Installing a Sarvam-only catalogue must not re-price a live Cartesia agent — which
    is exactly what a membership test would do the first time a sync ran."""
    install_voice_catalogue(
        catalogue_from_listing(EngineVoiceListing(voices=[_engine_voice()], complete=True))
    )
    assert voice_tier("sonic-3.5:whatever") == "cartesia"


# --- the translation ------------------------------------------------------------------


def test_a_cloned_voice_keeps_the_engines_name() -> None:
    """A clone's label cannot be derived from its id — the vendor's own example pairs
    `sXlZ9Juk5Ji8sZiFjRUV` with `my-custom-voice` (VERIFIED-VENDOR-DOCS,
    `bolna-findings/mirror/pages/api-reference/voice/get_all.md:102-112`). The label is a
    WIRE value as well as a human one, so a derived one would reach the engine."""
    voice = voice_from_engine(
        _engine_voice(voice_id="sXlZ9Juk5Ji8sZiFjRUV", label="my-custom-voice", is_custom=True)
    )
    assert voice is not None
    assert voice.label == "my-custom-voice"
    assert voice.speaker == "sXlZ9Juk5Ji8sZiFjRUV"
    assert voice.id == "bulbul:v3:sXlZ9Juk5Ji8sZiFjRUV", "the id spelling is `voice_id_for`'s"


def test_a_voice_on_a_model_we_do_not_offer_is_dropped() -> None:
    """A model no registry can place is a minute nothing can price (hard rule 7)."""
    assert voice_from_engine(_engine_voice(tts_model="eleven_turbo_v2_5")) is None


def test_a_voice_in_no_product_language_is_dropped() -> None:
    """We sell Telugu, Hindi and Indian English; a voice the engine returned under none of
    them has no row in this product's picker."""
    assert voice_from_engine(_engine_voice(languages=("fr-FR",))) is None


def test_an_engine_listed_voice_is_verified() -> None:
    """`verified` was False on every compiled entry with the reason written into the
    module: the confirming read is a live listing on the account. This IS that read —
    OPERATIONS §2 gate 3's question, answered by the engine itself."""
    voice = voice_from_engine(_engine_voice())
    assert voice is not None and voice.verified


def test_the_catalogue_puts_the_cheaper_tier_first() -> None:
    """A client scrolling should reach the tier they are already on before the one that
    costs more per minute (plan §0 Q9)."""
    listing = EngineVoiceListing(
        voices=[
            _engine_voice(voice_id="sonic-a", label="Aaa", tts_model="sonic-3.5"),
            _engine_voice(voice_id="zzz", label="Zzz"),
        ],
        complete=True,
    )
    assert [voice.provider for voice in catalogue_from_listing(listing)] == ["sarvam", "cartesia"]


# --- the snapshot and the fallback (constraint 5) --------------------------------------


def test_the_seed_is_in_force_until_something_is_installed() -> None:
    """The product must not become unpublishable because a background job has never run."""
    assert catalogue() == SEED_CATALOG
    assert catalogue_source() == "seed"


def test_the_seed_holds_no_voice_the_engine_is_known_to_reject() -> None:
    """`anushka` is the first name in Sarvam's enum and the one the engine refused. A seed
    compiled from the model vendor would ship it; this one is built from voices a live
    engine read returned."""
    assert all("anushka" not in voice.id for voice in SEED_CATALOG)
    assert any(voice.id == DEFAULT_VOICE_ID for voice in SEED_CATALOG), (
        "the default persona must survive in the fallback, or a fresh deployment cannot "
        "create the agent its own picker pre-selects a voice for"
    )


def test_installing_a_synced_catalogue_replaces_the_seed_and_says_so() -> None:
    install_voice_catalogue(
        catalogue_from_listing(
            EngineVoiceListing(
                voices=[_engine_voice(voice_id="ashutosh", label="Ashutosh")], complete=True
            )
        )
    )
    assert catalogue_source() == "engine"
    assert [voice.id for voice in catalogue()] == ["bulbul:v3:ashutosh"]


def test_an_empty_catalogue_is_refused_rather_than_installed() -> None:
    """Zero voices is what a revoked credential, a moved route and a genuinely empty
    account all look like, and only the last is a catalogue — while applying it takes the
    picker to zero entries and makes every agent's voice read as withdrawn."""
    with pytest.raises(ValueError, match="empty voice catalogue"):
        install_voice_catalogue(())
    assert catalogue() == SEED_CATALOG, "the previous answer must still be standing"


def test_exactly_one_default_survives_a_catalogue_without_our_persona() -> None:
    """The picker pre-selects the default and the create path calls `default_voice()`, so a
    catalogue with none would 500 a screen and one with two would pre-select at random.
    Whether the engine still offers OUR configured persona is the engine's business."""
    install_voice_catalogue(
        catalogue_from_listing(
            EngineVoiceListing(
                voices=[
                    _engine_voice(voice_id="sonic-a", label="Aaa", tts_model="sonic-3.5"),
                    _engine_voice(voice_id="priya", label="Priya"),
                ],
                complete=True,
            )
        )
    )
    defaults = [voice for voice in catalogue() if voice.is_default]
    assert len(defaults) == 1
    assert defaults[0].provider == "sarvam", (
        "Cartesia is chosen, never inherited: a default that costs the client more per "
        "minute must be a choice they made (plan §0 Q9)"
    )


def test_an_unrecognised_id_still_reads_back_as_itself() -> None:
    """`agents.tts_voice` is free text and a value we no longer offer must read back as
    itself rather than be dropped or guessed at — unchanged by the catalogue moving."""
    install_voice_catalogue(
        catalogue_from_listing(EngineVoiceListing(voices=[_engine_voice()], complete=True))
    )
    assert voices_module.speech_for_voice_id("some-legacy-value") == (None, "some-legacy-value")


# --- the DB half: upsert, prune, refusal, and the snapshot round trip -------------------
#
# THESE ARE THE CLAUSES THE CACHE EXISTS FOR, and none of them is reachable without a
# session: the module's whole reason to be is that a process which cannot reach the engine
# still serves the last good answer. The pure-unit clauses above prove the TRANSLATION
# (engine record -> `Voice`); these prove the PERSISTENCE, which is where the failures
# would be silent — a prune that ran on a partial read withdraws a voice a live agent is
# speaking, and nothing would log an error.
#
# `platform_voice_catalog` is PLATFORM-scoped and shared, like `platform_config`'s store,
# so every clause below cleans up after itself in `finally` rather than trusting ordering.


async def _clear() -> None:
    async with untenanted_session() as session:
        await session.execute(delete(PlatformVoiceCatalogEntry))
        await session.commit()


class _StubEngine:
    """A `VoiceEngine` stand-in for the two fields `sync_voice_catalogue` touches.

    Not `FakeEngine`: its catalogue is fixed by design (it is the conformance subject), and
    these clauses need to vary completeness and emptiness per call — which is exactly the
    axis the fake must NOT be mutable along.
    """

    name = "stub"

    def __init__(self, listing: EngineVoiceListing) -> None:
        self._listing = listing

    async def list_voices(self) -> EngineVoiceListing:
        return self._listing


async def test_a_synced_catalogue_survives_the_round_trip_through_the_table() -> None:
    """Engine -> rows -> snapshot, which is the whole path an API worker takes at boot.

    It reads the TABLE, never the engine (see the module docstring: folding the two would
    make every boot a vendor round trip and every vendor outage an empty picker), so a
    break here is a deployment that silently falls back to the seed with nothing wrong.
    """
    await _clear()
    try:
        engine = _StubEngine(
            EngineVoiceListing(
                voices=(
                    _engine_voice(),
                    _engine_voice(voice_id="ritu", label="Ritu"),
                    # A CLONE, carried through as itself — the case a compiled list cannot
                    # hold at all, and the reason this table exists.
                    _engine_voice(
                        voice_id="sXlZ9Juk5Ji8sZiFjRUV",
                        label="my-custom-voice",
                        is_custom=True,
                    ),
                ),
                complete=True,
            )
        )
        async with untenanted_session() as session:
            result = await sync_voice_catalogue(session, engine)
            await session.commit()
        assert result.written == 3, "the engine's voices did not reach the table"

        async with untenanted_session() as session:
            installed = await load_voice_catalogue(session)
        assert installed == 3

        cloned = next(voice for voice in catalogue() if voice.speaker == "sXlZ9Juk5Ji8sZiFjRUV")
        assert cloned.label == "my-custom-voice", (
            "the clone's name was derived rather than carried; no rule relates it to the id"
        )
        assert catalogue_source() == "engine"
    finally:
        await _clear()
        install_voice_catalogue(None)


async def test_a_second_sync_updates_a_renamed_voice_rather_than_duplicating_it() -> None:
    """IDEMPOTENT AT THE ROW (BACKEND-PATTERNS §4). The upsert names every column but the
    key precisely so a renamed clone converges — a cache that kept the first answer would
    be a second opinion about the vendor's own list."""
    await _clear()
    try:
        async with untenanted_session() as session:
            await sync_voice_catalogue(
                session,
                _StubEngine(EngineVoiceListing(voices=(_engine_voice(),), complete=True)),
            )
            await session.commit()
        async with untenanted_session() as session:
            again = await sync_voice_catalogue(
                session,
                _StubEngine(
                    EngineVoiceListing(voices=(_engine_voice(label="Shubh (warm)"),), complete=True)
                ),
            )
            await session.commit()
        assert again.written == 1
        async with untenanted_session() as session:
            cached = await read_cached_catalogue(session)

        assert len(cached) == 1, "a re-sync duplicated the row instead of converging on it"
        assert cached[0].label == "Shubh (warm)", "the rename did not reach the cache"
    finally:
        await _clear()


async def test_an_incomplete_listing_never_prunes() -> None:
    """THE CLAUSE THAT REACHES A CLIENT'S PHONE LINE.

    A page the adapter could not read looks exactly like a shorter catalogue. Pruning on
    one would withdraw voices that live agents are speaking right now — and the symptom
    would be a picker that quietly lost entries, not an error. `complete` is carried on the
    listing for this single decision.
    """
    await _clear()
    try:
        async with untenanted_session() as session:
            await sync_voice_catalogue(
                session,
                _StubEngine(
                    EngineVoiceListing(
                        voices=(
                            _engine_voice(),
                            _engine_voice(voice_id="ritu", label="Ritu"),
                        ),
                        complete=True,
                    )
                ),
            )
            await session.commit()

        async with untenanted_session() as session:
            partial = await sync_voice_catalogue(
                session,
                _StubEngine(
                    EngineVoiceListing(
                        voices=(_engine_voice(),),
                        complete=False,
                        incomplete_reason="page_cap_reached",
                    )
                ),
            )
            await session.commit()
        async with untenanted_session() as session:
            cached = await read_cached_catalogue(session)

        assert partial.pruned is None, "an incomplete read pruned; it must only upsert"
        assert {voice.speaker for voice in cached} == {"shubh", "ritu"}, (
            "a voice absent from a PARTIAL read was withdrawn from the catalogue"
        )
    finally:
        await _clear()


async def test_a_complete_listing_does_prune_a_withdrawn_voice() -> None:
    """The other half, or the clause above would pass on a sync that never prunes at all.
    A voice the engine has genuinely stopped offering must stop being offered here — that
    is the failure `anushka` was."""
    await _clear()
    try:
        async with untenanted_session() as session:
            await sync_voice_catalogue(
                session,
                _StubEngine(
                    EngineVoiceListing(
                        voices=(
                            _engine_voice(),
                            _engine_voice(voice_id="ritu", label="Ritu"),
                        ),
                        complete=True,
                    )
                ),
            )
            await session.commit()

        async with untenanted_session() as session:
            narrowed = await sync_voice_catalogue(
                session,
                _StubEngine(EngineVoiceListing(voices=(_engine_voice(),), complete=True)),
            )
            await session.commit()
        async with untenanted_session() as session:
            cached = await read_cached_catalogue(session)

        assert narrowed.pruned == 1
        assert {voice.speaker for voice in cached} == {"shubh"}
    finally:
        await _clear()


async def test_an_empty_listing_leaves_the_previous_catalogue_standing() -> None:
    """Zero voices is what a revoked credential, a moved route and a genuinely empty
    account all look like, and only the last is a catalogue. Applying it would take the
    picker to zero entries and make every agent's configured voice read as withdrawn."""
    await _clear()
    try:
        async with untenanted_session() as session:
            await sync_voice_catalogue(
                session,
                _StubEngine(EngineVoiceListing(voices=(_engine_voice(),), complete=True)),
            )
            await session.commit()

        async with untenanted_session() as session:
            empty = await sync_voice_catalogue(
                session, _StubEngine(EngineVoiceListing(voices=(), complete=True))
            )
            await session.commit()
        async with untenanted_session() as session:
            cached = await read_cached_catalogue(session)

        assert empty.written == 0 and empty.pruned is None
        assert len(cached) == 1, "an empty read emptied the catalogue instead of being refused"
    finally:
        await _clear()


async def test_a_deployment_that_never_synced_serves_the_seed_and_says_so() -> None:
    """A MISS IS NOT AN ERROR. A product that cannot make a voice agent until a background
    job has run is the half-wired seam CLAUDE.md names — so an empty table installs the
    seed and every surface that renders the picker reports `source: "seed"` so an operator
    knows to sync rather than guessing why the list is short."""
    await _clear()
    try:
        async with untenanted_session() as session:
            installed = await load_voice_catalogue(session)

        assert installed == 0
        assert catalogue_source() == "seed"
        assert catalogue(), "the seed is empty; the product cannot publish a voice at all"
        assert all(voice.speaker != "anushka" for voice in catalogue()), (
            "the seed offers a speaker the engine is KNOWN to reject (live 400, 11 Sep 2026)"
        )
    finally:
        install_voice_catalogue(None)
