"""What survives a load shed, checked against the route table rather than against prose.

`ALWAYS_ALLOWED_PREFIXES` (core/loadshed.py) is matched by string prefix, so it does not
name routes — it names path SPACES, and whatever lands in one inherits the exemption
without anyone deciding that it should. That is the failure this file exists for, and it
had already happened: the list carried `/v1/auth` "so signing in survives maintenance"
back when Clerk owned sessions (TRD §11) and this API had no sign-in route to protect.
The only route the prefix covered was `POST /v1/auth/signup`, which creates an
organization, an agent, an extraction schema and a set of retention policies — so the
platform kept manufacturing tenants in `maintenance` and `emergency`, the two modes that
exist because it cannot serve the tenants it already has.

The behaviour was not observable from outside, which is why it survived: `signup.py`
carries its own mode check and refuses first. That makes the defect a SHAPE defect —
an exemption pointing at nothing, with a second copy of the shedding rule in a route to
cover for it — and shape defects are the ones a test has to state, because nothing goes
red on its own.

**AND THEN THE OPPOSITE DEFECT ARRIVED, from the same sentence.** D-177 brought sessions
in-house, so `/v1/auth/{realm}/login` and `/v1/auth/{realm}/login/otp` are real mutating
routes now — and with nothing exempting them, every shed mode locked out any operator who
was not already holding a live cookie, including from signing in to END the shed. The
`/v1/ops` exemption kept the off switch reachable by nobody. `loadshed.ALWAYS_ALLOWED_PATHS`
is the by-name exemption that closes it, and the assertions below cover BOTH registries —
a stale prefix and an over-broad one are the same class read from opposite ends.

Four assertions, in the order they close the class:

1. every exempt prefix names at least one live route, and every exempt PATH is a live
   route exactly (the staleness guard its sibling `impersonation_reads_test.py` already
   has for `ADMIN_CONSOLE_GETS`);
2. every exemption of either kind has a recorded REASON, and the reason belongs to one of
   the four admissible kinds — observability, operator reachability, provider callbacks,
   and the door an operator signs in through;
3. no publicly reachable write survives a shed unless it is a provider callback or the
   door, which is the rule signup broke and the one a future `/v1/auth/anything` would
   break again — the door qualifies only by EXACT name, never by inheriting a prefix;
4. the door is actually open, in every mode that sheds, and its neighbours are not.
"""

from __future__ import annotations

import re

import pytest
from apps.api.core.loadshed import (
    ALWAYS_ALLOWED_PATHS,
    ALWAYS_ALLOWED_PREFIXES,
    LoadShedMode,
    PlatformStatus,
    is_shed,
)
from apps.api.core.rbac import PUBLIC_PREFIXES, iter_api_routes
from apps.api.main import app
from starlette.routing import Route as StarletteRoute

