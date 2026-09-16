"""D-618: the Gnani voice catalogue, and the tier question it forced open.

**THE POINT OF THE FIRST HALF IS THAT THE NAMES ARE CHECKED AGAINST THE VENDOR.**
`apps/api/agents/gnani_voices.py` types 24 voice names out, because hard rule 2 forbids
`apps/api` importing a vendor SDK and `docs.gnani.ai` is egress-blocked from this container
(HTTP 000, 15 Sep 2026) so nothing there can be fetched. A typed list nobody checks is
exactly the defect D-585 was caused by — a catalogue compiled from one source and sent to
another, discovered on a client's phone. A TEST may import the SDK, so this file holds our
table against `gnani.tts.client.TIMBRE_V25_VOICES` in the installed `gnani-vachana` 0.7.9
wheel (pinned in `uv.lock` by sha256), name for name.

**THE POINT OF THE SECOND HALF IS THAT A PROVIDER IS NOT A TIER.** Gnani publish no price,
so there is no rate to freeze on a credit lot and no floor to clear — and the type system
was saying so before this file did (four `voice_tier_label` call sites stopped
type-checking the moment `TtsProvider` grew a third member). The tests below pin the
answer: a label to RENDER is total over providers, and a tier to CHARGE against refuses.
"""

from __future__ import annotations

from typing import get_args

import pytest
from apps.api.agents.gnani_voices import (
    GNANI_PROVIDER,
    GNANI_TTS_MODEL,
    GNANI_VOICE_LANGUAGES,
    gnani_voice_entries,
    gnani_voice_language,
    gnani_voice_names,
)
from apps.api.agents.languages import Language
from apps.api.agents.voices import (
    VOICE_TIER_OF_PROVIDER,
    UnpricedVoiceProviderError,
    provider_of_tts_model,
    tts_model_of_voice_id,
    tts_models_for_provider,
    voice_id_for,
    voice_tier,
)
from apps.api.billing.rates import UNPRICED_TIER_LABEL, VOICE_TIERS, voice_tier_label
from calevate_shared.model_lifecycle import TTS_MODEL_LIFECYCLE, TtsProvider
from gnani.tts.client import SUPPORTED_MODELS, SUPPORTED_TTS_LANGUAGES, TIMBRE_V25_VOICES

# --------------------------------------------------------------------------------------
# The names, against the vendor's own package.
# --------------------------------------------------------------------------------------


def test_every_voice_we_offer_is_a_voice_the_vendor_ships() -> None:
    unknown = sorted(set(GNANI_VOICE_LANGUAGES) - set(TIMBRE_V25_VOICES))
    assert not unknown, (
        f"{unknown} are not `timbre-v2.5` voices in gnani-vachana. A name this product "
        "offers and the vendor does not is a 422 on a client's phone line."
    )


def test_the_three_language_groups_are_the_vendors_own_counts() -> None:
    """The vendor groups its 42 voices by locale; we take three groups whole.

    Counts rather than a re-typed list, because the names are already asserted above: what
    this catches is a voice DROPPED from our table, which no membership check would see.
    """
    assert len(gnani_voice_names("te-IN")) == 5
    assert len(gnani_voice_names("hi-IN")) == 13
    assert len(gnani_voice_names("en-IN")) == 6
    assert len(GNANI_VOICE_LANGUAGES) == 24


def test_the_other_eighteen_voices_are_deliberately_absent() -> None:
    """Tamil, Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi and Hinglish.

    They are REAL and they are not offered, because this product sells three languages.
    Asserted so that "24 of 42" stays a decision rather than becoming an omission nobody
    can tell from a typo.
    """
    assert len(TIMBRE_V25_VOICES) == 42
    assert "Poorvi" in TIMBRE_V25_VOICES  # Hinglish
    assert "Poorvi" not in GNANI_VOICE_LANGUAGES
    assert "Asmita" in TIMBRE_V25_VOICES  # Tamil
    assert "Asmita" not in GNANI_VOICE_LANGUAGES


def test_every_language_we_pair_a_voice_with_is_one_the_vendor_serves() -> None:
    for name, language in GNANI_VOICE_LANGUAGES.items():
        assert language in SUPPORTED_TTS_LANGUAGES, f"{name} is paired with {language}"


def test_the_model_string_is_the_vendors_and_the_two_copies_agree() -> None:
    """`apps/voice-worker` may not import `apps/api`, so the constant exists twice."""
    from voice_worker.gnani_tts import GNANI_TTS_MODEL as WORKER_MODEL

    assert GNANI_TTS_MODEL in SUPPORTED_MODELS
    assert GNANI_TTS_MODEL == WORKER_MODEL == "timbre-v2.5"


# --------------------------------------------------------------------------------------
# The entries.
# --------------------------------------------------------------------------------------


