"""The `__Host-` prefix is a security boundary only if nothing reads around it (D-198).

THE HOLE. `read_token` tried the prefixed cookie name and then the stripped one, on every
request, whatever scheme it arrived on. The stripped name exists for exactly one
deployment — plain-HTTP local development, where a browser refuses a `__Host-` cookie
outright — and accepting it over TLS handed back everything the prefix was bought for.

`authn/cookies.py`'s own module docstring states the claim this file measures: the prefix
means "no sibling subdomain and no compromised `*.calevate.tech` host can set or overwrite
it". The prefix does stop a sibling OVERWRITING `__Host-calevate_client_session`. It does
not stop that sibling setting `calevate_client_session=<attacker's token>;
Domain=.calevate.tech; Path=/`, which the browser then attaches to every request to
`api.calevate.tech` — so while the stripped name was read, a sibling host could SUPPLY a
session cookie even though it could not replace one.

WHAT THAT REACHED, end to end, with no other defect anywhere:

  1. a page on any `*.calevate.tech` host (a marketing subdomain, a dangling CNAME, a
     takeover of something nobody thought was security-relevant) sets the unprefixed name
     with a session token the attacker holds;
  2. a visitor who is NOT signed in opens the console and is silently signed in as the
     attacker — every lead they add, every number they enter, lands in the attacker's
     tenant;
  3. `clear_session_cookie` cannot undo it. `delete_cookie(path="/")` expires a HOST-ONLY
     cookie; a `Domain=`-scoped one is a different cookie to the browser, is untouched, and
     is sent again on the next request. Signing out re-signs the victim in.

Rotation on sign-in does not close it, which is why the fix is here and not in `sessions.py`:
the fixated session is never the victim's to rotate. OWASP's Session Management Cheat Sheet
puts cookie prefixes and session fixation side by side for this reason.

SHARED DATABASE DISCIPLINE (`tests/shared_state_assertion_guard_test.py`): nothing in this
file touches the database, Redis, or any row.
"""

from __future__ import annotations

import pytest
from apps.api.authn.cookies import (
    COOKIE_NAMES,
    clear_session_cookie,
    cookie_name,
    read_token,
    set_session_cookie,
)
from fastapi import Response
from starlette.requests import Request

#: The attacker in the story: a host under our own registrable domain that is not a console.
#: It cannot set `__Host-…`; it can set the stripped name with a `Domain` attribute.
SIBLING_SET_COOKIE = "calevate_client_session=attacker-held-token"

REALMS = sorted(COOKIE_NAMES)


def _request(*, scheme: str, cookie: str, forwarded_proto: str | None = None) -> Request:
    headers = [(b"host", b"api.calevate.tech"), (b"cookie", cookie.encode())]
    if forwarded_proto is not None:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/agents",
            "raw_path": b"/v1/agents",
            "query_string": b"",
            "headers": headers,
            "scheme": scheme,
            "server": ("api.calevate.tech", 443 if scheme == "https" else 80),
            "client": ("203.0.113.9", 5000),
            "root_path": "",
        }
    )


# ═══════════ the hole, driven from the sibling host's side ═══════════


@pytest.mark.parametrize("realm", REALMS)
def test_an_unprefixed_cookie_is_not_a_credential_over_tls(realm: str) -> None:
    """THE REGRESSION. A sibling subdomain's `Domain=`-scoped cookie must be nothing here.

    This is the whole finding: before the fix `read_token` returned the attacker's value,
    so a signed-out visitor to the console was signed in as somebody else.
    """
    cookie = f"{cookie_name(realm, secure=False)}=attacker-held-token"
    assert read_token(_request(scheme="https", cookie=cookie), realm) is None


@pytest.mark.parametrize("realm", REALMS)
def test_the_same_refusal_holds_behind_a_tls_terminating_proxy(realm: str) -> None:
    """Production terminates TLS at nginx, so the app sees `http` plus `X-Forwarded-Proto`.

    A fix that only read `request.url.scheme` would be correct in a test and absent in
    production, which is the deployment this control exists for.
    """
    cookie = f"{cookie_name(realm, secure=False)}=attacker-held-token"
    request = _request(scheme="http", cookie=cookie, forwarded_proto="https")
    assert read_token(request, realm) is None


@pytest.mark.parametrize("realm", REALMS)
def test_a_prefixed_cookie_is_not_shadowed_by_an_unprefixed_one(realm: str) -> None:
    """Both names present — the victim IS signed in and the sibling has planted one too.

    The prefixed cookie is the credential and the planted one is inert, in either order of
    appearance in the header (a browser does not promise an order).
    """
    real = f"{cookie_name(realm, secure=True)}=the-victims-own-token"
    planted = f"{cookie_name(realm, secure=False)}=attacker-held-token"
    for header in (f"{real}; {planted}", f"{planted}; {real}"):
        assert read_token(_request(scheme="https", cookie=header), realm) == "the-victims-own-token"


# ═══════════ and the deployment the stripped name exists for ═══════════


@pytest.mark.parametrize("realm", REALMS)
def test_plain_http_still_reads_the_stripped_name(realm: str) -> None:
    """Local development over `http://localhost` is why the stripped name exists at all.

    A browser refuses a `__Host-` cookie outside a secure context, so a fix that refused
    the stripped name everywhere would make local development impossible — which is the
    change nobody would keep.
    """
    cookie = f"{cookie_name(realm, secure=False)}=a-local-dev-token"
    assert read_token(_request(scheme="http", cookie=cookie), realm) == "a-local-dev-token"


@pytest.mark.parametrize("realm", REALMS)
def test_read_and_write_agree_about_which_name_this_deployment_speaks(realm: str) -> None:
    """The predicate that chooses the name to SET is the predicate that chooses the name to
    READ. Two copies would be how a deployment comes to write a cookie it cannot read."""
    for scheme in ("http", "https"):
        request = _request(scheme=scheme, cookie="")
        response = Response()
        set_session_cookie(response, realm=realm, token="issued-token", request=request)
        header = response.headers["set-cookie"]
        name = header.split("=", 1)[0]
        echoed = _request(scheme=scheme, cookie=f"{name}=issued-token")
        assert read_token(echoed, realm) == "issued-token"


@pytest.mark.parametrize("realm", REALMS)
def test_sign_out_still_clears_both_names(realm: str) -> None:
    """A deployment that gained TLS between a sign-in and a sign-out must not leave the
    other name sitting in the browser producing refusals that look like a bug."""
    response = Response()
    clear_session_cookie(response, realm=realm, request=_request(scheme="https", cookie=""))
    cleared = response.headers.getlist("set-cookie")
    assert any(header.startswith(f"{cookie_name(realm, secure=True)}=") for header in cleared)
    assert any(header.startswith(f"{cookie_name(realm, secure=False)}=") for header in cleared)


def test_a_realm_cannot_be_read_with_the_other_realms_cookie() -> None:
    """The names are an addressing convention, and this is the negative control for it: the
    admin cookie is not a client cookie under any scheme. (What actually separates the two
    is `sessions.token_fingerprint`; this asserts the name half does not undo it.)"""
    header = f"{cookie_name('admin', secure=True)}=an-operators-token"
    assert read_token(_request(scheme="https", cookie=header), "client") is None
