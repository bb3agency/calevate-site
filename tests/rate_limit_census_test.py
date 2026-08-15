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

from typing import Any

import pytest
from apps.api.core.middleware import RateLimitMiddleware
from apps.api.core.ratelimit import PROFILES, RULES, profile_for, resolve_rule
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
        # The five `/hooks` routes shared ONE bucket, so a lead-intake flood 429'd the
        # payment callback and the identity mirror. Three profiles now, and the census is
        # what keeps them three.
        ("/hooks/v1/ingest/{webhook_id}", "POST", "webhook_ingest"),
        ("/hooks/v1/ingest/meta/{webhook_id}", "POST", "webhook_ingest"),
        ("/hooks/v1/ingest/meta/{webhook_id}", "GET", "webhook_ingest"),
        ("/hooks/v1/razorpay", "POST", "webhook_payment"),
        ("/hooks/v1/clerk", "POST", "webhook_identity"),
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


def test_the_middleware_still_has_no_second_profile_table() -> None:
    """`RateLimitMiddleware` used to carry its own `PROFILES`/`EXEMPT` tuples. The census
    can only speak for the limits if there is one table, so the class must not grow
    another."""
    assert not hasattr(RateLimitMiddleware, "PROFILES")
    assert not hasattr(RateLimitMiddleware, "EXEMPT")
