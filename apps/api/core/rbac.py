"""RBAC as a policy registry VALIDATED AT BOOT (BACKEND-PATTERNS §7).

The pattern that matters: the endpoint→permission map is asserted at startup, not
discovered at first request. A new route that forgets its permission fails the boot
assertion in CI, not silently in production with an open door.

Role tables (DATA-MODEL §2):
- client realm `owner` — everything in their own tenant, including raw transcripts
  (role check + audit_log write, hard rule 5) and billing.
- client realm `staff`  — no billing, no org settings, no raw transcripts.
- admin realm `operator`   — runs onboarding and support across tenants.
- admin realm `superadmin` — adds the dangerous switches (big red switch, cap raises),
  each of which additionally needs step-up confirmation.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Literal

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

Permission = Literal[
    "agents:read",
    "agents:write",
    "calls:read",
    "calls:read_raw",
    "leads:read",
    "leads:write",
    "leads:dispatch",
    "billing:read",
    "org:read",
    "org:manage",
    "kb:write",
    "admin:tenants",
    "admin:impersonate",
    "ops:manage",
    # Reading and changing PLATFORM configuration — the engine selection, the calling
    # windows, the rate limits (PLATFORM-CONFIG §7).
    #
    # A NEW PERMISSION RATHER THAN A REUSE OF `admin:tenants`, and the spec argues why:
    # the blast radii are not comparable. `admin:tenants` is "act on one client";
    # this is "change what every client's platform does at the same instant" — switch
    # the voice engine, move a calling window outside TRAI's permitted hours, raise a
    # rate limit. An operator who onboards clients does not need it, and the whole
    # point of a separate name is that it can be held by fewer people.
    #
    # It is deliberately NOT `ops:manage` either, even though both are superadmin-only
    # today and both live under `/v1/ops`. `ops:manage` is the INCIDENT surface — the
    # big red switch, the DLQ replay, the audit-chain check — and its holders are
    # whoever is on call. Config is a change-management surface. Merging them would mean
    # the next person given the pager could also switch the engine, which is exactly the
    # separation §7 asks for and the one phase 4's `platform:secrets` deepens.
    "platform:config",
]

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "staff": frozenset(
        {
            "agents:read",
            "calls:read",
            "leads:read",
            "leads:write",
            "org:read",
        }
    ),
    "owner": frozenset(
        {
            "agents:read",
            "calls:read",
            "calls:read_raw",
            "leads:read",
            "leads:write",
            "leads:dispatch",
            "billing:read",
            "org:read",
            "org:manage",
            "kb:write",
        }
    ),
    "operator": frozenset(
        {
            "agents:read",
            "agents:write",
            "calls:read",
            "leads:read",
            "leads:write",
            "billing:read",
            "org:read",
            "org:manage",
            "kb:write",
            "admin:tenants",
            "admin:impersonate",
        }
    ),
    "superadmin": frozenset(
        {
            "agents:read",
            "agents:write",
            "calls:read",
            "calls:read_raw",
            "leads:read",
            "leads:write",
            "leads:dispatch",
            "billing:read",
            "org:read",
            "org:manage",
            "kb:write",
            "admin:tenants",
            "admin:impersonate",
            "ops:manage",
            "platform:config",
        }
    ),
}

# Permissions that mutate. An impersonating admin (D-22, read-only "view as client")
# is refused these even though its role grants them — no acting-as, ever.
MUTATING_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        "agents:write",
        "leads:write",
        "leads:dispatch",
        "org:manage",
        "kb:write",
        "ops:manage",
        "admin:tenants",
        # An impersonating admin (D-22, read-only "view as client") is refused this even
        # though `superadmin` grants it. A view-as session exists to SEE a client's
        # screens; nothing about that job needs to change what engine the platform dials
        # on. `GET /v1/ops/config` therefore also becomes invisible under impersonation,
        # which is correct and is why it is listed in `ADMIN_CONSOLE_GETS`
        # (tests/impersonation_reads_test.py): it is an admin-console read that
        # impersonation never reaches, not a view a client's screen depends on.
        "platform:config",
    }
)

# Routes exempt from the boot assertion: unauthenticated by design.
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/healthz",
    "/hooks",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/v1/auth/",
    # Authenticated but membership-less BY DESIGN: accepting an invitation is what
    # creates the membership a permission check would require (see current_identity).
    "/v1/invitations/accept",
)


# The attribute `auth.requires()` stamps on the dependency it returns, and the names of
# the dependencies that resolve an identity without checking a permission. Read by
# attribute rather than imported, because `core.auth` imports THIS module.
PERMISSION_ATTR = "calevate_permission"
IDENTITY_DEPENDENCIES: frozenset[str] = frozenset(
    {"current_any", "current_admin", "current_principal", "current_identity"}
)


def role_has(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


class MissingPolicyError(RuntimeError):
    """Boot-time failure: a route neither declares a permission nor is public."""


def iter_api_routes(app: FastAPI) -> Iterator[APIRoute]:
    """Every APIRoute the app will actually serve.

    FastAPI 0.140 stopped flattening `include_router` at mount time: `app.routes` now
    holds opaque `_IncludedRouter` wrappers that resolve lazily at request time. A
    naive `isinstance(route, APIRoute)` loop over `app.routes` therefore sees ONLY the
    four built-in doc routes and silently passes — which would turn the boot assertion
    below into decoration. So walk anything that exposes nested routes, wrapper or not.
    """
    seen: set[int] = set()

    def _walk(routes: Iterable[object]) -> Iterator[APIRoute]:
        for route in routes:
            if id(route) in seen:
                continue
            seen.add(id(route))
            if isinstance(route, APIRoute):
                yield route
                continue
            nested = getattr(route, "original_router", None) or getattr(route, "routes", None)
            if nested is not None:
                yield from _walk(getattr(nested, "routes", nested))

    yield from _walk(app.routes)


def route_enforcement(route: APIRoute) -> tuple[frozenset[str], bool]:
    """What a route ACTUALLY checks: (permissions verified, is an identity resolved).

    Walks the whole dependency tree, so a permission reached through a shared
    `Annotated[...]` alias or a router-level `dependencies=[...]` counts the same as
    one written on the handler.
    """
    permissions: set[str] = set()
    identified = False

    def _walk(dependant: Dependant) -> None:
        nonlocal identified
        call = dependant.call
        if call is not None:
            enforced = getattr(call, PERMISSION_ATTR, None)
            if isinstance(enforced, str):
                permissions.add(enforced)
                identified = True
            elif getattr(call, "__name__", "") in IDENTITY_DEPENDENCIES:
                identified = True
        for sub in dependant.dependencies:
            _walk(sub)

    _walk(route.dependant)
    return frozenset(permissions), identified


def assert_policy_registry_complete(app: FastAPI) -> None:
    """Called from `main.py` after routers are mounted. Every non-public route must
    DECLARE a permission in its `openapi_extra` and actually enforce it.

    Declaring is not enforcing. `permission_meta()` writes a string; the lock is
    `Depends(requires(...))`, and the two are written on separate lines of the same
    decorator — so the failure mode this guards is a route that carries the label with
    no lock behind it, or a label that names a different permission than the lock
    checks. Both read as protected in the OpenAPI schema, the generated TS client and
    any review that greps for `permission_meta`.
    """
    offenders: list[str] = []
    checked = 0
    for route in iter_api_routes(app):
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        checked += 1
        name = f"{sorted(route.methods or [])} {route.path}"
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        if not declared:
            offenders.append(name)
            continue
        enforced, identified = route_enforcement(route)
        if not identified:
            offenders.append(f"{name} declares {declared} but authenticates nobody")
        elif enforced and declared not in enforced:
            offenders.append(f"{name} declares {declared} but enforces {sorted(enforced)}")
    if checked == 0:
        # A registry that checks nothing is worse than no registry: it reads as a
        # passing guardrail. If route discovery ever breaks again, fail loudly.
        raise MissingPolicyError(
            "The RBAC policy registry found no routes to check. Route discovery is "
            "broken (see iter_api_routes) — fix it rather than removing this guard."
        )
    if offenders:
        raise MissingPolicyError(
            "Routes without a declared permission (BACKEND-PATTERNS §7): "
            + "; ".join(sorted(offenders))
            + ". Add `dependencies=[Depends(requires('<permission>'))]` and "
            "`openapi_extra=permission_meta('<permission>')`, or list the path in "
            "PUBLIC_PREFIXES with a reason."
        )


def permission_meta(permission: Permission) -> dict[str, object]:
    """OpenAPI extension the boot assertion reads; also documents the requirement in
    the generated TS client."""
    return {"x-calevate-permission": permission}


__all__ = [
    "IDENTITY_DEPENDENCIES",
    "MUTATING_PERMISSIONS",
    "PERMISSION_ATTR",
    "PUBLIC_PREFIXES",
    "ROLE_PERMISSIONS",
    "MissingPolicyError",
    "Permission",
    "assert_policy_registry_complete",
    "iter_api_routes",
    "permission_meta",
    "role_has",
    "route_enforcement",
]
