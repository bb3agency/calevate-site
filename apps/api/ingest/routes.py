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
from collections import Counter
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import alert
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import ingest_config_session, tenant_session
from apps.api.ingest import meta, service
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


class IngestAckOut(BaseModel):
    """What the SENDER is told about one delivery: ids and verdicts, never the lead.

    Declared rather than `dict[str, Any]`, and this is the response on this router where
    that matters most: the handler holds the sender's ENTIRE payload in scope, and an
    untyped return is one `**payload` away from echoing a customer's name and number back
    over a channel authenticated by a secret that gets pasted into form vendors. An
    untyped return is not a shape `scripts/check_redaction_exposure.py` judges safe — it
    inspects response MODELS, so it is a shape the guardrail cannot see at all (D-71).

    **On a `duplicate` every other field is null**, because THIS delivery decided
    nothing. The first one made the lead and the dial; re-deriving what it did from an
    inbox row that does not record it would be a claim we cannot back, and `dispatched:
    false` next to `status: duplicate` reads as "nobody was called", which is the one
    thing it must not be allowed to mean.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "duplicate"]
    lead_id: UUID | None = None
    # Whether THIS delivery placed the call. `false` with a `blocked` rule beside it is
    # the normal lawful outcome, not an error: the lead lands, the dial does not.
    dispatched: bool | None = None
    # The compliance rule that refused the dial (`dnc`, `no_form_consent`, `quiet_hours`,
    # …) — OUR authored rule name, never an exception's message. Null when nothing
    # refused it.
    blocked: str | None = None


class MetaLeadgenAckOut(BaseModel):
    """One verified Meta delivery, accounted for four ways.

    Meta itself reads only the status code; these counts are for US — they are what the
    delivery log and an operator tailing the response see, and `received != accepted +
    duplicate + refused` is the arithmetic that says a notification went missing.
    Declared for `IngestAckOut`'s reason: a counts-only response is safe by construction
    today and invisible to the redaction guardrail while it stays a bare dict.
    """

    model_config = ConfigDict(extra="forbid")

    # Lead notifications in the batch. Meta batches, so this is rarely 1.
    received: int
    accepted: int
    # Retries we absorbed without ringing the customer twice (deduped on `leadgen_id`).
    duplicate: int
    # Recorded against the `leadgen_id` with a reason the client can read, rather than
    # retried: our refusals here are permanent, and Meta unsubscribes a Page it cannot
    # deliver to.
    refused: int


@router.post(
    "/ingest/{webhook_id}",
    status_code=202,
    response_model=IngestAckOut,
    summary="Per-client lead intake → compliance-gated instant callback (FLOWS §4)",
)
async def ingest(webhook_id: UUID, request: Request) -> IngestAckOut:
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
            return IngestAckOut(status="duplicate")

        result = await ingest_lead(session, config=config, payload=payload, received_at=received_at)
        await mark_inbox_processed(session, row_id=claim.row_id)

    return IngestAckOut(
        status="accepted",
        lead_id=result["lead_id"],
        dispatched=bool(result["dispatched"]),
        blocked=result.get("blocked"),
    )


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
    # THE CURRENT SECRET ONLY, even mid-rotation. The grace window `accepted_secrets`
    # opens exists so a DELIVERY is not lost while the client finishes re-pasting, and a
    # handshake loses nothing: a refused subscription is retried with the token the
    # setup card is showing right now. Honouring the retiring token here would also take
    # back what `meta.verify_token_for` promises in as many words — that a rotated
    # secret leaves no stale token able to complete a subscription.
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
    response_model=MetaLeadgenAckOut,
    summary="Meta Lead Ads leadgen notifications, X-Hub-Signature-256 verified (SURFACES §2b)",
)
async def meta_leadgen(webhook_id: UUID, request: Request) -> MetaLeadgenAckOut:
    """One verified delivery → n leads, deduped per `leadgen_id`.

    Order is the security argument, and it is the same one `billing/payments.py` and
    the voice-runtime receiver make:

    1. bound the body BEFORE reading it — we cannot check a signature without the
       bytes, so an unauthenticated caller decides how much we allocate unless a cap
       decides first;
    2. verify the signature over those RAW bytes, before any parse;
    3. only then parse, normalize, and do work.

    The answer is 200 once the signature holds, including for the deliveries we REFUSE.
    Meta retries a non-2xx with backoff for hours and eventually unsubscribes the Page,
    and a refusal here is a verdict — an unreadable lead, a number we cannot dial, an
    agent nobody published — so retrying could only delay it and end with the client's
    integration switched off. The refusal is recorded instead, against the `leadgen_id`,
    where the client can see it.

    THE ONE EXCEPTION IS A TRANSIENT FAILURE, and it is 503 on purpose. A Graph timeout
    or a 5xx is not a verdict about the lead; it is us being unable to ask. Acking it
    200 would silently drop the enquiry the whole product exists to catch, and Meta's
    at-least-once ladder is a retry mechanism we already have — so we use it rather than
    building a second one. Redelivery is free because the `leadgen_id` claim absorbs the
    siblings that already committed: a batch of three with one deferred comes back as
    two duplicates and one fresh attempt.
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
    # Every secret this endpoint currently honours, not just the newest. A client who
    # rotates their Meta App Secret changes it in two places at two different moments,
    # and the deliveries in between are signed with the one they have not replaced yet —
    # those are leads, and the grace window (`accepted_secrets`) is what keeps them.
    # Unlike the handshake above, refusing here loses something.
    signature = request.headers.get(meta.SIGNATURE_HEADER)
    if not any(
        meta.verify_signature(app_secret=candidate, body=raw, header=signature)
        for candidate in config.accepted_secrets()
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
    outcomes: Counter[str] = Counter()
    for notification in notifications:
        outcomes[
            await _absorb_leadgen(
                webhook_id=webhook_id,
                config=config,
                notification=notification,
                received_at=received_at,
            )
        ] += 1
    ack = MetaLeadgenAckOut(
        received=len(notifications),
        accepted=outcomes["accepted"],
        duplicate=outcomes["duplicate"],
        refused=outcomes["refused"],
    )
    log.info(
        "meta_leadgen_received",
        extra={
            "webhook_id": str(webhook_id),
            **ack.model_dump(),
            # Not on the ack model, and not because it is unimportant: a deferred count
            # never travels in a 200 body, since the whole point of the 503 below is
            # that this delivery is NOT accounted for yet.
            "deferred": outcomes[_DEFERRED],
        },
    )
    if outcomes[_DEFERRED]:
        # Reached only when a lead could not be read for a reason that trying again can
        # fix. Everything that DID land above is committed and claimed, so Meta's
        # redelivery re-does exactly the part that failed.
        raise ProblemError(
            kind="transient",
            code="meta_lead_retrieval_deferred",
            title="Lead answers could not be fetched",
            # 503 is the one status allowed to keep a detailed message
            # (BACKEND-PATTERNS §3) and Meta reads only the code, so this sentence is
            # for the operator tailing the response. It names no lead and no reason
            # code: the reason is on the inbox row, where it belongs.
            detail="Fetching this lead's answers failed for a reason a retry can fix.",
            remediation="Meta will redeliver this notification; no action is needed.",
        )
    return ack


# The fourth outcome, spelled once. It is deliberately NOT a field of
# `MetaLeadgenAckOut`: a deferred delivery never travels in a 200 body, because the 503
# it produces is the statement that this delivery has not been accounted for yet.
_DEFERRED: Literal["deferred"] = "deferred"


async def _absorb_leadgen(
    *,
    webhook_id: UUID,
    config: IngestConfig,
    notification: meta.LeadNotification,
    received_at: float,
) -> Literal["accepted", "duplicate", "refused", "deferred"]:
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

    # ONE lookup for "may we read this client's leads" and "with what" — the capability
    # carries the retriever precisely so a second read cannot disagree with the first.
    # The question is per LEAD SOURCE, not per deployment: an adapter that holds no
    # token for this client is unavailable to this client, and says which.
    capability = meta.lead_retrieval_capability(source_id=webhook_id)
    if capability.retriever is None:
        # We hold the notification and not the answers, so there is no lead to write —
        # and writing one out of metadata we cannot read would be inventing it. Recorded
        # as failed with OUR reason code, which the activity view renders as `rejected`,
        # and re-claimable by CAS the moment a credential is attached.
        return await _record_refusal(
            config,
            claim.row_id,
            webhook_id=webhook_id,
            reason=capability.reason or meta.NO_RETRIEVER_REASON,
        )

    retrieved = await capability.retriever.fetch_answers(
        source_id=webhook_id, leadgen_id=notification.leadgen_id
    )
    if retrieved.status is meta.RetrievalStatus.TRANSIENT:
        # Mark the claim failed — which is what makes it RE-CLAIMABLE by CAS — and defer.
        # Not `mark_inbox_processed`: a row recorded as done is a lead nobody will ever
        # look at again, and this one is coming back.
        await _record_refusal(
            config, claim.row_id, webhook_id=webhook_id, reason=retrieved.reason or ""
        )
        return _DEFERRED
    if retrieved.status is meta.RetrievalStatus.PERMANENT:
        return await _record_refusal(
            config, claim.row_id, webhook_id=webhook_id, reason=retrieved.reason or ""
        )

    answers = retrieved.answers
    if not answers:
        # A lead with no answers at all is not a lead: there is no number to dial and
        # nothing to put in a row. Distinct from a Graph refusal, because the fix is
        # different — this one is about the client's form.
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


class LeadSourceDryRunStepOut(BaseModel):
    """One decision the real ingest path would have made, reported instead of acted on.

    **A caller's phone number is in scope where these are built, and it is not on this
    model.** The dry run normalizes the sample's number to decide whether it is dialable
    and to ask the compliance gate about it; what it reports is the VERDICT. Declaring
    the shape is what makes that structural rather than merely careful — `extra="forbid"`
    means a number can only ship from here if somebody ADDS a field, and
    `scripts/check_redaction_exposure.py` reports that field the moment they do.

    Until this model existed it could not: the guardrail inspects response MODELS, and
    this route answered `dict[str, Any]`, so it was not a route the check judged safe —
    it was a route the check could not see (the same defect as D-71's subject export and
    D-75's event catalogue). The half a schema walk still cannot judge is whether a
    STRING carries a number; `tests/response_shape_test.py` asserts the sample's own
    digits appear nowhere in the body.
    """

    model_config = ConfigDict(extra="forbid")

    # The five checks, in the order the real path applies them. A Literal rather than
    # `str`: the set is closed by construction — every value is emitted by the one
    # handler below — so the generated TypeScript client can switch on it exhaustively.
    # (This is NOT the case D-75 refused to narrow: there the server's list was a
    # DEPLOYMENT fact and the client's union a build-time one. These five are neither.)
    step: Literal["field_mapping", "phone_number", "agent", "form_consent", "compliance_gate"]
    ok: bool
    # A sentence for the person who pressed the button, never a value from their sample:
    # the only interpolation is the client's own CONFIGURED field name.
    detail: str
    # The compliance gate's rule name (`dnc`, `quiet_hours`, …) on the gate step. Null on
    # every other step, which is a different fact from "no rule fired".
    rule: str | None = None
    # Which of the client's configured fields the sample filled in — KEYS, never values.
    # Null where the question does not apply; `[]` on `field_mapping` is a real answer
    # ("your mapping matched nothing in this sample"), which is why it is not conflated.
    mapped_fields: list[str] | None = None


class LeadSourceDryRunOut(BaseModel):
    """Would a submission like this get a call right now, and every decision behind it.

    `would_call` is present tense on purpose: the gate reads the DNC list and the calling
    window live, so this is what would happen NOW rather than a property of the source.
    """

    model_config = ConfigDict(extra="forbid")

    would_call: bool
    steps: list[LeadSourceDryRunStepOut]


# --- provisioning (SURFACES §2b) ----------------------------------------------
#
# CLIENT REALM, and the same permissions the outbound endpoint surface next door uses:
# `org:read` to look, `org:manage` to change. A lead source is the client's own account
# configuration — which of their forms may hand us leads, which agent answers them —
# so it belongs where they already manage the OTHER direction of the same integration
# (`/v1/integrations/endpoints`), not behind a support request. `staff` holds `org:read`
# and not `org:manage` (SEC-COMP §5: staff do not get org settings), so a staff user can
# see that a source exists and cannot mint a credential; an impersonating operator gets
# the list and is refused every write (D-22), which is the same shape the outbound
# surface already has.
#
# An admin-realm twin was considered and NOT built. It would need its own tenant
# resolution, its own audit story and its own screen, to do what an operator can already
# do by impersonating for the read and asking the client to press the button for the
# write — and two provisioning paths for one row is precisely the drift the "one way per
# problem" rule is about. What the admin realm keeps is the part it uniquely holds: the
# `sm://` credential attachment SEC-COMP §5 will bring, which no client may ever name.


class CreateLeadSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["meta_lead_ads", "website_form", "zoho", "sheets", "custom"]
    # Which agent answers leads from this source. Optional because the honest answer at
    # setup time is often "not yet" — `ingest_lead` refuses with `ingest_no_agent` and
    # names the fix, rather than this route forcing a guess.
    agent_id: UUID | None = None
    # `dict[str, str]`, not `dict[str, Any]`: a mapping value is a field NAME, and the
    # loose type is also the shape `scripts/check_redaction_exposure.py` refuses on a
    # response model. Validated in `service.validate_mapping`.
    mapping: dict[str, str] = Field(default_factory=dict)
    # Only for the sources whose secret is not ours to mint (Meta's App Secret). The
    # field is named for what it is so nobody pastes a Page access token into it.
    app_secret: str | None = Field(default=None, min_length=8, max_length=512)


class LeadSourceCreatedOut(BaseModel):
    """The one moment a minted secret is ever returned."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    source: str
    ingest_path: str
    # `null` when the client supplied the secret themselves — there is nothing of ours
    # to show once. Never re-readable: no other route returns this field.
    secret: str | None
    secret_header: str


class LeadSourceOut(BaseModel):
    """A lead source as the config screen sees it — fingerprint only, never a value."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    source: str
    agent_id: UUID | None
    active: bool
    mapping: dict[str, str]
    secret_fingerprint: str
    # Set only while a rotation grace window is still open; `null` the moment it closes.
    previous_secret_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadSourceListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LeadSourceOut]
    secret_header: str


class RotateSecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An hour by default, zero on request. The default is a planned rotation, where the
    # client still has to paste the new value into a form vendor; zero is a revocation,
    # which is what a leak needs and what nobody should get by accident.
    grace_minutes: int = Field(default=60, ge=0, le=service.MAX_GRACE_MINUTES)
    app_secret: str | None = Field(default=None, min_length=8, max_length=512)


class RotateSecretOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    secret: str | None
    secret_header: str
    # When the OLD secret stops working; `null` means it already has.
    previous_secret_expires_at: datetime | None


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
    # PER LEAD SOURCE, not per deployment. A deployment with the Graph adapter selected
    # and no token attached for THIS source can no more fetch this client's answers than
    # one with no adapter at all, and the reason code says which of the two it is.
    capability = meta.lead_retrieval_capability(source_id=webhook_id)
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
    response_model=LeadSourceDryRunOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Dry-run a sample lead end-to-end WITHOUT placing a call (SURFACES §2b)",
)
async def test_webhook(
    webhook_id: UUID,
    body: TestWebhookIn,
    session: SessionDep,
    principal: Principal = Depends(requires("org:manage")),
) -> LeadSourceDryRunOut:
    """Everything the real path would decide, nothing it would do.

    This is NOT a compliance-gate bypass (hard rule 5 forbids those): no lead row is
    written, no call is dispatched, no inbox row is claimed. The gate is CONSULTED —
    same function, same live DNC read — and its verdict is reported instead of acted
    on. The difference between this and a bypass is the direction of the arrow: a
    bypass dials without asking; this asks without dialling.

    The number the sample carries is normalized here and never leaves: every step
    reports a verdict, `mapped_fields` reports KEYS, and the model above is what makes
    that a rule the guardrail enforces rather than a habit this function has.
    """
    assert principal.tenant_id is not None
    config = await load_config(session, webhook_id)
    if config is None:
        raise ProblemError.not_found("Lead source")

    mapped = apply_mapping(config.mapping, body.payload) if config.mapping else dict(body.payload)
    raw_phone = str(mapped.get("phone") or mapped.get("phone_number") or "")
    phone = normalize_phone(raw_phone) if raw_phone else None

    steps: list[LeadSourceDryRunStepOut] = [
        LeadSourceDryRunStepOut(
            step="field_mapping",
            ok=bool(mapped),
            detail=f"{len(mapped)} of your configured fields matched the sample.",
            mapped_fields=sorted(mapped.keys()),
        ),
        LeadSourceDryRunStepOut(
            step="phone_number",
            ok=phone is not None,
            detail=(
                "Found a dialable Indian number."
                if phone
                else "No dialable phone number — the real webhook would answer 422."
            ),
        ),
    ]
    if phone is None or config.agent_id is None:
        if config.agent_id is None:
            steps.append(
                LeadSourceDryRunStepOut(
                    step="agent", ok=False, detail="No agent attached to this source."
                )
            )
        return LeadSourceDryRunOut(would_call=False, steps=steps)

    consent_field = config.mapping.get("consent_field")
    if isinstance(consent_field, str) and consent_field:
        affirmed = str(body.payload.get(consent_field, "")).strip().lower() in (
            "true",
            "yes",
            "1",
            "on",
        )
        steps.append(
            LeadSourceDryRunStepOut(
                step="form_consent",
                ok=affirmed,
                detail=(
                    f"The '{consent_field}' field confirms permission to call."
                    if affirmed
                    else f"The '{consent_field}' field does not confirm permission — the lead "
                    "would be saved but never dialled."
                ),
            )
        )
        if not affirmed:
            return LeadSourceDryRunOut(would_call=False, steps=steps)

    decision = await check_dispatch(
        session, tenant_id=principal.tenant_id, agent_id=config.agent_id, phone_e164=phone
    )
    steps.append(
        LeadSourceDryRunStepOut(
            step="compliance_gate",
            ok=decision.allowed,
            detail=(
                "The call would be placed."
                if decision.allowed
                else decision.reason or "The gate would refuse this dial."
            ),
            rule=decision.rule,
        )
    )
    return LeadSourceDryRunOut(would_call=decision.allowed, steps=steps)


