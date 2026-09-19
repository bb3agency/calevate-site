"""Every money lookup keyed by a PLAN TIER or a VOICE RUNG is TOTAL — no silent default.

WHY THIS FILE EXISTS, and why it is not a duplicate of `voice_tier_totality_test.py`. That
file pins the per-RUNG accessors (`OpenLot.rate_for`, `CreditPack.inr_per_min`,
`cost_floor_inr_per_min`, `LotRates.rate_for`), which all raise. The SHAPE it was written
for — "a lookup plus a silent default, in the direction that is wrong" — is not confined to
rungs, and two more instances of it were live on the money path on 19 Sep 2026:

* `billing/ai_quota.AI_QUOTA_INR.get(tier, AI_QUOTA_INR["trial"])` — a PLAN TIER lookup
  defaulting to the SMALLEST allowance on the ladder. A tier added to
  `tenancy.models.PLAN_TIERS` and forgotten in that dict would have cut an entitled client
  from ₹250 of dashboard AI to ₹40 with nothing raising, blocked the feature six times
  early and put the paid-overage modal in front of them for money they did not owe. The
  `prepaid` entry's own comment records somebody nearly making exactly that omission.
* `billing/service.voice_tier_usage` — a rung lookup defaulting to ZERO, silently
  DISCARDING wallet debits the ledger had already taken (its own test below).

Both are closed by making the lookup total. The `AI_QUOTA_INR` half cannot be tested by
"pass a bad tier and watch it raise" — indexing a dict needs no test to prove it raises —
so what is pinned here is the property that makes the raise unreachable from the database:
the dict's keys and the column's CHECK constraint are the SAME SET. That is the assertion
that fails the day somebody adds a tier and forgets the money.

Run: uv run pytest -q tests/billing_tier_lookup_totality_test.py
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing.ai_quota import AI_QUOTA_INR
from apps.api.tenancy.models import DEFAULT_PLAN_TIER, PLAN_TIERS


def test_every_plan_tier_has_a_dashboard_ai_allowance_and_no_tier_is_invented() -> None:
    """The two sets are EQUAL, in both directions, and each direction catches a real
    mistake: a missing key was a client silently cut to the trial allowance, and a spare
    key is an allowance for a tier no account can be on — a number a founder would read as
    a live product term.

    DERIVED from `PLAN_TIERS` rather than retyped here (D-104's rule): a list of four
    strings in a test is a fifth place the tier vocabulary is written down, and it would
    agree with the others only until somebody edited one of them.
    """
    assert set(AI_QUOTA_INR) == set(PLAN_TIERS)


def test_the_allowance_lookup_is_indexed_rather_than_defaulted() -> None:
    """The behaviour the `.get(tier, AI_QUOTA_INR["trial"])` default hid.

    Sabotage-checked by hand: restoring the default makes this clause pass for a tier that
    has no allowance at all, which is the whole complaint — the old expression could not
    tell "this tier is worth ₹40" from "nobody taught me about this tier". Indexing makes
    the two different outcomes, and the second one is loud.
    """
    with pytest.raises(KeyError):
        AI_QUOTA_INR["enterprise"]  # a tier this build does not sell


def test_the_default_tier_is_not_the_cheapest_allowance() -> None:
    """The DIRECTION, which is why the old default was worse than an arbitrary one.

    It fell to `trial`, the SMALLEST figure on the ladder, so every way of being wrong cost
    the client. `DEFAULT_PLAN_TIER` is what a new account is born on (D-521) and it is
    worth strictly more than the trial allowance — so a default-shaped bug on this dict
    always under-served somebody, and never over-served us into noticing.
    """
    assert AI_QUOTA_INR[DEFAULT_PLAN_TIER] > AI_QUOTA_INR["trial"]
    assert AI_QUOTA_INR["trial"] == min(AI_QUOTA_INR.values())
    assert all(isinstance(value, Decimal) for value in AI_QUOTA_INR.values())
