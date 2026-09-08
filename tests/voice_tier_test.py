"""The second voice tier (D-547): the catalogue's shape, the tier derivation, and the
three grounds that decide whether a Cartesia voice may be OFFERED at all.

This file is about what `agents/voices.py` and `agents/voice_offer.py` promise, and the
promises are of two different kinds:

* **STRUCTURAL** — the catalogue has room for a second provider, builds its Cartesia
  entries from vendor records rather than from typed-in ids, and the whole thing holds
  with ZERO Cartesia entries, which is the state this phase ships in. Nobody here has read
  a Cartesia voice id (the library is behind a login), so shipping an invented one would
  publish an agent that 422s on a client's phone — see `CARTESIA_CATALOG_SOURCE`.
* **LIVE** — a key, a price and a platform-wide cap. Each is somebody's to fix and each
  refusal names which somebody, because a picker that could only say "unavailable" sends
  all three to support.

The DB-backed cross-tenant count (`count_live_cartesia_agents`) is not exercised here: the
predicates take the count as a parameter precisely so every refusal arm is drivable without
one, and the query itself is one statement under the tenant's own GUC.
"""

from __future__ import annotations

from typing import get_args

import pytest
from apps.api.agents import voice_offer
from apps.api.agents.voice_offer import (
    NO_ATTESTED_TTS_PRICE_REASON,
    NO_CARTESIA_CREDENTIAL_REASON,
    OfferedVoice,
    cartesia_cap_reached_reason,
    client_unofferable_reason,
    install_tts_price_reader,
    offerable_voices,
    unofferable_reason,
)
from apps.api.agents.voices import (
    CARTESIA_CATALOG_SOURCE,
    CARTESIA_TTS_MODEL,
    CATALOG,
    DEFAULT_VOICE_ID,
    CartesiaVoiceRecord,
    TtsModel,
    Voice,
    _cartesia_entry,
    cartesia_catalogue,
    default_voice,
    voice_id_for,
    voice_tier,
)
from apps.api.billing.rates import voice_tier_label
from apps.api.core.settings import get_settings
from calevate_shared.model_lifecycle import TTS_MODEL_LIFECYCLE


@pytest.fixture(autouse=True)
def _clean_price_reader() -> object:
    """Every case installs its own price predicate; none leaks into the next."""
    yield None
    install_tts_price_reader(None)


@pytest.fixture
def _cartesia_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that has cleared grounds 1 and 2 — key installed, price attested — so
    a case can drive ground 3 without re-stating the other two."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: True)
    install_tts_price_reader(lambda _provider: True)


def _record() -> CartesiaVoiceRecord:
    """ONE vendor record, and its id is deliberately not a plausible Cartesia id: nothing
    in this tree has read one, and a fixture that looked real is how an invented id ends up
    quoted as fact (hard rule 11)."""
    return CartesiaVoiceRecord(
        id="test-record-not-a-real-voice-id", name="Test Persona", languages=("te-IN",)
    )


# --- C.1: the catalogue's shape ------------------------------------------------


def test_the_catalogue_names_two_models_one_per_provider() -> None:
    """`TtsModel` is the set the lifecycle guard is held to, so it is the set that decides
    which voice models this product can ship at all."""
    assert set(get_args(TtsModel)) == {"bulbul:v3", "sonic-3.5"}
    assert CARTESIA_TTS_MODEL == "sonic-3.5"
    assert "sonic-3" not in get_args(TtsModel), (
        "sonic-3 is deprecated with a 20 Oct 2026 sunset and the engine recommends 3.5 for "
        "production — offering it would put a client on a dated model"
    )


def test_the_cartesia_catalogue_is_empty_and_that_is_the_point() -> None:
    """SHIPPING ZERO ENTRIES IS THE DESIGN, not an oversight. The vendor's voice ids are
    behind a login this container cannot reach; an id nobody read is an id somebody
    invented, and it publishes an agent that fails on a real client's phone."""
    assert CARTESIA_CATALOG_SOURCE == ()
    assert all(voice.provider == "sarvam" for voice in CATALOG)
    # And the import-time assertions in `voices.py` held at zero, which is what makes the
    # module importable at all — this test would not have run otherwise.
    assert default_voice().provider == "sarvam", "Cartesia is chosen, never inherited (Q9)"
    assert default_voice().id == DEFAULT_VOICE_ID


