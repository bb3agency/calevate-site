"""The operator's surface for per-tenant feature flags (SURFACES §1).

    GET /v1/admin/tenants/{tenant_id}/feature-flags          what this client is on
    PUT /v1/admin/tenants/{tenant_id}/feature-flags/{flag}   give them a position, or clear it

Admin realm only. There is deliberately NO client-realm read: a flag is our operational
decision about a client, not a document the client holds — unlike their KYC record or
their first-campaign review, both of which the client can read because they describe the
client's own compliance state and the client is expected to act on them.

WHO MAY DO WHAT, AND WHY THE TWO HALVES DIFFER
-----------------------------------------------
**The read is `org:read`.** D-22 forbids gating a GET on a permission read-only
impersonation refuses (`tests/route_shape_test.py` enforces it, and
`admin.read_commercial_terms` states the same rule), so a mutating permission on this
read would hide a client's configuration from the support session that is looking at that
client. `org:read` is held by both admin roles.

**The write is `admin:tenants`** — the permission every other per-tenant admin mutation
carries (KYC verification, the first-campaign release, DLT registration, commercial
terms). Checked against the role table rather than assumed: `ops:manage` is superadmin-
only and is the PLATFORM surface — the big red switch, the load-shed mode, the DLQ
replay, our own TM registration — every one of which acts on all tenants at once.
Enabling a beta for one client during their onboarding is an operator's job, and gating
it on `ops:manage` would mean an operator could complete an onboarding except for this.

**NO STEP-UP HEADER, and this is a decision rather than an omission.** Step-up in this
repo is reserved for actions where a live, fully-MFA'd session being replayed is the
threat: the big red switch, a cap RAISE, raw-transcript access. Two things put flags
outside that family:

* the neighbouring per-tenant compliance writes take none. Releasing a self-serve account
  for outbound dialling — `POST /v1/admin/tenants/{id}/first-campaign-review` — is a
  larger act than any flag flip and is protected by `admin:tenants` plus an audit row.
  Adding a confirmation here and not there would be the wrong way round;
* `admin.record_commercial_terms` shows the shape a step-up takes when it IS warranted:
  bound to the dangerous DIRECTION (loosening a spend ceiling), not to the route. A flag
  has no such direction, because a flag may not gate a compliance control at all
  (`flags/registry.py` states that limit). **The day one does, the flag is the wrong
  mechanism — not the day to add a header.**

Every write is audited, on a REAL change only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.admin.service import tenant_exists
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.flags.registry import FLAG_NAME_PATTERN, FLAGS, spec_for
from apps.api.flags.service import (
    FlagResolution,
    FlagSource,
    clear_flag,
    read_overrides,
    resolve_flags,
    set_flag,
)

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/feature-flags", tags=["admin"])

FlagReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
FlagWriter = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

# Validated at the boundary so a junk path segment is a 422 naming the rule, never a
# query. The SAME pattern the registry declares and the DB CHECK enforces — one spelling,
# imported rather than retyped.
FlagPath = Annotated[str, Path(pattern=FLAG_NAME_PATTERN, max_length=64)]


class FeatureFlagOut(BaseModel):
    """One flag as it stands for one tenant: the answer, and everything behind it.

    The three booleans are three different facts and none of them can be derived from
    another. `platform_default` is what a tenant with no row gets; `override` is this
    tenant's stored position, `null` when there is none; `enabled` is the resolved answer
    the code would see. A tenant explicitly overridden to the same value as the default
    is not the same as a tenant with no row — the next change to the default reaches one
    and not the other — so the console is given both rather than being asked to guess.
    """

    model_config = ConfigDict(extra="forbid")

    flag: str
    #: False for a row whose flag this build no longer declares. Such a row changes
    #: nothing (no code reads it) and clearing it is safe; the console says so rather
    #: than hiding it, because a hidden leftover is how a retired flag becomes permanent.
    declared: bool
    #: Null exactly when `declared` is false — a retired flag has no spec to describe it.
    description: str | None
    #: The module that CONSUMES this flag, or null while nothing does. Rendered beside
    #: the switch: an operator must never flip a control believing it does something.
    consumed_by: str | None
    platform_default: bool | None
    override: bool | None
    enabled: bool
    source: FlagSource
    #: Why this tenant is off the default. Null when there is no override.
    reason: str | None
    set_by_admin_id: UUID | None
    set_at: datetime | None


class FeatureFlagsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    #: Every DECLARED flag, plus any stored row for a flag this build no longer declares.
    items: list[FeatureFlagOut]


class FeatureFlagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The position to record. **`null` CLEARS the override**, so the tenant follows the
    #: platform default again — the same "null clears this side" contract
    #: `PUT /v1/billing/caps` uses, and the reason this is one route rather than a PUT
    #: and a DELETE: "what is this client's position" has three answers, not two.
    enabled: bool | None = None
    #: Required in both directions. An override nobody can account for is the finding the
    #: column exists to avoid, and "why did we put them BACK on the default" is asked
    #: just as often — the clear writes no row, so its reason survives only in
    #: `audit_log`. Same bounds and the same whitespace rule as `ops.PlatformStateIn`.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("a reason is required — say why this client is off the default")
        return stripped


class FlagStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    source: FlagSource


class FeatureFlagChangeOut(BaseModel):
    """What the write did — including doing nothing, which is a normal outcome.

    `changed: false` means the request restated the position already on file: no row
    moved, `updated_at` did not bump, and NO audit entry was written. That is the
    convention `admin.record_commercial_terms`, `approve_kb` and
    `integrations.deactivate_endpoint` share — the audit log answers "who changed this
    client's behaviour", and a row per button press makes that question harder to answer.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    flag: str
    changed: bool
    before: FlagStateOut
    after: FlagStateOut


