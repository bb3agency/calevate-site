"""Razorpay prepaid top-ups — the half of the integration that is OURS (D-34).

The self-serve motion needs a way to pay that does not involve someone in ops reading
a UTR off a bank statement (`billing/credit_routes.py`, which stays exactly as it is
for NEFT/UPI). This module is the machine version of that same act: a payment the
provider tells us about becomes one `credit_ledger` entry.

WHAT IS REAL HERE AND WHAT IS NOT — read this before wiring it to a live account
--------------------------------------------------------------------------------
There are no Razorpay credentials in this repository and no call has ever been made
against their API, so the vendor half of the contract is **unverified**. Rather than
invent it convincingly, everything we cannot check is pushed into two places you can
point a verifier at:

- `verify_signature` — the signing scheme. Implemented as HMAC-SHA256 of the RAW
  request body, hex-encoded, compared against the `X-Razorpay-Signature` header, with
  the dashboard's webhook secret as the key. **UNVERIFIED.** If it is wrong, every
  event is refused (fail-closed), which is the safe direction to be wrong in.
- `extract_captured_payment` — the payload shape: `event`, and
  `payload.payment.entity.{id,amount,currency,notes}` with `amount` an integer count
  of PAISE. **UNVERIFIED.** If a field name is wrong the extractor returns nothing we
  can act on and the receiver answers 422 without touching the ledger — a loud,
  obviously-unfinished integration rather than a plausible-looking wrong one.

What is NOT implemented at all: creating the order. That is a server-to-server POST
with a key id and secret we do not have, so `payment_routes.create_topup_intent`
returns `provider_order_id: null` and says so, instead of returning a fabricated id
that a frontend would hand to a checkout widget.

WHAT IS OURS, AND IS FINISHED
-----------------------------
- **Idempotency on the provider's payment id.** Every payment provider replays: on
  their retry schedule, on our 5xx, and on a manual redelivery from their dashboard.
  The permanent key for "this money arrived once" is the payment id, so it is the
  ledger's `ref` — the same argument `credit_routes` makes about a bank UTR, and the
  same one `charge_for_call` makes about a call id. A `webhook_inbox_events` claim
  sits in front of it as a cheap first line, but the inbox is not the guarantee: it is
  keyed per delivery and can be swept, while a ledger row is forever.
- **The lock is taken before the lookup.** `lock_tenant_credits` covers the whole
  check-then-write, because two concurrent deliveries of one payment would otherwise
  both read "not credited yet" and both append (billing/service.py's module docstring
  spells out why a row lock is not a substitute).
- **`record_entry` is the only writer.** No hand-rolled INSERT: append-only,
  balance-carrying and audited is a property of that function, not of this one.
- **Money is Decimal end to end** (hard rule 7). Paise arrive as an integer and are
  divided by an integer 100 in Decimal arithmetic, which is exact. A float anywhere on
  that path is refused, never rounded.

Deliberately NOT here: a `payment_orders` table. D-39's rule is that anything needing
a migration later is built now — and this flow needs no such row. The intent is
stateless (it mints a receipt and echoes the notes), the signature proves the callback
is genuine, the notes carry the tenant, and the ledger is the durable record. Adding a
table would add a second place a payment can be half-recorded.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.service import Balance, get_balance, lock_tenant_credits, record_entry
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

PROVIDER: Final = "razorpay"

# UNVERIFIED (see module docstring): the header Razorpay is understood to sign with.
SIGNATURE_HEADER: Final = "X-Razorpay-Signature"

# The only event that moves money. Authorizations, refunds and order events are ACKed
# and ignored — an ack stops the provider retrying, and ignoring is what we would do
# with them anyway until there is a decision-log entry saying otherwise.
CAPTURED_EVENT: Final = "payment.captured"

# The key our checkout attaches to the order's `notes`, carrying the tenant through
# the provider and back. It is prefixed because `notes` is a shared free-form map.
NOTES_TENANT_KEY: Final = "calevate_tenant_id"

# The ledger is INR (hard rule 7). A payment in any other currency is refused rather
# than converted: an fx rate applied at credit time is a number nobody can reproduce.
SUPPORTED_CURRENCY: Final = "INR"

PAISE_PER_RUPEE: Final = Decimal(100)


@dataclass(frozen=True, slots=True)
class CapturedPayment:
    """OUR normalized shape. Nothing downstream of `extract_captured_payment` sees a
    vendor payload — the same discipline hard rule 2 imposes on the voice engine,
    applied here because a payment provider is just as replaceable."""

    payment_id: str
    tenant_id: UUID
    amount_inr: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class TopUpResult:
    entry_id: UUID
    balance: Balance
    # False = this payment id was already on the ledger and nothing moved.
    recorded: bool


def verify_signature(*, secret: str, body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 over the RAW body, hex, constant-time compared.

    UNVERIFIED against a live Razorpay account (module docstring). Two properties hold
    regardless of whether the scheme is right:

    - the comparison is `hmac.compare_digest`, so a wrong signature leaks no timing
      information about how much of it was right;
    - the body is the bytes as received. Re-serializing parsed JSON to verify it would
      compare a signature against something the sender never signed, and would pass or
      fail on key order.
    """
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.strip(), expected)


