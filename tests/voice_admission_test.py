"""ADDING A VOICE BY TYPING ITS FACTS, AND HAVING THEM CHECKED (D-590).

WHAT THIS FILE IS DEFENDING. D-588 shipped a curation screen over 418 synced vendor
personas. The founder's answer was that they will not use any of them — only voices they
have CLONED — and that they want to add those by providing the facts. D-590 is that add,
and these are the clauses that hold it to what it promised:

* **an added voice is selectable in BOTH realms**, from one source of truth, without a sync
  ever having run;
* **an id the voice platform does not list is refused BY NAME** — the clause that reaches a
  phone line, because publishing on such an id returns a live `400 … not available for the
  provider` on a client's call rather than on this screen;
* **an ElevenLabs choice is refused with its reason**, never silently omitted: the voice
  platform clones on ElevenLabs or Cartesia and this product has no ElevenLabs model, so an
  operator who has just spent a sample there has to be told why;
* **the tier is still derived from the id**, so an added Cartesia voice bills as Cartesia
  whatever the form said (hard rule 7);
* **a live agent survives its voice being archived**, unchanged from D-588;
* **an unreadable voice platform is a refusal, not an unverified row**, and it is a
  different refusal from "that voice is not there".

`platform_voice_catalog` is PLATFORM-scoped and shared with every other suite, so every
clause removes the rows it added and re-seeds (`tests/voice_fixture.seed_platform_voices`).
"""

from __future__ import annotations

from typing import Final

