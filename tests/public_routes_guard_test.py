"""The public-route guardrail, proved against the states it exists to catch (D-173).

`scripts/check_public_routes.py` claims that the unauthenticated surface of `apps/api` is
enumerated rather than inherited from a path prefix, and that every mutating entry names a
credential the handler's module actually contains. A check making those claims while blind
to a violation would be the worst possible outcome here: it would put a green tick beside
a route that the RBAC boot assertion skips and that nobody declared — which is to say, an
open endpoint that two guardrails agree is somebody else's problem.

Three kinds of test, the shape the newer guardrails established:

- **wiring** — pointed at the REAL app, so a check that has drifted from what `rbac`
  actually skips fails here. Including the partition test: guarded and public must cover
  the route table between them, with nothing in both and nothing in neither.
- **detection** — one minimal mutation that IS the violation, applied to the real app or
  the real registry, asserted to be named.
- **calibration** — the shape that is legitimately exempt and legitimately mutating (a
  signed webhook), pinned so the credential clause cannot be quietly relaxed into always
  passing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from apps.api.core import rbac
from apps.api.main import app
from fastapi import APIRouter
from scripts import check_public_routes as guard


@pytest.fixture
def exempt() -> dict[str, object]:
    return guard.exempt_routes(app)


@pytest.fixture
def extra_public_route() -> Iterator[str]:
    """Mount one route under a live public prefix, then take it away again.

    The REAL app rather than a fixture app: the violation this guards is "somebody adds a
    route to the auth module", and the only faithful rehearsal of that is adding one to
    the app the process serves. Restored in a `finally` so no later test sees it.
    """
    before = list(app.router.routes)
    router = APIRouter()

    @router.post("/v1/auth/negative-control")
    async def _negative_control() -> dict[str, str]:  # pragma: no cover - never called
        return {"ok": "never"}

    app.include_router(router)
    app.openapi_schema = None
    try:
        yield "POST /v1/auth/negative-control"
    finally:
        app.router.routes = before
        app.openapi_schema = None


# --- wiring -------------------------------------------------------------------


class TestWiring:
    def test_the_live_surface_matches_its_declaration(self) -> None:
        """The state this guardrail holds. A failure here names the disagreement."""
        assert guard.audit(app) == []

    def test_the_public_and_guarded_sets_partition_the_route_table(
        self, exempt: dict[str, object]
    ) -> None:
        """Between this check and `assert_policy_registry_complete` every route is judged
        exactly once. A route in both would be judged twice by rules that can disagree; a
        route in neither is the hole both checks exist to close."""
        every = {
            f"{method} {route.path}"
            for route in rbac.iter_api_routes(app)
            for method in sorted(route.methods or [])
        }
        guarded = {
            key
            for key in every
            if not any(key.split(" ", 1)[1].startswith(p) for p in rbac.PUBLIC_PREFIXES)
        }
        assert guarded & set(exempt) == set()
        assert guarded | set(exempt) == every
        assert set(exempt) == set(guard.UNAUTHENTICATED_ROUTES)

    def test_the_surface_is_small_enough_to_read(self, exempt: dict[str, object]) -> None:
        """Not a rule, a tripwire. This registry is meant to be short enough that a human
        reads the whole thing in a review; if it doubles, that is the conversation, not a
        silent edit. Raising the bound is deliberate and shows up in a diff.

        RAISED 20 -> 36 when D-170's first-party auth landed. The jump is 24 routes in one
        change and it is not drift: twelve flows, mirrored across the admin and client
        realms, every one of which is unauthenticated by definition because it is how a
        person BECOMES authenticated. The realm mirroring is why this bound now moves in
        twos — a flow that existed for one realm and not the other would mean the boundary
        had been drawn in the wrong place. 36 leaves room for the frontend slice to add
        nothing and for one more pair; a third pair is the conversation this tripwire is
        for."""
        assert len(exempt) <= 36, sorted(exempt)


# --- detection ----------------------------------------------------------------


class TestDetection:
    def test_a_new_route_under_a_public_prefix_is_reported(self, extra_public_route: str) -> None:
        """The whole reason this check exists: a route mounted under `/v1/auth/` is exempt
        from the RBAC registry by construction. It must not also be invisible."""
        problems = guard.audit(app)
        assert any(extra_public_route in problem for problem in problems), problems

    def test_a_declaration_for_a_route_that_no_longer_exists_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, exempt: dict[str, object]
    ) -> None:
        """The registry may only shrink. A row outliving its route is a standing permission
        waiting for the path to be reused."""
        monkeypatch.setitem(
            guard.UNAUTHENTICATED_ROUTES,
            "POST /v1/auth/retired",
            guard.PublicRoute(why="a reason long enough to clear this check's length floor"),
        )
        problems = guard.audit(app)
        assert any("POST /v1/auth/retired" in problem for problem in problems), problems

    def test_a_credential_the_handler_does_not_contain_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The clause that makes the registry a claim rather than a comment. Rename the
        verifier in the row and the row stops describing the code."""
        key = "POST /hooks/v1/razorpay"
        monkeypatch.setitem(
            guard.UNAUTHENTICATED_ROUTES,
            key,
            replace(guard.UNAUTHENTICATED_ROUTES[key], credential="verify_signature_v2"),
        )
        problems = guard.audit(app)
        assert any("verify_signature_v2" in problem for problem in problems), problems

    def test_a_mutating_route_with_no_credential_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unauthenticated write with nothing standing in for a session. Dropping the
        `credential` field is exactly how that would be written."""
        key = "POST /hooks/v1/razorpay"
        monkeypatch.setitem(
            guard.UNAUTHENTICATED_ROUTES,
            key,
            replace(guard.UNAUTHENTICATED_ROUTES[key], credential=None),
        )
        problems = guard.audit(app)
        assert any(key in problem and "names no credential" in problem for problem in problems)

    def test_a_permission_label_on_an_exempt_route_is_reported(
        self, exempt: dict[str, object]
    ) -> None:
        """A route under a public prefix that carries `x-calevate-permission` reads as
        protected in the OpenAPI schema and the generated TypeScript client, while the
        registry never looks at it."""
        route = exempt["POST /v1/auth/signup"]
        before = route.openapi_extra
        route.openapi_extra = {"x-calevate-permission": "org:manage"}
        try:
            problems = guard.audit(app)
        finally:
            route.openapi_extra = before
        assert any("org:manage" in problem for problem in problems), problems

    def test_a_prefix_that_covers_nothing_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A prefix matching no live route is a standing exemption for whatever lands
        under it next — the failure mode this check was written to prevent, one level up."""
        monkeypatch.setattr(rbac, "PUBLIC_PREFIXES", (*rbac.PUBLIC_PREFIXES, "/v1/legacy/"))
        problems = guard.audit(app)
        assert any("/v1/legacy/" in problem for problem in problems), problems

    def test_a_thin_reason_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ "webhook" is not a reason. The floor cannot judge an argument, only refuse the
        absence of one."""
        key = "GET /healthz"
        monkeypatch.setitem(guard.UNAUTHENTICATED_ROUTES, key, guard.PublicRoute(why="webhook"))
        assert guard.thin_reasons() == [
            f"{key}: reason is 7 characters; {guard._MIN_REASON} is the floor"
        ]

    def test_broken_discovery_refuses_rather_than_passing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No exempt routes at all means discovery broke, not that the surface closed."""
        monkeypatch.setattr(rbac, "PUBLIC_PREFIXES", ())
        with pytest.raises(guard.PublicRouteError):
            guard.audit(app)


