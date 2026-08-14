"""The statistics an A/B script test reports, and the claims it refuses to make.

These are pure-function tests over hand-written counts, deliberately: `judge` is the one
function in this slice whose wrongness gets REPEATED TO A CLIENT ("variant B books more
appointments"), so it is tested against arithmetic a reviewer can check by hand rather
than against rows a fixture happened to produce.

The position under test, and the evidence for it, is argued in
`apps/api/agents/proportions.py`. In one line: Wilson per arm (Brown, Cai & DasGupta
2001 measure Wald's coverage collapsing at small n and p near 0 — which is exactly our
data), Newcombe's hybrid score for the difference (Fagerland, Lydersen & Laake 2011
recommend it and report acceptable coverage from ~40 per group, which is where
`MIN_CALLS_PER_VARIANT` comes from), and NO comparison at all below that.

Run: uv run pytest -q tests/experiment_stats_test.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from apps.api.agents.assignment import BUCKETS, VariantArm, bucket_of, pick_arm
from apps.api.agents.experiments import VariantResult, judge
from apps.api.agents.proportions import (
    MIN_CALLS_PER_VARIANT,
    newcombe_difference,
    wilson_interval,
)


def _arm(label: str, attributed: int, conversions: int) -> VariantResult:
    interval = wilson_interval(conversions, attributed) if attributed else None
    return VariantResult(
        variant_id=UUID(int=ord(label)),
        label=label,
        prompt_version=1 if label == "A" else 2,
        weight_bp=5000,
        published=True,
        # `judge` reads `attributed` and `conversions` only; the direction split exists
        # for the reader, not the arithmetic, so these arms are all-outbound.
        outbound_dialled=attributed,
        attributed=attributed,
        inbound_attributed=0,
        conversions=conversions,
        rate=interval.point if interval else None,
        rate_low=interval.low if interval else None,
        rate_high=interval.high if interval else None,
    )


# --- the intervals themselves -------------------------------------------------


def test_wilson_is_defined_where_wald_claims_certainty() -> None:
    """0 conversions in 45 calls is a REAL result an arm can produce, and the textbook
    Wald interval answers it with [0, 0] — a claim of certainty from the one sample that
    has none. Wilson gives a one-sided interval that still admits a plausible rate."""
    interval = wilson_interval(0, 45)
    assert interval.point == 0.0
    assert interval.low == 0.0
    assert 0.0 < interval.high < 0.12, interval

    perfect = wilson_interval(45, 45)
    assert perfect.low < 1.0 and perfect.high == 1.0


def test_wilson_matches_the_published_worked_example() -> None:
    """15/50 at 95% is the standard worked example: (0.191, 0.438), and note that it is
    NOT symmetric about 0.30 — that asymmetry is the whole difference from Wald and the
    reason the interval stays inside [0,1] near the extremes. Pinned to three decimals so
    a refactor of the formula cannot quietly change the arithmetic."""
    interval = wilson_interval(15, 50)
    assert interval.point == 0.30
    assert round(interval.low, 3) == 0.191
    assert round(interval.high, 3) == 0.438
    assert (interval.point - interval.low) < (interval.high - interval.point)


def test_wilson_refuses_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        wilson_interval(0, 0)
    with pytest.raises(ValueError):
        wilson_interval(5, 3)


def test_newcombe_interval_brackets_the_observed_difference() -> None:
    """The point estimate must lie inside the interval, and a big true gap on decent
    counts must clear zero while a small one on the same counts must not."""
    wide = newcombe_difference(40, 100, 10, 100)
    assert wide.low < wide.point < wide.high
    assert wide.point == pytest.approx(0.30)
    assert wide.excludes_zero

    narrow = newcombe_difference(31, 100, 28, 100)
    assert not narrow.excludes_zero, narrow


# --- the verdict --------------------------------------------------------------


def test_below_the_minimum_there_is_no_comparison_at_all() -> None:
    """The headline claim of this slice. 5/11 vs 1/11 is a 36-point gap, and it is
    NOTHING — the surface must say so, and must publish no interval."""
    basis, verdict, leader, winner, headline = judge([_arm("A", 11, 5), _arm("B", 11, 1)])
    assert basis == "insufficient_data"
    assert verdict == "not_enough_data"
    assert winner is None
    # The ordering is still true and is still reported. What is withheld is the CLAIM.
    assert leader == "A"
    assert "Not enough calls" in headline
    assert str(MIN_CALLS_PER_VARIANT) in headline


def test_the_minimum_is_per_arm_not_in_total() -> None:
    """A ramped experiment reaches 200 calls on the control long before the challenger
    has 40. Summing them would report a comparison the small arm cannot support."""
    basis, verdict, _, winner, _ = judge(
        [_arm("A", 400, 120), _arm("B", MIN_CALLS_PER_VARIANT - 1, 2)]
    )
    assert (basis, verdict, winner) == ("insufficient_data", "not_enough_data", None)


def test_a_three_point_gap_on_forty_calls_is_inconclusive_not_a_winner() -> None:
    """The exact case the brief names. 8/40 vs 7/40 is 'B is ahead' and is not
    'B is better' — the interval still contains zero."""
    basis, verdict, leader, winner, headline = judge([_arm("A", 40, 8), _arm("B", 40, 7)])
    assert basis == "measured"
    assert verdict == "inconclusive"
    assert leader == "A"
    assert winner is None
    assert "includes zero" in headline


def test_a_real_difference_on_real_counts_is_declared() -> None:
    """The gate must not be so tight that nothing ever passes it: a genuine 25-point
    gap on 200 calls an arm IS a result, and refusing to say so would be its own
    dishonesty."""
    basis, verdict, leader, winner, headline = judge([_arm("A", 200, 20), _arm("B", 200, 70)])
    assert (basis, verdict, leader, winner) == ("measured", "winner", "B", "B")
    assert "Variant B converts better" in headline


def test_an_arm_with_no_completed_calls_has_no_rate_and_no_verdict() -> None:
    """A rate over zero calls is not 0%. `rate is None` must survive all the way to the
    verdict rather than being coerced into a losing arm."""
    empty = _arm("B", 0, 0)
    assert empty.rate is None
    basis, verdict, leader, winner, _ = judge([_arm("A", 100, 30), empty])
    assert (basis, verdict, winner) == ("insufficient_data", "not_enough_data", None)
    assert leader == "A"


def test_a_dead_heat_names_no_leader() -> None:
    """Identical rates are not a lead. Naming one would put an arrow on a coin flip."""
    _, verdict, leader, winner, _ = judge([_arm("A", 60, 12), _arm("B", 60, 12)])
    assert verdict == "inconclusive"
    assert leader is None and winner is None


# --- the split ----------------------------------------------------------------


def test_the_bucket_is_stable_across_processes_and_salted_per_experiment() -> None:
    """`hash()` on a str is randomised by PYTHONHASHSEED, so a bucket built on it would
    differ between the worker that dialled and anything that tried to explain it. And
    two experiments must not reproduce each other's split."""
    one = UUID("11111111-1111-1111-1111-111111111111")
    two = UUID("22222222-2222-2222-2222-222222222222")
    assert bucket_of(one, "+919000000001") == bucket_of(one, "+919000000001")
    assert 0 <= bucket_of(one, "+919000000001") < BUCKETS
    differ = sum(
        bucket_of(one, f"+9190000{n:05d}") != bucket_of(two, f"+9190000{n:05d}") for n in range(200)
    )
    assert differ > 190, "the experiment id is not salting the hash"


