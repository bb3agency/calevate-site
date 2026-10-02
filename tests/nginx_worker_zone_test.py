"""The voice worker's door has its own edge zone, never tighter than the app's (PG8).

`/v1/worker/**` used to fall through to the api vhost's `location /`, i.e. `client_api`
at 120r/m per IP. Every worker container arrives from Pipecat Cloud's shared egress, so
that was a fleet-wide ceiling, and it sat in front of an app that budgets the same traffic
at two 600/min buckets per caller. A refused settlement is the call's post-call work lost.
"""

from __future__ import annotations

from apps.api.core.ratelimit import profile_for
from tests.edge_route_policy_test import _CONF_ZONE, RATE_ZONES_TEMPLATE, Location, block_for

#: One path per app bucket on the worker's door: the settlement and the speaking state.
WORKER_PATHS = ("/v1/worker/calls/x/settlement", "/v1/worker/calls/x/speaking")


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
    """The app's two worker buckets are per caller and independent, so one egress address
    can legitimately spend both. The edge rate must cover their sum."""
    profiles = [profile_for(path, "POST") for path in WORKER_PATHS]
    assert sorted(profile.name for profile in profiles) == ["worker_api", "worker_live"]
    assert _zone_rates_per_minute()["worker"] >= sum(p.per_client for p in profiles)
