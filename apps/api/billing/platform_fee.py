"""The monthly platform fee (D-707): one switch, one amount, one fee per client per month.

D-707 (founder, 10 Oct 2026) put every client on ONE pricing model — prepaid credits — and
added an optional platform-wide monthly fee on top of it:

* **One switch.** `Settings.platform_fee_enabled` and `Settings.platform_fee_inr`, set in
  the ops console. On, every live client that is not exempt is raised the fee each IST
  month; off, nobody is. It is never per plan or per client.
* **A separate payment.** The fee is never taken from calling credit. It is paid through
  its own Razorpay order (`platform_fee_routes`), or recorded by an operator as a bank
  transfer, into `monthly_fee_payments`, an append-only ledger beside `credit_ledger`.
* **Grace, then outbound pauses.** `GRACE_PERIOD` after a fee is raised, an unpaid fee
  pauses OUTBOUND calling through the dispatch gate (`compliance.service.check_dispatch`
  asks `platform_fee_paused`). Inbound is never asked: the gate answers an inbound-only
  agent before any money question. Paying lifts the pause on the next dial, because the
  gate reads the ledger rather than a flag somebody has to clear.
* **Exempt.** An account on a free trial, and an account an operator waived with a reason
  (written to `audit_log` by the route).

Whether a fee is paid is never a column: it is "does a payment row exist for this charge".
A status therefore cannot disagree with the money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import ist_billing_month
from apps.api.billing.trials import read_trial
from apps.api.compliance.trial_access import restricting_trial
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

#: How long a raised fee may stay unpaid before outbound calling pauses (D-707).
GRACE_PERIOD: Final = timedelta(days=7)

#: How long before the grace period ends the reminder email goes out.
REMINDER_BEFORE: Final = timedelta(days=2)

#: The dispatch gate's rule name and the client's sentence for it.
PLATFORM_FEE_RULE: Final = "platform_fee_overdue"
PLATFORM_FEE_PAUSE_REASON: Final = (
    "Outbound calls are paused because this month's platform fee is unpaid. Incoming "
    "calls keep working. Pay the fee on the Billing page and calling resumes at once."
)

#: The Razorpay order notes key that names the charge a payment settles.
NOTES_CHARGE_KEY: Final = "calevate_platform_fee_charge_id"

FeeStatus = Literal["paid", "due", "overdue", "waived"]
Exemption = Literal["trial", "waiver"]
PaymentMethod = Literal["razorpay", "manual"]


@dataclass(frozen=True, slots=True)
class FeeSwitch:
    """The ops console's switch, read once per question."""

    enabled: bool
    amount_inr: Decimal | None

    @property
    def charging(self) -> bool:
        """On AND priced. On without an amount raises nothing (the job alarms instead)."""
        return self.enabled and self.amount_inr is not None


def fee_switch() -> FeeSwitch:
    settings = get_settings()
    return FeeSwitch(enabled=settings.platform_fee_enabled, amount_inr=settings.platform_fee_inr)


@dataclass(frozen=True, slots=True)
class FeeCharge:
    """One raised fee, as every surface reads it."""

    id: UUID
    tenant_id: UUID
    period: str
    amount_inr: Decimal
    issued_at: datetime
    grace_ends_at: datetime
    provider_order_id: str | None
    paid_at: datetime | None
    payment_method: str | None
    issued_notice_sent_at: datetime | None
    reminder_sent_at: datetime | None
    paused_notice_sent_at: datetime | None

    @property
    def paid(self) -> bool:
        return self.paid_at is not None


def fee_status(
    charge: FeeCharge, *, at: datetime, exemption: Exemption | None, switch: FeeSwitch
) -> FeeStatus:
    """What a client is told about one fee. Paid wins; an exempt account, or a switch an
    operator has turned off, owes nothing on an unpaid fee; otherwise due until the grace
    period ends and overdue after it."""
    if charge.paid:
        return "paid"
    if exemption is not None or not switch.enabled:
        return "waived"
    return "due" if at < charge.grace_ends_at else "overdue"


_CHARGE_COLUMNS = (
    "c.id, c.tenant_id, c.period, c.amount, c.issued_at, c.grace_ends_at, "
    "c.provider_order_id, p.paid_at, p.method, c.issued_notice_sent_at, "
    "c.reminder_sent_at, c.paused_notice_sent_at"
)
_CHARGES_FROM = "FROM monthly_fee_charges c LEFT JOIN monthly_fee_payments p ON p.charge_id = c.id "


