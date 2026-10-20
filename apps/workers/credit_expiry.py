"""The daily job that lapses pack credit past its expiry (D-840, `billing/credit_expiry.py`).

    expire_credit_lots   daily, IST — one tenant_session per organization, then one
                          transaction per due lot

Nothing is due until `Settings.credit_pack_expiry_months` is set and a purchase stamps a lot
with `expires_at`, so the job finds nothing until then. Each lot is expired in its own
transaction under the tenant's credit lock, and the ledger row is keyed per lot, so a retried
or doubled tick expires nothing twice. The admin role reads the directory only (hard rule 1),
as `workers/number_rental.py` does.

Hard rule 6: ids and counts in every log line and alarm.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.credit_expiry import due_lots, expire_lot
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

_ALL_TENANTS = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"


async def expire_credit_lots(ctx: dict[str, Any]) -> str:
    """Lapse every due lot's remaining credit, tenant by tenant. One failure is counted and
    alarmed, never allowed to stop the rest."""
    now = datetime.now(UTC)
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_ALL_TENANTS))).scalars()]
    expired = failed = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            due = await due_lots(scoped, now=now)
        for lot_id in due:
            try:
                async with tenant_session(tenant_id) as scoped:
                    done = await expire_lot(scoped, tenant_id=tenant_id, lot_id=lot_id, now=now)
                expired += 1 if done is not None else 0
            except Exception as exc:
                failed += 1
                log.error(
                    "credit_lot_expiry_failed",
                    extra={"lot_id": str(lot_id), "error": exc.__class__.__name__},
                )
    if failed:
        alert(
            "WORKER_TERMINAL",
            "credit_expiry_incomplete",
            detail=(
                f"{failed} credit lot(s) past their expiry could not be expired; their "
                "credit is still spendable. The next daily run tries them again."
            ),
        )
    summary = {"expired": expired, "failed": failed}
    log.info("credit_lots_expired", extra=summary)
    return str(summary)


__all__ = ["expire_credit_lots"]
