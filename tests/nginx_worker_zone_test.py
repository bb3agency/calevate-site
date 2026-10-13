"""The voice engine's door has its own edge zone, never tighter than the app's (PG8).

`/v1/worker/**` used to fall through to the api vhost's `location /`, i.e. `client_api`
at 120r/m per IP. The engine calls from a handful of shared egress addresses, so that was a
fleet-wide ceiling in front of an app that budgets the same traffic at 600/min per caller.
A refused in-call action is a caller told the wrong thing.
"""

from __future__ import annotations

from apps.api.core.ratelimit import profile_for
from tests.edge_route_policy_test import _CONF_ZONE, RATE_ZONES_TEMPLATE, Location, block_for

#: One path per kind of engine call on the door: an in-call action and a caller lookup.
WORKER_PATHS = ("/v1/worker/engine-actions/thinnest/opt-out", "/v1/worker/engine-lookups/thinnest")


def _zone_rates_per_minute() -> dict[str, int]:
    text = RATE_ZONES_TEMPLATE.read_text(encoding="utf-8")
    return {
        name: int(number) * (60 if unit == "s" else 1)
        for name, number, unit in _CONF_ZONE.findall(text)
    }


def _worker_location() -> Location:
    found = [
        loc
        for loc in block_for("api").locations
        if loc.modifier == "^~" and loc.path == "/v1/worker/"
    ]
    assert len(found) == 1, "the api vhost has no `location ^~ /v1/worker/`"
    return found[0]


def test_the_worker_door_is_counted_in_its_own_zone() -> None:
    location = _worker_location()
    assert location.limit_zone == "worker"
    assert location.proxies


def test_the_edge_is_never_the_tighter_limit_on_the_worker_door() -> None:
    """The app counts every engine call against one per-caller bucket, so one egress
    address can legitimately spend all of it. The edge rate must cover it."""
    profiles = [profile_for(path, "POST") for path in WORKER_PATHS]
    assert {profile.name for profile in profiles} == {"worker_api"}
    assert _zone_rates_per_minute()["worker"] >= max(p.per_client for p in profiles)
