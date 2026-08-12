"""Outbound delivery worker (D-23, SEC-COMP §5).

The outbox has already guaranteed the event is real and committed. This job's only
question is whether the client's endpoint accepted it, and its only outputs are a
delivery row and — on a retryable failure — an `arq.Retry` that the retry ladder walks.

**Both D-23 endpoint kinds land here.** A signed POST (`kind='webhook'`) and a Google
Sheets append (`kind='google_sheets'`) differ only in the transport at the end: the
delivery id, the forensic row, the dedupe and the ladder below are shared. That is
deliberate — a second worker would mean a second definition of "we delivered a lead",
two delivery logs to reconcile when a client asks why a row is missing, and two ladders
to keep in step with `WORKER_MAX_TRIES`. The sheets transport and its row mapping live
in `apps/workers/sheets_sync.py`; everything about DELIVERY lives here.

The job keeps its name (`deliver_outbound_webhook`) because that name is arq's
registration key and the string every queued outbox row already carries; renaming it
would DLQ every message in flight for a wording improvement.

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
from apps.workers import sheets_sync

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
    request, and repeating the request cannot change it.

    A transport with no status codes states the answer itself (`transient`), because
    "no status" means something entirely different for a signed POST — where it is a
    network failure — than for an append refused for want of a service account.
    """
    if result.transient is not None:
        return result.transient
    if result.status_code is None:
        return True
    return result.status_code >= 500 or result.status_code in TRANSIENT_CLIENT_STATUS


def _kind_of(endpoint: dict[str, Any]) -> str:
    """Which D-23 kind this endpoint is. ONE resolution, used by every branch below —
    two readings of the same field would eventually disagree, and the disagreement
    would be "the dedupe thought it was a webhook and the delivery appended a row".

    `outbound_webhooks.kind` is NOT NULL, so a row always has one; an ABSENT key means a
    caller built this dict before the second kind existed, and the webhook is what it
    meant. An explicitly UNKNOWN kind is a different thing and still refuses — the
    fallback is for the missing key, never for a value we do not recognise.
    """
    return str(endpoint.get("kind") or service.WEBHOOK_KIND)


async def _deliver_to_endpoint(
    *,
    endpoint: dict[str, Any],
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
    delivery_id: UUID,
    attempt: int,
) -> service.DeliveryResult:
    """One attempt at one endpoint, whatever kind it is.

    The ONLY place the two D-23 kinds diverge. Everything the caller does with the
    result — the forensic row, the ladder, the alert — is common by construction.
    """
    kind = _kind_of(endpoint)
    mapping = endpoint["mapping"] or {}

    if kind == service.SHEET_KIND:
        # The attempt number is part of the sheets CONTRACT, not telemetry: a sheet
        # cannot deduplicate for us, so the adapter reads the document's delivery-id
        # column before writing on a retry. A webhook needs none of this — its receiver
        # dedupes on the envelope id (WEBHOOKS §1.5) — which is why the number is passed
        # here and not into `service.deliver`.
        return await sheets_sync.append_event(
            endpoint=endpoint,
            event=event,
            data=data,
            delivery_id=delivery_id,
            attempt=attempt,
        )

    if kind == service.WEBHOOK_KIND:
        body = service.apply_mapping(data, mapping.get("fields") or {})
        envelope = service.build_envelope(
            event=event, tenant_id=tenant_id, delivery_id=delivery_id, data=body
        )
        return await service.deliver(
            url=str(endpoint["url"]),
            secret=str(endpoint["secret"] or ""),
            event=event,
            envelope=envelope,
        )

    # A kind the CHECK constraint allows and this worker cannot deliver. Permanent by
    # nature, and recorded rather than swallowed: an endpoint nobody delivers is the
    # exact defect `DELIVERABLE_KINDS` exists to keep out of the queue.
    return service.DeliveryResult(
        delivered=False,
        status_code=None,
        error=f"unsupported_endpoint_kind:{kind}",
        channel="unknown",
        transient=False,
    )


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

        if _kind_of(endpoint) == service.SHEET_KIND and (
            await service.delivery_status(session, delivery_id) == "delivered"
        ):
            # A sheet cannot deduplicate for us and a duplicate row in a document a
            # human is reading cannot be un-seen, so the delivery log — the same row the
            # forensic screen shows, not a second bespoke mechanism — is the guard. Only
            # `delivered` blocks: a recorded ATTEMPT must not, or the ladder below would
            # be decorative. Not applied to the webhook path, which is documented
            # at-least-once and whose receivers dedupe on the envelope id
            # (WEBHOOKS §1.5).
            log.info("outbound_delivery_duplicate", extra={"delivery_id": str(delivery_id)})
            return "duplicate"

        result = await _deliver_to_endpoint(
            endpoint=endpoint,
            tenant_id=tenant_id,
            event=event,
            data=data,
            delivery_id=delivery_id,
            attempt=attempt,
        )
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event=event,
            status="delivered" if result.delivered else "failed",
            attempts=attempt,
            status_code=result.status_code,
            channel=result.channel,
            # WHY it failed, recorded rather than only logged. Until this was stored the
            # client's own screen could say no more than "sheets" — the transport's name
            # — for a delivery that failed because they had not shared the document with
            # us, which is a thing only they can fix and which no support ticket should
            # be needed to discover. Always one of OUR authored codes, never vendor
            # prose and never a payload (hard rule 6).
            reason=None if result.delivered else result.error,
        )

    if result.delivered:
        # An HTTP receiver's status code is the useful detail; an append has none, so it
        # names the channel instead of printing "delivered None".
        return (
            f"delivered {result.status_code}"
            if result.status_code is not None
            else f"delivered via {result.channel}"
        )

    log.warning(
        "outbound_delivery_failed",
        # `reason` is either an HTTP status, an exception TYPE or one of our own
        # authored refusal codes — never vendor prose and never a payload (hard rule 6).
        extra={
            "tenant_id": str(tenant_id),
            "event": event,
            "channel": result.channel,
            "reason": result.error,
        },
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
        # One alert code for both kinds, because it is one runbook
        # (runbooks/webhook-delivery-failures.md) and one broken integration from the
        # client's point of view. The channel is in the detail so the responder knows
        # whether to look at an endpoint or a spreadsheet.
        "outbound_webhook_exhausted",
        detail=(
            f"{result.channel}: {result.error or 'unknown'} after {attempt} attempt(s)"
            if transient
            else f"{result.channel}: {result.error or 'unknown'} is permanent, not retried"
        ),
        tenant_id=str(tenant_id),
    )
    if transient:
        return f"exhausted after {attempt}"
    return f"rejected {result.status_code if result.status_code is not None else result.error}"


__all__ = ["deliver_outbound_webhook"]
