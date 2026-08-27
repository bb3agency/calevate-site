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

from urllib.parse import urlencode

from apps.api.actions.schema import PreparedRequest
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

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


def authorize_url(*, state: str) -> str:
    """The consent URL a client is sent to. `state` carries our CSRF/tenant token."""
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
    "token_exchange_request",
    "token_refresh_request",
]
