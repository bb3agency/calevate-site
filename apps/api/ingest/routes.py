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

import json
import time
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import alert
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import ingest_config_session, tenant_session
from apps.api.ingest import meta
from apps.api.ingest.service import (
    IngestConfig,
    apply_mapping,
    ingest_lead,
    load_config,
    normalize_phone,
    verify_ingest_secret,
)
from apps.api.reliability.service import (
    body_hash,
    claim_inbox_event,
    mark_inbox_failed,
    mark_inbox_processed,
)

log = get_logger(__name__)

router = APIRouter(prefix="/hooks/v1", tags=["lead-ingest"])

# The client-realm half: activity + dry-run live under /v1 with the normal auth stack,
# NOT under /hooks — /hooks is the never-shed, secret-authenticated surface for
# machines, and a user-session endpoint does not belong on it.
sources_router = APIRouter(prefix="/v1/lead-sources", tags=["lead-ingest"])

SessionDep = Annotated[AsyncSession, Depends(db)]

SECRET_HEADER = "X-Ingest-Secret"

# The one `inbound_webhooks.source` that has a Meta endpoint. Spelled here rather than
# imported from `integrations.models.INBOUND_SOURCES` because this is not "one of the
# valid sources" — it is THE source this receiver is written for.
META_SOURCE = "meta_lead_ads"


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


async def _meta_config(webhook_id: UUID) -> IngestConfig:
    """The lead source behind a Meta callback URL, or a 404.

    Same pre-tenant read as the shared-secret path: one row, addressed by a UUID we
    minted (`ingest_config_session`). The source check is part of the 404 on purpose —
    an app secret and a shared ingest secret are different credentials, and a
    `website_form` source has no Meta endpoint to speak of. Indistinguishable from an
    unknown id, so a prober learns nothing either way.
    """
    async with ingest_config_session(webhook_id) as session:
        config = await load_config(session, webhook_id)
    if config is None or config.source != META_SOURCE:
        raise ProblemError.not_found("Lead source")
    return config


@router.get(
    "/ingest/meta/{webhook_id}",
    response_class=PlainTextResponse,
    summary="Meta's webhook subscription handshake — echoes hub.challenge (SURFACES §2b)",
)
async def meta_verify(
    webhook_id: UUID,
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    """Meta GETs this when someone subscribes the callback URL, and will not accept the
    subscription unless the challenge comes back verbatim as plain text with 200.

    The failure answer is 403, which is what Meta's own guidance asks for and also the
    correct shape here: the caller authenticated nothing, they presented a token that
    does not match. Nothing is written on either path — a handshake is not a delivery.
    """
    config = await _meta_config(webhook_id)
    expected = meta.verify_token_for(webhook_id=webhook_id, app_secret=config.secret_ref)
    if not meta.handshake_matches(mode=hub_mode, token=hub_verify_token, expected=expected):
        log.warning("meta_handshake_rejected", extra={"webhook_id": str(webhook_id)})
        raise ProblemError.forbidden("This subscription request was not recognised.")
    if not hub_challenge or len(hub_challenge) > meta.MAX_CHALLENGE_LEN:
        raise ProblemError(
            kind="validation",
            code="meta_challenge_missing",
            title="No challenge to echo",
            detail="A subscription handshake must carry a hub.challenge.",
        )
    # `text/plain` explicitly: the challenge is a string chosen by the caller, and the
    # one thing that must never happen to attacker-chosen bytes we echo is a browser
    # deciding for itself that they are HTML.
    return PlainTextResponse(hub_challenge, media_type="text/plain; charset=utf-8")


@router.post(
    "/ingest/meta/{webhook_id}",
    summary="Meta Lead Ads leadgen notifications, X-Hub-Signature-256 verified (SURFACES §2b)",
)
async def meta_leadgen(webhook_id: UUID, request: Request) -> dict[str, int]:
    """One verified delivery → n leads, deduped per `leadgen_id`.

    Order is the security argument, and it is the same one `billing/payments.py` and
    the voice-runtime receiver make:

    1. bound the body BEFORE reading it — we cannot check a signature without the
       bytes, so an unauthenticated caller decides how much we allocate unless a cap
       decides first;
    2. verify the signature over those RAW bytes, before any parse;
    3. only then parse, normalize, and do work.

    The answer is always 200 once the signature holds, including for the deliveries we
    refuse. Meta retries a non-2xx with backoff for hours and eventually unsubscribes
    the Page — and our refusal is permanent (no retriever), so retrying could only
    delay the verdict and end with the client's integration switched off. The refusal
    is recorded instead, against the `leadgen_id`, where the client can see it.
    """
    received_at = time.time()
    config = await _meta_config(webhook_id)

    raw = await meta.read_bounded_body(request)
    if raw is None:
        raise ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Payload too large",
            detail="The notification body exceeds the accepted size.",
            status=413,
        )
    if not meta.verify_signature(
        app_secret=config.secret_ref, body=raw, header=request.headers.get(meta.SIGNATURE_HEADER)
    ):
        # An alert, not just a log: a signed endpoint receiving unsigned or wrongly
        # signed traffic is either a rotated app secret (the client's integration is
        # down right now) or somebody trying it on. Both are worth a page.
        alert("ROUTE_HANDLER", "meta_signature_rejected", webhook_id=str(webhook_id))
        raise ProblemError.unauthorized("This notification was not signed by Meta.")

    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        # `json.loads` raises RecursionError — not ValueError — on a deeply nested
        # document, and this caller has already proved they hold the app secret, so
        # this is a shape we did not expect rather than an attack. Still not a 500.
        raise ProblemError(
            kind="validation",
            code="meta_not_json",
            title="Payload is not JSON",
            detail="This endpoint accepts JSON notifications only.",
        ) from exc

    notifications = meta.extract_lead_notifications(payload)
    counts = {"received": len(notifications), "accepted": 0, "duplicate": 0, "refused": 0}
    for notification in notifications:
        outcome = await _absorb_leadgen(
            webhook_id=webhook_id,
            config=config,
            notification=notification,
            received_at=received_at,
        )
        counts[outcome] += 1
    log.info("meta_leadgen_received", extra={"webhook_id": str(webhook_id), **counts})
    return counts


