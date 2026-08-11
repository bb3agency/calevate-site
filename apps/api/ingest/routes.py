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
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.service import check_dispatch
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import ingest_config_session, tenant_session
from apps.api.ingest.service import (
    apply_mapping,
    ingest_lead,
    load_config,
    normalize_phone,
    verify_ingest_secret,
)
from apps.api.reliability.service import body_hash, claim_inbox_event, mark_inbox_processed

log = get_logger(__name__)

router = APIRouter(prefix="/hooks/v1", tags=["lead-ingest"])

# The client-realm half: activity + dry-run live under /v1 with the normal auth stack,
# NOT under /hooks — /hooks is the never-shed, secret-authenticated surface for
# machines, and a user-session endpoint does not belong on it.
sources_router = APIRouter(prefix="/v1/lead-sources", tags=["lead-ingest"])

SessionDep = Annotated[AsyncSession, Depends(db)]

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


class TestWebhookIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]


@sources_router.get(
    "/activity",
    openapi_extra=permission_meta("org:manage"),
    summary="Every inbound delivery: accepted / deduplicated / rejected (SURFACES §2b)",
)
async def ingest_activity(
    session: SessionDep,
    limit: int = 50,
    _: Principal = Depends(requires("org:manage")),
) -> dict[str, Any]:
    """Reads the same durable inbox the dedupe writes, so this view costs nothing new.

    `duplicate_count` is the column that answers the classic support thread: the form
    vendor retried fifteen times, we rang the customer once, and the client wants to
    know which of those two things happened.
    """
    hooks = (await session.execute(text("SELECT id, source FROM inbound_webhooks"))).all()
    sources = {f"ingest:{row[0]}": str(row[1]) for row in hooks}
    if not sources:
        return {"items": []}

    rows = (
        await session.execute(
            text(
                "SELECT provider, event_name, status, duplicate_count, last_error, created_at, "
                "updated_at FROM webhook_inbox_events WHERE provider = ANY(:providers) "
                "ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"providers": list(sources.keys()), "limit": min(limit, 200)},
        )
    ).all()
    return {
        "items": [
            {
                "source": sources.get(str(r[0]), "unknown"),
                "event": r[1],
                # The three words the SURFACES spec uses, not our internal enum.
                "outcome": (
                    "rejected"
                    if r[2] == "failed"
                    else ("accepted" if r[2] in ("processed", "enqueued") else "processing")
                ),
                "deduplicated": int(r[3] or 0),
                "error": r[4],
                "first_at": r[5],
                "last_at": r[6],
            }
            for r in rows
        ]
    }


@sources_router.post(
    "/{webhook_id}/test",
    openapi_extra=permission_meta("org:manage"),
    summary="Dry-run a sample lead end-to-end WITHOUT placing a call (SURFACES §2b)",
)
async def test_webhook(
    webhook_id: UUID,
    body: TestWebhookIn,
    session: SessionDep,
    principal: Principal = Depends(requires("org:manage")),
) -> dict[str, Any]:
    """Everything the real path would decide, nothing it would do.

    This is NOT a compliance-gate bypass (hard rule 5 forbids those): no lead row is
    written, no call is dispatched, no inbox row is claimed. The gate is CONSULTED —
    same function, same live DNC read — and its verdict is reported instead of acted
    on. The difference between this and a bypass is the direction of the arrow: a
    bypass dials without asking; this asks without dialling.
    """
    assert principal.tenant_id is not None
    config = await load_config(session, webhook_id)
    if config is None:
        raise ProblemError.not_found("Lead source")

    mapped = apply_mapping(config.mapping, body.payload) if config.mapping else dict(body.payload)
    raw_phone = str(mapped.get("phone") or mapped.get("phone_number") or "")
    phone = normalize_phone(raw_phone) if raw_phone else None

    steps: list[dict[str, Any]] = [
        {
            "step": "field_mapping",
            "ok": bool(mapped),
            "detail": f"{len(mapped)} of your configured fields matched the sample.",
            "mapped_fields": sorted(mapped.keys()),
        },
        {
            "step": "phone_number",
            "ok": phone is not None,
            "detail": (
                "Found a dialable Indian number."
                if phone
                else "No dialable phone number — the real webhook would answer 422."
            ),
        },
    ]
    if phone is None or config.agent_id is None:
        if config.agent_id is None:
            steps.append(
                {"step": "agent", "ok": False, "detail": "No agent attached to this source."}
            )
        return {"would_call": False, "steps": steps}

    consent_field = config.mapping.get("consent_field")
    if isinstance(consent_field, str) and consent_field:
        affirmed = str(body.payload.get(consent_field, "")).strip().lower() in (
            "true",
            "yes",
            "1",
            "on",
        )
        steps.append(
            {
                "step": "form_consent",
                "ok": affirmed,
                "detail": (
                    f"The '{consent_field}' field confirms permission to call."
                    if affirmed
                    else f"The '{consent_field}' field does not confirm permission — the lead "
                    "would be saved but never dialled."
                ),
            }
        )
        if not affirmed:
            return {"would_call": False, "steps": steps}

    decision = await check_dispatch(
        session, tenant_id=principal.tenant_id, agent_id=config.agent_id, phone_e164=phone
    )
    steps.append(
        {
            "step": "compliance_gate",
            "ok": decision.allowed,
            "detail": (
                "The call would be placed."
                if decision.allowed
                else decision.reason or "The gate would refuse this dial."
            ),
            "rule": decision.rule,
        }
    )
    return {"would_call": decision.allowed, "steps": steps}


__all__ = ["SECRET_HEADER", "router", "sources_router"]
