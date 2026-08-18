"""Every route has a limit, every limit has a route (plan Part 3, item d).

nginx already applies per-real-IP zones and a body cap, and that is a real defence this
does not replace. What the edge structurally cannot do is per-TENANT, per-family and
cost-weighted — so `core/ratelimit.py` adds those, and this file is what stops the table
from rotting the two ways a table like it always rots:

- **a new route born unlimited.** Every route in `rbac.iter_api_routes(app)` must resolve
  a rule. A route mounted under a path family nobody profiled would otherwise be limited
  by nothing but the edge.
- **a cost weight that stopped matching anything.** Every rule must be reached by at
  least one live route. Rename `/v1/leads/export.csv` and the 6/min ceiling on the
  20,000-row export becomes a fossil that reads like protection.

Plus the property that makes "most specific wins" a single answer rather than a race:
no two rules may tie at the top for the same route.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from apps.api.core.middleware import RateLimitMiddleware
from apps.api.core.ratelimit import PROFILES, RULES, Rule, profile_for, resolve_rule
from apps.api.core.rbac import iter_api_routes
from apps.api.main import app

#: (path template, method) for everything the app will actually serve. The route
#: TEMPLATE — `/v1/leads/{lead_id}` — because that is what a census can enumerate; the
#: same patterns match the concrete path the middleware sees, which is the point of
#: compiling `{lead_id}` and a real id to the same single-segment wildcard.
LIVE_ROUTES: list[tuple[str, str]] = sorted(
    {
        (route.path, method.upper())
        for route in iter_api_routes(app)
        for method in route.methods
        if method.upper() != "HEAD"
    }
)


def _all_served_paths() -> set[str]:
    """Every path the app serves, INCLUDING the ones `iter_api_routes` does not yield.

    FastAPI mounts `/docs`, `/redoc` and `/openapi.json` as plain `starlette.routing.Route`
    objects, so a rule covering them looks dead to a census built only from `APIRoute`.
    They are served outside prod (`core/bootstrap.py`), and the limiter still has to know
    what they are in the environments that do serve them.
    """
    found: set[str] = set()

    def _walk(routes: Any) -> None:
        for route in routes:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                found.add(path)
            nested = getattr(route, "original_router", None) or getattr(route, "routes", None)
            if nested is not None:
                _walk(getattr(nested, "routes", nested))

    _walk(app.routes)
    return found


def test_no_route_is_born_unlimited() -> None:
    unprofiled = [
        f"{method} {path}" for path, method in LIVE_ROUTES if resolve_rule(path, method) is None
    ]
    assert not unprofiled, (
        "these routes match no rate-limit rule and are bounded only by nginx: "
        f"{unprofiled} — add a rule to core/ratelimit.RULES"
    )


def test_every_rule_still_matches_something() -> None:
    """A rule that matches nothing is worse than no rule: it reads as protection.

    Checked against every path the app serves rather than against `iter_api_routes`
    alone, so the doc-route exemptions count as reached.
    """
    served = _all_served_paths()
    methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    dead = [
        rule.pattern
        for rule in RULES
        if not any(rule.matches(path, method) for path in served for method in methods)
    ]
    assert not dead, f"rate-limit rules that match no live route: {dead}"


def test_the_most_specific_rule_is_always_a_single_answer() -> None:
    """Resolution must not depend on declaration order, so it must not be able to tie."""
    ambiguous: list[str] = []
    for path, method in LIVE_ROUTES:
        matches = [rule for rule in RULES if rule.matches(path, method)]
        if not matches:
            continue
        top = max(rule.specificity for rule in matches)
        if sum(1 for rule in matches if rule.specificity == top) > 1:
            winners = [rule.pattern for rule in matches if rule.specificity == top]
            ambiguous.append(f"{method} {path}: {winners}")
    assert not ambiguous, f"two rules tie for the same route: {ambiguous}"


def test_every_rule_names_a_profile_that_exists() -> None:
    assert {rule.profile for rule in RULES} <= set(PROFILES)


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        # The `/hooks` routes shared ONE bucket, so a lead-intake flood 429'd the
        # payment callback too. Two profiles now, and the census is what keeps them two —
        # a third, `webhook_identity`, went with the Clerk mirror (D-177).
        ("/hooks/v1/ingest/{webhook_id}", "POST", "webhook_ingest"),
        ("/hooks/v1/ingest/meta/{webhook_id}", "POST", "webhook_ingest"),
        ("/hooks/v1/ingest/meta/{webhook_id}", "GET", "webhook_ingest"),
        ("/hooks/v1/razorpay", "POST", "webhook_payment"),
        # Cost weighting: the expensive route and its cheap neighbour under one prefix.
        ("/v1/leads/export.csv", "GET", "bulk_read"),
        ("/v1/leads/{lead_id}", "GET", "client_api"),
        ("/v1/leads/bulk", "POST", "bulk_write"),
        ("/v1/leads/{lead_id}/call", "POST", "costly"),
        ("/v1/admin/tenants/{tenant_id}/invoice", "GET", "bulk_read"),
        ("/v1/admin/tenants/{tenant_id}/credits", "GET", "admin_api"),
        ("/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish", "POST", "costly"),
        ("/v1/ops/secrets/{key}", "PUT", "admin_api"),
        ("/v1/ops/secrets/{key}/test", "POST", "costly"),
        ("/v1/auth/signup", "POST", "auth"),
        ("/healthz/ready", "GET", "exempt"),
    ],
)
def test_named_routes_land_in_the_profile_they_were_weighted_for(
    path: str, method: str, expected: str
) -> None:
    assert profile_for(path, method).name == expected


def test_a_concrete_path_and_its_template_resolve_identically() -> None:
    """The middleware sees `/v1/leads/018f.../call` before routing; the post-auth tenant
    charge sees `/v1/leads/{lead_id}/call` after it. One table has to answer both, or the
    two halves of one limit would disagree about which limit it is."""
    for template, concrete, method in [
        ("/v1/leads/{lead_id}/call", "/v1/leads/018f8d3e-0000-7000-8000-000000000000/call", "POST"),
        ("/v1/leads/{lead_id}", "/v1/leads/018f8d3e-0000-7000-8000-000000000000", "GET"),
        ("/hooks/v1/ingest/{webhook_id}", "/hooks/v1/ingest/wh_abc123", "POST"),
        (
            "/v1/admin/tenants/{tenant_id}/invoice",
            "/v1/admin/tenants/018f8d3e-0000-7000-8000-000000000000/invoice",
            "GET",
        ),
    ]:
        assert profile_for(template, method) is profile_for(concrete, method), template


def test_the_client_profile_gives_a_tenant_more_room_than_one_of_its_users() -> None:
    """A tenant ceiling at or below the per-caller one would make the per-caller limit
    dead code — and the whole reason for the tenant dimension is that several people in
    one SMB share one NAT address."""
    client_api = PROFILES["client_api"]
    assert client_api.per_tenant is not None
    assert client_api.per_tenant > client_api.per_client


def test_every_non_exempt_profile_actually_limits_something() -> None:
    for name, profile in PROFILES.items():
        if name == "exempt":
            assert profile.per_client == 0 and profile.per_tenant is None
            continue
        assert profile.per_client > 0, f"{name} limits nothing"
        assert profile.window_s > 0


#: Every cost-weighted rule declares the methods it applies to; no family rule does. That
#: is the only structural difference between "this family of paths" and "this route costs
#: more than its family", and it is what lets the assertion below tell them apart without
#: a second list somebody has to keep in step.
def _cost_rules() -> list[Rule]:
    return [rule for rule in RULES if rule.methods]


def test_a_cost_weight_is_tighter_than_the_family_it_overrides() -> None:
    """THE PROPERTY A CENSUS CANNOT SEE. Its three assertions are about PRESENCE: every
    route resolves a rule, every rule reaches a route, no two rules tie. All three pass
    for `Rule("/v1/leads/export.csv", "admin_api")` — a real rule, matching a real route,
    winning cleanly — which would put the 20,000-row export on 300/min instead of 6 and
    read, in the table, exactly like protection.

    So: a rule that exists to make a route MORE expensive than its family must actually be
    tighter than what that route would resolve to without it, on both dimensions it
    declares. Computed by removing the rule and re-resolving, so it is the real resolution
    order under test and not a restatement of the table.

    Deliberately NOT applied to family rules: `admin_api` (300) is looser than `client_api`
    (240) on purpose — the operator console fans out harder and there are few operators —
    and a blanket "more specific means tighter" would forbid that. The distinction is
    argued in `core/ratelimit.RULES`; here it is `Rule.methods`.
    """
    slack: list[str] = []
    for rule in _cost_rules():
        weighted = PROFILES[rule.profile]
        others = tuple(other for other in RULES if other is not rule)
        method = next(iter(rule.methods or ()))
        # The concrete-ish path this pattern stands for, so the fallback resolves the way
        # a live request would: `*` is any segment, `**` is any tail.
        path = "/" + "/".join(
            "x" if segment in ("*", "**") else segment
            for segment in rule.pattern.split("/")
            if segment
        )
        candidates = [other for other in others if other.matches(path, method)]
        if not candidates:
            slack.append(f"{rule.pattern}: no family rule underneath it")
            continue
        family = PROFILES[max(candidates, key=lambda r: r.specificity).profile]
        if weighted.per_client >= family.per_client:
            slack.append(
                f"{method} {rule.pattern} → {weighted.name} ({weighted.per_client}/min) is "
                f"not tighter than {family.name} ({family.per_client}/min)"
            )
        if (
            family.per_tenant is not None
            and weighted.per_tenant is not None
            and weighted.per_tenant >= family.per_tenant
        ):
            slack.append(
                f"{method} {rule.pattern} → {weighted.name} tenant ceiling "
                f"({weighted.per_tenant}) is not tighter than {family.name} "
                f"({family.per_tenant})"
            )
    assert not slack, "cost weights that cost nothing: " + "; ".join(slack)


#: The largest ceilings this platform declares, and which profile establishes each.
#: `per_client` — `webhook_ingest`, sized for Meta delivering every tenant's leads from
#: Facebook's own addresses. `per_tenant` — `client_api`, ~50 concurrent users of one SMB.
MAX_PER_CLIENT = 600
MAX_PER_TENANT = 900


def test_no_profile_is_so_loose_that_it_is_a_limit_in_name_only() -> None:
    """The other way a census stays green while the limits stop meaning anything: raise
    the number. The cheapest way to make a 429 go away is to edit one integer, and every
    other assertion in this file survives that edit — coverage of a table says nothing
    about the values in it.

    A RATCHET, in the manner of `scripts/check_coverage_ratchet`, not a claim that these
    two numbers are correct: they are today's maxima, so exceeding one means editing this
    file, which is a deliberate act with a diff and a reviewer rather than a number
    quietly growing until the profile stops bounding anything.
    """
    loose = {
        name: (profile.per_client, profile.per_tenant)
        for name, profile in PROFILES.items()
        if profile.per_client > MAX_PER_CLIENT or (profile.per_tenant or 0) > MAX_PER_TENANT
    }
    assert not loose, (
        f"profiles above the platform's declared ceilings "
        f"({MAX_PER_CLIENT}/caller, {MAX_PER_TENANT}/tenant): {loose} — raising one is a "
        "decision-log entry, not a test edit"
    )


def test_the_credential_fingerprint_has_exactly_one_caller() -> None:
    """`ratelimit.fingerprint` is for the ONE bucket subject that is a live credential.

    The signup quota used to hash both of its subjects with it on a privacy argument that
    does not hold: an unkeyed digest of an IPv4 address is an encoding of a 32-bit space,
    the same address is written in the clear by this module's own caller dimension, and
    SEC-COMP §5 requires it kept permanently in `audit_log.ip`. The hash was buying
    nothing and the comment above it claimed otherwise, which is the more expensive half.

    So the rule is "hash credentials, not identifiers", and this is what keeps it one
    rule. A bare `fingerprint(...)` call anywhere but the token path is the next author
    reaching for it because the name sounds like privacy.
    """
    root = Path(__file__).resolve().parents[1] / "apps"
    callers = {
        path.relative_to(root.parent).as_posix()
        for path in root.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fingerprint"
    }
    assert callers == {"apps/api/core/middleware.py"}, (
        f"`ratelimit.fingerprint` is called from {sorted(callers)}. It pseudonymises a "
        "live credential; every other bucket subject goes through `bucket_subject`. See "
        "its docstring and `tenancy/signup.py::_consume`."
    )


def test_the_middleware_still_has_no_second_profile_table() -> None:
    """`RateLimitMiddleware` used to carry its own `PROFILES`/`EXEMPT` tuples. The census
    can only speak for the limits if there is one table, so the class must not grow
    another."""
    assert not hasattr(RateLimitMiddleware, "PROFILES")
    assert not hasattr(RateLimitMiddleware, "EXEMPT")
