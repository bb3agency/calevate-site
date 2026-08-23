"""Client-realm CRM endpoints (SURFACES §2).

Every route declares its permission twice on purpose: once as a dependency that
ENFORCES it, once in `openapi_extra` that DOCUMENTS it. The boot assertion
(`assert_policy_registry_complete`) reads the second and fails startup if a route
forgot — so a new endpoint cannot ship silently unguarded (BACKEND-PATTERNS §7).

Three routes here touch the compliance/PII rules directly and are commented in place:
raw transcript, recording link, and "call this lead".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import CALL_CAP_MAX_S
from apps.api.billing import service as billing
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm import assist, saved_views, service
from apps.api.crm import columns as lead_column_registry
from apps.api.crm.attention import attention_queue
from apps.api.crm.performance import performance
from apps.api.crm.schemas import (
    AttentionOut,
    CallAssistOut,
    CallbackEligibilityOut,
    CallbackOut,
    CallDetailOut,
    CallLeadIn,
    CallLeadOut,
    CallSummaryOut,
    DashboardOut,
    LeadBulkFailureOut,
    LeadBulkIn,
    LeadBulkOut,
    LeadColumnOut,
    LeadFacetOut,
    LeadFacetsOut,
    LeadFacetValueOut,
    LeadLensIn,
    LeadListOut,
    LeadOut,
    LeadSearchIn,
    LeadTimelineOut,
    LeadUpdateIn,
    PerformanceOut,
    RecordingLinkOut,
    SavedViewIn,
    SavedViewListOut,
    SavedViewOut,
    SavedViewUpdateIn,
    UsagePanelOut,
)
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)
from apps.workers.extraction import run_assist

router = APIRouter(prefix="/v1", tags=["crm"])

Session = Annotated[AsyncSession, Depends(db)]


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Headline numbers for the client dashboard",
)
async def get_dashboard(
    session: Session, _: Principal = Depends(requires("calls:read"))
) -> DashboardOut:
    return await service.dashboard(session)


@router.get(
    "/calls",
    response_model=list[CallSummaryOut],
    openapi_extra=permission_meta("calls:read"),
)
async def get_calls(
    session: Session,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    agent_id: UUID | None = None,
    _: Principal = Depends(requires("calls:read")),
) -> list[CallSummaryOut]:
    return await service.list_calls(
        session, limit=limit, offset=offset, status=status, agent_id=agent_id
    )


#: The floor on a recording link's life, and the value every link used to get.
#: Enough to start playing a short call on a slow connection.
RECORDING_LINK_FLOOR_S = 300
#: The ceiling. `CALL_CAP_MAX_S` is one hour, so twice a maximal call plus the floor is
#: the longest link this can ever mint — stated as its own constant so the widest
#: credential window this route can open is a number a reviewer can read, not one they
#: have to derive from an arithmetic expression.
RECORDING_LINK_CEILING_S = 2 * CALL_CAP_MAX_S + RECORDING_LINK_FLOOR_S


def recording_link_ttl_s(duration_s: int | None) -> int:
    """How long this call's presigned link must live: derived from the audio, not guessed.

    **THE DEFECT THIS CLOSES.** Every link was minted for a flat 300 seconds while
    `CALL_CAP_MAX_S` lets a call run for 3600. S3 rejects the request the moment the
    signature expires, and a browser mid-playback reports that as a bare `MEDIA_ERR_
    NETWORK` on the `<audio>` element — so a twenty-minute call played for five minutes
    and then stopped, with no message, and the owner's reasonable conclusion was that we
    had only recorded the first five minutes. The link has to outlive the thing it points
    at or it is not a link to that thing.

    **Twice the duration, not once.** A listener pauses, rewinds, re-reads a turn and
    scrubs back; a link sized to exactly one pass expires on anyone who does more than
    press play and wait. Doubling is the cheapest allowance that covers ordinary review
    behaviour, and it is bounded above by a constant either way.

    **Why not simply raise `PRESIGN_TTL_S`?** Because that constant is shared with every
    other presigned artefact, and the signature IS the credential — widening it globally
    would hand a longer window to objects that need seconds. Deriving it per call keeps
    the window proportional to the only thing that justifies it.

    An unknown duration (a call the poller never resolved) gets the floor rather than the
    ceiling: guessing long on a recording whose length we do not know is the wrong
    direction to be generous in, and the screen re-mints when a link expires.
    """
    if duration_s is None or duration_s <= 0:
        return RECORDING_LINK_FLOOR_S
    return min(max(RECORDING_LINK_FLOOR_S, duration_s * 2), RECORDING_LINK_CEILING_S)


@router.get(
    "/calls/{call_id}",
    response_model=CallDetailOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Call detail — transcript is REDACTED by default (hard rule 5)",
)
async def get_call(
    call_id: UUID, session: Session, _: Principal = Depends(requires("calls:read"))
) -> CallDetailOut:
    return await service.get_call(session, call_id, raw=False)


@router.get(
    "/calls/{call_id}/transcript/raw",
    response_model=CallDetailOut,
    openapi_extra=permission_meta("calls:read_raw"),
    summary="Unredacted transcript — role-checked AND audit-logged on every read",
)
async def get_raw_transcript(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("calls:read_raw")),
) -> CallDetailOut:
    # The audit row is written in the SAME transaction as the read, so there is no
    # window in which someone saw raw PII without it being recorded (hard rule 5).
    await write_audit(
        session,
        action="transcript.read_raw",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=client_request_ip(request),
    )
    return await service.get_call(session, call_id, raw=True)


@router.get(
    "/calls/{call_id}/recording",
    response_model=RecordingLinkOut,
    # `calls:read_raw`, NOT `calls:read` — the same move `/v1/leads/export.csv` made and
    # for a stronger reason. THE AUDIO IS THE SOURCE OF THE TEXT the whole redaction
    # apparatus protects: a caller who reads out an Aadhaar number, a card number or an
    # OTP is masked in `text_redacted` and audible in the recording. `calls:read` is held
    # by `staff` (core/rbac.py), so this route handed the unredacted artefact to exactly
    # the role SEC-COMP §5 and DATA-MODEL §2 both say never sees one — while the raw
    # transcript beside it was already `calls:read_raw` + audit. The route had the audit
    # half of hard rule 5 and not the role half; this is the other half.
    openapi_extra=permission_meta("calls:read_raw"),
    summary="Short-lived presigned link to OUR copy of the recording — owner-only, audited",
)
async def get_recording(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("calls:read_raw")),
) -> RecordingLinkOut:
    ref = await service.recording_ref_for(session, call_id)
    await write_audit(
        session,
        action="recording.read",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=client_request_ip(request),
    )
    # Imported here, not at module scope: the presigner lives in the workers package
    # and pulling boto3 into every API import would slow cold starts for one route.
    from apps.workers.storage import presigned_url

    ttl_s = recording_link_ttl_s(ref.duration_s)
    url = presigned_url(ref.key, ttl_s=ttl_s)
    if url is None:
        raise ProblemError(
            kind="dependency",
            code="recording_unavailable",
            title="Recording unavailable",
            detail="The recording could not be retrieved right now.",
        )
    return RecordingLinkOut(url=url, expires_in_s=ttl_s, duration_s=ref.duration_s)


@router.post(
    "/calls/{call_id}/assist",
    response_model=CallAssistOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Re-summarise this call with the assistant model — metered, quota-gated (D-127)",
    description=(
        "Runs the dashboard assistant over this call's REDACTED transcript and returns a "
        "fresh summary. Nothing is stored: the call's own summary and captured fields are "
        "the first pass over the raw transcript and are left alone. Refused before any "
        "model is called when the account is past its included AI allowance — the screen "
        "opens the wallet dialog on `ai_quota_exceeded`. A `Idempotency-Key` header is "
        "REQUIRED so a double-click is paid for once. Requires `org:manage`."
    ),
)
async def assist_call(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CallAssistOut:
    """SUBJECT → GATE → RUN → METER. `crm/assist.py`'s docstring argues each arrow.

    **`org:manage`, and it is the whole population question.** This is a POST that spends
    money, so `test_every_mutating_route_is_gated_by_a_mutating_permission` requires a
    permission in `MUTATING_PERMISSIONS` — which also means an operator inside a D-22
    read-only "view as client" session cannot spend a client's allowance from a client
    screen. Of the mutating permissions a client role holds, `org:manage` is the one this
    console already uses for the whole AI surface: `GET /v1/billing/ai-quota` is
    `billing:read` and `POST /v1/billing/ai-quota/extra` is `org:manage`, both owner-only,
    on SEC-COMP §5's ground that spend is an owner's business. Gating the thing that
    SPENDS the allowance more loosely than the panel that displays it would be this
    product disagreeing with itself. `leads:write` was the alternative — staff hold it, so
    it would let staff re-summarise — and was rejected because it names the wrong object
    on a call route and would put "leads:write" in the audit row for an act on a call. A
    new `calls:assist` was rejected on `bulk_leads`'s ground: its holder set would be
    exactly `leads:write`'s, and a permission every role holds precisely when it holds
    another is a fourth registry entry that buys nothing.

    **The `Idempotency-Key` is REQUIRED**, which `POST /v1/leads/{lead_id}/call` does not
    do, and the difference is what a repeat costs. A repeated dial re-runs the compliance
    gate and is bounded by the follow-up ladder; a repeated assist is a second, silent
    payment to our model provider — Azure OpenAI since D-410, Google when this was written
    — with nothing else in front of it. D-140 removed the client-suppliable
    metering `ref` precisely so that dedupe could not happen after the provider was paid,
    and moved double-click protection here. An OPTIONAL key would protect only the callers
    that remember to send one, i.e. this console on the day it was written, which is the
    argument `ops/config_routes.require_if_match` already makes for `If-Match`. 400 with a
    problem body is what draft-ietf-httpapi-idempotency-key-header-07 §2.4 asks for when
    the header is missing on an operation that documents it (RFC 9457 supersedes the
    draft's RFC 7807 reference; the shape is the same).
    """
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session
    tenant_id = principal.tenant_id

    idem_key = request.headers.get("Idempotency-Key")
    if not idem_key:
        raise ProblemError(
            kind="validation",
            status=400,
            code="idempotency_key_required",
            title="This request has to carry an Idempotency-Key",
            detail=(
                "Running the assistant costs money, so every attempt names itself and a "
                "repeat of the same attempt is answered rather than re-run."
            ),
            remediation="Send an `Idempotency-Key` header — one fresh value per attempt.",
        )
    # THE CLAIM COMMITS BEFORE THE MODEL RUNS, in its own transaction — the shape
    # `billing/payment_routes._create_order_once` argues for and the shape this route
    # did not have. Written into the REQUEST's transaction it was rolled back by
    # `core/deps.db` on any later exception, so a raise anywhere after `run_assist`
    # (a statement timeout, a severed connection, a refused audit write) erased the
    # claim, the usage rows and the audit row while the model provider had already been
    # paid (Azure OpenAI since D-410) — and the retry with the same key, which is what the
    # key is FOR, paid a second time.
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route="/v1/calls/{call_id}/assist",
            method="POST",
            key=idem_key,
            request_hash=body_hash({"call_id": str(call_id)}),
        )
    if claim.state == "replay" and claim.response_payload:
        # The stored answer, not a second run. This is the double-click, and it is
        # answered BEFORE the model is called, which is the only place answering it saves
        # anything (`billing/ai_quota.ASSIST_REF_PREFIX`).
        return CallAssistOut.model_validate(claim.response_payload)

    # STEPS 1-3 ARE ONE ARM, AND THE BOUNDARY IS "HAS THE PROVIDER BEEN PAID".
    #
    # This `try` used to open at step 3, around `run_assist` alone, and the two refusals
    # above it therefore left the claim `processing` for the whole `CLAIM_LEASE` — a
    # client who was told "this call has no transcript" or "you are at your ceiling"
    # could not reuse the key they had just been refused on, and got
    # `idempotent_request_in_flight` for a request that cost nothing. The browser worked
    # around it by minting a FRESH key per attempt, which is worse than the bug it hides:
    # a key that is never reused cannot dedupe, so a lost response — a 504, a dropped
    # connection — on a run the server COMPLETED pays a second time, which is the exact
    # event this required header exists to prevent.
    #
    # So the arm covers everything up to and including the provider call, and stops
    # there. `run_assist` RETURNING is the instant the money is spent, and every failure
    # after it keeps the claim on purpose — that half is the mechanism working, and step 4
    # says why. Releasing on a pre-payment refusal is not a relaxation of it: the two
    # cases are opposites, and conflating them is what left this one open.
    try:
        # 1. THE SUBJECT, before the money. A call with no readable redacted transcript
        #    cannot be summarised at any price, and finding that out after the ceiling
        #    check would answer a client at their limit with "add ₹500" for a call the
        #    money would not have helped with.
        source = await assist.load_assist_source(session, call_id)

        # 2. THE GATE. It RAISES — `ai_quota_exceeded` is what opens the wallet dialog
        #    (G-5), `ai_paused_platform_wide` is the brake — so a refusal reaches the
        #    client without a token having been spent. Everything below this line costs
        #    money.
        quota = await require_ai_assist(session, tenant_id=tenant_id)

        # 3. THE RUN. The key is minted HERE, by the server, per attempt:
        #    `record_ai_assist_usage` accepts nothing else, because its idempotency is a
        #    switch that turns metering off (D-140).
        ref = new_assist_ref()
        result = await run_assist(
            source.spec,
            # `text_redacted`, assembled by `crm/assist.py`, which never names the raw
            # column. `run_assist` re-runs `redact()` over this and REFUSES text that
            # still matches — that guard had no caller until this line, and this line
            # must not defeat it.
            source.transcript,
            # The gate's verdict, passed IN rather than re-read. It is False on every
            # path that reaches here — `require_ai_assist` RAISES at the ceiling rather
            # than returning "no", which is G-5's block — and it is written as the READ
            # rather than as a literal `False` so that this caller stays correct if the
            # gate ever learns to answer instead of raise. A literal would be a promise
            # about another module's control flow, made in this one.
            quota_exhausted=quota.at_ceiling,
        )
    except Exception:
        # NOTHING HAS BEEN PAID FOR ON ANY PATH THAT REACHES HERE, so the key is released
        # rather than left `processing`: a refused attempt that kept it would answer the
        # client's own retry with "already in flight" for the whole lease, for a request
        # that cost nothing. Its own transaction, for the same reason the claim had one —
        # the request's is about to roll back. `_create_order_once`'s failure arm, exactly.
        async with tenant_session(tenant_id) as fail_session:
            await fail_idempotency(fail_session, record_id=claim.record_id)
        raise

    # 4. THE METER, THE AUDIT AND THE CLAIM'S COMPLETION, in ONE transaction of their
    #    own — the record of a payment that has already happened. It is deliberately not
    #    the request's transaction: that one rolls back on any later exception, and this
    #    is the exact set of rows whose disappearance made a paid call look un-made.
    #    `meter_assist` never raises; if the audit write or the completion does, the money
    #    is unrecorded and the claim stays `processing`, which refuses the retry for the
    #    lease rather than paying twice — and the raise is what tells an operator.
    async with tenant_session(tenant_id) as record_session:
        metered = await assist.meter_assist(
            record_session, tenant_id=tenant_id, ref=ref, result=result
        )
        out = CallAssistOut(
            # The same `redact()` pass `calls.summary` goes out through. The model was
            # given redacted text and so cannot have copied a digit it never saw; this is
            # the belt to that braces, and it is what lets the redaction guardrail's entry
            # for this field say what `CallDetailOut.summary`'s says.
            summary=service.redacted_summary(result.output.summary) or "",
            disclosure=result.capability.disclosure,
            metered=metered.metered,
        )
        await write_audit(
            record_session,
            action="call.ai_assist",
            actor=principal,
            tenant_id=tenant_id,
            object_type="call",
            object_id=str(call_id),
            ip=client_request_ip(request),
            # `usage_events` records the tenant, the cost and the key; it does not record
            # WHO asked or WHICH call was read (`call_id IS NULL` is in the index
            # predicate). A transcript being handed to a sub-processor is a processing act
            # under DPDP and the actor and the subject are exactly what a grievance asks
            # for, so they are recorded here. Ids, a provider name and a boolean — no
            # prose, no output.
            summary={
                "provider": result.capability.provider,
                "fallback_reason": result.capability.fallback_reason,
                "metered": metered.metered,
                "ref": ref,
            },
        )
        await complete_idempotency(
            record_session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=out.model_dump(),
        )
    return out


# --- the Leads table's lens: which rows, and which columns --------------------
#
# `columns` and `f` are the two halves of one question, and they are declared here once
# and taken by BOTH `GET /v1/leads` and `GET /v1/leads/export.csv` with identical
# meanings. That is the whole "column chooser mirrored in CSV export" requirement
# (SURFACES §2): the file the client downloads is the table they were looking at.
#
# **The asymmetry between an unknown COLUMN and an unknown FILTER is deliberate, and it
# is a safety property rather than a taste.** Both can go stale — an admin edits the
# agent's extraction schema (D-21: admin-only, so the client never sees it coming) and a
# bookmark or a saved view outlives it.
#
#   * An unknown COLUMN key is DROPPED, and reported in `dropped_column_keys`. It
#     narrows the table, it is applied identically to the screen and the file (one
#     resolver, `crm.columns.resolve`), and a client's stale bookmark should keep
#     working. Nothing they can act on is hidden by it.
#   * An unknown FILTER key is REFUSED, 422. Dropping it would WIDEN the set: somebody
#     narrows the table to eleven hot leads, presses Export, and mails a supplier the
#     whole contact list with full phone numbers. A filter that silently did nothing is
#     the one failure this route must never have, so the request fails instead — and the
#     saved-view read is where a stale reference is pruned VISIBLY (`crm.saved_views`).
_COLUMNS_Q = Query(
    None,
    description="Comma-separated column keys, in display order. Omit for every column.",
)
_FIELD_FILTER_Q = Query(
    default_factory=list,
    alias="f",
    description=(
        "Facet filter, repeatable: `f=<extraction_key>:<value>`. Repeating one key ORs "
        "its values; different keys AND together."
    ),
)


def _parse_columns(raw: str | None) -> list[str] | None:
    """`None` (no choice) and `""` (a chooser that cleared itself) are the same answer.

    They have to be: a browser that drops an empty query parameter and one that sends it
    are both saying "the client picked nothing", and a file with no columns in it is not
    a smaller file, it is not a file.
    """
    if raw is None:
        return None
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys or None


def _parse_field_filters(raw: list[str], allowed: frozenset[str]) -> service.FieldFilters:
    """`f=key:value` → `{key: [value, ...]}`, refusing anything this agent cannot filter on.

    Split on the FIRST colon, which is unambiguous because an extraction key is
    `^[a-z][a-z0-9_]{0,39}$` and therefore contains none — a value that contains one
    survives intact.
    """
    parsed: service.FieldFilters = {}
    for entry in raw:
        key, sep, value = entry.partition(":")
        if not sep or not key or not value:
            raise ProblemError(
                kind="validation",
                code="lead_filter_malformed",
                title="Unreadable filter",
                detail=f"{entry!r} is not a filter. Filters are written `f=field:value`.",
                remediation="Re-apply the filter from the Leads screen.",
            )
        if key not in allowed:
            # Named, because the client can act on it: this is the field an admin removed
            # from their capture list, and the fix is to drop the chip.
            raise ProblemError(
                kind="validation",
                code="lead_filter_unknown_field",
                title="Unknown filter",
                detail=f"“{key}” is not a filterable field on this agent's capture list.",
                remediation=(
                    "Clear that filter and pick one from the panel. If it was a saved "
                    "view, open it again — the view will tell you which filters it lost."
                ),
            )
        parsed.setdefault(key, []).append(value)
    return parsed


def _column_out(column: lead_column_registry.LeadColumn) -> LeadColumnOut:
    return LeadColumnOut(key=column.key, label=column.label, kind=column.kind, type=column.type)


#: What a GET is told when it carries a search term.
#:
#: REFUSED, NEVER IGNORED. FastAPI drops an undeclared query parameter silently, and a
#: silently-dropped `search` WIDENS the result set — the exact failure `_FIELD_FILTER_Q`
#: above refuses an unknown facet for, and on `export.csv` it is the difference between
#: eleven hot leads and the client's whole contact list leaving with full phone numbers.
_SEARCH_MOVED_TO_POST = ProblemError(
    kind="validation",
    code="search_must_be_posted",
    title="Search terms are sent in a request body, not a URL",
    detail=(
        "The search box matches phone numbers, and a URL is written to access logs, "
        "browser history and referrers."
    ),
    remediation="Send the same lens to POST /v1/leads/search (or POST /v1/leads/export.csv).",
)


def _refuse_search_in_query(search: str | None) -> None:
    if search is not None:
        raise _SEARCH_MOVED_TO_POST


async def _leads_page(session: AsyncSession, lens: LeadSearchIn) -> LeadListOut:
    """One implementation of "the Leads table", for both shapes of the request.

    `agent_id` filters the ROWS as well as choosing the columns. It used to do only the
    latter, which meant this route and the export disagreed about what the same parameter
    meant, and a two-agent tenant read one agent's leads under the other's capture list.
    See `service._lead_scope` for the reasoning.
    """
    fields = await service.lead_columns(session, lens.agent_id)
    available = lead_column_registry.available(fields)
    resolved = lead_column_registry.resolve(available, _parse_columns(lens.columns))
    field_filters = _parse_field_filters(
        lens.f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )
    page = await service.list_leads_page(
        session,
        limit=lens.limit,
        offset=lens.offset,
        status=lens.status,
        search=lens.search,
        agent_id=lens.agent_id,
        assigned_to=lens.assigned_to,
        field_filters=field_filters,
    )
    return LeadListOut(
        items=page.items,
        # Columns travel with the rows so the frontend never hard-codes a client's
        # fields (TRD §7 (c)) — and they are the RESOLVED list, identical to the header
        # the export writes for the same lens.
        columns=[_column_out(c) for c in resolved.columns],
        available_columns=[_column_out(c) for c in available],
        dropped_column_keys=list(resolved.dropped),
        total=page.total,
        limit=lens.limit,
        offset=lens.offset,
        status_counts_matching_search=page.status_counts,
    )


@router.get("/leads", response_model=LeadListOut, openapi_extra=permission_meta("leads:read"))
async def get_leads(
    session: Session,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    # DECLARED SO IT CAN BE REFUSED. The parameter is gone as a feature and kept as a
    # 400: a client still sending it is asking for a narrowed table and would otherwise
    # be handed a wider one.
    search: str | None = Query(None, deprecated=True, description="Moved to POST /v1/leads/search"),
    agent_id: UUID | None = None,
    # "My leads", as a real predicate on a real column. A UUID rather than a `me`
    # literal, for two reasons: the same parameter then answers "show me Priya's leads"
    # off the owner column without a second spelling, and `me` would have to mean
    # something for an admin viewing this account through D-22 impersonation, whose
    # `principal.user_id` is an `admin_users` row that can own no lead. The screen sends
    # its own id from `/v1/me` and says so where the control is.
    assigned_to: UUID | None = None,
    columns: str | None = _COLUMNS_Q,
    f: list[str] = _FIELD_FILTER_Q,
    _: Principal = Depends(requires("leads:read")),
) -> LeadListOut:
    _refuse_search_in_query(search)
    return await _leads_page(
        session,
        LeadSearchIn(
            limit=limit,
            offset=offset,
            status=status,
            agent_id=agent_id,
            assigned_to=assigned_to,
            columns=columns,
            f=f,
        ),
    )


@router.post(
    "/leads/search",
    response_model=LeadListOut,
    # `leads:read` on a POST, and it is the same exemption `POST /v1/dnc/check` holds:
    # this route WRITES NOTHING, it is a POST because the request carries a phone number.
    # `tests/authz_audit_test.READS_SHAPED_AS_POSTS` records it with that reason, which is
    # what keeps D-22's read-only "view as client" session able to run a search.
    openapi_extra=permission_meta("leads:read"),
    summary="The Leads table, searched — POST because the search term is a phone number",
)
async def search_leads(
    payload: LeadSearchIn,
    session: Session,
    _: Principal = Depends(requires("leads:read")),
) -> LeadListOut:
    return await _leads_page(session, payload)


async def _lead_facets(session: AsyncSession, lens: LeadLensIn) -> LeadFacetsOut:
    """The filter rail and its counts, over the SAME scope the Leads table is answering.

    A separate route rather than another field on the list response, for one reason: the
    counts change when the FILTERS change and not when the PAGE changes, so folding them
    into the list would recompute up to eight aggregates every time somebody scrolls. It
    takes the SAME `LeadLensIn` the table takes, minus the paging fields, so "the rail
    describes this table" is checkable by comparing two lens objects rather than two
    query strings.
    """
    fields = await service.lead_columns(session, lens.agent_id)
    available = lead_column_registry.available(fields)
    field_filters = _parse_field_filters(
        lens.f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )
    result = await service.lead_facets(
        session,
        fields=fields,
        agent_id=lens.agent_id,
        status=lens.status,
        search=lens.search,
        assigned_to=lens.assigned_to,
        field_filters=field_filters,
    )
    return LeadFacetsOut(
        facets=[
            LeadFacetOut(
                key=facet.key,
                label=facet.label,
                values=[
                    LeadFacetValueOut(value=v.value, count=v.count, declared=v.declared)
                    for v in facet.values
                ],
            )
            for facet in result.facets
        ],
        omitted_field_count=result.omitted_field_count,
    )


@router.get(
    "/leads/facets",
    response_model=LeadFacetsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Faceted filters, built from this agent's extraction schema",
)
async def get_lead_facets(
    session: Session,
    status: str | None = None,
    # DECLARED SO IT CAN BE REFUSED, exactly as on `GET /v1/leads`. When the table's
    # search moved into a body the rail was left behind, and the client's only safe move
    # was to send the rail NO search term at all — which quietly made the counts describe
    # a wider set than the rows beside them. Refusing here rather than ignoring is what
    # lets the client send the term to the POST instead of dropping it.
    search: str | None = Query(None, deprecated=True, description="Moved to POST /v1/leads/facets"),
    agent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    f: list[str] = _FIELD_FILTER_Q,
    _: Principal = Depends(requires("leads:read")),
) -> LeadFacetsOut:
    _refuse_search_in_query(search)
    return await _lead_facets(
        session,
        LeadLensIn(status=status, agent_id=agent_id, assigned_to=assigned_to, f=f),
    )


@router.post(
    "/leads/facets",
    response_model=LeadFacetsOut,
    # `leads:read` on a POST, for the same reason `POST /v1/leads/search` and
    # `POST /v1/dnc/check` hold it: this route WRITES NOTHING and is a POST only because
    # the request carries a phone number. Recorded in
    # `tests/authz_audit_test.READS_SHAPED_AS_POSTS` with that reason, which is what keeps
    # D-22's read-only "view as client" session able to open the rail.
    openapi_extra=permission_meta("leads:read"),
    summary="Faceted filters, searched — POST because the search term is a phone number",
)
async def search_lead_facets(
    payload: LeadLensIn,
    session: Session,
    _: Principal = Depends(requires("leads:read")),
) -> LeadFacetsOut:
    """The rail for a searched table.

    It takes `LeadLensIn` and not `LeadSearchIn`: the rail has no page, and accepting
    `limit`/`offset` here would be two fields a caller could set and nothing could honour.
    The client sends the same lens it sent the table, minus the page — so the rail and the
    rows cannot describe different populations, which is the defect this route closes.
    """
    return await _lead_facets(session, payload)


# --- saved views ---------------------------------------------------------------
#
# Declared BEFORE `/leads/{lead_id}`: FastAPI matches in declaration order, and a
# literal segment behind a path parameter is a route that never runs.
#
# The mutations require `leads:write` rather than a permission of their own. A saved view
# is one person's private UI state and needs no new RBAC entry — but it must not be
# writable by an operator inside a D-22 impersonation, and `leads:write` is in
# `MUTATING_PERMISSIONS`, so `requires()` refuses that case for free. Inventing
# `views:write` would have been a third permission on the Leads screen that every role
# holds exactly when it holds `leads:write`.


def _view_owner(principal: Principal) -> UUID:
    """WHOSE views these are. A view is private, so a session with no user is not a
    session that can have any — and an impersonating operator's `user_id` is an
    `admin_users` row, which owns none of a client's views and correctly reads empty."""
    if principal.user_id is None:
        raise ProblemError.forbidden("Saved views belong to a signed-in user of this account.")
    return principal.user_id


@router.get(
    "/leads/views",
    response_model=SavedViewListOut,
    openapi_extra=permission_meta("leads:read"),
    summary="My saved views on this account",
)
async def get_saved_views(
    session: Session, principal: Principal = Depends(requires("leads:read"))
) -> SavedViewListOut:
    return SavedViewListOut(
        items=await saved_views.list_views(session, user_id=_view_owner(principal))
    )


@router.post(
    "/leads/views",
    response_model=SavedViewOut,
    status_code=201,
    openapi_extra=permission_meta("leads:write"),
    summary="Save the current filters and columns under a name",
)
async def create_saved_view(
    payload: SavedViewIn,
    session: Session,
    principal: Principal = Depends(requires("leads:write")),
) -> SavedViewOut:
    return await saved_views.create_view(session, user_id=_view_owner(principal), payload=payload)


@router.patch(
    "/leads/views/{view_id}",
    response_model=SavedViewOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Rename a saved view, or re-pin its filters and columns",
)
async def patch_saved_view(
    view_id: UUID,
    payload: SavedViewUpdateIn,
    session: Session,
    principal: Principal = Depends(requires("leads:write")),
) -> SavedViewOut:
    return await saved_views.update_view(
        session, view_id, user_id=_view_owner(principal), payload=payload
    )


@router.delete(
    "/leads/views/{view_id}",
    status_code=204,
    response_class=Response,
    openapi_extra=permission_meta("leads:write"),
    summary="Delete one of my saved views",
)
async def delete_saved_view(
    view_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("leads:write")),
) -> Response:
    await saved_views.delete_view(session, view_id, user_id=_view_owner(principal))
    return Response(status_code=204)