def _charge(row: Row[Any]) -> FeeCharge:
    values = tuple(row)
    return FeeCharge(
        id=UUID(str(values[0])),
        tenant_id=UUID(str(values[1])),
        period=str(values[2]),
        amount_inr=Decimal(str(values[3])),
        issued_at=values[4],
        grace_ends_at=values[5],
        provider_order_id=None if values[6] is None else str(values[6]),
        paid_at=values[7],
        payment_method=None if values[8] is None else str(values[8]),
        issued_notice_sent_at=values[9],
        reminder_sent_at=values[10],
        paused_notice_sent_at=values[11],
    )


async def exemption_of(session: AsyncSession, *, tenant_id: UUID, at: datetime) -> Exemption | None:
    """Why this account owes no fee, or None when it does.

    A free trial is exempt whether it is still running, has ended unpaid (the account is
    still restricted to test calls) or the account sits on the `trial` tier. A waiver is an
    operator's decision with a reason. Asked under the caller's tenant-scoped session.
    """
    row = (
        await session.execute(
            text("SELECT plan_tier, platform_fee_waived_at FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        return None
    if row[1] is not None:
        return "waiver"
    if str(row[0]) == "trial":
        return "trial"
    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is not None and trial.is_active(at=at):
        return "trial"
    if await restricting_trial(session, tenant_id=tenant_id) is not None:
        return "trial"
    return None


async def list_charges(
    session: AsyncSession, *, tenant_id: UUID, limit: int = 12
) -> list[FeeCharge]:
    """This client's fees, newest month first, with whether each was paid."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_CHARGE_COLUMNS} {_CHARGES_FROM}"
                "WHERE c.tenant_id = :tid ORDER BY c.period DESC LIMIT :limit"
            ),
            {"tid": tenant_id, "limit": limit},
        )
    ).all()
    return [_charge(row) for row in rows]


async def read_charge(
    session: AsyncSession, *, tenant_id: UUID, charge_id: UUID
) -> FeeCharge | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_CHARGE_COLUMNS} {_CHARGES_FROM}WHERE c.tenant_id = :tid AND c.id = :cid"
            ),
            {"tid": tenant_id, "cid": charge_id},
        )
    ).first()
    return None if row is None else _charge(row)


async def charge_for_order(
    session: AsyncSession, *, tenant_id: UUID, order_id: str
) -> FeeCharge | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_CHARGE_COLUMNS} {_CHARGES_FROM}"
                "WHERE c.tenant_id = :tid AND c.provider_order_id = :oid"
            ),
            {"tid": tenant_id, "oid": order_id},
        )
    ).first()
    return None if row is None else _charge(row)


async def overdue_charge(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> FeeCharge | None:
    """The oldest unpaid fee past its grace period that this account still owes, or None.

    None whenever the switch is off or the account is exempt: turning the fee off, or
    waiving one client, lifts a pause on the next dial without anybody touching a charge.
    """
    switch = fee_switch()
    if not switch.enabled:
        return None
    now = at or datetime.now(UTC)
    row = (
        await session.execute(
            text(
                f"SELECT {_CHARGE_COLUMNS} {_CHARGES_FROM}"
                "WHERE c.tenant_id = :tid AND c.grace_ends_at <= :at AND p.id IS NULL "
                "ORDER BY c.issued_at LIMIT 1"
            ),
            {"tid": tenant_id, "at": now},
        )
    ).first()
    if row is None:
        return None
    if await exemption_of(session, tenant_id=tenant_id, at=now) is not None:
        return None
    return _charge(row)


async def platform_fee_paused(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """THE outbound gate's question: is calling paused for an unpaid fee?"""
    return await overdue_charge(session, tenant_id=tenant_id) is not None


async def issue_charge(
    session: AsyncSession, *, tenant_id: UUID, amount_inr: Decimal, at: datetime
) -> UUID | None:
    """Raise this month's fee for one client. Returns the new charge id, or None when the
    month already has one: `ux_monthly_fee_charges_tenant_period` is the guard, in the
    write, so two ticks racing on one tenant-month cannot both raise it."""
    if amount_inr <= 0:
        raise ValueError("a platform fee is a positive amount")
    row = (
        await session.execute(
            text(
                "INSERT INTO monthly_fee_charges "
                "(id, tenant_id, period, amount, issued_at, grace_ends_at) "
                "VALUES (:id, :tid, :period, :amount, :at, :grace) "
                "ON CONFLICT (tenant_id, period) DO NOTHING RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "period": ist_billing_month(at),
                "amount": amount_inr,
                "at": at,
                "grace": at + GRACE_PERIOD,
            },
        )
    ).first()
    return None if row is None else UUID(str(row[0]))


async def attach_order(
    session: AsyncSession, *, tenant_id: UUID, charge_id: UUID, order_id: str
) -> None:
    """Remember the Razorpay order a client opened to pay this fee."""
    await session.execute(
        text(
            "UPDATE monthly_fee_charges SET provider_order_id = :oid, updated_at = now() "
            "WHERE id = :cid AND tenant_id = :tid"
        ),
        {"oid": order_id, "cid": charge_id, "tid": tenant_id},
    )


async def record_payment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    charge: FeeCharge,
    amount_inr: Decimal,
    method: PaymentMethod,
    payment_ref: str,
    paid_at: datetime,
    recorded_by: UUID | None = None,
) -> bool:
    """Settle one fee. True when this call recorded it, False when it was already paid.

    The amount must be exactly the fee: a payment that differs is refused rather than
    recorded, because a fee half paid is not a state this product has a word for. The
    unique index on `charge_id` makes a redelivered webhook, or two operators recording
    the same transfer, write one row.
    """
    if amount_inr != charge.amount_inr:
        raise ProblemError.conflict(
            "platform_fee_amount_mismatch",
            "This payment's amount does not match the platform fee it was for.",
            remediation="Nothing was recorded. Reconcile it against the provider dashboard.",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO monthly_fee_payments "
                "(id, tenant_id, charge_id, amount, method, payment_ref, recorded_by, paid_at) "
                "VALUES (:id, :tid, :cid, :amount, :method, :ref, :by, :at) "
                "ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": charge.id,
                "amount": amount_inr,
                "method": method,
                "ref": payment_ref.strip(),
                "by": recorded_by,
                "at": paid_at,
            },
        )
    ).first()
    return row is not None