async def _absorb_leadgen(
    *,
    webhook_id: UUID,
    config: IngestConfig,
    notification: meta.LeadNotification,
    received_at: float,
) -> Literal["accepted", "duplicate", "refused"]:
    """One lead, one transaction — the unit of work Meta actually delivers.

    One transaction PER NOTIFICATION rather than per delivery: Meta batches, and one
    lead whose number will not normalize must not roll back the two beside it that were
    fine. The inbox claim is what makes that safe to retry — the siblings that already
    committed are absorbed as duplicates on the next attempt.

    Three transactions, in this order, and each boundary is load-bearing:

    1. **claim**, committed alone, so a failure of the work below leaves a row we can
       mark rather than nothing at all. A crash in between leaves `processing`, which
       `claim_inbox_event` re-claims by CAS once `CLAIM_LEASE` lapses — and Meta is
       still retrying for hours by then.
    2. **the Graph read**, outside any transaction. A vendor round trip inside an open
       Postgres transaction holds a pooled connection for the length of somebody
       else's network.
    3. **the lead**, closing the claim in the SAME transaction that writes it — the
       ordering defect `tests/ingest_ordering_test.py` exists to prevent, which is
       recording a claim as done before the work under it is durable.
    """
    provider = meta.inbox_provider(webhook_id)
    async with tenant_session(config.tenant_id) as session:
        claim = await claim_inbox_event(
            session,
            provider=provider,
            event_key=notification.leadgen_id,
            # Hashed from OUR normalized shape, not the vendor dict: Meta renders ids
            # as numbers and a retry that quoted one as a string would otherwise look
            # like a doctored replay and raise `webhook_payload_mismatch` at a genuine
            # sender.
            payload_hash=body_hash(notification.provenance()),
            event_name=meta.LEADGEN_FIELD,
        )
        if claim.state == "duplicate":
            return "duplicate"

    retriever = meta.get_lead_retriever()
    if retriever is None:
        # THE HONEST HOLE (meta.py's docstring). We hold the notification and not the
        # answers, so there is no lead to write — and writing one out of metadata we
        # cannot read would be inventing it. Recorded as failed with OUR reason code,
        # which the activity view renders as `rejected`, and re-claimable by CAS the
        # day a retriever exists.
        return await _record_refusal(
            config,
            claim.row_id,
            webhook_id=webhook_id,
            reason=meta.lead_retrieval_capability().reason or "",
        )

    answers = meta.flatten_field_data(await retriever.fetch_field_data(notification.leadgen_id))
    if not answers:
        return await _record_refusal(
            config, claim.row_id, webhook_id=webhook_id, reason=meta.NO_ANSWERS_REASON
        )

    try:
        async with tenant_session(config.tenant_id) as session:
            await ingest_lead(
                session,
                config=config,
                payload=answers,
                received_at=received_at,
                # Hard rule 5: tapping a lead ad handed a number to META. It is not
                # permission for a voice agent to ring it, and this path never records
                # it as though it were — no consent question on the form means the lead
                # lands and the dial does not.
                require_form_consent=True,
                provenance={config.source: notification.provenance()},
            )
            await mark_inbox_processed(session, row_id=claim.row_id)
    except ProblemError as exc:
        # An unusable lead (no dialable number, no agent attached, agent unpublished) is
        # a VERDICT, not a transient. Meta would retry a 5xx for ~36 hours and then
        # unsubscribe the Page, so the refusal is recorded and acked instead — the code
        # that names the fix lands in the activity view where the client can read it.
        return await _record_refusal(config, claim.row_id, webhook_id=webhook_id, reason=exc.code)
    return "accepted"


