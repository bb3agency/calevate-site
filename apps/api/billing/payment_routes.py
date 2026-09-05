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
from decimal import ROUND_DOWN, Decimal
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.admin.service import tenant_exists
from apps.api.billing.credit_packs import (
    PACK_CATALOGUE,
    CreditPack,
    pack_by_id,
    pack_effective_rate_inr_per_min,
    pack_talk_time_minutes,
)
from apps.api.billing.payments import (
    CREDIT_EVENTS,
    NOTES_PACK_KEY,
    NOTES_TENANT_KEY,
    PAYMENT_FAILED_EVENT,
    PROVIDER,
    REFUND_PROCESSED_EVENT,
    REFUND_PROCESSING_DAYS,
    SIGNATURE_HEADER,
    SUPPORTED_CURRENCY,
    RefundEvent,
    claim_refund,
    credit_captured_payment,
    credit_refund,
    event_name,
    extract_captured_payment,
    extract_refund,
    failed_payment_summary,
    find_topup,
    inr_to_paise,
    issue_refund,
    payment_attempt_ids,
    payment_capability,
    payments_not_configured,
    razorpay_api_secret,
    razorpay_orders,
    release_refund_claim,
    topup_receipt,
    verify_checkout_signature,
    verify_signature,
)
from apps.api.billing.rates import MONEY_Q, PREPAID_TIERS, ROUNDING
from apps.api.billing.service import get_balance, plan_tier_of, to_paise
from apps.api.billing.wallet import record_attempt, settle_attempt
from apps.api.compliance.audit import write_audit
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
# Refunds are an OPS action against a tenant, not a client-realm one — a client cannot
# refund their own top-up. Mirrors `credit_routes.py`'s admin credits router prefix so the
# two operator money surfaces sit together. NOT mounted here; the integrator wires it into
# `main.py` alongside `credits_admin_router`.
refund_router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/refunds", tags=["admin"])

# Annotated dependency rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore.
TopUpWrite = Annotated[Principal, Depends(requires("org:manage", realm="client"))]
# The READ is a genuinely different permission, never the write's reused: D-22 forbids a
# GET requiring `org:manage`, and `billing:read` is what the surrounding usage screen
# already requires, so the two cannot disagree about who may see them.
TopUpRead = Annotated[Principal, Depends(requires("billing:read", realm="client"))]
# Issuing a refund is the same class of privileged, tenant-scoped ops write as an admin
# credit adjustment (`credit_routes.CreditsWrite`), so it takes the SAME permission — one
# vocabulary for "an operator may move this client's money".
RefundWrite = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: Refusals that ALREADY alerted where they were raised, so the guard in `razorpay_webhook`
#: does not fire a second alarm for one delivery. `_apply_captured_payment` and
#: `_apply_refund` both alert `razorpay_unknown_tenant` before raising `not_found`, and
#: that sentence names the case better than a general "we could not apply this" could.
_SELF_ALERTING_REFUSALS: Final = frozenset({"not_found"})

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
#
# THE TUPLE COMES FROM `billing/rates.py`, and this line used to restate it. Its own
# comment there says a tier added to one branch and not the others is "a wallet that stops
# draining"; a private copy here made the TOP-UP ROUTE — the one place money enters the
# wallet at all — invisible to that promise. Imported, so the gate on paying in and the
# gate on drawing down cannot come to disagree about who is prepaid.


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopUpIntentIn(Strict):
    # A top-up is EITHER a pack (`pack_id`, amount derived from the catalogue) OR a
    # free-form amount, never both and never neither — the model validator below enforces
    # exactly one. `amount_inr` is optional so a pack request need not restate a price it
    # does not set; a pack amount the client sent could disagree with the catalogue, and the
    # catalogue is the authority.
    #
    # max_digits/decimal_places mirror the column: MONEY is NUMERIC(12,4), and anything
    # finer than a paisa is a typo.
    amount_inr: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    #: A catalogue pack id (`billing/credit_packs.PACK_CATALOGUE`). When set, the amount and
    #: the volume bonus come from the catalogue and the client's own amount is ignored.
    pack_id: str | None = Field(default=None, min_length=1, max_length=64)

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

    @model_validator(mode="after")
    def _exactly_one_source(self) -> TopUpIntentIn:
        """A top-up is priced by a pack or by an amount, and confusing the two is a client
        error worth a 422 rather than a silent pick: sending both invites "which won", and
        sending neither is a request with no price at all."""
        if (self.pack_id is None) == (self.amount_inr is None):
            raise ValueError("send exactly one of pack_id or amount_inr")
        return self


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
    # The pack this intent priced, or null for a free-form top-up. NO default, for the
    # reason `provider_order_id` carries one: `null` (not a pack) must be distinguishable
    # from "the server did not say" in the generated types. Echoed so the checkout carries
    # the pack through to the order notes, which is what the receiver reads to grant the bonus.
    pack_id: str | None


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


