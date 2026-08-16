"""Integration endpoints — the client's own outbound config (D-23, SURFACES §2b).

`org:manage` on the writes: pointing our events at a URL or a spreadsheet is an
account-level decision, not a lead-handling one, and staff explicitly do not get org
settings (SEC-COMP §5). The reads take `org:read`, because D-22 refuses every mutating
permission to read-only impersonation and a support person must be able to see the
screen the client is looking at.

The signing secret is returned EXACTLY ONCE, at creation. After that the API answers
with a fingerprint and never the value — a config screen that re-displays a shared
secret turns every screenshot and every support session into a key disclosure.

**Creating an endpoint is an egress decision, and it is treated as one.** A webhook URL
is vetted by `egress_guard.assert_public_http_url` before the row exists — and again in
`service.deliver`, because the tenant owns that name's DNS — and BOTH create routes
write an `audit_log` row naming who did it. Registration is the act that starts a
client's lead PII leaving their tenant; it used to be the one mutating route here with
no record of it, while the DELETE that stops the flow had one.

**Both D-23 kinds are configurable here, and one of them is gated.** See
`create_sheets_endpoint` for the argument; the short version is that a checkbox for a
transport that cannot deliver is the defect the sheets work exists to remove, so the
route refuses rather than offering it where Google Sheets delivery does not exist.
The gate is also PUBLISHED, on `EndpointOptionsOut.sheets_delivery_available`, so a
console does not have to discover the refusal by attempting the create — but publishing
it changes nothing about who decides: the route still refuses on its own.
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
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.integrations import service
from apps.api.integrations.egress_guard import assert_public_http_url
from apps.api.integrations.service import EVENT_TYPES

# The API asking the delivery path whether it can deliver. Imported rather than
# re-derived from settings so there is ONE answer: a config surface that decided for
# itself would eventually disagree with the worker, and the disagreement reads as
# "the screen says configured and the spreadsheet stays empty".
from apps.workers.sheets_sync import sheets_delivery_available

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

Session = Annotated[AsyncSession, Depends(db)]

EventName = Literal["lead.created", "lead.updated", "call.completed", "campaign.completed"]

# The two audit actions this module writes. NAMED rather than typed twice: the disable
# action was a bare literal here and a second bare literal in the test that asserts it,
# which is one string away from a ledger that records an action nothing searches for.
ENDPOINT_CREATED = "integration_endpoint.created"
ENDPOINT_DISABLED = "integration_endpoint.disabled"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EndpointOptionsOut(Strict):
    """What an endpoint may subscribe to, and what this deployment can deliver on.

    A DECLARED model rather than the `dict[str, list[str]]` this route used to return.
    An undeclared response is one `openapi-typescript` can only describe as an index
    signature, so `events` was not a NAMED field and the console's single read of it was
    the one read `tsc` could not check — the same defect, and the same fix, as
    `SubjectExportOut` replacing a free-form dict, and the reason `MetaSetupOut` one
    module over says "declared rather than a bare dict". It also puts the response back
    inside `scripts/check_redaction_exposure.py`'s walk, which inspects response MODELS:
    a route with no model is a route that guardrail cannot inspect at all.

    `events` stays `list[str]` rather than `list[EventName]`, and that is deliberate.
    `EventName` is what THIS BUILD can put in a request body; `EVENT_TYPES` is what the
    RUNNING deployment offers. A console generated from an older snapshot has to be able
    to see a name outside its own union in order to SAY SO, rather than render a checkbox
    whose only possible outcome is a 422 — narrowing this to the literal would make that
    gap unrepresentable, and would turn a deployment that adds an event into a 500 out of
    response validation.
    """

    events: list[str]
    # Whether THIS DEPLOYMENT can append to a Google Sheet at all — the same selector
    # `create_sheets_endpoint` asks, so this response cannot offer a transport that route
    # refuses. It rides here rather than on an endpoint of its own for the reason
    # `KycRecordOut.number_purchase_available` does: it is half of "which of these forms
    # can I use", the event list is the other half, and a screen holding one without the
    # other would render a form built from something it does not have.
    #
    # A HINT FOR RENDERING, never the check. The route still refuses on its own, because
    # nothing obliges a client to have read this first — and because this value is a
    # deployment constant a console may legitimately have cached for half an hour while
    # an operator turned Sheets off.
    #
    # NOT a statement about any particular endpoint: whether a row has a Google
    # credential attached is `EndpointOut.secret_fingerprint`, checked per row by
    # `append_event`. False on every deployment today (no `GOOGLE_SHEETS_PROVIDER`),
    # which is a FOUNDER/OPS decision rather than a fault.
    sheets_delivery_available: bool


class CreateEndpointIn(Strict):
    # HttpUrl rejects a bare hostname and anything that is not http(s) — we sign and
    # POST to whatever lands here, so "looks like a URL" is not good enough.
    #
    # AND IT IS NOWHERE NEAR ENOUGH ON ITS OWN. `http://169.254.169.254/latest/meta-data/`
    # is a perfectly good `HttpUrl`, and this value ends up in `service.deliver`, which
    # POSTs a signed body carrying a lead's name and phone number to it. The address the
    # name RESOLVES to is the check that matters, and it is made by
    # `egress_guard.assert_public_http_url` in the handler — not in this model — because
    # it needs a DNS lookup and because the same call has to be repeated at delivery
    # time, where there is no request body to validate.
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
    # Whether a copy of what we sent is still retained for this delivery. A BOOLEAN, not
    # the key: the object-storage key names the subject's row id, and a client-facing
    # list is not the place for it. False is a real answer with several honest causes —
    # the body aged out on the tenant's own retention policy, an erasure destroyed it,
    # object storage was down when the delivery ran, or the event carries no subject we
    # could file it under (`service.body_subject`). The screen offers the link only when
    # this is true, so nobody clicks through to a refusal.
    payload_stored: bool


class DeliveryPayloadOut(Strict):
    """What we actually sent, byte for byte — the raw-PII surface of this module.

    Same class of data as a raw transcript and gated the same way (hard rule 5):
    `calls:read_raw` AND an `audit_log` row, never one of the two. `body` is the exact
    string that went on the wire, so it carries the lead's name and their number in
    whatever form the endpoint's own `include_raw_phone` choice produced — which is the
    entire point, since "you sent us the wrong lead" cannot be answered with a redaction.
    """

    delivery_id: UUID
    event_type: str | None
    # The client's own field names when they configured a mapping, because that is what
    # we sent them.
    body: str
    # Declared by the stored object, never inferred by comparing `len(body)` to today's
    # cap: a reader has to be able to tell "this is all of it" from "this is the first
    # 64 KiB of it", including for objects written when the cap was different.
    truncated: bool
    original_bytes: int
    stored_at: str | None


@router.get(
    "/events",
    response_model=EndpointOptionsOut,
    openapi_extra=permission_meta("org:read"),
    summary="What an endpoint may subscribe to, and which transports this account can use",
    description=(
        "The events an endpoint may subscribe to, and whether this account can deliver "
        "to a Google Sheet. `sheets_delivery_available: false` means "
        "`POST /v1/integrations/endpoints/sheets` will be refused with "
        "`sheets_delivery_unavailable`, so a form for it should not be offered — but the "
        "refusal remains the authority, and this field is only how you learn about it "
        "without attempting the create."
    ),
)
async def endpoint_options(_: Principal = Depends(requires("org:read"))) -> EndpointOptionsOut:
    """Both facts the two create forms need, in ONE read.

    Two reads would let a screen hold the events without the capability (or the reverse)
    and render half a decision; one read cannot. The path stays `/events` because
    renaming it churns every generated client for no contract gain — what moved is the
    response, not the resource.
    """
    return EndpointOptionsOut(
        events=list(EVENT_TYPES),
        # Asked per request rather than captured at import: enabling Sheets is a config
        # change, and an operator who makes one must not need an API restart before the
        # form appears.
        sheets_delivery_available=sheets_delivery_available(),
    )


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
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CreateEndpointOut:
    """Register a webhook endpoint. Two things happen here that did not used to.

    **The destination is vetted before the row exists.** `assert_public_http_url` resolves
    the host and refuses loopback, link-local, private, multicast, reserved and
    unroutable addresses, and any port but 80/443 — see `egress_guard` for the bypass
    classes and the evidence. It is checked AGAIN in `service.deliver`, because the name
    is one the tenant controls the DNS for and this row outlives the lookup.

    **And the registration is audited.** Deactivating an endpoint wrote an `audit_log`
    row while CREATING one wrote nothing, which had it exactly backwards: registration
    is the act that starts a client's lead PII leaving their tenant, and it was the act
    with no record of who performed it. Written in the SAME transaction as the INSERT,
    so an endpoint cannot exist without the row naming who made it.

    The summary records the HOST, never the URL. A webhook URL's path and query are
    tenant-authored free text and routinely carry a bearer credential (`?apikey=…`); an
    audit trail that quoted the whole thing would leak the secret it exists to attest
    (hard rule 6). The host is the fact an investigator needs — where the leads went.
    """
    assert principal.tenant_id is not None
    destination = await assert_public_http_url(str(payload.url))
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
    # AFTER the INSERT, deliberately: `write_audit` takes the chain's advisory lock and
    # holds it to COMMIT (BACKEND-PATTERNS §7), so it belongs late in the transaction.
    await write_audit(
        session,
        action=ENDPOINT_CREATED,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="outbound_webhook",
        object_id=str(endpoint_id),
        ip=client_request_ip(request),
        summary={
            "kind": service.WEBHOOK_KIND,
            "host": destination.host,
            "port": destination.port,
            # JOINED, not a list, and for the reason `core.health` joins its missing-key
            # names: `logging.redact_mapping` renders ANY list extra as "[N items]", so
            # this field reached the audit stream as the COUNT of the events subscribed
            # and never one of their names. "Who pointed our leads outward, and where" is
            # the question this row exists to answer, and half of "where" is which events
            # start flowing. Sorted so two identical registrations record identically.
            "events": ",".join(sorted(payload.events)),
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
    request: Request,
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
    # The SAME audit action as a webhook, in the same transaction, for the same reason:
    # this is the other way a tenant starts their lead PII leaving the tenant, and an
    # investigator asking "who pointed our leads outward, and where" must not have to
    # know which of the two forms was used to get an answer. There is no `host` to
    # record — the destination is Google's API and the document id is what identifies
    # it — so the id takes its place. NO SSRF check on this path, deliberately: nothing
    # here is ever fetched. `parse_spreadsheet_ref` has already reduced whatever was
    # pasted to a document id, the delivery goes to `sheets.googleapis.com`, and a URL
    # the client typed never reaches a socket.
    await write_audit(
        session,
        action=ENDPOINT_CREATED,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="outbound_webhook",
        object_id=str(endpoint_id),
        ip=client_request_ip(request),
        summary={
            "kind": service.SHEET_KIND,
            # Left as-is deliberately. `redact_mapping` masks any run of nine or more
            # digits as `[phone]`, which a Drive id could in principle trip — measured at
            # roughly one registration in a million, since these are 44 characters from a
            # 64-symbol alphabet. Re-judged rather than inherited: it is acceptable
            # because this row is not the only copy. `object_id` names the endpoint,
            # `outbound_webhooks.url` holds the id in full, and no route updates that
            # column — so an investigator who reads `[phone]` here is one join away from
            # the answer. Loosening the shared masker to protect a field that is already
            # recoverable would trade a certainty (no phone number in a log) for a
            # convenience.
            "spreadsheet_id": spreadsheet_id,
            # Joined for the reason the webhook route's is — see there.
            "events": ",".join(sorted(payload.events)),
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
            action=ENDPOINT_DISABLED,
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="outbound_webhook",
            object_id=str(endpoint_id),
            ip=client_request_ip(request),
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
                "SELECT d.id, d.event_type, d.status, d.attempts, d.first_at, d.last_at, "
                # The presence of the key, never the key. `payload_ref` contains the
                # subject's row id, and this endpoint is `org:read` — the raw body is
                # two permissions further up.
                "d.payload_ref IS NOT NULL "
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
            payload_stored=bool(r[6]),
        )
        for r in rows
    ]


@router.get(
    "/deliveries/{delivery_id}/payload",
    response_model=DeliveryPayloadOut,
    openapi_extra=permission_meta("calls:read_raw"),
    summary="What we actually sent — role-checked AND audit-logged on every read",
    description=(
        "The exact body we POSTed for one delivery, as your endpoint received it. This "
        "is your customer's personal data in unredacted form, so it requires the same "
        "permission as an unredacted transcript and every read is written to your audit "
        "log. Bodies are kept for as long as your lead-retention policy allows and are "
        "destroyed by an erasure request; `404 delivery_body_not_retained` means there "
        "is no longer one to show."
    ),
)
async def get_delivery_payload(
    delivery_id: UUID,
    session: Session,
    request: Request,
    # `calls:read_raw`, NOT `org:read` — the permission follows the DATA, not the screen
    # it happens to be on. This body carries the lead's name and their number in exactly
    # the form the endpoint's `include_raw_phone` choice produced, which is the same
    # class of thing as `text` versus `text_redacted`, and hard rule 5 puts that behind
    # a role check AND an audit row. `crm.routes.get_lead_contact` makes the identical
    # call for the identical reason. It also settles the D-22 question in the right
    # direction by construction: `operator` does not hold `calls:read_raw` at all, so an
    # impersonating support user sees the delivery list — which is what they need to
    # answer "did it arrive?" — and never the payload.
    principal: Principal = Depends(requires("calls:read_raw")),
) -> DeliveryPayloadOut:
    """One retained delivery body. Absent, expired and unreachable are three answers.

    A NULL `payload_ref` is 404 `delivery_body_not_retained`: the body aged out, an
    erasure destroyed it, or none was ever kept. An object the store cannot produce is
    503 `delivery_body_unavailable` — a fact about today, not about our retention — and
    collapsing the two would tell a client their evidence is gone during an outage.
    """
    payload_ref, event_type = await service.delivery_body_ref(session, delivery_id)
    if payload_ref is None:
        raise ProblemError(
            # `not_found` (404), not `business_rule` (422): the client asked for a thing
            # and it is not there. 422 would say their REQUEST was wrong, which it was
            # not — and the same code answers a delivery that never had a body, one that
            # aged out and one an erasure destroyed, because those are one fact to them.
            kind="not_found",
            code="delivery_body_not_retained",
            title="No copy of this delivery is kept",
            detail=(
                "We no longer hold a copy of what was sent for this delivery. Bodies are "
                "kept for as long as your lead-retention policy allows, and an erasure "
                "request destroys them."
            ),
            remediation=(
                "The delivery record itself — event, result and attempts — is still on "
                "your integrations screen."
            ),
        )

    # The audit row is written in the SAME transaction as the read, so there is no window
    # in which someone saw raw PII without it being recorded (hard rule 5). Written
    # BEFORE the object is fetched for the same reason: a read that failed on our side
    # was still an attempt to see this person's data.
    await write_audit(
        session,
        action="webhook_delivery.read_payload",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="webhook_delivery",
        object_id=str(delivery_id),
        ip=client_request_ip(request),
    )

    # Imported here, not at module scope, for the reason `crm.routes.get_recording`
    # gives: boto3 belongs to the workers package and pulling it into every API import
    # would slow cold starts for one route.
    from apps.workers.storage import StorageUnavailableError, read_delivery_body

    try:
        document = await read_delivery_body(payload_ref)
    except StorageUnavailableError as exc:
        raise ProblemError(
            kind="dependency",
            code="delivery_body_unavailable",
            title="The stored copy could not be retrieved",
            detail="The delivery body could not be read right now. It has not been deleted.",
            remediation="Try again in a few minutes.",
        ) from exc
    if document is None:
        # The reference outlived the object — an erasure or a sweep that cleared the
        # bytes and lost the row update, which the next sweep tidies. Says the same
        # thing to the client as a NULL ref, because it means the same thing to them.
        raise ProblemError(
            # `not_found` (404), not `business_rule` (422): the client asked for a thing
            # and it is not there. 422 would say their REQUEST was wrong, which it was
            # not — and the same code answers a delivery that never had a body, one that
            # aged out and one an erasure destroyed, because those are one fact to them.
            kind="not_found",
            code="delivery_body_not_retained",
            title="No copy of this delivery is kept",
            detail="We no longer hold a copy of what was sent for this delivery.",
            remediation=(
                "The delivery record itself — event, result and attempts — is still on "
                "your integrations screen."
            ),
        )

    return DeliveryPayloadOut(
        delivery_id=delivery_id,
        event_type=event_type or None,
        body=str(document.get("body") or ""),
        truncated=bool(document.get("truncated")),
        original_bytes=int(document.get("original_bytes") or 0),
        stored_at=str(document["stored_at"]) if document.get("stored_at") else None,
    )


__all__ = ["router"]