async def _record_refusal(
    config: IngestConfig, row_id: UUID, *, webhook_id: UUID, reason: str
) -> Literal["refused"]:
    """Mark the claim failed and say so once, in one place.

    The reason is an AUTHORED code every time — never vendor prose and never an
    exception's message, because this string is rendered to the client and an
    exception's message is where internals leak.

    The `leadgen_id` is deliberately NOT on this line. A 15-digit Meta object id is
    phone-shaped, and `core.logging`'s redactor cannot tell one from a number it is
    required to mask — it masks it, correctly, and a field that always reads `[phone]`
    is worse than no field. The id is durable where it belongs: `webhook_inbox_events`
    `.event_key`, which is also the row this function just marked.
    """
    async with tenant_session(config.tenant_id) as session:
        await mark_inbox_failed(session, row_id=row_id, error=reason)
    log.warning("meta_lead_refused", extra={"webhook_id": str(webhook_id), "reason": reason})
    return "refused"


class TestWebhookIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]


class IngestActivityItemOut(BaseModel):
    """One inbound source's rolled-up delivery record from the durable inbox.

    Declared rather than left as an untyped dict: an undeclared response is invisible
    to `scripts/check_redaction_exposure.py`, which inspects response MODELS — and a
    delivery record sits one careless `SELECT *` away from the sender's payload.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    # `webhook_inbox_events.event_name` is a nullable column: a row written by a
    # provider that sends no event name has none, and inventing "" would be a lie.
    event: str | None
    # The three words the SURFACES spec uses, not our internal inbox enum.
    outcome: Literal["accepted", "rejected", "processing"]
    # Vendor retries we absorbed without ringing the customer twice.
    deduplicated: int
    error: str | None
    first_at: datetime
    last_at: datetime


class IngestActivityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IngestActivityItemOut]


@sources_router.get(
    "/activity",
    response_model=IngestActivityOut,
    openapi_extra=permission_meta("org:read"),
    summary="Every inbound delivery: accepted / deduplicated / rejected (SURFACES §2b)",
)
async def ingest_activity(
    session: SessionDep,
    # Range-checked at the boundary rather than clamped below: `min(limit, 200)` let a
    # negative value reach the SQL LIMIT, which Postgres rejects with a 500.
    limit: int = Query(50, ge=1, le=200),
    # A read gated on a READ permission. `org:manage` is mutating, so D-22 hid this
    # from read-only impersonation — support could not see whether a client's form
    # was reaching us at all. The dry-run POST below stays on `org:manage`: it is an
    # action taken on the client's behalf, not a view of their data.
    _: Principal = Depends(requires("org:read")),
) -> IngestActivityOut:
    """Reads the same durable inbox the dedupe writes, so this view costs nothing new.

    `duplicate_count` is the column that answers the classic support thread: the form
    vendor retried fifteen times, we rang the customer once, and the client wants to
    know which of those two things happened.
    """
    hooks = (await session.execute(text("SELECT id, source FROM inbound_webhooks"))).all()
    # BOTH inbox keyspaces for each source. A Meta endpoint's deliveries live under
    # `meta:{id}` (they dedupe on a different unit of work), and leaving them out is
    # how a refusal we recorded on purpose becomes a delivery the client never sees.
    sources = {f"{prefix}{row[0]}": str(row[1]) for row in hooks for prefix in ("ingest:", "meta:")}
    if not sources:
        return IngestActivityOut(items=[])

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
    return IngestActivityOut(
        items=[
            IngestActivityItemOut(
                source=sources.get(str(r[0]), "unknown"),
                event=r[1],
                # The three words the SURFACES spec uses, not our internal enum.
                outcome=(
                    "rejected"
                    if r[2] == "failed"
                    else ("accepted" if r[2] in ("processed", "enqueued") else "processing")
                ),
                deduplicated=int(r[3] or 0),
                error=r[4],
                first_at=r[5],
                last_at=r[6],
            )
            for r in rows
        ]
    )


class MetaSetupOut(BaseModel):
    """Everything a client needs to point a Meta app at this lead source, and the one
    thing they need to know before they bother.

    Declared rather than a bare dict for the same reason `IngestActivityItemOut` is:
    `scripts/check_redaction_exposure.py` inspects response MODELS, and a setup view is
    one careless field away from echoing the app secret it derives the token from.
    """

    model_config = ConfigDict(extra="forbid")

    callback_path: str
    # The `hub.verify_token` to paste into the Meta App Dashboard. DERIVED from the
    # endpoint secret (meta.verify_token_for) rather than stored, and it discloses
    # nothing about that secret.
    verify_token: str
    # What to subscribe the Page to.
    subscribe_field: str
    signature_header: str
    # The honest half: verified deliveries are recorded, but the lead's own answers
    # need a Graph read this deployment cannot make.
    lead_retrieval_available: bool
    lead_retrieval_reason: str | None


@sources_router.post(
    "/{webhook_id}/meta/setup",
    response_model=MetaSetupOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Callback URL + verify token for a Meta Lead Ads source (SURFACES §2b)",
)
async def meta_setup(
    webhook_id: UUID,
    session: SessionDep,
    principal: Principal = Depends(requires("org:manage")),
) -> MetaSetupOut:
    """POST for a read, and `org:manage` rather than `org:read` — the two go together.

    The response hands over a credential-shaped string, so it must not be reachable by
    a read-only impersonating admin (D-22). But D-22 is enforced structurally: NO GET
    may require a MUTATING permission, and `org:manage` is one — a GET here would fail
    `tests/impersonation_reads_test.py`, which walks the live route table precisely so
    this cannot be argued case by case.

    Both halves are satisfiable at once because the shape is wrong, not the permission.
    This is the same resolution `/v1/dnc/check` reached from the other direction: it is
    a POST because the IDENTIFIER is sensitive, and this is a POST because the RESPONSE
    is. Spending a D-22 exemption instead would buy one route a hole in the rule that
    five near-misses in this repo say should stay unarguable.

    It states the capability BEFORE the client wires anything up, rather than letting
    them discover it from an activity view full of rejections — the same argument
    `payment_capability` makes about rendering a pay button for a deployment that
    cannot take payments.
    """
    assert principal.tenant_id is not None
    config = await load_config(session, webhook_id)
    if config is None or config.source != META_SOURCE:
        raise ProblemError.not_found("Lead source")
    capability = meta.lead_retrieval_capability()
    return MetaSetupOut(
        callback_path=f"/hooks/v1/ingest/meta/{webhook_id}",
        verify_token=meta.verify_token_for(webhook_id=webhook_id, app_secret=config.secret_ref),
        subscribe_field=meta.LEADGEN_FIELD,
        signature_header=meta.SIGNATURE_HEADER,
        lead_retrieval_available=capability.available,
        lead_retrieval_reason=capability.reason,
    )


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


__all__ = ["META_SOURCE", "SECRET_HEADER", "router", "sources_router"]
