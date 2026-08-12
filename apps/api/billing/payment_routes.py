"""Self-serve top-ups: the order intent (client realm) and the payment webhook (machine).

Two surfaces, two routers, because they have nothing in common but the money:

- `router` — `POST /v1/billing/topups/intent`. A client-realm owner says "I want to
  add ₹2,500"; we price it, bind it to their tenant and hand back what a checkout
  needs. Authenticated, permissioned, load-sheddable.
- `webhook_router` — `POST /hooks/v1/razorpay`. The provider says "that payment was
  captured"; we credit the wallet. Under `/hooks` because it shares the webhook
  doctrine with `ingest/routes.py` and `tenancy/clerk_webhooks.py`: never load-shed (a
  payment landing during degraded mode is still a payment), authenticated by a
  signature rather than a session, inbox-deduped, and idempotent on the provider's own
  identifier.

**What is honestly unfinished is marked as such.** There are no Razorpay credentials
here, so the intent does NOT create an order with the provider — it returns
`provider_order_id: null` and a note saying so, rather than a fabricated id. The
signing scheme and payload paths the receiver reads are our best reading of the
provider's contract and are flagged UNVERIFIED in `billing/payments.py`; if they are
wrong, every event is refused and nothing is credited. See that module's docstring.

Permissions. The intent is `org:manage`: spending the client's money is not a read,
and `org:manage` is already in `MUTATING_PERMISSIONS`, so an impersonating admin (D-22)
cannot start a payment on a client's behalf. There is no `billing:write` in the
registry and inventing one for a single route was not worth it — the same call
`credit_routes.py` made in the other direction.

NOT mounted here — the integrator wires both routers into `main.py`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.billing.payments import (
    CAPTURED_EVENT,
    NOTES_TENANT_KEY,
    PROVIDER,
    SIGNATURE_HEADER,
    SUPPORTED_CURRENCY,
    credit_captured_payment,
    event_name,
    extract_captured_payment,
    find_topup,
    payment_capability,
    payments_not_configured,
    tenant_exists,
    verify_signature,
)
from apps.api.billing.service import get_balance, plan_tier_of, to_paise
from apps.api.core.alerting import alert
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability.service import body_hash, claim_inbox_event, mark_inbox_processed

log = get_logger(__name__)

router = APIRouter(prefix="/v1/billing/topups", tags=["billing"])
webhook_router = APIRouter(prefix="/hooks/v1", tags=["billing-webhooks"])

# Annotated dependency rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore.
TopUpWrite = Annotated[Principal, Depends(requires("org:manage", realm="client"))]

# The band a self-serve top-up must fall in. The floor stops the ₹1 test payments that
# cost more in provider fees than they add; the ceiling is a typo guard — ₹100,000 is
# far more talk time than any SMB buys in one go, and a client who wants more can say
# so twice or be invoiced.
MIN_TOPUP_INR = Decimal("100.00")
MAX_TOPUP_INR = Decimal("100000.00")

# Only the prepaid motion has a wallet. A managed client is invoiced against their
# retainer (billing/service.py), so letting them top up would be charging twice.
PREPAID_TIERS = ("self_serve", "trial")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopUpIntentIn(Strict):
    # max_digits/decimal_places mirror the column: MONEY is NUMERIC(12,4), and anything
    # finer than a paisa is a typo.
    amount_inr: Decimal = Field(max_digits=10, decimal_places=2)

    @field_validator("amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        """Hard rule 7 at the boundary, identical to the manual top-up route: `2500.10`
        as a JSON number has already been through a binary float by the time we see it."""
        if isinstance(value, float):
            raise ValueError(
                'money crosses the wire as a string ("2500.00"), never as a JSON float'
            )
        return value


class TopUpIntentOut(Strict):
    tenant_id: UUID
    # Ours, opaque, and carried through the provider so a payment can be traced back
    # to the click that started it. It is NOT the idempotency key — the payment id is.
    receipt: str
    amount_inr: Decimal
    # The provider's unit is an integer count of paise. Published as an integer so the
    # frontend never does this conversion (and never does it in floating point).
    amount_paise: int
    currency: Literal["INR"]
    # What the checkout must attach to the order. The webhook resolves the tenant from
    # exactly this, so it is not decoration.
    notes: dict[str, str]
    key_id: str
    # ALWAYS null today: creating the order is a server-to-server call with credentials
    # this deployment does not have (module docstring). The field exists so the gap is
    # visible in the API contract instead of being discovered at integration time.
    provider_order_id: str | None = None
    provider_order_pending: bool = True


class WebhookAck(Strict):
    status: Literal["credited", "duplicate", "ignored"]
    event: str
    payment_id: str | None = None
    entry_id: UUID | None = None
    amount_inr: Decimal | None = None
    balance_inr: Decimal | None = None


@router.post(
    "/intent",
    response_model=TopUpIntentOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Start a prepaid top-up — prices it and binds it to this tenant (D-34)",
    description=(
        "Returns what a checkout needs. It does NOT create the provider-side order: "
        "that requires API credentials this deployment does not hold, so "
        "`provider_order_id` is null and `provider_order_pending` is true."
    ),
)
async def create_topup_intent(payload: TopUpIntentIn, principal: TopUpWrite) -> TopUpIntentOut:
    """The tenant comes from the verified session, never from the body — a top-up
    intent that named its own tenant would let anyone bind a payment to anyone."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    amount = to_paise(payload.amount_inr)

    if amount < MIN_TOPUP_INR or amount > MAX_TOPUP_INR:
        raise ProblemError.business_rule(
            "topup_amount_out_of_range",
            f"A top-up is between ₹{MIN_TOPUP_INR:,.0f} and ₹{MAX_TOPUP_INR:,.0f}.",
            remediation="Adjust the amount, or contact us for a larger prepayment.",
        )

    # ONE selector, shared with the receiver (`billing/payments.py`). This route used to
    # read `settings.razorpay_key_id` directly and conclude for itself that payments
    # worked — a credential is not a statement that the capability exists, and a second
    # read of the same settings is how a screen ends up offering what the route refuses.
    # The refusal writes NOTHING: no receipt is minted, no row is touched.
    capability = payment_capability()
    if not capability.available:
        raise payments_not_configured(capability.reason)
    settings = get_settings()
    assert settings.razorpay_key_id is not None, "the capability check proved this is set"

    async with tenant_session(tenant_id) as session:
        tier = await plan_tier_of(session, tenant_id)
    if tier not in PREPAID_TIERS:
        raise ProblemError.business_rule(
            "topup_not_available",
            "This account is invoiced, not prepaid.",
            remediation="Your plan is billed on its retainer; there is nothing to top up.",
        )

    # Exact by construction: `amount` is quantized to two decimals above, so this is a
    # whole number of paise and never a float multiplication.
    amount_paise = int((amount * 100).to_integral_exact())
    return TopUpIntentOut(
        tenant_id=tenant_id,
        receipt=f"clv_{uuid7().hex}",
        amount_inr=amount,
        amount_paise=amount_paise,
        currency=SUPPORTED_CURRENCY,
        notes={NOTES_TENANT_KEY: str(tenant_id)},
        key_id=settings.razorpay_key_id,
        # Never inverted here from a local condition: the capability is the one place
        # that knows whether an order-creation adapter exists, and today it does not
        # (`PROVIDER_CREATES_ORDERS`). SURFACES §2c:205 documents this field as the way
        # the gap lives in the contract rather than surfacing at integration time.
        provider_order_pending=not capability.creates_orders,
    )