#: Why each prefix is exempt, and which of the four admissible kinds it is.
#:
#: `observability` — the platform must stay readable while degraded.
#: `operator` — the human turning the shed off must not be locked out by it.
#: `callback` — a provider retry window is finite; a dropped webhook is data lost.
#: `door` — the route that MINTS the credential every `operator` exemption assumes.
#:
#: A prefix with no entry here fails the second test, which is the point: adding one is
#: a decision about what the platform keeps serving when it has decided to serve less,
#: and it should cost a sentence.
EXEMPT_PREFIX_REASONS: dict[str, tuple[str, str]] = {
    "/healthz": ("observability", "liveness and readiness — how anyone knows it is shed"),
    "/hooks": (
        "callback",
        "engine lead-ingest and Razorpay payment callbacks (the Clerk hook went with "
        "D-177). A dropped engine webhook is a call whose lead never appears, and the "
        "sender's retry window does not wait for our maintenance to end",
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

#: Why each exact PATH is exempt. Same shape as the prefix registry and a separate dict on
#: purpose: these entries buy an exemption for ONE route and must never be readable as a
#: statement about the space around them — `/v1/auth` holds four other writes that stay
#: shed, and the last time this list said something about a path space it said the wrong
#: thing for months.
EXEMPT_PATH_REASONS: dict[str, tuple[str, str]] = {
    "/v1/auth/admin/login": (
        "door",
        "the operator's sign-in. `/v1/ops` is exempt so the switch that ends a shed stays "
        "reachable — by nobody, if the route that mints the session is shed. This is the "
        "3am case: `emergency` is exactly the mode in which nobody is already signed in",
    ),
    "/v1/auth/admin/login/otp": (
        "door",
        "the second half of that sign-in. The emailed code is this product's whole second "
        "factor (D-170), so a session that has proved only a password can do nothing — "
        "exempting `login` alone is the same lockout in a subtler form",
    ),
    "/v1/auth/client/login": (
        "door",
        "`reduced` is DEFINED as every read continuing to work; a signed-out client who "
        "cannot sign in reads nothing at all, so shedding this falsifies the mode rather "
        "than trimming its cost. Bounded by the tightest rate-limit profile in the "
        "deployment plus `authn/throttle`'s per-account budgets, neither of which is shed",
    ),
    "/v1/auth/client/login/otp": ("door", "the second half of that sign-in, for its twin's reason"),
}

#: The exempt kinds that may cover a publicly reachable WRITE, and why. Everything else
#: public and mutating is customer traffic, which is what shedding is for.
#:
#: `callback` — the sender is a provider, not a user, and its retry window is finite.
#: `door` — the credential-minting route, WITHOUT WHICH EVERY `operator` EXEMPTION ON THE
#:   LIST IS UNREACHABLE by a human who is not already inside. It qualifies only by exact
#:   name (`EXEMPT_PATH_REASONS`): a `door` reason attached to a PREFIX would re-create
#:   the `/v1/auth` defect this file was written for, so the third test refuses it.
CALLBACK_KIND = "callback"
DOOR_KIND = "door"
#: The password step and the second-factor step of a sign-in, in any realm. A PATTERN over
#: the live route table rather than a copy of the exemption list — see
#: `test_an_operator_can_always_reach_the_door` for why the test must not read the list it
#: is checking. `/login/otp/resend` is deliberately outside it.
_SIGN_IN_ROUTE = re.compile(r"/v1/auth/[a-z]+/login(?:/otp)?")
PUBLIC_WRITE_KINDS = frozenset({CALLBACK_KIND, DOOR_KIND})
ADMISSIBLE_KINDS = frozenset({"observability", "operator", CALLBACK_KIND, DOOR_KIND})


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


def test_every_shed_exempt_path_is_a_live_route_exactly() -> None:
    """The same staleness guard, one notch stricter, because these entries are literals.

    `ALWAYS_ALLOWED_PATHS` is matched by EQUALITY, so a route renamed by one character
    stops being exempt and nothing anywhere goes red — the lockout comes back silently
    and looks exactly like the shed working. A prefix at least degrades to "matches
    something"; a literal degrades to nothing. So this compares against the route table
    rather than against a prefix of it.
    """
    live = _live_paths()
    missing = sorted(ALWAYS_ALLOWED_PATHS - live)
    assert not missing, (
        f"ALWAYS_ALLOWED_PATHS names routes this app does not serve: {missing}. Either "
        "the route was renamed — in which case the exemption is now protecting nothing "
        "and an operator is locked out of a shed platform — or the entry is a leftover."
    )


def test_every_shed_exempt_prefix_records_why_it_is_exempt() -> None:
    """The list and the reasons are the same list, in both directions.

    An unexplained prefix is how `/v1/auth` stayed: everyone reading it supplied their
    own justification ("auth, obviously") and nobody checked it against the route table.
    """
    for label, listed, explained in (
        ("prefixes", set(ALWAYS_ALLOWED_PREFIXES), set(EXEMPT_PREFIX_REASONS)),
        ("paths", set(ALWAYS_ALLOWED_PATHS), set(EXEMPT_PATH_REASONS)),
    ):
        assert listed == explained, (
            f"unexplained {label}: {sorted(listed - explained)}; "
            f"explanations for {label} that are no longer exempt: {sorted(explained - listed)}"
        )
    for entry, (kind, reason) in (EXEMPT_PREFIX_REASONS | EXEMPT_PATH_REASONS).items():
        assert kind in ADMISSIBLE_KINDS, f"{entry}: {kind}"
        assert reason.strip(), entry
    # The kind that exists to cover ONE route may not be spent on a path space. Asserted
    # rather than left to review, because attaching `door` to `/v1/auth` would restore the
    # original defect while passing every other test in this file.
    prefix_kinds = {kind for kind, _ in EXEMPT_PREFIX_REASONS.values()}
    assert DOOR_KIND not in prefix_kinds, (
        "a `door` exemption must name an exact path. A prefix hands the exemption to "
        "every route added under it later, which is how `/v1/auth` came to exempt signup."
    )


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
        # `.get`, not `[...]`: an entry added to a list and not to the reasons must
        # fail HERE with the offending route named, not with a KeyError that says
        # nothing about which write escaped. The missing reason is its own test.
        kinds = {EXEMPT_PREFIX_REASONS.get(p, ("unexplained", ""))[0] for p in exempting}
        if path in ALWAYS_ALLOWED_PATHS:
            exempting = [*exempting, path]
            kinds.add(EXEMPT_PATH_REASONS.get(path, ("unexplained", ""))[0])
        if not exempting:
            continue
        if kinds and kinds <= PUBLIC_WRITE_KINDS:
            continue
        offenders.append(f"{methods} {path} exempted by {exempting}")
    assert not offenders, (
        "publicly reachable writes that survive a load shed: "
        f"{offenders}. Shedding exists to stop exactly this work while the platform is "
        "degraded; only a provider callback or the sign-in door may outrank it."
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
        ("/hooks/v1/razorpay", "POST"),
        ("/openapi.json", "GET"),
    ):
        assert not is_shed(maintenance, path=path, method=method), f"{method} {path} was shed"

    # And the client realm is shed, which is what `maintenance` MEANS. Without this the
    # test above would keep passing if the whole guard were disabled.
    assert is_shed(maintenance, path="/v1/leads", method="GET")
    assert is_shed(maintenance, path="/v1/agents", method="GET")


@pytest.mark.parametrize("mode", ["reduced", "emergency", "maintenance"])
def test_an_operator_can_always_reach_the_door(mode: LoadShedMode) -> None:
    """THE LOCKOUT, asserted in every mode that sheds.

    `emergency` is the one that matters and the one that reads as paranoid until you
    picture it: the platform is refusing writes at 3am, the operator is asleep and
    therefore signed out, `/v1/ops` is exempt so the off switch is "reachable", and the
    only route that could have minted the session to reach it was shed. The shed becomes
    an outage only its own expiry can end.

    Both steps, because the emailed code is the whole second factor (D-170) and a
    password-only session can do nothing. Both realms, because `reduced` promises every
    read keeps working and a signed-out client reads nothing.

    THE SUBJECT COMES OFF THE ROUTE TABLE, NOT OFF `ALWAYS_ALLOWED_PATHS`, and that is
    the difference between a property and a tautology. Iterating the exemption list would
    make this test say "everything exempt is exempt" — deleting an entry would shrink the
    loop and stay green, which is the same self-reference that let `/v1/auth` describe a
    surface it did not cover. So the sign-in routes are found in the app, and the count is
    asserted: a realm added without an exemption fails here, and so does one removed.
    """
    status = PlatformStatus(mode=mode, outbound_halted=True)
    sign_in = sorted(path for path in _live_paths() if _SIGN_IN_ROUTE.fullmatch(path))
    assert len(sign_in) == 4, (
        f"expected two realms x (login, login/otp); the app serves {sign_in}. If a realm "
        "was added or renamed, `loadshed.ALWAYS_ALLOWED_PATHS` has to move with it."
    )
    for path in sign_in:
        assert not is_shed(status, path=path, method="POST"), (
            f"{path} was shed in {mode!r} — an operator who is not already signed in "
            "cannot get in, including to turn this off"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/auth/admin/login/otp/resend",
        "/v1/auth/admin/password/reset/request",
        "/v1/auth/admin/password/reset/confirm",
        "/v1/auth/client/session/refresh",
        "/v1/auth/signup",
        "/v1/invitations",
    ],
)
def test_the_door_is_a_door_and_not_the_whole_wall(path: str) -> None:
    """The control on the fix, and the reason `ALWAYS_ALLOWED_PATHS` is matched by
    equality rather than by prefix.

    Every path here lives under a prefix that a `/v1/auth`-shaped exemption would have
    swept up, and each is deliberately still shed — the resend (a convenience over an
    exempt route that already mints a fresh code), the reset pair (a one-hour emailed
    token, not the path out of an incident), the session refresh (unnecessary: any
    authenticated request extends `idle_expires_at`, and the operator surface is exempt)
    and the two account-creating writes. If this test starts failing, the exemption has
    stopped naming routes and started naming a space.
    """
    for mode in ("reduced", "emergency", "maintenance"):
        status = PlatformStatus(mode=mode, outbound_halted=True)
        assert is_shed(status, path=path, method="POST"), f"{path} survived {mode!r}"


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
