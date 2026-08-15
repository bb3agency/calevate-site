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
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import service as billing
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm import columns as lead_column_registry
from apps.api.crm import saved_views, service
from apps.api.crm.attention import attention_queue
from apps.api.crm.performance import performance
from apps.api.crm.schemas import (
    AttentionOut,
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
    LeadListOut,
    LeadOut,
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
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    scope_key,
)

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
        ip=request.client.host if request.client else None,
    )
    return await service.get_call(session, call_id, raw=True)


@router.get(
    "/calls/{call_id}/recording",
    response_model=RecordingLinkOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Short-lived presigned link to OUR copy of the recording",
)
async def get_recording(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("calls:read")),
) -> RecordingLinkOut:
    key = await service.recording_key_for(session, call_id)
    await write_audit(
        session,
        action="recording.read",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=request.client.host if request.client else None,
    )
    # Imported here, not at module scope: the presigner lives in the workers package
    # and pulling boto3 into every API import would slow cold starts for one route.
    from apps.workers.storage import PRESIGN_TTL_S, presigned_url

    url = presigned_url(key)
    if url is None:
        raise ProblemError(
            kind="dependency",
            code="recording_unavailable",
            title="Recording unavailable",
            detail="The recording could not be retrieved right now.",
        )
    return RecordingLinkOut(url=url, expires_in_s=PRESIGN_TTL_S)


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


