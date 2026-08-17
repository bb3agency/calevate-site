"""How a session token reaches the browser, and how it comes back (D-166).

═══ WHY A COOKIE AND NOT A BEARER TOKEN ═══

Because the token must be unreadable to JavaScript. Today `apps/web` holds a Clerk token in
memory and attaches it with `Authorization:`, which is structurally immune to CSRF and
structurally exposed to XSS — any script that runs on the page can read it and exfiltrate
it. An `HttpOnly` cookie inverts both properties, and the trade is worth taking: an XSS on
a dashboard that renders client CRM data is a realistic risk this product has to plan for,
whereas CSRF is a well-understood problem with well-understood controls, applied below.

═══ THE COOKIE, ATTRIBUTE BY ATTRIBUTE ═══

`__Host-` prefix — forbids a `Domain` attribute and forces `Path=/` and `Secure`
(draft-ietf-httpbis-rfc6265bis §4.1.3, read 2026-08-17). It makes the cookie host-only to
the API origin, so no sibling subdomain and no compromised `*.calevate.tech` host can set
or overwrite it. This is the one attribute that defends against cookie FIXATION from a
neighbouring host, which `SameSite` does not touch.

`HttpOnly` — the point of the exercise.

`Secure` — implied by `__Host-` and stated anyway, so the intent survives somebody
renaming the cookie.

`SameSite=Strict` — and this is where we deliberately differ from the reference
implementation, which argues for `Lax`. Their argument is correct for their situation: a
flow that must survive a top-level navigation ARRIVING from another site (an email link
that lands you signed in) breaks under `Strict`. Ours has no such flow — the API is reached
only by `fetch` from our own two consoles, and the emailed links in this package land on a
PAGE which then makes its own same-origin call, so the cookie is never needed on the
cross-site navigation itself. Taking `Strict` costs nothing here and removes the entire
class of top-level-navigation CSRF.

`Max-Age` is deliberately ABSENT, making this a session cookie. The authority on when the
session ends is the ROW (`idle_expires_at` / `absolute_expires_at`), and a `Max-Age` would
be a second, client-controlled, unenforceable copy of that fact which the browser could
disagree with. `sessions.py` already argues that the row is the session.

═══ TWO COOKIE NAMES, AND WHAT THAT IS AND IS NOT ═══

`__Host-calevate_admin_session` and `__Host-calevate_client_session`. AUTH-MIGRATION §3 is
blunt about the limit of this and it is repeated here because it is the thing a reader will
get wrong: **because both consoles talk to one API host, both cookies land on that host, so
the NAME IS AN ADDRESSING CONVENTION AND NOT A SECURITY BOUNDARY.** What actually separates
the realms is `sessions.token_fingerprint` putting the realm inside the hash, the `realm`
predicate beside it, and the origin check below. The two names exist so that being signed
into both consoles at once works at all — one name would mean the second sign-in silently
evicted the first.

═══ CSRF ═══

OWASP's CSRF Prevention Cheat Sheet (read 2026-08-17) is explicit that `SameSite` is
defence in depth rather than sufficient, and that `Sec-Fetch-Site` rejection with an
`Origin` allowlist fallback is a recommended layer. Both are here, in `enforce_same_origin`.

**What is NOT here: the signed double-submit token.** The cheat sheet's bottom line is to
layer that on top, and AUTH-MIGRATION §6 designs it. It is not built, because it is half a
frontend feature — the header has to be attached by `lib/api/client.ts`, and `apps/web` is
out of scope for this change. Building the server half alone would mean either a header
nothing sends (so every mutating request fails) or a check that passes when the header is
absent (so it defends nothing). It is named in AUTH-MIGRATION §1 C-22 as outstanding rather
than left to be discovered.
"""

from __future__ import annotations

from typing import Final

from fastapi import Request, Response

from apps.api.authn.models import AUTHN_REALMS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: One name per realm. See the module docstring on what this is not.
COOKIE_NAMES: Final[dict[str, str]] = {
    "admin": "__Host-calevate_admin_session",
    "client": "__Host-calevate_client_session",
}

#: `__Host-` REQUIRES `Secure`, and browsers reject a `__Host-` cookie sent over plain
#: HTTP — which would make local development impossible, because `http://localhost` is not
#: a secure context for cookie purposes in every browser. So the prefix is dropped, and
#: ONLY the prefix, when the request did not arrive over TLS. Deciding this from the
#: REQUEST rather than from `APP_ENV` is deliberate: a staging box terminating TLS at nginx
#: and a laptop on plain HTTP differ in exactly this way, and reading the actual scheme
#: means neither has to be configured.
_INSECURE_PREFIX_STRIP: Final = "__Host-"


