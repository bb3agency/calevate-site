"""Google Calendar actions — the freebusy/book request builders and the calendar's OAuth.

The platform holds ONE Google Cloud OAuth client (the founder's project); each client
connects their own calendar through it (`oauth.py`, the one flow every connection uses), and
the refresh token is stored as a per-tenant `integration_credentials` row (kind
`google_calendar`). In-call the executor mints an access token from it and then queries
free/busy or inserts an event.

VERIFIED-VENDOR-DOCS, read 9 Oct 2026:

  * Scopes: `calendar.events` ("View and edit events on all your calendars") and
    `calendar.freebusy` ("View your availability in your calendars"),
    developers.google.com/workspace/calendar/api/auth. freeBusy.query accepts
    `calendar.freebusy`; events.insert accepts `calendar.events`.
  * Free/busy: `POST https://www.googleapis.com/calendar/v3/freeBusy` with `timeMin`,
    `timeMax` (RFC 3339), optional `timeZone` (default UTC) and `items[].id`; the answer is
    `calendars.{id}.busy[]` with an inclusive `start` and exclusive `end`
    (…/calendar/api/v3/reference/freebusy/query).
  * Book: `POST …/calendars/{calendarId}/events`, `start`/`end` each with `dateTime`
    (RFC 3339, offset required unless `timeZone` is given) and `timeZone` (IANA name);
    `sendUpdates` is `all`, `externalOnly` or `none` (…/reference/events/insert).

EXTERNAL BLOCKER: nothing here is live until `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI`
are set (OPERATIONS gate A-1). `calendar_configured()` gates every route so it refuses
cleanly rather than half-working.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from apps.api.actions import oauth
from apps.api.actions.schema import PreparedRequest
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

#: How long a consent round trip may take (`oauth.STATE_TTL`).
OAUTH_STATE_TTL: Final = oauth.STATE_TTL

#: Read availability, insert events — no full `calendar` scope, which could delete anything.
CALENDAR_SCOPES = oauth.GOOGLE_CALENDAR_SCOPES

#: Every caller of ours is in India; the calendar is asked and written in India time.
CALENDAR_TIME_ZONE: Final = "Asia/Kolkata"

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


def mint_oauth_state(*, tenant_id: UUID, user_id: UUID, now: datetime | None = None) -> str:
    """The `state` for one consent round trip, bound to the account AND the person
    (`oauth.mint_state`, which argues the CSRF defence)."""
    return oauth.mint_state("google_calendar", tenant_id=tenant_id, user_id=user_id, now=now)


def calendar_state_refused() -> ProblemError:
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


def build_freebusy(
    *, calendar_id: str, time_min: str, time_max: str, access_token: str
) -> PreparedRequest:
    """Busy intervals over a window, asked in India time so the answer reads in it
    (freebusy/query: `timeZone` optional, default UTC; `calendars.{id}.busy[]` start
    inclusive, end exclusive)."""
    return PreparedRequest(
        method="POST",
        url=f"{_API_BASE}/freeBusy",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json_body={
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": CALENDAR_TIME_ZONE,
            "items": [{"id": calendar_id}],
        },
    )


def build_book(
    *,
    calendar_id: str,
    start: str,
    end: str,
    summary: str,
    access_token: str,
    description: str | None = None,
) -> PreparedRequest:
    """Insert an event (events/insert). `start.dateTime` carries an offset and `timeZone`
    is the IANA name, so Google stores it in India time; `sendUpdates=none` because the
    event has no attendees we could invite — the caller is confirmed on the call."""
    from urllib.parse import quote

    body: dict[str, object] = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": CALENDAR_TIME_ZONE},
        "end": {"dateTime": end, "timeZone": CALENDAR_TIME_ZONE},
    }
    if description:
        body["description"] = description
    return PreparedRequest(
        method="POST",
        url=f"{_API_BASE}/calendars/{quote(calendar_id, safe='')}/events?sendUpdates=none",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json_body=body,
    )


__all__ = [
    "CALENDAR_SCOPES",
    "CALENDAR_TIME_ZONE",
    "build_book",
    "build_freebusy",
    "calendar_configured",
    "calendar_state_refused",
    "calendar_unavailable",
    "mint_oauth_state",
]
