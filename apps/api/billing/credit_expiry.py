"""Credit bought in a pack lapses some months after purchase (D-840, founder 20 Oct 2026).

THE TERM IS FIXED AT PURCHASE. A pack purchase opens its lot with `credit_lots.expires_at`
set from `Settings.credit_pack_expiry_months` at that instant (`service.apply_credit_to_lots`),
and the column is frozen with the lot's other terms, so changing the setting later changes
nothing a client already bought. A lot opened while the setting was unset never expires.

THE SWITCH IS GATED ON THE TERMS. Our published Terms and refund policy say credit does not
expire, so the setting is refused (`assert_expiry_may_switch_on`) and ignored
(`credit_expiry_months`) until `TERMS_REVISION_STATING_EXPIRY` names the Terms revision in
`legal/catalogue.DOCUMENTS` that says otherwise. That revision is the founder's to approve.

EXPIRY IS AN APPEND, NEVER AN EDIT (hard rule 4). `expire_lot` writes one `adjustment` row on
`credit_ledger` for the credit still on the lot (negative, `meta.kind = credit_expiry`, keyed
`credit_expiry:<lot_id>` so a replay writes nothing) and closes the lot through the same CAS a
re-price uses. Only credit still unspent lapses; a lot already spent has nothing to expire.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import lots as credit_lots
from apps.api.billing.plans import IST
from apps.api.billing.service import find_entry_by_ref, lock_tenant_credits, record_entry
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

#: The Terms revision (`legal/catalogue.DOCUMENTS`, slug `terms`) that states credit expiry.
#: None until the founder approves that wording and it is published; while None, the
#: expiry setting is refused and ignored.
TERMS_REVISION_STATING_EXPIRY: Final[str | None] = None

#: `credit_ledger.meta.kind` of an expiry row; `reason` stays `adjustment`.
CREDIT_EXPIRY_META_KIND: Final = "credit_expiry"
CREDIT_EXPIRY_REF_PREFIX: Final = "credit_expiry"

#: How many lots one tenant's sweep expires per run; the rest wait a day.
EXPIRY_BATCH: Final = 200


def credit_expiry_ref(lot_id: UUID) -> str:
    return f"{CREDIT_EXPIRY_REF_PREFIX}:{lot_id}"


def _terms_state_expiry() -> bool:
    from apps.api.legal.catalogue import DOCUMENTS

    if TERMS_REVISION_STATING_EXPIRY is None:
        return False
    terms = next(doc for doc in DOCUMENTS if doc.slug == "terms")
    return any(rev.revision == TERMS_REVISION_STATING_EXPIRY for rev in terms.revisions)


def credit_expiry_months() -> int | None:
    """The months a pack bought NOW lapses after, or None when credit does not expire."""
    months = get_settings().credit_pack_expiry_months
    return months if months is not None and _terms_state_expiry() else None


def assert_expiry_may_switch_on(months: object) -> None:
    """Refuse setting `credit_pack_expiry_months` while the Terms still say credit does not
    expire. Clearing it is always allowed."""
    if months is None or _terms_state_expiry():
        return
    raise ProblemError.business_rule(
        "credit_expiry_terms_not_published",
        "Credit cannot be set to expire yet: the published Terms say credit does not expire.",
        remediation=(
            "Publish a Terms revision that states the expiry, approved by the founder, and "
            "name it in billing/credit_expiry.TERMS_REVISION_STATING_EXPIRY; then set this."
        ),
    )


def expires_at_for(opened_at: datetime, *, months: int) -> datetime:
    """`opened_at` moved `months` calendar months on in IST, the day clamped to the month's
    last: bought on 31 Jan with 1 month, it lapses on 28/29 Feb at the same time of day."""
    local = opened_at.astimezone(IST)
    index = local.month - 1 + months
    year, month = local.year + index // 12, index % 12 + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day)


@dataclass(frozen=True, slots=True)
class ExpiredLot:
    lot_id: UUID
    credits_inr: Decimal


_DUE_SQL = (
    "SELECT id FROM credit_lots WHERE closed_at IS NULL AND expires_at IS NOT NULL "
    "AND expires_at <= :now ORDER BY expires_at, id LIMIT :cap"
)


async def expire_lot(
    session: AsyncSession, *, tenant_id: UUID, lot_id: UUID, now: datetime
) -> ExpiredLot | None:
    """Lapse the credit left on one due lot. None when it was already expired, spent, or not
    due; the caller's transaction commits the ledger row and the close together."""
    await lock_tenant_credits(session, tenant_id)
    ref = credit_expiry_ref(lot_id)
    if await find_entry_by_ref(session, tenant_id=tenant_id, reason="adjustment", ref=ref):
        return None
    lot = await credit_lots.read_lot(session, lot_id=lot_id)
    if (
        lot is None
        or lot.closed_at is not None
        or lot.expires_at is None
        or lot.expires_at > now
        or lot.credits_remaining <= 0
    ):
        return None
    # Under the credit lock no other writer can move this lot between the read and the CAS.
    closed = await credit_lots.close_lot(
        session, lot_id=lot_id, seen_remaining=lot.credits_remaining
    )
    assert closed, "a lot read under the credit lock moved before its CAS"
    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-lot.credits_remaining,
        reason="adjustment",
        ref=ref,
        meta={
            "kind": CREDIT_EXPIRY_META_KIND,
            "lot_id": str(lot_id),
            "expires_at": lot.expires_at.isoformat(),
            "credits_inr": str(lot.credits_remaining),
        },
    )
    return ExpiredLot(lot_id=lot_id, credits_inr=lot.credits_remaining)


async def due_lots(session: AsyncSession, *, now: datetime) -> list[UUID]:
    """This tenant's open lots past their expiry, oldest expiry first (RLS scopes them)."""
    rows = await session.execute(text(_DUE_SQL), {"now": now, "cap": EXPIRY_BATCH})
    return [UUID(str(row)) for row in rows.scalars()]


__all__ = [
    "CREDIT_EXPIRY_META_KIND",
    "CREDIT_EXPIRY_REF_PREFIX",
    "EXPIRY_BATCH",
    "TERMS_REVISION_STATING_EXPIRY",
    "ExpiredLot",
    "assert_expiry_may_switch_on",
    "credit_expiry_months",
    "credit_expiry_ref",
    "due_lots",
    "expire_lot",
    "expires_at_for",
]
