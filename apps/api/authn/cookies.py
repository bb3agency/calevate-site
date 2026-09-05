"""How a session token reaches the browser, and how it comes back (D-170).

═══ WHY A COOKIE AND NOT A BEARER TOKEN ═══

Because the token must be unreadable to JavaScript. `apps/web` used to hold a Clerk token
in memory and attach it with `Authorization:`, which is structurally immune to CSRF and
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

**That sentence is only true because `read_token` accepts ONE name per request** (D-198).
A prefix defends nothing while an unprefixed alias of the same cookie is still read: a
sibling host cannot overwrite `__Host-calevate_client_session`, but it can set
`calevate_client_session` with `Domain=.calevate.tech` and have the browser send it here.
See `read_token` for the attack that reached, and for why the stripped name is now honoured
only on a request that did not arrive over TLS.

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

`Max-Age` — **PRESENT ON THE CLIENT REALM, ABSENT ON THE ADMIN REALM (D-539), AND THIS
PARAGRAPH USED TO SAY IT WAS ABSENT ON BOTH.** The old argument was that a `Max-Age` would
be "a second, client-controlled, unenforceable copy" of the row's expiry. That is right
about one failure and silent about the opposite one, which is the one a person actually
reported:

  * **The browser must not be able to END a session.** Unchanged, and nothing below
    weakens it: `verify_session` re-reads the row on every request, and an expired,
    superseded or revoked row is refused whatever the browser presents. A cookie the
    browser keeps for longer than the row lives buys its holder nothing.
  * **The browser must not DISCARD a still-valid credential either.** A cookie with no
    `Max-Age` dies when the browser session does, and on a phone that is not "when the
    person is finished" — iOS and Android reclaim backgrounded tabs, and the cookie goes
    with them. So a client whose row is good for fourteen days was signed out by closing
    a tab. `Max-Age` is the ONLY lever that exists for that, and it is not a second
    authority as long as it is derived from the row rather than chosen: it is bounded by
    `absolute_expires_at`, so the two cannot disagree in the dangerous direction — the row
    can always end the session EARLIER (idle timeout, revocation, reuse detection) and the
    cookie can never outlive the bound the row was born with.

**IT DOES NOT SLIDE WITH THE IDLE WINDOW, AND THAT IS THE DELIBERATE PART.** The row's
`idle_expires_at` slides on every verification (`sessions._verify_within`), but
`absolute_expires_at` is fixed at issue and CARRIED FORWARD unchanged by `rotate_session`.
The cookie is pinned to that fixed instant, so every re-issue of the same session hands the
browser a SHORTER `Max-Age` converging on one moment. Sliding it with the idle window
instead would be the thing the old paragraph feared: a lifetime the client controls, which
could outrun the absolute bound and leave a cookie alive after the only clock that can stop
it has stopped.

**THE TWO REALMS GET DIFFERENT ANSWERS, because their risk is different and their evidence
is different.** The client realm is a business owner on a phone with a 14-day absolute
bound and a 12-hour idle window: persisting is the fix, and the idle window is what bounds
a cookie left on a shared device — an abandoned browser stops being a credential twelve
hours later whether or not the cookie is still on disk. The ADMIN realm is 30 minutes idle
and 8 hours absolute, holds operator powers over every tenant, and is used on a laptop. A
persistent cookie there could survive at most the remainder of one shift, which is not a
usability problem anybody reported, and it would put an operator credential on disk across
a browser restart on whatever machine is to hand. So `admin` stays a session cookie. The
split is data (`COOKIE_PERSISTENCE`), not a conditional at a call site.

**WHAT THE BROWSER ACTUALLY GUARANTEES: LESS THAN THE HEADER ASKS FOR, AND THE PRODUCT IS
CORRECT EITHER WAY.** `Max-Age` is a request. Reported (web search, 5 Sep 2026, secondary
sources only — `webkit.org`, `datatracker.ietf.org`, `developer.mozilla.org` and
`developer.chrome.com` are ALL egress-blocked from this container, so none of this is
VERIFIED-VENDOR-DOCS and it must not be restated as fact): Safari's ITP caps first-party
cookies set from `document.cookie` at 7 days and server-set `Set-Cookie` cookies are not
capped that way, and Chrome since 104 rewrites any expiry beyond 400 days down to 400.
Neither bound is load-bearing here — ours is `HttpOnly`, so script CANNOT have set it, and
14 days is far under 400 — but the design does not depend on being right about that: if a
browser ignores or shortens the `Max-Age`, the person is asked to sign in sooner than the
row would have required, which is exactly today's behaviour and is the safe direction. No
code branch anywhere reads the cookie's lifetime; the row remains the only clock.

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

OWASP's CSRF Prevention Cheat Sheet (re-read 2026-08-17) is explicit that `SameSite` is
defence in depth rather than sufficient, and that `Sec-Fetch-Site` rejection with `Origin`
verification is a recommended layer. Both are here, in `enforce_same_origin`.

**THE SIGNED DOUBLE-SUBMIT TOKEN IS NOT BUILT, AND IS NOT OUTSTANDING (D-178).** It was
listed as a gap; it has been argued away instead, and the argument is worth stating where
somebody will look for the header.

The cheat sheet names the conditions under which origin verification plus `SameSite` is
sufficient without a token: no shared registrable domain, no state change via GET,
`SameSite=Strict`, `Origin`/`Referer` verified, and the browser-support gap accepted. This
deployment meets four of the five outright — `Strict` above, no GET mutates (the route
table is walked by `tests/edge_route_policy_test.py`), verification below, and there is no
legacy-browser population for a product that has not launched. **The one it did NOT meet was
the first**, and that was a real hole rather than a caveat: three consoles under one
registrable domain mean a compromised `*.calevate.tech` host issues requests the browser
calls `same-site`, which `enforce_same_origin` used to wave through. That is fixed by
checking the `Origin` unconditionally — see that function — which is the SAME defence a
double-submit token would have provided against the SAME attacker, without a secret to
distribute, a header for `apps/web` to attach, or a rotation story.

What a token would still add, honestly: it would survive a same-site attacker who can also
suppress or forge the `Origin` header, which a browser does not permit page script to do.
Buying that would cost a signed value in a second cookie, a header on every mutating request
in the generated client, and — the reason it is a bad trade here — a "what if it is absent"
branch, which is either a header nothing sends (every mutating request fails) or a check
that passes when absent (defends nothing). AUTH-MIGRATION §11 no longer promises it.

`core/middleware.CookieCsrfMiddleware` applies this same check to EVERY mutating request
that arrives with one of these cookies, not just to the routes in `authn/routes.py`, so the
paragraph above stays true of the whole API on the day cookies authenticate the whole API.
"""

