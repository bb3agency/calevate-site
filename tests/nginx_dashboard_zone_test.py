"""The dashboards' edge zones are never tighter than the app's own limits.

The app answers an over-limit request with problem+json, CORS headers and Retry-After, so the
page can say what happened and wait. nginx's own 429 carries no CORS header, so the browser
reports it as a network error and the page says no reply arrived. When the edge was the
tighter limit (`client_api` 120r/m, burst 30), one hard refresh of the client dashboard
crossed it, the retries kept it crossed, and the whole page failed to load.
"""

from __future__ import annotations

from apps.api.core.ratelimit import PROFILES
from tests.edge_route_policy_test import Location, block_for
from tests.nginx_worker_zone_test import _zone_rates_per_minute

#: Requests one dashboard load may fire at once, with each read's two retries, before the
#: app's own limiter should be the one to refuse.
DASHBOARD_LOAD = 100


def _api_location(modifier: str, path: str) -> Location:
    found = [
        loc for loc in block_for("api").locations if loc.modifier == modifier and loc.path == path
    ]
    assert len(found) == 1, f"the api vhost has no `location {modifier} {path}`"
    return found[0]


def test_the_client_edge_is_looser_than_the_app() -> None:
    location = _api_location("", "/")
    assert location.limit_zone == "client_api"
    assert _zone_rates_per_minute()["client_api"] > PROFILES["client_api"].per_client
    assert location.limit_burst >= DASHBOARD_LOAD


def test_the_admin_edge_is_looser_than_the_app() -> None:
    location = _api_location("^~", "/v1/admin/")
    assert location.limit_zone == "admin_api"
    assert _zone_rates_per_minute()["admin_api"] > PROFILES["admin_api"].per_client
    assert location.limit_burst >= DASHBOARD_LOAD
