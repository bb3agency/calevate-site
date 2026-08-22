"""A read must not require a permission that read-only impersonation refuses.

D-22 makes "view as client" read-only by refusing every permission in
`MUTATING_PERMISSIONS`, which is right. The bug that keeps recurring is on the other
side of that rule: a GET endpoint declared with a MUTATING permission is invisible to
the support person looking at the client's screen — and it is invisible in exactly the
moment support is needed, because the views that explain a refusal (why is the launch
button disabled, did my form reach you, did the webhook reach my CRM) are the ones that
kept getting gated on the permission to ACT rather than the permission to LOOK.

This has now been found three times in three different modules — the KB approval queue
(`kb:write` on a read), the callback-eligibility check and the integration views. Three
occurrences of one mistake is not three mistakes; it is a missing rule. So this file
asserts the RULE over the whole route table rather than the three instances, and a new
GET that repeats it fails here on the day it is written.
"""

from __future__ import annotations

from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes
from apps.api.main import app

# GETs that legitimately require a mutating permission, each with the reason it is not
# an instance of the bug. The test asserts these are STILL exempt-worthy by requiring
# every entry to actually exist — a stale exemption for a deleted route is how an
# allowlist quietly becomes a hole.
#
# The common thread: these are admin-CONSOLE surfaces, reached with an admin token and
# no `X-Impersonate-Org` header. Impersonation never touches them, so gating them on a
# mutating permission costs nobody a view.
ADMIN_CONSOLE_GETS: dict[str, str] = {
    "/v1/admin/tenants": "the client directory — admin console, never impersonated",
    "/v1/admin/tenants/{tenant_id}": "one client's admin record, same surface",
    "/v1/admin/tenants/{tenant_id}/invoice": "an ops document about a client, not a client view",
    "/v1/admin/tenants/{tenant_id}/credits": "the credit ledger as ops reads it",
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt": "prompt history, admin only",
    "/v1/admin/organizations/{org_id}/llm-defaults": (
        "which language model one client's agents run — admin console, and the ONE case "
        "in this table where the client's own view of the same fact is fully reachable "
        "through impersonation. `GET /v1/organization/llm-defaults` is `org:read`, which "
        "D-22 admits, so a support person in a view-as session sees exactly the screen "
        "the client is looking at. This path is the operator's door to the same resource "
        "for an account they are NOT impersonating — named in the path, entered with an "
        "admin token — so hiding it from impersonation costs a support person nothing "
        "(D-454)"
    ),
    "/v1/ops/platform": "the platform switches — superadmin surface",
    "/v1/ops/audit/verify": "the audit chain check — superadmin surface",
    "/v1/ops/engine-latency": (
        "the fleet-wide engine latency board (D-445) — superadmin surface. It aggregates "
        "every tenant's calls to answer one question about OUR infrastructure (what the "
        "US-hosted orchestrator costs a South-India model in time-to-first-token), so it "
        "is not a view of any one client and there is nothing here for a support person "
        "to be looking at ALONGSIDE a client. Impersonation shows a client's own screen; "
        "this screen has no client-realm counterpart to show."
    ),
    "/v1/ops/secrets": (
        "installed credentials — superadmin surface, and the one list a view-as session "
        "must never reach. It returns no plaintext at all, so hiding it from "
        "impersonation costs a support person nothing"
    ),
    "/v1/ops/secrets/kek": (
        "key-management state — superadmin surface, and it names no credential at all: "
        "a KEK fingerprint and two counts"
    ),
    "/v1/ops/dnc/global": (
        "the platform-wide suppression list — superadmin surface, and nothing a client "
        "screen depends on: a global entry already appears in the client's own "
        "`GET /v1/dnc` (in full since D-436, `removable: false`), which is what a "
        "view-as session sees. This is the ops view of what we refuse to dial for EVERY "
        "tenant"
    ),
    "/v1/ops/config": (
        "platform configuration — superadmin surface, and the one thing a view-as "
        "session has no business seeing: it is OUR deployment's settings, not the "
        "client's. Nothing on a client screen depends on it"
    ),
}


def _get_routes() -> list[tuple[str, str]]:
    """(path, declared permission) for every GET-only route that declares one."""
    found: list[tuple[str, str]] = []
    for route in iter_api_routes(app):
        if route.methods != {"GET"} and route.methods != {"GET", "HEAD"}:
            continue
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        if isinstance(declared, str):
            found.append((route.path, declared))
    return found


def test_no_read_is_gated_on_a_permission_impersonation_refuses() -> None:
    offenders = [
        (path, permission)
        for path, permission in _get_routes()
        if permission in MUTATING_PERMISSIONS and path not in ADMIN_CONSOLE_GETS
    ]
    assert not offenders, (
        "These GETs require a MUTATING permission, so D-22 hides them from read-only "
        "impersonation — support cannot see what the client is looking at: "
        f"{offenders}. Use the matching read permission (leads:read / org:read / "
        "agents:read), or add the path to ADMIN_CONSOLE_GETS with the reason it is "
        "never reached through impersonation."
    )


def test_every_admin_console_exemption_still_names_a_real_route() -> None:
    """A stale exemption is how an allowlist becomes a hole: the path gets renamed, the
    entry stays, and the next route to land on that path inherits a pass it never
    earned."""
    live = {path for path, _ in _get_routes()}
    stale = sorted(set(ADMIN_CONSOLE_GETS) - live)
    assert not stale, f"ADMIN_CONSOLE_GETS names routes that no longer exist: {stale}"


def test_the_views_that_explain_a_refusal_are_readable() -> None:
    """The three that were actually broken, pinned by name.

    The rule test above would catch a regression on any of them, but these three are
    worth naming: each is the view a client or a support person opens precisely when
    something has already gone wrong, which is the worst possible moment to answer with
    a 403.
    """
    permissions = dict(_get_routes())
    for path in (
        "/v1/calls/{call_id}/callback",
        "/v1/lead-sources/activity",
        "/v1/integrations/deliveries",
        # The fourth: it EXISTS to explain a disabled launch button, and it used to
        # demand the permission to place calls in order to say why you cannot.
        "/v1/campaigns/{campaign_id}/launch-check",
    ):
        assert path in permissions, f"{path} is missing — did it move?"
        assert permissions[path] not in MUTATING_PERMISSIONS, (
            f"{path} explains why something is blocked; it must be readable by someone "
            "who may only look."
        )


def test_the_launch_check_preview_is_readable_without_the_power_to_dial() -> None:
    """`GET /v1/campaigns/{id}/launch-check` now asks for `leads:read`, while
    `POST /launch` keeps `leads:dispatch`.

    That split is the rule in one endpoint pair: reading why you cannot dial is not the
    authority to dial. It was carried here as a strict xfail until the permission swap
    landed; the path is now inside the rule test above and named in the list of
    refusal-explaining views, so nothing about it depends on an exemption.
    """
    permissions = dict(_get_routes())
    launch_check = "/v1/campaigns/{campaign_id}/launch-check"
    assert permissions[launch_check] == "leads:read", permissions[launch_check]
    assert launch_check not in ADMIN_CONSOLE_GETS, "it is a client view, not an ops one"
