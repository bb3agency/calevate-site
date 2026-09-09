"""The TTS speaking rate, MEASURED from our own transcripts — pilot gate 12's number.

TRD §10.1 prices the TTS leg at ₹1.08-1.62 per call-minute from an assumption it names in
its own words: *"the agent speaks 40-60% of a call, at ~900 characters/minute of actual
speech → 360-540 TTS characters per call-minute. That ratio is itself unmeasured — it is
the single biggest lever on the TTS line."* Nothing measured it. With the Sarvam voice
fixed and self-hosting out, it is the largest cost lever still in play — ₹0.27-0.40/min
of a ₹3.70 floor — and this module is what turns it from a sentence into a number.

THE ENGINE CANNOT SUPPLY IT. `apps/workers/pipeline.py` records that the engine bills TTS
as a leg cost with no character count, and under BYOK it may not bill it at all
(`rates.ENGINE_REPORTS_TTS_MODEL` is the neighbouring blindness). The honest source is
OUR transcripts: characters in the AGENT's turns ÷ the call's duration = chars per
call-minute, directly, with no vendor figure anywhere in the arithmetic.

WHAT IS COUNTED. Every call that has a transcript AND `duration_s > 0`, one sample per
call, and the sample is `length(COALESCE(text_redacted, text))` summed over its `agent`
turns. `COALESCE` is deliberate and the comment on the query says why: an aggregate
`length()` never returns a character of text, so hard rule 5 is not at stake, but reading
the default-redacted column keeps this inside the rule's DEFAULT rather than needing an
exemption — and for the agent's own scripted turns the redaction mask is noise (a masked
number is about the same length as the number). A caller's turns are never counted:
they cost STT seconds, not TTS characters.

THREE FIGURES, BECAUSE ONE WOULD MISLEAD. The pooled rate (Σ chars x 60 / Σ seconds) is
what the fleet's TTS bill actually divides by its minutes, so it is the number the cost
floor is re-derived from. The p50 is what a typical CALL does, which a long chatty
outlier can pull the pooled figure away from. The p95 is the shape of the tail — the
call that pushes a month toward the ceiling TRD §10.3 accepted. Percentiles are
NEAREST-RANK (the value at position ⌈p·n⌉ of the sorted sample): no interpolation, so
every published figure is a rate some real call actually ran at, which is what makes it
a measurement rather than an estimate.

BELOW THE THRESHOLD IT REFUSES TO PUBLISH A FIGURE. `TTS_SPEAKING_RATE_MIN_CALLS` is
hard rule 11 applied to our own data: a chars-per-minute displayed as "measured" from
three calls would be exactly the laundering of a small number into a fact that rule
exists to stop. Under the threshold the result carries the sample size and the reason
and NO rate — the assumed band stays the fallback and the board says so.

TWO READERS, AND THE SECOND ONE IS WHY THE FIRST IS NOT ENOUGH (D-557). Everything above
is the BOARD: one sample per call, so a distribution can be built, which forces a walk of
the client book. Nothing in the cost model can afford that shape on a page, and for weeks
nothing in the cost model consumed this measurement at all — every floor still divided by
the assumed 540. The second half of this module (below `summarize`) is a platform COUNTER
the post-call meter moves: three running totals, one indexed row per month, the pooled rate
the cost model actually divides by, and `FleetSpeakingRate.basis()` is the ONE door from it
into `billing/rates.py`. Pooled and not p50/p95, and the reason is argued at that block.

TENANCY. `transcript_turns` and `calls` are FORCE-RLS'd and an untenanted read of either
returns ZERO rows and reports success (the maintenance lane hit exactly that). So there
is no fleet query here: `sample_tenant` reads ONE client inside that client's own
`tenant_session`, and `spend_routes.fleet_tts_speaking_rate` walks the live directory the way
`fleet_spend` does — one directory read, one scoped session per client, nothing that can
see two tenants at once, and no policy widened to make it faster. `summarize` is pure
arithmetic over the pooled per-call samples and never touches the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import (
    ROUNDING,
    TTS_ASSUMED_CHARS_PER_CALL_MINUTE,
    SpeakingRateBasis,
    assumed_speaking_rate,
    tts_inr_per_call_minute,
)

#: The smallest sample a figure may be PUBLISHED from. Twenty, and the reason is
#: arithmetic rather than taste: under nearest-rank, ⌈0.95 x n⌉ = n for every n < 20, so
#: below twenty calls the "p95" is literally the single longest-talking call in the
#: sample — a maximum wearing a percentile's name. Twenty is the first n at which it is
#: not. It is also two hundred-odd call-minutes at typical lengths, enough that one
#: outlier cannot move the pooled figure by a rupee. A figure from fewer calls is not
#: hidden — the sample size and this constant are always published — it is just not
#: called a measurement, which is hard rule 11.
TTS_SPEAKING_RATE_MIN_CALLS: Final[int] = 20

#: Chars-per-minute figures are quantized to four places, the same scale as every rupee
#: here (`billing/models.MONEY`), so a rate prints like the rupee it implies. The
#: arithmetic that produces them is exact; only the published spelling is rounded.
#:
#: ROUNDING IS PASSED EXPLICITLY WHEREVER THIS IS USED, and `money_rounding_mode_test`
#: is what caught its absence. A bare `quantize()` takes the process-global `decimal`
#: context — ROUND_HALF_EVEN by default and mutable by any library in the image — so the
#: figure this module publishes would have depended on what else happened to be imported.
#: This is not rupees, but it is the number the TTS cost leg is re-derived from, so it
#: uses the same `billing.rates.ROUNDING` as the money it feeds rather than a second
#: convention nobody could keep straight.
_RATE_Q: Final[Decimal] = Decimal("0.0001")
_SECONDS_PER_MINUTE: Final[Decimal] = Decimal(60)

#: One row per call with a transcript, under the CALLER's RLS scope. `FILTER` on the agent
#: speaker rather than a join predicate so a call whose transcript holds only caller turns
#: still appears (as a zero) rather than vanishing from the sample size — it IS a call with
#: a transcript, and its agent spoke nothing, which is a rate too.
#:
#: `COALESCE(text_redacted, text)`: the aggregate returns a LENGTH and never a character,
#: so hard rule 5 is not engaged — but reading the default-redacted column first keeps the
#: query inside the rule's default rather than reaching for the raw column it gates.
#:
#: ⚠ **THE MASK IS NOT EXACTLY LENGTH-NEUTRAL, AND THE RESIDUAL BIAS IS DOWNWARD.** This
#: comment used to say only "length-neutral to within noise". Read against the masks
#: themselves (`workers/redaction.MASK` is `[redacted]`, 10 chars; `PHONE_MASK` is
#: `[phone ••{last2}]`, 12): a phone number the agent read back is 10-13 characters and
#: comes out at 12, which really is noise, but an email or a card number is replaced by
#: something SHORTER than it. So a measured rate is, at the margin, slightly LOW — and a low
#: speaking rate is the direction that flatters us, since it makes the TTS leg and the floor
#: cheaper than they are. It is bounded by how often an AGENT turn contains a PII pattern at
#: all (a receptionist reading back a number), and the alternative — reading the raw column
#: — is a hard-rule-5 exemption for a fourth-decimal correction, which is not a trade this
#: repository makes. Recorded rather than left implied, so the next reader inherits the
#: direction of the error and not just the number.
_AGENT_CHARS_PER_CALL: Final[str] = (
    "SELECT c.id AS call_id, c.duration_s, "
    "COALESCE(SUM(length(COALESCE(t.text_redacted, t.text))) "
    "FILTER (WHERE t.speaker = :agent), 0) AS agent_chars "
    "FROM calls c JOIN transcript_turns t ON t.call_id = c.id "
    "WHERE c.duration_s > 0 "
    "GROUP BY c.id, c.duration_s"
)


@dataclass(frozen=True, slots=True)
class CallSample:
    """One call's contribution: how many characters its agent spoke, over how long."""

    tenant_id: UUID
    call_id: UUID
    duration_s: int
    agent_chars: int

    @property
    def chars_per_minute(self) -> Decimal:
        """Exact — chars x 60 / seconds in Decimal, quantized only when published."""
        return Decimal(self.agent_chars) * _SECONDS_PER_MINUTE / Decimal(self.duration_s)