def test_the_split_is_honoured_and_the_edges_land_where_the_weights_say() -> None:
    arms = [
        VariantArm(variant_id=UUID(int=1), label="A", weight_bp=8000, engine_agent_ref="a"),
        VariantArm(variant_id=UUID(int=2), label="B", weight_bp=2000, engine_agent_ref="b"),
    ]
    assert pick_arm(arms, 0).label == "A"
    assert pick_arm(arms, 7999).label == "A"
    assert pick_arm(arms, 8000).label == "B"
    assert pick_arm(arms, BUCKETS - 1).label == "B"

    # Over a realistic contact list the observed share tracks the configured one. Loose
    # bounds on purpose: this asserts the split is APPLIED, not that blake2b is uniform.
    in_a = sum(
        pick_arm(arms, bucket_of(UUID(int=7), f"+9190000{n:05d}")).label == "A" for n in range(2000)
    )
    assert 1500 < in_a < 1700, in_a


# --- the counts survive the trip to the wire ----------------------------------


def test_the_three_counts_reach_the_response_under_their_own_names() -> None:
    """Three counts that are all small integers about the same arm are three chances to
    publish one under another's name, and `_render` is a hand-written mapping with no
    other test over it. So: three DIFFERENT numbers, checked individually.

    This is the shape of the defect the split replaced — a count that meant one thing and
    was labelled another — and a transposition here would reproduce it exactly, with the
    server and the screen agreeing on the wrong number.
    """
    from apps.api.agents.experiment_routes import _render
    from apps.api.agents.experiments import ExperimentResults

    arm = VariantResult(
        variant_id=UUID(int=1),
        label="A",
        prompt_version=1,
        weight_bp=5000,
        published=True,
        outbound_dialled=71,
        attributed=53,
        inbound_attributed=17,
        conversions=11,
        rate=11 / 53,
        rate_low=0.11,
        rate_high=0.34,
    )
    rendered = _render(
        ExperimentResults(
            experiment_id=UUID(int=9),
            agent_id=UUID(int=8),
            name="Direct booking greeting",
            status="running",
            conversion_metric="call_outcome_resolved",
            conversion_metric_label="calls the agent resolved",
            started_at=datetime(2026, 8, 1, tzinfo=UTC),
            concluded_at=None,
            promoted_label=None,
            variants=[arm],
            minimum_calls_per_variant=MIN_CALLS_PER_VARIANT,
            basis="insufficient_data",
            verdict="not_enough_data",
            leader_label=None,
            winner_label=None,
            difference_point=None,
            difference_low=None,
            difference_high=None,
            headline="Not enough calls to compare yet.",
            caveat="The 95% confidence is per reading.",
            attributed_directions=("inbound", "outbound"),
            unattributed_inbound=4,
            coverage_note="Some inbound calls were answered by an arm's own line.",
        )
    )
    published = rendered.variants[0]
    assert published.outbound_dialled == 71, "calls we PLACED into the arm"
    assert published.attributed == 53, "completed calls — the denominator of the rate"
    assert published.inbound_attributed == 17, "of those, the ones nobody split into it"
    assert published.conversions == 11
