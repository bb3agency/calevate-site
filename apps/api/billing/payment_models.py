"""Razorpay objects we own, auto-recharge mandates and disputes (D-699).

Four tenant tables, each FORCE-RLS'd with the strict `tenant_isolation` policy and, where a
cross-tenant reader exists, one `FOR SELECT` policy that admits only an UNTENANTED session
(migration e1a7c93b5d24). None of them is a ledger: money is recorded on `credit_ledger`
and nowhere else.

- `razorpay_object_routes` maps an id Razorpay hands back (an order, a token, a customer)
  to the tenant that created it. A webhook arrives with no session and, for token events,
  with no notes at all (`api/payments/recurring-payments/webhooks.md`, token.confirmed
  sample, read 9 Oct 2026), so the route is the only way to attribute it. It is also what
  "verify the tenant and amount from OUR order record" reads: the order's amount and
  purpose are recorded here when we create it.
- `auto_recharge_settings` is one row per tenant: the client's threshold, recharge amount
  and monthly cap, and the Razorpay customer and token ids of the method they authorised.
  Only ids are stored, never a card or UPI detail.
- `auto_recharge_charges` is one row per recharge we started. The partial unique index on
  `status = 'pending'` is what makes a second recharge in flight impossible.
- `payment_disputes` is one row per Razorpay dispute, with the hold we placed on the
  client's credit.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

MONEY = Numeric(12, 4)

ROUTE_KINDS: Final = ("order", "token", "customer")
ROUTE_PURPOSES: Final = ("topup", "mandate", "auto_recharge", "platform_fee")
MANDATE_METHODS: Final = ("upi", "card")
#: `none` before any authorisation; `pending` between the authorisation payment and
#: `token.confirmed`; the rest are Razorpay's token states
#: (`payments/recurring-payments/subscribe-to-webhooks.md`, "Token States", read 9 Oct 2026),
#: less `initiated`, which we fold into `pending`.
MANDATE_STATUSES: Final = ("none", "pending", "confirmed", "rejected", "cancelled", "paused")
CHARGE_STATUSES: Final = ("pending", "captured", "failed")
#: Razorpay's dispute statuses (`api/disputes/entity.md`, read 9 Oct 2026).
DISPUTE_STATUSES: Final = ("open", "under_review", "won", "lost", "closed")


class RazorpayObjectRoute(PKMixin, Base):
    """Which tenant an order, token or customer at Razorpay belongs to."""

    __tablename__ = "razorpay_object_routes"
    __table_args__ = (
        CheckConstraint(f"kind IN {ROUTE_KINDS!r}", name="kind_enum"),
        CheckConstraint(f"purpose IS NULL OR purpose IN {ROUTE_PURPOSES!r}", name="purpose_enum"),
        CheckConstraint("amount_paise IS NULL OR amount_paise > 0", name="amount_positive"),
        CheckConstraint("(kind = 'order') = (amount_paise IS NOT NULL)", name="order_has_amount"),
        Index("ix_razorpay_object_routes_tenant_recent", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    object_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(24))
    #: What WE asked the order for, in paise. A captured payment against this order must
    #: match it exactly, whatever the payment's own notes say.
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class AutoRechargeSettings(PKMixin, TimestampMixin, Base):
    """One tenant's auto-recharge preferences and the mandate behind them."""

    __tablename__ = "auto_recharge_settings"
    __table_args__ = (
        CheckConstraint("threshold_inr >= 0", name="threshold_non_negative"),
        CheckConstraint("amount_inr > 0", name="amount_positive"),
        CheckConstraint("monthly_cap_inr >= amount_inr", name="cap_covers_one_charge"),
        CheckConstraint(
            f"mandate_method IS NULL OR mandate_method IN {MANDATE_METHODS!r}",
            name="method_enum",
        ),
        CheckConstraint(f"mandate_status IN {MANDATE_STATUSES!r}", name="mandate_status_enum"),
        # Charging needs a confirmed token; the switch cannot be on without one.
        CheckConstraint(
            "NOT enabled OR (mandate_status = 'confirmed' AND token_id IS NOT NULL)",
            name="enabled_needs_confirmed_token",
        ),
        CheckConstraint("consecutive_failures >= 0", name="failures_non_negative"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    threshold_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    monthly_cap_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(64))
    token_id: Mapped[str | None] = mapped_column(String(64))
    mandate_method: Mapped[str | None] = mapped_column(String(8))
    mandate_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'none'")
    )
    #: The per-debit ceiling the client authorised (the order's `token.max_amount`).
    mandate_max_inr: Mapped[Decimal | None] = mapped_column(MONEY)
    #: The authorisation order, so `token.*` and `payment.captured` for it can be matched.
    mandate_order_id: Mapped[str | None] = mapped_column(String(64))
    consecutive_failures: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    #: Why the switch was turned off by us rather than by the client, in our own words.
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    #: The member who authorised the mandate. Each recurring charge must carry the
    #: customer's email and phone (`.../upi/create-subsequent-payments.md`), and they are
    #: read from this user at charge time rather than copied here.
    authorised_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AutoRechargeCharge(PKMixin, TimestampMixin, Base):
    """One recharge we started against a client's mandate."""

    __tablename__ = "auto_recharge_charges"
    __table_args__ = (
        CheckConstraint("amount_inr > 0", name="amount_positive"),
        CheckConstraint(f"status IN {CHARGE_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            "(status = 'pending') = (settled_at IS NULL)", name="settled_iff_not_pending"
        ),
        # ONE RECHARGE IN FLIGHT PER TENANT. Razorpay: "Do not create another subsequent
        # payment until you get the status of the previous one"
        # (`api/payments/recurring-payments/upi/create-subsequent-payments.md`, 9 Oct 2026).
        Index(
            "ux_auto_recharge_charges_one_pending",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_auto_recharge_charges_tenant_recent", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payment_id: Mapped[str | None] = mapped_column(String(64))
    amount_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Razorpay's error CODE on a failure (a short machine token, never its prose).
    failure_code: Mapped[str | None] = mapped_column(String(64))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentDispute(PKMixin, TimestampMixin, Base):
    """One chargeback or dispute raised against a client's payment."""

    __tablename__ = "payment_disputes"
    __table_args__ = (
        CheckConstraint("amount_inr > 0", name="amount_positive"),
        CheckConstraint("hold_inr >= 0", name="hold_non_negative"),
        CheckConstraint(f"status IN {DISPUTE_STATUSES!r}", name="status_enum"),
        Index("ix_payment_disputes_tenant_recent", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    dispute_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(24))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    respond_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The credit held against this dispute (a compensating `adjustment` on the ledger).
    hold_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    #: True after `payment.dispute.action_required`, until the next contest.
    action_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: The last webhook event applied, for the admin page.
    last_event: Mapped[str | None] = mapped_column(String(48))


__all__ = [
    "CHARGE_STATUSES",
    "DISPUTE_STATUSES",
    "MANDATE_METHODS",
    "MANDATE_STATUSES",
    "ROUTE_KINDS",
    "ROUTE_PURPOSES",
    "AutoRechargeCharge",
    "AutoRechargeSettings",
    "PaymentDispute",
    "RazorpayObjectRoute",
]
