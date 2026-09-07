"""The `meta.lots` shape a `usage` row carries (ADDENDUM 2 §2.1, invariant §2.3.5).

The month's statement and the margin panel are re-derived from these rows alone (D-492 /
D-458), so the shape is a contract and not a debug aid. Its one rule: **an inapplicable key
is ABSENT, never null.** A key whose null means "not applicable" is a tri-state that every
reader has to interpret, and the first reader to interpret it as zero adds unspecified
values into a month's talk minutes.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

from apps.api.billing import lots


def test_a_call_split_carries_all_six_keys() -> None:
    split = lots.CallSplit(
        lot_id=uuid4(),
        credits=Decimal("47.0000"),
        minutes=Decimal("10.0000"),
        inr_per_min=Decimal("4.7000"),
        voice_tier="cartesia",
    )

    [row] = lots.split_meta([split])

    assert row == {
        "kind": "call",
        "credits": "47.0000",
        "lot_id": str(split.lot_id),
        "minutes": "10.0000",
        "inr_per_min": "4.7000",
        "voice_tier": "cartesia",
    }


def test_an_ai_assist_split_omits_minutes_rate_and_voice_entirely() -> None:
    """Not `"minutes": null` — absent. The dashboard-AI debit buys rupees of assistance;
    there is no rate and no voice to record."""
    split = lots.AiAssistSplit(lot_id=uuid4(), credits=Decimal("30.0000"))

    [row] = lots.split_meta([split])

    assert row == {"kind": "ai_assist", "credits": "30.0000", "lot_id": str(split.lot_id)}
    assert "minutes" not in row
    assert "inr_per_min" not in row
    assert "voice_tier" not in row


def test_the_overdraft_portion_names_no_lot() -> None:
    """Same rule, one level down: the overdrawn minutes came from no lot, so `lot_id` is
    absent rather than null — and they still carry their price, because the whole point of
    plan §0 Q5 is that overdraft has one."""
    rows = lots.split_meta(
        [
            lots.CallSplit(
                lot_id=None,
                credits=Decimal("23.5000"),
                minutes=Decimal("5.0000"),
                inr_per_min=Decimal("4.7000"),
                voice_tier="sarvam",
            ),
            lots.AiAssistSplit(lot_id=None, credits=Decimal("30.0000")),
        ]
    )

    assert "lot_id" not in rows[0]
    assert rows[0]["inr_per_min"] == "4.7000"
    assert "lot_id" not in rows[1]


def test_every_value_crosses_jsonb_as_digits_and_never_as_a_float() -> None:
    """Hard rule 7 at the boundary: a JSON number would be a binary double by the time a
    statement renders it, and `2500.10` is not `2500.10` after that trip."""
    rows = lots.split_meta(
        [
            lots.CallSplit(
                lot_id=uuid4(),
                credits=Decimal("2500.1000"),
                minutes=Decimal("500.0200"),
                inr_per_min=Decimal("5.0000"),
                voice_tier="sarvam",
            )
        ]
    )

    round_tripped = json.loads(json.dumps({"lots": rows}))["lots"][0]
    assert all(isinstance(value, str) for value in round_tripped.values())
    assert Decimal(round_tripped["credits"]) == Decimal("2500.1000")


def test_the_splits_sum_to_the_ledger_delta_whatever_kind_they_are() -> None:
    """Invariant §2.3.5: a reader totalling MONEY sums `credits` across every split; only
    a reader totalling TALK MINUTES filters `kind == "call"`."""
    splits: list[lots.LotSplit] = [
        lots.CallSplit(
            lot_id=uuid4(),
            credits=Decimal("100.0000"),
            minutes=Decimal("20.0000"),
            inr_per_min=Decimal("5.0000"),
            voice_tier="sarvam",
        ),
        lots.AiAssistSplit(lot_id=uuid4(), credits=Decimal("30.0000")),
    ]

    assert lots.credits_of(splits) == Decimal("130.0000")
    assert sum(
        (split.minutes for split in splits if isinstance(split, lots.CallSplit)), Decimal("0")
    ) == Decimal("20.0000")