@dataclass(frozen=True, slots=True)
class SpeakingRatePoint:
    """A speaking rate and the TTS ₹ per call-minute it implies at the live rate card."""

    chars_per_minute: Decimal
    tts_inr_per_minute: Decimal


@dataclass(frozen=True, slots=True)
class TtsSpeakingRate:
    """The measurement, or the honest refusal to make one.

    `p50`, `p95` and `pooled` are all set or all `None`, and `measured` says which.
    `assumed_low` / `assumed_high` are always present: they are TRD §10.1's band, the
    figure the measurement replaces (or, below the threshold, the figure still in force).
    """

    calls: int
    clients: int
    minimum_calls: int
    measured: bool
    reason: str | None
    p50: SpeakingRatePoint | None
    p95: SpeakingRatePoint | None
    pooled: SpeakingRatePoint | None
    assumed_low: SpeakingRatePoint
    assumed_high: SpeakingRatePoint


async def sample_tenant(session: AsyncSession, *, tenant_id: UUID) -> list[CallSample]:
    """Every call this tenant's transcripts can speak for. Tenant-scoped session ONLY.

    `tenant_id` is stamped onto each sample for the `clients` count and is not a filter:
    the session's RLS scope is the filter, and a `WHERE tenant_id` here would be a second
    isolation mechanism pretending to be the first.
    """
    rows = (await session.execute(text(_AGENT_CHARS_PER_CALL), {"agent": "agent"})).all()
    return [
        CallSample(
            tenant_id=tenant_id,
            call_id=UUID(str(row.call_id)),
            duration_s=int(row.duration_s),
            agent_chars=int(row.agent_chars),
        )
        for row in rows
    ]


