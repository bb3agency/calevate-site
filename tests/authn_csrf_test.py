"""The CSRF layer that ships, and the hole that closing it fixed (D-178).

AUTH-MIGRATION §11 listed "the signed double-submit token" as not built. It is now argued
away rather than outstanding, and the argument is only honest if the layer it leans on is
airtight — so this file is the measurement of that layer, not of the token.

THE HOLE. `enforce_same_origin` used to return early on `Sec-Fetch-Site: same-site` without
consulting the `Origin` allowlist. `admin.calevate.tech`, `app.calevate.tech` and the API
share one registrable domain, so a page on ANY `*.calevate.tech` host — a compromised
marketing subdomain, a dangling CNAME — issues requests the browser labels `same-site`, with
the session cookie attached, and that early return waved them through. `SameSite=Strict`
does not help (it is not cross-site) and `__Host-` does not help (that prefix stops a sibling
SETTING the cookie, not the browser sending it). OWASP's CSRF cheat sheet names "no shared
registrable domain" as the FIRST condition for `SameSite` + origin verification being
sufficient, and it is the one this deployment cannot meet.

Every test below that names a `*.calevate.tech` origin is that hole, driven from the
attacker's side.

SHARED DATABASE DISCIPLINE: nothing here writes a row.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.authn.cookies import (
    COOKIE_NAMES,
    cookie_name,
    cross_site_refusal,
    enforce_same_origin,
    session_cookie_present,
)
from apps.api.core.bootstrap import DEFAULT_CORS_ORIGINS
from apps.api.core.errors import ProblemError
from apps.api.core.middleware import CookieCsrfMiddleware
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

API_ORIGIN = "http://api"

#: The attacker in the story: a host under our own registrable domain that is not a console.
SIBLING_ORIGIN = "https://blog.calevate.tech"


def _request(headers: dict[str, str], *, path: str = "/v1/auth/admin/login") -> Request:
    """A Starlette request with these headers, addressed to `API_ORIGIN`."""
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    raw.append((b"host", API_ORIGIN.removeprefix("http://").encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": raw,
            "scheme": "http",
            "server": ("api", 80),
            "client": ("203.0.113.9", 5000),
            "root_path": "",
        }
    )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=API_ORIGIN)


# ═══════════════ the rule itself ═══════════════


def test_a_sibling_subdomain_is_refused_even_though_the_browser_calls_it_same_site() -> None:
    """THE HOLE. This request is `same-site` by the specification's own definition and it
    is not one of ours. Before D-178 it was allowed."""
    with pytest.raises(ProblemError) as caught:
        enforce_same_origin(_request({"sec-fetch-site": "same-site", "origin": SIBLING_ORIGIN}))
    assert caught.value.code == "cross_site_request"
    assert caught.value.status == 403


def test_a_sibling_subdomain_is_refused_when_it_sends_no_fetch_metadata_either() -> None:
    """`Sec-Fetch-Site` is a browser header, so an attacker's tooling can omit it. The
    `Origin` check has to stand alone, and does."""
    with pytest.raises(ProblemError):
        enforce_same_origin(_request({"origin": SIBLING_ORIGIN}))


def test_an_explicitly_cross_site_request_is_refused_before_the_origin_is_read() -> None:
    with pytest.raises(ProblemError) as caught:
        enforce_same_origin(
            _request({"sec-fetch-site": "cross-site", "origin": DEFAULT_CORS_ORIGINS[0]})
        )
    assert caught.value.code == "cross_site_request"


@pytest.mark.parametrize("origin", DEFAULT_CORS_ORIGINS)
def test_each_console_origin_is_allowed(origin: str) -> None:
    """The allowlist is the SAME list CORS is installed with — a second copy is how the two
    come to disagree about which consoles exist."""
    enforce_same_origin(_request({"sec-fetch-site": "same-site", "origin": origin}))


def test_the_api_s_own_origin_is_allowed_although_it_is_not_in_the_console_list() -> None:
    """What the removed `same-origin` early exit used to buy. Without it, tightening the
    rule would have refused a legitimate same-origin call from the API's own docs page."""
    enforce_same_origin(_request({"sec-fetch-site": "same-origin", "origin": API_ORIGIN}))


