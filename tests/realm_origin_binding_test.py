"""Admin-realm paths accept the admin console's origin and nothing else.

The CORS allowlist and the CSRF `Origin` allowlist used to be one list for every path, so
`https://app.calevate.tech` and `https://calevate.tech` were trusted origins for
`/v1/admin/**`, `/v1/ops/**` and `/v1/auth/admin/**` too. Both session cookies live on the
API host, so the browser attaches an operator's cookie to any credentialed request a page
on either of those origins makes: script running in the client console (an XSS, a
compromised dependency) could drive the operator's session and read the answers.

Each case below drives the assembled app, the way a browser would reach it. Nothing here
writes a row.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from apps.api.authn.cookies import COOKIE_NAMES, cross_site_refusal
from apps.api.core.bootstrap import admin_origins_for_env, cors_origins_for_env
from apps.api.core.console_links import ADMIN_CONSOLE_BASE, CONSOLE_BASE, VIEW_AS_HANDOFF_PATHS
from apps.api.core.rbac import (
    ADMIN_AUTH_PREFIX,
    ADMIN_ORIGIN_PREFIXES,
    iter_api_routes,
    route_realms,
)
from apps.api.core.settings import get_settings
from apps.api.main import app
from httpx import ASGITransport, AsyncClient

MARKETING_ORIGIN = "https://calevate.tech"
NOT_ADMIN_ORIGINS = (CONSOLE_BASE, MARKETING_ORIGIN)

#: One mutation per admin-realm prefix; each is refused before routing, so the body and
#: the path parameters never matter.
ADMIN_MUTATIONS = (
    ("POST", "/v1/admin/tenants"),
    ("PUT", "/v1/ops/config/engine"),
    ("POST", "/v1/auth/admin/login"),
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _is_cross_site_refusal(response_json: object) -> bool:
    return isinstance(response_json, dict) and str(response_json.get("type", "")).endswith(
        "/cross_site_request"
    )


# ═══════════════ CSRF: the Origin check ═══════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", NOT_ADMIN_ORIGINS)
@pytest.mark.parametrize(("method", "path"), ADMIN_MUTATIONS)
async def test_an_admin_mutation_from_the_client_or_marketing_origin_is_refused(
    method: str, path: str, origin: str
) -> None:
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["admin"], uuid.uuid4().hex)
        response = await http.request(
            method, path, headers={"origin": origin, "sec-fetch-site": "same-site"}, json={}
        )
    assert response.status_code == 403, response.text
    assert _is_cross_site_refusal(response.json()), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), ADMIN_MUTATIONS)
async def test_an_admin_mutation_from_the_admin_console_passes_the_origin_check(
    method: str, path: str
) -> None:
    """Past the CSRF layer, the made-up cookie is then refused by authentication."""
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["admin"], uuid.uuid4().hex)
        response = await http.request(
            method,
            path,
            headers={"origin": ADMIN_CONSOLE_BASE, "sec-fetch-site": "same-site"},
            json={},
        )
    assert not _is_cross_site_refusal(response.json()), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", (CONSOLE_BASE, MARKETING_ORIGIN, ADMIN_CONSOLE_BASE))
async def test_client_paths_still_accept_every_console_origin(origin: str) -> None:
    """Unchanged for the client realm: the client console, the marketing site's sign-in
    and the admin console's view-as (D-22) all call client paths."""
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["client"], uuid.uuid4().hex)
        response = await http.put(
            "/v1/billing/caps",
            headers={"origin": origin, "sec-fetch-site": "same-site"},
            json={},
        )
        login = await http.post(
            "/v1/auth/client/login",
            headers={"origin": origin, "sec-fetch-site": "same-site"},
            json={},
        )
    assert not _is_cross_site_refusal(response.json()), response.text
    assert not _is_cross_site_refusal(login.json()), login.text