from __future__ import annotations

from datetime import UTC, datetime
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

#: Does this realm's cookie SURVIVE the browser closing? (D-539.)
#:
#: Data rather than a conditional at the call site, for the reason `REALM_TIMEOUTS` is:
#: the two realms differ, and the difference is a posture that should be readable in one
#: place and assertable in one test. The argument for each answer is in the module
#: docstring, under `Max-Age`. `tests/authn_cookie_persistence_test.py` asserts the map
#: covers exactly `AUTHN_REALMS`, so a third realm cannot arrive without a decision.
COOKIE_PERSISTENCE: Final[dict[str, bool]] = {"admin": False, "client": True}


def _refuse_unknown_realm(realm: str) -> None:
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm")


def cookie_name(realm: str, *, secure: bool = True) -> str:
    """The cookie this realm's session lives in."""
    _refuse_unknown_realm(realm)
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

    ONE NAME PER REQUEST, CHOSEN BY THE SCHEME THE REQUEST ARRIVED ON — not both names
    tried in order, which is what this did and which quietly gave back everything the
    `__Host-` prefix was bought for (D-198).

    The prefix's whole value, stated at the top of this module, is that "no sibling
    subdomain and no compromised `*.calevate.tech` host can set or overwrite it". That is
    true of the PREFIXED name and of nothing else: a page on any host under the registrable
    domain may set `calevate_client_session=<value>; Domain=.calevate.tech; Path=/`, and the
    browser then attaches it to `api.calevate.tech`. While the stripped name was accepted on
    an HTTPS request, that cookie WAS a credential — so the prefix stopped a sibling
    overwriting the cookie and did not stop it supplying one.

    What that bought an attacker, end to end: a visitor who is not signed in arrives at the
    console carrying the attacker's session token, is silently signed in as the attacker,
    and types their own data into the attacker's tenant. It survives sign-out, because
    `clear_session_cookie` can only delete a HOST-ONLY cookie — a `Domain=`-scoped one is a
    different cookie to the browser and is still sent on the next request, so the victim is
    signed back into the attacker's account without a second visit. That is OWASP's session
    fixation (Session Management Cheat Sheet, "Renew the Session ID After Any Privilege
    Level Change" and its cookie-prefix guidance) arriving through the one door the design
    left open, and rotation on sign-in cannot close it because the fixated session is never
    the victim's to rotate.

    The stripped name exists for exactly one deployment — plain-HTTP local development,
    where a browser refuses a `__Host-` cookie outright — so it is honoured on exactly that
    request and no other. `_is_secure` is the same predicate `set_session_cookie` uses to
    decide which name to WRITE, so read and write cannot disagree about which name this
    deployment speaks.

    Rejected: keeping the fallback and comparing the two values, or preferring the prefixed
    one. Both leave the stripped name a live credential whenever there is no prefixed one to
    prefer — which is precisely the signed-out visitor the attack targets.

    FOUND TWICE, INDEPENDENTLY (D-198, and again as D-330 by a red-team pass that branched
    before the fix landed). The second pass drove it over HTTP against a live MFA-complete
    admin session and reached the same conclusion by a different route, which is worth
    recording: the defect was not subtle to anyone who looked, only to a reader of the
    module docstring who took "the prefix defends against fixation" as covering the
    fallback the next function down was doing. That pass's variant also accepted the
    PREFIXED name on a plain-HTTP request; this one does not, because a browser will not
    send a `__Host-` cookie over cleartext anyway and a name that cannot legitimately
    arrive should not be read.

    A deployment that gains TLS between a sign-in and the next request stops reading the
    cookie it wrote and the person signs in again. That is the safe direction, it happens
    once per deployment, and `clear_session_cookie` still clears both names so nothing is
    left rotting in the browser.
    """
    token = request.cookies.get(cookie_name(realm, secure=_is_secure(request)))
    return token or None


def session_cookie_max_age(
    realm: str, *, absolute_expires_at: datetime, now: datetime | None = None
) -> int | None:
    """How long the browser is asked to keep this realm's cookie, or `None` for "until it closes".

    DERIVED FROM THE ROW, never chosen. The whole reason a `Max-Age` is defensible here is
    that this function has no number of its own to disagree with `absolute_expires_at`: it
    reports the distance to that instant and nothing else. See the module docstring.

    `None` for a realm `COOKIE_PERSISTENCE` says does not persist — a session cookie, as
    before.

    A non-positive result is returned AS ZERO rather than clamped up. Zero tells the
    browser to drop the cookie immediately, which is the truth: the row it names is already
    past its absolute bound and `verify_session` will refuse the token on the next request
    anyway. Clamping to one second would hand out a credential we know is dead; raising
    would turn a clock skew into a failed sign-in.
    """
    _refuse_unknown_realm(realm)
    if not COOKIE_PERSISTENCE[realm]:
        return None
    at = now or datetime.now(UTC)
    return max(0, int((absolute_expires_at - at).total_seconds()))


def set_session_cookie(
    response: Response,
    *,
    realm: str,
    token: str,
    request: Request,
    absolute_expires_at: datetime,
    now: datetime | None = None,
) -> None:
    """Attach a freshly issued session token.

    `absolute_expires_at` is REQUIRED and comes from the row that was just written
    (`sessions.IssuedSession`), so there is no call site that can set this cookie without
    the bound it must not outlive.
    """
    secure = _is_secure(request)
    max_age = session_cookie_max_age(realm, absolute_expires_at=absolute_expires_at, now=now)
    response.set_cookie(
        key=cookie_name(realm, secure=secure),
        value=token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        # `None` leaves the header without `Max-Age` — a browser-session cookie, which is
        # what the admin realm still gets. See the module docstring for both halves.
        max_age=max_age,
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


def session_cookie_present(cookie_header: str | None) -> bool:
    """Does this raw `Cookie:` header carry one of our session cookies, under either name?

    A substring test on the raw header rather than a parse, deliberately: this runs in a
    middleware on every mutating request, the names are long and distinctive, and a false
    POSITIVE only means the origin check runs on a request that would have passed it anyway.
    A parse would cost more and buy a precision this decision does not need.
    """
    if not cookie_header:
        return False
    return any(
        cookie_name(realm, secure=secure) in cookie_header
        for realm in AUTHN_REALMS
        for secure in (True, False)
    )


def session_cookie_value(cookie_header: str | None) -> str | None:
    """A stable bucket key for EVERY session cookie of ours in this raw `Cookie:` header.

    A REAL PARSE, unlike `session_cookie_present` above, and the difference is the point:
    that function answers "should the origin check run", where a false positive costs a
    check that would have passed anyway. This one answers "which bucket does this request
    count against", where a wrong answer silently merges two callers' budgets — so a
    substring test that matched a cookie named `x__Host-calevate_client_session_backup`
    would be a defect rather than a harmless over-approximation.

    THE VALUE IS NEVER AUTHENTICATED HERE and must not be treated as a credential. This
    runs before routing and before authentication, exactly like the bearer-token read it
    sits beside — nothing at this layer can tell a session from a guess. It is a bucket
    key, it is fingerprinted before use, and the mint is charged to the address for the
    reason `RateLimitMiddleware._subjects` gives at length.

    ═══ IT RETURNS ALL OF THEM, ORDER-INDEPENDENTLY, AND THAT IS A CORRECTION ═══

    This used to return the FIRST match in header order, on the stated ground that "a
    browser sends at most one of ours per request (the two realms are two hostnames)" and
    that "a request carrying both is already outside the model". **Both halves were false,
    and this module's own docstring says so eighty lines up**: the two consoles talk to ONE
    API host, so both cookies land on that host, and the two names exist precisely "so that
    being signed into both consoles at once works at all". An operator signed into
    `admin.` and `app.` at the same time — the founder, on any day they look at a client's
    screen — sends both on every request to `api.`, which is the designed case and not an
    excursion from the model.

    What the old spelling did with it: RFC 6265 §5.4 orders equal-path cookies by CREATION
    time, so which of the two answered depended on which console had been signed into
    first, and signing into that one again silently moved the pair to a different bucket
    mid-session. A rate limiter whose bucket moves when nothing about the caller changed is
    the defect class `charge_tenant_quota` names ("a limiter that does not mean what it
    says", D-131's per-process `hash()` seed) arriving through the cookie arm.

    So the key covers the whole SET, sorted by name, and never the header's order. Two
    consequences, both deliberate:

      * **Two live consoles are ONE caller with ONE budget.** That is the conservative
        direction and the one `_subjects` already commits to — "presenting a credential
        never buys more room than presenting none" — so being signed in twice must not
        double a ceiling. Splitting the pair into two budgets is the change this refuses.
      * **Signing out of one realm moves the pair to the remaining realm's own bucket.**
        A fresh bucket costs one unit of the address bucket (the mint charge), once, which
        is exactly what any other new credential costs.

    Returns `None` when the header carries none of ours — the caller then IS the address.
    """
    if not cookie_header:
        return None
    wanted = {
        cookie_name(realm, secure=secure) for realm in AUTHN_REALMS for secure in (True, False)
    }
    present: set[str] = set()
    for pair in cookie_header.split(";"):
        name, sep, value = pair.partition("=")
        key = name.strip()
        if not sep or key not in wanted:
            continue
        # RFC 6265 permits a quoted cookie-value; strip the quotes so the same session
        # cannot occupy two buckets depending on how the browser wrote it.
        candidate = value.strip().strip('"')
        if candidate:
            present.add(f"{key}={candidate}")
    if not present:
        return None
    # A SET joined in sorted order, not a list in arrival order: a browser may legitimately
    # send two of these (see above), and a host-only cookie sitting beside a same-named one
    # from a sibling host is a duplicate this must also answer the same way every time.
    return "\x00".join(sorted(present))


def cross_site_refusal(
    *, sec_fetch_site: str | None, origin: str | None, own_origin: str | None, path: str
) -> ProblemError | None:
    """THE rule, as a pure function, so the route guard and the middleware cannot diverge.

    Returns the refusal rather than raising it, because one caller is an ASGI middleware
    that has to render a response itself rather than let an exception cross the boundary.
    `enforce_same_origin` is the raising face for route code.
    """
    site = (sec_fetch_site or "").strip().lower()
    if site == "cross-site":
        log.warning("authn_cross_site_refused", extra={"path": path})
        return _cross_site()
    if not origin:
        return None
    from apps.api.core.bootstrap import cors_origins_for_env

    allowed = {o.rstrip("/") for o in cors_origins_for_env()}
    if own_origin:
        allowed.add(own_origin.rstrip("/"))
    if origin.rstrip("/") in allowed:
        return None
    log.warning("authn_foreign_origin_refused", extra={"path": path})
    return _cross_site()


def enforce_same_origin(request: Request) -> None:
    """Refuse a cross-site mutating request. The CSRF layer that does not need a header.

    Two checks, in the order the OWASP cheat sheet recommends:

    1. **`Sec-Fetch-Site`.** Browsers set it themselves and page script cannot forge it, so
       `cross-site` is a reliable "this came from somewhere else". `none` is a direct
       navigation or a tool, and is allowed for the same reason step 2 exists.
    2. **`Origin` allowlist**, ALWAYS, whenever an `Origin` is present. An absent `Origin`
       is allowed, and that is not a hole: browsers always send it on cross-origin requests
       with credentials, so absent means either same-origin (older browsers omit it) or a
       non-browser client, which has no ambient cookie to be tricked into replaying.

    ═══ WHY `same-site` IS NO LONGER AN EARLY EXIT (D-178) ═══

    It used to be. `Sec-Fetch-Site: same-origin | same-site` returned before the allowlist
    was consulted, and that left the one CSRF path this deployment's topology actually
    has open. OWASP's CSRF cheat sheet (re-read 2026-08-17) lists the conditions under
    which `SameSite` alone suffices and the FIRST of them is **no shared registrable
    domain**. Ours is shared by construction: `admin.calevate.tech`, `app.calevate.tech`
    and `api.calevate.tech` are one site (draft-ietf-httpbis-rfc6265bis decides "same
    site" by registrable domain), so a page on ANY `*.calevate.tech` host — a compromised
    marketing subdomain, a dangling CNAME, a takeover of something nobody thought was
    security-relevant — issues a request the browser labels `same-site` and attaches the
    session cookie to. `SameSite=Strict` does not stop it, because it is not cross-site.
    `__Host-` does not stop it, because that prefix stops a sibling SETTING the cookie,
    not the browser SENDING it.

    Checking the `Origin` unconditionally closes it: that sibling's origin is not
    `admin.calevate.tech` and is not in the allowlist. The request's OWN origin is
    accepted alongside the list, which is what `same-origin` used to buy — the API host is
    not in `DEFAULT_CORS_ORIGINS` (that list names the marketing site and the two
    consoles), so without this the tightening would refuse a legitimate same-origin call.

    The allowlist is `core/bootstrap.DEFAULT_CORS_ORIGINS` — the SAME list the CORS
    middleware is installed with, deliberately, rather than a second one to keep in step.
    That list already carries the invariant this check depends on: `install_middleware`
    raises if it contains a wildcard, because `allow_credentials=True` and `*` cannot both
    be true, so there is no configuration in which this falls through to "allow anything".
    Imported inside the function because `core.bootstrap` imports the router tree that
    imports this module.
    """
    # The API's own origin is added to the allowlist, so a same-origin call is not refused
    # by a list that names only the consoles. `request.base_url` is what Starlette resolved
    # after the proxy headers, i.e. the scheme and host the caller actually addressed.
    refusal = cross_site_refusal(
        sec_fetch_site=request.headers.get("sec-fetch-site"),
        origin=request.headers.get("origin"),
        own_origin=str(request.base_url),
        path=request.url.path,
    )
    if refusal is not None:
        raise refusal


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
    "COOKIE_PERSISTENCE",
    "clear_session_cookie",
    "cookie_name",
    "cross_site_refusal",
    "enforce_same_origin",
    "read_token",
    "session_cookie_max_age",
    "session_cookie_present",
    "session_cookie_value",
    "set_session_cookie",
]