class CreditPackOut(Strict):
    """One purchasable pack, priced for display. Every rupee value is an exact decimal
    STRING (hard rule 7) and stays one to the DOM — nothing here is a JSON number a browser
    would parse back through a float.

    The EFFECTIVE RATE and TALK TIME are derived server-side from the live list rate and the
    catalogue, so the table a client sees and the credits the receiver grants come from one
    source and cannot drift.
    """

    pack_id: str
    #: What the client pays (2dp), equal to the paid credits granted (1 credit = ₹1).
    amount_inr: Decimal
    paid_credits: Decimal
    #: The volume bonus in credits (₹1 each) — the "free" column.
    bonus_credits: Decimal
    total_credits: Decimal
    #: The volume bonus as a percent, e.g. "8".
    bonus_pct: Decimal
    #: The price the client actually pays per minute on this pack, at rate precision (4dp,
    #: NUMERIC(12,4)) — a RATE, not a rupee amount, so it is not rounded to paise (the
    #: distinction `billing.service.rate_to_display` makes).
    effective_rate_inr_per_min: Decimal
    #: Whole minutes of calling the pack's credits buy at the list rate, floored (you do not
    #: get a partial minute). A display estimate, not a billed figure.
    talk_time_minutes: int
    #: The single "best value" badge.
    best_value: bool


class CreditPacksOut(Strict):
    """The pack rate card. `list_rate_inr_per_min` is published beside the packs so the
    screen can show what a minute lists at (and, on the 0%-bonus pack, that the effective
    rate equals it) without a second source of the number."""

    list_rate_inr_per_min: Decimal
    packs: list[CreditPackOut]


class WebhookAck(Strict):
    # `credited` = a payment landed on the wallet; `refunded` = a refund debited it;
    # `duplicate` = we had already applied this event; `failed` = a payment.failed event,
    # acked so the provider stops retrying but moving no money; `ignored` = an event this
    # deployment has no handler for.
    status: Literal["credited", "refunded", "duplicate", "failed", "ignored"]
    event: str
    payment_id: str | None = None
    entry_id: UUID | None = None
    amount_inr: Decimal | None = None
    balance_inr: Decimal | None = None


class CheckoutCallbackIn(Strict):
    """The three fields Razorpay Checkout hands back to the browser on success.

    Named exactly as the provider names them so the frontend forwards them verbatim; the
    server is where they are verified (never in the browser).
    """

    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class CheckoutCallbackOut(Strict):
    """What the confirmation route tells the browser once the signature verifies.

    `credit_pending` is TRUE deliberately and always: the callback proves authenticity but
    carries no amount and no tenant, so the wallet credit follows from the webhook. The UI
    should show "payment received, balance updating" rather than asserting a new balance it
    has not been told — the same honesty `provider_order_pending` keeps on the intent.
    """

    verified: Literal[True]
    payment_id: str
    order_id: str
    credit_pending: bool


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


