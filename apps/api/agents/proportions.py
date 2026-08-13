"""Interval estimation for the two conversion rates an A/B script test produces.

WHY THIS FILE EXISTS AT ALL, AND WHY IT IS NOT A p-VALUE
--------------------------------------------------------
The number this module feeds is sales-facing: "variant B books more appointments".
A wrong statistical claim on that sentence is worse than no number, because it will be
repeated to a client and then acted on. So the surface must be able to say three
different things — *we cannot compare yet*, *B is ahead but we cannot tell you it is
better*, and *B is better* — and the arithmetic here is what separates them.

WHAT WE USE, AND THE EVIDENCE FOR IT (searched 2026-08, not recalled)
---------------------------------------------------------------------
* **Per variant: the Wilson score interval** (Wilson 1927). Brown, Cai & DasGupta,
  "Interval Estimation for a Binomial Proportion", *Statistical Science* 16(2):101-133
  (2001) — https://projecteuclid.org/journals/statistical-science/volume-16/issue-2/
  Interval-Estimation-for-a-Binomial-Proportion/10.1214/ss/1009213286.full — measured
  the textbook Wald interval's actual coverage "oscillating wildly", dipping well under
  90% at a nominal 95% for n below ~30 or p near 0 or 1, and recommend Wilson (or
  equal-tailed Jeffreys) for n ≤ 40. Our n IS small and our p IS near 0 — a conversion
  rate of 4 in 60 is exactly the corner where Wald invents a symmetric interval that can
  run below zero. So: Wilson, not Wald, and not a bare point estimate.

* **For the difference: Newcombe's hybrid score interval** (Newcombe, "Interval
  estimation for the difference between independent proportions: comparison of eleven
  methods", *Statistics in Medicine* 17:873-890, 1998 — his method 10), which is built
  by square-and-adding the two Wilson intervals rather than by a normal approximation to
  the difference. Fagerland, Lydersen & Laake, "Recommended confidence intervals for two
  independent binomial proportions", *Statistical Methods in Medical Research* (2011) —
  https://www.ms.uky.edu/~mai/sta635/FagerlandLydersenLaake2011---
  RecommendedCIsForTwoIndependent....pdf — recommend it as a default and report that
  **40 or more observations per group gives acceptable coverage**. That number is where
  `MIN_CALLS_PER_VARIANT` comes from; it is not a taste.

* **REJECTED: a chi-square / two-proportion z test.** It answers a narrower question
  (is the difference distinguishable from zero) with a scarier object (a p-value), it
  needs its own small-n caveat (expected cell counts ≥ 5), and it gives an operator no
  sense of HOW BIG the difference might be — which is the only thing that decides
  whether to promote a script. An interval that contains zero says "inconclusive" and
  says how inconclusive, in the units the operator already thinks in.

* **REJECTED: Fisher's exact test.** Correct, but conservative, and still a p-value.

WHAT THIS CANNOT DO, STATED SO NOBODY INFERS IT
------------------------------------------------
The 95% is **per look**. An operator who refreshes the results screen daily and stops
the moment the interval clears zero is doing repeated significance testing, and their
real error rate is higher than 5%. Fixing that needs a sequential design (alpha
spending, or a Bayesian stopping rule) with a pre-declared sample size, which is a much
larger commitment than this milestone; `experiments.py` therefore ships the caveat as
part of the RESULT rather than pretending it away, and the UI prints it.

FLOATS ARE CORRECT HERE. Hard rule 7 is about MONEY. A conversion rate is not money, is
never summed into a ledger and is never displayed as a currency; a `Decimal` here would
buy exact arithmetic on a quantity whose input is already a ratio of two counts and
whose output is rounded to a percentage point on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

# Two-sided 95%. Hardcoded rather than parameterised: a confidence level a caller can
# choose is a confidence level somebody tunes until the answer is the one they wanted.
Z_95 = 1.959963984540054

# Fagerland/Lydersen/Laake 2011: the Newcombe hybrid-score interval attains acceptable
# coverage from ~40 observations per group. BELOW THIS WE REPORT NO COMPARISON AT ALL —
# not a wide one, not a hedged one. A rate over eleven calls is not a result, and the
# most expensive thing this feature could do is render one as though it were.
MIN_CALLS_PER_VARIANT = 40


@dataclass(frozen=True, slots=True)
class Interval:
    """A closed interval on a proportion, plus the point estimate it surrounds."""

    point: float
    low: float
    high: float


def wilson_interval(successes: int, trials: int, *, z: float = Z_95) -> Interval:
    """The Wilson score interval for one proportion.

    Defined at `successes == 0` and `successes == trials`, where Wald collapses to a
    zero-width interval and claims certainty from the one sample that has none — the
    property that makes it the wrong tool for a conversion rate of 0/45.
    """
    if trials <= 0:
        raise ValueError("wilson_interval needs at least one trial")
    if not 0 <= successes <= trials:
        raise ValueError("successes must lie in [0, trials]")

    p = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    half = (z / denominator) * sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    # Clamped because the interval is a statement about a proportion; the formula
    # cannot leave [0,1] by more than floating-point dust, and dust on a screen reads
    # as a bug in the arithmetic.
    return Interval(point=p, low=max(0.0, centre - half), high=min(1.0, centre + half))


@dataclass(frozen=True, slots=True)
class Difference:
    """The difference `a - b` in conversion rate, as an interval.

    `excludes_zero` is the whole verdict: an interval that contains zero is consistent
    with the two scripts performing identically, however far apart their point estimates
    happen to be on today's counts.
    """

    point: float
    low: float
    high: float

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0.0 or self.high < 0.0


def newcombe_difference(
    successes_a: int,
    trials_a: int,
    successes_b: int,
    trials_b: int,
    *,
    z: float = Z_95,
) -> Difference:
    """Newcombe (1998) method 10 — the hybrid score interval for `p_a - p_b`.

    The construction, so the next reader does not have to take it on faith: take the
    Wilson interval (l, u) for each proportion, and combine the DISTANCES from each
    point estimate to the relevant bound in quadrature. It inherits Wilson's good
    behaviour at the extremes instead of assuming the difference is normal — which is
    the assumption that fails on exactly our data, where one arm can legitimately be 0
    conversions in 40 calls.
    """
    if trials_a <= 0 or trials_b <= 0:
        raise ValueError("newcombe_difference needs at least one trial in each arm")

    a = wilson_interval(successes_a, trials_a, z=z)
    b = wilson_interval(successes_b, trials_b, z=z)
    point = a.point - b.point
    return Difference(
        point=point,
        low=point - sqrt((a.point - a.low) ** 2 + (b.high - b.point) ** 2),
        high=point + sqrt((a.high - a.point) ** 2 + (b.point - b.low) ** 2),
    )


__all__ = [
    "MIN_CALLS_PER_VARIANT",
    "Z_95",
    "Difference",
    "Interval",
    "newcombe_difference",
    "wilson_interval",
]
