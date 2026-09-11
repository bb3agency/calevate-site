"""What a client is told a voice tier is CALLED, and why it is not the vendor's name.

The wire, the ledger, the lot rows and every column keep the vendor spelling, because
that is what they mean and an auditor reconciles them against a vendor invoice. This file
guards the other half of the founder's 7 Sep 2026 decision: no surface a CLIENT reads
names a vendor as a product tier, so the vendor can change without a client-visible
rename.

Two names are excluded on purpose and the exclusion is asserted rather than left to a
comment: `standard` and `premium` are what the comparable product calls its rungs (TRD
§10's reading of their code), so copying them reads as copying the product; `basic` is a
quality claim about the Sarvam voice that nothing in this repo measures.

Run: uv run pytest tests/voice_tier_label_test.py -q
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.billing.rates import (
    VOICE_TIER_LABELS,
    VOICE_TIERS,
    voice_tier_label,
)


def test_every_tier_has_a_label_and_no_tier_has_two() -> None:
    """Total over the Literal, which is what lets callers drop the fallback branch."""
    assert set(VOICE_TIER_LABELS) == set(VOICE_TIERS)
    assert len(set(VOICE_TIER_LABELS.values())) == len(VOICE_TIERS), (
        "two tiers sharing one label would render as one choice in the picker"
    )


def test_no_label_names_a_vendor() -> None:
    """The decision itself. A client buys a voice quality, not a vendor's product."""
    for tier, label in VOICE_TIER_LABELS.items():
        lowered = label.lower()
        for vendor in VOICE_TIERS:
            assert vendor not in lowered, (
                f"the {tier} tier is shown to clients as {label!r}, which names the "
                f"vendor {vendor!r}. The wire keeps the vendor spelling; what a human "
                f"reads must not."
            )


def test_no_label_is_one_the_comparable_product_uses_or_a_quality_claim() -> None:
    """Copying a competitor's rung names reads as copying the product; `basic` would be
    a claim about the Sarvam voice this repo has never measured."""
    for label in VOICE_TIER_LABELS.values():
        assert label.lower() not in {"standard", "premium", "basic"}


def test_the_label_is_reached_by_a_function_so_there_is_one_definition() -> None:
    """Callers go through `voice_tier_label`, never the mapping, so the day a label is
    computed rather than looked up there is one place to change."""
    for tier in VOICE_TIERS:
        assert voice_tier_label(tier) == VOICE_TIER_LABELS[tier]
        assert voice_tier_label(tier).strip() == voice_tier_label(tier)
        assert voice_tier_label(tier), "a blank label renders as a nameless tier"


@dataclass(frozen=True, slots=True)
class _Note:
    """A note and the id to name in a failure — so a per-provider sentence can be checked by
    the same loop that checks a catalogue entry, without inventing a whole `Voice`."""

    note: str
    id: str


def test_no_catalogue_note_names_a_vendor_as_the_tier() -> None:
    """THE GUARD THIS FILE WAS MISSING, and the string it would have caught.

    `Voice.note` is written for an operator's dropdown and reaches a CLIENT — it rides
    `OfferedVoiceOut.note` on `GET /v1/agents/voices`, which any realm may read
    (`tests/agent_voice_test.py` proves the client read). Both shared notes said "the
    <vendor> voice tier" in as many words, which is exactly the sentence
    `test_no_label_names_a_vendor` forbids one level up: the labels were clean and the
    prose beside them was not. So the rule is asserted over the prose too, and it is asserted
    over `catalogue_note` PER PROVIDER rather than over catalogue entries: since D-588 the
    entries come from whatever the engine account happens to list, so a deployment with no
    Cartesia provider would silently stop checking the Cartesia sentence.
    """
    from apps.api.agents.voices import catalogue, catalogue_note

    for note in (*(voice.note for voice in catalogue()), catalogue_note("cartesia")):
        lowered = note.lower()
        for vendor in VOICE_TIERS:
            assert f"{vendor} voice tier" not in lowered, (
                f"a catalogue note calls the tier {vendor!r}. A client reads this string."
            )
    for provider in ("sarvam", "cartesia"):
        assert voice_tier_label(provider) in catalogue_note(provider), (
            "the note names the tier, and it must name it the way the client is told it — "
            "composed from `voice_tier_label`, never typed in a second time"
        )


def test_no_catalogue_note_tells_a_client_to_fix_our_configuration() -> None:
    """The other half of the same leak. The Cartesia note used to end "offered only once the
    Cartesia key is installed, its price attested and the platform-wide Cartesia agent cap
    not reached" — two of our own settings, in a client-readable string, and a second
    un-forked copy of an answer `agents/voice_offer.unofferable_reason` gives per audience
    and per deployment.

    Over `catalogue_note` per provider rather than over entries, for the reason the clause
    above gives: since D-588 the entries are whatever the engine listed."""
    from apps.api.agents.voices import catalogue, catalogue_note

    for voice in (*catalogue(), *(_Note(catalogue_note(p), p) for p in ("sarvam", "cartesia"))):
        lowered = voice.note.lower()
        for ours in ("cartesia_api_key", "cartesia_agent_cap", "ops console", "attest"):
            assert ours not in lowered, (
                f"{voice.id}'s note names {ours!r} — a client cannot act on it, and the "
                "refusal that can is served per voice by `voice_offer.unofferable_reason`"
            )
