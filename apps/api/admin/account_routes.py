"""The two questions an operator asks about a client account that had no answer.

    GET /v1/admin/tenants/{tenant_id}/readiness    what stands between them and dialling
    GET /v1/admin/tenants/{tenant_id}/activity     what has been done to this account

Both are READS and neither invents a fact. The readiness answer is
`legal.readiness.readiness_rows` — the same composition of the same gate predicates the
client reads on their own Agreements & readiness screen — asked for an account named in
the path instead of for the caller's own tenant. The activity answer is `audit_log`,
which already records every mutation in both realms; nothing new is stored to produce it.

**WHY THESE ARE OPERATOR SURFACES AND NOT A SECOND IMPLEMENTATION.** A support call opens
with "why can't we make calls yet", and until now the only way to answer it was to enter
the client's account through view-as and read their screen — which works, costs an
impersonation grant and an audit row, and is impossible for the several accounts an
operator is comparing. The readiness route is the same verdict for an account they are
NOT impersonating. If the gate set ever changes, it changes in `compliance/service.py`
and both screens follow it; neither re-derives a verdict (the rule
`legal/readiness.py` states at length).

**`org:read`, not `admin:tenants`.** D-22 forbids gating a GET on a permission read-only
view-as refuses, and `admin:tenants` is in `MUTATING_PERMISSIONS`. The existing
`/v1/admin/tenants` GETs carry it under an exemption in
`tests/impersonation_reads_test.py`; a new surface does not inherit that exemption, and
the repo's rule is to pick the read permission when one fits (`holds_routes.py` makes the
same choice for the same reason). `realm="admin"` is what keeps a client token out, never
the permission — client roles hold `org:read` too.

**BOTH WRITE `admin.tenant_read`** through `record_admin_tenant_read`, because both name
one client in the path and read that client's own state outside impersonation — SEC-COMP
§5 and D-482 L-1, coalesced per (operator, tenant) per window so a refresh does not fill
the ledger. That is the difference from the holds QUEUE, which is cross-tenant, names no
account's own state and therefore writes nothing.

**HARD RULE 6.** Neither response carries a phone number, a transcript, an extraction
payload or a caller. The activity trail carries `audit_log`'s own columns and no summary —
`audit_log` HAS no summary column (`write_audit`'s summary goes to the log stream, not the
ledger), which is why an operator-facing trail of it is safe to render at all. The one
identity it resolves is the CALEVATE OPERATOR who acted; a client-side actor is reported
as `user` with no address attached, because an operator reading an account's history has
no need for the personal data of the person who clicked and the console has a members
screen for the question they actually mean.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.core.auth import record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.legal.readiness import readiness_rows

router = APIRouter(prefix="/v1/admin/tenants", tags=["admin"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `account_routes.py` — the resolution `holds_routes.py`
# and `kyc_routes.py` reached for the same reason.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
AccountReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]

#: The largest page of history one request will build. Bounded because `audit_log` is the
#: fastest-growing table in this schema and an unbounded trail is a screen that stops
#: rendering on the accounts that need it most.
MAX_ACTIVITY_PAGE = 200


class ReadinessRowOut(BaseModel):
    """One condition holding this account, in the gate's own words."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    title: str
    #: The gate's own refusal sentence, verbatim — the same string the client is shown and
    #: the same one the dial gate returns. An operator on the phone and the client reading
    #: their screen are then quoting one sentence to each other.
    reason: str
    #: Whose move: `client` or `calevate`. The column that turns a list of blockers into a
    #: decision about who to chase.
    actor: Literal["client", "calevate"]
    next_step: str


class TenantReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    #: True when NOTHING is in the way — the same `not rows` the client's own screen
    #: computes, not a second opinion about it.
    may_operate: bool
    #: How many of the blockers are ours to clear. On screen this is the number that
    #: decides whether the operator closes the tab or opens a gate.
    blocked_on_calevate: int
    rows: list[ReadinessRowOut]


@router.get(
    "/{tenant_id}/readiness",
    response_model=TenantReadinessOut,
    openapi_extra=permission_meta("org:read"),
    summary="Everything between one client and their first call — the operator's copy",
    description=(
        "Every organisation-level condition currently blocking this account's outgoing "
        "calls, each with the gate's own refusal sentence, whose move it is and what "
        "clears it. This is the same set the client sees on their Agreements & readiness "
        "screen, composed from the same gate predicates, for an account named in the path "
        "rather than for the caller's own — so a support call does not need a view-as "
        "session to answer 'why can't we dial yet'. Campaign-level blockers (a missing "
        "DLT template, an empty contact list) are not here: they belong to a campaign this "
        "account-level view cannot see. Reading this writes an `admin.tenant_read` audit "
        "row."
    ),
)
async def read_tenant_readiness(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: AccountReader,
) -> TenantReadinessOut:
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")
    # THE ACCOUNT'S OWN RLS SESSION, never the widened admin one: every predicate behind
    # `readiness_rows` reads tenant tables (`kyc_records`, `spend_state`, agreements), and
    # `app.admin` widens `organizations` and nothing else — so asking on the admin session
    # would return zero rows and report a blocked account as ready. The pattern
    # `admin/holds.py` and `service.tenant_overview` both use, and for the same reason.
    async with tenant_session(tenant_id) as scoped:
        rows = await readiness_rows(scoped, tenant_id=tenant_id)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return TenantReadinessOut(
        tenant_id=tenant_id,
        may_operate=not rows,
        blocked_on_calevate=sum(1 for row in rows if row.actor == "calevate"),
        rows=[
            ReadinessRowOut(
                rule=row.rule,
                title=row.title,
                reason=row.reason,
                actor=row.actor,
                next_step=row.next_step,
            )
            for row in rows
        ],
    )


