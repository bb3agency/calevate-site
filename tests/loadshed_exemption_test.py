"""What survives a load shed, checked against the route table rather than against prose.

`ALWAYS_ALLOWED_PREFIXES` (core/loadshed.py) is matched by string prefix, so it does not
name routes — it names path SPACES, and whatever lands in one inherits the exemption
without anyone deciding that it should. That is the failure this file exists for, and it
had already happened: the list carried `/v1/auth` "so signing in survives maintenance"
while **no sign-in route exists in this API at all** (Clerk owns sessions, TRD §11). The
only route the prefix covered was `POST /v1/auth/signup`, which creates an organization,
an agent, an extraction schema and a set of retention policies — so the platform kept
manufacturing tenants in `maintenance` and `emergency`, the two modes that exist because
it cannot serve the tenants it already has.

The behaviour was not observable from outside, which is why it survived: `signup.py`
carries its own mode check and refuses first. That makes the defect a SHAPE defect —
an exemption pointing at nothing, with a second copy of the shedding rule in a route to
cover for it — and shape defects are the ones a test has to state, because nothing goes
red on its own.

Three assertions, in the order they close the class:

1. every exempt prefix names at least one live route (the staleness guard its sibling
   `impersonation_reads_test.py` already has for `ADMIN_CONSOLE_GETS`);
2. every exempt prefix has a recorded REASON, and the reason belongs to one of the three
   admissible kinds — observability, operator reachability, provider callbacks;
3. no publicly reachable write survives a shed unless it is a provider callback, which
   is the rule signup broke and the one a future `/v1/auth/anything` would break again.
"""

from __future__ import annotations

import pytest
from apps.api.core.loadshed import ALWAYS_ALLOWED_PREFIXES, LoadShedMode, PlatformStatus, is_shed
from apps.api.core.rbac import PUBLIC_PREFIXES, iter_api_routes
from apps.api.main import app
from starlette.routing import Route as StarletteRoute

#: Why each prefix is exempt, and which of the three admissible kinds it is.
#:
#: `observability` — the platform must stay readable while degraded.
#: `operator` — the human turning the shed off must not be locked out by it.
#: `callback` — a provider retry window is finite; a dropped webhook is data lost.
#:
#: A prefix with no entry here fails the second test, which is the point: adding one is
#: a decision about what the platform keeps serving when it has decided to serve less,
#: and it should cost a sentence.
EXEMPT_PREFIX_REASONS: dict[str, tuple[str, str]] = {
    "/healthz": ("observability", "liveness and readiness — how anyone knows it is shed"),
    "/hooks": (
        "callback",
        "engine, Clerk and Razorpay callbacks. A dropped engine webhook is a call whose "
        "lead never appears, and the sender's retry window does not wait for our "
        "maintenance to end",
    ),
    "/v1/ops": (
        "operator",
        "the platform switches, including the one that ENDS the shed. A load-shed mode "
        "that sheds its own off switch is an outage the operator cannot end",
    ),
    "/v1/admin": (
        "operator",
        "the admin console. Support has to be able to look at an account during an "
        "incident — that is when someone asks",
    ),
    "/openapi.json": (
        "observability",
        "the schema the typed console client is generated from, and the artefact the "
        "wiring guardrails read",
    ),
    "/docs": ("observability", "the schema, rendered. Same argument, outside prod only"),
}

#: The one exempt kind that may cover a publicly reachable WRITE, and why. Everything
#: else public and mutating is customer traffic, which is what shedding is for.
CALLBACK_KIND = "callback"


def _live_paths() -> set[str]:
    """Every path this app serves, API routes and Starlette ones alike.

    `iter_api_routes` yields `APIRoute`s only, and `/openapi.json` and `/docs` are plain
    `starlette.routing.Route`s — so a census built on it alone would report those two
    prefixes as naming nothing and fail for a reason that is about FastAPI's internals
    rather than about this list. The same detail is why `rbac.PUBLIC_PREFIXES` stopped
    listing them.
    """
    api = {route.path for route in iter_api_routes(app)}
    plain = {route.path for route in app.routes if isinstance(route, StarletteRoute)}
    return api | plain


