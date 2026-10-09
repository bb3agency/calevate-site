"""Auto-recharge: notify, then charge a mandate the client authorised once (D-699).

THE FLOW
--------
1. The client opts in with a threshold, a recharge amount and a monthly cap, and
   authorises a payment method ONCE: UPI Autopay or a card mandate, through Razorpay
   Recurring Payments — a customer, an authorisation order carrying a `token` block, then
   Checkout with `recurring: "1"` (`api/payments/recurring-payments/upi/
   create-authorization-transaction.md`, `.../cards/create-authorization-transaction.md`,
   read 9 Oct 2026). The ₹1 authorisation payment is credited like any top-up.
2. `token.confirmed` makes the mandate usable; `token.rejected`, `token.cancelled` and
   `token.paused` switch auto-recharge off with a message to the client.
3. A sweep (`apps/workers/auto_recharge.py`, every five minutes) finds a wallet below its
   threshold and starts ONE recharge: it tells the client first (an email, through the
   outbox), then creates a charge order and the recurring payment. We send no
   `notification` object, so Razorpay sends the regulatory pre-debit notification itself
   and debits 25 hours (UPI) or 36 hours 5 minutes (cards) after it is delivered, retrying
   a failed debit itself (`.../create-subsequent-payments.md`). The threshold therefore has
   to cover more than a day of calling; the settings screen says so.
4. The capture arrives as an ordinary `payment.captured` and is credited by
   `payments.credit_captured_payment` (the ONE credit path, which also calls the first-
   payment hook). `settle_charge` closes the charge row in the same transaction.

THE RULES THE FOUNDER SET, AND WHERE EACH IS ENFORCED
-----------------------------------------------------
- Outbound keeps running and inbound is never affected: nothing here gates a call.
- Store only Razorpay customer and token ids: `auto_recharge_settings` has no card or UPI
  column; the token list Razorpay returns (which carries a VPA) is read for its status only.
- Every charge is audited (`auto_recharge.charge_*`).
- The monthly cap is hard: `_month_spent` + the amount must fit, counted over pending and
  captured charges in the IST month, under a row lock on the settings.
- No double charge: `ux_auto_recharge_charges_one_pending` admits one pending charge per
  tenant, and Razorpay asks for exactly that ("Do not create another subsequent payment
  until you get the status of the previous one").
- Failures: the client is told each time; after `auto_recharge_max_failures` in a row the
  switch goes off with a clear message.
- Per-debit limit: ₹15,000 without an additional factor of authentication, for cards and
  UPI alike (`razorpay_api.MANDATE_MAX_DEBIT_INR`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.payment_objects import AUTO_RECHARGE, MANDATE, record_route
from apps.api.billing.payments import NOTES_TENANT_KEY, verify_checkout_signature
from apps.api.billing.plans import ist_billing_month, ist_month_window
from apps.api.billing.razorpay_api import (
    MANDATE_AUTH_AMOUNT_INR,
    MANDATE_MAX_DEBIT_INR,
    MANDATE_YEARS,
    MandateMethod,
    razorpay_api,
)
from apps.api.billing.service import get_balance, to_paise
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session, user_session
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

#: The outbox job that emails a client about a payment event (`apps/workers/payment_notices`).
PAYMENT_NOTICE_JOB: Final = "send_payment_notice"

NoticeKind = Literal[
    "recharge_started",
    "recharge_captured",
    "recharge_failed",
    "auto_recharge_disabled",
    "mandate_confirmed",
    "mandate_ended",
]

#: A charge Razorpay has not answered after this long is failed by the sweep. UPI can take
#: 24-36 hours to reflect a subsequent payment (`.../upi/create-subsequent-payments.md`);
#: cards debit 36 hours 5 minutes after the pre-debit notification. Three days covers both
#: with a margin, and Razorpay refunds anything it captures later than its own window.
CHARGE_ANSWER_WINDOW: Final = timedelta(days=3)

#: Defaults offered before a client has chosen anything (the founder's examples).
DEFAULT_THRESHOLD_INR: Final = Decimal("500.00")
DEFAULT_AMOUNT_INR: Final = Decimal("2000.00")
DEFAULT_MONTHLY_CAP_INR: Final = Decimal("6000.00")

_TOKEN_STATUS_OF_EVENT: Final = {
    "token.confirmed": "confirmed",
    "token.rejected": "rejected",
    "token.cancelled": "cancelled",
    "token.paused": "paused",
}


@dataclass(frozen=True, slots=True)
class AutoRechargeState:
    enabled: bool
    threshold_inr: Decimal
    amount_inr: Decimal
    monthly_cap_inr: Decimal
    mandate_status: str
    mandate_method: str | None
    mandate_max_inr: Decimal | None
    consecutive_failures: int
    disabled_reason: str | None
    month_charged_inr: Decimal
    pending_charge_inr: Decimal | None
    #: A threshold that covers the ~1.5 days between a recharge starting and the money
    #: landing, from this account's last 14 days of calling; None with no usage yet.
    suggested_threshold_inr: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MandateCheckout:
    """What the browser needs to open the authorisation Checkout."""

    key_id: str
    order_id: str
    customer_id: str
    amount_paise: int
    notes: dict[str, str]


_SETTINGS_COLUMNS = (
    "enabled, threshold_inr, amount_inr, monthly_cap_inr, mandate_status, mandate_method, "
    "mandate_max_inr, consecutive_failures, disabled_reason, customer_id, token_id, "
    "mandate_order_id, authorised_by"
)


async def _settings_row(
    session: AsyncSession, tenant_id: UUID, *, lock: bool = False
) -> Any | None:
    sql = f"SELECT {_SETTINGS_COLUMNS} FROM auto_recharge_settings WHERE tenant_id = :tid"
    if lock:
        sql += " FOR UPDATE"
    return (await session.execute(text(sql), {"tid": tenant_id})).first()


async def _month_spent(session: AsyncSession, tenant_id: UUID, *, at: datetime) -> Decimal:
    start, end = ist_month_window(ist_billing_month(at))
    total = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(amount_inr), 0) FROM auto_recharge_charges "
                "WHERE tenant_id = :tid AND status IN ('pending', 'captured') "
                "AND created_at >= :start AND created_at < :end"
            ),
            {"tid": tenant_id, "start": start, "end": end},
        )
    ).scalar()
    return Decimal(str(total or 0))


#: How long a recharge takes to land: the pre-debit notice, then the debit 25 hours (UPI)
#: or about 24-36 hours (cards) after it (`api/payments/recurring-payments/upi/
#: create-subsequent-payments.md`, `payments/recurring-payments/cards/faqs.md`), so the
#: threshold must carry this many days of calling.
RECHARGE_LAG_DAYS: Final = Decimal("1.5")
_USAGE_WINDOW_DAYS: Final = 14


async def _suggested_threshold(session: AsyncSession, tenant_id: UUID) -> Decimal | None:
    spent = (
        await session.execute(
            text(
                "SELECT COALESCE(-SUM(delta), 0) FROM credit_ledger WHERE tenant_id = :tid "
                "AND reason = 'usage' AND occurred_at >= now() - make_interval(days => :days)"
            ),
            {"tid": tenant_id, "days": _USAGE_WINDOW_DAYS},
        )
    ).scalar()
    daily = Decimal(str(spent or 0)) / _USAGE_WINDOW_DAYS
    if daily <= 0:
        return None
    # Rounded UP to the next ₹100, so the suggestion is a number a person would type.
    hundreds = (daily * RECHARGE_LAG_DAYS / 100).to_integral_value(rounding=ROUND_CEILING)
    return to_paise(max(hundreds * 100, Decimal("100")))


async def read_auto_recharge(session: AsyncSession, *, tenant_id: UUID) -> AutoRechargeState:
    """The client's settings and mandate, or the defaults when they have none yet."""
    suggested = await _suggested_threshold(session, tenant_id)
    row = await _settings_row(session, tenant_id)
    pending = (
        await session.execute(
            text(
                "SELECT amount_inr FROM auto_recharge_charges "
                "WHERE tenant_id = :tid AND status = 'pending'"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    spent = await _month_spent(session, tenant_id, at=datetime.now(UTC))
    if row is None:
        return AutoRechargeState(
            enabled=False,
            threshold_inr=DEFAULT_THRESHOLD_INR,
            amount_inr=DEFAULT_AMOUNT_INR,
            monthly_cap_inr=DEFAULT_MONTHLY_CAP_INR,
            mandate_status="none",
            mandate_method=None,
            mandate_max_inr=None,
            consecutive_failures=0,
            disabled_reason=None,
            month_charged_inr=to_paise(spent),
            pending_charge_inr=None,
            suggested_threshold_inr=suggested,
        )
    return AutoRechargeState(
        enabled=bool(row.enabled),
        threshold_inr=to_paise(Decimal(str(row.threshold_inr))),
        amount_inr=to_paise(Decimal(str(row.amount_inr))),
        monthly_cap_inr=to_paise(Decimal(str(row.monthly_cap_inr))),
        mandate_status=str(row.mandate_status),
        mandate_method=row.mandate_method,
        mandate_max_inr=(
            None if row.mandate_max_inr is None else to_paise(Decimal(str(row.mandate_max_inr)))
        ),
        consecutive_failures=int(row.consecutive_failures),
        disabled_reason=row.disabled_reason,
        month_charged_inr=to_paise(spent),
        pending_charge_inr=None if pending is None else to_paise(Decimal(str(pending))),
        suggested_threshold_inr=suggested,
    )


def _validate(threshold: Decimal, amount: Decimal, cap: Decimal) -> None:
    from apps.api.billing.payment_routes import MAX_TOPUP_INR, MIN_TOPUP_INR

    if threshold < 0:
        raise ProblemError.business_rule(
            "auto_recharge_invalid",
            "The low-balance threshold cannot be negative.",
            remediation="Enter ₹0 or more.",
        )
    ceiling = min(MAX_TOPUP_INR, MANDATE_MAX_DEBIT_INR)
    if amount < MIN_TOPUP_INR or amount > ceiling:
        raise ProblemError.business_rule(
            "auto_recharge_invalid",
            f"A recharge is between ₹{MIN_TOPUP_INR:,.0f} and ₹{ceiling:,.0f}.",
            remediation=(
                "Automatic payments above ₹15,000 need you to approve each one, so they "
                "cannot run unattended."
            ),
        )
    if cap < amount:
        raise ProblemError.business_rule(
            "auto_recharge_invalid",
            "The monthly limit must be at least one recharge.",
            remediation="Raise the monthly limit or lower the recharge amount.",
        )


async def save_auto_recharge(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    enabled: bool,
    threshold_inr: Decimal,
    amount_inr: Decimal,
    monthly_cap_inr: Decimal,
    actor_user_id: UUID | None,
    ip: str | None = None,
) -> AutoRechargeState:
    """Upsert the client's preferences. Turning it ON needs a confirmed mandate whose
    per-debit limit covers the amount."""
    _validate(threshold_inr, amount_inr, monthly_cap_inr)
    row = await _settings_row(session, tenant_id, lock=True)
    if enabled:
        if row is None or row.mandate_status != "confirmed" or row.token_id is None:
            raise ProblemError.business_rule(
                "auto_recharge_needs_mandate",
                "Set up an automatic payment method before turning auto-recharge on.",
                remediation="Choose UPI Autopay or a card and approve it once.",
            )
        if row.mandate_max_inr is not None and amount_inr > Decimal(str(row.mandate_max_inr)):
            raise ProblemError.business_rule(
                "auto_recharge_over_mandate",
                f"Your approved limit is ₹{to_paise(Decimal(str(row.mandate_max_inr)))} per "
                "payment.",
                remediation="Lower the recharge amount, or approve a new payment method.",
            )
    await session.execute(
        text(
            "INSERT INTO auto_recharge_settings (id, tenant_id, enabled, threshold_inr, "
            "amount_inr, monthly_cap_inr) VALUES (:id, :tid, :en, :th, :amt, :cap) "
            "ON CONFLICT (tenant_id) DO UPDATE SET enabled = EXCLUDED.enabled, "
            "threshold_inr = EXCLUDED.threshold_inr, amount_inr = EXCLUDED.amount_inr, "
            "monthly_cap_inr = EXCLUDED.monthly_cap_inr, "
            "consecutive_failures = CASE WHEN EXCLUDED.enabled "
            "THEN 0 ELSE auto_recharge_settings.consecutive_failures END, "
            "disabled_reason = CASE WHEN EXCLUDED.enabled THEN NULL "
            "ELSE auto_recharge_settings.disabled_reason END, updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "en": enabled,
            "th": threshold_inr,
            "amt": amount_inr,
            "cap": monthly_cap_inr,
        },
    )
    await write_audit(
        session,
        action="auto_recharge.settings",
        actor_type="user",
        tenant_id=tenant_id,
        object_type="auto_recharge_settings",
        object_id=str(tenant_id),
        ip=ip,
        summary={
            "enabled": str(enabled),
            "threshold_inr": str(to_paise(threshold_inr)),
            "amount_inr": str(to_paise(amount_inr)),
            "monthly_cap_inr": str(to_paise(monthly_cap_inr)),
            "by": str(actor_user_id) if actor_user_id else None,
        },
    )
    return await read_auto_recharge(session, tenant_id=tenant_id)


async def _payer_contact(user_id: UUID) -> tuple[str, str, str]:
    """(name, email, phone) of the member authorising, as Razorpay requires them."""
    async with user_session(user_id) as session:
        row = (
            await session.execute(
                text("SELECT name, email, phone FROM users WHERE id = :uid"), {"uid": user_id}
            )
        ).first()
    if row is None or not row.email or not row.phone:
        raise ProblemError.business_rule(
            "auto_recharge_needs_contact",
            "Automatic payments need your email address and mobile number.",
            remediation="Add a mobile number to your profile, then try again.",
        )
    return (str(row.name or row.email), str(row.email), str(row.phone))


async def begin_mandate(
    *,
    tenant_id: UUID,
    user_id: UUID,
    method: MandateMethod,
    max_debit_inr: Decimal,
    ip: str | None = None,
) -> MandateCheckout:
    """Create (or reuse) the Razorpay customer and the authorisation order.

    No database session is held across the provider calls (BACKEND-PATTERNS §5): read,
    call, then write.
    """
    from apps.api.billing.payment_routes import MIN_TOPUP_INR

    if max_debit_inr < MIN_TOPUP_INR or max_debit_inr > MANDATE_MAX_DEBIT_INR:
        raise ProblemError.business_rule(
            "auto_recharge_invalid",
            f"The per-payment limit is between ₹{MIN_TOPUP_INR:,.0f} and ₹15,000.",
            remediation="Choose the largest single recharge you want to allow.",
        )
    async with tenant_session(tenant_id) as session:
        row = await _settings_row(session, tenant_id)
    name, email, phone = await _payer_contact(user_id)
    api = razorpay_api()
    notes = {NOTES_TENANT_KEY: str(tenant_id), "calevate_purpose": MANDATE}
    customer_id = row.customer_id if row is not None and row.customer_id else None
    if customer_id is None:
        customer_id = await api.create_customer(
            name=name, email=email, contact=phone, notes={NOTES_TENANT_KEY: str(tenant_id)}
        )
    expire_at = int((datetime.now(UTC) + timedelta(days=365 * MANDATE_YEARS)).timestamp())
    receipt = f"clvm_{uuid7().hex[:30]}"
    order_id = await api.create_mandate_order(
        customer_id=customer_id,
        method=method,
        max_debit_inr=max_debit_inr,
        expire_at=expire_at,
        receipt=receipt,
        notes=notes,
    )
    async with tenant_session(tenant_id) as session:
        await record_route(session, tenant_id=tenant_id, object_id=customer_id, kind="customer")
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose=MANDATE,
            amount_inr=MANDATE_AUTH_AMOUNT_INR,
        )
        await session.execute(
            text(
                "INSERT INTO auto_recharge_settings (id, tenant_id, enabled, threshold_inr, "
                "amount_inr, monthly_cap_inr, customer_id, mandate_method, mandate_status, "
                "mandate_max_inr, mandate_order_id, authorised_by) VALUES (:id, :tid, false, "
                ":th, :amt, :cap, :cust, :method, 'pending', :max, :order, :uid) "
                "ON CONFLICT (tenant_id) DO UPDATE SET enabled = false, "
                "customer_id = EXCLUDED.customer_id, mandate_method = EXCLUDED.mandate_method, "
                "mandate_status = 'pending', token_id = NULL, "
                "mandate_max_inr = EXCLUDED.mandate_max_inr, "
                "mandate_order_id = EXCLUDED.mandate_order_id, "
                "authorised_by = EXCLUDED.authorised_by, updated_at = now()"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "th": DEFAULT_THRESHOLD_INR,
                "amt": min(DEFAULT_AMOUNT_INR, max_debit_inr),
                "cap": max(DEFAULT_MONTHLY_CAP_INR, max_debit_inr),
                "cust": customer_id,
                "method": method,
                "max": max_debit_inr,
                "order": order_id,
                "uid": user_id,
            },
        )
        await write_audit(
            session,
            action="auto_recharge.mandate_started",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="auto_recharge_settings",
            object_id=order_id,
            ip=ip,
            summary={"method": method, "max_debit_inr": str(to_paise(max_debit_inr))},
        )
    key_id = get_settings().razorpay_key_id
    assert key_id is not None
    return MandateCheckout(
        key_id=key_id,
        order_id=order_id,
        customer_id=customer_id,
        amount_paise=int(MANDATE_AUTH_AMOUNT_INR * 100),
        notes=notes,
    )


async def confirm_mandate(
    *, tenant_id: UUID, order_id: str, payment_id: str, signature: str
) -> AutoRechargeState:
    """The browser's return from the authorisation Checkout.

    The signature is checked against OUR mandate order id (not the one the browser echoes),
    then the payment is read back for its `token_id` (`api/payments/fetch-with-id.md`). The
    mandate stays `pending` until `token.confirmed`, or until the sweep reads the token's
    status itself.
    """
    from apps.api.billing.payments import razorpay_api_secret

    async with tenant_session(tenant_id) as session:
        row = await _settings_row(session, tenant_id)
    secret = razorpay_api_secret()
    if (
        row is None
        or row.mandate_order_id != order_id
        or secret is None
        or not verify_checkout_signature(
            key_secret=secret, order_id=order_id, payment_id=payment_id, signature=signature
        )
    ):
        raise ProblemError(
            kind="auth",
            code="payment_signature_invalid",
            title="Payment could not be verified",
            detail="We could not confirm this approval was genuine.",
            remediation="Start the set-up again. Contact us if you were charged.",
        )
    payment = await razorpay_api().fetch_payment(payment_id)
    async with tenant_session(tenant_id) as session:
        if payment.token_id:
            await _remember_token(session, tenant_id=tenant_id, token_id=payment.token_id)
        state = await read_auto_recharge(session, tenant_id=tenant_id)
    return state


async def _remember_token(session: AsyncSession, *, tenant_id: UUID, token_id: str) -> None:
    await record_route(session, tenant_id=tenant_id, object_id=token_id, kind="token")
    await session.execute(
        text(
            "UPDATE auto_recharge_settings SET token_id = :tok, updated_at = now() "
            "WHERE tenant_id = :tid AND (token_id IS NULL OR token_id = :tok)"
        ),
        {"tid": tenant_id, "tok": token_id},
    )


async def note_mandate_payment(
    session: AsyncSession, *, tenant_id: UUID, order_id: str, token_id: str | None
) -> None:
    """A captured payment against the mandate's authorisation order: keep its token."""
    row = await _settings_row(session, tenant_id)
    if row is None or row.mandate_order_id != order_id or not token_id:
        return
    await _remember_token(session, tenant_id=tenant_id, token_id=token_id)


async def apply_token_status(
    session: AsyncSession, *, tenant_id: UUID, token_id: str, status: str
) -> bool:
    """Move the mandate to Razorpay's token state. Any state but `confirmed` turns
    auto-recharge off; a confirmed mandate is NOT switched on (the client does that).
    Returns True when the state changed."""
    if status == "initiated":
        status = "pending"
    changed = (
        await session.execute(
            text(
                "UPDATE auto_recharge_settings SET mandate_status = CAST(:st AS varchar), "
                "enabled = CASE WHEN CAST(:st AS text) = 'confirmed' THEN enabled ELSE false END, "
                "disabled_reason = CASE WHEN CAST(:st AS text) IN ('confirmed', 'pending') "
                "THEN disabled_reason ELSE CAST(:reason AS text) END, updated_at = now() "
                "WHERE tenant_id = :tid AND token_id = :tok "
                "AND mandate_status <> CAST(:st AS varchar) "
                "RETURNING id"
            ),
            {
                "st": status,
                "tid": tenant_id,
                "tok": token_id,
                "reason": _ENDED_REASON.get(status),
            },
        )
    ).first()
    if changed is None:
        return False
    await write_audit(
        session,
        action="auto_recharge.mandate_status",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="auto_recharge_settings",
        object_id=token_id,
        summary={"status": status},
    )
    if status == "confirmed":
        await _notice(session, tenant_id, "mandate_confirmed")
    elif status != "pending":
        await _notice(session, tenant_id, "mandate_ended", reason=_ENDED_REASON.get(status))
    return True


_ENDED_REASON: Final = {
    "rejected": "Your bank or UPI app did not approve the automatic payment.",
    "cancelled": "The automatic payment approval was cancelled.",
    "paused": "The automatic payment approval was paused in your UPI app.",
}


def token_status_of_event(event: str) -> str | None:
    return _TOKEN_STATUS_OF_EVENT.get(event)


async def cancel_mandate(
    *, tenant_id: UUID, actor_user_id: UUID | None, ip: str | None = None
) -> AutoRechargeState:
    """The client withdraws the mandate: Razorpay first, then our row."""
    async with tenant_session(tenant_id) as session:
        row = await _settings_row(session, tenant_id)
    if row is None or row.token_id is None or row.customer_id is None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE auto_recharge_settings SET enabled = false, mandate_status = 'none', "
                    "updated_at = now() WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
            return await read_auto_recharge(session, tenant_id=tenant_id)
    method: MandateMethod = "card" if row.mandate_method == "card" else "upi"
    await razorpay_api().cancel_token(
        customer_id=row.customer_id, token_id=row.token_id, method=method
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE auto_recharge_settings SET enabled = false, mandate_status = 'cancelled', "
                "disabled_reason = NULL, updated_at = now() WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        await write_audit(
            session,
            action="auto_recharge.mandate_cancelled",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="auto_recharge_settings",
            object_id=row.token_id,
            ip=ip,
            summary={"by": str(actor_user_id) if actor_user_id else None},
        )
        return await read_auto_recharge(session, tenant_id=tenant_id)


async def _notice(
    session: AsyncSession,
    tenant_id: UUID,
    kind: NoticeKind,
    *,
    amount_inr: Decimal | None = None,
    reason: str | None = None,
) -> None:
    await enqueue_outbox(
        session,
        job=PAYMENT_NOTICE_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "kind": kind,
            "amount_inr": None if amount_inr is None else str(to_paise(amount_inr)),
            "reason": reason,
        },
    )


# --- the charge -------------------------------------------------------------------------


async def due_tenants() -> list[UUID]:
    """Tenants with auto-recharge on, read untenanted through the ops-read policy."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id FROM auto_recharge_settings WHERE enabled ORDER BY tenant_id"
                )
            )
        ).all()
    return [UUID(str(r[0])) for r in rows]


async def maybe_start_recharge(tenant_id: UUID) -> str:
    """Start one recharge if this wallet is below its threshold. Returns the outcome.

    Claim first (one transaction: the pending row, the notice, the audit), then the
    provider calls with no session held, then the order and payment ids. A provider
    failure fails the claim and counts against the switch.
    """
    claim_id = uuid7()
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        row = await _settings_row(session, tenant_id, lock=True)
        if row is None or not row.enabled or row.token_id is None:
            return "off"
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        if balance >= Decimal(str(row.threshold_inr)):
            return "above_threshold"
        amount = Decimal(str(row.amount_inr))
        if await _month_spent(session, tenant_id, at=now) + amount > Decimal(
            str(row.monthly_cap_inr)
        ):
            return "monthly_cap_reached"
        claimed = (
            await session.execute(
                text(
                    "INSERT INTO auto_recharge_charges (id, tenant_id, order_id, amount_inr, "
                    "status) VALUES (:id, :tid, :placeholder, :amt, 'pending') "
                    "ON CONFLICT (tenant_id) WHERE status = 'pending' DO NOTHING RETURNING id"
                ),
                {
                    "id": claim_id,
                    "tid": tenant_id,
                    "placeholder": f"claim:{claim_id}",
                    "amt": amount,
                },
            )
        ).first()
        if claimed is None:
            return "in_flight"
        await _notice(session, tenant_id, "recharge_started", amount_inr=amount)
        await write_audit(
            session,
            action="auto_recharge.charge_started",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="auto_recharge_charges",
            object_id=str(claim_id),
            summary={
                "amount_inr": str(to_paise(amount)),
                "balance_inr": str(to_paise(balance)),
                "threshold_inr": str(to_paise(Decimal(str(row.threshold_inr)))),
            },
        )
        customer_id, token_id, payer = row.customer_id, row.token_id, row.authorised_by

    try:
        if payer is None:
            raise ProblemError.business_rule(
                "auto_recharge_needs_contact",
                "The member who approved automatic payments is no longer on this account.",
                remediation="Approve the payment method again.",
            )
        _, email, phone = await _payer_contact(UUID(str(payer)))
        api = razorpay_api()
        notes = {NOTES_TENANT_KEY: str(tenant_id), "calevate_purpose": AUTO_RECHARGE}
        order_id = await api.create_charge_order(
            amount_inr=amount, receipt=f"clva_{claim_id.hex[:30]}", notes=notes
        )
        async with tenant_session(tenant_id) as session:
            await record_route(
                session,
                tenant_id=tenant_id,
                object_id=order_id,
                kind="order",
                purpose=AUTO_RECHARGE,
                amount_inr=amount,
            )
            await session.execute(
                text(
                    "UPDATE auto_recharge_charges SET order_id = :oid, updated_at = now() "
                    "WHERE id = :id"
                ),
                {"oid": order_id, "id": claim_id},
            )
        payment_id = await api.create_recurring_payment(
            email=email,
            contact=phone,
            amount_inr=amount,
            order_id=order_id,
            customer_id=str(customer_id),
            token_id=str(token_id),
            notes=notes,
        )
    except ProblemError as exc:
        async with tenant_session(tenant_id) as session:
            await _fail_charge(session, tenant_id=tenant_id, charge_id=claim_id, code=exc.code)
        return "failed"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE auto_recharge_charges SET payment_id = :pid, updated_at = now() "
                "WHERE id = :id AND status = 'pending'"
            ),
            {"pid": payment_id, "id": claim_id},
        )
    log.info("auto_recharge_started", extra={"tenant_id": str(tenant_id), "payment_id": payment_id})
    return "started"


async def _fail_charge(
    session: AsyncSession, *, tenant_id: UUID, charge_id: UUID, code: str | None
) -> None:
    updated = (
        await session.execute(
            text(
                "UPDATE auto_recharge_charges SET status = 'failed', failure_code = :code, "
                "settled_at = now(), updated_at = now() "
                "WHERE id = :id AND status = 'pending' RETURNING amount_inr"
            ),
            {"id": charge_id, "code": (code or "unknown")[:64]},
        )
    ).first()
    if updated is None:
        return
    amount = Decimal(str(updated[0]))
    limit = get_settings().auto_recharge_max_failures
    counted = (
        await session.execute(
            text(
                "UPDATE auto_recharge_settings "
                "SET consecutive_failures = consecutive_failures + 1, "
                "enabled = CASE WHEN consecutive_failures + 1 >= :limit "
                "THEN false ELSE enabled END, "
                "disabled_reason = CASE WHEN consecutive_failures + 1 >= :limit THEN :reason "
                "ELSE disabled_reason END, updated_at = now() "
                "WHERE tenant_id = :tid RETURNING consecutive_failures, enabled"
            ),
            {"tid": tenant_id, "limit": limit, "reason": _DISABLED_REASON},
        )
    ).first()
    await write_audit(
        session,
        action="auto_recharge.charge_failed",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="auto_recharge_charges",
        object_id=str(charge_id),
        summary={"amount_inr": str(to_paise(amount)), "failure_code": code},
    )
    await _notice(session, tenant_id, "recharge_failed", amount_inr=amount)
    if counted is not None and not counted.enabled and int(counted.consecutive_failures) >= limit:
        await _notice(session, tenant_id, "auto_recharge_disabled", reason=_DISABLED_REASON)
        alert("WORKER_DELIVERY", "auto_recharge_disabled", tenant_id=str(tenant_id))


_DISABLED_REASON: Final = (
    "Auto-recharge is off because the last automatic payments did not go through."
)


async def settle_charge(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    order_id: str,
    payment_id: str | None,
    captured: bool,
    failure_code: str | None = None,
) -> None:
    """Close the charge behind an `auto_recharge` order: captured or failed. Called by the
    webhook in the transaction that credits (or marks) the payment."""
    row = (
        await session.execute(
            text(
                "SELECT id, amount_inr FROM auto_recharge_charges "
                "WHERE tenant_id = :tid AND order_id = :oid AND status = 'pending'"
            ),
            {"tid": tenant_id, "oid": order_id},
        )
    ).first()
    if row is None:
        return
    charge_id = UUID(str(row[0]))
    if not captured:
        await _fail_charge(session, tenant_id=tenant_id, charge_id=charge_id, code=failure_code)
        return
    await session.execute(
        text(
            "UPDATE auto_recharge_charges SET status = 'captured', payment_id = "
            "COALESCE(:pid, payment_id), settled_at = now(), updated_at = now() WHERE id = :id"
        ),
        {"pid": payment_id, "id": charge_id},
    )
    await session.execute(
        text(
            "UPDATE auto_recharge_settings SET consecutive_failures = 0, updated_at = now() "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    await write_audit(
        session,
        action="auto_recharge.charge_captured",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="auto_recharge_charges",
        object_id=str(charge_id),
        summary={"amount_inr": str(to_paise(Decimal(str(row[1])))), "payment_ref": payment_id},
    )
    await _notice(session, tenant_id, "recharge_captured", amount_inr=Decimal(str(row[1])))


async def expire_unanswered(tenant_id: UUID, *, now: datetime | None = None) -> int:
    """Fail charges Razorpay has not answered within `CHARGE_ANSWER_WINDOW`."""
    cutoff = (now or datetime.now(UTC)) - CHARGE_ANSWER_WINDOW
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM auto_recharge_charges WHERE tenant_id = :tid "
                    "AND status = 'pending' AND created_at < :cutoff"
                ),
                {"tid": tenant_id, "cutoff": cutoff},
            )
        ).all()
        for (charge_id,) in rows:
            await _fail_charge(
                session, tenant_id=tenant_id, charge_id=UUID(str(charge_id)), code="no_answer"
            )
    return len(rows)


async def pending_mandates() -> list[tuple[UUID, str, str]]:
    """(tenant, customer, token) of mandates waiting for `token.confirmed`, or paused by the
    client in their UPI app: Razorpay documents no event for a resume, so the sweep reads
    the token's state back (`api/payments/recurring-payments/upi/tokens.md` §2.2), and a
    resumed token reads `confirmed`."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, customer_id, token_id FROM auto_recharge_settings "
                    "WHERE mandate_status IN ('pending', 'paused') AND token_id IS NOT NULL "
                    "AND customer_id IS NOT NULL ORDER BY tenant_id"
                )
            )
        ).all()
    return [(UUID(str(r[0])), str(r[1]), str(r[2])) for r in rows]


async def refresh_pending_mandate(tenant_id: UUID, customer_id: str, token_id: str) -> str | None:
    """Read a pending token's state from Razorpay, for a lost `token.*` webhook."""
    status = await razorpay_api().token_status(customer_id=customer_id, token_id=token_id)
    if status is None or status == "initiated":
        return status
    async with tenant_session(tenant_id) as session:
        await apply_token_status(session, tenant_id=tenant_id, token_id=token_id, status=status)
    return status


__all__ = [
    "CHARGE_ANSWER_WINDOW",
    "PAYMENT_NOTICE_JOB",
    "AutoRechargeState",
    "MandateCheckout",
    "NoticeKind",
    "apply_token_status",
    "begin_mandate",
    "cancel_mandate",
    "confirm_mandate",
    "due_tenants",
    "expire_unanswered",
    "maybe_start_recharge",
    "note_mandate_payment",
    "pending_mandates",
    "read_auto_recharge",
    "refresh_pending_mandate",
    "save_auto_recharge",
    "settle_charge",
    "token_status_of_event",
]
