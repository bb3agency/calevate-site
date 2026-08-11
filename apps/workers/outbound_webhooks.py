"""Outbound webhook delivery worker (D-23, SEC-COMP §5).

The outbox has already guaranteed the event is real and committed. This job's only
question is whether the client's endpoint accepted it, and its only outputs are a
delivery row and — on failure — an exception that ARQ's retry ladder walks.

Retry policy is ARQ's, not a loop here: raising is how a job says "try again later",
and swallowing the failure to write a nicer log line is how deliveries get silently
lost. After `MAX_ATTEMPTS` the job stops and the delivery row shows `failed`, which is
what the webhook-activity screen reads and what support answers "did it reach my CRM?"
with.

A tenant that has deleted or deactivated its endpoint between enqueue and delivery is
NOT a failure — the client changed their mind, and retrying against a config row that
no longer exists would be noise forever.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service

log = get_logger(__name__)


async def deliver_outbound_webhook(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    endpoint_id = UUID(str(payload["endpoint_id"]))
    event = str(payload["event"])
    data: dict[str, Any] = payload.get("data") or {}
    # Retries reuse the delivery id so the forensic row is one row per delivery, not
    # one per attempt — and so a receiver deduplicating on it sees a retry as a retry.
    delivery_id = UUID(str(payload["delivery_id"])) if payload.get("delivery_id") else uuid7()
    attempt = int(ctx.get("job_try", 1))

    async with tenant_session(tenant_id) as session:
        endpoint = await service.load_endpoint(session, endpoint_id)
        if endpoint is None:
            log.info("outbound_endpoint_gone", extra={"tenant_id": str(tenant_id)})
            await service.record_delivery(
                session,
                delivery_id=delivery_id,
                endpoint_id=endpoint_id,
                event=event,
                status="skipped",
                attempts=attempt,
                status_code=None,
            )
            return "endpoint_inactive"

        mapping = endpoint["mapping"] or {}
        body = service.apply_mapping(data, mapping.get("fields") or {})
        envelope = service.build_envelope(
            event=event, tenant_id=tenant_id, delivery_id=delivery_id, data=body
        )
        result = await service.deliver(
            url=str(endpoint["url"]),
            secret=str(endpoint["secret"] or ""),
            event=event,
            envelope=envelope,
        )
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event=event,
            status="delivered" if result.delivered else "failed",
            attempts=attempt,
            status_code=result.status_code,
        )

    if result.delivered:
        return f"delivered {result.status_code}"

    log.warning(
        "outbound_delivery_failed",
        extra={"tenant_id": str(tenant_id), "event": event, "reason": result.error},
    )
    if attempt >= service.MAX_ATTEMPTS:
        # Give up loudly. The client's integration is broken and someone has to know;
        # a silent stop is indistinguishable from "no events happened".
        alert(
            "WORKER_DELIVERY",
            "outbound_webhook_exhausted",
            detail=result.error or "unknown",
            tenant_id=str(tenant_id),
        )
        return f"exhausted after {attempt}"
    raise RuntimeError(f"outbound delivery failed: {result.error}")


__all__ = ["deliver_outbound_webhook"]