def _ingest_path(webhook_id: UUID, source: str) -> str:
    """The URL the sender posts to, built from the routes above rather than typed out.

    A Meta source has a DIFFERENT receiver (signature-verified, `leadgen_id`-deduped),
    and handing a client the shared-secret path for it would produce a source that
    authenticates with a header Meta never sends.
    """
    return (
        f"/hooks/v1/ingest/meta/{webhook_id}"
        if source == META_SOURCE
        else f"/hooks/v1/ingest/{webhook_id}"
    )


@sources_router.get(
    "",
    response_model=LeadSourceListOut,
    openapi_extra=permission_meta("org:read"),
    summary="Every lead source on this account — fingerprints, never secrets (SURFACES §2b)",
)
async def list_lead_sources(
    session: SessionDep,
    # A READ permission on a read, same as the activity view beside it: nothing here is
    # written and no secret VALUE is returned, so hiding it from a read-only
    # impersonating operator (D-22) would cost support the screen and buy nothing.
    _: Principal = Depends(requires("org:read")),
) -> LeadSourceListOut:
    """The list that made the ID box on the lead-sources screen unnecessary.

    Tenant scoping is RLS and only RLS (hard rule 1) — there is no `WHERE tenant_id`
    here, because a hand-written predicate beside the policy is a second, weaker
    boundary that the next query forgets.
    """
    return LeadSourceListOut(
        items=[
            LeadSourceOut(
                id=row.id,
                source=row.source,
                agent_id=row.agent_id,
                active=row.active,
                mapping=row.mapping,
                secret_fingerprint=row.secret_fingerprint,
                previous_secret_expires_at=row.previous_secret_expires_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in await service.list_lead_sources(session)
        ],
        secret_header=SECRET_HEADER,
    )


@sources_router.post(
    "",
    response_model=LeadSourceCreatedOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Create a lead source — the ingest secret is shown once (SURFACES §2b)",
    # Stated rather than inherited from the docstring, for the reason
    # `create_sheets_endpoint` gives: `/docs` is public, and the argument below names
    # column names and internal call sites.
    description=(
        "Create an endpoint your website form, CRM or ad account can post leads to. "
        "The response carries the secret to send in the `X-Ingest-Secret` header, and "
        "it is the only time that value is ever returned — the list endpoint shows a "
        "fingerprint. Meta Lead Ads sources are different: Meta signs with your own "
        "app's App Secret, so you supply it as `app_secret` and nothing is minted."
    ),
)
async def create_lead_source(
    payload: CreateLeadSourceIn,
    session: SessionDep,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> LeadSourceCreatedOut:
    """`org:manage`, and audited in the same transaction as the row.

    Creating a lead source mints a credential that dials this tenant's customers on
    arrival, which puts it in the same class as the outbound endpoint that ships their
    leads elsewhere: an account-level decision, not a lead-handling one, so `staff` is
    out (SEC-COMP §5) and an impersonating operator is refused (D-22).

    The audit summary carries IDS AND THE SOURCE NAME AND NOTHING ELSE — no secret, no
    fingerprint. `write_audit`'s summary is written to the log stream, and a fingerprint
    in a log is a stable identifier for a live credential.
    """
    assert principal.tenant_id is not None
    webhook_id, minted = await service.create_lead_source(
        session,
        tenant_id=principal.tenant_id,
        source=payload.source,
        agent_id=payload.agent_id,
        mapping=payload.mapping,
        supplied_secret=payload.app_secret,
    )
    await write_audit(
        session,
        action="lead_source.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="inbound_webhook",
        object_id=str(webhook_id),
        ip=request.client.host if request.client else None,
        summary={"source": payload.source, "agent_id": str(payload.agent_id or "")},
    )
    return LeadSourceCreatedOut(
        id=webhook_id,
        source=payload.source,
        ingest_path=_ingest_path(webhook_id, payload.source),
        secret=minted,
        secret_header=SECRET_HEADER,
    )


@sources_router.post(
    "/{webhook_id}/rotate-secret",
    response_model=RotateSecretOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Issue a new secret, with the old one honoured for a stated window",
    description=(
        "Replace this source's secret. The new value is returned once. The previous "
        "secret keeps working for `grace_minutes` (default 60, max 1440) so leads "
        "submitted while you update your form vendor are not rejected — send "
        "`grace_minutes: 0` to revoke the old secret immediately, which is what a "
        "leaked secret needs. For a Meta source, supply the new App Secret as "
        "`app_secret`; nothing is minted and the response's `secret` is null."
    ),
)
async def rotate_lead_source_secret(
    webhook_id: UUID,
    payload: RotateSecretIn,
    session: SessionDep,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> RotateSecretOut:
    """The rotation is safe by DEFAULT and instant by REQUEST, and the response says
    which one happened — `previous_secret_expires_at` is the deadline the client has to
    finish pasting, or `null` when they asked for none."""
    assert principal.tenant_id is not None
    rotation = await service.rotate_secret(
        session,
        webhook_id=webhook_id,
        grace_minutes=payload.grace_minutes,
        supplied_secret=payload.app_secret,
    )
    await write_audit(
        session,
        action="lead_source.secret_rotated",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="inbound_webhook",
        object_id=str(webhook_id),
        ip=request.client.host if request.client else None,
        # The GRACE is the security-relevant fact: "rotated with an hour of overlap" and
        # "revoked on the spot" are different answers to an incident review.
        summary={"grace_minutes": payload.grace_minutes},
    )
    return RotateSecretOut(
        id=webhook_id,
        secret=rotation.secret,
        secret_header=SECRET_HEADER,
        previous_secret_expires_at=rotation.previous_secret_expires_at,
    )


@sources_router.delete(
    "/{webhook_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Disable — kept, not deleted, so the delivery history stays readable",
)
async def disable_lead_source(
    webhook_id: UUID,
    session: SessionDep,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> None:
    """Deactivate, and close any rotation window with it.

    Idempotent: disabling an already-disabled source is 204, not 404. The outbound
    twin (`DELETE /v1/integrations/endpoints/{id}`) once answered 404 to the second
    click, because its CAS predicate and its existence check were the same statement;
    it now shares this shape (`integrations.service.deactivate_endpoint`), so the two
    directions of D-23 answer the same question the same way. The audit row is written
    only for a real transition, so the ledger records changes and not button presses.
    """
    assert principal.tenant_id is not None
    if await service.set_active(session, webhook_id=webhook_id, active=False):
        await write_audit(
            session,
            action="lead_source.disabled",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="inbound_webhook",
            object_id=str(webhook_id),
            ip=request.client.host if request.client else None,
        )


@sources_router.post(
    "/{webhook_id}/enable",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Re-enable a disabled lead source",
)
async def enable_lead_source(
    webhook_id: UUID,
    session: SessionDep,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> None:
    """The other half of disable, which the outbound surface never grew.

    Without it a client who disabled a source to stop a misbehaving form has no way
    back except a support ticket — which is the same out-of-band provisioning this whole
    module exists to end. The secret is UNCHANGED by re-enabling: a source comes back
    exactly as it left, so a client who did not rotate does not have to re-paste.
    """
    assert principal.tenant_id is not None
    if await service.set_active(session, webhook_id=webhook_id, active=True):
        await write_audit(
            session,
            action="lead_source.enabled",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="inbound_webhook",
            object_id=str(webhook_id),
            ip=request.client.host if request.client else None,
        )


__all__ = ["META_SOURCE", "SECRET_HEADER", "router", "sources_router"]
