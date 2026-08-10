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

from typing import Literal

from fastapi import FastAPI
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
)


def role_has(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


class MissingPolicyError(RuntimeError):
    """Boot-time failure: a route neither declares a permission nor is public."""


def assert_policy_registry_complete(app: FastAPI) -> None:
    """Called from `main.py` after routers are mounted. Every non-public route must
    carry `permission` in its `openapi_extra` (set by the `requires()` dependency)."""
    offenders: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        if not declared:
            offenders.append(f"{sorted(route.methods or [])} {route.path}")
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
    "MUTATING_PERMISSIONS",
    "PUBLIC_PREFIXES",
    "ROLE_PERMISSIONS",
    "MissingPolicyError",
    "Permission",
    "assert_policy_registry_complete",
    "permission_meta",
    "role_has",
]
