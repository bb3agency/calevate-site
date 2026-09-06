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

TENANCY. `transcript_turns` and `calls` are FORCE-RLS'd and an untenanted read of either
returns ZERO rows and reports success (the maintenance lane hit exactly that). So there
is no fleet query here: `sample_tenant` reads ONE client inside that client's own
`tenant_session`, and `spend_routes.fleet_tts_speaking_rate` walks the live directory the way
`fleet_spend` does — one directory read, one scoped session per client, nothing that can
see two tenants at once, and no policy widened to make it faster. `summarize` is pure
arithmetic over the pooled per-call samples and never touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import (
    TTS_ASSUMED_CHARS_PER_CALL_MINUTE,
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
_RATE_Q: Final[Decimal] = Decimal("0.0001")
_SECONDS_PER_MINUTE: Final[Decimal] = Decimal(60)

#: One row per call with a transcript, under the CALLER's RLS scope. `FILTER` on the agent
#: speaker rather than a join predicate so a call whose transcript holds only caller turns
#: still appears (as a zero) rather than vanishing from the sample size — it IS a call with
#: a transcript, and its agent spoke nothing, which is a rate too.
#:
#: `COALESCE(text_redacted, text)`: the aggregate returns a LENGTH and never a character,
#: so hard rule 5 is not engaged — but reading the default-redacted column first keeps the
#: query inside the rule's default rather than reaching for the raw column it gates. For
#: an agent's scripted turns the mask is length-neutral to within noise.
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
        chars_per_minute=chars_per_minute.quantize(_RATE_Q),
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


__all__ = [
    "TTS_SPEAKING_RATE_MIN_CALLS",
    "CallSample",
    "SpeakingRatePoint",
    "TtsSpeakingRate",
    "assumed_band",
    "sample_tenant",
    "summarize",
]