def test_a_cartesia_entry_is_built_from_a_vendor_record_not_typed_in() -> None:
    """The loader is the seam the vendor's `GET /voices` output drops into. Everything the
    catalogue needs is derived from the record — the id spelling included, through
    `voice_id_for`, so `agents/service.speech_for_voice_id` can split it back apart."""
    voice = _cartesia_entry(_record())

    assert isinstance(voice, Voice)
    assert voice.provider == "cartesia"
    assert voice.tts_model == CARTESIA_TTS_MODEL
    assert voice.id == voice_id_for("sonic-3.5", "test-record-not-a-real-voice-id")
    assert voice.speaker == "test-record-not-a-real-voice-id"
    assert voice.is_default is False, "the dearer tier is never a default"
    assert voice.verified is False, "no Cartesia voice has been heard on this engine"
    assert "Telugu" in voice.note and "English" in voice.note, (
        "Cartesia vouches for Hinglish and Taglish and says speech outside those cases "
        "may sound accented; Telugu-English is not among them, so every Telugu entry "
        "carries that caveat rather than letting a screen imply the mixing"
    )


def test_an_archived_vendor_voice_never_enters_the_catalogue() -> None:
    """Cartesia's list endpoint omits archived voices by default, so a record marked
    archived arrived through a wider fetch somebody made deliberately — and offering a voice
    the vendor has withdrawn from its own library puts a client on it. ONE filter, in the
    loader, rather than at every reader."""
    live = _record()
    gone = CartesiaVoiceRecord(
        id="archived-record", name="Retired Persona", languages=("te-IN",), archived=True
    )

    built = cartesia_catalogue((live, gone))

    assert [voice.speaker for voice in built] == [live.id]


def test_the_loader_carries_languages_not_the_vendors_deprecated_field() -> None:
    """Cartesia marks the top-level `language` field DEPRECATED in its own schema with
    "prefer accents[].locale" beside it, so the record is keyed on the languages a
    translator resolved from the accents — a loader on the deprecated field goes quietly
    wrong the day they remove it."""
    record = CartesiaVoiceRecord(
        id="two-language-voice", name="Bilingual", languages=("te-IN", "en-IN")
    )

    voice = _cartesia_entry(record)

    assert voice.languages == ("te-IN", "en-IN")
    assert not hasattr(record, "language"), "the deprecated singular field has no home here"


def test_the_shared_note_states_no_price() -> None:
    """A rate card in a dropdown string is a second definition of a number that reaches
    money (hard rule 7). Under D-547 a minute's price is the rate frozen on the credit lot
    it draws from, and there are two of them per lot — so no figure belongs here."""
    for voice in (*CATALOG, _cartesia_entry(_record())):
        assert "₹" not in voice.note, f"{voice.id} quotes a price the rate card owns"
        assert "10k" not in voice.note


# --- C.8: the tier derivation --------------------------------------------------


def test_the_tier_is_the_provider_and_nothing_else() -> None:
    """Plan §2.3 invariant 7: there is no way to hold a Cartesia voice and a Sarvam tier,
    because the tier is not stored anywhere it could disagree with the voice."""
    for voice in CATALOG:
        assert voice_tier(voice.id) == voice.provider
    assert voice_tier(_cartesia_entry(_record()).id) == "sarvam", (
        "a voice built but not REGISTERED in the catalogue is not a catalogue id, so it "
        "cannot claim the dearer tier — the lookup is the whole authority"
    )


def test_an_unknown_or_missing_voice_is_the_cheaper_tier() -> None:
    """A decision, not a fallback: an agent with no voice speaks the engine's default
    Sarvam persona, and a legacy free-text row is a Sarvam row. Defaulting the other way
    would bill an unmigrated agent at the dearer rate for a call it never made there."""
    for unknown in (None, "", "bulbul:v3", "sonic-3.5", "whatever-this-is"):
        assert voice_tier(unknown) == "sarvam"


# --- C.2: offerability ----------------------------------------------------------


def test_a_sarvam_voice_is_offerable_with_no_cartesia_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Cartesia grounds must not reach the tier that has none of them: its key is the
    engine account's own, its cost is on the rate card, and no cap applies."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    for voice in CATALOG:
        assert unofferable_reason(voice, cartesia_live_agents=10_000) is None


