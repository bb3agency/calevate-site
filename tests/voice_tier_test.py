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
from apps.api.agents import voices as voices_module
from apps.api.agents.voice_offer import (
    ARCHIVED_REASON,
    DISABLED_REASON,
    NO_ATTESTED_TTS_PRICE_REASON,
    NO_CARTESIA_CREDENTIAL_REASON,
    NOT_CURATED_REASON,
    OfferedVoice,
    cartesia_cap_reached_reason,
    client_unofferable_reason,
    install_tts_price_reader,
    offerable_voices,
    unofferable_reason,
)
from apps.api.agents.voices import (
    CARTESIA_TTS_MODEL,
    CurationState,
    TtsModel,
    Voice,
    catalogue,
    catalogue_note,
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


def _cartesia_voice(speaker: str = "test-record-not-a-real-voice-id") -> Voice:
    """ONE Cartesia catalogue entry, as the ENGINE SYNC would build it.

    Its id is deliberately not a plausible Cartesia id: nothing in this tree has read one,
    and a fixture that looked real is how an invented id ends up quoted as fact (hard rule
    11). It is built HERE rather than through a loader because D-588 deleted the hand-loaded
    Cartesia list — the only route into the catalogue is now `voice_sync.voice_from_engine`,
    and these clauses are about the OFFER seam, not about that translation.
    """
    return Voice(
        id=voice_id_for(CARTESIA_TTS_MODEL, speaker),
        label="Test Persona",
        provider="cartesia",
        tts_model=CARTESIA_TTS_MODEL,
        speaker=speaker,
        languages=("te-IN",),
        gender=None,
        verified=True,
        note=catalogue_note("cartesia"),
    )


def _curation(*extra: Voice, state: CurationState = "enabled") -> dict[str, CurationState]:
    """Offerability GROUND ZERO, cleared — so a clause about the three PRICED grounds is
    driving the ground it means to.

    Every clause below passes it explicitly rather than defaulting it inside the predicate,
    which is the property that makes curation compose instead of masking: a test that forgot
    it fails loudly rather than silently exercising an enabled platform.
    """
    return {voice.id: state for voice in (*catalogue(), *extra)}


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


def test_no_cartesia_voice_is_typed_into_this_product_anywhere() -> None:
    """SHIPPING NO HAND-WRITTEN CARTESIA ID IS THE DESIGN, and D-588 made it structural.

    The vendor's voice library is behind a login this container cannot reach; an id nobody
    read is an id somebody invented, and it publishes an agent that fails on a real client's
    phone. `voices.py` used to ship the SHAPE of a hand-loaded list waiting to be filled —
    `CartesiaVoiceRecord`, an empty `CARTESIA_CATALOG_SOURCE`, a loader. All of it is gone:
    the ENGINE enumerates its own providers, so a Cartesia voice arrives through the same
    sync as a Sarvam one, with an id somebody read.
    """
    import apps.api.agents.voices as voices_source

    for gone in (
        "CARTESIA_CATALOG_SOURCE",
        "CartesiaVoiceRecord",
        "cartesia_catalogue",
        "_cartesia_entry",
        "SEED_CATALOG",
        "SEED_SPEAKERS",
        "SPEAKERS",
        "Speaker",
        "DEFAULT_SPEAKER",
        "DEFAULT_VOICE_ID",
        "default_voice",
    ):
        assert not hasattr(voices_source, gone), (
            f"`voices.{gone}` is back. Every one of these named a voice, a speaker or a "
            "persona chosen in SOURCE rather than read from the engine account — which is "
            "the defect D-588 removed and the founder's requirement inverts: only what an "
            "operator enabled is selectable."
        )


def test_a_cartesia_entry_carries_the_tier_and_the_telugu_caveat() -> None:
    """What a Cartesia catalogue entry must carry however it was built: the dearer tier, the
    id spelling `speech_for_voice_id` can split back apart, and the vendor's own caveat."""
    voice = _cartesia_voice()

    assert isinstance(voice, Voice)
    assert voice.provider == "cartesia"
    assert voice.tts_model == CARTESIA_TTS_MODEL
    assert voice.id == voice_id_for("sonic-3.5", "test-record-not-a-real-voice-id")
    assert voice.speaker == "test-record-not-a-real-voice-id"
    assert "Telugu" in voice.note and "English" in voice.note, (
        "Cartesia vouches for Hinglish and Taglish and says speech outside those cases "
        "may sound accented; Telugu-English is not among them, so every Telugu entry "
        "carries that caveat rather than letting a screen imply the mixing"
    )


def test_the_shared_note_states_no_price() -> None:
    """A rate card in a dropdown string is a second definition of a number that reaches
    money (hard rule 7). Under D-547 a minute's price is the rate frozen on the credit lot
    it draws from, and there are two of them per lot — so no figure belongs here."""
    for voice in (*catalogue(), _cartesia_voice()):
        assert "₹" not in voice.note, f"{voice.id} quotes a price the rate card owns"
        assert "10k" not in voice.note


# --- C.8: the tier derivation --------------------------------------------------


def test_the_tier_is_the_provider_and_nothing_else() -> None:
    """Plan §2.3 invariant 7: there is no way to hold a Cartesia voice and a Sarvam tier,
    because the tier is not stored anywhere it could disagree with the voice."""
    for voice in catalogue():
        assert voice_tier(voice.id) == voice.provider
    assert voice_tier(_cartesia_voice().id) == "cartesia", (
        "⚠ THIS ASSERTION USED TO EXPECT `sarvam`, AND REVERSING IT IS THE POINT OF D-585. "
        "The tier used to be a CATALOGUE LOOKUP that answered 'sarvam' for any id it could "
        "not find. That was safe only while the catalogue was a frozen compiled constant; "
        "it is now cached from the engine, so 'absent' is a state a live Cartesia agent "
        "can be in — a cache not yet synced, a voice the vendor withdrew, a clone renamed "
        "— and every one of those would have billed a Cartesia minute at the Sarvam rate "
        "on an append-only ledger (hard rule 7). The tier now comes from the id's own "
        "model prefix, so a Cartesia id prices as Cartesia whether or not a row exists."
    )


def test_an_unknown_or_missing_voice_is_the_cheaper_tier() -> None:
    """A decision, not a fallback: an agent with no voice speaks the engine's default
    Sarvam persona, and a row naming NO model we offer is a Sarvam row. Defaulting the
    other way would bill an unmigrated agent at the dearer rate for a call it never made
    there.

    ⚠ **`sonic-3.5` MOVED OUT OF THIS LIST ON 11 SEP 2026 (D-585) AND THAT IS A FIX, NOT A
    REGRESSION.** A bare model string is the pre-split legacy spelling, and the legacy
    spelling of a CARTESIA row names the Cartesia model — so pricing it as Sarvam was the
    exact under-billing this change exists to remove. `bulbul:v3` stays here and still
    answers `sarvam`, for the same reason and in the same direction: it names the Sarvam
    model."""
    for unknown in (None, "", "bulbul:v3", "whatever-this-is", "Anushka", "bulbul"):
        assert voice_tier(unknown) == "sarvam"
    assert voice_tier("sonic-3.5") == "cartesia", (
        "a legacy row naming the Cartesia model is a Cartesia row; billing it at the "
        "Sarvam rate is unmetered spend on the dearer tier (hard rule 7)"
    )


# --- C.2: offerability ----------------------------------------------------------


def test_a_sarvam_voice_is_offerable_with_no_cartesia_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Cartesia grounds must not reach the tier that has none of them: its key is the
    engine account's own, its cost is on the rate card, and no cap applies."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    for voice in catalogue():
        assert (
            unofferable_reason(voice, curation=_curation(voice), cartesia_live_agents=10_000)
            is None
        )


def test_a_cartesia_voice_with_no_key_names_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    install_tts_price_reader(lambda _provider: True)

    reason = unofferable_reason(
        _cartesia_voice(), curation=_curation(_cartesia_voice()), cartesia_live_agents=0
    )

    assert reason == NO_CARTESIA_CREDENTIAL_REASON
    assert "cartesia_api_key" in reason, "the reader is told which field to fill"


def test_a_cartesia_voice_with_no_attested_price_names_the_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 7 at the SELECTION rather than at the meter: an unpriced minute is
    unmetered spend, and the only place refusing it is free is before the call."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: True)

    reason = unofferable_reason(
        _cartesia_voice(), curation=_curation(_cartesia_voice()), cartesia_live_agents=0
    )

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
    voice = _cartesia_voice()

    assert (
        unofferable_reason(voice, curation=_curation(voice), cartesia_live_agents=cap - 1) is None
    )
    reason = unofferable_reason(voice, curation=_curation(voice), cartesia_live_agents=cap)
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
    entries = (*catalogue(), _cartesia_voice())

    offered = offerable_voices(cartesia_live_agents=0, curation=_curation(*entries), voices=entries)

    assert len(offered) == len(entries), "the list never shrinks"
    assert [row.voice for row in offered] == list(entries)
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

    for voice in catalogue():
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
    voice = _cartesia_voice()
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

        operator = unofferable_reason(
            voice, curation=_curation(voice), cartesia_live_agents=live, audience="operator"
        )
        client = unofferable_reason(
            voice, curation=_curation(voice), cartesia_live_agents=live, audience="client"
        )

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
    entries = (*catalogue(), _cartesia_voice())
    for audience in ("operator", "client"):
        rows = offerable_voices(
            cartesia_live_agents=0, curation=_curation(*entries), voices=entries, audience=audience
        )
        assert [row.offerable for row in rows] == [
            row.offerable
            for row in offerable_voices(
                cartesia_live_agents=0, curation=_curation(*entries), voices=entries
            )
        ]
        assert all(row.offerable is (row.reason is None) for row in rows)


def test_the_default_audience_is_the_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every existing caller — the write backstop, the ops console, these tests — asked
    without an audience and must keep getting the actionable ground. The client realm opts
    in, at the route."""
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: False)
    voice = _cartesia_voice()
    assert (
        unofferable_reason(voice, curation=_curation(voice), cartesia_live_agents=0)
        == NO_CARTESIA_CREDENTIAL_REASON
    )
    assert (
        unofferable_reason(
            voice, curation=_curation(voice), cartesia_live_agents=0, audience="operator"
        )
        == NO_CARTESIA_CREDENTIAL_REASON
    )


def test_an_offerable_voice_carries_no_sentence_for_either_reader() -> None:
    """A refusal a client cannot act on is bad; a refusal on a voice they CAN choose would
    be worse. Sarvam fails no ground, so both audiences get `None`."""
    for voice in catalogue():
        for audience in ("operator", "client"):
            assert (
                unofferable_reason(
                    voice, curation=_curation(voice), cartesia_live_agents=0, audience=audience
                )
                is None
            )


# --- GROUND ZERO: curation (D-588) ----------------------------------------------
#
# The fourth ground, and the only one that applies to BOTH providers. These clauses are the
# founder's requirement made executable — *only the voices they enable are selectable* — and
# the composition rule that stops it from masking the three priced grounds or being masked
# by them.


def test_a_sarvam_voice_nobody_enabled_is_not_offered() -> None:
    """THE REQUIREMENT ITSELF. A Sarvam voice clears every priced ground — its key is the
    engine account's own, its cost is on the rate card, no cap applies — so if curation sat
    below the `provider == "sarvam"` short-circuit it would exempt the entire default tier
    from the one rule the founder actually asked for."""
    for state in ("disabled", "archived"):
        for voice in catalogue():
            assert (
                unofferable_reason(voice, cartesia_live_agents=0, curation=_curation(state=state))
                is not None
            ), f"a {state} voice was offered"


def test_the_three_curation_refusals_send_an_operator_to_three_places() -> None:
    """`disabled` and `archived` are the same verdict and different sentences, because one
    is undone from the working list and the other from the archived one. A voice the vendor
    has WITHDRAWN is a third: nothing on our console restores it, and telling an operator to
    enable it would send them round a loop that cannot end."""
    voice = next(iter(catalogue()))

    disabled = unofferable_reason(voice, cartesia_live_agents=0, curation={voice.id: "disabled"})
    archived = unofferable_reason(voice, cartesia_live_agents=0, curation={voice.id: "archived"})
    withdrawn = unofferable_reason(voice, cartesia_live_agents=0, curation={})

    assert len({disabled, archived, withdrawn}) == 3
    assert disabled == DISABLED_REASON and archived == ARCHIVED_REASON
    assert withdrawn == NOT_CURATED_REASON
    assert all(reason and not reason[0].isupper() for reason in (disabled, archived, withdrawn)), (
        "each completes a sentence the picker starts, so none begins with a capital"
    )


def test_a_voice_the_platform_no_longer_lists_fails_closed() -> None:
    """A catalogue snapshot can be newer than the curation rows, or a live agent can be on a
    voice the vendor removed. Either way the honest answer is "not offerable": the live 400
    proving it — *"Provided voice: Anushka is not available for the provider: sarvam"* — is
    what happens when we offer a voice the platform does not have."""
    voice = next(iter(catalogue()))
    assert unofferable_reason(voice, cartesia_live_agents=0, curation={}) == NOT_CURATED_REASON


def test_curation_and_the_priced_grounds_compose_without_masking_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FOUR GROUNDS, ONE DECIDING SENTENCE, AND THE RIGHT ONE EVERY TIME.

    An enabled Cartesia voice with no attested price must read as a PRICE problem, not as a
    curation one — otherwise the operator who just enabled it is told to enable it again. A
    disabled one must read as curation whatever the price says, because attesting a price
    for a voice nobody offers fixes nothing.
    """
    monkeypatch.setattr(voice_offer, "cartesia_credential_installed", lambda: True)
    voice = _cartesia_voice()

    assert (
        unofferable_reason(voice, cartesia_live_agents=0, curation={voice.id: "enabled"})
        == NO_ATTESTED_TTS_PRICE_REASON
    )
    assert (
        unofferable_reason(voice, cartesia_live_agents=0, curation={voice.id: "disabled"})
        == DISABLED_REASON
    )

    # ...and with the price attested, curation is still the thing standing in the way.
    install_tts_price_reader(lambda _provider: True)
    assert (
        unofferable_reason(voice, cartesia_live_agents=0, curation={voice.id: "disabled"})
        == DISABLED_REASON
    )
    assert unofferable_reason(voice, cartesia_live_agents=0, curation={voice.id: "enabled"}) is None


def test_a_client_is_never_told_their_plan_lacks_a_voice_an_operator_switched_off() -> None:
    """THE CLIENT SENTENCE FORKS ON WHICH GROUND DECIDED, and this is why.

    The priced grounds collapse to one client sentence naming the TIER — "the Studio voice
    is not available on your account yet". Said about a single persona an operator disabled,
    that is simply false: it tells a client their plan lacks a quality they may already be
    paying for, and sends them to an account manager over a console toggle.
    """
    voice = next(iter(catalogue()))
    client = unofferable_reason(
        voice, cartesia_live_agents=0, curation={voice.id: "disabled"}, audience="client"
    )

    assert client == voice_offer.CLIENT_NOT_OFFERED_REASON
    assert client != client_unofferable_reason(voice)
    for leak in ("cartesia", "sarvam", "bulbul", "sonic", "ops console", "admin console"):
        assert leak not in client.lower(), (
            f"the client-facing curation refusal names {leak!r} — a vendor, a model or one "
            "of our own surfaces, none of which a client may read (founder, 7 Sep 2026)"
        )


def test_the_verdict_is_the_same_fact_for_both_audiences() -> None:
    """Only the SENTENCE forks. If `None`-ness forked, `OfferedVoice.offerable` could read
    True for a client on a voice the write refuses."""
    voice = next(iter(catalogue()))
    for curation in ({voice.id: "enabled"}, {voice.id: "disabled"}, {}):
        operator = unofferable_reason(
            voice, cartesia_live_agents=0, curation=curation, audience="operator"
        )
        client = unofferable_reason(
            voice, cartesia_live_agents=0, curation=curation, audience="client"
        )
        assert (operator is None) == (client is None)


def test_curation_cannot_re_tier_an_agent_or_re_price_a_minute() -> None:
    """HARD RULE 7, AGAINST THE ONE THING D-588 ADDED THAT COULD HAVE BROKEN IT.

    `voice_tier()` derives an agent's billing tier from the stored id's own MODEL PREFIX
    through `TTS_MODEL_LIFECYCLE` — deliberately not from catalogue membership, because
    "absent from the catalogue" became a reachable state the day the catalogue was cached
    from a vendor (D-585), and a Cartesia agent in that state would have billed at the
    Sarvam rate on an append-only ledger.

    Curation adds three more ways for a voice to be absent from what a picker OFFERS — an
    operator disabled it, archived it, or the platform withdrew it — and the tier must be
    blind to all three. It is a pure function of the string, so this holds it to that: the
    same id prices the same way whatever any table says about it, including when no table
    says anything at all.
    """
    for voice in (*catalogue(), _cartesia_voice()):
        expected = voice.provider
        # The tier takes no curation argument at all, which is the structural half of the
        # guarantee: there is no parameter through which a console click could reach it.
        assert voice_tier(voice.id) == expected
        # And it holds with NOTHING installed — the state of a process that has never
        # synced, where a membership-based derivation would answer `sarvam` for every id.
        installed = catalogue()
        try:
            voices_module.install_voice_catalogue(None)
            assert voice_tier(voice.id) == expected, (
                "the tier moved when the catalogue emptied — it is reading membership "
                "again, and a Cartesia minute would bill at the Sarvam rate"
            )
        finally:
            voices_module.install_voice_catalogue(installed or None)
