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
    "/v1/admin/operators": (
        "the operator allowlist — who may use the console at all. `admin:operators` is "
        "superadmin-only and is in MUTATING_PERMISSIONS, so a view-as session cannot "
        "reach it; that is correct rather than a cost, because this list has no "
        "client-realm counterpart at all. A support person inside a client's account is "
        "looking at that client's screens, and none of them names a Calevate operator."
    ),
    "/v1/admin/numbers/available": (
        "the voice platform's own for-sale inventory (D-537) — an ops purchasing screen, "
        "and the one list that is not about any client at all: it is what OUR vendor "
        "account could buy, priced in the vendor's USD. There is no client-realm "
        "counterpart to be looking at alongside it — the client-realm numbers route is "
        "`POST /v1/numbers/purchase` and it has no GET — so a view-as session never "
        "reaches this and loses nothing by not reaching it"
    ),
    "/v1/admin/numbers/tenants/{tenant_id}": (
        "what each of one client's numbers COSTS US (D-537) — `monthly_rental_usd` is "
        "our supplier cost basis, the same class of fact as /v1/ops/model-prices and "
        "/v1/ops/fx-rate, and it is not a view of a client's own screen. It is entered "
        "with an admin token for an account named in the path and it WRITES an "
        "`admin_tenant_read` row for that reason (SEC-COMP §5, D-482 L-1); an "
        "impersonated session is a client dashboard, which has no screen showing what "
        "Calevate pays a vendor"
    ),
    "/v1/copilot/conversation": (
        "ONE PERSON'S conversation with the assistant (D-540), and the exemption rests on "
        "a fact about the KEY rather than on a judgement about support. This route is "
        "scoped on `principal.user_id`, and inside a D-22 view-as session that value is "
        "the OPERATOR'S `admin_users.id` (`core/auth.py`: the impersonated principal "
        "carries `user_id=admin_id` with the client's `tenant_id`). "
        "`copilot_conversation_turns.user_id` is a foreign key to `users`, so an admin id "
        "can never appear in it: an impersonated read returns an EMPTY page whatever "
        "permission guards it. Giving this a read permission would therefore buy a "
        "support person nothing — the same empty page, one round trip later — because "
        "the thing they would want to see is keyed on a person they are not. What a "
        "support person can see of an assistant answer is what has always been "
        "reviewable: the `copilot.ask` audit row, which names the screen, the spend and "
        "any change the answer made. The turns themselves are the client's own chat, they "
        "are cleared when that client's last session ends, and no screen in either "
        "console has ever displayed another person's"
    ),
    "/v1/admin/copilot/conversation": (
        "the OPERATOR'S own conversation with the admin assistant (D-540) — the same "
        "shape as the entry above and a shorter argument: it is keyed on the operator "
        "asking, it is an admin-console surface with no client-realm counterpart at all, "
        "and a client dashboard has no screen showing an operator's notes to themselves"
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
    "/v1/ops/model-prices": (
        "the founder's attested per-model prices (D-459) — superadmin ops surface, "
        "gated on platform:config for the same reason /v1/ops/config is. A view-as "
        "session is on a CLIENT dashboard, never the ops console, so it is never "
        "reached through impersonation; and a price is OUR cost basis, not the "
        "client's to see"
    ),
    "/v1/ops/dashboard-data-use": (
        "which LLM legs the in-app assistant may run on, and the operator attestation "
        "behind each (D-477) — superadmin ops surface, gated on platform:config for the "
        "same reason /v1/ops/model-prices is. A view-as session is on a CLIENT dashboard, "
        "never the ops console. Note what a client DOES see of this fact and where: when "
        "their own model cannot serve the assistant they are told so in their own terms "
        "by the answer's disclosure and by `assist_unavailable`'s client remediation, "
        "which is the whole of what is theirs to know — the vendor account, the tier and "
        "the ground behind it are OURS"
    ),
    "/v1/ops/fx-rate": (
        "the USD/INR rate vendor costs are converted at, and how fresh it is (D-475) — "
        "superadmin ops surface, gated on platform:config for /v1/ops/model-prices' "
        "reason and never reached from a client dashboard. It is the same class of fact "
        "as the price above: OUR cost basis and OUR feed's health, not a view of any one "
        "client. What a client sees of this number is the rupee amount on their own "
        "invoice, which is already fully reachable through impersonation"
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