def _point(chars_per_minute: Decimal) -> SpeakingRatePoint:
    return SpeakingRatePoint(
        chars_per_minute=chars_per_minute.quantize(_RATE_Q, rounding=ROUNDING),
        tts_inr_per_minute=tts_inr_per_call_minute(chars_per_minute),
    )


def _nearest_rank(sorted_rates: list[Decimal], percentile: Decimal) -> Decimal:
    """The value at position ⌈p x n⌉ (1-based) — a rate some real call ran at."""
    rank = ceil(percentile * len(sorted_rates))
    return sorted_rates[max(rank, 1) - 1]


def assumed_band() -> tuple[SpeakingRatePoint, SpeakingRatePoint]:
    """TRD §10.1's 360-540 chars/min, priced by the same function as the measurement."""
    low, high = TTS_ASSUMED_CHARS_PER_CALL_MINUTE
    return _point(low), _point(high)


def summarize(samples: list[CallSample], *, minimum_calls: int | None = None) -> TtsSpeakingRate:
    """Pure arithmetic over the pooled samples; refuses below the threshold.

    `minimum_calls` is a parameter for the same reason `FLEET_BUDGET_S` is patched in
    tests rather than raced: a shared development database holds however many calls it
    holds, and the refusal branch has to be provable against a fixture of known size.
    """
    threshold = TTS_SPEAKING_RATE_MIN_CALLS if minimum_calls is None else minimum_calls
    low, high = assumed_band()
    calls = len(samples)
    clients = len({s.tenant_id for s in samples})
    if calls < threshold:
        return TtsSpeakingRate(
            calls=calls,
            clients=clients,
            minimum_calls=threshold,
            measured=False,
            reason=(
                f"{calls} call{'' if calls == 1 else 's'} with a transcript; a figure is "
                f"published from {threshold} or more. TRD §10.1's assumed band stays in force."
            ),
            p50=None,
            p95=None,
            pooled=None,
            assumed_low=low,
            assumed_high=high,
        )

    rates = sorted(s.chars_per_minute for s in samples)
    total_chars = sum(s.agent_chars for s in samples)
    total_seconds = sum(s.duration_s for s in samples)
    pooled = Decimal(total_chars) * _SECONDS_PER_MINUTE / Decimal(total_seconds)
    return TtsSpeakingRate(
        calls=calls,
        clients=clients,
        minimum_calls=threshold,
        measured=True,
        reason=None,
        p50=_point(_nearest_rank(rates, Decimal("0.5"))),
        p95=_point(_nearest_rank(rates, Decimal("0.95"))),
        pooled=_point(pooled),
        assumed_low=low,
        assumed_high=high,
    )


