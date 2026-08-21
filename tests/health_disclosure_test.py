"""What an unauthenticated caller may learn from this deployment, and what it may not.

TWO SURFACES, ONE PROPERTY: the status is public, the reasons are not.

1. **`/healthz` and `/healthz/ready`.** Readiness published `fields[].field` — literally
   `runtime_config_missing_keys`, i.e. the NAMES of the credentials this deployment has
   not installed (`BOLNA_API_KEY`, `CLERK_ADMIN_SECRET_KEY`, `AUDIT_CHAIN_SECRET`) —
   alongside queue depth, oldest-waiting age and which of DB/Redis is down. It is
   unauthenticated, exempt from the in-app rate limiter, and proxied from
   `api.calevate.tech` (and `hooks.calevate.tech`) by the nginx template. That is a
   targeting oracle, and it is loudest during the window before the real keys land.

   The origin lock is not a defence and never was: `calevate-origin.conf` is already
   included by the api vhost, and what it admits is every Cloudflare edge — the whole
   internet, since the zone is proxied. So the detail moves behind `ops:manage`, which
   is the incident permission this repo already has.

2. **`/docs`, `/redoc`, `/openapi.json`**, served unauthenticated in every environment:
   the whole path list, every schema, and `x-calevate-permission` — a map of which
   permission guards which route. Off in `prod`.

WHY THE POSITIVE HALF OF EVERY PAIR IS HERE. "The secret is not in the response" passes
just as well when there is no response at all, when the route 404s, when the body is an
error, or when the endpoint answers `{}` to everybody including the operator who needs
it. Every hiding assertion below is therefore paired with a showing one driven through
the SAME sentinel value: the string an anonymous caller must not see is the string an
`ops:manage` caller must see. A change that breaks either direction fails a test.

AND THE THIRD COPY. Withholding the detail from the wire would have traded an
information leak for an undiagnosable red light, so `core.health` logs it instead. That
log line is asserted too — it is the compensating control, and an uncovered compensating
control is a comment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apps.api.core import bootstrap as bootstrap_module
from apps.api.core import health as health_module
from apps.api.core.bootstrap import create_app
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.rbac import PUBLIC_PREFIXES
from apps.api.db.session import untenanted_session
from apps.api.main import app as api_app
from calevate_shared.config import Settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from main import app as voice_app
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A configuration key name that exists nowhere else, so finding it in a response body
#: proves the disclosure came from `runtime_config_missing_keys` and not from anything
#: this box happens to be missing today.
SENTINEL_KEY = "SENTINEL_CREDENTIAL_NOT_INSTALLED"

#: Everything `/healthz/ready` says beyond "which word describes me".
READY_DETAIL = frozenset({"degradation_mode", "checks", "queue", "fields"})
HEALTH_DETAIL = frozenset({"degradation_mode", "checks"})

DOC_ROUTES = ("/docs", "/redoc", "/openapi.json")


def _client(app: FastAPI = api_app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """A real `admin_users` row plus the dev-token realm credential — `route_shape_test`'s
    idiom, and the same one `ops_outbox_replay_test` uses to reach an `ops:manage` route."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _get(path: str, *, token: str | None = None, app: FastAPI = api_app) -> Response:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with _client(app) as http:
        return await http.get(path, headers=headers)


@pytest.fixture
def healthy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A deployment with nothing missing and an empty queue.

    The queue is stubbed rather than trusted because Redis is shared across concurrent
    test runs: a job another suite parked would make `oldest_waiting_s` exceed
    `QUEUE_STALE_AFTER_S` and flip `degradation_mode` to `queue_stale` under this file's
    feet. Determinism here is what lets the assertions below be equalities.
    """
    monkeypatch.setattr(health_module, "runtime_config_missing_keys", lambda _settings: [])
    monkeypatch.setattr(health_module, "_queue_stats", _no_queue)
    yield


@pytest.fixture
def missing_a_credential(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The condition this endpoint exists to report, forced by name."""
    monkeypatch.setattr(
        health_module, "runtime_config_missing_keys", lambda _settings: [SENTINEL_KEY]
    )
    monkeypatch.setattr(health_module, "_queue_stats", _no_queue)
    yield


async def _no_queue() -> tuple[int, float | None]:
    return 0, None


# --------------------------------------------------------- 1. the anonymous caller


