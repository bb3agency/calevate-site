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
from apps.api.billing.rates import (
    PREMIUM_VOICE_TIER,
    VALUE_VOICE_TIER,
    VOICE_TIERS,
    voice_tier_label,
)
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


def test_no_entry_carries_a_price_and_every_entry_says_it_is_not_on_sale() -> None:
    """Hard rule 7 at the surface a client reads.

    The only Gnani figure in the wild is a RESELLER's (₹27 per 10 000 characters, their
    platform's price and not Gnani's). It may not appear anywhere in this product.

    ⚠ **THE TIER NAME USED TO BE BANNED HERE TOO, AND IT IS NOW REQUIRED.** Gnani had no
    tier while Sarvam served the value rung; since 18 Sep 2026 it IS that rung, so naming it
    is a fact rather than an invention. What must not weaken is the SALEABILITY claim — a
    rung with no attested price may not read as on sale — so the note is held to saying so
    in its own words instead.
    """
    for entry in gnani_voice_entries():
        assert "₹" not in entry.note
        assert "27" not in entry.note
        assert voice_tier_label("gnani") in entry.note
        assert voice_tier_label("studio") not in entry.note
        assert "not yet on sale" in entry.note.lower()
        # AND IT NAMES NONE OF OUR MACHINERY: this string reaches a client on
        # `GET /v1/agents/voices`. The operator's version of the same fact —
        # "attest the Gnani TTS price in the ops console" — is
        # `voice_offer.no_attested_price_reason`, served per audience.
        for ours in ("attest", "ops console", "credential", "api key"):
            assert ours not in entry.note.lower()


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


def test_gnani_is_the_provider_of_the_value_rung_and_is_not_itself_a_tier() -> None:
    """⚠ **THIS ASSERTED `VOICE_TIER_OF_PROVIDER["gnani"] is None` UNTIL 18 Sep 2026.** The
    founder withdrew the Sarvam TTS leg and Gnani took the value rung. The rung it took is
    still called `"sarvam"` — a HISTORICAL money token, argued at `billing/rates.VoiceTier`
    — which is exactly why "gnani" must still not appear in `VOICE_TIERS`: a provider is
    not a tier, and this is the assertion that keeps the two vocabularies apart."""
    assert "gnani" in get_args(TtsProvider)
    assert VOICE_TIER_OF_PROVIDER["gnani"] == VALUE_VOICE_TIER
    assert "gnani" not in VOICE_TIERS
    assert "sarvam" not in get_args(TtsProvider), (
        "the Sarvam TTS leg is withdrawn; `sarvam` survives as a TIER token and must not "
        "come back as a provider (Sarvam STT is a different vocabulary entirely)"
    )


def test_a_label_is_total_over_providers_and_over_tiers() -> None:
    """⚠ **`voice_tier_label("gnani")` USED TO BE `UNPRICED_TIER_LABEL` ("Unreleased").**
    Both that constant and the hole it named are gone: every provider bills on a rung now,
    and Gnani's is the value one. The function takes either vocabulary because the two are
    now entirely disjoint: the rungs were renamed `clear`/`studio` on 19 Sep 2026 (D-630),
    so no token is both a provider and a tier any more — which is why every case below has
    to be asserted rather than inferred from one word covering two jobs."""
    assert voice_tier_label("clear") == "Clear"  # the TIER token
    assert voice_tier_label("studio") == "Studio"  # the other TIER token
    assert voice_tier_label("gnani") == "Clear"  # the PROVIDER of the value rung
    assert voice_tier_label("cartesia") == "Studio"  # the PROVIDER of the premium rung
    # It names no vendor: no client-facing surface calls a tier by its vendor.
    for label in ("Clear", "Studio"):
        assert "gnani" not in label.lower()
        assert "cartesia" not in label.lower()
        assert "sarvam" not in label.lower()


def test_a_minute_on_a_provider_with_no_rung_refuses_instead_of_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half that reaches money, and the reason the two questions were separated.

    §1.3 of `docs/PIPECAT-MIGRATION.md`: *"a leg we cannot price raises"*. Returning the
    value tier for a provider that has no rung would bill its minutes at the Clear rate on
    an append-only ledger, silently — the defect D-585 fixed for Cartesia.

    ⚠ **GNANI USED TO BE THE SUBJECT AND IS NOT ANY MORE**: it took the value rung on
    18 Sep 2026, so no provider reaches the refusal by itself today and the arm is driven
    through a patched mapping. That is deliberate rather than a weakening — `voice_tier`
    must keep REFUSING a provider whose rung nobody has decided, and the day a fourth vendor
    arrives that is the only thing standing between it and the cheaper rate.

    **WHAT STOPS A GNANI MINUTE BEING BILLED IS NOW A DIFFERENT GATE AND IT IS SHUT**: no
    Gnani price is attested, so `voice_offer` refuses the voice before an agent can hold it
    and `rates.tts_rate_inr_per_char` refuses the character if one ever does.
    """
    monkeypatch.setitem(VOICE_TIER_OF_PROVIDER, "gnani", None)
    with pytest.raises(UnpricedVoiceProviderError, match="no priced tier"):
        voice_tier("timbre-v2.5:Suhana")

    monkeypatch.undo()
    assert voice_tier("timbre-v2.5:Suhana") == VALUE_VOICE_TIER
    assert voice_tier("sonic-3.5:anything") == PREMIUM_VOICE_TIER
    # An id naming none of our models is the value rung, which is a decision and not a
    # fallback (`voices.voice_tier`). `bulbul:v3` is such an id now.
    assert voice_tier(None) == VALUE_VOICE_TIER
    assert voice_tier("bulbul:v3") == VALUE_VOICE_TIER
    assert voice_tier("bulbul:v3:shubh") == VALUE_VOICE_TIER