@router.get("/leads", response_model=LeadListOut, openapi_extra=permission_meta("leads:read"))
async def get_leads(
    session: Session,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    search: str | None = Query(None, max_length=60),
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
    # `agent_id` filters the ROWS as well as choosing the columns. It used to do only
    # the latter, which meant this route and the export disagreed about what the same
    # query parameter meant, and a two-agent tenant read one agent's leads under the
    # other's capture list. See `service._lead_scope` for the reasoning.
    fields = await service.lead_columns(session, agent_id)
    available = lead_column_registry.available(fields)
    resolved = lead_column_registry.resolve(available, _parse_columns(columns))
    field_filters = _parse_field_filters(
        f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )
    page = await service.list_leads_page(
        session,
        limit=limit,
        offset=offset,
        status=status,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    return LeadListOut(
        items=page.items,
        # Columns travel with the rows so the frontend never hard-codes a client's
        # fields (TRD §7 (c)) — and they are the RESOLVED list, identical to the header
        # the export writes for the same query string.
        columns=[_column_out(c) for c in resolved.columns],
        available_columns=[_column_out(c) for c in available],
        dropped_column_keys=list(resolved.dropped),
        total=page.total,
        limit=limit,
        offset=offset,
        status_counts_matching_search=page.status_counts,
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
    search: str | None = Query(None, max_length=60),
    agent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    f: list[str] = _FIELD_FILTER_Q,
    _: Principal = Depends(requires("leads:read")),
) -> LeadFacetsOut:
    """The filter rail and its counts, over the SAME scope `GET /v1/leads` is answering.

    A separate route rather than another field on the list response, for one reason: the
    counts change when the FILTERS change and not when the PAGE changes, so folding them
    into the list would recompute up to eight aggregates every time somebody scrolls.
    Same query parameters, minus the paging ones, so "the rail describes this table" is
    checkable by comparing two query strings.
    """
    fields = await service.lead_columns(session, agent_id)
    available = lead_column_registry.available(fields)
    field_filters = _parse_field_filters(
        f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )
    result = await service.lead_facets(
        session,
        fields=fields,
        agent_id=agent_id,
        status=status,
        search=search,
        assigned_to=assigned_to,
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


@router.get(
    "/leads/export.csv",
    # `calls:read_raw`, NOT `leads:read`. This is the one route where a client's contact
    # list leaves us with FULL phone numbers, and the redaction guardrail exempts it on
    # the stated grounds that it is role-gated and audited. `leads:read` is held by
    # `staff` — so the "role gate" was every logged-in employee, and the exemption was
    # describing a control that did not exist. `calls:read_raw` is the permission that
    # already means "you may see the unmasked artefact, and your having seen it is
    # recorded": owner in the client realm, superadmin in ours, never staff.
    openapi_extra=permission_meta("calls:read_raw"),
    summary="CSV export — full phone numbers, owner-only and audit-logged",
    response_class=Response,
)
async def export_leads(
    session: Session,
    request: Request,
    agent_id: UUID | None = None,
    # The SAME three filters `GET /v1/leads` takes, with the same meanings, so "export
    # what I am looking at" is expressible. It accepted `agent_id` alone, so a client
    # who filtered the table to `hot` and pressed Export downloaded every contact in the
    # account with full numbers — the widest possible read of the narrowest possible
    # request. Widening the filters does NOT widen the gate: this stays `calls:read_raw`
    # and stays audited, and a narrower request is not a cheaper permission.
    status: str | None = None,
    search: str | None = Query(None, max_length=60),
    # The fourth, added in the same change that added it to the list rather than a
    # release later — that gap is exactly how the status/search divergence above
    # happened, and it is the one route where the gap ships full phone numbers.
    assigned_to: UUID | None = None,
    # The COLUMN CHOOSER and the FACETS, taken here with exactly the meanings
    # `GET /v1/leads` gives them — see `_COLUMNS_Q` above for why an unknown column is
    # dropped and an unknown facet is refused. This is the mirroring SURFACES §2 asks
    # for, and on this route it is a correctness requirement rather than a nicety: the
    # screen and the file must not disagree about which rows and which columns, because
    # the file is the one carrying unmasked numbers out of the building.
    columns: str | None = _COLUMNS_Q,
    f: list[str] = _FIELD_FILTER_Q,
    principal: Principal = Depends(requires("calls:read_raw")),
) -> Response:
    available = lead_column_registry.available(await service.lead_columns(session, agent_id))
    chosen = _parse_columns(columns)
    field_filters = _parse_field_filters(
        f, frozenset(c.key for c in lead_column_registry.facetable(available))
    )
    export = await service.export_leads_csv(
        session,
        agent_id=agent_id,
        status=status,
        search=search,
        assigned_to=assigned_to,
        field_filters=field_filters,
        columns=chosen,
    )
    # An export leaves our redaction behind (SEC-COMP §4 says redaction runs BEFORE any
    # transcript leaves the system — a lead export is contact data, not transcript, and
    # is the client's own data — so it is audited rather than masked).
    await write_audit(
        session,
        action="leads.export",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead_export",
        ip=request.client.host if request.client else None,
        # WHAT was taken, now that it can vary. "Exported four hot leads" and "exported
        # the entire account" were the same audit row while `agent_id` was the only
        # filter; they are the two ends of an incident and the record should tell them
        # apart. `search` is recorded as a BOOLEAN and never as text — hard rule 6, and
        # the search box accepts a phone suffix.
        summary={
            "status": status,
            "agent_id": str(agent_id) if agent_id else None,
            "searched": bool(search),
            # An id, not a name (hard rule 6 logs ids) — and recorded for the same
            # reason `status` is: "exported my own eight leads" and "exported the
            # account" must not be the same audit row.
            "assigned_to": str(assigned_to) if assigned_to else None,
            # Counted by the query, not by counting newlines in the file: `QUOTE_ALL`
            # keeps a newline inside its cell, so a lead whose name or note contains one
            # made this number larger than the number of contacts that actually left.
            "rows": export.row_count,
            # WHICH COLUMNS left the building, now that it varies. "Exported the phone
            # column for four hot leads" and "exported everything we hold about them"
            # are different events and the record should tell them apart — and this is
            # the audit row an incident reads to answer "did the numbers go out?".
            # Keys, never values (hard rule 6): a column KEY is schema vocabulary the
            # admin authored, not a caller's data.
            "columns": sorted(chosen) if chosen else "all",
            # FACET keys only, and never their values — a facet value is a client's own
            # captured data ("budget: 40L") and belongs in no log line.
            "field_filters": sorted(field_filters) or None,
        },
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
    search: str | None = Query(None, max_length=60),
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
        search=search,
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
        ip=request.client.host if request.client else None,
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
        claim = await claim_idempotency(
            session,
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
            await complete_idempotency(
                session,
                record_id=claim.record_id,
                response_status=200,
                response_payload=result.model_dump(),
            )
        return result

    from apps.api.agents.service import dispatch_call

    handle = await dispatch_call(
        session,
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        lead_id=lead_id,
        phone_e164=phone,
        lead_name=name,
        context_note=payload.context_note,
    )
    await write_audit(
        session,
        action="lead.call_dispatched",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="lead",
        object_id=str(lead_id),
        ip=request.client.host if request.client else None,
        summary={"agent_id": str(payload.agent_id), "has_note": bool(payload.context_note)},
    )
    result = CallLeadOut(status="queued", call_handle=handle)
    if claim is not None:
        await complete_idempotency(
            session,
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
    days: int = 30,
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
            "credit_balance_inr": (
                str(balance.amount_inr) if tier in ("self_serve", "trial") else None
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

    claim = await claim_idempotency(
        session,
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
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(),
        )
        return result

    from apps.api.agents.service import dispatch_call

    handle = await dispatch_call(
        session,
        tenant_id=principal.tenant_id,
        agent_id=plan.agent_id,
        lead_id=plan.lead_id,
        phone_e164=plan.phone_e164,
        lead_name=plan.lead_name,
        context_note=plan.context_note,
    )
    await service.link_callback(session, handle=handle, parent_call_id=call_id)
    await write_audit(
        session,
        action="call.callback_dispatched",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=request.client.host if request.client else None,
        summary={"follow_up_number": plan.depth + 1},
    )
    result = CallbackOut(status="queued", call_handle=handle, follow_up_number=plan.depth + 1)
    await complete_idempotency(
        session,
        record_id=claim.record_id,
        response_status=200,
        response_payload=result.model_dump(),
    )
    return result


__all__ = ["router"]