async def test_an_anonymous_probe_gets_a_verdict_and_nothing_else(healthy: None) -> None:
    """The public contract, as an EQUALITY.

    A subset assertion ("`fields` is not in the body") would still pass if the route
    started 404ing, started erroring, or started answering `{}` — none of which is the
    behaviour anybody wants from a readiness probe. Two keys, both of them the verdict.
    """
    response = await _get("/healthz/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "service": "api"}


async def test_the_probe_still_says_not_ready_and_still_says_503(
    missing_a_credential: None,
) -> None:
    """THE HALF THAT MUST NOT REGRESS WHILE FIXING THE OTHER ONE. A probe that cannot
    distinguish healthy from unhealthy is worse than no probe: an orchestrator would
    route traffic at a box that cannot place a call. The status code and the status word
    are the whole of what a probe reads, and both survive."""
    response = await _get("/healthz/ready")
    assert response.status_code == 503, response.text
    assert response.json() == {"status": "not_ready", "service": "api"}


async def test_the_name_of_the_missing_credential_never_reaches_an_anonymous_caller(
    missing_a_credential: None,
) -> None:
    """The oracle, stated on the raw bytes rather than on the parsed shape: a key that
    moved from `fields[]` into `detail`, into a header, or into a problem+json title
    would still be a disclosure."""
    response = await _get("/healthz/ready")
    assert SENTINEL_KEY not in response.text
    assert SENTINEL_KEY not in json.dumps(dict(response.headers))


async def test_healthz_does_not_say_which_dependency_is_down(healthy: None) -> None:
    """`/healthz` published the identical `checks` dict. Gating readiness while leaving
    this one open would be a mitigation defeated by a second URL — which is exactly the
    shape of the `/docs` one-route workaround this change also removes."""
    response = await _get("/healthz")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "service": "api"}


# --------------------------------------------------------- 2. the authorised caller


async def test_an_ops_manage_caller_is_told_exactly_what_is_missing(
    missing_a_credential: None,
) -> None:
    """THE POSITIVE HALF, driven through the same sentinel as the negative one.

    Without this the file could be satisfied by an endpoint that answers nobody, and the
    guard would be the `assert x == 0` against a counter nothing increments.
    """
    response = await _get("/healthz/ready", token=await _make_admin())
    assert response.status_code == 503, response.text
    body = response.json()
    assert set(body) == {"status", "service"} | READY_DETAIL
    assert body["degradation_mode"] == "config_missing"
    # `/healthz/ready` reports the schema revision too; `/healthz` deliberately does not
    # (it is the container healthcheck, and a schema behind the code is not a reason to
    # kill a container — see `_check_schema_current`).
    assert body["checks"] == {"db": True, "schema": True, "redis": True}
    assert body["queue"] == {"depth": 0, "oldest_waiting_s": None}
    assert [field["field"] for field in body["fields"]] == [SENTINEL_KEY]


async def test_the_detail_is_not_merely_the_503_body(healthy: None) -> None:
    """A gate implemented as "show the detail when unhealthy" would pass every
    assertion above and still be the leak. So the healthy case is driven too: an
    authorised caller gets the same shape at 200, and an anonymous one does not."""
    response = await _get("/healthz/ready", token=await _make_admin())
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"status", "service"} | READY_DETAIL
    assert body["degradation_mode"] == "none"
    assert body["fields"] == []


async def test_healthz_tells_an_authorised_caller_which_dependency_it_reached(
    healthy: None,
) -> None:
    response = await _get("/healthz", token=await _make_admin())
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"status", "service"} | HEALTH_DETAIL
    assert body["checks"] == {"db": True, "redis": True}


# --------------------------------------------------- 3. who is NOT an authorised caller


async def test_an_operator_is_not_on_call_and_does_not_see_it(
    missing_a_credential: None,
) -> None:
    """`ops:manage` is superadmin-only and deliberately so (rbac.ROLE_PERMISSIONS): it
    is the incident surface, and the operator role that runs onboarding does not hold
    it. Asserted with a real admin session so this is about the PERMISSION and not about
    whether a token was presented."""
    response = await _get("/healthz/ready", token=await _make_admin(role="operator"))
    assert response.status_code == 503, response.text
    assert response.json() == {"status": "not_ready", "service": "api"}
    assert SENTINEL_KEY not in response.text