import pytest
from apps.api.agents.voice_admission import (
    UNPUBLISHABLE_CLONING_PROVIDERS,
    VoiceFacts,
    admit_voice,
)
from apps.api.agents.voice_curation import (
    list_curated_voices,
    read_one_curated_voice,
    set_curation_state,
)
from apps.api.agents.voice_offer import offered_catalogue
from apps.api.agents.voice_sync import load_voice_catalogue, sync_voice_catalogue
from apps.api.agents.voices import (
    CARTESIA_TTS_MODEL,
    DEFAULT_TTS_MODEL,
    catalogue,
    install_voice_catalogue,
    speech_for_voice_id,
    voice_id_for,
    voice_tier,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from calevate_shared.engine import EngineVoice, EngineVoiceListing
from sqlalchemy import text
from tests.voice_fixture import seed_platform_voices

#: A CLONE, in the shape the vendor's own example shows: an opaque generated id paired with
#: a name that has no derivable relationship to it (VERIFIED-VENDOR-DOCS,
#: `bolna-findings/mirror/pages/api-reference/voice/get_all.md:102-112`). Using a Sarvam
#: persona name here would let a bug that derives the label from the id pass every clause.
CLONE_ID: Final = "sXlZ9Juk5Ji8sZiFjRUV"
CLONE_NAME: Final = "my-custom-voice"
CLONE_VOICE_ID: Final = voice_id_for(CARTESIA_TTS_MODEL, CLONE_ID)

#: A SARVAM clone, for the clauses about OFFERING. The Cartesia tier has three further
#: offerability grounds (a key, an attested price, the agent cap) that a test database clears
#: none of, so proving "an added voice is selectable" on a Cartesia voice would be proving
#: the opposite. The grounds composing is a separate, deliberate clause below.
SARVAM_CLONE_ID: Final = "raghava-clone"
SARVAM_CLONE_NAME: Final = "Raghava — warm"
SARVAM_VOICE_ID: Final = voice_id_for(DEFAULT_TTS_MODEL, SARVAM_CLONE_ID)


def _sarvam_facts(**overrides: object) -> VoiceFacts:
    return _facts(
        provider="sarvam",
        tts_model=DEFAULT_TTS_MODEL,
        engine_voice_id=SARVAM_CLONE_ID,
        label=SARVAM_CLONE_NAME,
        **overrides,
    )


def _sarvam_listing() -> EngineVoiceListing:
    return _listing(
        _engine_voice(
            voice_id=SARVAM_CLONE_ID, label=SARVAM_CLONE_NAME, tts_model=DEFAULT_TTS_MODEL
        )
    )


def _engine_voice(
    *,
    voice_id: str = CLONE_ID,
    label: str = CLONE_NAME,
    tts_model: str = CARTESIA_TTS_MODEL,
    languages: tuple[str, ...] = ("te-IN", "en-IN"),
    is_custom: bool = True,
) -> EngineVoice:
    return EngineVoice(
        voice_id=voice_id,
        label=label,
        tts_model=tts_model,
        languages=languages,
        is_custom=is_custom,
    )


class _StubEngine:
    """A `VoiceEngine` stand-in for the ONE method admission calls.

    `listing=None` means the call RAISES — the "voice platform is unreachable" axis, which
    the conformance fake deliberately cannot be moved along.
    """

    name = "stub"

    def __init__(self, listing: EngineVoiceListing | None) -> None:
        self._listing = listing

    async def list_voices(self) -> EngineVoiceListing:
        if self._listing is None:
            raise RuntimeError("the voice platform is unreachable")
        return self._listing


def _listing(*voices: EngineVoice, complete: bool = True) -> EngineVoiceListing:
    return EngineVoiceListing(
        voices=list(voices) or [_engine_voice()],
        complete=complete,
        incomplete_reason=None if complete else "page_cap_reached",
    )


def _facts(**overrides: object) -> VoiceFacts:
    base: dict[str, object] = {
        "provider": "cartesia",
        "tts_model": CARTESIA_TTS_MODEL,
        "engine_voice_id": CLONE_ID,
        "label": CLONE_NAME,
        "languages": ("te-IN",),
    }
    base.update(overrides)
    return VoiceFacts(**base)  # type: ignore[arg-type]


async def _add(facts: VoiceFacts, listing: EngineVoiceListing | None = None) -> None:
    async with untenanted_session() as session:
        await admit_voice(session, _StubEngine(listing or _listing()), facts)  # type: ignore[arg-type]
        await load_voice_catalogue(session)
        await session.commit()


@pytest.fixture(autouse=True)
async def _restore_the_platforms_voices() -> object:
    """Every clause writes platform-wide rows; every clause takes its own back out.

    Not a rolled-back transaction: admission commits (the console's write does), and the
    rows are shared with every other suite in the run. The delete is keyed on the ids THIS
    file adds, so it cannot take a sibling suite's platform to zero voices.
    """
    yield
    async with untenanted_session() as session:
        await session.execute(
            text(
                "DELETE FROM platform_voice_catalog "
                "WHERE voice_id LIKE 'sonic-3.5:%' OR voice_id = :sarvam"
            ),
            {"sarvam": SARVAM_VOICE_ID},
        )
        await session.commit()
    await seed_platform_voices()
    async with untenanted_session() as session:
        await load_voice_catalogue(session)


# --- the founder's requirement --------------------------------------------------


async def test_an_added_voice_is_selectable_in_both_realms_from_one_source_of_truth() -> None:
    """THE REQUIREMENT, END TO END. Type the facts, and the voice is on both pickers.

    Asked twice through `voice_offer.offered_catalogue` — the ONE seam both realms read —
    because a second answer for the admin realm is how a client and an operator come to see
    different products. Only the refusal wording forks there; offerability does not.
    """
    await _add(_sarvam_facts(), _sarvam_listing())

    for audience in ("operator", "client"):
        rows = {row.voice.id: row for row in await offered_catalogue(audience=audience)}
        assert SARVAM_VOICE_ID in rows, f"the added voice never reached the {audience} picker"
        assert rows[SARVAM_VOICE_ID].offerable is True, (
            f"the added voice was refused to the {audience} realm: {rows[SARVAM_VOICE_ID].reason}"
        )


async def test_an_added_cartesia_voice_is_added_and_still_names_its_remaining_ground() -> None:
    """THE FOUR GROUNDS STILL COMPOSE, AND ADDING CLEARS ONLY GROUND ZERO.

    This is the clause that matters if every agent ends up on a cloned — therefore Cartesia
    — voice: the voice is really added, and the reason nobody can be put on it yet is named
    (a missing key here; on a keyed, priced deployment it becomes
    `cartesia_cap_reached_reason`, which prints the cap and the live count). A screen that
    reported "added" and stopped would send the operator hunting for a bug.
    """
    await _add(_facts())

    rows = {row.voice.id: row for row in await offered_catalogue()}
    assert CLONE_VOICE_ID in rows, "the voice was not added at all"
    assert rows[CLONE_VOICE_ID].offerable is False
    assert "cartesia" in (rows[CLONE_VOICE_ID].reason or "").lower()


async def test_adding_a_voice_needs_no_sync_to_have_happened_first() -> None:
    """THE HALF THAT MAKES THIS AN ADD RATHER THAN A CURATION.

    D-588's answer required a sync first — you enabled a row somebody else's list had put
    there. The founder's requirement is to TYPE the facts, so a deployment that has never
    synced must still be able to add a voice and offer it. Nothing here calls the sync.
    """
    install_voice_catalogue(None)
    await _add(_facts())

    assert any(voice.id == CLONE_VOICE_ID for voice in catalogue()), (
        "an added voice did not reach the process snapshot, so no picker can render it "
        "and `speech_for_voice_id` cannot split its id on the publish path"
    )
    assert speech_for_voice_id(CLONE_VOICE_ID) == (CARTESIA_TTS_MODEL, CLONE_ID)


async def test_the_added_row_carries_the_platforms_own_name_and_its_clone_flag() -> None:
    """The NAME is a wire value (the vendor's synthesizer block requires `voice` beside
    `voice_id`) and is not derivable from a clone's id, so it must be stored as the platform
    spells it. `is_custom` comes from the engine's own `source` enum, never assumed."""
    await _add(_facts())

    async with untenanted_session() as session:
        row = await read_one_curated_voice(session, voice_id=CLONE_VOICE_ID)
    assert row.voice.label == CLONE_NAME
    assert row.voice.speaker == CLONE_ID
    assert row.is_custom is True
    assert row.origin == "operator"
    assert row.state == "enabled", "typing a voice's facts IS the decision to offer it"


# --- the verification, which is the quality bar ----------------------------------


async def test_an_id_the_platform_does_not_list_is_refused_by_name() -> None:
    """THE CLAUSE THAT REACHES A PHONE LINE.

    Publishing an agent on an id the platform does not carry returns a live
    `400 POST /v2/agent` — *"Provided voice: Anushka is not available for the provider:
    sarvam"* (11 Sep 2026) — which is discovered by a caller, not by the operator. So the
    refusal happens here, and it names the id so the operator can fix the field.
    """
    with pytest.raises(ProblemError) as refusal:
        await _add(_facts(engine_voice_id="not-a-real-clone"))
    assert refusal.value.code == "voice_not_on_platform"
    assert "not-a-real-clone" in refusal.value.detail
    assert refusal.value.kind == "business_rule", (
        "a voice the platform does not have is not a transient failure, and telling an "
        "operator to retry would be telling them to wait for something that never changes"
    )
    async with untenanted_session() as session:
        rows = await list_curated_voices(session, scope="all")
    assert not any(row.voice.speaker == "not-a-real-clone" for row in rows), (
        "a refused add left a row behind"
    )


async def test_an_unreadable_voice_platform_refuses_and_is_retryable() -> None:
    """WE REFUSE RATHER THAN ACCEPT AN UNVERIFIED ID, and the refusal says so.

    Accepting unverified would be exactly the pre-verification state with the failure moved
    from a form the operator is looking at to a call they are not. `kind="dependency"` is
    what makes it retryable — the console offers "try again" rather than "fix your input".
    """
    with pytest.raises(ProblemError) as refusal:
        async with untenanted_session() as session:
            await admit_voice(session, _StubEngine(None), _facts())  # type: ignore[arg-type]
    assert refusal.value.code == "voice_check_unavailable"
    assert refusal.value.kind == "dependency"
    assert refusal.value.as_problem()["retryable"] is True


async def test_an_incomplete_listing_is_a_different_refusal_from_a_missing_voice() -> None:
    """A page we could not read looks exactly like a shorter catalogue.

    Collapsing the two produces the worst message available: telling an operator their
    correctly-typed voice id does not exist because a pagination cap was hit. The same
    distinction `voice_sync` refuses to prune on.
    """
    with pytest.raises(ProblemError) as refusal:
        await _add(
            _facts(engine_voice_id="a-voice-on-an-unread-page"),
            _listing(_engine_voice(), complete=False),
        )
    assert refusal.value.code == "voice_check_incomplete"
    assert refusal.value.kind == "dependency"


async def test_a_name_that_is_not_the_platforms_name_is_refused_with_the_platforms_name() -> None:
    """The typed name is the operator's statement that they are adding the voice they think
    they are — the ONE check that catches a valid id belonging to a DIFFERENT voice. Case and
    whitespace are forgiven; a different name is not."""
    await _add(_facts(label=f"  {CLONE_NAME.upper()}  "))  # forgiven

    with pytest.raises(ProblemError) as refusal:
        await _add(_facts(label="Some Other Voice"))
    assert refusal.value.code == "voice_name_mismatch"
    assert CLONE_NAME in refusal.value.detail, (
        "the refusal did not print the platform's own name, so the fix is a guess"
    )


async def test_a_language_the_platform_does_not_list_is_refused() -> None:
    """A voice put on a Hindi picker that the platform does not synthesise in Hindi is the
    same class of failure as an unlisted id: a row that saves and fails on a call."""
    with pytest.raises(ProblemError) as refusal:
        await _add(_facts(languages=("te-IN", "hi-IN")))
    assert refusal.value.code == "voice_language_not_listed"
    assert "hi-IN" in refusal.value.detail


# --- the two refusals about our own catalogue ------------------------------------


async def test_an_elevenlabs_clone_is_refused_with_its_reason_not_silently_omitted() -> None:
    """THE FLAG THE FOUNDER HAS TO SEE.

    The voice platform clones on ElevenLabs or Cartesia (VERIFIED-VENDOR-DOCS,
    `bolna-findings/mirror/pages/clone-voices.md`, the "Select Provider" step). This product
    has no ElevenLabs model, so no provider, no tier and no price for a minute of it (hard
    rule 7). An operator who has just spent a sample cloning there needs the sentence, not a
    missing option — and the sentence has to name Cartesia as the thing to do instead.
    """
    assert "elevenlabs" in UNPUBLISHABLE_CLONING_PROVIDERS

    with pytest.raises(ProblemError) as refusal:
        await _add(_facts(provider="ElevenLabs"))
    assert refusal.value.code == "voice_provider_not_published_here"
    detail = refusal.value.detail.lower()
    assert "elevenlabs" in detail
    assert "cartesia" in detail, "the refusal did not tell the operator what to do instead"


async def test_a_model_that_does_not_belong_to_the_named_provider_is_refused() -> None:
    """Two fields, one voice: a disagreement between them means the operator is not holding
    the voice they think they are. Caught before the vendor call, because it is theirs to
    fix."""
    with pytest.raises(ProblemError) as refusal:
        await _add(_facts(provider="sarvam", tts_model=CARTESIA_TTS_MODEL))
    assert refusal.value.code == "voice_model_not_on_provider"
    assert DEFAULT_TTS_MODEL in refusal.value.detail


# --- hard rule 7: the tier is still the id's -------------------------------------


async def test_the_tier_is_derived_from_the_id_and_not_from_the_form() -> None:
    """PLAN §2.3 INVARIANT 7, UNREGRESSED. The provider field is an attestation that is
    cross-checked and then discarded; the billing tier comes off the id's model prefix
    through the one model→provider registry, so a form can never be the place an agent gets
    a Cartesia voice at a Sarvam rate."""
    await _add(_facts())

    async with untenanted_session() as session:
        row = await read_one_curated_voice(session, voice_id=CLONE_VOICE_ID)
    assert row.voice.provider == "cartesia"
    assert voice_tier(CLONE_VOICE_ID) == "cartesia"
    # Derived from the ID ALONE — true even with nothing in the catalogue at all, which is
    # the property the money lane needs (a cache miss must not re-price a minute).
    install_voice_catalogue(None)
    assert voice_tier(CLONE_VOICE_ID) == "cartesia"


# --- the properties D-588 established, held across the change --------------------


async def test_archiving_an_added_voice_does_not_break_an_agent_already_on_it() -> None:
    """UNCHANGED FROM D-588, AND IT IS THE CLAUSE THAT REACHES A CALL.

    `voices.catalogue()` is the LOOKUP layer and keeps resolving an archived id, so a live
    agent goes on publishing the model/speaker pair it was speaking. Only OFFERING narrows.
    """
    await _add(_facts())
    async with untenanted_session() as session:
        await set_curation_state(session, voice_id=CLONE_VOICE_ID, state="archived")
        await session.commit()

    assert speech_for_voice_id(CLONE_VOICE_ID) == (CARTESIA_TTS_MODEL, CLONE_ID), (
        "an archived voice stopped resolving, so a live agent's next publish would send "
        "the whole composed id in the vendor's speaker slot"
    )
    rows = {row.voice.id: row for row in await offered_catalogue()}
    assert rows[CLONE_VOICE_ID].offerable is False


async def test_a_sync_cannot_reclassify_or_un_offer_an_added_voice() -> None:
    """A SYNC REPORTS WHAT THE PLATFORM HAS; IT DOES NOT DECIDE WHAT WE SELL.

    The upsert names every column it refreshes and `origin`/`curation_state` are not among
    them, so re-reading the vendor's list cannot turn an operator's attestation back into a
    cache line — which would silently un-offer the voice on the next hourly tick.
    """
    await _add(_facts())
    async with untenanted_session() as session:
        await sync_voice_catalogue(
            session,
            _StubEngine(_listing(_engine_voice(languages=("te-IN", "en-IN")))),  # type: ignore[arg-type]
        )
        await session.commit()
    async with untenanted_session() as session:
        row = await read_one_curated_voice(session, voice_id=CLONE_VOICE_ID)
    assert row.origin == "operator"
    assert row.state == "enabled"


async def test_the_console_opens_on_decided_rows_and_says_how_many_it_is_not_showing() -> None:
    """THE FOUNDER'S ACTUAL COMPLAINT — *"these are too much"*.

    The default scope is what somebody decided about; the undecided cache is reachable but
    is not the opening screen. It hides nothing that is OFFERED: an enabled row is decided
    whatever its provenance, which is what keeps a legacy D-588 row visible.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_voice_catalog (voice_id, engine_voice_id, label, "
                "tts_model, provider, languages, is_custom, synced_at, curation_state) "
                "VALUES ('sonic-3.5:undecided', 'undecided', 'Undecided', 'sonic-3.5', "
                "'cartesia', ARRAY['te-IN'], false, now(), 'disabled')"
            )
        )
        await session.commit()
    await _add(_facts())

    async with untenanted_session() as session:
        decided = await list_curated_voices(session)
        everything = await list_curated_voices(session, scope="all")
    shown = {row.voice.id for row in decided}
    assert CLONE_VOICE_ID in shown
    assert "sonic-3.5:undecided" not in shown, "the opening screen is a curation chore again"
    assert "sonic-3.5:undecided" in {row.voice.id for row in everything}
