"""Chargebacks and disputes against a client's payment (D-699).

Razorpay raises a dispute when a customer or their bank challenges a payment; its states
are `open`, `under_review`, `won`, `lost` and `closed`, and a dispute we accept becomes
`lost` irreversibly (`api/disputes/entity.md`, `api/disputes/accept.md`, read 9 Oct 2026).
If we lose, the amount is deducted from our Razorpay balance (`payments/disputes.md`).

WHAT HAPPENS HERE, PER EVENT (`webhooks/disputes.md`)
- `payment.dispute.created` (or the first event we see for a dispute): the disputed amount
  is HELD against the client's credit as a compensating `adjustment` entry
  (`meta.kind = dispute_hold`, ref `dispute_hold:<id>`, idempotent on the ledger's unique
  index), the outbound gate refuses while a dispute is open (`dispute_hold_active`), and
  the admin is alerted (`payment_dispute_opened`). Inbound is untouched.
- `won` and `closed`: the hold is released by a compensating credit
  (`dispute_release:<id>`), back onto the purchase's own lot at its frozen rates. `closed`
  releases too: Razorpay closes a fraud dispute after we either explain the payment or
  refund it, and a refund records its own debit through `refund.processed`.
- `lost`: the hold stands as the final debit; Razorpay has taken the money from us.
- `under_review`, `action_required`: the row is updated and, for the second, the admin is
  alerted to add evidence.

The admin contests (evidence documents plus a summary, `api/disputes/contest.md`, at least
one document required) or accepts (`api/disputes/accept.md`) from the disputes page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.dispute_hold import DISPUTE_HOLD_REASON, OPEN_STATES, dispute_hold_active
from apps.api.billing.lots import split_meta
from apps.api.billing.payments import PROVIDER, paise_to_inr
from apps.api.billing.service import (
    apply_credit_to_lots,
    find_entry_by_ref,
    find_topup,
    lock_tenant_credits,
    lot_of_entry,
    rate_card_at,
    record_entry,
    remove_credit_from_lots,
    to_paise,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

DISPUTE_HOLD_KIND: Final = "dispute_hold"
DISPUTE_RELEASE_KIND: Final = "dispute_release"


@dataclass(frozen=True, slots=True)
class DisputeFacts:
    """OUR normalized dispute, read from `payload.dispute.entity`."""

    dispute_id: str
    payment_id: str
    amount_inr: Decimal
    status: str
    phase: str | None
    reason_code: str | None
    respond_by: datetime | None


def extract_dispute(envelope: Any) -> DisputeFacts:
    """`payload.dispute.entity` → `DisputeFacts`, or `dispute_payload_unrecognized`."""
    entity: Any = None
    if isinstance(envelope, dict):
        payload = envelope.get("payload")
        dispute = payload.get("dispute") if isinstance(payload, dict) else None
        entity = dispute.get("entity") if isinstance(dispute, dict) else None
    did = entity.get("id") if isinstance(entity, dict) else None
    pid = entity.get("payment_id") if isinstance(entity, dict) else None
    status = entity.get("status") if isinstance(entity, dict) else None
    if not (isinstance(did, str) and isinstance(pid, str) and isinstance(status, str)):
        raise ProblemError.business_rule(
            "dispute_payload_unrecognized",
            "This dispute event did not match the shape this deployment can read.",
            remediation="Nothing was recorded. Check the provider's event format.",
        )
    if str(entity.get("currency") or "").upper() != "INR":
        raise ProblemError.business_rule(
            "payment_currency_unsupported",
            "This account settles in Indian rupees only.",
            remediation="Nothing was recorded. Handle this dispute by hand.",
        )
    respond_by = entity.get("respond_by")

    def _s(key: str) -> str | None:
        value = entity.get(key)
        return value if isinstance(value, str) and value else None

    return DisputeFacts(
        dispute_id=did,
        payment_id=pid,
        amount_inr=paise_to_inr(entity.get("amount")),
        status=status,
        phase=_s("phase"),
        reason_code=_s("reason_code"),
        respond_by=(
            datetime.fromtimestamp(respond_by, UTC)
            if isinstance(respond_by, int) and not isinstance(respond_by, bool)
            else None
        ),
    )


async def apply_dispute_event(
    session: AsyncSession, *, tenant_id: UUID, event: str, dispute: DisputeFacts
) -> str:
    """Record one dispute event in the caller's transaction. Returns what it did."""
    await lock_tenant_credits(session, tenant_id)
    existing = (
        await session.execute(
            text("SELECT id, hold_inr FROM payment_disputes WHERE dispute_id = :did"),
            {"did": dispute.dispute_id},
        )
    ).first()
    action_required = event == "payment.dispute.action_required"
    if existing is None:
        await session.execute(
            text(
                "INSERT INTO payment_disputes (id, tenant_id, dispute_id, payment_id, "
                "amount_inr, status, phase, reason_code, respond_by, hold_inr, "
                "action_required, last_event) VALUES (:id, :tid, :did, :pid, :amt, :st, "
                ":phase, :reason, :respond, 0, :action, :event)"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "did": dispute.dispute_id,
                "pid": dispute.payment_id,
                "amt": dispute.amount_inr,
                "st": dispute.status,
                "phase": dispute.phase,
                "reason": dispute.reason_code,
                "respond": dispute.respond_by,
                "action": action_required,
                "event": event,
            },
        )
    else:
        await session.execute(
            text(
                "UPDATE payment_disputes SET status = :st, phase = COALESCE(:phase, phase), "
                "respond_by = COALESCE(:respond, respond_by), action_required = :action, "
                "last_event = :event, updated_at = now() WHERE dispute_id = :did"
            ),
            {
                "st": dispute.status,
                "phase": dispute.phase,
                "respond": dispute.respond_by,
                "action": action_required,
                "event": event,
                "did": dispute.dispute_id,
            },
        )

    outcome = "recorded"
    if dispute.status in OPEN_STATES:
        if await _hold(session, tenant_id=tenant_id, dispute=dispute):
            outcome = "held"
            alert(
                "ROUTE_HANDLER",
                "payment_dispute_opened",
                detail="A client payment is disputed. Outbound calling is paused for that "
                "account until the dispute is resolved: /admin/payments/disputes.",
                tenant_id=str(tenant_id),
                dispute_id=dispute.dispute_id,
            )
    elif dispute.status in ("won", "closed") and await _release(
        session, tenant_id=tenant_id, dispute=dispute
    ):
        outcome = "released"
    if action_required:
        alert(
            "ROUTE_HANDLER",
            "payment_dispute_action_required",
            detail="The bank asked for more evidence on a disputed payment.",
            tenant_id=str(tenant_id),
            dispute_id=dispute.dispute_id,
        )
    await write_audit(
        session,
        action="payment.dispute",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="payment_disputes",
        object_id=dispute.dispute_id,
        summary={
            "event": event,
            "status": dispute.status,
            "payment_ref": dispute.payment_id,
            "amount_inr": str(to_paise(dispute.amount_inr)),
            "outcome": outcome,
        },
    )
    log.info(
        "razorpay_dispute_applied",
        extra={"tenant_id": str(tenant_id), "dispute_id": dispute.dispute_id, "outcome": outcome},
    )
    return outcome