def test_an_absent_origin_is_allowed_and_the_docstring_says_why() -> None:
    """Browsers always send `Origin` on a credentialed cross-origin request, so absent
    means same-origin or a non-browser client — which has no ambient cookie to replay."""
    enforce_same_origin(_request({"sec-fetch-site": "none"}))
    enforce_same_origin(_request({}))


def test_a_trailing_slash_does_not_make_a_console_a_stranger() -> None:
    enforce_same_origin(
        _request({"sec-fetch-site": "same-site", "origin": DEFAULT_CORS_ORIGINS[0] + "/"})
    )


def test_the_pure_rule_and_the_raising_face_agree() -> None:
    """`enforce_same_origin` is the raising face of `cross_site_refusal` and nothing else.
    Two implementations of one rule is how the route guard and the middleware drift."""
    refusal = cross_site_refusal(
        sec_fetch_site="same-site", origin=SIBLING_ORIGIN, own_origin=API_ORIGIN, path="/x"
    )
    assert refusal is not None and refusal.code == "cross_site_request"
    assert (
        cross_site_refusal(
            sec_fetch_site="same-site",
            origin=DEFAULT_CORS_ORIGINS[0],
            own_origin=API_ORIGIN,
            path="/x",
        )
        is None
    )


# ═══════════════ which requests the middleware picks up ═══════════════


@pytest.mark.parametrize("realm", sorted(COOKIE_NAMES))
@pytest.mark.parametrize("secure", [True, False])
def test_either_cookie_name_in_either_scheme_arms_the_check(realm: str, secure: bool) -> None:
    """Both realms, and both the `__Host-` name and the stripped one a plain-HTTP local
    deployment uses — a name the check did not recognise would be a session it did not
    protect."""
    assert session_cookie_present(f"{cookie_name(realm, secure=secure)}=abc123")


def test_an_unrelated_cookie_does_not_arm_the_check() -> None:
    assert not session_cookie_present("consent=1; ab_test=blue")
    assert not session_cookie_present(None)
    assert not session_cookie_present("")


def test_the_unsafe_method_set_is_exactly_the_state_changing_ones() -> None:
    """`OPTIONS` is deliberately absent: the CORS preflight arrives cross-origin BY
    DEFINITION and refusing it would break every console request it precedes."""
    assert {"POST", "PUT", "PATCH", "DELETE"} == CookieCsrfMiddleware.UNSAFE_METHODS


@pytest.mark.asyncio
async def test_the_middleware_refuses_a_sibling_origin_on_a_route_outside_the_auth_package() -> (
    None
):
    """The reason this is a middleware and not a per-route dependency. The route below is
    not in `authn/routes.py` and calls `enforce_same_origin` nowhere; it is protected
    because the rule is applied once, before routing, to everything carrying our cookie."""
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["admin"], uuid.uuid4().hex)
        response = await http.post(
            "/v1/ops/platform",
            headers={"origin": SIBLING_ORIGIN, "sec-fetch-site": "same-site"},
            json={},
        )
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/cross_site_request")
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_a_request_with_no_session_cookie_is_not_touched_by_the_middleware() -> None:
    """CSRF is about an AMBIENT credential. A caller with no cookie has none to be
    replayed, so refusing it would break `curl`, the webhooks and every server-to-server
    caller for nothing. This one gets past the middleware and is refused by AUTH."""
    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform",
            headers={"origin": SIBLING_ORIGIN, "sec-fetch-site": "same-site"},
            json={},
        )
    assert not response.json()["type"].endswith("/cross_site_request"), response.text


@pytest.mark.asyncio
async def test_a_read_is_not_touched_even_with_a_cookie_and_a_foreign_origin() -> None:
    """Nothing in this API mutates on GET (`tests/edge_route_policy_test.py` walks the
    table), so a read is not a CSRF target and refusing one would only break embedding."""
    async with _client() as http:
        http.cookies.set(COOKIE_NAMES["client"], uuid.uuid4().hex)
        response = await http.get(
            "/healthz",
            headers={"origin": SIBLING_ORIGIN, "sec-fetch-site": "same-site"},
        )
    assert response.status_code == 200, response.text