class ActivityEntryOut(BaseModel):
    """One thing that happened to this account, as the ledger recorded it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    at: datetime
    #: The dotted action name `write_audit` was called with — `admin.plan_tier_changed`,
    #: `compliance.kyc_recorded`. Rendered as itself rather than mapped to prose here: the
    #: vocabulary is open (every module adds to it) and a console that only knew some of
    #: the names would silently drop the rest.
    action: str
    object_type: str | None
    object_id: str | None
    actor_type: Literal["admin", "user", "system"]
    actor_id: UUID | None
    #: WHO, when the actor is one of ours — the operator's name or sign-in address from
    #: `admin_users`. `None` for a client-side or system actor, deliberately: see the
    #: module docstring.
    actor_label: str | None
    #: The view-as grant this act came through, or `None` for an ordinary admin-realm act
    #: (D-587). Present is the fact that matters: it means an operator did this while
    #: wearing the client's face, and it joins to the `admin.impersonation_started` row
    #: that names who entered and when.
    via_grant_id: UUID | None


class TenantActivityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    entries: list[ActivityEntryOut]
    total: int
    limit: int
    offset: int


#: The trail, newest first. `(at, id)` is the chain's own total order
#: (`ix_audit_log_chain`), so paging on it can neither repeat nor skip an entry when two
#: rows share a timestamp — which they do, because one request writes several.
#:
#: `admin_users` is LEFT JOINed: `actor_id` is not a foreign key (it holds a `users` id
#: for a client-side act and an `admin_users` id for ours), so the join resolves a label
#: for our own operators and leaves every other actor unlabelled rather than dropping the
#: row. An inner join here would hide from an operator exactly the acts they did not do.
_ACTIVITY_PAGE = (
    "SELECT a.id, a.at, a.action, a.object_type, a.object_id, a.actor_type, a.actor_id, "
    "       a.via_grant_id, coalesce(u.name, u.email) AS actor_label "
    "FROM audit_log a "
    "LEFT JOIN admin_users u ON u.id = a.actor_id AND a.actor_type = 'admin' "
    "WHERE a.tenant_id = :tid "
    "  AND (CAST(:actor_type AS text) IS NULL OR a.actor_type = :actor_type) "
    "ORDER BY a.at DESC, a.id DESC "
    "LIMIT :limit OFFSET :offset"
)

_ACTIVITY_TOTAL = (
    "SELECT count(*) FROM audit_log "
    "WHERE tenant_id = :tid "
    "  AND (CAST(:actor_type AS text) IS NULL OR actor_type = :actor_type)"
)


@router.get(
    "/{tenant_id}/activity",
    response_model=TenantActivityOut,
    openapi_extra=permission_meta("org:read"),
    summary="What has been done to this account, and by whom — read from the audit ledger",
    description=(
        "This account's entries from `audit_log`, newest first: every audited act in "
        "either realm, with the Calevate operator named where one acted and the view-as "
        "grant named where the act came through one. It is a view of the existing "
        "tamper-evident ledger and not a second store, so nothing on it can be edited or "
        "removed. It carries no personal data: `audit_log` records an action, an object "
        "type and an object id, never a phone number, a transcript or a form payload. "
        "Filter by `actor_type` to separate what we did from what the client did. Reading "
        "this writes an `admin.tenant_read` audit row of its own."
    ),
)
async def read_tenant_activity(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: AccountReader,
    actor_type: Literal["admin", "user", "system"] | None = Query(None),
    limit: int = Query(50, ge=1, le=MAX_ACTIVITY_PAGE),
    offset: int = Query(0, ge=0),
) -> TenantActivityOut:
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")
    params = {"tid": tenant_id, "actor_type": actor_type}
    rows = (
        await session.execute(text(_ACTIVITY_PAGE), {**params, "limit": limit, "offset": offset})
    ).all()
    total = int((await session.execute(text(_ACTIVITY_TOTAL), params)).scalar() or 0)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return TenantActivityOut(
        tenant_id=tenant_id,
        entries=[
            ActivityEntryOut(
                id=row.id,
                at=row.at,
                action=row.action,
                object_type=row.object_type,
                object_id=row.object_id,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                actor_label=row.actor_label,
                via_grant_id=row.via_grant_id,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


__all__ = ["router"]
