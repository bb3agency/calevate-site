"""Sign in with Google: OpenID Connect authorization code flow, client realm only (D-703).

Google vouches for WHO the person is; Calevate still mints its own session (`sessions.py`)
and Google holds no session of ours. The flow, against Google's OIDC guide
(developers.google.com/identity/openid-connect/openid-connect, read 10 Oct 2026):

1. `begin` builds the authorization URL: scope `openid email profile` only (Calendar and
   Sheets are asked for later, on the same account, by `actions/oauth.py`), `prompt=
   select_account`, a `state`, an OIDC `nonce`, and a PKCE S256 challenge (Google's
   discovery document lists `S256` in `code_challenge_methods_supported`).
2. Google returns the person to `google_signin_redirect_uri`, a page in the client console
   that POSTs the `code` and `state` to `finish`.
3. `finish` exchanges the code at `https://oauth2.googleapis.com/token` with our client
   secret and the PKCE verifier, then checks the ID token's `iss`, `aud`, `exp` and `nonce`.

LOGIN CSRF. A `state` alone does not stop an attacker completing THEIR Google sign-in in a
victim's browser. So `begin` also returns a random browser nonce that the route sets as an
HttpOnly cookie, the `state` carries its hash, and the `nonce` and PKCE verifier are both
derived from it: a code started in another browser cannot be finished in this one.

THE ID TOKEN'S SIGNATURE IS NOT CHECKED, deliberately: it comes straight from Google's
token endpoint over TLS in exchange for our client secret, and Google's guide says such a
token can be trusted for that reason. It is used here and passed nowhere else, which is the
condition the same guide attaches.

WHO SIGNS IN. The Google `sub` is the key (`auth_identities`), never the email. A first
sign-in links to an existing account only when Google says `email_verified` and the address
matches one live account; with no account, it creates one only when self-serve signup is
open. An unverified Google email never opens or links anything.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import text

from apps.api.authn.sessions import IssuedSession, issue_session
from apps.api.authn.subjects import (
    create_verified_client,
    load_subject,
    mark_email_verified,
    resolve_by_email,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.db.base import uuid7
from apps.api.db.session import credential_session
from apps.api.integrations.egress_guard import egress_client

log = get_logger(__name__)

GOOGLE_AUTH_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL: Final = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS: Final = frozenset({"https://accounts.google.com", "accounts.google.com"})
SIGN_IN_SCOPES: Final = ("openid", "email", "profile")
REALM: Final = "client"
PROVIDER: Final = "google"

STATE_TTL: Final = timedelta(minutes=10)
#: Clock skew tolerated on the ID token's `exp` and `iat`.
LEEWAY_S: Final = 60
EXCHANGE_TIMEOUT_S: Final = 10.0
#: The browser-binding cookie. `__Host-` pins it to the API host (no Domain, Path=/).
BINDING_COOKIE: Final = "__Host-calevate_google_signin"
_STATE_AUDIENCE: Final = "calevate:google-sign-in"
_KDF_INFO: Final = b"calevate:google-sign-in:v1"
_ALGORITHM: Final = "HS256"
_NEXT_MAX: Final = 512


@dataclass(frozen=True, slots=True)
class Begun:
    authorize_url: str
    #: Set as `BINDING_COOKIE`; never shown to page script.
    browser_nonce: str


@dataclass(frozen=True, slots=True)
class SignedIn:
    subject_id: Any
    session: IssuedSession
    #: The relative path the person asked to return to, already vetted.
    next_path: str | None
    created: bool
    linked: bool


# --- configuration ---------------------------------------------------------------------


def configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret)


def _redirect_uri() -> str | None:
    return get_settings().google_signin_redirect_uri


def _unavailable() -> ProblemError:
    missing = [
        name
        for name, value in (
            ("GOOGLE_OAUTH_CLIENT_ID", get_settings().google_oauth_client_id),
            ("GOOGLE_OAUTH_CLIENT_SECRET", get_settings().google_oauth_client_secret),
            ("GOOGLE_SIGNIN_REDIRECT_URI", _redirect_uri()),
        )
        if not value
    ]
    log.warning("google_sign_in_not_configured", extra={"missing": ",".join(missing)})
    return ProblemError(
        kind="business_rule",
        code="google_sign_in_unavailable",
        title="Google sign-in is not available yet",
        detail="Signing in with Google has not been switched on yet.",
        remediation="Sign in with your email address and password instead.",
    )


def require_configured() -> None:
    if not (configured() and _redirect_uri()):
        raise _unavailable()


# --- the browser-bound secrets ---------------------------------------------------------


def _key() -> bytes:
    settings = get_settings()
    parent = resolve_hmac_key(
        settings.impersonation_grant_secret,
        env_var="IMPERSONATION_GRANT_SECRET",
        purpose="Google sign-in state",
        code="google_sign_in_unavailable",
        title="Google sign-in is not available yet",
        local_fallback=f"calevate-local-dev-impersonation-grant-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    return hmac.new(parent, _KDF_INFO + b"\x01", hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _derive(label: bytes, browser_nonce: str) -> str:
    return _b64(hmac.new(_key(), label + b"\x00" + browser_nonce.encode(), hashlib.sha256).digest())


def _binding(browser_nonce: str) -> str:
    return hashlib.sha256(browser_nonce.encode()).hexdigest()


def pkce_verifier(browser_nonce: str) -> str:
    """43 characters of the RFC 7636 alphabet, derived so nothing has to be stored."""
    return _derive(b"pkce", browser_nonce)


def oidc_nonce(browser_nonce: str) -> str:
    return _derive(b"nonce", browser_nonce)


def safe_next(raw: str | None) -> str | None:
    """A same-site relative path, or None. Refuses `//host`, `/\\host` and schemes."""
    if not raw or any(ch in raw for ch in "\r\n\t"):
        return None
    value = raw.strip()
    if (
        not value.startswith("/")
        or value.startswith("//")
        or value.startswith("/\\")
        or len(value) > _NEXT_MAX
    ):
        return None
    return value


# --- step 1 ----------------------------------------------------------------------------


def begin(*, next_path: str | None, now: datetime | None = None) -> Begun:
    require_configured()
    at = now or datetime.now(UTC)
    browser_nonce = secrets.token_urlsafe(32)
    state = jwt.encode(
        {
            "aud": _STATE_AUDIENCE,
            "bnd": _binding(browser_nonce),
            "nxt": safe_next(next_path),
            "jti": str(uuid7()),
            "iat": int(at.timestamp()),
            "exp": int((at + STATE_TTL).timestamp()),
        },
        _key(),
        algorithm=_ALGORITHM,
    )
    challenge = _b64(hashlib.sha256(pkce_verifier(browser_nonce).encode()).digest())
    params = {
        "client_id": get_settings().google_oauth_client_id or "",
        "redirect_uri": _redirect_uri() or "",
        "response_type": "code",
        "scope": " ".join(SIGN_IN_SCOPES),
        "state": state,
        "nonce": oidc_nonce(browser_nonce),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return Begun(
        authorize_url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}", browser_nonce=browser_nonce
    )


# --- step 3 ----------------------------------------------------------------------------


def _refused(code: str, title: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(kind="auth", code=code, title=title, detail=detail, remediation=remediation)


def _not_started_here() -> ProblemError:
    return _refused(
        "google_sign_in_expired",
        "That Google sign-in did not finish",
        "The sign-in was started in another browser, or it took longer than ten minutes.",
        "Choose Continue with Google again.",
    )


def _google_refused() -> ProblemError:
    return _refused(
        "google_sign_in_failed",
        "Google did not confirm the sign-in",
        "Google did not hand back a sign-in we could use.",
        "Choose Continue with Google again, or sign in with your email address.",
    )


def _state_claims(state: str, browser_nonce: str | None) -> dict[str, Any]:
    if not browser_nonce:
        raise _not_started_here()
    try:
        claims: dict[str, Any] = jwt.decode(
            state,
            _key(),
            algorithms=[_ALGORITHM],
            audience=_STATE_AUDIENCE,
            options={"require": ["aud", "bnd", "exp", "jti"]},
        )
    except jwt.PyJWTError as exc:
        log.info("google_sign_in_state_rejected", extra={"error": type(exc).__name__})
        raise _not_started_here() from exc
    if not hmac.compare_digest(str(claims.get("bnd", "")), _binding(browser_nonce)):
        log.warning("google_sign_in_binding_mismatch")
        raise _not_started_here()
    return claims


async def _exchange(code: str, browser_nonce: str, client: httpx.AsyncClient | None) -> str:
    settings = get_settings()
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.google_oauth_client_id or "",
        "client_secret": settings.google_oauth_client_secret or "",
        "redirect_uri": _redirect_uri() or "",
        "code_verifier": pkce_verifier(browser_nonce),
    }
    http = client or egress_client(timeout=EXCHANGE_TIMEOUT_S, follow_redirects=False)
    try:
        response = await http.post(GOOGLE_TOKEN_URL, data=form)
    except httpx.HTTPError as exc:
        log.warning("google_sign_in_exchange_unreachable", extra={"error": type(exc).__name__})
        raise ProblemError(
            kind="transient",
            code="google_unreachable",
            title="Google did not answer",
            detail="We could not reach Google to finish signing you in.",
            remediation="Try again in a moment.",
        ) from exc
    finally:
        if client is None:
            await http.aclose()
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code != 200 or not isinstance(body, dict) or not body.get("id_token"):
        error = body.get("error") if isinstance(body, dict) else None
        log.info(
            "google_sign_in_exchange_refused",
            extra={"status": response.status_code, "error": str(error or "")[:64]},
        )
        raise _google_refused()
    return str(body["id_token"])


def verify_id_token(
    id_token: str, *, browser_nonce: str, now: datetime | None = None
) -> dict[str, Any]:
    """The claims of an ID token from Google's token endpoint, after the guide's checks."""
    at = int((now or datetime.now(UTC)).timestamp())
    try:
        claims: dict[str, Any] = jwt.decode(id_token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise _google_refused() from exc
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    checks = {
        "iss": claims.get("iss") in GOOGLE_ISSUERS,
        "aud": get_settings().google_oauth_client_id in audiences,
        "exp": isinstance(claims.get("exp"), int | float) and claims["exp"] + LEEWAY_S > at,
        "nonce": hmac.compare_digest(str(claims.get("nonce", "")), oidc_nonce(browser_nonce)),
        "sub": isinstance(claims.get("sub"), str) and 0 < len(claims["sub"]) <= 255,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        log.warning("google_sign_in_id_token_rejected", extra={"failed": ",".join(failed)})
        raise _google_refused()
    return claims


async def _identity_subject(provider_subject: str) -> Any | None:
    async with credential_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT subject_id FROM auth_identities "
                    "WHERE provider = :p AND provider_subject = :s"
                ),
                {"p": PROVIDER, "s": provider_subject},
            )
        ).first()
    return row[0] if row is not None else None


async def _link(subject_id: Any, provider_subject: str, at: datetime) -> None:
    """Attach this Google account. One Google account per person: a second, different
    Google account for someone already linked is refused rather than replacing the first."""
    async with credential_session() as session:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO auth_identities (id, realm, subject_id, provider, "
                    "provider_subject, created_at, updated_at) "
                    "VALUES (:id, :realm, :sub, :p, :ps, :at, :at) "
                    "ON CONFLICT DO NOTHING RETURNING id"
                ),
                {
                    "id": uuid7(),
                    "realm": REALM,
                    "sub": subject_id,
                    "p": PROVIDER,
                    "ps": provider_subject,
                    "at": at,
                },
            )
        ).first()
    if inserted is None:
        log.warning("google_sign_in_link_conflict", extra={"user_id": str(subject_id)})
        raise _refused(
            "google_account_mismatch",
            "This account uses a different Google account",
            "Your Calevate account is already linked to another Google account.",
            "Choose that Google account, or sign in with your email address and password.",
        )


async def finish(
    *,
    code: str,
    state: str,
    browser_nonce: str | None,
    signup_open: bool,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> SignedIn:
    """Finish a Google sign-in and start a Calevate session. See the module docstring."""
    require_configured()
    at = now or datetime.now(UTC)
    claims = _state_claims(state, browser_nonce)
    assert browser_nonce is not None  # `_state_claims` refuses a missing one
    id_claims = verify_id_token(
        await _exchange(code, browser_nonce, client), browser_nonce=browser_nonce, now=at
    )
    sub = str(id_claims["sub"])
    email = str(id_claims.get("email") or "").strip()
    verified = id_claims.get("email_verified") is True

    created = linked = False
    subject_id = await _identity_subject(sub)
    if subject_id is not None:
        if await load_subject(REALM, subject_id) is None:
            log.info("google_sign_in_inactive_account", extra={"user_id": str(subject_id)})
            raise _refused(
                "account_unavailable",
                "This account cannot sign in",
                "The Calevate account linked to this Google account is not active.",
                "Ask your workspace owner, or write to us.",
            )
    else:
        if not verified or not email:
            log.info("google_sign_in_email_unverified")
            raise _refused(
                "google_email_unverified",
                "Google has not verified this email address",
                "We can only use a Google account whose email address Google has verified.",
                "Verify the address with Google, or sign in with your email and password.",
            )
        existing = await resolve_by_email(REALM, email)
        if existing is not None:
            subject_id = existing.subject_id
            await _link(subject_id, sub, at)
            if existing.email_verified_at is None:
                await mark_email_verified(REALM, subject_id, at=at)
            linked = True
        else:
            if not signup_open:
                raise _refused(
                    "no_account_for_google",
                    "There is no Calevate account for this Google account",
                    "No Calevate account uses this Google account's email address.",
                    "Use the invitation your workspace owner sent, or write to us.",
                )
            name = str(id_claims.get("name") or "").strip()[:120] or None
            subject_id = await create_verified_client(email=email, name=name, at=at)
            if subject_id is None:
                # Created between our read and our write: the address is proved, so link.
                raced = await resolve_by_email(REALM, email)
                if raced is None:
                    raise _google_refused()
                subject_id = raced.subject_id
                linked = True
            else:
                created = True
            await _link(subject_id, sub, at)

    async with credential_session() as session:
        issued = await issue_session(session, realm=REALM, subject_id=subject_id, now=at)
    return SignedIn(
        subject_id=subject_id,
        session=issued,
        next_path=safe_next(claims.get("nxt")),
        created=created,
        linked=linked,
    )


__all__ = [
    "BINDING_COOKIE",
    "GOOGLE_AUTH_URL",
    "GOOGLE_TOKEN_URL",
    "SIGN_IN_SCOPES",
    "STATE_TTL",
    "Begun",
    "SignedIn",
    "begin",
    "configured",
    "finish",
    "oidc_nonce",
    "pkce_verifier",
    "require_configured",
    "safe_next",
    "verify_id_token",
]
