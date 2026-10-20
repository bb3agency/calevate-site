"""Cost inputs an operator attests that are not a per-minute engine price (D-840).

Three subjects, each effective-dated in `platform_cost_attestations` and read at the instant
the cost was incurred, never as a code constant:

* `thinnest_topup_fee` — the voice platform's wallet top-up fee, a FRACTION added to every
  rupee its minutes and number rent cost us (`engine_minutes.wallet_topup_fee`). Carried over
  from the code constant by migration `d8a4c2e7f150` (2.36%, VENDOR-STATED in ThinnestAI's
  email of 12 Oct 2026).
* `razorpay_topup_fee` — the payment gateway's fee on what a client pays for credit, a
  FRACTION of the sale, counted in the per-minute cost floor (founder, 20 Oct 2026). Not
  seeded: the gateway's rate for this account has not been read off a statement here, so
  until an operator attests it the floor omits it and says so.
* `thinnest_number_month` — what a number rented in the voice platform's console costs us a
  month, in RUPEES, before the top-up fee: the plan rate its number search quotes
  (snapshots/2026-10-19/pages/api-reference/phone-numbers/search-available-phone-numbers.md:7,
  "each with its monthly rent at your plan's rate"). Not seeded.

An absent subject is UNPRICED, never zero: the meter writes a NULL cost and alarms, and the
floor names the missing input (hard rule 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal, get_args

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import rates
from apps.api.core.errors import ProblemError

CostSubject = Literal["thinnest_topup_fee", "razorpay_topup_fee", "thinnest_number_month"]
COST_SUBJECTS: Final[tuple[str, ...]] = get_args(CostSubject)

#: Subjects that are a fraction of an amount (0 <= value < 1); the rest are rupees.
FRACTION_SUBJECTS: Final = frozenset({"thinnest_topup_fee", "razorpay_topup_fee"})

#: The wallet top-up fee of each engine paid from a topped-up wallet.
WALLET_TOPUP_FEE_SUBJECTS: Final[Mapping[str, CostSubject]] = MappingProxyType(
    {"thinnest": "thinnest_topup_fee"}
)
#: The monthly rent of a number rented in each engine's own console.
ENGINE_NUMBER_RENT_SUBJECTS: Final[Mapping[str, CostSubject]] = MappingProxyType(
    {"thinnest": "thinnest_number_month"}
)
#: The payment gateway's fee on a client's top-up.
GATEWAY_FEE_SUBJECT: Final[CostSubject] = "razorpay_topup_fee"

#: What each subject is, for the operator's console. Names the vendor: admin realm only.
SUBJECT_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "thinnest_topup_fee": "ThinnestAI wallet top-up fee",
        "razorpay_topup_fee": "Razorpay fee on a client's top-up",
        "thinnest_number_month": "ThinnestAI number rent, per month",
    }
)

#: NUMERIC(14,6): eight integer digits.
_MAX_VALUE: Final = Decimal("100000000")


@dataclass(frozen=True, slots=True)
class AttestedCost:
    subject: str
    value: Decimal
    effective_from: datetime
    attested_at: datetime
    #: None only on the row carried over from the code constant.
    attested_by: str | None
    source_note: str


def _require_subject(subject: str) -> None:
    if subject not in COST_SUBJECTS:
        raise ProblemError(
            kind="not_found",
            code="cost_attestation_unknown_subject",
            title="No such cost",
            detail=f"{subject!r} is not one of {', '.join(COST_SUBJECTS)}.",
        )


async def attested_costs(session: AsyncSession, *, at: datetime) -> dict[str, AttestedCost]:
    """Every subject's figure in force at `at`. An unattested subject is ABSENT."""
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (subject) subject, value, effective_from, attested_at, "
                "attested_by, source_note FROM platform_cost_attestations "
                "WHERE effective_from <= :at ORDER BY subject, effective_from DESC"
            ),
            {"at": at},
        )
    ).all()
    return {
        str(row[0]): AttestedCost(
            subject=str(row[0]),
            value=Decimal(str(row[1])),
            effective_from=row[2],
            attested_at=row[3],
            attested_by=None if row[4] is None else str(row[4]),
            source_note=str(row[5]),
        )
        for row in rows
    }


