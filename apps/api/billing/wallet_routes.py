"""The prepaid wallet, read by the person whose money it is.

Everything on this router is a READ. Nothing here writes a row, nothing here decides
whether a call may be placed, and there is deliberately no second credit check anywhere
in it — `compliance.service.credits_exhausted` is the one gate and this router ASKS it.
Buying is `POST /v1/billing/topups/intent` on `billing/payment_routes.py`, one permission
up; correcting is the operator's `billing/credit_routes.py`, one realm over.

## Why a new router rather than more of `credit_routes.py`

`credit_routes.py` is the ADMIN wallet: `/v1/admin/tenants/{id}/credits`, `admin:tenants`
to write and a per-tenant audit row on every read (D-482 L-1). Its reader is an operator
holding a bank statement, and its whole vocabulary — reversible amounts, restatements,
compensating entries — is about repairing a ledger. None of that belongs on the screen a
clinic owner opens to find out whether they can still make calls, and putting the client's
read behind an admin path would have meant either an audit row per page view or a second
meaning for one route.

What is NOT duplicated is the money itself. The balance is `service.get_balance`, the
payments behind the top-up entries are `service.recorded_payments`, the runway is
`billing/wallet.py`, and the supplier block on the receipt is `gst.supplier_identity` —
the same functions the operator's screen and the monthly statement read, so the client's
figures and ours cannot disagree.

## Permissions: seeing is not buying (the founder's decision, 2 Sep 2026)

`wallet:read` — held by `owner`, `admin` and, uniquely among billing surfaces, `staff`.
The reason is operational rather than generous: the thing that stops a staff member
dialling is an empty wallet, and a refusal whose explanation only the owner can see is a
refusal with no words in it. It is NOT `billing:read`, which would have carried the spend
breakdown, the caps and the monthly statement with it (SEC-COMP §5 scopes those to the
owner); and it is NOT in `MUTATING_PERMISSIONS`, so a D-22 view-as operator can see a
client's wallet on a support call and can never spend from it.

## Money

Every rupee figure below is an exact `Decimal`, quantized once through `service.to_paise`
and published as a digit string. Nothing is summed in a browser: the drawdown buckets add
up to `spent_inr` because `billing/wallet.py` added them in SQL over `NUMERIC`, not
because a screen subtracted two strings (hard rule 7 reaches the frontend).

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from apps.api.billing.gst import supplier_identity
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import (
    LOW_BALANCE_INR,
    PAYMENT_REF_SQL,
    plan_tier_of,
    recorded_payments,
    to_paise,
)
from apps.api.billing.wallet import (
    ATTEMPT_LIMIT,
    BURN_WINDOW_DAYS,
    LEDGER_LIMIT,
    MAX_RUNWAY_DAYS,
    MIN_BURN_HISTORY_DAYS,
    Runway,
    read_attempts,
    read_wallet,
)
from apps.api.compliance.service import credits_exhausted
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/billing/wallet", tags=["billing"])

#: A READ, and `wallet:read` is the permission the whole router takes. Annotated rather
#: than `Depends()` in a default: this file is not `routes.py`, so it is outside the B008
#: per-file ignore.
WalletRead = Annotated[Principal, Depends(requires("wallet:read", realm="client"))]

#: The ceiling on the ledger page. Bounded because every list in this repository is
#: (`scripts/check_list_bounds.py`), and set to the same depth the operator's wallet shows
#: (`credit_routes.MAX_LIMIT` territory) so a support call is not two different screens.
MAX_LEDGER_LIMIT = 200


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunwayOut(Strict):
    """How long the balance lasts — and, when it may not be said, WHY not.

    `days` is null on every basis but `projected`, and `basis` carries which reason.
    "We have not been watching you long enough to tell" and "you are not spending
    anything" are different sentences to an owner deciding whether to top up, and a
    screen that collapsed them into a blank would answer neither.

    NO DEFAULTS on any field, for `TopUpIntentOut.provider_order_id`'s reason: a Pydantic
    default generates an OPTIONAL property in the TypeScript client, and `days: null`
    (we will not put a number on it) must stay distinguishable from `undefined` (the
    server did not say).
    """

    #: `projected` · `no_burn` · `too_new` · `empty`.
    basis: str
    #: Whole days, floored. Null unless `basis` is `projected` and `beyond_horizon` is
    #: false.
    days: int | None
    #: What this account spent per day over the window — the working behind `days`, so an
    #: owner who disagrees with "nine days" can see the ₹340 a day it came from.
    daily_burn_inr: Decimal | None
    #: How long we have actually been watching, in whole days. What makes `too_new`
    #: legible ("three days of history; we need seven") rather than a bare refusal.
    history_days: int
    #: True when the honest answer is "longer than we will put a number on".
    beyond_horizon: bool
    #: The window the burn was measured over and the floor it needed, published so the
    #: screen can say "over the last 30 days" without a second copy of the number.
    window_days: int
    min_history_days: int
    max_days: int


class DrawdownOut(Strict):
    """WHERE THE MONEY WENT, over the same window the runway was measured on.

    Every figure is POSITIVE and its direction is in the field name, never in a sign — a
    screen that had to decide whether `-340.00` was a debit or a correction of one is a
    screen that will eventually decide wrong.

    THERE IS NO MESSAGING BUCKET, and that is deliberate rather than missing: nothing on
    this platform debits the wallet for a WhatsApp message or an SMS, so a "Messaging"
    row reading ₹0.00 would be a category invented to look complete, and a client reading
    it would reasonably conclude they are being charged for messages.
    """

    calls_inr: Decimal
    ai_assist_inr: Decimal
    #: Operator corrections that took credit BACK. A correction that PUT credit back is
    #: money added and is counted in `added_inr`, where a client will look for it.
    adjustments_inr: Decimal
    #: The three above, summed in SQL — so the total on screen is by construction the sum
    #: of the rows beneath it.
    spent_inr: Decimal
    added_inr: Decimal
    refunded_inr: Decimal


class WalletOut(Strict):
    """Everything the credits screen needs about the money, in one read."""

    tenant_id: UUID
    #: False when this account has no wallet at all (an invoiced client). The screen shows
    #: the retainer story instead of a balance about nothing, and never offers a top-up
    #: the intent route is bound to refuse with `topup_not_available`.
    prepaid: bool
    balance_inr: Decimal
    is_low: bool
    low_balance_threshold_inr: Decimal
    #: THE DIAL GATE'S OWN VERDICT (`compliance.service.credits_exhausted`) — asked, never
    #: re-derived here. It is not `balance <= 0`: that comparison is tier-blind, and a
    #: managed client's dialling does not stop for a wallet they never bought.
    outbound_stopped: bool
    runway: RunwayOut
    #: Whole minutes of calling the balance buys at the live list rate. Null when this
    #: deployment quotes no rate — never a zero, which would tell a client with money in
    #: their wallet that they cannot call.
    minutes_left: int | None
    drawdown: DrawdownOut


class WalletEntryOut(Strict):
    """One line of the wallet, as its owner reads it.

    Deliberately NOT `credit_routes.LedgerEntryOut` — and named apart from it for a
    second, mechanical reason: two different schemas under one name make FastAPI emit
    fully-qualified component names for BOTH, which would rename the admin console's
    generated type out from under `lib/api/credits.ts`. That one carries `reversible_inr`,
    which exists so an OPERATOR can be offered a correction with a ceiling on it. It is
    meaningless to a client, and publishing it here would invite a screen to render a
    control this realm does not have.
    """

    id: UUID
    #: SIGNED — negative took credit off the wallet. The sign is the only place direction
    #: lives, and the screen reads it off the DIGITS rather than through `Number()`.
    delta_inr: Decimal
    #: `topup` · `usage` · `adjustment` · `refund` · `bonus`, as stored.
    reason: str
    ref: str | None
    balance_after_inr: Decimal
    occurred_at: datetime
    #: WHICH PAYMENT this row belongs to, or null when it is not a payment. It is what
    #: lets the screen offer a receipt beside the entry without doing string surgery on
    #: `ref` — a restated payment's own `ref` is `restated:<payment_ref>:<total>`, and
    #: taking that apart in a browser would be a second definition of "same payment".
    payment_ref: str | None


class WalletPaymentOut(Strict):
    """One payment, as the wallet holds it — the line a receipt is issued against."""

    payment_ref: str
    #: EVERYTHING that reference has credited, summed by the server across every row that
    #: belongs to it, including rows that have scrolled off this page.
    credited_inr: Decimal
    entries: int
    first_at: datetime


class LedgerOut(Strict):
    entries: list[WalletEntryOut]
    #: The payments behind the `topup` entries on this page, newest first. One line per
    #: payment however many ledger rows it took, which is what lets the screen offer
    #: exactly one receipt per payment.
    payments: list[WalletPaymentOut]


class TopUpAttemptOut(Strict):
    """A payment that was STARTED — including the ones that went nowhere.

    THE POINT OF THIS LIST is the rows a ledger cannot hold. A declined card moves no
    money, so it has no `credit_ledger` entry, so before it existed a client whose payment
    failed came back to a screen indistinguishable from one they had never touched.
    """

    id: UUID
    #: OUR reference — the one the client sees and quotes to us.
    receipt: str
    amount_inr: Decimal
    pack_id: str | None
    #: `settling` · `unfinished` · `captured` · `failed` — the SCREEN's word, derived
    #: server-side because it depends on a clock, so "how old is too old" has one
    #: definition rather than a timezone-dependent comparison in a browser.
    #:
    #: THERE IS DELIBERATELY NO `retryable` BESIDE IT. Trying again means starting a fresh
    #: top-up on `POST /v1/billing/topups/intent`, which is one control on one panel; a
    #: per-attempt retry flag would invite a SECOND control that starts a payment, and two
    #: controls that both mint an order is how a client ends up with two orders for one
    #: top-up. The provider's order id is likewise not published: nothing a client can do
    #: with it is safe, and it is an identifier of a payment (hard rule 6's neighbour).
    outcome: str
    started_at: datetime


class ReceiptOut(Strict):
    """A RECEIPT for one payment. It is NOT a tax invoice and never says it is.

    The business is not registered for GST and is not required to be at present turnover
    (`docs/legal/LEGAL-OPS-PLAYBOOK.md` §4), so `gst.supplier_identity().is_registered` is
    false on every deployment: there is no GSTIN to print, no tax is charged, and CGST
    s.32 forbids an unregistered person collecting any. `document_type` is therefore
    `receipt` — an acknowledgement that money was received — and the console renders its
    heading from THIS field, never from a literal, exactly as the monthly statement does.
    Nothing here carries a tax head, a rate, or an estimate of one.
    """

    document_type: str
    payment_ref: str
    amount_inr: Decimal
    received_at: datetime
    #: How many ledger rows the payment took. More than one means it was restated — the
    #: only place that is visible as such, and the reason `amount_inr` is the SUM.
    entries: int
    supplier_legal_name: str | None
    supplier_address: str | None
    organization_name: str
    organization_billing_email: str | None
    #: The sentence that says what this document is and is not. Server-owned, because a
    #: paraphrase in a browser would be a second statement about tax.
    note: str


#: What the receipt says about itself. It states the two facts a reader needs — money was
#: received, and no tax was charged — and it names neither a rate nor a registration that
#: does not exist.
RECEIPT_NOTE = (
    "This is a receipt for calling credit added to your account. No tax has been "
    "charged on it. It is not a tax invoice."
)


def _runway_out(runway: Runway) -> RunwayOut:
    """The dataclass `billing/wallet.py` computed, published.

    Separate from the dataclass on purpose: the wire shape carries the three CONSTANTS the
    projection was made under (`window_days`, `min_history_days`, `max_days`) so the
    screen can say "over the last 30 days" and "we need a week" without keeping its own
    copies of numbers that live in one module.
    """
    return RunwayOut(
        basis=runway.basis,
        days=runway.days,
        daily_burn_inr=(
            to_paise(runway.daily_burn_inr) if runway.daily_burn_inr is not None else None
        ),
        history_days=runway.history_days,
        beyond_horizon=runway.beyond_horizon,
        window_days=BURN_WINDOW_DAYS,
        min_history_days=MIN_BURN_HISTORY_DAYS,
        max_days=MAX_RUNWAY_DAYS,
    )


@router.get(
    "",
    response_model=WalletOut,
    openapi_extra=permission_meta("wallet:read"),
    summary="Balance, how long it lasts, and where the money went",
    description=(
        "The prepaid wallet as its owner reads it. `outbound_stopped` is the dial "
        "gate's own verdict, asked rather than re-derived — inbound calls are never "
        "stopped by a balance. `runway.days` is null whenever a projection may not "
        "honestly be asserted, and `runway.basis` says which reason."
    ),
)
async def read_wallet_summary(principal: WalletRead) -> WalletOut:
    """One read, one session, and the two VERDICTS asked from their owners.

    `prepaid` is the tier test and `outbound_stopped` is the compliance gate; both are
    resolved HERE and handed to `wallet.read_wallet`, which is what stops that module
    becoming a second credit gate — the one thing the founder's decision explicitly
    forbade ("be consistent with it, do NOT build a second credit check").
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    settings = get_settings()

    async with tenant_session(tenant_id) as session:
        tier = await plan_tier_of(session, tenant_id)
        prepaid = tier in PREPAID_TIERS
        # ASKED, not re-derived. It is False for an invoiced client by the gate's own
        # rule, so this is also the answer for a tenant with no wallet.
        stopped = await credits_exhausted(session, tenant_id=tenant_id)
        summary = await read_wallet(
            session,
            tenant_id=tenant_id,
            prepaid=prepaid,
            outbound_stopped=stopped,
            # Priced through the SAME function the usage panel calls, at the SAME live
            # rate the top-up flow prices from, so the runway on this screen, the runway
            # on the usage screen and the packs a client is offered cannot disagree.
            rate_inr_per_min=settings.self_serve_inr_per_min,
        )

    return WalletOut(
        tenant_id=tenant_id,
        prepaid=summary.prepaid,
        balance_inr=to_paise(summary.balance.amount_inr),
        is_low=summary.balance.is_low,
        low_balance_threshold_inr=to_paise(LOW_BALANCE_INR),
        outbound_stopped=summary.outbound_stopped,
        runway=_runway_out(summary.runway),
        minutes_left=summary.minutes_left,
        drawdown=DrawdownOut(
            calls_inr=to_paise(summary.drawdown.calls_inr),
            ai_assist_inr=to_paise(summary.drawdown.ai_assist_inr),
            adjustments_inr=to_paise(summary.drawdown.adjustments_inr),
            spent_inr=to_paise(summary.drawdown.spent_inr),
            added_inr=to_paise(summary.drawdown.added_inr),
            refunded_inr=to_paise(summary.drawdown.refunded_inr),
        ),
    )


