"""Two reads for the billing screen's redesign (D-869, founder decision f7d9f716 §3).

`GET /v1/billing/voice-tiers` — Clear against Studio. Every rupee comes from the sources
that already price a minute and nothing is typed here (hard rule 7): the card's range from
`payment_routes.rate_card_out` (the same function the public rate card and the packs screen
read), this account's rate now from `lots.voice_tier_rates` (the oldest open lot, which is
what the next minute is charged), its minutes left from `lots.runway`, and this month's use
of each from `service.voice_tier_usage`. What each tier includes is product copy, and names
no provider (D-679).

`GET /v1/billing/credit-usage` — what entered and left the wallet this IST month and over
the wallet's whole life, in the drawdown buckets the statements already use
(`wallet.DRAWDOWN_BUCKETS_SQL`, `wallet.CREDIT_ADDED_SQL`).

Both `billing:read`: spend is an owner's business (SEC-COMP §5), the same as `/v1/usage`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import lots
from apps.api.billing.ai_quota import OVERAGE_META_KIND
from apps.api.billing.payment_routes import rate_card_out
from apps.api.billing.plans import ist_month_window
from apps.api.billing.rates import VOICE_TIERS, VoiceTier, voice_tier_label
from apps.api.billing.service import (
    allocate_paise,
    current_billing_month,
    to_paise,
    voice_tier_usage,
)
from apps.api.billing.wallet import CREDIT_ADDED_SQL, DRAWDOWN_BUCKETS_SQL
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/billing", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
BillingReader = Annotated[Principal, Depends(requires("billing:read", realm="client"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: What each tier gives a client, in their words. Product copy, not a price: no rupee is
#: written here, and no provider is named.
TIER_INCLUDES: Final[dict[VoiceTier, tuple[str, ...]]] = {
    "clear": (
        "Clear, natural voices for every call",
        "Everything your agent does: answering, capturing leads, call-backs",
        "The lowest price per minute",
    ),
    "studio": (
        "Studio-quality voices that sound closest to a person",
        "Voices our team prepares for your business",
        "Everything Clear includes",
    ),
}
TIER_BEST_FOR: Final[dict[VoiceTier, str]] = {
    "clear": "Most businesses: enquiries, bookings, reminders and follow-ups.",
    "studio": "Businesses where how the agent sounds matters as much as what it says.",
}


class VoiceTierCompareOut(Strict):
    tier: VoiceTier
    #: What the client calls it ("Clear", "Studio").
    label: str
    #: False when no agent can be put on this tier on this deployment yet.
    offered: bool
    #: The card's cheapest and dearest ₹/min across packs (rate precision, 4 dp).
    from_inr_per_min: Decimal
    to_inr_per_min: Decimal
    #: The rate this account's next minute on this tier is charged (its oldest open credit);
    #: null with no open credit.
    your_inr_per_min: Decimal | None
    #: Whole minutes the wallet still buys on this tier; null with no open credit.
    minutes_left: int | None
    #: This IST month so far.
    minutes_this_month: Decimal
    charged_this_month_inr: Decimal
    includes: list[str]
    best_for: str


class VoiceTierComparisonOut(Strict):
    tiers: list[VoiceTierCompareOut]
    #: The sentence a page shows beside a tier that is not offered; null when both are.
    not_offered_notice: str | None
    #: "Which is right for me": the tier we suggest, and why, from this account's own use.
    recommended: VoiceTier
    recommendation_reason: str


def recommend(
    *, studio_offered: bool, clear_minutes: Decimal, studio_minutes: Decimal
) -> tuple[VoiceTier, str]:
    """Deterministic: Studio only when it is offered AND most of this month's minutes were
    already spoken on it; Clear otherwise."""
    if not studio_offered:
        return "clear", "Studio is not open on your account yet, so Clear is the one to use."
    if studio_minutes > 0 and studio_minutes >= clear_minutes:
        return (
            "studio",
            "Most of your calls this month already use Studio voices, so Studio fits how you work.",
        )
    return (
        "clear",
        "Clear costs less per minute and suits most calls. Choose Studio for agents whose "
        "voice is part of your brand.",
    )


@router.get(
    "/voice-tiers",
    response_model=VoiceTierComparisonOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Clear against Studio: ₹ per minute, your rate, your use, what each includes",
)
async def voice_tiers(session: Session, principal: BillingReader) -> VoiceTierComparisonOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    card = await rate_card_out(session)
    yours = {
        r.voice_tier: r.inr_per_min
        for r in await lots.voice_tier_rates(session, tenant_id=tenant_id)
    }
    runway = await lots.runway(session, tenant_id=tenant_id)
    has_lots = any(rate is not None for rate in yours.values())
    usage = await voice_tier_usage(session, tenant_id=tenant_id, month=current_billing_month())
    columns: dict[VoiceTier, tuple[str, str]] = {
        "clear": ("clear_inr_per_min", "clear_minutes"),
        "studio": ("studio_inr_per_min", "studio_minutes"),
    }
    tiers: list[VoiceTierCompareOut] = []
    for tier in VOICE_TIERS:
        rate_field, minutes_key = columns[tier]
        rates = [Decimal(getattr(pack, rate_field)) for pack in card.packs]
        spoken = usage.by_voice.get(tier)
        tiers.append(
            VoiceTierCompareOut(
                tier=tier,
                label=voice_tier_label(tier),
                offered=card.voice_not_offered != tier,
                from_inr_per_min=min(rates),
                to_inr_per_min=max(rates),
                your_inr_per_min=yours.get(tier),
                minutes_left=int(runway[minutes_key]) if has_lots else None,
                minutes_this_month=spoken.minutes if spoken else Decimal("0"),
                charged_this_month_inr=to_paise(spoken.charged_inr if spoken else Decimal("0")),
                includes=list(TIER_INCLUDES[tier]),
                best_for=TIER_BEST_FOR[tier],
            )
        )
    by_tier = {t.tier: t for t in tiers}
    recommended, reason = recommend(
        studio_offered=by_tier["studio"].offered,
        clear_minutes=by_tier["clear"].minutes_this_month,
        studio_minutes=by_tier["studio"].minutes_this_month,
    )
    return VoiceTierComparisonOut(
        tiers=tiers,
        not_offered_notice=card.voice_not_offered_notice,
        recommended=recommended,
        recommendation_reason=reason,
    )


CreditPeriod = Literal["this_month", "all_time"]


class CreditUsagePeriodOut(Strict):
    period: CreditPeriod
    #: Credit that landed: payments, bonuses, positive adjustments and grants.
    added_inr: Decimal
    #: Everything that left the wallet: the four buckets below added together.
    spent_inr: Decimal
    calls_inr: Decimal
    ai_assist_inr: Decimal
    number_rental_inr: Decimal
    adjustments_inr: Decimal
    #: Credit that lapsed unused ("Credit expired"); not part of `spent_inr`.
    expired_inr: Decimal


class CreditUsageOut(Strict):
    #: The IST month `this_month` covers, `YYYY-MM`.
    month: str
    this_month: CreditUsagePeriodOut
    all_time: CreditUsagePeriodOut


_CREDIT_USAGE_SQL: Final = (
    f"SELECT {CREDIT_ADDED_SQL}, {DRAWDOWN_BUCKETS_SQL} FROM credit_ledger "
    "WHERE tenant_id = :tid AND (CAST(:start AS timestamptz) IS NULL OR occurred_at >= :start) "
    "AND (CAST(:end AS timestamptz) IS NULL OR occurred_at < :end)"
)


async def _period(
    session: AsyncSession,
    *,
    tenant_id: object,
    period: CreditPeriod,
    start: datetime | None,
    end: datetime | None,
) -> CreditUsagePeriodOut:
    row = (
        await session.execute(
            text(_CREDIT_USAGE_SQL),
            {"tid": tenant_id, "start": start, "end": end, "ai_kind": OVERAGE_META_KIND},
        )
    ).one()
    added, calls, ai, adjustments, rental, expired = (Decimal(str(v)) for v in row)
    # The parts are allocated against the rounded total, so the lines printed under
    # "spent" add up to it: call debits carry sub-paisa digits.
    spent = to_paise(calls + ai + adjustments + rental)
    calls_p, ai_p, adjustments_p, rental_p = allocate_paise([calls, ai, adjustments, rental], spent)
    return CreditUsagePeriodOut(
        period=period,
        added_inr=to_paise(added),
        spent_inr=spent,
        calls_inr=calls_p,
        ai_assist_inr=ai_p,
        number_rental_inr=rental_p,
        adjustments_inr=adjustments_p,
        expired_inr=to_paise(expired),
    )


@router.get(
    "/credit-usage",
    response_model=CreditUsageOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Credit added and used: this IST month and all time",
)
async def credit_usage(session: Session, principal: BillingReader) -> CreditUsageOut:
    assert principal.tenant_id is not None
    month = current_billing_month()
    start, end = ist_month_window(month)
    return CreditUsageOut(
        month=month,
        this_month=await _period(
            session, tenant_id=principal.tenant_id, period="this_month", start=start, end=end
        ),
        all_time=await _period(
            session,
            tenant_id=principal.tenant_id,
            period="all_time",
            start=None,
            end=datetime.now(UTC),
        ),
    )


__all__ = ["recommend", "router"]