def _state(resolution: FlagResolution) -> FlagStateOut:
    return FlagStateOut(enabled=resolution.enabled, source=resolution.source)


@router.get(
    "",
    response_model=FeatureFlagsOut,
    openapi_extra=permission_meta("org:read"),
    summary="Every feature flag this client is on, and where each answer comes from",
    description=(
        "Resolution is platform default → this tenant's override. A flag with no row "
        "for this tenant resolves to its declared default — no row is required to exist "
        "for any tenant. Rows for flags this build no longer declares are listed with "
        "`declared: false`; they change nothing and clearing them is safe."
    ),
)
async def read_feature_flags(tenant_id: UUID, principal: FlagReader) -> FeatureFlagsOut:
    """The read a future gate would make, plus the paperwork a human needs beside it.

    `resolve_flags` is the SAME function a gate calls — not a second query that agrees
    with it today — so this screen cannot report a flag as on while the code reads it as
    off. `read_overrides` supplies who set it, why and when, which the resolution
    deliberately does not carry (a hot-path read should not drag prose through it).
    """
    del principal
    async with tenant_session(tenant_id) as session:
        if not await tenant_exists(session, tenant_id):
            raise ProblemError.not_found("Organization")
        resolved = await resolve_flags(session, tenant_id=tenant_id)
        stored = {row.flag: row for row in await read_overrides(session, tenant_id=tenant_id)}

    items = [
        FeatureFlagOut(
            flag=name,
            declared=True,
            description=FLAGS[name].description,
            consumed_by=FLAGS[name].consumed_by,
            platform_default=FLAGS[name].default,
            override=stored[name].enabled if name in stored else None,
            enabled=resolution.enabled,
            source=resolution.source,
            reason=stored[name].reason if name in stored else None,
            set_by_admin_id=stored[name].set_by_admin_id if name in stored else None,
            set_at=stored[name].updated_at if name in stored else None,
        )
        for name, resolution in resolved.items()
    ]
    items.extend(
        FeatureFlagOut(
            flag=row.flag,
            declared=False,
            description=None,
            consumed_by=None,
            platform_default=None,
            override=row.enabled,
            # A retired flag has no behaviour to report, because no code reads it. The
            # row's own value is echoed in `override` so an operator can see what it
            # said; `enabled` reports what it DOES, which is nothing.
            enabled=False,
            source="tenant_override",
            reason=row.reason,
            set_by_admin_id=row.set_by_admin_id,
            set_at=row.updated_at,
        )
        for flag, row in stored.items()
        if spec_for(flag) is None
    )
    return FeatureFlagsOut(tenant_id=tenant_id, items=items)