def _pack_out(pack: CreditPack, *, list_rate: Decimal) -> CreditPackOut:
    """Price one pack for the table, from the live list rate. The effective rate and talk
    time are derived here — never in the browser — so the money arithmetic lives in the one
    language with an exact decimal type."""
    return CreditPackOut(
        pack_id=pack.pack_id,
        amount_inr=to_paise(pack.amount_inr),
        paid_credits=to_paise(pack.paid_credits),
        bonus_credits=to_paise(pack.bonus_credits),
        total_credits=to_paise(pack.total_credits),
        bonus_pct=pack.bonus_pct,
        # A rate, kept at NUMERIC(12,4): rounding it to paise would break the client's only
        # arithmetic on it (rate x minutes), the reason `rate_to_display` exists.
        effective_rate_inr_per_min=pack_effective_rate_inr_per_min(
            pack, list_rate=list_rate
        ).quantize(MONEY_Q, rounding=ROUNDING),
        # Floored to whole minutes: a client does not buy a fraction of a minute, and
        # rounding UP would advertise talk time the credits do not cover.
        talk_time_minutes=int(
            pack_talk_time_minutes(pack, list_rate=list_rate).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
        ),
        best_value=pack.best_value,
    )


@router.get(
    "/packs",
    response_model=CreditPacksOut,
    openapi_extra=permission_meta("billing:read"),
    summary="The prepaid credit-pack rate card, priced at the live list rate",
    description=(
        "The static pack catalogue (`billing/credit_packs.py`), each pack priced for "
        "display: paid + bonus credits, the effective per-minute rate, and the talk time "
        "the credits buy. Selecting a pack starts a top-up intent with its `pack_id`."
    ),
)
async def read_credit_packs(_principal: TopUpRead) -> CreditPacksOut:
    """The rate card, priced at whatever `self_serve_inr_per_min` currently is — the same
    value calls are billed at, so the effective rates shown are the ones a client will
    actually get. No tenant state is read; the catalogue is the same for everyone."""
    list_rate = get_settings().self_serve_inr_per_min
    return CreditPacksOut(
        list_rate_inr_per_min=to_paise(list_rate),
        packs=[_pack_out(pack, list_rate=list_rate) for pack in PACK_CATALOGUE],
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

    # A pack prices itself from the catalogue; a free-form top-up prices from the body. The
    # model validator has already guaranteed exactly one is set, so this is the ONE place the
    # amount is resolved and the pack id is bound to the payment.
    if payload.pack_id is not None:
        pack = pack_by_id(payload.pack_id)
        if pack is None:
            raise ProblemError.business_rule(
                "unknown_credit_pack",
                "That credit pack is not one we offer.",
                remediation="Pick a pack from the list, or add a free-form amount instead.",
            )
        amount = to_paise(pack.amount_inr)
        pack_id: str | None = pack.pack_id
    else:
        assert payload.amount_inr is not None, "the model validator proved one source is set"
        amount = to_paise(payload.amount_inr)
        pack_id = None

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
    if pack_id is not None:
        # Into the order by construction, so the receiver grants the bonus from the payment
        # itself and never from a frontend it has to trust (the argument `NOTES_TENANT_KEY`
        # carries for the tenant, applied to the pack).
        notes[NOTES_PACK_KEY] = pack_id

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
            pack_id=pack_id,
        )

    # THE DURABLE TRACE, WRITTEN BEFORE THE PROVIDER IS CALLED (migration e9b24c73f105).
    #
    # Until this row existed a top-up left NO record until money arrived, so a client
    # whose card was declined came back to a screen indistinguishable from one they had
    # never touched — and nobody could tell "still settling" from "nothing happened".
    # It is written FIRST, without an order id, for the reason the idempotency claim
    # commits first: a provider call that then fails must still leave the attempt behind,
    # or the one case the table exists for is the one case it misses.
    #
    # It is NOT money and it may not refuse a payment — but at THIS point nothing has been
    # ordered and no money can move, so a failure here is raised rather than swallowed
    # (the client retries and nothing is lost). Once an order exists the balance of that
    # judgement flips, and `_remember_order` below says so.
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt=receipt,
            amount_inr=amount,
            provider_order_id=None,
            pack_id=pack_id,
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

    intent = await _create_order_once(
        tenant_id=tenant_id, amount_inr=amount, receipt=receipt, notes=notes, build=_intent
    )
    if intent.provider_order_id is not None:
        await _remember_order(
            tenant_id=tenant_id,
            receipt=receipt,
            amount_inr=amount,
            pack_id=pack_id,
            order_id=intent.provider_order_id,
        )
    return intent