def cookie_name(realm: str, *, secure: bool = True) -> str:
    """The cookie this realm's session lives in."""
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm")
    name = COOKIE_NAMES[realm]
    return name if secure else name.removeprefix(_INSECURE_PREFIX_STRIP)


def _is_secure(request: Request) -> bool:
    """Did this request arrive over TLS, counting a terminating proxy?

    `request.url.scheme` is what Starlette resolved after `ProxyHeadersMiddleware`, so a
    deployment behind nginx reports `https` correctly. The explicit `X-Forwarded-Proto`
    read is the fallback for a proxy configuration that did not set the trusted-hosts
    option — reading it is safe HERE because the consequence of getting it wrong is a
    cookie that is MORE restrictive than needed on a request that lied, never less.
    """
    if request.url.scheme == "https":
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def read_token(request: Request, realm: str) -> str | None:
    """The session token this request presents for this realm, if any.

    Tries the secure name first and the stripped one second, so a single deployment can
    serve both without the caller knowing which it is.
    """
    for secure in (True, False):
        token = request.cookies.get(cookie_name(realm, secure=secure))
        if token:
            return token
    return None


def set_session_cookie(response: Response, *, realm: str, token: str, request: Request) -> None:
    """Attach a freshly issued session token."""
    secure = _is_secure(request)
    response.set_cookie(
        key=cookie_name(realm, secure=secure),
        value=token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        # No `max_age`/`expires`: the row is the authority. See the module docstring.
    )


def clear_session_cookie(response: Response, *, realm: str, request: Request) -> None:
    """Remove the cookie on sign-out.

    BOTH names are cleared, not just the one this scheme would set. A deployment that
    gained TLS between a sign-in and a sign-out would otherwise leave the other name
    sitting in the browser — harmless, because the row behind it is revoked either way, but
    it would keep being sent and would keep producing a refusal that looks like a bug.
    """
    for secure in (True, False):
        response.delete_cookie(
            key=cookie_name(realm, secure=secure),
            path="/",
            httponly=True,
            secure=secure,
            samesite="strict",
        )


def enforce_same_origin(request: Request) -> None:
    """Refuse a cross-site mutating request. The CSRF layer that does not need a header.

    Two checks, in the order the OWASP cheat sheet recommends:

    1. **`Sec-Fetch-Site`.** Browsers set it themselves and page script cannot forge it, so
       `cross-site` is a reliable "this came from somewhere else". `same-origin` and
       `same-site` are allowed — `same-site` because `admin.calevate.tech` and
       `app.calevate.tech` are the same site as the API and legitimate traffic reports it.
       `none` is a direct navigation or a tool, and is allowed for the same reason step 2
       exists.
    2. **`Origin` allowlist**, for clients that send no `Sec-Fetch-Site`. An absent `Origin`
       is ALLOWED, and that is not a hole: browsers always send it on cross-origin requests
       with credentials, so absent means either same-origin (older browsers omit it) or a
       non-browser client, which has no ambient cookie to be tricked into replaying.

    The allowlist is `core/bootstrap.DEFAULT_CORS_ORIGINS` — the SAME list the CORS
    middleware is installed with, deliberately, rather than a second one to keep in step.
    That list already carries the invariant this check depends on: `install_middleware`
    raises if it contains a wildcard, because `allow_credentials=True` and `*` cannot both
    be true, so there is no configuration in which this falls through to "allow anything".
    Imported inside the function because `core.bootstrap` imports the router tree that
    imports this module.
    """
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if site == "cross-site":
        log.warning("authn_cross_site_refused", extra={"path": request.url.path})
        raise _cross_site()
    origin = request.headers.get("origin")
    if not origin or site in {"same-origin", "same-site"}:
        return
    from apps.api.core.bootstrap import DEFAULT_CORS_ORIGINS

    if origin.rstrip("/") in {o.rstrip("/") for o in DEFAULT_CORS_ORIGINS}:
        return
    log.warning("authn_foreign_origin_refused", extra={"path": request.url.path})
    raise _cross_site()


def _cross_site() -> ProblemError:
    return ProblemError(
        kind="permission",
        code="cross_site_request",
        title="Request blocked",
        detail="This request did not come from a Calevate console.",
        remediation="Sign in from the Calevate dashboard and try again.",
    )


__all__ = [
    "COOKIE_NAMES",
    "clear_session_cookie",
    "cookie_name",
    "enforce_same_origin",
    "read_token",
    "set_session_cookie",
]
