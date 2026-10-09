"""The account's FIRST PAYMENT, and everything it unlocks (D-697).

`on_payment_credited` is the ONE hook every payment-credit path calls, in the transaction
that credits the money, after the ledger row is written. Today that is the gateway top-up
(`payments.credit_captured_payment`) and the bank transfer an operator credits to the wallet
(`credit_routes.record_topup` and its restatement twin). On the first such payment at or
above the minimum top-up it, once:

1. stamps `organizations.first_paid_at` / `first_paid_via` (`WHERE first_paid_at IS NULL`,
   so a replay or a second payment changes nothing);
2. ends a running trial as `converted` (the counters restart, `trials.end_trial`), or keeps
   the data of a trial that already ended without a sale (clears its pending `erase_after`);
3. owes the account its own voice workspace (`queue_workspace_provisioning`, through the
   outbox, in this same transaction).

**A GOODWILL GRANT IS NOT A PAYMENT.** `reason = 'grant'` and `'bonus'` rows never reach
this hook: a grant is credit we gave, not money the client paid, and counting it would let an
operator's gesture unlock KYC, numbers and live calling for an account that has paid nothing.

`PAID_TENANT_SQL` is THE predicate "this account has paid", in SQL, for the directory reads
(the workspace backfill); `has_paid` is the same question for one tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.trials import PAID_REASON, TRIAL_ACTIVE, end_trial, read_trial
from apps.api.compliance.audit import write_audit
from apps.api.core.logging import get_logger
from apps.api.tenancy.engine_workspace import queue_workspace_provisioning

log = get_logger(__name__)

#: How a payment reached the wallet: a gateway top-up, or a bank transfer an operator
#: credited. A subset of `tenancy.models.FIRST_PAID_VIA` (the backfill's `before_d697` is the
#: rest).
PaymentVia = Literal["wallet_topup", "manual_topup"]

#: THE predicate "this account has made its first payment", on `organizations` aliased `o`.
PAID_TENANT_SQL: Final = "o.first_paid_at IS NOT NULL"


async def has_paid(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Has this account made its first payment? One primary-key read."""
    row = await session.execute(
        text(f"SELECT {PAID_TENANT_SQL} FROM organizations o WHERE o.id = :tid"),
        {"tid": tenant_id},
    )
    return bool(row.scalar())


def _minimum_top_up() -> Decimal:
    # The minimum a client may top up, read where the top-up intent enforces it. Imported
    # here: `payment_routes` imports the payment modules that call this hook.
    from apps.api.billing.payment_routes import MIN_TOPUP_INR

    return MIN_TOPUP_INR


async def on_payment_credited(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    amount_inr: Decimal,
    via: PaymentVia,
    at: datetime | None = None,
) -> bool:
    """Record that money reached this wallet. True only for the account's FIRST payment.

    Call it in the crediting transaction, after the `topup` ledger row is written, for every
    positive payment credit; it decides itself whether this one is the first. Never for a
    grant, a bonus, an adjustment or a refund. Does not commit.
    """
    if amount_inr < _minimum_top_up():
        return False
    now = at or datetime.now(UTC)
    claimed = (
        await session.execute(
            text(
                "UPDATE organizations SET first_paid_at = :at, first_paid_via = :via, "
                "updated_at = now() WHERE id = :tid AND first_paid_at IS NULL RETURNING id"
            ),
            {"at": now, "via": via, "tid": tenant_id},
        )
    ).first()
    if claimed is None:
        return False

    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is not None and trial.status == TRIAL_ACTIVE:
        await end_trial(
            session, tenant_id=tenant_id, outcome="converted", reason=PAID_REASON, at=now
        )
    elif trial is not None and trial.erase_after is not None and trial.erasure_filed_at is None:
        # A trial that ended without a sale had this client's data scheduled for erasure.
        # They have now bought; their leads and calls are the value they built.
        await session.execute(
            text("UPDATE tenant_trials SET erase_after = NULL, updated_at = :at WHERE id = :id"),
            {"at": now, "id": trial.id},
        )
    workspace_owed = await queue_workspace_provisioning(session, tenant_id=tenant_id)
    await write_audit(
        session,
        action="account.first_payment",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="organizations",
        object_id=str(tenant_id),
        summary={
            "via": via,
            "amount_inr": str(amount_inr),
            "trial_converted": str(trial is not None and trial.status == TRIAL_ACTIVE),
            "workspace_queued": str(workspace_owed),
        },
    )
    log.info(
        "account_first_payment",
        extra={"tenant_id": str(tenant_id), "via": via, "workspace_queued": workspace_owed},
    )
    return True


__all__ = ["PAID_TENANT_SQL", "PaymentVia", "has_paid", "on_payment_credited"]