async def _remember_order(
    *, tenant_id: UUID, receipt: str, amount_inr: Decimal, pack_id: str | None, order_id: str
) -> None:
    """Fill the provider's order id onto the attempt row — and NEVER fail the payment.

    This runs AFTER a live order exists at the provider, which inverts the judgement made
    one function up: raising here would turn a real, payable order into an error the
    client sees, and they would click again and get a second order for the same money.
    The row is a narrative and the ledger is the record, so the worst a lost write costs
    is that the webhook cannot find this attempt to mark — which `settle_attempt` already
    treats as ordinary rather than as an error.

    Swallowed, but never SILENTLY: it alerts, because an attempt table that stops learning
    order ids degrades into exactly the blind screen it was built to end.
    """
    try:
        async with tenant_session(tenant_id) as session:
            await record_attempt(
                session,
                tenant_id=tenant_id,
                receipt=receipt,
                amount_inr=amount_inr,
                provider_order_id=order_id,
                pack_id=pack_id,
            )
    except Exception:
        alert("ROUTE_HANDLER", "topup_attempt_not_recorded")
        log.warning("topup_attempt_order_unrecorded", extra={"tenant_id": str(tenant_id)})


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


@router.post(
    "/callback",
    response_model=CheckoutCallbackOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Verify the Checkout callback signature (order_id|payment_id, key_secret)",
    description=(
        "After a successful Checkout the browser posts back razorpay_order_id, "
        "razorpay_payment_id and razorpay_signature. This verifies the signature on the "
        "SERVER with the key_secret — a different scheme and a different secret from the "
        "webhook — and rejects a mismatch. It does NOT credit the wallet: the callback "
        "carries no amount, so the credit follows from the webhook."
    ),
)
async def confirm_topup_callback(
    payload: CheckoutCallbackIn, principal: TopUpWrite
) -> CheckoutCallbackOut:
    """Authenticity, not money. The signature proves Razorpay produced this order/payment
    pair; a forged `razorpay_order_id` cannot round-trip its own signature.

    The secret is the KEY SECRET (`razorpay_api_secret`), never the webhook secret — the
    two verifiers are separate functions naming the secret they take precisely so this
    cannot be got wrong silently. A deployment with no key secret cannot verify a callback
    and refuses rather than waving it through.

    Reason it does not credit here: the callback has no amount and no tenant notes, so
    constructing a wallet credit from it would be guessing. The webhook (which carries
    both) is the single writer, idempotent on the payment id — so a client who returns on
    the callback sees "received, updating" and the balance moves when the webhook lands.
    """
    assert principal.tenant_id is not None

    capability = payment_capability()
    if not capability.available:
        raise payments_not_configured(capability.reason)
    key_secret = razorpay_api_secret()
    if key_secret is None:
        # Without the key secret there is no way to verify a callback — refuse rather than
        # accept an unverifiable "payment succeeded" from the browser.
        raise payments_not_configured(capability.orders_reason)

    if not verify_checkout_signature(
        key_secret=key_secret,
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature,
    ):
        log.warning("topup_callback_bad_signature", extra={"tenant_id": str(principal.tenant_id)})
        raise ProblemError(
            kind="auth",
            code="payment_signature_invalid",
            title="Payment could not be verified",
            detail="We could not confirm this payment was genuine.",
            remediation="Do not retry the payment. Contact us if it was debited.",
        )

    log.info(
        "topup_callback_verified",
        extra={"tenant_id": str(principal.tenant_id), "payment_id": payload.razorpay_payment_id},
    )
    return CheckoutCallbackOut(
        verified=True,
        payment_id=payload.razorpay_payment_id,
        order_id=payload.razorpay_order_id,
        credit_pending=True,
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
    ip = client_request_ip(request)

    # payment.captured AND order.paid both carry `payload.payment.entity` and both mean
    # "money arrived", deduped on the same payment id — so they take the same path.
    #
    # THE GUARD AROUND THEM IS THE ONE THING BETWEEN A REFUSED PAYMENT AND SILENCE. Past
    # the signature check the money is REAL: Razorpay signed this delivery, so a refusal
    # here is a rupee that reached the provider and did not reach the wallet. Every
    # refusal on this path is one of ours — an unreadable payload, a currency we do not
    # settle in, an amount that is not whole paise, missing tenant notes, or a payment id
    # already on the ledger for a different amount — and each was previously visible only
    # as a 4xx in an access log while the provider retried into the same wall. The client
    # meanwhile sees a debited card and an unmoved balance, and nobody here is told.
    # `razorpay_unknown_tenant` already alerted for its own case, which is the standard
    # this generalizes rather than a precedent it duplicates.
    try:
        if event in CREDIT_EVENTS:
            return await _apply_captured_payment(envelope, event=event, ip=ip)
        if event == REFUND_PROCESSED_EVENT:
            return await _apply_refund(envelope, event=event, ip=ip)
    except ProblemError as exc:
        if exc.code not in _SELF_ALERTING_REFUSALS:
            alert(
                "ROUTE_HANDLER",
                "razorpay_money_unapplied",
                detail=(
                    "A payment event this deployment could not apply passed signature "
                    "verification, so the money is real and the wallet did not move. "
                    "Reconcile it by hand: runbooks/topup-payments.md."
                ),
                problem_code=exc.code,
                event=event,
            )
        raise
    if event == PAYMENT_FAILED_EVENT:
        # A failed attempt moves no money, so nothing is credited and no ledger row is
        # written. What DOES happen now — and did not before `topup_attempts` existed — is
        # that the client's own screen learns about it: a declined card has no ledger
        # entry, so without this mark a client who tried to pay came back to a screen
        # indistinguishable from one they had never touched.
        log.info("razorpay_payment_failed", extra=failed_payment_summary(envelope))
        await _mark_attempt_failed(envelope)
        # ACKed regardless, so the provider stops retrying a failure.
        return WebhookAck(status="failed", event=event)
    # ACK an event this deployment has no handler for, so the provider stops retrying.
    log.info("razorpay_event_ignored", extra={"event": event})
    return WebhookAck(status="ignored", event=event or "unknown")


async def _mark_attempt_failed(envelope: Any) -> None:
    """Mark the top-up attempt behind a `payment.failed` event, if we can tell which.

    Best-effort by design, at both ends. `payment_attempt_ids` returns None when the
    payload does not carry the ids (the contract is UNVERIFIED — `billing/payments.py`),
    and `settle_attempt` updates nothing when no row matches; in both cases the attempt
    simply keeps saying "settling" until it ages into "unfinished". That is the whole
    reason this state lives in its own table rather than on the ledger: the worst a lost
    write here can cost is a slightly stale word on a screen, never a rupee.

    `settle_attempt` refuses to move a row OUT of `captured`, so an in-modal retry that
    fails a first card and then succeeds cannot re-label a paid order as failed.
    """
    attempt = payment_attempt_ids(envelope)
    if attempt is None:
        return
    async with tenant_session(attempt.tenant_id) as session:
        await settle_attempt(
            session,
            tenant_id=attempt.tenant_id,
            order_id=attempt.order_id,
            payment_id=attempt.payment_id,
            status="failed",
        )


async def _apply_captured_payment(envelope: Any, *, event: str, ip: str | None) -> WebhookAck:
    """A captured payment → one `credit_ledger` top-up, deduped twice (inbox + ledger ref).

    The inbox key is `<event>:<payment id>` so payment.captured and order.paid for the same
    payment claim SEPARATE inbox rows — but both credit the same payment id, so the ledger
    `ref` (the guarantee, checked under the credit lock inside `credit_captured_payment`)
    collapses them to one row: whichever event arrives first credits, the other reports a
    replay. The claim and the credit share ONE transaction, so a crash after the claim rolls
    it back and the provider's retry is processed rather than answered "duplicate" for ever.
    """
    payment = extract_captured_payment(envelope)
    async with tenant_session(payment.tenant_id) as session:
        if not await tenant_exists(session, payment.tenant_id):
            # Real money we cannot attribute. A 404 (rather than a silent ack) is what
            # gets it into someone's hands instead of into nobody's wallet.
            alert("ROUTE_HANDLER", "razorpay_unknown_tenant")
            raise ProblemError.not_found("Organization")

        claim = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=f"{event}:{payment.payment_id}",
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
            event_name=event,
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
        # THE ATTEMPT IS MARKED IN THE SAME TRANSACTION AS THE CREDIT, so the client's
        # screen and the client's wallet cannot disagree about whether this payment
        # landed. `captured` is terminal in `settle_attempt`, which is what stops a
        # `payment.failed` for an in-modal first card re-labelling a paid order.
        #
        # The order id comes from the envelope rather than from `CapturedPayment`, which
        # deliberately does not keep it: the typed model carries only what a CREDIT needs,
        # and the attempt row is keyed on the order because that is the only identifier it
        # holds before money arrives. `None` (an event whose ids we could not read) simply
        # marks nothing — the ledger is the record either way.
        attempt = payment_attempt_ids(envelope)
        if attempt is not None and attempt.tenant_id == payment.tenant_id:
            await settle_attempt(
                session,
                tenant_id=payment.tenant_id,
                order_id=attempt.order_id,
                payment_id=payment.payment_id,
                status="captured",
            )
        await mark_inbox_processed(session, row_id=claim.row_id)

    return WebhookAck(
        status="credited" if result.recorded else "duplicate",
        event=event,
        payment_id=payment.payment_id,
        entry_id=result.entry_id,
        amount_inr=to_paise(payment.amount_inr),
        balance_inr=to_paise(result.balance.amount_inr),
    )


async def _apply_refund(envelope: Any, *, event: str, ip: str | None) -> WebhookAck:
    """A processed refund → one COMPENSATING `credit_ledger` entry, deduped twice.

    The mirror of `_apply_captured_payment` for money going the other way: inbox on
    `refund.processed:<refund id>` as the cheap first line, the ledger `ref = refund id` as
    the guarantee inside `credit_refund` — so a refund we already recorded from the API
    response (`issue_refund` → `credit_refund`) dedupes against this event and vice versa.
    """
    refund = extract_refund(envelope)
    async with tenant_session(refund.tenant_id) as session:
        if not await tenant_exists(session, refund.tenant_id):
            alert("ROUTE_HANDLER", "razorpay_unknown_tenant")
            raise ProblemError.not_found("Organization")

        claim = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=f"{event}:{refund.refund_id}",
            payload_hash=body_hash(
                {
                    "refund_id": refund.refund_id,
                    "payment_id": refund.payment_id,
                    "tenant_id": str(refund.tenant_id),
                    "amount_inr": str(refund.amount_inr),
                    "currency": refund.currency,
                }
            ),
            event_name=event,
        )
        if claim.state == "duplicate":
            balance = await get_balance(session, tenant_id=refund.tenant_id)
            return WebhookAck(
                status="duplicate",
                event=event,
                payment_id=refund.payment_id,
                balance_inr=to_paise(balance.amount_inr),
            )

        result = await credit_refund(session, refund=refund, ip=ip)
        await mark_inbox_processed(session, row_id=claim.row_id)

    return WebhookAck(
        status="refunded" if result.recorded else "duplicate",
        event=event,
        payment_id=refund.payment_id,
        entry_id=result.entry_id,
        amount_inr=to_paise(refund.amount_inr),
        balance_inr=to_paise(result.balance.amount_inr),
    )