@pytest.mark.parametrize(
    "impersonate",
    [
        pytest.param("some-client", id="a slug with no grant behind it"),
        pytest.param("", id="the blank header D-119 found"),
        pytest.param("   ", id="whitespace"),
    ],
)
async def test_a_view_as_session_is_not_a_way_into_the_incident_surface(
    missing_a_credential: None, impersonate: str
) -> None:
    """FAIL-CLOSED ON THE IMPERSONATION PATH, which is where the gate's `try` could most
    plausibly fail open.

    `ops:manage` is in `MUTATING_PERMISSIONS`, so `requires` refuses it under
    impersonation by design — a read-only "view as client" session exists to see a
    client's screens, and nothing about that job needs the platform's incident detail.
    These three header shapes never get that far (no grant, and D-119's blank is a
    request defect answered as one), and each raises a DIFFERENT `ProblemError`: the
    property asserted is that every one of them lands on the minimal body rather than on
    a 500, a 403, or the detail.
    """
    async with _client() as http:
        response = await http.get(
            "/healthz/ready",
            headers={
                "Authorization": f"Bearer {await _make_admin()}",
                "X-Impersonate-Org": impersonate,
            },
        )
    assert response.status_code == 503, response.text
    assert response.json() == {"status": "not_ready", "service": "api"}


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("dev:client:someone", id="a client-realm token"),
        pytest.param("not-a-token-at-all", id="a garbage bearer"),
        pytest.param("", id="an empty bearer"),
    ],
)
async def test_a_credential_that_is_not_an_admin_session_learns_nothing(
    missing_a_credential: None, token: str
) -> None:
    """And none of them 500s or 401s the probe. A health endpoint that started refusing
    unauthenticated callers would be a fix that broke every orchestrator polling it."""
    response = await _get("/healthz/ready", token=token)
    assert response.status_code == 503, response.text
    assert response.json() == {"status": "not_ready", "service": "api"}


# ------------------------------------- what gating a probe cost, and what bounds it now
#
# The gate put an AUTHENTICATION ATTEMPT on the two routes carrying
# `ratelimit.PROFILES["exempt"]` — no per-client limit at all, because a probe must answer
# during an incident. Behind an authentication attempt is `auth._signing_key_for`, whose
# own docstring says `PyJWKClient` refetches the whole key set for an unknown `kid` and
# never memoises the failure, so any caller can force one fetch per request by varying one
# field of an unsigned JWT — "and on `/healthz*` there is not even a rate-limit profile in
# front of it". D-135 moved that fetch off the event loop onto `asyncio.to_thread`; the
# pool it moved onto is `min(32, cpu+4)` threads and shared with everything else blocking
# in the process. Moving a hazard to a scarcer resource is not the same as bounding it,
# and the mounting is what was left open.