@router.get(
    "/ledger",
    response_model=LedgerOut,
    openapi_extra=permission_meta("wallet:read"),
    summary="The wallet's entries, newest first, with the payments behind them",
    description=(
        "Every movement on the wallet — payments, call usage, pack bonuses, operator "
        "corrections and refunds — newest first. `payments` carries one line per "
        "payment on the page, which is what a receipt is issued against."
    ),
)
async def read_wallet_ledger(
    principal: WalletRead,
    limit: Annotated[int, Query(ge=1, le=MAX_LEDGER_LIMIT)] = LEDGER_LIMIT,
) -> LedgerOut:
    """The same query shape the operator's wallet runs, minus the reversible amounts.

    `payment_ref` comes out of `service.PAYMENT_REF_SQL` rather than being taken apart
    from `ref` here: a restatement's `ref` is `restated:<payment_ref>:<total>`, so pairing
    a row with its payment by string surgery would be a second definition of "the same
    payment", free to drift from the write path's.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    # RLS already scopes this; `tenant_id` is in the predicate as well
                    # because it is what makes it an index scan on
                    # `ix_credit_ledger_tenant_recent` (the argument `read_credits`
                    # records), and because it makes the answer depend on the argument
                    # rather than on which session it was handed.
                    "SELECT id, delta, reason, ref, balance_after, occurred_at, "
                    f"{PAYMENT_REF_SQL} "
                    "FROM credit_ledger WHERE tenant_id = :tid "
                    "ORDER BY occurred_at DESC, id DESC LIMIT :limit"
                ),
                {"tid": tenant_id, "limit": limit},
            )
        ).all()
        # Totals summed over ALL of each payment's rows, on or off this page — a payment
        # restated long ago whose anchor has scrolled away would otherwise be published at
        # less than it credited, which is a lie about money on the document a client
        # downloads.
        payments = await recorded_payments(
            session,
            tenant_id=tenant_id,
            payment_refs=sorted({str(row[6]) for row in rows if row[6] is not None}),
        )

    return LedgerOut(
        entries=[
            WalletEntryOut(
                id=UUID(str(row[0])),
                delta_inr=to_paise(Decimal(str(row[1]))),
                reason=str(row[2]),
                ref=str(row[3]) if row[3] is not None else None,
                balance_after_inr=to_paise(Decimal(str(row[4]))),
                occurred_at=row[5],
                payment_ref=str(row[6]) if row[6] is not None else None,
            )
            for row in rows
        ],
        payments=[
            WalletPaymentOut(
                payment_ref=payment.payment_ref,
                credited_inr=to_paise(payment.credited_inr),
                entries=payment.rows,
                first_at=payment.first_at,
            )
            # Newest first, matching the ledger's own ordering, so two panels on one
            # screen never disagree about which way round time runs.
            for payment in sorted(payments.values(), key=lambda p: p.first_at, reverse=True)
        ],
    )


@router.get(
    "/topups",
    response_model=list[TopUpAttemptOut],
    openapi_extra=permission_meta("wallet:read"),
    summary="Payments that were started — including the ones that failed or never landed",
    description=(
        "A declined card moves no money, so it has no ledger entry. This is the list "
        "that shows it happened, so a client whose payment failed does not come back "
        "to a screen indistinguishable from one they never touched."
    ),
)
async def read_topup_attempts(principal: WalletRead) -> list[TopUpAttemptOut]:
    """Bounded at `ATTEMPT_LIMIT` with no `limit` parameter, deliberately.

    This is a "what happened just now" list, not a history: an attempt older than the ten
    newest is answered by the ledger (if it became money) or by nothing (if it did not),
    and offering a page size would invite a screen to ask for a year of failed cards.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with tenant_session(tenant_id) as session:
        attempts = await read_attempts(session, tenant_id=tenant_id, limit=ATTEMPT_LIMIT)
    return [
        TopUpAttemptOut(
            id=attempt.id,
            receipt=attempt.receipt,
            amount_inr=to_paise(attempt.amount_inr),
            pack_id=attempt.pack_id,
            outcome=attempt.outcome,
            started_at=attempt.started_at,
        )
        for attempt in attempts
    ]


