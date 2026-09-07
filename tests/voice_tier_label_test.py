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