def test_the_pure_rule_is_path_aware() -> None:
    def refused(path: str, origin: str) -> bool:
        return (
            cross_site_refusal(
                sec_fetch_site="same-site", origin=origin, own_origin="http://api", path=path
            )
            is not None
        )

    assert refused("/v1/admin/tenants", CONSOLE_BASE)
    assert refused("/v1/auth/admin/login", MARKETING_ORIGIN)
    assert not refused("/v1/admin/tenants", ADMIN_CONSOLE_BASE)
    assert not refused("/v1/agents", CONSOLE_BASE)
    # The API's own origin stays accepted on admin paths (a same-origin call).
    assert not refused("/v1/admin/tenants", "http://api")


# ═══════════════ CORS ═══════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", NOT_ADMIN_ORIGINS)
@pytest.mark.parametrize(("method", "path"), ADMIN_MUTATIONS)
async def test_an_admin_preflight_from_another_origin_gets_no_allow_origin(
    method: str, path: str, origin: str
) -> None:
    async with _client() as http:
        response = await http.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert "access-control-allow-origin" not in response.headers
    assert response.status_code == 400
    assert "origin" in response.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), ADMIN_MUTATIONS)
async def test_an_admin_preflight_from_the_admin_console_is_allowed(method: str, path: str) -> None:
    async with _client() as http:
        response = await http.options(
            path,
            headers={
                "Origin": ADMIN_CONSOLE_BASE,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == ADMIN_CONSOLE_BASE
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_an_admin_read_answered_to_the_client_console_carries_no_allow_origin() -> None:
    """The simple-request half: without `Access-Control-Allow-Origin` the browser does not
    hand the response to the page, so the client console cannot read an admin answer."""
    async with _client() as http:
        foreign = await http.get("/v1/admin/tenants", headers={"Origin": CONSOLE_BASE})
        own = await http.get("/v1/admin/tenants", headers={"Origin": ADMIN_CONSOLE_BASE})
    assert "access-control-allow-origin" not in foreign.headers
    assert own.headers["access-control-allow-origin"] == ADMIN_CONSOLE_BASE


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", (CONSOLE_BASE, MARKETING_ORIGIN, ADMIN_CONSOLE_BASE))
async def test_a_client_preflight_is_unchanged(origin: str) -> None:
    async with _client() as http:
        response = await http.options(
            "/v1/billing/caps",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == origin


# ═══════════════ the binding is complete, and local dev still works ═══════════════


def test_every_admin_realm_route_sits_under_an_admin_origin_prefix() -> None:
    """Both layers run before routing, so they bind by path. An admin-realm route mounted
    outside these prefixes would accept the client console's origin; this fails first."""
    stray = sorted(
        route.path
        for route in iter_api_routes(app)
        if route_realms(route) == frozenset({"admin"})
        and not route.path.startswith(ADMIN_ORIGIN_PREFIXES)
    )
    assert not stray, f"admin-realm routes outside ADMIN_ORIGIN_PREFIXES: {stray}"
    admin_auth = [r.path for r in iter_api_routes(app) if "auth-admin" in (r.tags or [])]
    assert admin_auth, "found no admin sign-in routes to check"
    assert all(path.startswith(ADMIN_AUTH_PREFIX) for path in admin_auth), admin_auth


def test_admin_origins_are_the_admin_console_plus_the_dev_origin_only_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    try:
        assert admin_origins_for_env() == [ADMIN_CONSOLE_BASE]
    finally:
        get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    try:
        local = admin_origins_for_env()
        assert local == [ADMIN_CONSOLE_BASE, "http://localhost:3000"]
        assert set(local) <= set(cors_origins_for_env())
    finally:
        get_settings.cache_clear()


# ═══════════════ the view-as handoff (D-22) runs on the client console ═══════════════
#
# "View as client" opens `app.calevate.tech/c/<slug>?view=admin`, and that document
# restores the OPERATOR's admin session, mints the grant and answers the step-up the mint
# asks for. Binding those four paths to the admin origin made the restore's `fetch` fail
# CORS, which the console renders as "We could not check your session" — view-as stopped
# opening on every browser.

VIEW_AS_MUTATIONS = tuple(sorted(p for p in VIEW_AS_HANDOFF_PATHS if not p.endswith("/session")))


@pytest.mark.asyncio
async def test_the_admin_session_restore_is_readable_from_the_client_console() -> None:
    """The exact request that failed in production: a simple credentialed GET whose answer
    the browser only hands to the page when it carries `Access-Control-Allow-Origin`."""
    async with _client() as http:
        response = await http.get("/v1/auth/admin/session", headers={"Origin": CONSOLE_BASE})
    assert response.headers.get("access-control-allow-origin") == CONSOLE_BASE
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", VIEW_AS_MUTATIONS)
async def test_a_view_as_preflight_from_the_client_console_is_allowed(path: str) -> None:
    async with _client() as http:
        response = await http.options(
            path,
            headers={
                "Origin": CONSOLE_BASE,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-confirm-action",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == CONSOLE_BASE


@pytest.mark.asyncio
@pytest.mark.parametrize("path", VIEW_AS_MUTATIONS)
async def test_a_view_as_mutation_from_the_client_console_passes_the_origin_check(
    path: str,
) -> None:
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["admin"], uuid.uuid4().hex)
        response = await http.post(
            path, headers={"origin": CONSOLE_BASE, "sec-fetch-site": "same-site"}, json={}
        )
    assert not _is_cross_site_refusal(response.json()), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", VIEW_AS_MUTATIONS)
async def test_a_view_as_mutation_from_the_marketing_site_is_still_refused(path: str) -> None:
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["admin"], uuid.uuid4().hex)
        response = await http.post(
            path, headers={"origin": MARKETING_ORIGIN, "sec-fetch-site": "same-site"}, json={}
        )
    assert response.status_code == 403, response.text
    assert _is_cross_site_refusal(response.json()), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ("/v1/auth/admin/session/refresh", "/v1/auth/admin/logout", "/v1/admin/tenants")
)
async def test_the_handoff_widens_exact_paths_and_not_their_neighbours(path: str) -> None:
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["admin"], uuid.uuid4().hex)
        response = await http.post(
            path, headers={"origin": CONSOLE_BASE, "sec-fetch-site": "same-site"}, json={}
        )
        preflight = await http.options(
            path,
            headers={"Origin": CONSOLE_BASE, "Access-Control-Request-Method": "POST"},
        )
    assert _is_cross_site_refusal(response.json()), response.text
    assert "access-control-allow-origin" not in preflight.headers


def test_every_view_as_handoff_path_is_a_mounted_route() -> None:
    mounted = {route.path for route in iter_api_routes(app)}
    unmounted = VIEW_AS_HANDOFF_PATHS - mounted
    assert not unmounted, sorted(unmounted)


def test_the_handoff_set_names_what_the_view_as_document_calls() -> None:
    """The web callers, read from source, so a new admin-realm call made under view-as
    fails here rather than as an unexplained 'could not check your session'."""
    web = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "lib"
    admin_authn = (web / "authn" / "adminAuthn.ts").read_text(encoding="utf-8")
    realm = (web / "authn" / "realm.ts").read_text(encoding="utf-8")
    admin_api = (web / "api" / "admin.ts").read_text(encoding="utf-8")
    assert 'request<AuthnSession>("/session"' in realm
    assert 'adminAuthn.request<void>("/step-up"' in admin_authn
    assert '"/step-up/verify"' in admin_authn
    assert 'IMPERSONATION_GRANT_PATH = "/v1/admin/impersonation-grants"' in admin_api
    handoff = set(VIEW_AS_HANDOFF_PATHS)
    assert handoff == {
        "/v1/auth/admin/session",
        "/v1/auth/admin/step-up",
        "/v1/auth/admin/step-up/verify",
        "/v1/admin/impersonation-grants",
    }