def test_an_entry_spells_its_id_the_way_every_other_catalogue_entry_does() -> None:
    entries = {entry.id: entry for entry in gnani_voice_entries()}
    suhana = entries[voice_id_for(GNANI_TTS_MODEL, "Suhana")]

    assert suhana.id == "timbre-v2.5:Suhana"
    assert suhana.provider == GNANI_PROVIDER
    assert suhana.tts_model == GNANI_TTS_MODEL
    # The vendor names a voice on the wire, so the speaker and the label are one string.
    assert suhana.speaker == suhana.label == "Suhana"
    assert suhana.languages == ("te-IN",)


def test_no_entry_claims_to_have_been_verified_by_a_listing() -> None:
    """`verified` means a LIVE listing on our own account returned it. Gnani expose none."""
    assert all(entry.verified is False for entry in gnani_voice_entries())


def test_no_entry_carries_a_price_or_a_tier_name() -> None:
    """Hard rule 7 at the surface a client reads.

    The only Gnani figure in the wild is a RESELLER's (₹27 per 10 000 characters, their
    platform's price and not Gnani's). It may not appear anywhere in this product, and
    neither may a tier name, because Gnani is not on a tier.
    """
    for entry in gnani_voice_entries():
        assert "₹" not in entry.note
        assert "27" not in entry.note
        for tier in VOICE_TIERS:
            assert voice_tier_label(tier) not in entry.note


def test_the_entries_are_not_installed_into_the_live_catalogue() -> None:
    """D-588: only voices an operator enabled are selectable, so a compiled list may not
    be in force merely because it was imported."""
    from apps.api.agents import voices

    assert all(entry.id not in voices.voice_ids() for entry in gnani_voice_entries())


def test_a_voice_name_we_do_not_offer_resolves_to_no_language() -> None:
    assert gnani_voice_language("Suhana") == "te-IN"
    assert gnani_voice_language("Poorvi") is None  # a real voice, a language we do not sell
    assert gnani_voice_language("Nobody") is None


def test_every_language_in_the_table_is_one_the_product_sells() -> None:
    sold: set[Language] = set(get_args(Language))
    assert set(GNANI_VOICE_LANGUAGES.values()) <= sold


# --------------------------------------------------------------------------------------
# Provider, model and tier.
# --------------------------------------------------------------------------------------


def test_the_model_registry_knows_who_synthesises_it() -> None:
    assert provider_of_tts_model(GNANI_TTS_MODEL) == "gnani"
    assert tts_models_for_provider("gnani") == (GNANI_TTS_MODEL,)
    assert tts_model_of_voice_id("timbre-v2.5:Suhana") == "timbre-v2.5"


def test_the_lifecycle_row_says_nobody_has_read_a_retirement_page() -> None:
    """Hard rule 11's distinction, on the first row in this tree that needs it.

    `unread` is not `none-announced`: no Gnani lifecycle page has been opened by anybody,
    and the four pages that WERE read are not lifecycle pages. Claiming the vendor
    announced nothing would be the laundering that produced the Gemini retirement defect.
    """
    row = TTS_MODEL_LIFECYCLE[GNANI_TTS_MODEL]
    assert row.provider == "gnani"
    assert row.retirement_stance == "unread"
    assert row.retires_on is None
    assert row.retirement.verified is False
    # The availability half IS verified, and against the strongest source a blocked host
    # leaves: the vendor's own installed wheel.
    assert row.availability.verified is True


def test_gnani_is_a_provider_and_not_a_priced_tier() -> None:
    assert "gnani" in get_args(TtsProvider)
    assert VOICE_TIER_OF_PROVIDER["gnani"] is None
    assert "gnani" not in VOICE_TIERS


def test_a_label_is_total_over_providers_because_a_table_has_to_render() -> None:
    assert voice_tier_label("sarvam") == "Clear"
    assert voice_tier_label("cartesia") == "Studio"
    assert voice_tier_label("gnani") == UNPRICED_TIER_LABEL
    # It names no vendor: no client-facing surface calls a tier by its vendor.
    assert "gnani" not in UNPRICED_TIER_LABEL.lower()


def test_a_minute_on_an_unpriced_provider_refuses_instead_of_billing() -> None:
    """The half that reaches money, and the reason the two questions were separated.

    §1.3 of `docs/PIPECAT-MIGRATION.md`: *"a leg we cannot price raises"*. Returning
    `"sarvam"` here would bill a Gnani minute at the Clear rate on an append-only ledger,
    silently — which is the defect D-585 fixed for Cartesia and which a third provider
    would have reintroduced.
    """
    with pytest.raises(UnpricedVoiceProviderError, match="no priced tier"):
        voice_tier("timbre-v2.5:Suhana")

    # Unchanged for everything that IS priced, including the two legacy readings.
    assert voice_tier("bulbul:v3:shubh") == "sarvam"
    assert voice_tier("sonic-3.5:anything") == "cartesia"
    assert voice_tier(None) == "sarvam"
    assert voice_tier("bulbul:v3") == "sarvam"