async def _export_and_summary(
    session: AsyncSession, lens: LeadLensIn
) -> tuple[service.LeadExport, dict[str, Any]]:
    """The CSV, and WHAT WAS TAKEN as the audit row's summary.

    The summary is built here so the two request shapes can never describe the same
    export differently — "exported four hot leads" and "exported the entire account"
    were one audit row while `agent_id` was the only filter, and they are the two ends of
    an incident. Every member is an id, a key or a count; `search` is a BOOLEAN and never
    its text, because the search box accepts a phone suffix (hard rule 6).
    """
    available = lead_column_registry.available(await service.lead_columns(session, lens.agent_id))
    chosen = _parse_columns(lens.columns)
    field_filters = _parse_field_filters(
        lens.f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )
    export = await service.export_leads_csv(
        session,
        agent_id=lens.agent_id,
        status=lens.status,
        search=lens.search,
        assigned_to=lens.assigned_to,
        field_filters=field_filters,
        columns=chosen,
    )
    summary: dict[str, Any] = {
        "status": lens.status,
        "agent_id": str(lens.agent_id) if lens.agent_id else None,
        "searched": bool(lens.search),
        # An id, not a name — and recorded for the same reason `status` is: "exported my
        # own eight leads" and "exported the account" must not be the same audit row.
        "assigned_to": str(lens.assigned_to) if lens.assigned_to else None,
        # Counted by the query, not by counting newlines in the file: `QUOTE_ALL` keeps a
        # newline inside its cell, so a lead whose name or note contains one made this
        # number larger than the number of contacts that actually left.
        "rows": export.row_count,
        # WHICH COLUMNS left the building. "Exported the phone column for four hot leads"
        # and "exported everything we hold about them" are different events, and this is
        # the audit row an incident reads to answer "did the numbers go out?". Keys,
        # never values: a column KEY is schema vocabulary the admin authored.
        "columns": sorted(chosen) if chosen else "all",
        # FACET keys only, and never their values — a facet value is a client's own
        # captured data ("budget: 40L") and belongs in no log line.
        "field_filters": sorted(field_filters) or None,
    }
    return export, summary