def paise_to_inr(amount: Any) -> Decimal:
    """An integer count of paise → rupees, exactly.

    `Decimal(int) / Decimal(100)` is exact for every paise value; `amount / 100` on a
    float is not, and `Decimal(float)` would import the error rather than reject it.
    So a non-integer amount is REFUSED (hard rule 7) — including a JSON float that
    happens to look whole, because by the time we see it the damage has been done.

    `bool` is checked before `int` on purpose: `True` is an `int` in Python and would
    otherwise credit one paisa.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ProblemError.business_rule(
            "payment_amount_unrecognized",
            "The captured amount was not an integer number of paise.",
            remediation="A payment amount must arrive as an integer; nothing was credited.",
        )
    if amount <= 0:
        raise ProblemError.business_rule(
            "payment_amount_unrecognized",
            "The captured amount was not a positive number of paise.",
            remediation="A refund is a compensating entry, never a negative top-up.",
        )
    return Decimal(amount) / PAISE_PER_RUPEE


def event_name(envelope: Any) -> str:
    """UNVERIFIED field: the top-level `event` string."""
    if not isinstance(envelope, dict):
        return ""
    value = envelope.get("event")
    return value if isinstance(value, str) else ""


def extract_captured_payment(envelope: Any) -> CapturedPayment:
    """Vendor envelope → `CapturedPayment`, or a refusal that credits nothing.

    EVERY field path read here is UNVERIFIED (module docstring). They are all read in
    this one function so that verifying the contract against a real account is a
    single-function change, and so that being wrong is visible: a missing or oddly
    shaped field produces `payment_payload_unrecognized`, never a guess and never a
    partial credit.
    """
    entity: Any = None
    if isinstance(envelope, dict):
        payload = envelope.get("payload")
        if isinstance(payload, dict):
            payment = payload.get("payment")
            if isinstance(payment, dict):
                entity = payment.get("entity")
    if not isinstance(entity, dict):
        raise ProblemError.business_rule(
            "payment_payload_unrecognized",
            "This payment event did not match the shape this deployment can read.",
            remediation="Nothing was credited. Check the provider's payload contract.",
        )

    payment_id = entity.get("id")
    if not isinstance(payment_id, str) or not payment_id.strip():
        raise ProblemError.business_rule(
            "payment_payload_unrecognized",
            "This payment event carried no payment identifier.",
            remediation="Nothing was credited: the identifier is what makes a credit idempotent.",
        )

    currency = entity.get("currency")
    if not isinstance(currency, str) or currency.upper() != SUPPORTED_CURRENCY:
        raise ProblemError.business_rule(
            "payment_currency_unsupported",
            "This account settles in Indian rupees only.",
            remediation="Nothing was credited. A non-INR payment needs a manual adjustment.",
        )

    amount_inr = paise_to_inr(entity.get("amount"))

    notes = entity.get("notes")
    raw_tenant = notes.get(NOTES_TENANT_KEY) if isinstance(notes, dict) else None
    try:
        tenant_id = UUID(str(raw_tenant))
    except (TypeError, ValueError) as exc:
        # The tenant is the ONE fact the provider cannot supply on its own — our
        # checkout puts it in `notes`. Without it a payment is real money we cannot
        # attribute, which is an ops problem, not a wallet to guess at.
        raise ProblemError.business_rule(
            "payment_tenant_unresolved",
            "This payment did not say which account it was for.",
            remediation=(
                "Nothing was credited. Record it manually against the right account "
                "once the payer is identified."
            ),
        ) from exc

    return CapturedPayment(
        payment_id=payment_id.strip(),
        tenant_id=tenant_id,
        amount_inr=amount_inr,
        currency=SUPPORTED_CURRENCY,
    )


async def tenant_exists(session: AsyncSession, tenant_id: UUID) -> bool:
    found = (
        await session.execute(
            text("SELECT 1 FROM organizations WHERE id = :tid AND deleted_at IS NULL"),
            {"tid": tenant_id},
        )
    ).first()
    return found is not None


async def find_topup(
    session: AsyncSession, *, tenant_id: UUID, ref: str
) -> tuple[UUID, Decimal] | None:
    """The idempotency lookup: has this payment reference already been credited?

    Scoped to `reason = 'topup'` so a payment id can never collide with the call id a
    usage row carries in the same column. (`billing/credit_routes.py` has the same
    query for the manual path; both belong in `billing/service.py` next to
    `record_entry`, which is that file's owner's call to make, not this module's.)
    """
    row = (
        await session.execute(
            text(
                "SELECT id, delta FROM credit_ledger WHERE tenant_id = :tid "
                "AND reason = 'topup' AND ref = :ref ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id, "ref": ref},
        )
    ).first()
    return (UUID(str(row[0])), Decimal(str(row[1]))) if row is not None else None


async def credit_captured_payment(
    session: AsyncSession, *, payment: CapturedPayment, ip: str | None = None
) -> TopUpResult:
    """Put one captured payment on the wallet, exactly once.

    The caller supplies a `tenant_session(payment.tenant_id)` — `credit_ledger`'s RLS
    policy is what isolates this, exactly as on the manual top-up route.

    Order is the whole correctness argument:

    1. `lock_tenant_credits` FIRST, before the lookup. Two deliveries of one payment
       (the provider's retry racing its own first attempt) would otherwise both read
       "not credited" and both append.
    2. the lookup on `ref = payment_id`, which is permanent — unlike an inbox row.
    3. `record_entry`, the only writer, and `write_audit` in the SAME transaction, so
       money that moved without an audit row is not a reachable state.
    """
    await lock_tenant_credits(session, payment.tenant_id)

    existing = await find_topup(session, tenant_id=payment.tenant_id, ref=payment.payment_id)
    if existing is not None:
        entry_id, amount = existing
        if amount != payment.amount_inr:
            # One payment id, two amounts. Absorbing this as a replay would swallow the
            # difference silently; refusing is how anyone finds out.
            raise ProblemError.conflict(
                "payment_amount_conflict",
                "That payment is already on this wallet for a different amount.",
                remediation="Nothing was credited a second time. Reconcile against the provider.",
            )
        log.info(
            "razorpay_topup_replay",
            extra={"tenant_id": str(payment.tenant_id), "entry_id": str(entry_id)},
        )
        return TopUpResult(
            entry_id=entry_id,
            balance=await get_balance(session, tenant_id=payment.tenant_id),
            recorded=False,
        )

    balance = await record_entry(
        session,
        tenant_id=payment.tenant_id,
        delta=payment.amount_inr,
        reason="topup",
        ref=payment.payment_id,
        meta={"source": PROVIDER, "currency": payment.currency},
    )
    written = await find_topup(session, tenant_id=payment.tenant_id, ref=payment.payment_id)
    assert written is not None, "the row was inserted in this transaction"

    await write_audit(
        session,
        action="credit.topup",
        # No human took this action, and naming one would be a lie in the one log that
        # is supposed to be evidence. The provider callback is a system actor.
        actor_type="system",
        tenant_id=payment.tenant_id,
        object_type="credit_ledger",
        object_id=str(written[0]),
        ip=ip,
        summary={
            "source": PROVIDER,
            "payment_ref": payment.payment_id,
            "amount_inr": str(payment.amount_inr),
            "balance_after_inr": str(balance.amount_inr),
        },
    )
    log.info(
        "razorpay_topup_recorded",
        extra={"tenant_id": str(payment.tenant_id), "entry_id": str(written[0])},
    )
    return TopUpResult(entry_id=written[0], balance=balance, recorded=True)


__all__ = [
    "CAPTURED_EVENT",
    "NOTES_TENANT_KEY",
    "PROVIDER",
    "SIGNATURE_HEADER",
    "SUPPORTED_CURRENCY",
    "CapturedPayment",
    "TopUpResult",
    "credit_captured_payment",
    "event_name",
    "extract_captured_payment",
    "find_topup",
    "paise_to_inr",
    "tenant_exists",
    "verify_signature",
]