async def set_waiver(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    reason: str | None,
    operator_id: UUID | None,
    at: datetime,
) -> bool:
    """Grant (`reason` set) or withdraw (`reason` None) this client's fee waiver.

    Returns True when the account's waiver changed. The caller writes the audit row in
    the same transaction.
    """
    if reason is None:
        row = (
            await session.execute(
                text(
                    "UPDATE organizations SET platform_fee_waived_at = NULL, "
                    "platform_fee_waiver_reason = NULL, platform_fee_waived_by = NULL, "
                    "updated_at = now() WHERE id = :tid AND platform_fee_waived_at IS NOT NULL "
                    "RETURNING id"
                ),
                {"tid": tenant_id},
            )
        ).first()
        return row is not None
    row = (
        await session.execute(
            text(
                "UPDATE organizations SET platform_fee_waived_at = :at, "
                "platform_fee_waiver_reason = :reason, platform_fee_waived_by = :by, "
                "updated_at = now() WHERE id = :tid "
                "AND platform_fee_waiver_reason IS DISTINCT FROM :reason RETURNING id"
            ),
            {"tid": tenant_id, "at": at, "reason": reason.strip(), "by": operator_id},
        )
    ).first()
    return row is not None


@dataclass(frozen=True, slots=True)
class Waiver:
    waived_at: datetime
    reason: str
    #: The operator who granted it (`admin_users.id`), or None once they have left.
    waived_by: UUID | None = None


async def read_waiver(session: AsyncSession, *, tenant_id: UUID) -> Waiver | None:
    row = (
        await session.execute(
            text(
                "SELECT platform_fee_waived_at, platform_fee_waiver_reason, platform_fee_waived_by "
                "FROM organizations WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or row[0] is None:
        return None
    return Waiver(
        waived_at=row[0],
        reason=str(row[1]),
        waived_by=None if row[2] is None else UUID(str(row[2])),
    )


__all__ = [
    "GRACE_PERIOD",
    "NOTES_CHARGE_KEY",
    "PLATFORM_FEE_PAUSE_REASON",
    "PLATFORM_FEE_RULE",
    "REMINDER_BEFORE",
    "Exemption",
    "FeeCharge",
    "FeeStatus",
    "FeeSwitch",
    "PaymentMethod",
    "Waiver",
    "attach_order",
    "charge_for_order",
    "exemption_of",
    "fee_status",
    "fee_switch",
    "issue_charge",
    "list_charges",
    "overdue_charge",
    "platform_fee_paused",
    "read_charge",
    "read_waiver",
    "record_payment",
    "set_waiver",
]
