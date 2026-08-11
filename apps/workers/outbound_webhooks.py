"""Outbound webhook delivery worker (D-23, SEC-COMP §5).

The outbox has already guaranteed the event is real and committed. This job's only
question is whether the client's endpoint accepted it, and its only outputs are a
delivery row and — on a retryable failure — an `arq.Retry` that the retry ladder walks.

**`arq.Retry`, not a bare `raise`.** This is not a style choice. arq 0.28 retries a job
only for `Retry`, `RetryJob` or `CancelledError`; every other exception sets
`finish=True` and the job leaves the queue after ONE attempt (`arq/worker.py`, the
`else` branch in `run_job`'s handler). This module used to signal "try again later" by
raising `RuntimeError`, so `max_tries = 3` was decorative, the `attempt >= MAX_ATTEMPTS`
branch below was unreachable, and `outbound_webhook_exhausted` — the alert whose entire
job is to notice that a client's integration has gone stale — could never fire in
production. Anything raised from here that is NOT a `Retry` is a permanent stop.

**Not every failure deserves a retry.** A 5xx, a timeout or a refused connection is a
blip and gets the ladder. A 4xx (bar 408/425/429) or a redirect is the client's endpoint
telling us the request itself is wrong: the same signed body will be rejected identically
in two minutes, so retrying only delays the verdict on the delivery row and triples the
load on a host that is already unhappy. We stop, record `failed`, and alert — the client
needs to hear about it either way, and the two cases are told apart by the alert detail.

A tenant that has deleted or deactivated its endpoint between enqueue and delivery is
NOT a failure — the client changed their mind, and retrying against a config row that
no longer exists would be noise forever.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service

log = get_logger(__name__)

# Seconds to wait before each retry, indexed by the attempt that just failed. One entry
# shorter than the budget, because the last attempt has nothing after it. Real backoff
# (not a flat re-poll): a receiver that is restarting wants half a minute, and a
# receiver that is genuinely down should not be re-hit every few seconds for the sake
# of a curve that looks busy.
RETRY_BACKOFF_S: tuple[float, ...] = (30.0, 120.0)

# 4xx that ARE worth another go: the request is fine, the receiver is not ready for it.
TRANSIENT_CLIENT_STATUS = frozenset({408, 425, 429})


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _is_transient(result: service.DeliveryResult) -> bool:
    """Transport failures (no status at all — DNS, refused, timeout, TLS) and 5xx are
    blips. Everything else the receiver actually answered with is a verdict on the
    request, and repeating the request cannot change it."""
    if result.status_code is None:
        return True
    return result.status_code >= 500 or result.status_code in TRANSIENT_CLIENT_STATUS


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
    transient = _is_transient(result)
    if transient and attempt < service.MAX_ATTEMPTS:
        # The one exception type arq treats as "not finished". The delivery row is
        # already committed — the session closed above — so the retry starts from a
        # recorded attempt, not from nothing.
        raise Retry(defer=_retry_after(attempt))

    # Give up loudly, whether the budget ran out or the endpoint rejected the request
    # outright. The client's integration is broken and someone has to know; a silent
    # stop is indistinguishable from "no events happened".
    alert(
        "WORKER_DELIVERY",
        "outbound_webhook_exhausted",
        detail=(
            f"{result.error or 'unknown'} after {attempt} attempt(s)"
            if transient
            else f"{result.error or 'unknown'} is permanent, not retried"
        ),
        tenant_id=str(tenant_id),
    )
    return f"exhausted after {attempt}" if transient else f"rejected {result.status_code}"


__all__ = ["deliver_outbound_webhook"]