async def attested_cost(
    session: AsyncSession, *, subject: CostSubject, at: datetime
) -> AttestedCost | None:
    """One subject's figure in force at `at`, or None while unattested."""
    return (await attested_costs(session, at=at)).get(subject)


def parse_cost_value(subject: str, raw: str) -> Decimal:
    """An operator's typed figure as an exact Decimal, or this subject's refusal. A fraction
    subject is typed in PERCENT ("2.36") and stored as a fraction."""
    _require_subject(subject)
    try:
        value = Decimal(raw.strip())
    except ArithmeticError:
        value = Decimal("NaN")
    fraction = subject in FRACTION_SUBJECTS
    stored = value / 100 if fraction and value.is_finite() else value
    exponent = stored.as_tuple().exponent if stored.is_finite() else None
    if (
        not stored.is_finite()
        or stored < 0
        or (fraction and stored >= 1)
        or (not fraction and (stored <= 0 or stored >= _MAX_VALUE))
        or (isinstance(exponent, int) and -exponent > 6)
    ):
        raise ProblemError(
            kind="validation",
            code="cost_attestation_invalid",
            title="That is not a valid figure",
            detail=(
                "A percentage from 0 up to (not including) 100, with at most four decimals."
                if fraction
                else "Rupees a month: a positive decimal with at most six decimals."
            ),
            remediation="Type the figure from the invoice or statement, like 2.36 or 349.00.",
        )
    return stored


async def attest_cost(
    session: AsyncSession,
    *,
    subject: str,
    value: Decimal,
    effective_from: datetime,
    source_note: str,
    actor_id: object,
) -> AttestedCost:
    """Record one attested figure as a NEW effective-dated row. Never an UPDATE.

    The caller MUST be step-up confirmed and MUST write the audit row on this session, the
    contract `engine_minutes.attest_engine_minute_price` carries."""
    _require_subject(subject)
    if subject not in FRACTION_SUBJECTS:
        try:
            rates.assert_rate_is_meterable(value, subject=f"the attested {subject}", unit="month")
        except ValueError as too_small:
            raise ProblemError(
                kind="validation",
                code="attested_price_not_meterable",
                title="This price is quoted in too small a unit to meter",
                detail=str(too_small),
            ) from too_small
    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM platform_cost_attestations "
                "WHERE subject = :s AND effective_from = :ef"
            ),
            {"s": subject, "ef": effective_from},
        )
    ).first()
    if existing is not None:
        raise ProblemError(
            kind="conflict",
            code="cost_attestation_duplicate_instant",
            title="A figure already exists for this cost at this instant",
            detail="A correction is a NEW effective instant, never an edit of an existing one.",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_cost_attestations "
                "(subject, effective_from, value, attested_by, source_note) "
                "VALUES (:s, :ef, :v, :by, :note) RETURNING attested_at"
            ),
            {"s": subject, "ef": effective_from, "v": value, "by": actor_id, "note": source_note},
        )
    ).one()
    return AttestedCost(
        subject=subject,
        value=value,
        effective_from=effective_from,
        attested_at=row[0],
        attested_by=str(actor_id),
        source_note=source_note,
    )


__all__ = [
    "COST_SUBJECTS",
    "ENGINE_NUMBER_RENT_SUBJECTS",
    "FRACTION_SUBJECTS",
    "GATEWAY_FEE_SUBJECT",
    "SUBJECT_LABELS",
    "WALLET_TOPUP_FEE_SUBJECTS",
    "AttestedCost",
    "CostSubject",
    "attest_cost",
    "attested_cost",
    "attested_costs",
    "parse_cost_value",
]