@router.post(
    "/leads/export.csv",
    # `calls:read_raw`, NOT `leads:read`. This is the route that takes a client's WHOLE
    # contact list out of the building in one file, and the redaction guardrail exempts
    # it on the stated grounds that it is role-gated and audited. `leads:read` is held by
    # `staff` — so the "role gate" was every logged-in employee, and the exemption was
    # describing a control that did not exist. `calls:read_raw` is the permission that
    # already means "you may take the artefact, and your having taken it is recorded":
    # owner in the client realm, BOTH admin tiers in ours since the founder's correction
    # to D-457, never staff. D-436 unmasked the SCREENS; it did not move this gate,
    # because a bulk extract is a different act from reading the row in front of you —
    # and that distinction is now the whole of what stands between a support person and a
    # client's contact list, so the audit row below is load-bearing rather than tidy
    # (`tests/impersonation_audit_test.py` drives an operator through it and then reads
    # the ledger).
    #
    # **The POST shape exists for `search` and only for `search`.** That field is matched
    # against `phone_e164`, and a customer's number in a query string is written to
    # nginx's access log, the edge's log, browser history and the next request's
    # `Referer` (`_SEARCH_MOVED_TO_POST`). The GET below keeps every filter that is NOT
    # personal data and REFUSES `search`, so there is one place a phone number can be
    # sent and it is a body. It writes nothing;
    # `tests/authz_audit_test.READS_SHAPED_AS_POSTS` records that with the reason, which
    # is what keeps a read from being gated on a mutating permission (D-22).
    openapi_extra=permission_meta("calls:read_raw"),
    summary="CSV export — full phone numbers, owner-only and audit-logged",
    response_class=Response,
)
async def export_leads(
    payload: LeadLensIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("calls:read_raw")),
) -> Response:
    """The SAME filters `GET /v1/leads` takes, with the same meanings, so "export what I
    am looking at" is expressible. It accepted `agent_id` alone once, so a client who
    filtered the table to `hot` and pressed Export downloaded every contact in the account
    with full numbers — the widest possible read of the narrowest possible request.
    Widening the filters does NOT widen the gate: this stays `calls:read_raw` and stays
    audited, and a narrower request is not a cheaper permission.

    The COLUMN CHOOSER and the FACETS mean exactly what they mean on the list — see
    `_COLUMNS_Q` for why an unknown column is dropped and an unknown facet is refused.
    That mirroring is a correctness requirement here rather than a nicety: the screen and
    the file must not disagree about which rows and which columns, because the file is the
    one carrying the whole contact list out of the building in a single click.
    """
    export, summary = await _export_and_summary(session, payload)
    # An export leaves our redaction behind (SEC-COMP §4 says redaction runs BEFORE any
    # transcript leaves the system — a lead export is contact data, not transcript, and
    # is the client's own data — so it is audited rather than withheld). In the handler,
    # by the guardrail's requirement — see the GET twin below.
    await write_audit(
        session,
        action="leads.export",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead_export",
        ip=client_request_ip(request),
        summary=summary,
    )
    return Response(
        content=export.csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


@router.get(
    "/leads/export.csv",
    # The SAME route, the SAME gate, and the filters that are not personal data. See the
    # POST above for why `search` is not among them.
    openapi_extra=permission_meta("calls:read_raw"),
    summary="CSV export, unsearched — full phone numbers, owner-only and audit-logged",
    response_class=Response,
)
async def export_leads_filtered(
    session: Session,
    request: Request,
    principal: Annotated[Principal, Depends(requires("calls:read_raw"))],
    agent_id: UUID | None = None,
    status: str | None = None,
    # Declared so it can be REFUSED. FastAPI drops an undeclared query parameter
    # silently, and a silently-dropped `search` widens the export from eleven leads to
    # the client's whole contact list.
    search: str | None = Query(
        None, deprecated=True, description="Moved to POST /v1/leads/export.csv"
    ),
    assigned_to: UUID | None = None,
    columns: str | None = _COLUMNS_Q,
    f: list[str] = _FIELD_FILTER_Q,
) -> Response:
    _refuse_search_in_query(search)
    lens = LeadLensIn(
        status=status, agent_id=agent_id, assigned_to=assigned_to, columns=columns, f=f
    )
    export, summary = await _export_and_summary(session, lens)
    # WRITTEN HERE rather than inside `_export_and_summary`, and the duplication is
    # deliberate: `scripts/check_redaction_exposure` requires every route allowed to
    # return raw PII to name `write_audit` in its OWN body, so that a handler cannot
    # acquire the exemption by calling a helper that used to audit and no longer does.
    # What is shared is the expensive part and the summary's vocabulary; what is repeated
    # is the eight lines that make the exemption true.
    await write_audit(
        session,
        action="leads.export",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead_export",
        ip=client_request_ip(request),
        summary=summary,
    )
    return Response(
        content=export.csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


# --- bulk actions --------------------------------------------------------------
#
# Declared BEFORE `/leads/{lead_id}` like the saved views above: FastAPI matches in
# declaration order, and a literal segment behind a path parameter is a route that never
# runs. There is no `POST /leads/{lead_id}` today, so the order is defensive rather than
# load-bearing — which is exactly when it is cheapest to get right.


@router.post(
    "/leads/bulk",
    response_model=LeadBulkOut,
    openapi_extra=permission_meta("leads:write"),
    summary="One action over many leads — page-scoped or filter-scoped, and it says which",
)
async def bulk_leads(
    payload: LeadBulkIn,
    session: Session,
    request: Request,
    # The FILTER scope's rows, in the SAME query parameters and with the same meanings
    # as `GET /v1/leads` and `GET /v1/leads/export.csv` (`_COLUMNS_Q` above argues the
    # asymmetry between an unknown column and an unknown filter; only filters apply
    # here, so an unknown one is refused). `columns` is deliberately absent: a bulk
    # action changes rows, and which COLUMNS you were looking at cannot narrow it.
    status: str | None = None,
    # Refused here too: the term rides in the body (`LeadBulkIn.search`) for the reason
    # `_SEARCH_MOVED_TO_POST` states — a POST whose PII travels in the query string is
    # logged exactly as a GET's is.
    search: str | None = Query(None, deprecated=True, description="Moved into the request body"),
    agent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    f: list[str] = _FIELD_FILTER_Q,
    principal: Principal = Depends(requires("leads:write")),
) -> LeadBulkOut:
    """Move many leads at once, and report what happened to each of them.

    **`leads:write` and no new permission.** Both actions are the ones the row already
    offers inline, done to more rows at a time; a bulk-only permission would be a fourth
    RBAC entry every role holds exactly when it holds `leads:write`. `leads:write` is in
    `MUTATING_PERMISSIONS`, so a D-22 impersonating operator is refused this for free.

    **No `Idempotency-Key`, and that is a property rather than an omission.** The
    reliability triad asks for one where a repeat has a side effect that cannot be undone
    — a phone ringing twice (`POST /leads/{id}/call`), a campaign launched twice. Here a
    repeat is *the same request*: `status` and `assigned_to` are single-value fields, so
    the second run finds every lead already in the target state and answers
    `unchanged: N` with no timeline rows written (`db/transition.py`). The idempotency
    that matters is in the write, not in a key.

    **200, always, when the request itself was well-formed.** A lead the action could not
    move is a per-item outcome in `failures`, not an HTTP error — the same shape
    `POST /leads/{id}/call` uses for a compliance refusal, and the reason RFC-9457 stays
    reserved for "the request failed". The two cases that ARE request failures and are
    refused up front: a filter matching more than the cap (`lead_bulk_too_many` — never a
    silent truncation), and a set that moved out from under a confirmation
    (`lead_bulk_set_moved`).
    """
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session
    _refuse_search_in_query(search)

    # An unknown facet key is refused here exactly as it is on the list and the export.
    # The stakes are higher, not lower: a filter that silently did nothing would WIDEN
    # the set, and this route writes to every row in it.
    available = lead_column_registry.available(await service.lead_columns(session, agent_id))
    field_filters = _parse_field_filters(
        f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )

    targets = await service.resolve_bulk_targets(
        session,
        ids=list(payload.ids) if payload.scope == "ids" else None,
        status=status,
        search=payload.search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    total = len(targets.ids) + len(targets.missing)
    if payload.expected_count is not None and payload.expected_count != total:
        # The set the person confirmed is not the set in front of us. Refusing costs one
        # extra click; running anyway spends their confirmation on a different set of
        # rows, which is the failure the researched confirmation rule is about.
        raise ProblemError.conflict(
            "lead_bulk_set_moved",
            f"This now matches {total} leads rather than the {payload.expected_count} "
            "you confirmed, so nothing was changed.",
            remediation="Check the table and run the action again.",
        )

    outcome = await service.apply_bulk_leads(
        session,
        targets=targets,
        action=payload.action,
        status=payload.status,
        # `AssigneeChange` rather than a bare id for the reason the single-lead PATCH
        # gives: `None` inside it is "unassign", and the request model has already told
        # an absent `assign_to` apart from an explicit null.
        assignee=(
            service.AssigneeChange(user_id=payload.assign_to)
            if payload.action == "assign"
            else None
        ),
        actor=str(principal.user_id),
    )
    await write_audit(
        session,
        action=f"lead.bulk_{payload.action}",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead",
        ip=client_request_ip(request),
        # COUNTS and SCOPE, never the id list and never a facet VALUE — the same rule the
        # export's audit row follows, for the same reason: a facet value is a client's own
        # captured data and a lead id list of 500 is not a summary. "Moved four leads I
        # had ticked" and "moved every hot lead in the account" are the two ends of an
        # incident and this row tells them apart.
        summary={
            "scope": payload.scope,
            "requested": outcome.requested,
            "changed": outcome.changed,
            "unchanged": outcome.unchanged,
            "failed": len(outcome.failures),
            "status": payload.status,
            "searched": bool(search),
            "agent_id": str(agent_id) if agent_id else None,
            "field_filters": sorted(field_filters) or None,
        },
    )
    return LeadBulkOut(
        action=payload.action,
        scope=payload.scope,
        requested=outcome.requested,
        changed=outcome.changed,
        unchanged=outcome.unchanged,
        failures=[
            LeadBulkFailureOut(lead_id=fail.lead_id, rule=fail.rule, reason=fail.reason)
            for fail in outcome.failures
        ],
    )


@router.get("/leads/{lead_id}", response_model=LeadOut, openapi_extra=permission_meta("leads:read"))
async def get_lead(
    lead_id: UUID, session: Session, _: Principal = Depends(requires("leads:read"))
) -> LeadOut:
    return await service.get_lead(session, lead_id)


@router.patch(
    "/leads/{lead_id}",
    response_model=LeadOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Edit one lead — status, name, and who owns it",
)
async def patch_lead(
    lead_id: UUID,
    payload: LeadUpdateIn,
    session: Session,
    principal: Principal = Depends(requires("leads:write")),
) -> LeadOut:
    """Assignment rides on THIS route rather than on a `PUT /leads/{id}/assignee`.

    The choice was between one route that edits a lead and a second route that edits
    one of its fields, and "one way per problem" decides it: the status select and the
    assignee select sit in the same table row, need the same `leads:write`, and want
    the same cache invalidation — two endpoints would be two mutations, two hooks and
    two places for the next editable field to be added to the wrong one. `staff` holds
    `leads:write` deliberately (core/rbac.py): assignment is how a team divides work,
    not an owner-only setting.

    The one thing a shared PATCH costs is the null: `"assigned_to": null` must mean
    "unassign" while an ABSENT `assigned_to` means "leave the owner alone", and both
    arrive as `None` on the model. Pydantic v2's `model_fields_set` holds exactly the
    fields the request supplied, so it is what tells them apart
    (pydantic.dev/docs/validation/latest/concepts/models). `AssigneeChange` carries the
    answer onward as a value rather than as a second boolean parameter, so the service
    cannot read the two cases the same way by accident.
    """
    return await service.update_lead(
        session,
        lead_id,
        status=payload.status,
        name=payload.name,
        assignee=(
            service.AssigneeChange(user_id=payload.assigned_to)
            if "assigned_to" in payload.model_fields_set
            else None
        ),
        actor=str(principal.user_id),
    )


@router.get(
    "/leads/{lead_id}/timeline",
    response_model=LeadTimelineOut,
    # `leads:read`, and it has to be: D-22 refuses every MUTATING permission to a
    # read-only impersonating admin, so gating a lead's history on `leads:write` would
    # hide it from support at the exact moment support is looking
    # (`tests/impersonation_reads_test.py` asserts the rule over the whole route table).
    # Reading what happened to a lead is not the authority to change it.
    openapi_extra=permission_meta("leads:read"),
    summary="What happened to this lead, newest first — projected, never the raw payload",
)
async def lead_timeline(
    lead_id: UUID,
    session: Session,
    limit: int = Query(50, ge=1, le=service.MAX_TIMELINE_PAGE),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(requires("leads:read")),
) -> LeadTimelineOut:
    """The record existed and nobody could read it.

    `lead_events` is written by six producers across three deployables — the status
    change, the blocked dial, each call, each hot-lead alert, each WhatsApp attempt,
    each spent campaign ladder — and until now the only reader was the aggregate
    needs-attention query. "We called them twice, the WhatsApp was refused, the campaign
    gave up" was on record and invisible to the person it is about.

    Bounded rather than unbounded, and the bound is stated in the response: `limit` is
    validated HERE (1..100) rather than clamped in the service, for the reason
    `/v1/attention` gives — `min(limit, 100)` turns a negative limit into a silently
    short page instead of into a bad request.
    """
    return await service.lead_timeline(session, lead_id, limit=limit, offset=offset)


@router.post(
    "/leads/{lead_id}/call",
    response_model=CallLeadOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Dispatch one AI call to this lead (D-21) — compliance-gated, idempotent",
)
async def call_lead(
    lead_id: UUID,
    payload: CallLeadIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CallLeadOut:
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session

    # Idempotency: a double-click must not place two calls to a customer. The key is
    # required here precisely because the side effect is a real phone ringing.
    idem_key = request.headers.get("Idempotency-Key")
    claim = None
    if idem_key:
        # IN ITS OWN COMMITTED TRANSACTION, before anything can ring — see the assist
        # route above for the argument, which is the same one with a phone call in place
        # of a model call: a claim written into the request's transaction is erased by
        # the rollback that follows any later failure, and the retry the key exists to
        # answer rings the customer a second time.
        async with tenant_session(principal.tenant_id) as claim_session:
            claim = await claim_idempotency(
                claim_session,
                scope=scope_key(tenant_id=principal.tenant_id, user_id=principal.user_id),
                route="/v1/leads/{lead_id}/call",
                method="POST",
                key=idem_key,
                request_hash=body_hash({"lead_id": str(lead_id), **payload.model_dump()}),
            )
        if claim.state == "replay" and claim.response_payload:
            return CallLeadOut.model_validate(claim.response_payload)

    phone, name = await service.lead_phone(session, lead_id)

    # THE COMPLIANCE GATE. D-21 is explicit that client-initiated dispatch runs the
    # same pre-checks as webhook dispatch; a decision (not an exception) comes back so
    # the UI can explain WHY the button is refusing (SURFACES §2b).
    decision = await check_dispatch(
        session, tenant_id=principal.tenant_id, agent_id=payload.agent_id, phone_e164=phone
    )
    if not decision.allowed:
        result = CallLeadOut(
            status="blocked", blocked_reason=decision.reason, blocked_rule=decision.rule
        )
        if claim is not None:
            async with tenant_session(principal.tenant_id) as done_session:
                await complete_idempotency(
                    done_session,
                    record_id=claim.record_id,
                    response_status=200,
                    response_payload=result.model_dump(),
                )
        return result

    from apps.api.agents.service import DialUnconfirmedError, dispatch_call

    try:
        handle = await dispatch_call(
            session,
            tenant_id=principal.tenant_id,
            agent_id=payload.agent_id,
            lead_id=lead_id,
            phone_e164=phone,
            lead_name=name,
            context_note=payload.context_note,
        )
    except DialUnconfirmedError as unconfirmed:
        # THE CLAIM IS DELIBERATELY LEFT `processing`. Marking it failed would let the
        # very next press of the button re-dial somebody whose phone may be ringing right
        # now — the one outcome this route's idempotency exists to prevent — and the row
        # `dispatch_call` committed is already on the lead's call log, so the client can
        # see what we are telling them about.
        raise ProblemError(
            kind="dependency",
            code="dial_unconfirmed",
            title="We could not confirm whether the call was placed",
            detail=(
                "The voice platform did not answer us, and it may have started the call anyway."
            ),
            remediation=(
                "Check this lead's call log in a minute before trying again — calling "
                "again could ring them twice."
            ),
        ) from unconfirmed

    # THE AUDIT AND THE CLAIM'S COMPLETION IN THEIR OWN TRANSACTION, for the reason the
    # claim had one: the phone has rung, and the record of it must not be undone by a
    # failure later in this request.
    result = CallLeadOut(status="queued", call_handle=handle)
    async with tenant_session(principal.tenant_id) as record_session:
        await write_audit(
            record_session,
            action="lead.call_dispatched",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="lead",
            object_id=str(lead_id),
            ip=client_request_ip(request),
            summary={"agent_id": str(payload.agent_id), "has_note": bool(payload.context_note)},
        )
        if claim is not None:
            await complete_idempotency(
                record_session,
                record_id=claim.record_id,
                response_status=200,
                response_payload=result.model_dump(),
            )
    return result


@router.get(
    "/performance",
    response_model=PerformanceOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Connect rate, funnel, outcomes, busiest hours IST (teardown §5 floor)",
)
async def performance_panel(
    session: Session,
    # BOUNDED at both ends (D-302). `days` was an unbounded int that goes straight into
    # the window of four aggregate scans of `calls`, so `?days=100000` was a full-table
    # aggregate any `calls:read` holder could ask for, repeatedly, inside the ordinary
    # rate limit. A year is past every window this panel offers and is a cheap ceiling;
    # `ge=1` refuses the zero-width window that returned a panel of zeroes.
    days: int = Query(30, ge=1, le=365),
    _: Principal = Depends(requires("calls:read")),
) -> PerformanceOut:
    # `model_validate`, not a passthrough: the model is `extra="forbid"`, so a key the
    # service grows without the schema growing with it fails HERE, loudly, instead of
    # reaching a browser as a field no generated type knows about.
    return PerformanceOut.model_validate(await performance(session, days=days))


@router.get(
    "/attention",
    response_model=AttentionOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Everything that stopped, and what to do about it (SURFACES §2b)",
)
async def attention(
    session: Session,
    # Validated here rather than clamped in the service: an out-of-range limit is a bad
    # request, and `min(limit, 100)` turns a negative one into a silently short queue.
    limit: int = Query(50, ge=1, le=100),
    _: Principal = Depends(requires("leads:read")),
) -> AttentionOut:
    """`leads:read`, not an owner permission: staff work this queue — it is the daily
    operational surface, and gating it on billing-grade permissions would put the work
    on the one person least likely to be doing it."""
    return AttentionOut.model_validate(await attention_queue(session, limit=min(limit, 100)))


@router.get(
    "/usage",
    response_model=UsagePanelOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This month's usage and what it costs (SURFACES §2b)",
)
async def usage_panel(
    session: Session,
    month: str | None = None,
    principal: Principal = Depends(requires("billing:read")),
) -> UsagePanelOut:
    """`billing:read`, which staff do not have (SEC-COMP §5) — spend is an owner's
    business. Our supplier cost never appears here; that is the admin margin panel."""
    assert principal.tenant_id is not None
    summary = await billing.usage_summary(session, tenant_id=principal.tenant_id, month=month)
    balance = await billing.get_balance(session, tenant_id=principal.tenant_id)
    tier = await billing.plan_tier_of(session, principal.tenant_id)
    return UsagePanelOut.model_validate(
        {
            # Decimal → string, never float (hard rule 7). The model declares each of
            # these `str` for the same reason.
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in summary.items()},
            "plan_tier": tier,
            # Credits only mean something for the self-serve motion (D-34); showing a
            # managed client a ₹0 wallet would invite a support ticket about a concept
            # that does not apply to them.
            #
            # **`to_paise`, like every other money field on this panel (D-375).** This was
            # the ONE field that published `credit_ledger.balance_after` at its
            # NUMERIC(12,4) storage precision, and the inconsistency was not cosmetic on
            # either side of the wire. `billing.service.to_paise` is documented as "the
            # ONE place a rupee amount is rounded ... so no two surfaces can round the
            # same number differently", and every credit route already goes through it —
            # while `formatINR`, which draws this figure, TRUNCATES the fraction to two
            # digits rather than rounding it. So one wallet read on two screens: at a
            # balance of ₹489.7050 the admin console said ₹489.71 and the client's own
            # panel said ₹489.70. Four-decimal balances are ordinary, not exotic — a
            # prepaid debit is `prepaid_billed_inr`, quantized at `MONEY_Q`, and any
            # `self_serve_inr_per_min` that is not a divisor of 60 produces one on the
            # first call. The LEDGER keeps its full precision; only the wire is quantized.
            #
            # `PREPAID_TIERS` rather than the literal pair, because that tuple is the one
            # place the motion is named and a third prepaid tier added to it must not
            # silently stop showing a wallet here.
            "credit_balance_inr": (
                str(billing.to_paise(balance.amount_inr)) if tier in PREPAID_TIERS else None
            ),
        }
    )


@router.get(
    "/calls/{call_id}/callback",
    response_model=CallbackEligibilityOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Whether this call may be followed up, and why not (D-21)",
)
async def callback_eligibility(
    call_id: UUID,
    session: Session,
    # `leads:read`, not `leads:dispatch`: this endpoint exists so a button can
    # render disabled WITH A REASON, and `leads:dispatch` is mutating, so D-22 hid
    # the reason from anyone viewing a client read-only. The POST that actually
    # places the call keeps `leads:dispatch` — reading why you cannot dial is not
    # the authority to dial.
    principal: Principal = Depends(requires("leads:read")),
) -> CallbackEligibilityOut:
    """A GET so the button renders disabled-with-a-reason on page load.

    Both the eligibility rules AND the compliance gate are evaluated, because a call
    that is eligible on our rules can still be un-dialable right now (outside calling
    hours, DNC, spend cap) — and "the button is greyed out and I do not know why" is
    the exact failure SURFACES §2b exists to prevent.
    """
    assert principal.tenant_id is not None
    try:
        plan = await service.plan_callback(session, call_id)
    except ProblemError as problem:
        if problem.kind != "business_rule":
            raise
        return CallbackEligibilityOut(eligible=False, reason=problem.detail, rule=problem.code)

    decision = await check_dispatch(
        session,
        tenant_id=principal.tenant_id,
        agent_id=plan.agent_id,
        phone_e164=plan.phone_e164,
    )
    if not decision.allowed:
        return CallbackEligibilityOut(eligible=False, reason=decision.reason, rule=decision.rule)
    return CallbackEligibilityOut(eligible=True, follow_up_number=plan.depth + 1)


@router.post(
    "/calls/{call_id}/callback",
    response_model=CallbackOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="AI callback with prior-call context (D-21) — same gate, bounded chain",
)
async def call_back(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CallbackOut:
    """Re-dispatch the same agent to the same lead, carrying what happened last time.

    Idempotency keys off the CALL, not a client-supplied header: the natural key for
    "follow up this call" is the call itself, and a double-click must not ring a
    customer twice even from two browser tabs.
    """
    assert principal.tenant_id is not None
    plan = await service.plan_callback(session, call_id)

    # Committed before anything dials, in its own transaction — `call_lead`'s argument,
    # and this route has the sharper version of it: the key is derived from the call, so
    # a claim lost to a rollback is re-taken by the very next press.
    async with tenant_session(principal.tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=principal.tenant_id, user_id=principal.user_id),
            route="/v1/calls/{call_id}/callback",
            method="POST",
            key=str(call_id),
            request_hash=body_hash({"call_id": str(call_id)}),
        )
    if claim.state == "replay" and claim.response_payload:
        return CallbackOut.model_validate(claim.response_payload)

    decision = await check_dispatch(
        session,
        tenant_id=principal.tenant_id,
        agent_id=plan.agent_id,
        phone_e164=plan.phone_e164,
    )
    if not decision.allowed:
        result = CallbackOut(
            status="blocked", blocked_reason=decision.reason, blocked_rule=decision.rule
        )
        async with tenant_session(principal.tenant_id) as done_session:
            await complete_idempotency(
                done_session,
                record_id=claim.record_id,
                response_status=200,
                response_payload=result.model_dump(),
            )
        return result

    from apps.api.agents.service import DialUnconfirmedError, dispatch_call

    try:
        handle = await dispatch_call(
            session,
            tenant_id=principal.tenant_id,
            agent_id=plan.agent_id,
            lead_id=plan.lead_id,
            phone_e164=plan.phone_e164,
            lead_name=plan.lead_name,
            context_note=plan.context_note,
        )
    except DialUnconfirmedError as unconfirmed:
        # The claim stays `processing` on purpose — `call_lead` carries the argument.
        raise ProblemError(
            kind="dependency",
            code="dial_unconfirmed",
            title="We could not confirm whether the callback was placed",
            detail=(
                "The voice platform did not answer us, and it may have started the call anyway."
            ),
            remediation=(
                "Check this call's follow-ups in a minute before trying again — calling "
                "again could ring them twice."
            ),
        ) from unconfirmed
    # The chain link stays on the REQUEST's session: it is a pointer between two of our
    # own rows and its loss costs a follow-up count, not a record of a call.
    await service.link_callback(session, handle=handle, parent_call_id=call_id)
    result = CallbackOut(status="queued", call_handle=handle, follow_up_number=plan.depth + 1)
    async with tenant_session(principal.tenant_id) as record_session:
        await write_audit(
            record_session,
            action="call.callback_dispatched",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="call",
            object_id=str(call_id),
            ip=client_request_ip(request),
            summary={"follow_up_number": plan.depth + 1},
        )
        await complete_idempotency(
            record_session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(),
        )
    return result


__all__ = ["router"]