# --- calibration --------------------------------------------------------------


class TestCalibration:
    def test_a_signed_webhook_is_accepted_and_says_what_signs_it(
        self, exempt: dict[str, object]
    ) -> None:
        """Every mutating public route we have IS legitimately public and IS backed. If
        this ever passes with a `credential` of None, clause 4 has been relaxed into
        nothing."""
        mutating = {
            key: guard.UNAUTHENTICATED_ROUTES[key]
            for key in exempt
            if key.split(" ", 1)[0] in guard._MUTATING
        }
        assert mutating, "the tripwire: no mutating public routes means the set moved"
        assert all(entry.credential for entry in mutating.values()), mutating

    def test_a_read_only_probe_may_be_genuinely_open(self) -> None:
        """The health probes have no credential and must not be required to invent one —
        a liveness endpoint that needs a secret store is unrecoverable during an outage."""
        assert guard.UNAUTHENTICATED_ROUTES["GET /healthz/live"].credential is None
        assert guard.audit(app) == []

    def test_a_credential_named_only_in_prose_does_not_count(
        self, exempt: dict[str, object]
    ) -> None:
        """The narrowing that separates this from the check it was written from.

        `route-discipline-check.js` regexes the route config's SOURCE TEXT, so a comment
        mentioning `opsAuthGuard` satisfies it. Clause 4 reads the AST instead. This proves
        it: `verify_signature` IS in the payment webhook module's names, and a word that
        appears only in that module's prose is not — even though a substring search would
        find both.

        THE SUBJECT MOVED, and it is worth saying why rather than letting a diff say it.
        This was written against `POST /hooks/v1/clerk` and `verify_svix`, which D-177
        deleted with the identity mirror. The payment callback is the same shape — an
        unauthenticated write whose credential is an HMAC over the raw body — so the
        property is unchanged and only its example is new.
        """
        route = exempt["POST /hooks/v1/razorpay"]
        names = guard._referenced_names(route)
        assert "verify_signature" in names
        # `forgery` appears in that module's prose about why the HMAC is over raw bytes,
        # and nowhere in its code. If this ever passes, the check has gone back to reading
        # prose.
        assert "forgery" not in names
