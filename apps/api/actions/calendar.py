"""Google Calendar actions — OAuth connect and the freebusy/book request builders.

The platform holds ONE Google Cloud OAuth client (the founder's project); each client
connects their own calendar through it, and the resulting refresh token is stored as a
per-tenant `integration_credentials` row (kind `google_calendar`), with the connected
account email and scopes in `non_secret`. In-call the executor refreshes an access token
from that refresh token and then queries free/busy or inserts an event.

VERIFIED (developers.google.com — the pages are egress-blocked in this environment, so
this is REPORTED from Google's published reference, consistent across their auth and v3
reference pages; OPERATIONS §2 owns a gate to confirm against a live project):

  * OAuth 2.0 web flow: authorize at https://accounts.google.com/o/oauth2/v2/auth with
    `access_type=offline` + `prompt=consent` to get a refresh token; exchange the code and
    refresh at https://oauth2.googleapis.com/token (form-encoded).
  * Scopes: `calendar.events` to insert an event, `calendar.freebusy` to read availability
    (developers.google.com/workspace/calendar/api/auth).
  * Free/busy: POST /calendar/v3/freeBusy with {timeMin, timeMax, items:[{id}]} returns
    busy intervals (…/reference/freebusy/query).
  * Book: POST /calendar/v3/calendars/{calendarId}/events with {summary, start, end}
    (…/reference/events/insert).

EXTERNAL BLOCKER: none of this is live until `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI`
are set (a Google Cloud project + OAuth consent screen — a vendor account, legitimately not
ours to code around per CLAUDE.md tempo). `calendar_configured()` gates every route so it
refuses cleanly rather than half-working.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlencode
from uuid import UUID

import jwt

from apps.api.actions.schema import PreparedRequest
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: How long a consent round trip may take. Google's own authorization codes are short-lived;
#: ten minutes covers a person reading the consent screen without leaving a state usable all day.
OAUTH_STATE_TTL: Final = timedelta(minutes=10)
OAUTH_STATE_AUDIENCE: Final = "calevate:google-calendar-oauth-state"
OAUTH_STATE_ALGORITHM: Final = "HS256"
_STATE_KDF_INFO: Final = b"calevate:google-calendar-oauth-state:v1"
_STATE_REQUIRED_CLAIMS: Final = ("aud", "sub", "act", "exp", "jti")

# Read access to availability + write access to insert an event. Kept minimal — no full
# `calendar` scope, which would let us delete anything (auth page's guidance).
CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://www.googleapis.com/calendar/v3"


def calendar_configured() -> bool:
    """Whether the platform Google OAuth client exists. False disables every calendar path."""
    s = get_settings()
    return bool(
        s.google_oauth_client_id and s.google_oauth_client_secret and s.google_oauth_redirect_uri
    )


def calendar_unavailable() -> ProblemError:
    """The ONE wording of this refusal, and the log line that carries the operator's half.

    Two sites raised it — here and `actions/routes.calendar_connect` — with two copies of
    the same sentence, and both copies were addressed to the wrong person. "This
    deployment has no Google OAuth client configured yet" is read by a clinic owner who
    pressed *Connect Google Calendar*: "deployment" is not their word, a Google Cloud
    OAuth client is not a thing they hold, and neither half tells them what happens next.
    The EXTERNAL BLOCKER in the module docstring is the real ground — this waits on a
    Google Cloud project, which is the founder's to open — so the honest client sentence
    is that it is not connected yet and nobody is waiting on them.

    Which of the three settings is absent is what an operator acts on, and it was in no
    log at all before this. It is here now, named individually rather than as a count so
    a half-filled environment reads as one line rather than a puzzle.
    """
    settings = get_settings()
    log.warning(
        "calendar_not_configured",
        extra={
            "missing": ",".join(
                name
                for name, value in (
                    ("GOOGLE_OAUTH_CLIENT_ID", settings.google_oauth_client_id),
                    ("GOOGLE_OAUTH_CLIENT_SECRET", settings.google_oauth_client_secret),
                    ("GOOGLE_OAUTH_REDIRECT_URI", settings.google_oauth_redirect_uri),
                )
                if not value
            )
            or "none",
        },
    )
    return ProblemError(
        kind="business_rule",
        code="calendar_not_configured",
        title="Calendar booking is not switched on yet",
        detail=(
            "Calevate's link to Google Calendar has not been set up on our side, so an "
            "agent cannot check your diary or book into it yet. Nothing else about your "
            "agents is affected."
        ),
        remediation=(
            "There is nothing for you to set up. Ask your Calevate team when calendar "
            "booking will be ready — quote the reference on this message."
        ),
    )


def _require_configured() -> None:
    if not calendar_configured():
        raise calendar_unavailable()


def _state_key() -> bytes:
    """A purpose-separated subkey of `IMPERSONATION_GRANT_SECRET` (HKDF-Expand, one block).

    The same derivation `copilot/write_tools._signing_key` argues for its proposals, under
    its own `info` label: a short-lived token we mint, hand to our own browser and verify
    back, so a fifth deployment secret would buy nothing but a new readiness key.
    """
    settings = get_settings()
    parent = resolve_hmac_key(
        settings.impersonation_grant_secret,
        env_var="IMPERSONATION_GRANT_SECRET",
        purpose="Google Calendar OAuth state",
        code="calendar_state_not_configured",
        title="Calendar connection is not available",
        local_fallback=f"calevate-local-dev-impersonation-grant-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    return hmac.new(parent, _STATE_KDF_INFO + b"\x01", hashlib.sha256).digest()


def mint_oauth_state(*, tenant_id: UUID, user_id: UUID, now: datetime | None = None) -> str:
    """The `state` for one consent round trip, bound to the account AND the person.

    This is the OAuth CSRF defence (RFC 6749 §10.12, RFC 9700 §2.1): without it, anyone can
    obtain an authorization code for THEIR OWN Google account and get it redeemed by a
    signed-in owner, so the owner's calendar bookings — callers' names and numbers — land
    in the attacker's calendar. A bare tenant id is not a defence because it is not secret.
    Binding the user as well means a state minted by one colleague cannot complete another's.
    """
    at = now or datetime.now(UTC)
    claims = {
        "aud": OAUTH_STATE_AUDIENCE,
        "sub": str(tenant_id),
        "act": str(user_id),
        "jti": str(uuid7()),
        "iat": int(at.timestamp()),
        "exp": int((at + OAUTH_STATE_TTL).timestamp()),
    }
    return jwt.encode(claims, _state_key(), algorithm=OAUTH_STATE_ALGORITHM)


def verify_oauth_state(raw: str, *, tenant_id: UUID, user_id: UUID) -> None:
    """Refuse a `state` this deployment did not mint for this account and this person."""
    try:
        claims = jwt.decode(
            raw,
            _state_key(),
            algorithms=[OAUTH_STATE_ALGORITHM],
            audience=OAUTH_STATE_AUDIENCE,
            options={"require": list(_STATE_REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError as exc:
        log.info("calendar_oauth_state_rejected", extra={"error": type(exc).__name__})
        raise _state_refused() from exc
    if claims.get("sub") != str(tenant_id) or claims.get("act") != str(user_id):
        log.warning("calendar_oauth_state_mismatch")
        raise _state_refused()


def _state_refused() -> ProblemError:
    return ProblemError(
        kind="permission",
        code="calendar_oauth_state_invalid",
        title="This calendar connection was not started here",
        detail=(
            "The connection request did not come from a calendar connection you started "
            "in this account, or it has expired."
        ),
        remediation="Start the connection again from the Actions screen.",
    )


def authorize_url(*, state: str) -> str:
    """The consent URL a client is sent to. `state` is `mint_oauth_state`'s token."""
    _require_configured()
    s = get_settings()
    params = {
        "client_id": s.google_oauth_client_id or "",
        "redirect_uri": s.google_oauth_redirect_uri or "",
        "response_type": "code",
        "scope": " ".join(CALENDAR_SCOPES),
        # A refresh token is issued only with offline access AND a forced consent prompt —
        # without `prompt=consent` a re-authorizing user gets no new refresh token.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def token_exchange_request(*, code: str) -> PreparedRequest:
    """Exchange the authorization code for tokens (the refresh token we store)."""
    _require_configured()
    s = get_settings()
    return PreparedRequest(
        method="POST",
        url=_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form_body={
            "code": code,
            "client_id": s.google_oauth_client_id or "",
            "client_secret": s.google_oauth_client_secret or "",
            "redirect_uri": s.google_oauth_redirect_uri or "",
            "grant_type": "authorization_code",
        },
    )


def token_refresh_request(*, refresh_token: str) -> PreparedRequest:
    """Mint a fresh access token from a stored refresh token (in-call, per action)."""
    _require_configured()
    s = get_settings()
    return PreparedRequest(
        method="POST",
        url=_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form_body={
            "refresh_token": refresh_token,
            "client_id": s.google_oauth_client_id or "",
            "client_secret": s.google_oauth_client_secret or "",
            "grant_type": "refresh_token",
        },
    )


def build_freebusy(
    *, calendar_id: str, time_min: str, time_max: str, access_token: str
) -> PreparedRequest:
    """Availability over a window — busy intervals only (…/freebusy/query)."""
    return PreparedRequest(
        method="POST",
        url=f"{_API_BASE}/freeBusy",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json_body={"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]},
    )


def build_book(
    *, calendar_id: str, start: str, end: str, summary: str, access_token: str
) -> PreparedRequest:
    """Insert an event (…/events/insert). Times are RFC 3339 with an offset."""
    from urllib.parse import quote

    return PreparedRequest(
        method="POST",
        url=f"{_API_BASE}/calendars/{quote(calendar_id, safe='')}/events",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json_body={
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        },
    )


__all__ = [
    "CALENDAR_SCOPES",
    "authorize_url",
    "build_book",
    "build_freebusy",
    "calendar_configured",
    "mint_oauth_state",
    "token_exchange_request",
    "token_refresh_request",
    "verify_oauth_state",
]
