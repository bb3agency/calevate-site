"""Keep every agent's engine webhook endpoint registered, subscribed and switched on (D-678).

ThinnestAI retries a failed delivery five times over about 8½ hours, switches an endpoint off
after five events in a row that failed every attempt, and keeps every payload for 7 days so
what failed can be re-sent (`thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/webhooks.md:110-117, :149-187`). So this sweep puts a switched-off endpoint
back, asks the vendor to re-send what failed while it was off (D-691), and alarms, because an
endpoint the vendor switched off means deliveries were being lost. It also registers an
endpoint for any agent that has none (a publish whose registration failed after the agent was
created) and brings an old endpoint's subscription up to date.

The re-send is safe to repeat: every re-sent delivery carries its original event id, which
the receiver's inbox has already settled or settles now (`apps/voice-runtime/
signed_intake.py`). Calls whose events are past the 7 days are settled from the call list by
`pipeline.reconcile_executions`.

One `ensure_agent_webhook` per active route, each in its OWN tenant session: one tenant's
failure is counted and the sweep carries on, as every fleet-wide walk here does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_webhooks import thinnest_webhooks
from apps.api.reliability.engine_webhooks import WEBHOOK_ENGINES, ensure_agent_webhook

log = get_logger(__name__)

WEBHOOK_SWEEP_MINUTES: Final = frozenset({1, 21, 41})
#: Vendor round trips per sweep, at most. Twenty minutes later the rest are reached.
WEBHOOK_SWEEP_BUDGET: Final = 200

#: How far back a re-send may reach: the vendor keeps payloads 7 days and refuses a `since`
#: outside them with a 400 (`webhooks/redeliver-webhook-events.md:89-98`), so the floor
#: stays a margin inside the window rather than on its edge.
REDELIVERY_FLOOR: Final = timedelta(days=7) - timedelta(minutes=30)
#: Before the last time the endpoint was seen healthy: an event whose attempts were still
#: being retried then may have failed its last attempt since (the schedule spans ~8½ h).
REDELIVERY_TAIL: Final = timedelta(hours=9)


def redelivery_since(last_checked: datetime | None, *, now: datetime) -> datetime:
    """The `since` a re-send asks for: back to before the endpoint was last seen healthy,
    never further than the vendor still holds."""
    floor = now - REDELIVERY_FLOOR
    if last_checked is None:
        return floor
    return max(last_checked - REDELIVERY_TAIL, floor)


async def _redeliver(
    engine: str, *, webhook_id: str, last_checked: datetime | None, tenant_id: str, ref: str
) -> bool:
    """Ask for everything that failed to be sent again. A refusal alarms and does not fail
    the sweep: the endpoint is already back on, and the call list settles the gap."""
    try:
        queued = await thinnest_webhooks().redeliver_since(
            webhook_id, redelivery_since(last_checked, now=datetime.now(UTC))
        )
    except ProblemError as exc:
        alert(
            "WORKER_DELIVERY",
            "engine_webhook_redelivery_failed",
            detail=(
                f"engine={engine}: the endpoint is back on but the voice platform did not "
                f"accept the request to re-send what failed while it was off ({exc.code}). "
                "Re-send failed deliveries from the endpoint in the vendor console; the "
                "reconciliation re-drive settles the calls from the call list meanwhile."
            ),
            tenant_id=tenant_id,
            engine_agent_ref=ref,
        )
        return False
    log.info(
        "engine_webhook_redelivery_requested",
        extra={"engine": engine, "webhook_id": webhook_id, "queued": queued},
    )
    return True


async def reconcile_engine_webhooks(ctx: dict[str, Any]) -> str:
    engine = get_settings().engine
    if engine not in WEBHOOK_ENGINES:
        return "engine_without_webhooks"
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, engine_agent_ref, webhook_checked_at "
                    "FROM engine_agent_routes WHERE engine = :engine AND active "
                    "ORDER BY webhook_checked_at ASC NULLS FIRST LIMIT :budget"
                ),
                {"engine": engine, "budget": WEBHOOK_SWEEP_BUDGET},
            )
        ).all()
    reenabled = registered = unreached = redelivered = 0
    for tenant_id, ref, last_checked in rows:
        try:
            async with tenant_session(UUID(str(tenant_id))) as session:
                registration = await ensure_agent_webhook(
                    session, engine=engine, engine_agent_ref=str(ref)
                )
        except Exception as exc:
            log.warning(
                "engine_webhook_check_failed",
                extra={"engine": engine, "tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )
            unreached += 1
            continue
        outcome = registration.outcome
        if outcome == "reenabled" and registration.webhook_id is not None:
            reenabled += 1
            alert(
                "WORKER_DELIVERY",
                "engine_webhook_reenabled",
                detail=(
                    f"engine={engine}: the vendor had switched this agent's webhook endpoint "
                    "off after repeated failed deliveries, and it is back on. What failed in "
                    "the last 7 days has been asked for again; older calls are settled by the "
                    "reconciliation re-drive from the engine's call record. Check why the "
                    "receiver was failing."
                ),
                tenant_id=str(tenant_id),
                engine_agent_ref=str(ref),
            )
            redelivered += await _redeliver(
                engine,
                webhook_id=registration.webhook_id,
                last_checked=last_checked,
                tenant_id=str(tenant_id),
                ref=str(ref),
            )
        elif outcome in ("registered", "replaced"):
            registered += 1
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "engine_webhook_sweep_incomplete",
            detail=(
                f"{unreached} of {len(rows)} agent webhook endpoint(s) could not be checked; "
                "a switched-off endpoint among them is still losing deliveries. See "
                "engine_webhook_check_failed in the worker log."
            ),
            engine=engine,
        )
    return (
        f"checked={len(rows)} reenabled={reenabled} redelivered={redelivered} "
        f"registered={registered} unreached={unreached}"
    )


__all__ = [
    "REDELIVERY_FLOOR",
    "REDELIVERY_TAIL",
    "WEBHOOK_SWEEP_BUDGET",
    "WEBHOOK_SWEEP_MINUTES",
    "reconcile_engine_webhooks",
    "redelivery_since",
]
