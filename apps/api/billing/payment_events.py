"""What each verified Razorpay event does (D-699); the receiver is `payment_routes`.

Everything here runs AFTER the signature has verified, and none of it calls Razorpay: each
handler is database work in one transaction (the inbox claim, the ledger, the state rows,
the audit row and any outbox notice commit together), so the 200 goes back well inside
Razorpay's 5-second window (`webhooks/best-practices.md`, read 9 Oct 2026) and anything
slow — an email, an alert mail — is the outbox's or the alert thread's.

Dedupe is two layers, as before: the inbox, keyed on Razorpay's `x-razorpay-event-id` when
the delivery carries one and on `<event>:<object id>` when it does not, and the ledger's
own `ref` under `lock_tenant_credits`, which is the guarantee.

`apply_captured` is ALSO the reconciliation's credit path (`billing/reconciliation.py`), so
a payment whose webhook was lost is credited by exactly the code that would have credited
it, and lands on the same ledger `ref`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from apps.api.admin.service import tenant_exists
from apps.api.billing.auto_recharge import (
    apply_token_status,
    note_mandate_payment,
    settle_charge,
    token_status_of_event,
)
from apps.api.billing.disputes import apply_dispute_event, extract_dispute
from apps.api.billing.payment_objects import (
    AUTO_RECHARGE,
    MANDATE,
    ObjectRoute,
    route_for,
    verify_order,
)
from apps.api.billing.payments import (
    NOTES_TENANT_KEY,
    PROVIDER,
    CapturedPayment,
    RefundEvent,
    credit_captured_payment,
    credit_refund,
    extract_captured_payment,
    extract_refund,
    find_topup,
    payment_attempt_ids,
    payment_order_id,
    refund_idempotency_key,
    release_refund_claim,
)
from apps.api.billing.service import get_balance, to_paise
from apps.api.billing.wallet import settle_attempt
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.reliability.service import body_hash, claim_inbox_event, mark_inbox_processed

log = get_logger(__name__)

EventStatus = Literal[
    "credited",
    "refunded",
    "duplicate",
    "failed",
    "ignored",
    "authorized",
    "refund_failed",
    "mandate",
    "dispute",
]

_UNKNOWN_TENANT: Final = "razorpay_unknown_tenant"


@dataclass(frozen=True, slots=True)
class EventResult:
    status: EventStatus
    payment_id: str | None = None
    entry_id: UUID | None = None
    amount_inr: Decimal | None = None
    balance_inr: Decimal | None = None


def _entity(envelope: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(envelope, dict):
        return None
    payload = envelope.get("payload")
    holder = payload.get(name) if isinstance(payload, dict) else None
    entity = holder.get("entity") if isinstance(holder, dict) else None
    return entity if isinstance(entity, dict) else None


def _notes_tenant(entity: dict[str, Any] | None) -> UUID | None:
    notes = entity.get("notes") if entity else None
    raw = notes.get(NOTES_TENANT_KEY) if isinstance(notes, dict) else None
    try:
        return UUID(str(raw)) if raw else None
    except ValueError:
        return None


async def _require_tenant(session: Any, tenant_id: UUID) -> None:
    if not await tenant_exists(session, tenant_id):
        alert("ROUTE_HANDLER", _UNKNOWN_TENANT)
        raise ProblemError.not_found("Organization")


async def apply_captured(
    envelope: Any,
    *,
    event: str,
    event_id: str | None,
    ip: str | None = None,
    payment: CapturedPayment | None = None,
    route: ObjectRoute | None = None,
) -> EventResult:
    """A captured payment → one `credit_ledger` top-up and its side effects.

    The reconciliation passes `payment`/`route` it already read from the API, and no
    envelope inbox key (the ledger ref is the guarantee there).
    """
    if payment is None:
        route = await route_for(payment_order_id(envelope))
        payment = extract_captured_payment(
            envelope, tenant_hint=None if route is None else route.tenant_id
        )
    verify_order(payment, route)
    async with tenant_session(payment.tenant_id) as session:
        await _require_tenant(session, payment.tenant_id)
        claim = None
        if envelope is not None:
            claim = await claim_inbox_event(
                session,
                provider=PROVIDER,
                event_key=event_id or f"{event}:{payment.payment_id}",
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
                return EventResult(
                    status="duplicate",
                    payment_id=payment.payment_id,
                    entry_id=existing[0] if existing else None,
                    amount_inr=to_paise(existing[1]) if existing else None,
                    balance_inr=to_paise(balance.amount_inr),
                )

        result = await credit_captured_payment(session, payment=payment, ip=ip)
        # The attempt is marked in the SAME transaction as the credit, so the client's
        # screen and wallet cannot disagree. `captured` is terminal in `settle_attempt`.
        if payment.order_id is not None:
            await settle_attempt(
                session,
                tenant_id=payment.tenant_id,
                order_id=payment.order_id,
                payment_id=payment.payment_id,
                status="captured",
            )
        if route is not None and route.purpose == MANDATE and payment.order_id is not None:
            await note_mandate_payment(
                session,
                tenant_id=payment.tenant_id,
                order_id=payment.order_id,
                token_id=payment.token_id,
            )
        if route is not None and route.purpose == AUTO_RECHARGE and payment.order_id is not None:
            await settle_charge(
                session,
                tenant_id=payment.tenant_id,
                order_id=payment.order_id,
                payment_id=payment.payment_id,
                captured=True,
            )
        if payment.international and result.recorded:
            # Credited: the money is real. Alarmed: international cards should be off on
            # the account (`runbooks/topup-payments.md` §1).
            alert(
                "ROUTE_HANDLER",
                "razorpay_international_payment",
                detail="An international-card payment was captured although international "
                "payments should be disabled on the Razorpay account.",
                payment_id=payment.payment_id,
            )
        if claim is not None:
            await mark_inbox_processed(session, row_id=claim.row_id)
    return EventResult(
        status="credited" if result.recorded else "duplicate",
        payment_id=payment.payment_id,
        entry_id=result.entry_id,
        amount_inr=to_paise(payment.amount_inr),
        balance_inr=to_paise(result.balance.amount_inr),
    )


async def apply_payment_state(envelope: Any, *, event: str, failed: bool) -> EventResult:
    """`payment.authorized` / `payment.failed`: no money moves. The attempt row moves to
    `authorized` or `failed`; a failed auto-recharge debit is counted against the switch.
    Best-effort by design: an event we cannot place is acked, never retried for ever."""
    route = await route_for(payment_order_id(envelope))
    attempt = payment_attempt_ids(envelope, tenant_hint=None if route is None else route.tenant_id)
    if attempt is None:
        return EventResult(status="failed" if failed else "authorized")
    entity = _entity(envelope, "payment") or {}
    error_code = entity.get("error_code")
    async with tenant_session(attempt.tenant_id) as session:
        await settle_attempt(
            session,
            tenant_id=attempt.tenant_id,
            order_id=attempt.order_id,
            payment_id=attempt.payment_id,
            status="failed" if failed else "authorized",
        )
        if failed and route is not None and route.purpose == AUTO_RECHARGE:
            await settle_charge(
                session,
                tenant_id=attempt.tenant_id,
                order_id=attempt.order_id,
                payment_id=attempt.payment_id,
                captured=False,
                failure_code=error_code if isinstance(error_code, str) else None,
            )
    return EventResult(status="failed" if failed else "authorized", payment_id=attempt.payment_id)


async def apply_refund_processed(
    envelope: Any, *, event: str, event_id: str | None, ip: str | None
) -> EventResult:
    """A processed refund → one COMPENSATING `credit_ledger` entry, deduped twice."""
    refund = extract_refund(envelope)
    async with tenant_session(refund.tenant_id) as session:
        await _require_tenant(session, refund.tenant_id)
        claim = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=event_id or f"{event}:{refund.refund_id}",
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
            return EventResult(
                status="duplicate",
                payment_id=refund.payment_id,
                balance_inr=to_paise(balance.amount_inr),
            )
        result = await credit_refund(session, refund=refund, ip=ip)
        await mark_inbox_processed(session, row_id=claim.row_id)
    return EventResult(
        status="refunded" if result.recorded else "duplicate",
        payment_id=refund.payment_id,
        entry_id=result.entry_id,
        amount_inr=to_paise(refund.amount_inr),
        balance_inr=to_paise(result.balance.amount_inr),
    )


async def apply_refund_failed(envelope: Any) -> EventResult:
    """A refund Razorpay could not process: no money left us, so the claim it held on the
    payment's refund ceiling is released and the admin is told (`razorpay_refund_failed`)."""
    refund: RefundEvent = extract_refund(envelope)
    async with tenant_session(refund.tenant_id) as session:
        await _require_tenant(session, refund.tenant_id)
        await release_refund_claim(
            session,
            tenant_id=refund.tenant_id,
            refund_key=refund_idempotency_key(
                payment_id=refund.payment_id, amount_inr=refund.amount_inr
            ),
        )
        await write_audit(
            session,
            action="refund.failed",
            actor_type="system",
            tenant_id=refund.tenant_id,
            object_type="credit_ledger",
            object_id=refund.refund_id,
            summary={
                "refund_ref": refund.refund_id,
                "payment_ref": refund.payment_id,
                "amount_inr": str(to_paise(refund.amount_inr)),
            },
        )
    alert(
        "ROUTE_HANDLER",
        "razorpay_refund_failed",
        detail="A refund could not be processed by Razorpay. Nothing left the client's wallet; "
        "issue it again or pay it by bank transfer.",
        tenant_id=str(refund.tenant_id),
        refund_id=refund.refund_id,
    )
    return EventResult(status="refund_failed", payment_id=refund.payment_id)