def _mutating_public_routes() -> list[tuple[list[str], str]]:
    """(methods, path) for every route that is BOTH reachable without a permission check
    (`PUBLIC_PREFIXES`) and able to change state."""
    found = []
    for route in iter_api_routes(app):
        methods = sorted(route.methods or set())
        if not set(methods) & {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            found.append((methods, route.path))
    return found


def test_every_shed_exempt_prefix_names_a_live_route() -> None:
    """A prefix that matches nothing is not harmless — it is a claim about what the
    platform protects, kept alive by nobody checking.

    `/v1/auth` was that claim for as long as it was on the list: it read as "sign-in
    survives a shed" and delivered "tenant creation survives a shed", because the only
    route underneath it was `signup`. A rename or a deletion produces the same state
    silently, which is why this is asserted rather than reviewed.
    """
    live = _live_paths()
    stale = sorted(
        prefix
        for prefix in ALWAYS_ALLOWED_PREFIXES
        if not any(path.startswith(prefix) for path in live)
    )
    assert not stale, (
        f"ALWAYS_ALLOWED_PREFIXES exempts path spaces with no routes in them: {stale}. "
        "Delete the entry — an exemption for a surface that does not exist protects "
        "nothing and misdescribes what does."
    )


def test_every_shed_exempt_prefix_records_why_it_is_exempt() -> None:
    """The list and the reasons are the same list, in both directions.

    An unexplained prefix is how `/v1/auth` stayed: everyone reading it supplied their
    own justification ("auth, obviously") and nobody checked it against the route table.
    """
    listed = set(ALWAYS_ALLOWED_PREFIXES)
    explained = set(EXEMPT_PREFIX_REASONS)
    assert listed == explained, (
        f"unexplained prefixes: {sorted(listed - explained)}; "
        f"explanations for prefixes that are no longer exempt: {sorted(explained - listed)}"
    )
    for prefix, (kind, reason) in EXEMPT_PREFIX_REASONS.items():
        assert kind in {"observability", "operator", CALLBACK_KIND}, f"{prefix}: {kind}"
        assert reason.strip(), prefix


def test_no_public_write_survives_a_shed_unless_it_is_a_provider_callback() -> None:
    """The rule that would have caught signup on the day it was written.

    A route that is publicly reachable AND mutating is, by construction, work an
    unauthenticated (or membership-less) caller can make the platform do. Shedding
    exists to stop exactly that when the platform is degraded. The single admissible
    exception is a provider callback, whose sender is not a user and whose retry window
    is finite — `/hooks`, and it says so in `EXEMPT_PREFIX_REASONS`.

    Stated over the route table rather than over the prefix list because the prefix list
    is not where the next instance will appear: it will be a new route landing under a
    prefix somebody already justified for a different reason.
    """
    offenders = []
    for methods, path in _mutating_public_routes():
        exempting = [p for p in ALWAYS_ALLOWED_PREFIXES if path.startswith(p)]
        if not exempting:
            continue
        # `.get`, not `[...]`: a prefix added to the list and not to the reasons must
        # fail HERE with the offending route named, not with a KeyError that says
        # nothing about which write escaped. The missing reason is its own test.
        kinds = {EXEMPT_PREFIX_REASONS.get(p, ("unexplained", ""))[0] for p in exempting}
        if kinds == {CALLBACK_KIND}:
            continue
        offenders.append(f"{methods} {path} exempted by {exempting}")
    assert not offenders, (
        "publicly reachable writes that survive a load shed: "
        f"{offenders}. Shedding exists to stop exactly this work while the platform is "
        "degraded; only a provider callback may outrank it."
    )


@pytest.mark.parametrize("mode", ["reduced", "emergency", "maintenance"])
def test_signup_is_shed_like_any_other_expensive_write(mode: LoadShedMode) -> None:
    """The instance, named. `POST /v1/auth/signup` writes an organization, an agent, an
    extraction schema and several retention policies — the single most expensive write
    an outsider can trigger, and the one that adds an account for a platform that has
    just declared it cannot serve the accounts it has.

    Asserted on `is_shed` rather than over HTTP deliberately: the route ALSO refuses
    non-normal modes itself (`tenancy/signup.py::assert_signup_open`), so an HTTP
    assertion would pass identically with the exemption restored — a test that cannot
    tell the fix from the defect. This one fails the moment `/v1/auth` returns to the
    list.
    """
    status = PlatformStatus(mode=mode, outbound_halted=False)
    assert is_shed(status, path="/v1/auth/signup", method="POST")


def test_the_operator_surface_and_provider_callbacks_survive_even_maintenance() -> None:
    """The control on the narrowing: `maintenance` sheds reads as well as writes, so
    this is where an over-eager trim would show up as an operator locked out of the
    switch that ends the incident."""
    maintenance = PlatformStatus(mode="maintenance", outbound_halted=True)
    for path, method in (
        ("/healthz", "GET"),
        ("/healthz/ready", "GET"),
        ("/v1/ops/platform", "POST"),
        ("/v1/admin/tenants", "GET"),
        ("/hooks/v1/clerk", "POST"),
        ("/openapi.json", "GET"),
    ):
        assert not is_shed(maintenance, path=path, method=method), f"{method} {path} was shed"

    # And the client realm is shed, which is what `maintenance` MEANS. Without this the
    # test above would keep passing if the whole guard were disabled.
    assert is_shed(maintenance, path="/v1/leads", method="GET")
    assert is_shed(maintenance, path="/v1/agents", method="GET")


def test_normal_mode_sheds_nothing_at_all() -> None:
    """The other control: none of the above is reachable in the mode the platform spends
    its life in, exemption or no exemption."""
    normal = PlatformStatus(mode="normal", outbound_halted=False)
    for path, method in (
        ("/v1/auth/signup", "POST"),
        ("/v1/leads", "POST"),
        ("/v1/agents", "GET"),
    ):
        assert not is_shed(normal, path=path, method=method), f"{method} {path} was shed"