@router.get(
    "/receipts/{payment_ref}",
    response_model=ReceiptOut,
    openapi_extra=permission_meta("wallet:read"),
    summary="A receipt for one payment — NOT a tax invoice",
    description=(
        "An acknowledgement that money was received against this reference. The "
        "business is not registered for GST, so no tax is charged and no tax invoice "
        "can be issued; `document_type` says what this document is and the console "
        "renders its heading from that field."
    ),
)
async def read_payment_receipt(payment_ref: str, principal: WalletRead) -> ReceiptOut:
    """One payment, or a 404 — and the 404 is the tenancy boundary doing its job.

    `recorded_payments` runs inside `tenant_session`, so a reference that belongs to
    another organization returns nothing here for the same reason a cross-tenant SELECT
    returns zero rows: the RLS policy, not a comparison this function makes.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id

    async with tenant_session(tenant_id) as session:
        found = await recorded_payments(
            session, tenant_id=tenant_id, payment_refs=[payment_ref.strip()]
        )
        payment = found.get(payment_ref.strip())
        if payment is None:
            raise ProblemError.not_found("Payment")
        org = (
            await session.execute(
                text("SELECT name, billing_email FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
    if org is None:
        raise ProblemError.not_found("Organization")

    supplier = supplier_identity(get_settings())
    return ReceiptOut(
        # `receipt` unconditionally, and there is no branch here that could make it say
        # anything else: this document acknowledges money received for prepaid credit,
        # which is not a supply of service being invoiced. The GST fork lives on the
        # monthly statement (`billing/invoice.py`), where it belongs.
        document_type="receipt",
        payment_ref=payment.payment_ref,
        amount_inr=to_paise(payment.credited_inr),
        received_at=payment.first_at,
        entries=payment.rows,
        supplier_legal_name=supplier.legal_name,
        supplier_address=supplier.address,
        organization_name=str(org[0]),
        organization_billing_email=str(org[1]) if org[1] is not None else None,
        note=RECEIPT_NOTE,
    )


__all__ = [
    "MAX_LEDGER_LIMIT",
    "RECEIPT_NOTE",
    "ReceiptOut",
    "WalletEntryOut",
    "WalletOut",
    "WalletPaymentOut",
    "router",
]
