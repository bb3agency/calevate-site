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

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.engine_webhooks import WEBHOOK_ENGINES, ensure_agent_webhook

log = get_logger(__name__)

WEBHOOK_SWEEP_MINUTES: Final = frozenset({1, 21, 41})
#: Vendor round trips per sweep, at most. Twenty minutes later the rest are reached.
WEBHOOK_SWEEP_BUDGET: Final = 200


async def reconcile_engine_webhooks(ctx: dict[str, Any]) -> str:
    engine = get_settings().engine
    if engine not in WEBHOOK_ENGINES:
        return "engine_without_webhooks"
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, engine_agent_ref "
                    "FROM engine_agent_routes WHERE engine = :engine AND active "
                    "ORDER BY webhook_checked_at ASC NULLS FIRST LIMIT :budget"
                ),
                {"engine": engine, "budget": WEBHOOK_SWEEP_BUDGET},
            )
        ).all()
    reenabled = registered = unreached = redelivered = 0
    for tenant_id, ref in rows:
        try:
            async with tenant_session(UUID(str(tenant_id))) as session:
                registration = await ensure_agent_webhook(
                    session, engine=engine, engine_agent_ref=str(ref)
                )
        except Exception as exc:
            log.warning(
                "engine_webhook_check_failed",
                extra={
                    "engine": engine,
                    "tenant_id": str(tenant_id),
                    "reason": type(exc).__name__,
                    # A ProblemError's code says which refusal it was; the class name alone
                    # leaves an operator re-running the sweep by hand to find out.
                    "code": getattr(exc, "code", None),
                },
            )
            unreached += 1
            continue
        # A switched-off endpoint is re-enabled, alarmed and re-sent inside
        # `ensure_agent_webhook`, the same as when a publish finds it so.
        outcome = registration.outcome
        redelivered += registration.redelivered
        if outcome == "reenabled":
            reenabled += 1
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
    "WEBHOOK_SWEEP_BUDGET",
    "WEBHOOK_SWEEP_MINUTES",
    "reconcile_engine_webhooks",
]