async def test_an_anonymous_probe_never_reaches_the_token_verifier(
    missing_a_credential: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uptime monitor and a load balancer send no `Authorization` header, and the
    overwhelming majority of traffic on these routes is one of those two.

    `current_admin` is where the JWKS machinery lives behind `requires`. Asserted on what
    was CALLED rather than on the response: the body is identical either way, so a
    response-shaped assertion would pass whether or not the verifier ran.
    """
    from apps.api.core import auth as auth_module

    entered: list[str] = []
    real = auth_module.current_admin

    async def counted(request: Any) -> Any:
        entered.append("x")
        return await real(request)

    monkeypatch.setattr(auth_module, "current_admin", counted)

    anonymous = await _get("/healthz/ready")
    assert anonymous.status_code == 503
    assert entered == [], "a probe with no credential paid for the verifier anyway"

    # The paired positive: the short-circuit is a cost saving, NOT the access control.
    # A caller who does present something reaches the real ladder and is judged by it.
    await _get("/healthz/ready", token="not-a-token-at-all")
    assert entered == ["x"], "presenting a credential must still be checked properly"


async def test_the_probe_cannot_be_used_to_spend_the_pool_the_verifier_runs_on(
    missing_a_credential: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound, measured at its peak rather than asserted from the source.

    A slow verifier stands in for the JWKS fetch an unknown `kid` forces. Twelve
    concurrent bogus credentials arrive at an endpoint with no rate-limit profile; at most
    `_DETAIL_GATE_CONCURRENCY` of them may be inside the verifier at once, and every one
    of the twelve must still get its probe answer — denying the DETAIL under contention is
    the intended failure, denying the PROBE would be an outage.
    """
    from apps.api.core import auth as auth_module

    live = 0
    peak = 0

    async def slow(request: Any) -> Any:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            await asyncio.sleep(0.05)
            raise ProblemError.forbidden("no")
        finally:
            live -= 1

    monkeypatch.setattr(auth_module, "current_admin", slow)

    async with _client() as http:
        responses = await asyncio.gather(
            *(
                http.get("/healthz/ready", headers={"Authorization": f"Bearer forged-{n}"})
                for n in range(12)
            )
        )

    assert peak <= bootstrap_module._DETAIL_GATE_CONCURRENCY, (
        f"{peak} verifications at once on a route with no rate limit"
    )
    assert [r.status_code for r in responses] == [503] * 12, "every probe still answered"
    assert all(set(r.json()) == {"status", "service"} for r in responses), (
        "and none of them leaked the detail on the way past the bound"
    )


async def test_the_saturation_refusal_is_visible_to_an_operator(
    missing_a_credential: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A silent bound is a bound nobody can tell is being hit. This log line is the only
    place the shape of an amplification attempt on this route is visible."""
    from apps.api.core import auth as auth_module

    async def slow(request: Any) -> Any:
        await asyncio.sleep(0.05)
        raise ProblemError.forbidden("no")

    monkeypatch.setattr(auth_module, "current_admin", slow)
    with caplog.at_level(logging.WARNING, logger="apps.api.core.bootstrap"):
        async with _client() as http:
            await asyncio.gather(
                *(
                    http.get("/healthz", headers={"Authorization": f"Bearer forged-{n}"})
                    for n in range(8)
                )
            )
    assert [r for r in caplog.records if r.getMessage() == "health_detail_gate_saturated"]


async def test_an_authorised_operator_alone_is_never_the_one_denied(
    missing_a_credential: None,
) -> None:
    """The bound must not cost the person it exists for. One operator, one request, and
    the detail arrives — the ordinary case, which every other test here shortcuts past."""
    response = await _get("/healthz/ready", token=await _make_admin())
    assert set(response.json()) >= READY_DETAIL


async def test_liveness_never_grows_a_detail_for_anybody(healthy: None) -> None:
    """It touches no dependency, so it has nothing to disclose — pinned so a future
    "just add degradation_mode everywhere" cannot reopen the surface on the one endpoint
    Docker polls every 15 seconds."""
    anonymous = await _get("/healthz/live")
    authorised = await _get("/healthz/live", token=await _make_admin())
    assert anonymous.json() == authorised.json() == {"status": "ok", "service": "api"}


async def test_voice_runtime_discloses_nothing_to_anyone(missing_a_credential: None) -> None:
    """`hooks.calevate.tech/healthz/ready` published the same key names from the same
    call. It authenticates no human being — `core.auth` is not on its pinned import
    surface (tests/voice_runtime_import_surface_test.py) and putting the Clerk verifier
    on a live-call service's boot graph to answer a probe would be hard rule 3 traded for
    convenience. So it is built with no gate at all, and an `ops:manage` credential is
    not a way in either."""
    token = await _make_admin()
    for response in (
        await _get("/healthz/ready", app=voice_app),
        await _get("/healthz/ready", token=token, app=voice_app),
    ):
        assert response.status_code == 503, response.text
        assert response.json() == {"status": "not_ready", "service": "voice-runtime"}


# ------------------------------------------------ 4. the operator's copy of the detail


async def test_what_is_withheld_from_the_wire_is_written_to_the_log(
    missing_a_credential: None, caplog: pytest.LogCaptureFixture
) -> None:
    """THE COMPENSATING CONTROL, and the reason this change is not an outage waiting to
    happen: during `db_down` nobody can authenticate, so `ops:manage` reaches no one and
    the response is minimal for everybody. The operator's next step has to survive that,
    and a log line is where they already are.

    The key NAMES are logged, never values — an environment variable name is in
    `.env.example` and is the whole of the next step. Joined into a string on purpose:
    `logging.redact_mapping` renders a list extra as "[N items]", so a list here would
    have logged the COUNT of what is missing and none of the names, which is the shape
    of a guardrail that reads as one.
    """
    with caplog.at_level(logging.WARNING, logger="apps.api.core.health"):
        await _get("/healthz/ready")

    records = [r for r in caplog.records if r.getMessage() == "health_not_ready"]
    assert records, "readiness went red and left the operator nothing to read"

    # ASSERTED THROUGH THE FORMATTER, and that is the whole point rather than a detail.
    # The record holds what the code passed; the rendered line is what an operator
    # actually reads, and `redact_mapping` runs in between — it collapses a list extra
    # to "[N items]" and blanks any key matching REDACT_KEYS. An assertion on the record
    # alone would pass for a line that ships the COUNT of missing credentials and none
    # of their names, which is a red light with no next step wearing a guardrail's face.
    rendered = json.loads(JsonFormatter().format(records[-1]))
    assert rendered["missing_config_keys"] == SENTINEL_KEY, rendered
    assert rendered["degradation_mode"] == "config_missing", rendered
    assert rendered["service"] == "api", rendered


async def test_a_healthy_readiness_check_is_silent(
    healthy: None, caplog: pytest.LogCaptureFixture
) -> None:
    """The other half: a line per poll on a healthy box is how a log stops being read,
    and the warning that matters gets lost in it."""
    with caplog.at_level(logging.WARNING, logger="apps.api.core.health"):
        await _get("/healthz/ready")
    assert [r for r in caplog.records if r.getMessage() == "health_not_ready"] == []


# ------------------------------------------------------- 5. the API documentation


def _prod_settings() -> Settings:
    """A production-shaped configuration. `_env_file=None` so this describes a prod
    deployment rather than whatever this developer's `.env` holds."""
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="prod",
        database_url="postgresql+psycopg://calevate_app:x@db.internal:5432/calevate",
        redis_url="redis://redis.internal:6379/0",
        object_store_endpoint="https://example.invalid",
        object_store_bucket="calevate-prod",
    )


def _build(monkeypatch: pytest.MonkeyPatch, environment: str) -> FastAPI:
    settings = (
        _prod_settings()
        if environment == "prod"
        else _prod_settings().model_copy(update={"app_env": environment})
    )
    monkeypatch.setattr(bootstrap_module, "get_settings", lambda: settings)
    # `minimal=True` for the same reason voice-runtime uses it: this test is about which
    # routes exist, and building the middleware stack would drag a CORS/rate-limit/
    # load-shed chain into an assertion that has nothing to do with them.
    return create_app(service=f"docsprobe-{environment}", title="docs probe", minimal=True)


def test_the_schema_is_not_served_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """The path list, every request and response model, and which permission guards
    which route — published unauthenticated on the same host as the routes."""
    paths = {getattr(route, "path", None) for route in _build(monkeypatch, "prod").routes}
    assert not paths & set(DOC_ROUTES), sorted(paths & set(DOC_ROUTES))


@pytest.mark.parametrize("environment", ["local", "staging"])
def test_the_schema_is_still_served_everywhere_else(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """The control. Staging is where a human reads the schema, and a change that turned
    it off everywhere would be paid for in every debugging session — the cheapest way to
    pass the test above is to delete the feature."""
    paths = {getattr(route, "path", None) for route in _build(monkeypatch, environment).routes}
    assert set(DOC_ROUTES) <= paths, sorted(set(DOC_ROUTES) - paths)


def test_prod_can_still_generate_the_schema_it_no_longer_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CLAIM "nothing loses a capability", CHECKED RATHER THAN ASSERTED IN PROSE.

    `openapi_url=None` removes the ROUTE, not `FastAPI.openapi()`. That distinction is
    what `scripts/check_openapi_fresh` rests on — it imports the app and calls the
    method — so the guardrail that keeps the committed snapshot fresh is unaffected by
    an environment it never runs in.
    """
    schema = _build(monkeypatch, "prod").openapi()
    assert schema["paths"], "the schema itself must still be generable"
    assert "/healthz/ready" in schema["paths"]


def test_the_typed_client_is_generated_from_a_file_and_not_from_a_server() -> None:
    """The other half of "nothing loses a capability", read off the build rather than
    believed: if `gen:api` pointed at a URL, turning the route off in prod would break
    the frontend build the first time anyone generated against a prod host."""
    package = json.loads((REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    generator = package["scripts"]["gen:api"]
    assert "src/lib/api/openapi.json" in generator, generator
    assert "http" not in generator, f"gen:api reaches a server: {generator}"
    assert (REPO_ROOT / "apps" / "web" / "src" / "lib" / "api" / "openapi.json").exists()


def test_the_doc_routes_are_no_longer_declared_a_public_surface() -> None:
    """`PUBLIC_PREFIXES` is the repo's written statement of what is unauthenticated by
    design, and `integrations/routes.py` cites it as the reason a handler's docstring
    was rewritten. Leaving the entries behind would leave that statement true."""
    assert not set(DOC_ROUTES) & set(PUBLIC_PREFIXES)
    assert "/healthz" in PUBLIC_PREFIXES, "the probe itself is still unauthenticated"


__all__: list[Any] = []
