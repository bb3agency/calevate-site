"""The account's FIRST PAYMENT, and everything it unlocks (D-697, D-859).

`on_payment_credited` is the ONE hook every payment-credit path calls, in the transaction
that credits the money, after the ledger row is written: the gateway top-up
(`payments.credit_captured_payment`), the bank transfer an operator credits to the wallet
(`credit_routes.record_topup`) and its restatement (`credit_routes.record_restatement`, which
passes the restated total, so a transfer first recorded short of the minimum counts once it is
stated correctly). On the first such payment at or above the minimum top-up it, once:

1. stamps `organizations.first_paid_at` / `first_paid_via` (`WHERE first_paid_at IS NULL`,
   so a replay or a second payment changes nothing);
2. ends a running trial as `converted` (the counters restart and the account's workspace is
   queued, `trials.end_trial`), or keeps
   the data of a trial that already ended without a sale (clears its pending `erase_after`);
3. owes the account its own voice workspace (`queue_workspace_provisioning`, through the
   outbox, in this same transaction), and the owner the go-live guide (`go_live_guides`).

An operator converting the trial of an account invoiced outside the wallet
(`trial_routes.close_trial`) is the same fact by another door: `on_operator_conversion` stamps
it `operator_conversion` and owes the same guide.

**A GOODWILL GRANT IS NOT A PAYMENT.** `reason = 'grant'` and `'bonus'` rows never reach
this hook: a grant is credit we gave, not money the client paid, and counting it would let an
operator's gesture unlock KYC, numbers and live calling for an account that has paid nothing.

**A REVERSED PAYMENT IS AN OPERATOR'S DECISION** (D-859, founder decision 6): a refund or a
dispute on a paid account moves nothing back; `alert_payment_reversed` pages an operator with
the tenant and the payment's references.

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
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.tenancy.engine_workspace import (
    queue_workspace_provisioning,
    read_workspace_state,
)

log = get_logger(__name__)

#: How a payment reached the wallet: a gateway top-up, or a bank transfer an operator
#: credited. A subset of `tenancy.models.FIRST_PAID_VIA` (the backfill's `before_d697` and an
#: operator's `operator_conversion` are the rest).
PaymentVia = Literal["wallet_topup", "manual_topup"]

#: THE predicate "this account has made its first payment", on `organizations` aliased `o`.
PAID_TENANT_SQL: Final = "o.first_paid_at IS NOT NULL"

OPERATOR_CONVERSION: Final = "operator_conversion"


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


async def _claim(session: AsyncSession, *, tenant_id: UUID, via: str, at: datetime) -> bool:
    """Stamp the account paid, once. True only for the call that stamped it."""
    claimed = (
        await session.execute(
            text(
                "UPDATE organizations SET first_paid_at = :at, first_paid_via = :via, "
                "updated_at = now() WHERE id = :tid AND first_paid_at IS NULL RETURNING id"
            ),
            {"at": at, "via": via, "tid": tenant_id},
        )
    ).first()
    return claimed is not None


async def _owe_go_live_guide(session: AsyncSession, *, tenant_id: UUID, at: datetime) -> None:
    """The owner is guided through going live from now (D-859). Once per account."""
    await session.execute(
        text(
            "INSERT INTO go_live_guides (id, tenant_id, owed_at) VALUES (:id, :tid, :at) "
            "ON CONFLICT (tenant_id) DO NOTHING"
        ),
        {"id": uuid7(), "tid": tenant_id, "at": at},
    )


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
    if not await _claim(session, tenant_id=tenant_id, via=via, at=now):
        return False

    trial = await read_trial(session, tenant_id=tenant_id)
    converting = trial is not None and trial.status == TRIAL_ACTIVE
    if converting:
        # Converting queues the account's workspace and refreshes its agents itself
        # (`end_trial`).
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
    if trial is not None and trial.status != TRIAL_ACTIVE:
        # A trial that ended unpaid kept its restrictions; paying lifts them, call-backs
        # included (D-720), and its agents belong in its own workspace (D-859). An active
        # trial is converted by `end_trial` above, which owes the same.
        from apps.api.go_live.moves import refresh_agents_after_payment

        await refresh_agents_after_payment(session, tenant_id=tenant_id, reason="first_payment")
    workspace_owed = (
        (await read_workspace_state(session, tenant_id)).status == "pending"
        if converting
        else await queue_workspace_provisioning(session, tenant_id=tenant_id)
    )
    await _owe_go_live_guide(session, tenant_id=tenant_id, at=now)
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
            "trial_converted": str(converting),
            "workspace_queued": str(workspace_owed),
        },
    )
    log.info(
        "account_first_payment",
        extra={"tenant_id": str(tenant_id), "via": via, "workspace_queued": workspace_owed},
    )
    return True


async def on_operator_conversion(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> bool:
    """An operator converted this account's trial (`trial_routes.close_trial`): it is paid.

    Call it in the conversion's transaction, after `end_trial`, which has queued the workspace
    and the agents' refresh. True only when this stamped the account; an account that already
    paid by top-up keeps its own `first_paid_via`."""
    now = at or datetime.now(UTC)
    if not await _claim(session, tenant_id=tenant_id, via=OPERATOR_CONVERSION, at=now):
        return False
    await _owe_go_live_guide(session, tenant_id=tenant_id, at=now)
    await write_audit(
        session,
        action="account.first_payment",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="organizations",
        object_id=str(tenant_id),
        summary={"via": OPERATOR_CONVERSION, "trial_converted": "True"},
    )
    log.info(
        "account_first_payment", extra={"tenant_id": str(tenant_id), "via": OPERATOR_CONVERSION}
    )
    return True


ReversalKind = Literal["refund", "dispute"]


async def alert_payment_reversed(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: ReversalKind,
    payment_ref: str,
    reversal_ref: str,
) -> bool:
    """Page an operator when money is taken back from an account that has paid (D-859).

    Nothing is reversed: its agents stay in its own workspace and its trial stays converted.
    The operator decides what follows. True when the alarm was raised."""
    if not await has_paid(session, tenant_id=tenant_id):
        return False
    alert(
        "ROUTE_HANDLER",
        "paid_account_payment_reversed",
        detail=(
            f"a {kind} was recorded against a payment of an account that has paid, so its "
            "agents may already have moved into its own voice workspace. Nothing was reversed "
            "automatically; decide whether the account stays paid "
            "(runbooks/agent-workspace-move.md)."
        ),
        tenant_id=str(tenant_id),
        payment_ref=payment_ref,
        reversal_ref=reversal_ref,
    )
    return True


__all__ = [
    "OPERATOR_CONVERSION",
    "PAID_TENANT_SQL",
    "PaymentVia",
    "ReversalKind",
    "alert_payment_reversed",
    "has_paid",
    "on_operator_conversion",
    "on_payment_credited",
]