class RefundIn(Strict):
    """An operator issuing a refund against one captured payment.

    `amount_inr` is optional: absent means "refund the full top-up recorded for this
    payment", present means a partial refund of that much. A float is refused at the
    boundary, identical to the top-up route — money crosses the wire as a string.
    """

    payment_id: str = Field(min_length=1, max_length=64)
    amount_inr: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    reason: str = Field(min_length=1, max_length=280)

    @field_validator("amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError('money crosses the wire as a string ("2500.00"), never as a float')
        return value


class RefundOut(Strict):
    refund_id: str
    payment_id: str
    amount_inr: Decimal
    # True once the compensating ledger entry has been written (an instant/processed
    # refund); False when the provider has accepted the refund but it is not yet processed,
    # in which case the `refund.processed` webhook writes the entry. NO default — the console
    # must tell "not yet applied" from "the server did not say" (TopUpIntentOut's argument).
    recorded: bool
    balance_inr: Decimal | None
    processing_days: int


@refund_router.post(
    "",
    response_model=RefundOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Refund a captured payment — provider refund + a compensating ledger entry",
    description=(
        "Issues a refund at the provider and records it as a compensating credit_ledger "
        "entry (append-only, negative delta). Idempotent on a derived key so a double "
        "click issues one refund. Omit amount_inr for a full refund of the payment's "
        "top-up, or send a smaller amount for a partial refund."
    ),
)
async def issue_tenant_refund(
    tenant_id: UUID, payload: RefundIn, request: Request, principal: RefundWrite
) -> RefundOut:
    """Refund one payment: provider call FIRST (no DB lock across it), then the ledger.

    Order is the correctness argument, and it mirrors `_create_order_once`:

    1. Resolve the amount — a full refund is the top-up recorded for this payment, read
       from the ledger, so an operator need not retype it and cannot fat-finger it.
    2. CLAIM the refund and COMMIT the claim (`claim_refund`), which is where the ceiling
       is now enforced. It has to be a committed row rather than a read, because the act
       it guards happens after the transaction ends — see below.
    3. `issue_refund` calls the provider OUTSIDE any transaction (BACKEND-PATTERNS §5).
       If it raises, the claim this request took is RELEASED: no money moved, so nothing
       may go on counting against what the client can still be refunded.
    4. Only if the provider reports the refund already PROCESSED do we write the
       compensating entry now (`credit_refund`, idempotent on the refund id). Otherwise
       the `refund.processed` webhook writes it — same single writer, deduped on the same
       ref, so the entry lands exactly once whichever path gets there first.

    **WHY STEP 2 IS A COMMITTED ROW AND NOT THE LEDGER READ IT REPLACES.** This route used
    to read the refunds already on `credit_ledger` under `lock_tenant_credits` and call
    that "the check half of a check-then-write". It was not: `pg_advisory_xact_lock` is
    released by COMMIT, and the transaction ended at the `async with` before the provider
    was called. Two operators refunding ₹2,000 and ₹1,000 against a ₹2,500 top-up at the
    same moment both read "nothing refunded yet", both passed, and both issued a provider
    refund — ₹500 the client never paid, as two entries an append-only ledger cannot take
    back. `billing/payments.claim_refund` carries the whole argument and migration
    `c4b8e91d7a05` carries why neither an advisory lock nor a Redis lease can span a
    vendor call.

    Audited on the operator's issuance regardless of whether the entry landed here, because
    the privileged act is asking for the refund; the system-actor `credit.refund` audit
    that `credit_refund` writes records the money movement separately.
    """
    async with tenant_session(tenant_id) as session:
        if not await tenant_exists(session, tenant_id):
            raise ProblemError.not_found("Organization")
        existing_topup = await find_topup(session, tenant_id=tenant_id, ref=payload.payment_id)
        if existing_topup is None:
            # We only refund money we recorded arriving. Refunding a payment with no top-up
            # row would be a compensating entry against nothing — an ops error, not a route.
            raise ProblemError.not_found("Payment")
        topup_amount = existing_topup.amount_inr

    amount = payload.amount_inr if payload.amount_inr is not None else topup_amount
    if amount <= 0:
        raise ProblemError.business_rule(
            "invalid_refund_amount",
            "A refund amount must be positive.",
            remediation="Send a positive amount, or omit it to refund the whole payment.",
        )

    # THE CEILING IS ON THE TOTAL, NOT ON THIS REQUEST, and it is enforced by a COMMITTED
    # CLAIM rather than by a read (`claim_refund`, and the docstring above for why the
    # read could not hold it). A repeat of an amount already claimed comes back
    # `claimed=False` and is let through as the replay it is: the provider's own
    # idempotency key is `(payment_id, amount)`, so it can only collapse onto the refund
    # that already exists.
    async with tenant_session(tenant_id) as session:
        claim = await claim_refund(
            session,
            tenant_id=tenant_id,
            payment_id=payload.payment_id,
            amount_inr=amount,
            payment_total_inr=topup_amount,
        )

    try:
        refund = await issue_refund(
            tenant_id=tenant_id, payment_id=payload.payment_id, amount_inr=amount
        )
    except Exception:
        # NOTHING MOVED, SO NOTHING MAY GO ON BEING RESERVED. A claim left behind by a
        # vendor timeout would shrink what this client can be refunded for ever — money
        # withheld by an outage, which is a worse failure than the double refund the
        # claim exists to prevent. Only a claim THIS request took is released; a replay's
        # belongs to the refund that already exists.
        if claim.claimed:
            async with tenant_session(tenant_id) as session:
                await release_refund_claim(
                    session, tenant_id=tenant_id, refund_key=claim.refund_key
                )
        raise
    ip = client_request_ip(request)

    recorded = False
    balance_inr: Decimal | None = None
    if refund.is_processed:
        event = RefundEvent(
            refund_id=refund.refund_id,
            payment_id=refund.payment_id,
            tenant_id=tenant_id,
            amount_inr=amount,
            currency=SUPPORTED_CURRENCY,
        )
        async with tenant_session(tenant_id) as session:
            result = await credit_refund(session, refund=event, ip=ip)
        recorded = result.recorded
        balance_inr = to_paise(result.balance.amount_inr)

    async with tenant_session(tenant_id) as session:
        await write_audit(
            session,
            action="refund.issued",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=refund.refund_id,
            ip=ip,
            summary={
                "source": PROVIDER,
                "refund_ref": refund.refund_id,
                "payment_ref": refund.payment_id,
                "amount_inr": str(to_paise(amount)),
                "reason": payload.reason,
                "status": refund.status,
            },
        )
    log.info(
        "razorpay_refund_issued",
        extra={"tenant_id": str(tenant_id), "refund_id": refund.refund_id, "recorded": recorded},
    )
    return RefundOut(
        refund_id=refund.refund_id,
        payment_id=refund.payment_id,
        amount_inr=to_paise(amount),
        recorded=recorded,
        balance_inr=balance_inr,
        processing_days=REFUND_PROCESSING_DAYS,
    )


__all__ = [
    "INTENT_ROUTE",
    "MAX_TOPUP_INR",
    "MIN_TOPUP_INR",
    "CheckoutCallbackOut",
    "CreditPackOut",
    "CreditPacksOut",
    "RefundOut",
    "TopUpCapabilityOut",
    "TopUpIntentOut",
    "refund_router",
    "router",
    "webhook_router",
]
