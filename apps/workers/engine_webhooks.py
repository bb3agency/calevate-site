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

A ROUTE WHOSE VENDOR AGENT IS GONE. A 404 about a missing endpoint is repaired inside
`ensure_agent_webhook`; a 404 that escapes it is about the AGENT ("The agent is not in this
workspace", `snapshots/2026-10-15/pages/api-reference/webhooks/create-webhook.md:510-517`).
The route is switched off only when nothing of ours still names that vendor agent — no
agent row that is not archived, no experiment arm — because then no call can ever report
through it and re-asking every twenty minutes only buries the alarm. A route an agent still
publishes under is never switched off here: a 404 there means the agent we sell is missing
at the vendor (or was asked for in the wrong workspace), and that needs a person and a
republish, so it is named in the alarm instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.plans import IST
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.reliability.engine_webhooks import WEBHOOK_ENGINES, ensure_agent_webhook

log = get_logger(__name__)

WEBHOOK_SWEEP_MINUTES: Final = frozenset({1, 21, 41})
#: Vendor round trips per sweep, at most. Twenty minutes later the rest are reached.
WEBHOOK_SWEEP_BUDGET: Final = 200

#: Switches a route off when its vendor agent is gone AND nothing of ours names it any more.
#: Archived agents count as not naming it: their vendor agent is left standing on purpose
#: (`agents/lifecycle.py`), so if the vendor no longer has it there is nothing to report.
_RETIRE_ORPHANED_ROUTE_SQL = """
UPDATE engine_agent_routes r SET active = false, updated_at = now()
WHERE r.engine = :engine AND r.engine_agent_ref = :ref AND r.active
  AND NOT EXISTS (
    SELECT 1 FROM agents a
    WHERE a.engine_agent_ref = r.engine_agent_ref
      AND a.status <> 'archived' AND a.deleted_at IS NULL
  )
  AND NOT EXISTS (
    SELECT 1 FROM prompt_experiment_variants v WHERE v.engine_agent_ref = r.engine_agent_ref
  )
"""


#: One `engine_webhook_events_pending` per IST day: the endpoint still delivers what it holds,
#: and the fix is the vendor's, so a reminder a day is enough and one per sweep is noise.
_EVENTS_PENDING_KEY: Final = "alert:engine_webhook_events_pending:{engine}:{day}"
_EVENTS_PENDING_TTL_S: Final = 2 * 86_400


async def _alarm_events_pending(engine: str, count: int) -> None:
    """Fails towards alerting: when Redis cannot answer, the alarm is raised."""
    day = datetime.now(UTC).astimezone(IST).date().isoformat()
    try:
        first = bool(
            await get_redis().set(
                _EVENTS_PENDING_KEY.format(engine=engine, day=day),
                "1",
                nx=True,
                ex=_EVENTS_PENDING_TTL_S,
            )
        )
    except Exception:
        first = True
    if not first:
        return
    alert(
        "WORKER_DELIVERY",
        "engine_webhook_events_pending",
        detail=(
            f"{count} agent webhook endpoint(s) are on and delivering the events they hold, "
            "but the voice platform fails (HTTP 5xx) to add the newer ones (contact.erased, "
            "byok.changed), both in place and on a new endpoint. Call results are not "
            "affected. Raise it with ThinnestAI quoting engine_webhook_patch_failed; the "
            "sweep keeps trying every 20 minutes and this is repeated once a day."
        ),
        engine=engine,
    )


def _vendor_detail(exc: Exception) -> dict[str, Any]:
    """The vendor's own refusal facts, ids and codes only (hard rule 6): the status, the
    vendor's error code and reason word, the field it named, and whether the adapter judged
    it our set-up. The vendor's sentence is on the `engine_error` line logged at the raise."""
    if not isinstance(exc, EngineRejectedError):
        return {}
    return {
        "vendor_status": exc.vendor_status,
        "vendor_code": exc.vendor_code,
        "vendor_error": exc.vendor_error,
        "vendor_reason": exc.vendor_reason,
        "vendor_field": exc.vendor_field,
        "setup_refused": exc.setup_refused,
    }


async def _retire_if_orphaned(tenant_id: UUID, engine: str, ref: str) -> bool:
    """Switch the route off when no agent or arm of ours still names it. True if it was."""
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text(_RETIRE_ORPHANED_ROUTE_SQL), {"engine": engine, "ref": ref}
        )
    return rowcount_of(result) > 0


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
    reenabled = registered = unreached = redelivered = retired = 0
    agent_absent = vendor_failed = events_pending = 0
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
                    **_vendor_detail(exc),
                },
            )
            if isinstance(exc, EngineRejectedError) and exc.object_absent:
                if await _retire_if_orphaned(UUID(str(tenant_id)), engine, str(ref)):
                    log.warning(
                        "engine_webhook_route_retired",
                        extra={"engine": engine, "tenant_id": str(tenant_id)},
                    )
                    retired += 1
                    continue
                agent_absent += 1
            elif isinstance(exc, EngineRejectedError) and (exc.vendor_status or 0) >= 500:
                vendor_failed += 1
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
        elif outcome == "events_pending":
            events_pending += 1
    if events_pending:
        await _alarm_events_pending(engine, events_pending)
    if unreached:
        absent_note = (
            f" {agent_absent} of them belong to an agent the voice platform says it does not "
            "have in that workspace while one of our agents still publishes under it: "
            "republish that agent."
            if agent_absent
            else ""
        )
        vendor_note = (
            f" {vendor_failed} failed on the voice platform's side (HTTP 5xx, it could not "
            "save or read the endpoint) and is retried next sweep; if it repeats, raise it "
            "with ThinnestAI quoting the engine_error line."
            if vendor_failed
            else ""
        )
        alert(
            "WORKER_DELIVERY",
            "engine_webhook_sweep_incomplete",
            detail=(
                f"{unreached} of {len(rows)} agent webhook endpoint(s) could not be checked; "
                "any switched-off endpoint among them is still losing deliveries."
                f"{absent_note}{vendor_note} See engine_webhook_check_failed (vendor_status, "
                "vendor_code) "
                "and the engine_error line before it in the worker log."
            ),
            engine=engine,
        )
    return (
        f"checked={len(rows)} reenabled={reenabled} redelivered={redelivered} "
        f"registered={registered} unreached={unreached} retired={retired} "
        f"events_pending={events_pending}"
    )


__all__ = [
    "WEBHOOK_SWEEP_BUDGET",
    "WEBHOOK_SWEEP_MINUTES",
    "reconcile_engine_webhooks",
]
