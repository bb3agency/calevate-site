"""Self-serve top-ups: the order intent (client realm) and the payment webhook (machine).

Two surfaces, two routers, because they have nothing in common but the money:

- `router` — `POST /v1/billing/topups/intent`. A client-realm owner says "I want to
  add ₹2,500"; we price it, bind it to their tenant and hand back what a checkout
  needs. Authenticated, permissioned, load-sheddable.
- `webhook_router` — `POST /hooks/v1/razorpay`. The provider says "that payment was
  captured"; we credit the wallet. Under `/hooks` because it shares the webhook
  doctrine with `ingest/routes.py`: never load-shed (a
  payment landing during degraded mode is still a payment), authenticated by a
  signature rather than a session, inbox-deduped, and idempotent on the provider's own
  identifier.

**What is honestly unfinished is marked as such.** Since D-98 the intent DOES create the
provider-side order — `RazorpayOrders.create_order`, a real `POST /v1/orders` — but only
on a deployment that holds the API secret, and none does: no Razorpay account has been
provisioned, so `capability.creates_orders` is False everywhere and the response is still
`provider_order_id: null` / `provider_order_pending: true`. The difference is that it is
now a NAMED state (`no_api_secret`) rather than an absence. The signing scheme is READ AT
SOURCE from the vendor's own SDK; the webhook payload paths remain UNVERIFIED. See
`billing/payments.py`.

A third surface, small and deliberate:

- `GET /v1/billing/topups/capability` — what this deployment can do about money, asked
  BEFORE the click. D-75's shape (`KycRecordOut.number_purchase_available`): the
  capability is a RENDERING HINT and never the check, so the intent route stays the
  authority and a stale hint costs a refusal rather than a payment. Without it the top-up
  form on `/c/{slug}/usage` offers a control that this deployment's default configuration
  refuses every single time — §52's "loading is a skeleton, failure is a refusal" applied
  one step earlier, to a control that should not have been offered at all.

Permissions. The intent is `org:manage`: spending the client's money is not a read,
and `org:manage` is already in `MUTATING_PERMISSIONS`, so an impersonating admin (D-22)
cannot start a payment on a client's behalf. There is no `billing:write` in the
registry and inventing one for a single route was not worth it — the same call
`credit_routes.py` made in the other direction.

NOT mounted here — the integrator wires both routers into `main.py`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.admin.service import tenant_exists
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
    inr_to_paise,
    payment_capability,
    payments_not_configured,
    razorpay_orders,
    topup_receipt,
    verify_signature,
)
from apps.api.billing.service import get_balance, plan_tier_of, to_paise
from apps.api.core.alerting import alert
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    claim_inbox_event,
    complete_idempotency,
    fail_idempotency,
    mark_inbox_processed,
    scope_key,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/billing/topups", tags=["billing"])
webhook_router = APIRouter(prefix="/hooks/v1", tags=["billing-webhooks"])

# Annotated dependency rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore.
TopUpWrite = Annotated[Principal, Depends(requires("org:manage", realm="client"))]
# The READ is a genuinely different permission, never the write's reused: D-22 forbids a
# GET requiring `org:manage`, and `billing:read` is what the surrounding usage screen
# already requires, so the two cannot disagree about who may see them.
TopUpRead = Annotated[Principal, Depends(requires("billing:read", realm="client"))]

# The route this intent claims its idempotency key under. A literal, matching the
# `crm/routes.py` convention of naming the templated path rather than the resolved one.
INTENT_ROUTE = "/v1/billing/topups/intent"

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
    # The provider's order id, or null when this deployment could not create one.
    #
    # NO DEFAULT ON EITHER FIELD, and that is load-bearing rather than tidy: a Pydantic
    # field with a default generates an OPTIONAL property in the TypeScript client, and
    # the console must be able to tell "there is no order" from "the server did not say".
    # This repository has been bitten by that four times. `str | None` with no default is
    # a REQUIRED `string | null` in the generated types.
    provider_order_id: str | None
    # True = there is no order and one is still owed. Never inverted from a local
    # condition — it is `not capability.creates_orders`, and the capability is the one
    # place that knows whether the adapter AND the credential are both present.
    provider_order_pending: bool


class TopUpCapabilityOut(Strict):
    """What this deployment can do about money, asked before the click (D-75's shape).

    Two booleans because they are two facts and a screen needs both:
    `online_payments_available` decides whether the top-up form is offered at all, and
    `provider_orders_available` decides what the screen may promise once it is submitted.

    Neither carries a default, for the reason on `TopUpIntentOut.provider_order_id`: a
    missing key must not read as `false`, which would render "online payment is switched
    off for your account" out of our own ignorance rather than out of the server's answer.

    NO reason code is published. `reason` names OUR configuration state and a client
    cannot act on "no_webhook_secret"; telling them which of our secrets is missing is an
    internals leak. It is logged where an operator can reach it (`payments_unavailable`).
    """

    online_payments_available: bool
    provider_orders_available: bool


class WebhookAck(Strict):
    status: Literal["credited", "duplicate", "ignored"]
    event: str
    payment_id: str | None = None
    entry_id: UUID | None = None
    amount_inr: Decimal | None = None
    balance_inr: Decimal | None = None


@router.get(
    "/capability",
    response_model=TopUpCapabilityOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Can this deployment take an online payment, and can it create an order?",
    description=(
        "A RENDERING HINT, never the check (D-75). The intent route asks the same "
        "selector and remains the authority; a stale answer here costs a refusal, "
        "never a payment."
    ),
)
async def read_topup_capability(_principal: TopUpRead) -> TopUpCapabilityOut:
    """Answered from `payment_capability()` — the SAME selector every other surface
    asks, so a screen cannot offer what the route will refuse. No settings are read
    here; that is the entire point of the seam."""
    capability = payment_capability()
    if not capability.available:
        # Logged, not returned. An operator reading `payments_unavailable` gets the
        # authored reason; the client gets two booleans they can act on.
        log.info("topup_capability_unavailable", extra={"reason": capability.reason or "unknown"})
    elif not capability.creates_orders:
        log.info(
            "topup_orders_unavailable",
            extra={"reason": capability.orders_reason or "unknown"},
        )
    return TopUpCapabilityOut(
        online_payments_available=capability.available,
        provider_orders_available=capability.creates_orders,
    )


@router.post(
    "/intent",
    response_model=TopUpIntentOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Start a prepaid top-up — prices it, binds it to this tenant, creates the order (D-98)",
    description=(
        "Creates the provider-side order when this deployment holds the API secret. "
        "It does not today — no Razorpay account is provisioned — so `provider_order_id` "
        "is null and `provider_order_pending` is true. Idempotent on a server-derived "
        "key: the same tenant asking for the same amount twice gets one order."
    ),
)
async def create_topup_intent(payload: TopUpIntentIn, principal: TopUpWrite) -> TopUpIntentOut:
    """The tenant comes from the verified session, never from the body — a top-up
    intent that named its own tenant would let anyone bind a payment to anyone.

    Order of operations is the correctness argument, and each step is cheap-before-dear:
    validate, then ask the seam, then check the plan, and only then spend a network call
    on the provider. Everything that can refuse, refuses before anything is written.
    """
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
    key_id = get_settings().razorpay_key_id
    assert key_id is not None, "the capability check proved this is set"

    async with tenant_session(tenant_id) as session:
        tier = await plan_tier_of(session, tenant_id)
    if tier not in PREPAID_TIERS:
        raise ProblemError.business_rule(
            "topup_not_available",
            "This account is invoiced, not prepaid.",
            remediation="Your plan is billed on its retainer; there is nothing to top up.",
        )

    # THE one conversion to the provider's unit, and it refuses rather than rounds
    # (`payments.inr_to_paise`). It used to be an inline `to_integral_exact()` here,
    # which silently rounded — see that function for why that was correct only by
    # accident. One way per problem: the adapter converts through the same function.
    amount_paise = inr_to_paise(amount)
    receipt = topup_receipt(tenant_id=tenant_id, amount_inr=amount, at=datetime.now(UTC))
    notes = {NOTES_TENANT_KEY: str(tenant_id)}

    def _intent(order_id: str | None) -> TopUpIntentOut:
        return TopUpIntentOut(
            tenant_id=tenant_id,
            receipt=receipt,
            amount_inr=amount,
            amount_paise=amount_paise,
            currency=SUPPORTED_CURRENCY,
            notes=notes,
            key_id=key_id,
            provider_order_id=order_id,
            provider_order_pending=order_id is None,
        )

    if not capability.creates_orders:
        # No API secret on this deployment (`no_api_secret`), which is every deployment
        # today. The receipt is real and the amount is priced, so the bank-transfer path
        # in `runbooks/topup-payments.md` §3 has a reference to quote; nothing is
        # fabricated in `provider_order_id`.
        log.info(
            "topup_intent_without_order",
            extra={"tenant_id": str(tenant_id), "reason": capability.orders_reason or "unknown"},
        )
        return _intent(None)

    return await _create_order_once(
        tenant_id=tenant_id, amount_inr=amount, receipt=receipt, notes=notes, build=_intent
    )


async def _create_order_once(
    *,
    tenant_id: UUID,
    amount_inr: Decimal,
    receipt: str,
    notes: dict[str, str],
    build: Callable[[str | None], TopUpIntentOut],
) -> TopUpIntentOut:
    """Create at most ONE provider order per derived key, and replay it thereafter.

    `claim_idempotency` is this repository's answer to "the same client-initiated
    mutation, twice", and the key is derived server-side by `topup_receipt` rather than
    read off a header — `crm.routes.call_back`'s pattern, because a second CLICK mints a
    second header and would place the side effect twice.

    **The claim commits BEFORE the network call, in its own transaction.** Two clicks
    racing would otherwise both be inside `INSERT … ON CONFLICT`, so the loser blocks on
    the unique index until the winner's transaction ends — i.e. a database lock held
    across a call to a payment provider, which is the one thing BACKEND-PATTERNS §5 names
    outright. Committing first turns that into the CAS the machinery is designed around:
    the loser reads `processing` and gets `idempotent_request_in_flight` with a
    `Retry-After`, and a crashed attempt is retaken after `CLAIM_LEASE`.

    The scope is the TENANT, with no user: `scope_key(tenant_id=…, user_id=None)`. A
    top-up belongs to the organization's wallet, not to whoever clicked — two owners
    submitting the same amount at the same moment want one order, not one each.
    """
    scope = scope_key(tenant_id=tenant_id, user_id=None)
    request_hash = body_hash({"tenant_id": str(tenant_id), "receipt": receipt})

    async with tenant_session(tenant_id) as session:
        claim = await claim_idempotency(
            session,
            scope=scope,
            route=INTENT_ROUTE,
            method="POST",
            key=receipt,
            request_hash=request_hash,
        )
    if claim.state == "replay" and claim.response_payload:
        # The SAME order, re-served. Money is stored and re-read as digit strings
        # (`model_dump(mode="json")`), so a replay cannot be the place a Decimal becomes
        # a float.
        return TopUpIntentOut.model_validate(claim.response_payload)

    try:
        order = await razorpay_orders().create_order(
            amount_inr=amount_inr, receipt=receipt, notes=notes
        )
    except Exception:
        # Never swallowed, and never left `processing`: a failed attempt that kept the
        # claim would refuse the client's own retry as "already in flight" for ten
        # minutes. Marking it failed lets the very next click retake it by CAS.
        async with tenant_session(tenant_id) as session:
            await fail_idempotency(session, record_id=claim.record_id)
        raise

    result: TopUpIntentOut = build(order.order_id)
    async with tenant_session(tenant_id) as session:
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(mode="json"),
        )
    log.info(
        "topup_order_created",
        extra={"tenant_id": str(tenant_id), "order_id": order.order_id},
    )
    return result


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
    `reliability/service.py` documents against the retired Clerk mirror).
    """
    raw = await request.body()

    # The SAME selector the intent route asks. Fail CLOSED: an
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
    ip = client_request_ip(request)

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


__all__ = [
    "INTENT_ROUTE",
    "MAX_TOPUP_INR",
    "MIN_TOPUP_INR",
    "TopUpCapabilityOut",
    "TopUpIntentOut",
    "router",
    "webhook_router",
]
