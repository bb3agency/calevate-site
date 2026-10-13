"""The voice tier (D-547): the catalogue's shape, the tier derivation, and the price ground.

`agents/voices.py` derives the tier a minute bills on from the voice id's own model prefix,
never from catalogue membership, so a voice absent from the cached catalogue still prices
on its real rung (hard rule 7). `agents/voice_offer.py` answers whether a provider's minute
is billable at all; with nothing attested, nothing is.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import get_args

import pytest
from apps.api.agents import voice_offer
from apps.api.agents import voices as voices_module
from apps.api.agents.voice_offer import install_tts_price_reader
from apps.api.agents.voices import (
    VOICE_TIER_OF_PROVIDER,
    TtsModel,
    Voice,
    VoiceProvider,
    catalogue,
    catalogue_note,
    voice_id_for,
    voice_tier,
)
from apps.api.billing.rates import VALUE_VOICE_TIER
from tests.voice_fixture import STUDIO_TTS_MODEL


@pytest.fixture(autouse=True)
def _clean_price_reader() -> Iterator[None]:
    """A COLD platform: nothing attested. `conftest._tts_price_reader_is_restored` puts the
    suite's reader back afterwards."""
    install_tts_price_reader(None)
    yield None
    install_tts_price_reader(None)


def _cartesia_voice(speaker: str = "test-record-not-a-real-voice-id") -> Voice:
    """ONE Cartesia catalogue entry. Its id is deliberately not a plausible Cartesia id:
    a fixture that looked real is how an invented id ends up quoted as fact (hard rule 11)."""
    return Voice(
        id=voice_id_for(STUDIO_TTS_MODEL, speaker),
        label="Test Persona",
        provider="cartesia",
        tts_model=STUDIO_TTS_MODEL,
        speaker=speaker,
        languages=("te-IN",),
        gender=None,
        verified=True,
        note=catalogue_note("cartesia"),
    )


# --- the catalogue's shape -----------------------------------------------------


def test_the_catalogue_names_one_model_per_provider() -> None:
    """`TtsModel` is the set the lifecycle guard is held to, so it is the set that decides
    which voice models this product can ship at all."""
    assert set(get_args(TtsModel)) == {STUDIO_TTS_MODEL}


def test_a_cartesia_entry_carries_the_tier_and_the_telugu_caveat() -> None:
    """What a Cartesia catalogue entry must carry however it was built: the dearer tier, the
    id spelling `speech_for_voice_id` can split back apart, and the vendor's own caveat."""
    voice = _cartesia_voice()

    assert voice.provider == "cartesia"
    assert voice.tts_model == STUDIO_TTS_MODEL
    assert voice.id == voice_id_for("sonic-3.5", "test-record-not-a-real-voice-id")
    assert voice.speaker == "test-record-not-a-real-voice-id"
    assert "Telugu" in voice.note and "English" in voice.note, (
        "Cartesia vouches for Hinglish and Taglish and says speech outside those cases "
        "may sound accented; Telugu-English is not among them, so every Telugu entry "
        "carries that caveat rather than letting a screen imply the mixing"
    )


def test_the_shared_note_states_no_price() -> None:
    """A rate card in a dropdown string is a second definition of a number that reaches
    money (hard rule 7): a minute's price is the rate frozen on the credit lot it draws from."""
    for voice in (*catalogue(), _cartesia_voice()):
        assert "₹" not in voice.note, f"{voice.id} quotes a price the rate card owns"
        assert "10k" not in voice.note


# --- the tier derivation --------------------------------------------------------


def test_the_tier_is_the_provider_and_nothing_else() -> None:
    """Plan §2.3 invariant 7: the tier is not stored anywhere it could disagree with the
    voice."""
    for voice in catalogue():
        assert voice_tier(voice.id) == VOICE_TIER_OF_PROVIDER[voice.provider]
    assert voice_tier(_cartesia_voice().id) == "studio"


def test_an_unknown_or_missing_voice_is_the_cheaper_tier() -> None:
    """A decision, not a fallback: a row naming no model we offer is a value-rung row.
    Defaulting the other way would bill an unmigrated agent at the dearer rate for a call it
    never made there. A bare `sonic-3.5` is the legacy spelling of a Cartesia row and
    prices as one."""
    for unknown in (None, "", "retired-model:speaker", "whatever-this-is", "Anushka", "retired"):
        assert voice_tier(unknown) == VALUE_VOICE_TIER
    assert voice_tier("sonic-3.5") == "studio", (
        "a legacy row naming the Cartesia model is a Cartesia row; billing it on the value "
        "rung is unmetered spend on the dearer tier (hard rule 7)"
    )


def test_catalogue_membership_cannot_re_tier_an_agent_or_re_price_a_minute() -> None:
    """`voice_tier()` is a pure function of the id. It must hold with NOTHING installed —
    the state of a process that has never synced, where a membership-based derivation would
    answer the value rung for every id."""
    for voice in (*catalogue(), _cartesia_voice()):
        expected = VOICE_TIER_OF_PROVIDER[voice.provider]
        assert voice_tier(voice.id) == expected
        installed = catalogue()
        try:
            voices_module.install_voice_catalogue(None)
            assert voice_tier(voice.id) == expected, (
                "the tier moved when the catalogue emptied — it is reading membership "
                "again, and a Studio minute would bill at the Clear rate"
            )
        finally:
            voices_module.install_voice_catalogue(installed or None)


# --- the price ground -------------------------------------------------------------


def test_the_default_price_predicate_answers_for_every_provider_honestly() -> None:
    """With an empty price store nothing is billable: answering otherwise would let a client
    onto a tier whose minutes meter as free (hard rule 7)."""
    install_tts_price_reader(None)
    for provider in get_args(VoiceProvider):
        assert voice_offer.tts_price_is_billable(provider) is False, provider
        assert voice_offer.default_tts_price_is_billable(provider) is False, provider


def test_an_installed_reader_is_what_answers() -> None:
    install_tts_price_reader(lambda provider: provider == "cartesia")
    assert voice_offer.tts_price_is_billable("cartesia") is True
