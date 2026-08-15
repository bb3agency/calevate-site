"""Capture surface for the CLIENT's WhatsApp alert opt-in (migration e6b2d94f31a7).

The reasoning that decides what a row must carry lives in `compliance/whatsapp_optin.py`.
What this file decides is WHO may write one, and from WHICH realm — which the migration
argues is a first-class part of the design rather than plumbing.

**Two routers, because they are two different acts.**

`router` (client realm) is the owner opting THEMSELVES in. The subject and the principal
are the same person, which is what makes the act self-evidencing and is enforced both by
the service (`alert_optin_self_serve_is_first_person`) and by a CHECK constraint.

`admin_router` is an operator recording that the owner already agreed — during
onboarding, on a call, on a signed form. A claim about somebody else, so it carries a
document reference and names the operator, and it lives in the admin realm because that
is where an operator's identity is resolvable (`admin_users.id`).

**Recording is `org:manage`, and the choice is load-bearing.**

- It is the permission that already governs a client's own account settings, and
  agreeing to receive WhatsApp about your business is exactly that decision.
- Only the `owner` role holds it (`ROLE_PERMISSIONS`), so a staff member cannot opt the
  business's owner in — the subject of the opt-in is the only person who can give it.
- It is in `MUTATING_PERMISSIONS`, so D-22 refuses it inside a read-only "view as
  client" session. An admin wearing a client's face cannot manufacture that client's
  consent, which is the whole reason the operator path exists separately and audibly.

Reading is `org:read`, not `org:manage`: seeing whether alerts are on is not turning them
on, and it must stay visible inside an impersonated session — the recurring bug
`tests/impersonation_reads_test.py` exists to stop.

**There is no phone number anywhere on these surfaces.** The subject is the authenticated
principal (client realm) or the tenant's owner (admin realm), and the number is read
server-side from `users.phone` — the same row `resolve_destination` reads. Nothing echoes
a number back, and nothing accepts one: a number on the wire would be a second copy of a
fact we already hold, and a second chance for the consent key to drift from the delivery
key. That is also why the client-realm read may be a GET while `messaging-consent`'s
lookup must be a POST: there is no identifier in the path or query to leak.

There is no DELETE. The ledger is append-only (hard rule 4) and the way to say "no
longer" is `status: "withdrawn"`, which is a new row that supersedes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import whatsapp_optin
from apps.api.compliance.audit import write_audit
from apps.api.compliance.models import ALERT_OPTIN_OPERATOR, ALERT_OPTIN_SELF_SERVE
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/compliance/whatsapp-alerts", tags=["compliance"])
# Its own `/v1/admin/tenants/{tenant_id}/...` prefix, like every other per-tenant admin
# surface whose table lives in the compliance package (`first_campaign_routes`).
admin_router = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/whatsapp-alerts", tags=["admin", "compliance"]
)

Session = Annotated[AsyncSession, Depends(db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is only waived for
# `**/routes.py`, and this module is `whatsapp_optin_routes.py` — the same situation, and
# the same resolution, as `consent_routes.py` and `dnc_routes.py`.
Owner = Annotated[Principal, Depends(requires("org:manage", realm="client"))]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

# Spelled as a Literal rather than derived from the tuple so the generated TypeScript
# client gets a union it can switch on. The tuple in `compliance/models.py` is still the
# source of truth: `tests/whatsapp_optin_test.py` asserts the two cannot drift.
AlertOptInStatus = Literal["granted", "withdrawn"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordAlertOptInIn(Strict):
    """No phone field, deliberately — see the module docstring. The number is read from
    the principal's own profile so the consent key and the delivery key are the same
    read."""

    status: AlertOptInStatus
    # Which wording the client was shown. Sent by the console and CHECKED against the
    # server's current version rather than stored blindly: a client running a cached
    # build that shows last quarter's notice must not have this quarter's version
    # recorded against their agreement. That row would be evidence of something that did
    # not happen, which is worse than no row.
    notice_version: str = Field(min_length=1, max_length=64)


class RecordOperatorOptInIn(Strict):
    """An operator recording that the owner already agreed. Carries the document."""

    status: AlertOptInStatus
    # WHERE the agreement is filed — the onboarding pack reference, the ticket id. A
    # reference, never the document (the `secret_ref` principle). Required for a grant by
    # both the service and a CHECK; meaningless for a withdrawal.
    evidence: dict[str, str] | None = Field(default=None, max_length=20)


class AlertOptInOut(Strict):
    """Never the number. `status: "none"` means this person has never been asked, which
    is a 200 and the normal state of the world, not a 404."""

    status: str
    channel: str | None
    captured_at: datetime | None
    notice_version: str | None
    # The whole question, computed server-side. The console must not re-derive it, or it
    # will disagree with the worker on the day it matters.
    messageable: bool
    # The wording currently in force, and its version. NO DEFAULTS on either: a Pydantic
    # field with a default is OPTIONAL in the generated TypeScript, and a console that
    # has to render the exact text a client is agreeing to cannot be handed a `| null`
    # for it. Returned on every response so the tick-box copy comes from the same place
    # the stored `notice_version` points at.
    current_notice_version: str
    current_notice_text: str
    # Whether this deployment could actually deliver an alert if they said yes. A screen
    # that offers an opt-in for a channel nothing can send on is the "looks finished"
    # failure the WhatsApp seam was built to avoid.
    delivery_available: bool
    delivery_unavailable_reason: str | None


def _out(state: whatsapp_optin.AlertOptIn) -> AlertOptInOut:
    # Imported here rather than at module scope: `apps/workers/*` is the worker package
    # and an API route module importing it at import time would drag the worker's
    # dependency surface into the API's boot. The selector is a pure settings read.
    from apps.workers.whatsapp import whatsapp_delivery_status

    delivery = whatsapp_delivery_status()
    return AlertOptInOut(
        status=state.status,
        channel=state.channel,
        captured_at=state.captured_at,
        notice_version=state.notice_version,
        messageable=state.messageable,
        current_notice_version=whatsapp_optin.ALERT_NOTICE_VERSION,
        current_notice_text=whatsapp_optin.ALERT_NOTICE_TEXT,
        delivery_available=delivery.available,
        delivery_unavailable_reason=delivery.reason,
    )


async def _phone_of(session: AsyncSession, user_id: UUID) -> str:
    """The number an alert would actually be sent to, from the row the worker reads.

    Refuses rather than defaulting: a person with no number on their profile cannot opt
    in to messages at a number, and recording that they did would be a consent record
    with nothing behind it.
    """
    row = (
        await session.execute(
            text("SELECT phone FROM users WHERE id = :uid AND deactivated_at IS NULL"),
            {"uid": user_id},
        )
    ).first()
    phone = str(row[0]) if row is not None and row[0] else ""
    if not phone:
        raise ProblemError.business_rule(
            "alert_optin_needs_a_number",
            "There is no mobile number on this account to send alerts to.",
            remediation="Add a mobile number to the profile first, then turn alerts on.",
        )
    return phone


async def _owner_of(session: AsyncSession, tenant_id: UUID) -> tuple[UUID, str]:
    """The tenant's owner and their number — the SAME query `resolve_destination` runs.

    Deliberately the same shape rather than a convenient variation: the operator surface
    must record the opt-in against exactly the person the worker would send to, or an
    operator could evidence one human's agreement and the alert would reach another.
    """
    row = (
        await session.execute(
            text(
                "SELECT u.id, u.phone FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.tenant_id = :tid AND m.role = 'owner' "
                "AND u.deactivated_at IS NULL AND u.phone IS NOT NULL "
                "ORDER BY m.created_at LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or not row[1]:
        raise ProblemError.business_rule(
            "alert_optin_no_owner_with_a_number",
            "This account has no active owner with a mobile number.",
            remediation="Add a mobile number to the owner's profile, then record the opt-in.",
        )
    return UUID(str(row[0])), str(row[1])


@router.get(
    "",
    response_model=AlertOptInOut,
    openapi_extra=permission_meta("org:read"),
    summary="Are WhatsApp hot-lead alerts on for me?",
    description=(
        "The current state of your own WhatsApp alert opt-in, plus the wording in force "
        "and whether this deployment can deliver on the channel at all. No phone number "
        "is accepted or returned."
    ),
)
async def read(session: Session, principal: Reader) -> AlertOptInOut:
    assert principal.tenant_id is not None
    if principal.user_id is None:
        # An admin "view as client" session has no `users` row of its own, so there is no
        # subject to read an opt-in for. Answering `none` would be a claim about a person
        # who does not exist in this session; answering the OWNER's state would leak one
        # human's consent record to another. So it reports the channel's readiness and no
        # subject state, which is the only true answer.
        return _out(whatsapp_optin.NO_OPT_IN)
    phone = await _phone_of(session, principal.user_id)
    return _out(
        await whatsapp_optin.read_alert_optin(
            session, tenant_id=principal.tenant_id, user_id=principal.user_id, phone_e164=phone
        )
    )


@router.post(
    "",
    response_model=AlertOptInOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Turn your own WhatsApp hot-lead alerts on or off (append-only)",
    description=(
        "Appends one row to the opt-in ledger. Withdrawing is a new row with "
        "`status: withdrawn`, never an edit of the opt-in it supersedes. Only the "
        "account owner can record their own opt-in, and an impersonated session cannot."
    ),
)
async def record(
    payload: RecordAlertOptInIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> AlertOptInOut:
    assert principal.tenant_id is not None
    if principal.user_id is None:
        # Unreachable through `requires(..., realm="client")`, which resolves a
        # membership — but the type says `UUID | None`, and an opt-in row attributed to
        # nobody is the one thing this ledger must never contain.
        raise ProblemError.forbidden("An opt-in can only be recorded by the person giving it.")
    if (
        payload.status == "granted"
        and payload.notice_version != whatsapp_optin.ALERT_NOTICE_VERSION
    ):
        # A stale console showing last quarter's notice must not have this quarter's
        # version recorded against it. Refusing is the honest outcome: the client is
        # agreeing to wording we are no longer showing, and the row would evidence
        # something that did not happen.
        raise ProblemError.business_rule(
            "alert_optin_notice_out_of_date",
            "The wording on your screen is out of date.",
            remediation="Reload the page and confirm again — the text has changed since it loaded.",
        )
    phone = await _phone_of(session, principal.user_id)
    state = await whatsapp_optin.record_alert_optin(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        phone_e164=phone,
        status=payload.status,
        channel=ALERT_OPTIN_SELF_SERVE,
        # The subject IS the recorder. The CHECK requires the two to be equal for a
        # self-serve grant, which is what makes an operator-written self-serve row
        # unrepresentable rather than merely discouraged.
        recorded_by_user_id=principal.user_id,
    )
    await write_audit(
        session,
        action="whatsapp_alert_optin.recorded",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="whatsapp_alert_optin_ledger",
        object_id=None,
        ip=request.client.host if request.client else None,
        # The decision and the wording, never the number.
        summary={
            "status": payload.status,
            "channel": ALERT_OPTIN_SELF_SERVE,
            "notice_version": whatsapp_optin.ALERT_NOTICE_VERSION,
        },
    )
    return _out(state)


@admin_router.post(
    "",
    response_model=AlertOptInOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record that a client's owner agreed to WhatsApp alerts (append-only)",
    description=(
        "For an opt-in given during onboarding rather than on the settings screen. A "
        "grant must carry the reference of the document or ticket the client agreed in, "
        "and the row names the operator who recorded it."
    ),
)
async def record_for_client(
    tenant_id: UUID,
    payload: RecordOperatorOptInIn,
    session: AdminSession,
    request: Request,
    principal: Operator,
) -> AlertOptInOut:
    """Same family and shape as `first_campaign_routes.decide`: `admin:tenants`, tenant
    in the PATH, and the tenant-table work done inside `tenant_session(tenant_id)` so
    RLS is what isolates it rather than a WHERE clause."""
    # `requires(..., realm="admin")` resolved this principal against `admin_users`, so
    # `user_id` here is an admin id — which is exactly what the ledger's
    # `recorded_by_admin_id` FK points at, and the CHECK behind this write refuses an
    # operator record that cannot name its operator.
    assert principal.user_id is not None
    async with tenant_session(tenant_id) as scoped:
        owner_id, phone = await _owner_of(scoped, tenant_id)
        state = await whatsapp_optin.record_alert_optin(
            scoped,
            tenant_id=tenant_id,
            user_id=owner_id,
            phone_e164=phone,
            status=payload.status,
            channel=ALERT_OPTIN_OPERATOR,
            recorded_by_admin_id=principal.user_id,
            evidence=payload.evidence,
        )
    await write_audit(
        session,
        action="whatsapp_alert_optin.recorded_by_operator",
        actor=principal,
        tenant_id=tenant_id,
        object_type="whatsapp_alert_optin_ledger",
        object_id=str(owner_id),
        ip=request.client.host if request.client else None,
        summary={
            "status": payload.status,
            "channel": ALERT_OPTIN_OPERATOR,
            "evidenced": bool(payload.evidence),
        },
    )
    return _out(state)


__all__ = ["admin_router", "router"]