def test_a_cartesia_voice_with_no_key_names_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    install_tts_price_reader(lambda _provider: True)

    reason = unofferable_reason(_cartesia_entry(_record()), cartesia_live_agents=0)

    assert reason == NO_CARTESIA_CREDENTIAL_REASON
    assert "cartesia_api_key" in reason, "the reader is told which field to fill"


def test_a_cartesia_voice_with_no_attested_price_names_the_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 7 at the SELECTION rather than at the meter: an unpriced minute is
    unmetered spend, and the only place refusing it is free is before the call."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: True)

    reason = unofferable_reason(_cartesia_entry(_record()), cartesia_live_agents=0)

    assert reason == NO_ATTESTED_TTS_PRICE_REASON


def test_the_default_price_predicate_answers_for_the_two_tiers_honestly() -> None:
    """Phase D installs the real attestation. Until it does, the shipped default is not a
    placeholder that says yes: Sarvam's TTS cost is on the rate card, Cartesia's is
    recorded by nobody, and answering otherwise would let a client onto an unpriced tier."""
    assert voice_offer.tts_price_is_billable("sarvam") is True
    assert voice_offer.tts_price_is_billable("cartesia") is False


def test_the_cap_refuses_by_name_and_carries_both_numbers(_cartesia_ready: None) -> None:
    """An operator deciding whether to RAISE the cap needs to know how far past it they
    are; a bare "unavailable" makes the decision unmakeable."""
    cap = get_settings().cartesia_agent_cap
    voice = _cartesia_entry(_record())

    assert unofferable_reason(voice, cartesia_live_agents=cap - 1) is None
    reason = unofferable_reason(voice, cartesia_live_agents=cap)
    assert reason == cartesia_cap_reached_reason(cap=cap, live=cap)
    assert str(cap) in reason and "cartesia_agent_cap" in reason


def test_the_cap_defaults_to_the_founders_two() -> None:
    """Q10's number, and `0` is the switch that turns the tier off entirely."""
    assert get_settings().cartesia_agent_cap == 2


def test_every_voice_comes_back_with_its_verdict_never_a_shorter_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Cartesia voice MISSING from the answer is indistinguishable from a Cartesia tier
    this product does not sell — so the operator who pasted the key an hour ago cannot see
    that the price is what is still missing. The reason is the product; filtering is the
    caller's."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: True)
    catalogue = (*CATALOG, _cartesia_entry(_record()))

    offered = offerable_voices(cartesia_live_agents=0, voices=catalogue)

    assert len(offered) == len(catalogue), "the list never shrinks"
    assert [row.voice for row in offered] == list(catalogue)
    verdicts = {row.voice.provider: row for row in offered}
    assert verdicts["sarvam"].offerable is True and verdicts["sarvam"].reason is None
    assert verdicts["cartesia"].offerable is False
    assert verdicts["cartesia"].reason == NO_ATTESTED_TTS_PRICE_REASON


def test_the_three_reasons_are_three_different_sentences() -> None:
    """They have three different OWNERS — a key the founder pastes, a price read off an
    invoice, a cap an operator raises after deciding to. One collapsed sentence sends all
    three to support."""
    reasons = {
        NO_CARTESIA_CREDENTIAL_REASON,
        NO_ATTESTED_TTS_PRICE_REASON,
        cartesia_cap_reached_reason(cap=2, live=2),
    }
    assert len(reasons) == 3
    assert all(reason and not reason[0].isupper() for reason in reasons), (
        "each completes a sentence the picker starts, so none begins with a capital"
    )


# --- C.6: the catalogue and the lifecycle table cannot drift -------------------


def test_every_shipped_voice_model_has_a_lifecycle_row() -> None:
    """The equality `scripts/check_model_lifecycle` enforces, asserted here too so a
    catalogue edit fails in the unit suite rather than only in `make guardrails`."""
    assert set(TTS_MODEL_LIFECYCLE) == set(get_args(TtsModel))
    assert {row.provider for row in TTS_MODEL_LIFECYCLE.values()} == {"sarvam", "cartesia"}


# --- what a client is told the tier is CALLED ---------------------------------


