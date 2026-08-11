"""The per-client ingest endpoint (FLOWS §4).

`POST /hooks/v1/ingest/{webhook_id}` — under `/hooks` because it shares the webhook
doctrine: never load-shed (a lead arriving during degraded mode is still a lead),
inbox-deduped, and authenticated by something the SENDER holds rather than by a user
session. The `{webhook_id}` is a UUID, so the URL itself is already unguessable; the
secret is what makes it revocable.

Speed-to-lead starts the moment the request arrives, which is why `received_at` is
stamped here and threaded through rather than measured inside the service.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import ingest_config_session, tenant_session
from apps.api.ingest.service import ingest_lead, load_config, verify_ingest_secret
from apps.api.reliability.service import body_hash, claim_inbox_event, mark_inbox_processed

log = get_logger(__name__)

router = APIRouter(prefix="/hooks/v1", tags=["lead-ingest"])

SECRET_HEADER = "X-Ingest-Secret"


@router.post(
    "/ingest/{webhook_id}",
    status_code=202,
    summary="Per-client lead intake → compliance-gated instant callback (FLOWS §4)",
)
async def ingest(webhook_id: UUID, request: Request) -> dict[str, Any]:
    received_at = time.time()

    # Config lookup happens before any tenant is known — the webhook id IS the
    # routing key, same shape as engine_agent_routes (see ingest_config_session).
    async with ingest_config_session(webhook_id) as session:
        config = await load_config(session, webhook_id)
    if config is None:
        # 404, not 401: an inactive or unknown endpoint should be indistinguishable
        # from a nonexistent one to a probing sender.
        raise ProblemError.not_found("Lead source")

    if not verify_ingest_secret(config, request.headers.get(SECRET_HEADER)):
        log.warning("ingest_bad_secret", extra={"webhook_id": str(webhook_id)})
        raise ProblemError.unauthorized("This lead source rejected the credentials.")

    try:
        payload = await request.json()
    except Exception as exc:
        raise ProblemError(
            kind="validation",
            code="ingest_not_json",
            title="Payload is not JSON",
            detail="This endpoint accepts JSON bodies only.",
        ) from exc
    if not isinstance(payload, dict):
        payload = {"value": payload}

    # Form vendors and Zapier RETRY on timeouts, and a retried form submission must
    # not ring the customer twice. Same durable dedupe as every other webhook.
    digest = body_hash(payload)
    async with tenant_session(config.tenant_id) as session:
        claim = await claim_inbox_event(
            session,
            provider=f"ingest:{webhook_id}",
            event_key=digest,
            payload_hash=digest,
            event_name=config.source,
        )
        if claim.state == "duplicate":
            return {"status": "duplicate"}

        result = await ingest_lead(session, config=config, payload=payload, received_at=received_at)
        await mark_inbox_processed(session, row_id=claim.row_id)

    return {
        "status": "accepted",
        "lead_id": str(result["lead_id"]),
        "dispatched": result["dispatched"],
        **({"blocked": result["blocked"]} if result.get("blocked") else {}),
    }


__all__ = ["SECRET_HEADER", "router"]