async def apply_token(envelope: Any, *, event: str) -> EventResult:
    """`token.confirmed|rejected|cancelled|paused` → the mandate's state. A token we do not
    know yet (its route is written when the authorisation payment or the browser's return
    reaches us) is acked; the mandate sweep reads its state from Razorpay instead."""
    entity = _entity(envelope, "token")
    token_id = entity.get("id") if entity else None
    status = token_status_of_event(event)
    if not isinstance(token_id, str) or status is None:
        return EventResult(status="ignored")
    route = await route_for(token_id)
    if route is None:
        log.info("razorpay_token_unrouted", extra={"event": event})
        return EventResult(status="ignored")
    async with tenant_session(route.tenant_id) as session:
        await apply_token_status(
            session, tenant_id=route.tenant_id, token_id=token_id, status=status
        )
    return EventResult(status="mandate")


async def apply_dispute(envelope: Any, *, event: str, event_id: str | None) -> EventResult:
    """A `payment.dispute.*` event: tenant from the disputed payment's notes or OUR order
    record, then `disputes.apply_dispute_event`."""
    dispute = extract_dispute(envelope)
    payment_entity = _entity(envelope, "payment")
    tenant_id = _notes_tenant(payment_entity)
    if tenant_id is None:
        route = await route_for(payment_order_id(envelope))
        tenant_id = None if route is None else route.tenant_id
    if tenant_id is None:
        alert("ROUTE_HANDLER", _UNKNOWN_TENANT)
        raise ProblemError.not_found("Organization")
    async with tenant_session(tenant_id) as session:
        await _require_tenant(session, tenant_id)
        claim = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=event_id or f"{event}:{dispute.dispute_id}",
            payload_hash=body_hash(
                {"dispute_id": dispute.dispute_id, "status": dispute.status, "event": event}
            ),
            event_name=event,
        )
        if claim.state == "duplicate":
            return EventResult(status="duplicate", payment_id=dispute.payment_id)
        await apply_dispute_event(session, tenant_id=tenant_id, event=event, dispute=dispute)
        await mark_inbox_processed(session, row_id=claim.row_id)
    return EventResult(status="dispute", payment_id=dispute.payment_id)


__all__ = [
    "EventResult",
    "EventStatus",
    "apply_captured",
    "apply_dispute",
    "apply_payment_state",
    "apply_refund_failed",
    "apply_refund_processed",
    "apply_token",
]