def test_the_wire_carries_the_tier_name_so_the_browser_never_holds_a_copy() -> None:
    """The founder's 7 Sep 2026 decision, at the one place it can be enforced.

    `provider` stays on the wire — the ledger, the lot rows and a vendor invoice are all
    reconciled against it. `tier_label` is what a human is shown, and it is SERVED rather
    than looked up in TypeScript for the reason the marketing provenance rule exists: a
    second copy of the name in the browser is how the two drift until one client meets
    both. A picker that had to map `provider` to a name itself would be that second copy.
    """
    from apps.api.agents.voice_routes import OfferedVoiceOut
    from apps.api.billing.rates import voice_tier_label

    for voice in CATALOG:
        row = OfferedVoiceOut.of(OfferedVoice(voice=voice, reason=None))
        assert row.tier_label == voice_tier_label(voice.provider)
        assert row.provider not in row.tier_label.lower(), (
            "the label a client reads must not be the vendor's name"
        )


# --- C.2b: whose language a refusal is in --------------------------------------
#
# `GET /v1/agents/voices` is `agents:read` in EITHER realm, and all three grounds above name
# a vendor while two of them name one of our own settings. So the sentence forks by audience
# the way `llm_models.unofferable_reason` already forks for a model — the operator keeps the
# ground they can fix, a client is told the one action they have. `tests/agent_voice_test.py`
# is where the ROUTE is proved to pick the right one from the realm; these are the predicate.


def _a_refusing_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key and no attested price: a deployment on which every Cartesia voice refuses."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    install_tts_price_reader(lambda _provider: False)


def test_a_client_reads_one_sentence_that_names_no_vendor_and_no_setting_of_ours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE LEAK THIS FORK EXISTS TO CLOSE. Every operator ground names Cartesia, and two of
    them name a field only we can edit — on a route a tenant may read. A client gets the
    tier's client-facing name and the one action they have."""
    voice = _cartesia_entry(_record())
    cap = get_settings().cartesia_agent_cap
    states = (
        # (key installed, price billable, live agents) — one per ground, in the module's order.
        (False, True, 0),
        (True, False, 0),
        (True, True, cap),
    )
    for installed, priced, live in states:
        monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda i=installed: i)
        install_tts_price_reader(lambda _provider, p=priced: p)

        operator = unofferable_reason(voice, cartesia_live_agents=live, audience="operator")
        client = unofferable_reason(voice, cartesia_live_agents=live, audience="client")

        assert operator is not None, "this state must refuse, or the case proves nothing"
        assert client == client_unofferable_reason(voice)
        assert "cartesia" not in client.lower(), "the vendor's name reached a client"
        assert "sarvam" not in client.lower()
        for setting in ("cartesia_api_key", "cartesia_agent_cap", "ops console", "attest"):
            assert setting not in client.lower(), f"{setting!r} is ours, not a client's"
        assert voice_tier_label(voice.provider) in client, (
            "a client is told WHICH voice quality is unavailable, by the name they know it by"
        )
        assert str(cap) not in client, "the platform-wide cap is not a client's business"


def test_offerability_itself_does_not_fork_by_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    """`None`-ness is one fact for both readers — which is what lets `OfferedVoice.offerable`
    stay derived from the reason instead of computed a second way per audience."""
    _a_refusing_deployment(monkeypatch)
    catalogue = (*CATALOG, _cartesia_entry(_record()))
    for audience in ("operator", "client"):
        rows = offerable_voices(cartesia_live_agents=0, voices=catalogue, audience=audience)
        assert [row.offerable for row in rows] == [
            row.offerable for row in offerable_voices(cartesia_live_agents=0, voices=catalogue)
        ]
        assert all(row.offerable is (row.reason is None) for row in rows)


def test_the_default_audience_is_the_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every existing caller — the write backstop, the ops console, these tests — asked
    without an audience and must keep getting the actionable ground. The client realm opts
    in, at the route."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    voice = _cartesia_entry(_record())
    assert unofferable_reason(voice, cartesia_live_agents=0) == NO_CARTESIA_CREDENTIAL_REASON
    assert (
        unofferable_reason(voice, cartesia_live_agents=0, audience="operator")
        == NO_CARTESIA_CREDENTIAL_REASON
    )


def test_an_offerable_voice_carries_no_sentence_for_either_reader() -> None:
    """A refusal a client cannot act on is bad; a refusal on a voice they CAN choose would
    be worse. Sarvam fails no ground, so both audiences get `None`."""
    for voice in CATALOG:
        for audience in ("operator", "client"):
            assert unofferable_reason(voice, cartesia_live_agents=0, audience=audience) is None