async def _hold(session: AsyncSession, *, tenant_id: UUID, dispute: DisputeFacts) -> bool:
    ref = f"{DISPUTE_HOLD_KIND}:{dispute.dispute_id}"
    if await find_entry_by_ref(session, tenant_id=tenant_id, reason="adjustment", ref=ref):
        return False
    paid = await find_topup(session, tenant_id=tenant_id, ref=dispute.payment_id)
    removal = await remove_credit_from_lots(
        session,
        tenant_id=tenant_id,
        corrected_entry_id=None if paid is None else paid.entry_id,
        amount_inr=dispute.amount_inr,
    )
    meta: dict[str, Any] = {
        "kind": DISPUTE_HOLD_KIND,
        "source": PROVIDER,
        "dispute_ref": dispute.dispute_id,
        "payment_ref": dispute.payment_id,
    }
    if removal.splits:
        meta["lots"] = split_meta(removal.splits)
    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-dispute.amount_inr,
        reason="adjustment",
        ref=ref,
        meta=meta,
        allow_negative=True,
    )
    await session.execute(
        text("UPDATE payment_disputes SET hold_inr = :amt WHERE dispute_id = :did"),
        {"amt": dispute.amount_inr, "did": dispute.dispute_id},
    )
    return True


async def _release(session: AsyncSession, *, tenant_id: UUID, dispute: DisputeFacts) -> bool:
    hold = await find_entry_by_ref(
        session,
        tenant_id=tenant_id,
        reason="adjustment",
        ref=f"{DISPUTE_HOLD_KIND}:{dispute.dispute_id}",
    )
    ref = f"{DISPUTE_RELEASE_KIND}:{dispute.dispute_id}"
    if hold is None or await find_entry_by_ref(
        session, tenant_id=tenant_id, reason="adjustment", ref=ref
    ):
        return False
    amount = abs(hold.amount_inr)
    balance = await record_entry(
        session,
        tenant_id=tenant_id,
        delta=amount,
        reason="adjustment",
        ref=ref,
        meta={
            "kind": DISPUTE_RELEASE_KIND,
            "source": PROVIDER,
            "dispute_ref": dispute.dispute_id,
            "payment_ref": dispute.payment_id,
        },
    )
    released = await find_entry_by_ref(session, tenant_id=tenant_id, reason="adjustment", ref=ref)
    assert released is not None
    paid = await find_topup(session, tenant_id=tenant_id, ref=dispute.payment_id)
    lot = None if paid is None else await lot_of_entry(session, ledger_entry_id=paid.entry_id)
    await apply_credit_to_lots(
        session,
        tenant_id=tenant_id,
        credits_inr=amount,
        balance_after=balance.amount_inr,
        rates=(await rate_card_at(session, at=datetime.now(UTC))).for_purchase(
            pack_id=None, amount_inr=amount
        ),
        source="topup",
        pack_id=None,
        ledger_entry_id=released.entry_id,
        restate_lot_id=None if lot is None else lot.lot_id,
    )
    return True


