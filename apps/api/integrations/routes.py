"""Integration endpoints — the client's own outbound config (D-23, SURFACES §2b).

`org:manage` on the writes: pointing our events at a URL or a spreadsheet is an
account-level decision, not a lead-handling one, and staff explicitly do not get org
settings (SEC-COMP §5). The reads take `org:read`, because D-22 refuses every mutating
permission to read-only impersonation and a support person must be able to see the
screen the client is looking at.

The signing secret is returned EXACTLY ONCE, at creation. After that the API answers
with a fingerprint and never the value — a config screen that re-displays a shared
secret turns every screenshot and every support session into a key disclosure.

**Both D-23 kinds are configurable here, and one of them is gated.** See
`create_sheets_endpoint` for the argument; the short version is that a checkbox for a
transport that cannot deliver is the defect the sheets work exists to remove, so the
route refuses rather than offering it where Google Sheets delivery does not exist.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.integrations import service
from apps.api.integrations.service import EVENT_TYPES

# The API asking the delivery path whether it can deliver. Imported rather than
# re-derived from settings so there is ONE answer: a config surface that decided for
# itself would eventually disagree with the worker, and the disagreement reads as
# "the screen says configured and the spreadsheet stays empty".
from apps.workers.sheets_sync import sheets_delivery_available

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

Session = Annotated[AsyncSession, Depends(db)]

EventName = Literal["lead.created", "lead.updated", "call.completed", "campaign.completed"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateEndpointIn(Strict):
    # HttpUrl rejects a bare hostname and anything that is not http(s) — we sign and
    # POST to whatever lands here, so "looks like a URL" is not good enough.
    url: HttpUrl
    events: list[EventName] = Field(min_length=1)


class CreateEndpointOut(Strict):
    id: UUID
    url: str
    events: list[str]
    # Shown once, never again.
    secret: str


class CreateSheetEndpointIn(Strict):
    # NOT `HttpUrl`: a bare document id is a legitimate answer here, and "looks like a
    # URL" is not the check that matters — `service.parse_spreadsheet_ref` is, and it
    # is the same parser the delivery worker runs against the stored value.
    #
    # There is deliberately NO credential field. `secret_ref` holds an `sm://` pointer
    # into OUR secrets manager, so accepting one from a request body would be a tenancy
    # hole wearing a config field's clothes — a client could name another tenant's path.
    # Attaching one is an operator action, and until it happens the endpoint reports
    # `credential_attached: false` rather than looking finished.
    spreadsheet: str = Field(min_length=1, max_length=512)
    events: list[EventName] = Field(min_length=1)
    worksheet: str | None = Field(default=None, min_length=1, max_length=100)


class SheetEndpointOut(Strict):
    id: UUID
    kind: str
    # The document id we resolved, echoed so the client can confirm we read the right
    # sheet out of whatever they pasted.
    spreadsheet_id: str
    worksheet: str
    events: list[str]
    active: bool
    # Whether a secrets-manager REFERENCE is attached — never the reference. False on
    # everything this route creates today, and computed from what was written to
    # `secret_ref` rather than hardcoded, so the day the route can attach one the
    # answer changes with the row instead of with someone remembering to edit this.
    credential_attached: bool


class EndpointOut(Strict):
    id: UUID
    # D-23's `outbound_webhooks.kind`: `webhook` or `google_sheets`. This list used to
    # filter to webhooks, which meant a provisioned sheets endpoint fanned out, failed
    # and alerted while the screen the client opens to understand their integrations
    # showed nothing at all — they could not see the thing producing the failures, let
    # alone deactivate it.
    kind: str
    url: str | None
    events: list[str]
    active: bool
    # For a webhook: which signing secret this is. For a sheet: `secret_ref` holds a
    # secrets-manager REFERENCE rather than a signing secret, so the fingerprint
    # answers exactly one question — is a credential attached yet — and the reference
    # itself never leaves the database.
    secret_fingerprint: str | None
    created_at: datetime


class DeliveryOut(Strict):
    id: UUID
    event_type: str | None
    status: str | None
    attempts: int
    first_at: datetime
    last_at: datetime


@router.get(
    "/events",
    openapi_extra=permission_meta("org:read"),
    summary="The events an endpoint may subscribe to",
)
async def list_event_types(_: Principal = Depends(requires("org:read"))) -> dict[str, list[str]]:
    return {"events": list(EVENT_TYPES)}


@router.get(
    "/endpoints",
    response_model=list[EndpointOut],
    openapi_extra=permission_meta("org:read"),
)
async def list_endpoints(
    session: Session,
    # A READ permission on a read. `org:manage` is in MUTATING_PERMISSIONS, which
    # D-22 refuses while impersonating — so gating this view on it made a client's
    # own integration config invisible to the support person looking at their
    # screen, for no security gain: nothing here is written, and secrets are shown
    # as fingerprints only.
    _: Principal = Depends(requires("org:read")),
) -> list[EndpointOut]:
    # Every kind, not just `webhook`. The old filter made a `google_sheets` row — the
    # only way to have one until `create_sheets_endpoint` below existed was for an
    # operator to write it — invisible to the tenant it belonged to, while it fanned
    # out and produced failed deliveries on the screen next door. RLS is the tenant
    # scoping here; the WHERE clause was never doing that job.
    rows = (
        await session.execute(
            text(
                "SELECT id, url, events, active, secret_ref, created_at, kind "
                "FROM outbound_webhooks ORDER BY created_at DESC"
            )
        )
    ).all()
    return [
        EndpointOut(
            id=r[0],
            kind=str(r[6]),
            url=r[1],
            events=list(r[2] or []),
            active=bool(r[3]),
            secret_fingerprint=service.secret_fingerprint(r[4]) if r[4] else None,
            created_at=r[5],
        )
        for r in rows
    ]


@router.post(
    "/endpoints",
    response_model=CreateEndpointOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Register a webhook endpoint — the signing secret is shown once",
)
async def create_endpoint(
    payload: CreateEndpointIn,
    session: Session,
    principal: Principal = Depends(requires("org:manage")),
) -> CreateEndpointOut:
    assert principal.tenant_id is not None
    endpoint_id = uuid7()
    secret = secrets.token_urlsafe(32)
    await session.execute(
        text(
            "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
            "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
            ":events, true, now(), now())"
        ),
        {
            "id": endpoint_id,
            "tid": principal.tenant_id,
            "url": str(payload.url),
            "secret": secret,
            "events": list(payload.events),
        },
    )
    return CreateEndpointOut(
        id=endpoint_id, url=str(payload.url), events=list(payload.events), secret=secret
    )


@router.post(
    "/endpoints/sheets",
    response_model=SheetEndpointOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Register a Google Sheets endpoint — refused where Sheets delivery does not exist",
    # Stated rather than inherited from the docstring below. FastAPI publishes a
    # handler's docstring as the operation `description`, and `/docs` is in
    # PUBLIC_PREFIXES — so the argument for this route's shape, which necessarily names
    # config keys, column names and internal call sites, would be served to anyone who
    # asks. What a client needs is the contract; the reasoning stays in the code.
    description=(
        "Deliver events to a Google Sheet. Accepts the sheet's URL or document id and "
        "the events to subscribe to. Refused with `sheets_delivery_unavailable` on "
        "accounts where Google Sheets delivery is not enabled, so an endpoint is never "
        "created that cannot receive rows. The Google credential is attached by "
        "Calevate, never sent here: until it is, `credential_attached` is false and "
        "attempts appear as failures on your delivery screen."
    ),
)
async def create_sheets_endpoint(
    payload: CreateSheetEndpointIn,
    session: Session,
    principal: Principal = Depends(requires("org:manage")),
) -> SheetEndpointOut:
    """Configure the OTHER D-23 kind. Ships behind a gate, and the gate is the argument.

    **Why this route did not exist, and why it does now.** The wave that built the
    sheets delivery path deliberately shipped no way to create one, on the grounds that
    offering the checkbox before a credential path exists recreates the exact "silently
    never delivers" defect the work was fixing. That was right, and it turned on
    something the codebase could not then say: transport selection keyed off
    `app_env == "local"`, and "are we on a laptop" is not a statement about Google
    Sheets. There was nothing to gate on, so the only safe gate was the absence of the
    route — a decision recorded in a docstring, which no deployment can read.

    `GOOGLE_SHEETS_PROVIDER` is that missing statement, so the refusal becomes
    executable. Where the deployment has no Sheets transport, this route refuses in
    problem+json and writes nothing; where it has one, the endpoint it creates is on
    exactly the same footing as a webhook — same fan-out, same delivery id, same
    forensic row, same retry ladder, same delivery screen. The checkbox is offered only
    where it is true.

    **What is still missing is stated, not hidden.** A client cannot supply the Google
    credential: `secret_ref` is an `sm://` pointer into our secrets manager, and
    accepting one from a request body would let a client name another tenant's path.
    So every endpoint this route creates comes back `credential_attached: false`, and
    until an operator attaches one `append_event` refuses each delivery with
    `no_credential_ref` — recorded `failed` on the client's own delivery screen and
    alerted, which is loud on purpose. Noisy beats silent: the alternative is a
    spreadsheet that simply stays empty.

    **Created ACTIVE, deliberately.** There is no route to activate an endpoint (only
    `DELETE`, which deactivates), so an endpoint created inactive would be a dead row
    with no way forward — a checkbox that lies in the other direction. Active means the
    first lead either lands in the sheet or produces a visible refusal, and both of
    those are answers.

    Two refusals happen here rather than at delivery time, because the client can still
    fix them at this point: a `spreadsheet` we cannot resolve to a document id (we
    refuse to guess which document to append a client's leads into), and an event whose
    column ORDER we do not know — `sheet_columns` refuses to infer one from a single
    row's keys, so a subscription we could never write is refused once here instead of
    once per lead forever.
    """
    assert principal.tenant_id is not None
    if not sheets_delivery_available():
        raise ProblemError(
            kind="business_rule",
            code="sheets_delivery_unavailable",
            title="Google Sheets delivery is not available",
            detail="This account cannot deliver leads to Google Sheets yet.",
            remediation=(
                "Register a webhook endpoint instead, or contact support to have "
                "Google Sheets enabled for your account."
            ),
        )

    # The same parser the delivery worker runs against the stored value, so a sheet
    # that configures cannot be a sheet that fails to resolve two minutes later.
    spreadsheet_id = service.parse_spreadsheet_ref(payload.spreadsheet)
    if spreadsheet_id is None:
        raise ProblemError(
            kind="validation",
            code="invalid_spreadsheet_ref",
            title="Not a Google Sheets document",
            detail="That is not a Google Sheets link or document id.",
            remediation="Paste the URL from your browser's address bar while the sheet is open.",
            fields=[{"field": "spreadsheet", "rule": "spreadsheet_ref", "message": "Unrecognised"}],
        )

    # Only a worksheet we would actually use gets stored. A whitespace-only tab name is
    # the same as not naming one, and writing it down would leave a config row whose
    # `mapping` disagrees with the tab the worker appends to.
    mapping: dict[str, Any] = {}
    worksheet = (payload.worksheet or "").strip()
    if worksheet:
        mapping["worksheet"] = worksheet

    unwritable = [event for event in payload.events if not service.sheet_columns(event, mapping)]
    if unwritable:
        raise ProblemError(
            kind="business_rule",
            code="sheet_column_order_unknown",
            title="That event cannot be written to a sheet",
            detail=(
                "These events have no defined column layout yet, so they cannot be "
                f"written to a spreadsheet: {', '.join(unwritable)}."
            ),
            remediation="Remove them from the subscription, or send them to a webhook instead.",
            fields=[
                {"field": "events", "rule": "column_order", "message": event}
                for event in unwritable
            ],
        )

    endpoint_id = uuid7()
    # No credential, and no way for this route to supply one — see the docstring. The
    # NULL is the honest state and it is what `credential_attached` reports.
    credential_ref: str | None = None
    await session.execute(
        text(
            "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
            "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'google_sheets', "
            ":url, :secret, :events, CAST(:mapping AS jsonb), true, now(), now())"
        ),
        {
            "id": endpoint_id,
            # Written from the principal, but the INSERT runs under the session's RLS
            # context — a tenant the session does not hold is refused by the policy,
            # not by this line (hard rule 1).
            "tid": principal.tenant_id,
            # The canonical id, not the pasted URL: a stored `#gid=0` fragment would
            # read as a tab selection, and the tab is `mapping.worksheet`.
            "url": spreadsheet_id,
            "secret": credential_ref,
            "events": list(payload.events),
            "mapping": json.dumps(mapping) if mapping else None,
        },
    )
    return SheetEndpointOut(
        id=endpoint_id,
        kind=service.SHEET_KIND,
        spreadsheet_id=spreadsheet_id,
        # Reported through the worker's own resolver, so "Leads" is never a default
        # this file happens to agree with.
        worksheet=service.sheet_worksheet(mapping),
        events=list(payload.events),
        active=True,
        credential_attached=credential_ref is not None,
    )


@router.delete(
    "/endpoints/{endpoint_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Deactivate — kept, not deleted, so the delivery history stays readable",
    # Stated rather than inherited from the docstring, for the reason
    # `create_sheets_endpoint` gives: `/docs` is public, and the reasoning below names
    # internal call sites. What a client needs is the CONTRACT, and the contract here
    # has a part they can only learn from us — that a repeat is a success.
    description=(
        "Deactivate an endpoint. The endpoint and its delivery history are kept, so "
        "past attempts stay readable. Idempotent: deactivating an endpoint that is "
        "already inactive returns 204, so retrying after a lost response is safe. 404 "
        "means only that no endpoint of yours has that id."
    ),
)
async def deactivate_endpoint(
    endpoint_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> None:
    """Deactivate the endpoint; the row and its delivery history stay.

    Idempotent: disabling an already-disabled endpoint is 204, not 404 — the second
    click, and the retry of a request whose response was lost, are the same request as
    the first (RFC 9110 §9.2.2). A genuinely absent id — including another tenant's,
    which RLS makes indistinguishable on purpose — is still 404. `service.
    deactivate_endpoint` carries the argument and the CAS; this route only decides what
    to write down.

    The audit row follows the inbound twin: written ONLY for a real transition, so the
    ledger records changes rather than button presses. An audit trail that logs actions
    nobody took is worse than one that logs fewer (`tenancy.members.set_role` makes the
    same call for the same reason).
    """
    assert principal.tenant_id is not None
    if await service.deactivate_endpoint(session, endpoint_id=endpoint_id):
        await write_audit(
            session,
            action="integration_endpoint.disabled",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="outbound_webhook",
            object_id=str(endpoint_id),
            ip=request.client.host if request.client else None,
        )


@router.get(
    "/deliveries",
    response_model=list[DeliveryOut],
    openapi_extra=permission_meta("org:read"),
    summary="Recent delivery attempts — 'did it reach my CRM?' answered without support",
)
async def list_deliveries(
    session: Session,
    # Range-checked at the boundary: `min(limit, 200)` passed a negative value straight
    # into the SQL LIMIT, where Postgres refuses it and the client sees a 500.
    limit: int = Query(50, ge=1, le=200),
    # Read permission on a read — see `list_endpoints`. This one matters most:
    # "did it reach my CRM?" is the question support is asked, and it was the one
    # view support could not open.
    _: Principal = Depends(requires("org:read")),
) -> list[DeliveryOut]:
    # `webhook_deliveries` is not tenant-RLS'd (engine webhooks arrive before tenant
    # resolution — see its model docstring), so this query is scoped by the tenant's
    # OWN endpoint ids rather than by RLS. That is the whole reason it is a subquery
    # against `outbound_webhooks`, which IS tenant-scoped, instead of a plain select.
    rows = (
        await session.execute(
            text(
                "SELECT d.id, d.event_type, d.status, d.attempts, d.first_at, d.last_at "
                "FROM webhook_deliveries d WHERE d.direction = 'out' "
                "AND d.endpoint_id IN (SELECT id FROM outbound_webhooks) "
                "ORDER BY d.last_at DESC LIMIT :limit"
            ),
            {"limit": min(limit, 200)},
        )
    ).all()
    return [
        DeliveryOut(
            id=r[0],
            event_type=r[1],
            status=r[2],
            attempts=int(r[3] or 0),
            first_at=r[4],
            last_at=r[5],
        )
        for r in rows
    ]


__all__ = ["router"]