# --- THE FLEET FIGURE THE COST MODEL ACTUALLY DIVIDES BY (D-557) ----------------------
#
# EVERYTHING ABOVE IS THE BOARD; EVERYTHING BELOW IS THE WIRE. `summarize` needs one sample
# per call to produce a percentile, so its reader has to walk the client book — one
# `tenant_session` per account, because `calls` and `transcript_turns` FORCE RLS. That is
# the right shape for a board an operator OPENS and the wrong shape for anything a page
# renders: the identical walk turned one rate-card read into 8,480 session checkouts on
# this repository's own development database (D-556, `billing/tts_volume.py`).
#
# The COST MODEL does not need percentiles. It needs the pooled rate, which is three
# running totals — so those three totals are a platform counter the post-call meter moves,
# and reading them is ONE indexed row per month on whatever session the caller already
# holds. `platform_speaking_rate` (migration `a3f81c2e6d94`) is that counter and this is its
# one reader and one writer.
#
# **POOLED, AND NOT p50 OR p95, AND THE CHOICE IS NOT A ROUNDING PREFERENCE.** The pooled
# rate is Sigma chars / Sigma minutes — the only figure that reconstructs a month's TTS bill
# from a month's minutes, which is precisely what a cost floor is for. The p50 answers "what
# does a TYPICAL call do" and understates the bill whenever the distribution is right-skewed
# (a few long chatty calls, which is the shape a receptionist agent has). The p95 answers
# "how bad can ONE call be": multiplying it into a floor prices every minute of the month as
# if it were the worst call of the month, which would refuse rungs that are comfortably
# profitable in aggregate. So the tail stays on the board as an exposure figure and never
# enters a rupee the card is judged against.

#: The counter's month-keyed rows, summed over a window. THREE running totals moved in ONE
#: statement, so two calls completing at the same instant cannot both read a pre-increment
#: total and both write it back (BACKEND-PATTERNS §5 — the guard is IN the write).
#: `platform_speaking_rate` is a counter and not a ledger, deliberately NOT in
#: `APPEND_ONLY_TABLES`: every figure it holds is re-derivable from the `calls` and
#: `transcript_turns` rows that produced it, which is exactly what its migration's backfill
#: does.
_BUMP_SQL: Final = """
INSERT INTO platform_speaking_rate (month, calls, agent_chars, call_seconds, updated_at)
VALUES (:month, :calls, :agent_chars, :call_seconds, now())
ON CONFLICT (month) DO UPDATE
   SET calls        = platform_speaking_rate.calls        + EXCLUDED.calls,
       agent_chars  = platform_speaking_rate.agent_chars  + EXCLUDED.agent_chars,
       call_seconds = platform_speaking_rate.call_seconds + EXCLUDED.call_seconds,
       updated_at   = now()
"""

_READ_SQL: Final = (
    "SELECT COALESCE(SUM(calls), 0), COALESCE(SUM(agent_chars), 0), "
    "COALESCE(SUM(call_seconds), 0), MIN(month), MAX(month) FROM platform_speaking_rate"
)

#: The window clause, appended only when a caller names months. Kept out of `_READ_SQL`
#: rather than passed as an always-present `:months` array, because `= ANY(NULL)` is NULL
#: and would silently return the empty measurement — an absence that reads exactly like "no
#: calls yet" while the counter is full.
_READ_WINDOW: Final = " WHERE month = ANY(:months)"