@router.put(
    "/{flag}",
    response_model=FeatureFlagChangeOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set this client's position on one flag, or clear it (audited on a real change)",
    description=(
        "`enabled: true|false` records an explicit position for this client. "
        "`enabled: null` CLEARS the override, so they follow the platform default again. "
        "A `reason` is required either way. Restating the position already on file "
        "returns `changed: false` and writes nothing — no row moves and no audit entry "
        "is made. Setting a flag this build does not declare is refused; CLEARING one is "
        "allowed, because that is how a retired flag's leftover rows are removed."
    ),
)
async def put_feature_flag(
    tenant_id: UUID,
    flag: FlagPath,
    payload: FeatureFlagIn,
    request: Request,
    principal: FlagWriter,
) -> FeatureFlagChangeOut:
    """Audited on a real change, in the transaction that made it.

    `write_audit` appends in the CALLER'S transaction, so the row and the record of who
    moved it commit together or not at all (`recompute_spend_cap` is the same shape). The
    summary carries the flag name, both effective values and the reason — code
    identifiers and ops prose, no phone number, transcript or extraction anywhere on this
    path (hard rule 6), and `redact_mapping` runs over it regardless.

    Setting an UNDECLARED flag is refused here rather than in the service, so the operator
    gets a problem naming the flags that exist instead of a row nothing will ever read.
    Clearing one is allowed for the reason `service.clear_flag` argues: refusing it would
    make a retired flag's rows unreachable from the product.
    """
    # `requires(..., realm="admin")` resolved this principal against `admin_users`, so
    # the id is present — and `set_by_admin_id` is NOT NULL, so a None here would be an
    # IntegrityError at COMMIT rather than a clear failure at the top of the request.
    assert principal.user_id is not None

    setting = payload.enabled is not None
    if setting and spec_for(flag) is None:
        raise ProblemError(
            kind="validation",
            code="feature_flag_unknown",
            title="Unknown feature flag",
            detail=f"{flag!r} is not a flag this build declares, so setting it would do nothing.",
            remediation=f"Use one of: {', '.join(sorted(FLAGS))}.",
            fields=[{"field": "flag", "rule": "declared", "message": "no such flag"}],
        )

    async with tenant_session(tenant_id) as session:
        if not await tenant_exists(session, tenant_id):
            # A mistyped uuid must not answer 200 with a cheerful "nothing changed" —
            # read as "already set" by the operator who meant a different client.
            raise ProblemError.not_found("Organization")

        if payload.enabled is None:
            change = await clear_flag(session, tenant_id=tenant_id, flag=flag)
            action = "feature_flag.cleared"
        else:
            change = await set_flag(
                session,
                tenant_id=tenant_id,
                flag=flag,
                enabled=payload.enabled,
                reason=payload.reason,
                set_by_admin_id=principal.user_id,
            )
            action = "feature_flag.set"

        if change.changed:
            await write_audit(
                session,
                action=action,
                actor=principal,
                tenant_id=tenant_id,
                object_type="tenant_feature_flag",
                object_id=flag,
                ip=client_request_ip(request),
                summary={
                    "flag": flag,
                    "enabled_before": change.before.enabled,
                    "enabled_after": change.after.enabled,
                    "source_before": change.before.source,
                    "source_after": change.after.source,
                    "reason": payload.reason,
                },
            )

    return FeatureFlagChangeOut(
        tenant_id=tenant_id,
        flag=flag,
        changed=change.changed,
        before=_state(change.before),
        after=_state(change.after),
    )


__all__ = ["router"]