# --- the admin queue --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DisputeRow:
    tenant_id: UUID
    tenant_name: str | None
    dispute_id: str
    payment_id: str
    amount_inr: Decimal
    hold_inr: Decimal
    status: str
    phase: str | None
    reason_code: str | None
    respond_by: datetime | None
    action_required: bool
    created_at: datetime


async def list_disputes(*, include_closed: bool = False, limit: int = 200) -> list[DisputeRow]:
    """Every client's disputes, open first. Untenanted, through the ops-read policy; the
    name comes from the client directory the admin session already reads."""
    where = "" if include_closed else "WHERE d.status IN ('open', 'under_review')"
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, dispute_id, payment_id, amount_inr, hold_inr, status, "
                    "phase, reason_code, respond_by, action_required, created_at "
                    f"FROM payment_disputes d {where} "
                    "ORDER BY (status IN ('open', 'under_review')) DESC, respond_by NULLS LAST, "
                    "created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).all()
    return [
        DisputeRow(
            tenant_id=UUID(str(r[0])),
            tenant_name=None,
            dispute_id=str(r[1]),
            payment_id=str(r[2]),
            amount_inr=to_paise(Decimal(str(r[3]))),
            hold_inr=to_paise(Decimal(str(r[4]))),
            status=str(r[5]),
            phase=r[6],
            reason_code=r[7],
            respond_by=r[8],
            action_required=bool(r[9]),
            created_at=r[10],
        )
        for r in rows
    ]


async def dispute_tenant(dispute_id: str) -> UUID | None:
    """Which tenant a dispute belongs to, read untenanted."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT tenant_id FROM payment_disputes WHERE dispute_id = :did"),
                {"did": dispute_id},
            )
        ).first()
    return None if row is None else UUID(str(row[0]))


__all__ = [
    "DISPUTE_HOLD_KIND",
    "DISPUTE_HOLD_REASON",
    "DISPUTE_RELEASE_KIND",
    "OPEN_STATES",
    "DisputeFacts",
    "DisputeRow",
    "apply_dispute_event",
    "dispute_hold_active",
    "dispute_tenant",
    "extract_dispute",
    "list_disputes",
]