@webhook_router.post(
    f"/{PROVIDER}",
    response_model=WebhookAck,
    summary="Payment-captured callback → one credit_ledger entry, idempotent on the payment id",
)
async def razorpay_webhook(request: Request) -> WebhookAck:
    """Signature first, money last.

    Nothing is read out of this payload until the HMAC verifies, and nothing durable is
    written until the tenant resolves — so a forged or malformed event leaves no row at
    all, not even an inbox trace it could later be replayed from.

    Two layers of duplicate protection, deliberately:

    1. the durable inbox, claimed on `payment.captured:<payment id>` with a hash of the
       NORMALIZED facts (not the raw body), so a redelivery whose envelope gained a
       field still dedupes, while the same payment id arriving with a different amount
       is the conflict `claim_inbox_event` is designed to shout about;
    2. the ledger's own `ref`, checked under the per-tenant credit lock inside
       `credit_captured_payment`. This one is the guarantee: inbox rows are per
       delivery and can be swept, a ledger row is permanent.

    The claim and the credit share ONE transaction, which is what makes a failure
    recoverable: a crash after the claim rolls the claim back too, so the provider's
    retry is processed rather than answered "duplicate" forever (the failure mode
    `reliability/service.py` documents against the Clerk mirror).
    """
    raw = await request.body()

    # The SAME selector the intent route asks. Fail CLOSED, like the Clerk mirror: an
    # unverifiable payment feed is worse than no feed, because it credits wallets on
    # anyone's say-so. A deployment that has a key id but no webhook secret is refused
    # here AND at the intent, which is the point of one selector — the alternative is a
    # deployment that can take money and can never credit it.
    capability = payment_capability()
    if not capability.available:
        alert("ROUTE_HANDLER", "razorpay_webhook_unconfigured")
        raise payments_not_configured(capability.reason)
    secret = get_settings().razorpay_webhook_secret
    assert secret is not None, "the capability check proved this is set"
    if not verify_signature(
        secret=secret, body=raw, signature=request.headers.get(SIGNATURE_HEADER)
    ):
        alert("ROUTE_HANDLER", "razorpay_webhook_bad_signature")
        raise ProblemError.unauthorized("Signature verification failed.")

    try:
        envelope = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        envelope = {}

    event = event_name(envelope)
    if event != CAPTURED_EVENT:
        # ACK so the provider stops retrying. Authorized-but-not-captured is not money
        # we hold, and a refund is a compensating entry someone decides on, not one we
        # infer from a callback.
        log.info("razorpay_event_ignored", extra={"event": event})
        return WebhookAck(status="ignored", event=event or "unknown")

    payment = extract_captured_payment(envelope)
    ip = request.client.host if request.client else None

    async with tenant_session(payment.tenant_id) as session:
        if not await tenant_exists(session, payment.tenant_id):
            # Real money we cannot attribute. A 404 (rather than a silent ack) is what
            # gets it into someone's hands instead of into nobody's wallet.
            alert("ROUTE_HANDLER", "razorpay_unknown_tenant")
            raise ProblemError.not_found("Organization")

        claim = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=f"{CAPTURED_EVENT}:{payment.payment_id}",
            # The FACTS, not the envelope: a redelivery that gained an `account_id` is
            # the same payment, while a different amount under the same id is not.
            payload_hash=body_hash(
                {
                    "payment_id": payment.payment_id,
                    "tenant_id": str(payment.tenant_id),
                    "amount_inr": str(payment.amount_inr),
                    "currency": payment.currency,
                }
            ),
            event_name=CAPTURED_EVENT,
        )
        if claim.state == "duplicate":
            existing = await find_topup(
                session, tenant_id=payment.tenant_id, ref=payment.payment_id
            )
            balance = await get_balance(session, tenant_id=payment.tenant_id)
            return WebhookAck(
                status="duplicate",
                event=event,
                payment_id=payment.payment_id,
                entry_id=existing[0] if existing else None,
                amount_inr=to_paise(existing[1]) if existing else None,
                balance_inr=to_paise(balance.amount_inr),
            )

        result = await credit_captured_payment(session, payment=payment, ip=ip)
        await mark_inbox_processed(session, row_id=claim.row_id)

    return WebhookAck(
        status="credited" if result.recorded else "duplicate",
        event=event,
        payment_id=payment.payment_id,
        entry_id=result.entry_id,
        amount_inr=to_paise(payment.amount_inr),
        balance_inr=to_paise(result.balance.amount_inr),
    )


__all__ = ["MAX_TOPUP_INR", "MIN_TOPUP_INR", "router", "webhook_router"]