@dataclass(frozen=True, slots=True)
class FleetSpeakingRate:
    """The fleet's pooled speaking rate, or the honest refusal to publish one.

    Three totals and the months they span. `basis()` is the only way this becomes a figure
    the cost model may use, and it applies `TTS_SPEAKING_RATE_MIN_CALLS` — so a consumer
    cannot reach a measured rate without clearing the bar, and cannot forget to check.
    """

    calls: int
    agent_chars: int
    call_seconds: Decimal
    first_month: str | None
    last_month: str | None

    @property
    def window(self) -> str | None:
        """`"2026-07..2026-09"`, or `None` when the counter holds nothing at all."""
        if self.first_month is None or self.last_month is None:
            return None
        if self.first_month == self.last_month:
            return self.first_month
        return f"{self.first_month}..{self.last_month}"

    @property
    def pooled_chars_per_minute(self) -> Decimal | None:
        """Sigma chars x 60 / Sigma seconds, EXACT — or `None` with no seconds to divide by.

        `None` and never zero: a fleet that has spoken no seconds has no rate, and a zero
        would price the TTS leg at nothing, which is the direction that flatters us.
        """
        if self.call_seconds <= 0 or self.agent_chars <= 0:
            return None
        return Decimal(self.agent_chars) * _SECONDS_PER_MINUTE / self.call_seconds

    def basis(self, *, minimum_calls: int | None = None) -> SpeakingRateBasis:
        """**THE ONE DOOR FROM A MEASUREMENT INTO THE COST MODEL.**

        Returns a MEASURED basis when the sample clears the bar and the assumed band
        otherwise — carrying the sample size either way, so a screen can say "7 of 20 calls"
        rather than only "unmeasured". Hard rule 11 applied to our own data: a figure from
        under the bar may be shown, and may not be called a measurement.

        `minimum_calls` is a parameter for the reason `summarize`'s is: a shared development
        database holds however many calls it holds, and the refusal branch has to be
        provable against a fixture of known size.
        """
        threshold = TTS_SPEAKING_RATE_MIN_CALLS if minimum_calls is None else minimum_calls
        pooled = self.pooled_chars_per_minute
        if pooled is None or self.calls < threshold:
            return assumed_speaking_rate(calls=self.calls, minimum_calls=threshold)
        return SpeakingRateBasis(
            # Quantized at the same scale as every other published rate here, and the rupee
            # it implies is taken from the quantized figure so the screen's rate and the
            # screen's floor cannot disagree in the fourth place.
            chars_per_call_minute=pooled.quantize(_RATE_Q, rounding=ROUNDING),
            measured=True,
            calls=self.calls,
            minimum_calls=threshold,
            window=self.window,
        )


async def fleet_speaking_rate(
    session: AsyncSession, *, months: Sequence[str] | None = None
) -> FleetSpeakingRate:
    """The whole platform's pooled speaking rate. ONE aggregate over one row per month.

    Works on ANY session — the table carries no `tenant_id` and no policy, so it answers the
    same on a tenant-scoped session as on the admin one. That is the entire reason it exists
    (the block comment above), and it is what lets a page ask the question without a walk.

    `months` scopes the window and defaults to EVERY month the counter holds. The whole
    archive is the largest honest sample, and a speaking rate is a property of how our
    agents' scripts are written rather than of a period — the day a script change makes
    history misleading, a trailing window is this argument and no other edit.
    """
    params = {"months": list(months)} if months is not None else {}
    sql = _READ_SQL + (_READ_WINDOW if months is not None else "")
    row = (await session.execute(text(sql), params)).one()
    return FleetSpeakingRate(
        calls=int(row[0]),
        agent_chars=int(row[1]),
        call_seconds=Decimal(str(row[2])),
        first_month=row[3],
        last_month=row[4],
    )


async def bump_speaking_rate(
    session: AsyncSession,
    *,
    month: str,
    agent_chars: int,
    call_seconds: Decimal,
) -> None:
    """Add ONE call's characters and seconds to the fleet's month. Exactly one call.

    Called by the post-call meter INSIDE the same transaction as the `usage_events` rows it
    describes, so the counter and the ledger it summarises can never be half-written — and
    the meter's own "already metered?" guard is what makes it exactly-once per call.

    **A CALL WITH NO SECONDS IS NOT COUNTED AT ALL**, which is the same predicate the walk
    applies (`_AGENT_CHARS_PER_CALL`'s `duration_s > 0`): it contributes nothing to either
    total and would still raise the divisor of the publication threshold, making twenty
    zero-second calls read as a sample. A call whose agent said nothing IS counted, as a
    zero — its agent really did speak no characters in real seconds, and dropping it would
    bias the fleet rate upward.
    """
    if call_seconds <= 0:
        return
    await session.execute(
        text(_BUMP_SQL),
        {
            "month": month,
            "calls": 1,
            "agent_chars": max(0, agent_chars),
            "call_seconds": call_seconds,
        },
    )


__all__ = [
    "TTS_SPEAKING_RATE_MIN_CALLS",
    "CallSample",
    "FleetSpeakingRate",
    "SpeakingRatePoint",
    "TtsSpeakingRate",
    "assumed_band",
    "bump_speaking_rate",
    "fleet_speaking_rate",
    "sample_tenant",
    "summarize",
]
