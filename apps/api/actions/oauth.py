"""OAuth connections a client makes in Calevate: Google Calendar, Zoho CRM and HubSpot.

ONE flow for all three (D-700). The platform holds one OAuth app per vendor (the founder
registers them, OPERATIONS gates A-1..A-3); each client consents once, and the refresh token
that comes back is sealed as that client's `integration_credentials` row, whose `kind` is
the provider key below. Executing an action mints a short-lived access token from it.

THE STATE is the OAuth CSRF defence (RFC 6749 §10.12, RFC 9700 §2.1): a signed, ten-minute
token bound to the account AND the person who pressed Connect, under a per-provider audience
and key, so a state minted for one vendor or one colleague cannot complete another. Google's
audience and key label are the ones `calendar.py` has always minted under, so a consent in
flight across a deploy still completes.

Vendor facts, each read on the vendor's own page on 9 Oct 2026:

* Google: authorize `https://accounts.google.com/o/oauth2/v2/auth` with `access_type=offline`
  and `prompt=consent`; token and refresh `POST https://oauth2.googleapis.com/token`
  (form); revoke `POST https://oauth2.googleapis.com/revoke` with `token`
  (developers.google.com/identity/protocols/oauth2/web-server). A refresh token is "only
  returned on the first authorization", which is why `prompt=consent` is sent.
* Zoho: authorize `{accounts}/oauth/v2/auth?scope=..&client_id=..&response_type=code&
  access_type=offline&redirect_uri=..&prompt=consent`; the redirect returns `code`,
  `location` and `accounts-server`, and the token call goes to THAT server:
  `POST {accounts-server}/oauth/v2/token` (form), answering `api_domain` beside the tokens
  (zoho.com/accounts/protocol/oauth/web-apps/authorization.html, zoho.com/crm/developer/docs/
  api/v8/access-refresh.html, .../refresh.html). Revoke: `POST {accounts-server}/oauth/v2/
  revoke/token`, Basic client_id:client_secret, form `token`
  (zoho.com/accounts/protocol/oauth/revoke-refresh-token.html). Scopes are comma-separated
  (zoho.com/crm/developer/docs/api/v8/scopes.html); search additionally needs
  `ZohoSearch.securesearch.READ` (…/v8/search-records.html).
* HubSpot: authorize `https://app.hubspot.com/oauth/authorize` with space-separated scopes;
  token and refresh `POST https://api.hubapi.com/oauth/v3/token` (form), answering
  `expires_in` 1800 (developers.hubspot.com/docs/apps/developer-platform/build-apps/
  authentication/oauth/oauth-quickstart-guide). ⚠ HubSpot's v1 migration guide names a
  date-versioned `/oauth/2026-03/token` instead; the two pages disagree and OPERATIONS gate
  A-3 confirms which one the registered app answers on. HubSpot's revoke body is not
  documented on a page we could read, so a disconnect asks the client to uninstall the app
  in HubSpot rather than guessing a wire field.

The accounts server Zoho names is CHECKED against Zoho's published data-centre hosts
(zoho.com/accounts/protocol/oauth/multi-dc.html) before our client secret is sent to it: a
forged redirect naming another host would otherwise receive the secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import jwt

from apps.api.actions.schema import PreparedRequest
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.db.base import uuid7

log = get_logger(__name__)

OAuthKind = Literal["google_calendar", "google_sheets", "zoho_crm", "hubspot"]
OAUTH_KINDS: Final[tuple[OAuthKind, ...]] = (
    "google_calendar",
    "google_sheets",
    "zoho_crm",
    "hubspot",
)
#: The two Google connections share one OAuth client and ask for their scopes separately,
#: on the account the person signs in with (incremental authorization, D-703).
GOOGLE_KINDS: Final = frozenset({"google_calendar", "google_sheets"})

STATE_TTL: Final = timedelta(minutes=10)
_STATE_ALGORITHM: Final = "HS256"
_STATE_REQUIRED_CLAIMS: Final = ("aud", "sub", "act", "exp", "jti")

GOOGLE_AUTH_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL: Final = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL: Final = "https://oauth2.googleapis.com/revoke"
HUBSPOT_AUTH_URL: Final = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL: Final = "https://api.hubapi.com/oauth/v3/token"

#: Google Calendar: read availability, insert events. No full `calendar` scope.
GOOGLE_CALENDAR_SCOPES: Final = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
)
#: Google Sheets: `drive.file` only, a NON-SENSITIVE scope that reaches just the files the
#: client opens with Calevate or picks in Google's Picker (developers.google.com/workspace/
#: drive/api/guides/api-specific-auth, read 10 Oct 2026). Never `spreadsheets`, which is
#: sensitive and reaches every sheet the person owns.
GOOGLE_SHEETS_SCOPES: Final = ("https://www.googleapis.com/auth/drive.file",)
#: Zoho CRM: read and create Leads and Contacts (upsert takes CREATE, upsert-records.html),
#: and search by phone, which needs the search scope as well.
ZOHO_SCOPES: Final = (
    "ZohoCRM.modules.leads.READ",
    "ZohoCRM.modules.leads.CREATE",
    "ZohoCRM.modules.contacts.READ",
    "ZohoCRM.modules.contacts.CREATE",
    "ZohoSearch.securesearch.READ",
)
#: HubSpot: read and write contacts; `oauth` is the scope every HubSpot app carries.
HUBSPOT_SCOPES: Final = ("oauth", "crm.objects.contacts.read", "crm.objects.contacts.write")

#: Zoho's accounts servers, one per data centre (multi-dc.html).
ZOHO_ACCOUNTS_HOSTS: Final = frozenset(
    {
        "accounts.zoho.com",
        "accounts.zoho.in",
        "accounts.zoho.eu",
        "accounts.zoho.com.au",
        "accounts.zoho.jp",
        "accounts.zoho.uk",
        "accounts.zoho.sa",
        "accounts.zohocloud.ca",
    }
)


@dataclass(frozen=True, slots=True)
class _Provider:
    kind: OAuthKind
    #: What the client is told the connection is for, in their words.
    label: str
    audience: str
    kdf_info: bytes


_PROVIDERS: Final[dict[OAuthKind, _Provider]] = {
    "google_calendar": _Provider(
        "google_calendar",
        "Google Calendar",
        "calevate:google-calendar-oauth-state",
        b"calevate:google-calendar-oauth-state:v1",
    ),
    "google_sheets": _Provider(
        "google_sheets",
        "Google Sheets",
        "calevate:google-sheets-oauth-state",
        b"calevate:google-sheets-oauth-state:v1",
    ),
    "zoho_crm": _Provider(
        "zoho_crm", "Zoho CRM", "calevate:zoho-crm-oauth-state", b"calevate:zoho-crm-oauth-state:v1"
    ),
    "hubspot": _Provider(
        "hubspot", "HubSpot", "calevate:hubspot-oauth-state", b"calevate:hubspot-oauth-state:v1"
    ),
}


def _client(kind: OAuthKind) -> tuple[str | None, str | None, str | None]:
    s = get_settings()
    if kind in GOOGLE_KINDS:
        return s.google_oauth_client_id, s.google_oauth_client_secret, s.google_oauth_redirect_uri
    if kind == "zoho_crm":
        return s.zoho_oauth_client_id, s.zoho_oauth_client_secret, s.zoho_oauth_redirect_uri
    return s.hubspot_oauth_client_id, s.hubspot_oauth_client_secret, s.hubspot_oauth_redirect_uri


def configured(kind: OAuthKind) -> bool:
    """Whether the platform's app for this vendor exists. False disables its connect path."""
    return all(_client(kind))


def unavailable(kind: OAuthKind) -> ProblemError:
    """The client sentence when the platform app is not registered yet, and the operator's
    half in a log line naming which setting is missing."""
    names = {
        "google_calendar": "GOOGLE_OAUTH",
        "google_sheets": "GOOGLE_OAUTH",
        "zoho_crm": "ZOHO_OAUTH",
        "hubspot": "HUBSPOT_OAUTH",
    }[kind]
    missing = [
        f"{names}_{part}"
        for part, value in zip(
            ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI"), _client(kind), strict=True
        )
        if not value
    ]
    log.warning("oauth_app_not_configured", extra={"kind": kind, "missing": ",".join(missing)})
    label = _PROVIDERS[kind].label
    return ProblemError(
        kind="business_rule",
        code=f"{kind}_not_configured",
        title=f"Connecting {label} is not switched on yet",
        detail=(
            f"Calevate's link to {label} has not been set up on our side yet, so it cannot "
            "be connected. Nothing else about your agents is affected."
        ),
        remediation=(
            f"There is nothing for you to set up. Ask your Calevate team when {label} will "
            "be ready — quote the reference on this message."
        ),
    )


def require_configured(kind: OAuthKind) -> None:
    if not configured(kind):
        raise unavailable(kind)


# --- the state -------------------------------------------------------------------------


def _state_key(kind: OAuthKind) -> bytes:
    """A purpose-separated subkey of `IMPERSONATION_GRANT_SECRET` (HKDF-Expand, one block),
    per provider: the derivation `copilot/write_tools._signing_key` argues for."""
    settings = get_settings()
    parent = resolve_hmac_key(
        settings.impersonation_grant_secret,
        env_var="IMPERSONATION_GRANT_SECRET",
        purpose=f"{_PROVIDERS[kind].label} OAuth state",
        code="oauth_state_not_configured",
        title="Connecting accounts is not available",
        local_fallback=f"calevate-local-dev-impersonation-grant-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    return hmac.new(parent, _PROVIDERS[kind].kdf_info + b"\x01", hashlib.sha256).digest()


def mint_state(
    kind: OAuthKind, *, tenant_id: UUID, user_id: UUID, now: datetime | None = None
) -> str:
    """The `state` for one consent round trip, bound to the provider, account and person."""
    at = now or datetime.now(UTC)
    claims = {
        "aud": _PROVIDERS[kind].audience,
        "sub": str(tenant_id),
        "act": str(user_id),
        "jti": str(uuid7()),
        "iat": int(at.timestamp()),
        "exp": int((at + STATE_TTL).timestamp()),
    }
    return jwt.encode(claims, _state_key(kind), algorithm=_STATE_ALGORITHM)


def verify_state(
    kind: OAuthKind, raw: str, *, tenant_id: UUID, user_id: UUID, refusal: ProblemError
) -> None:
    """Refuse a `state` this deployment did not mint for this provider, account and person."""
    try:
        claims = jwt.decode(
            raw,
            _state_key(kind),
            algorithms=[_STATE_ALGORITHM],
            audience=_PROVIDERS[kind].audience,
            options={"require": list(_STATE_REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError as exc:
        log.info("oauth_state_rejected", extra={"kind": kind, "error": type(exc).__name__})
        raise refusal from exc
    if claims.get("sub") != str(tenant_id) or claims.get("act") != str(user_id):
        log.warning("oauth_state_mismatch", extra={"kind": kind})
        raise refusal


def state_refused(kind: OAuthKind) -> ProblemError:
    label = _PROVIDERS[kind].label
    return ProblemError(
        kind="permission",
        code="oauth_state_invalid",
        title=f"This {label} connection was not started here",
        detail=(
            f"The connection request did not come from a {label} connection you started in "
            "this account, or it has expired."
        ),
        remediation="Start the connection again from the Connections screen.",
    )


# --- the three legs --------------------------------------------------------------------


def authorize_url(kind: OAuthKind, *, state: str, login_hint: str | None = None) -> str:
    """The consent URL a client is sent to.

    For Google, `login_hint` is the address the person signed in to Calevate with, so
    Google offers that same account, and `include_granted_scopes` keeps whatever that
    account already granted us: Calendar and Sheets end up on ONE Google account, asked
    for only when each is connected.
    """
    require_configured(kind)
    client_id, _, redirect = _client(kind)
    if kind in GOOGLE_KINDS:
        scopes = GOOGLE_CALENDAR_SCOPES if kind == "google_calendar" else GOOGLE_SHEETS_SCOPES
        params = {
            "client_id": client_id or "",
            "redirect_uri": redirect or "",
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    if kind == "zoho_crm":
        params = {
            "scope": ",".join(ZOHO_SCOPES),
            "client_id": client_id or "",
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": redirect or "",
            "prompt": "consent",
            "state": state,
        }
        return f"{_zoho_accounts_base()}/oauth/v2/auth?{urlencode(params)}"
    params = {
        "client_id": client_id or "",
        "redirect_uri": redirect or "",
        "scope": " ".join(HUBSPOT_SCOPES),
        "state": state,
    }
    return f"{HUBSPOT_AUTH_URL}?{urlencode(params)}"


def _zoho_accounts_base() -> str:
    base = get_settings().zoho_accounts_url.strip().rstrip("/")
    return zoho_accounts_server(base) or "https://accounts.zoho.in"


def zoho_accounts_server(raw: str | None) -> str | None:
    """`https://<host>` when `raw` names one of Zoho's accounts servers, else None."""
    if not raw:
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme != "https" or (parts.hostname or "") not in ZOHO_ACCOUNTS_HOSTS:
        return None
    if parts.port is not None or parts.username or parts.password:
        return None
    return f"https://{parts.hostname}"


def _token_url(kind: OAuthKind, accounts_server: str | None) -> str:
    if kind in GOOGLE_KINDS:
        return GOOGLE_TOKEN_URL
    if kind == "hubspot":
        return HUBSPOT_TOKEN_URL
    server = zoho_accounts_server(accounts_server) or _zoho_accounts_base()
    return f"{server}/oauth/v2/token"


def exchange_request(
    kind: OAuthKind, *, code: str, accounts_server: str | None = None
) -> PreparedRequest:
    """Exchange the authorization code for tokens."""
    require_configured(kind)
    client_id, secret, redirect = _client(kind)
    return PreparedRequest(
        method="POST",
        url=_token_url(kind, accounts_server),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form_body={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id or "",
            "client_secret": secret or "",
            "redirect_uri": redirect or "",
        },
    )


def refresh_request(
    kind: OAuthKind, *, refresh_token: str, accounts_server: str | None = None
) -> PreparedRequest:
    """Mint a fresh access token from a stored refresh token."""
    require_configured(kind)
    client_id, secret, redirect = _client(kind)
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id or "",
        "client_secret": secret or "",
    }
    if kind == "hubspot":
        # The quickstart's refresh carries the redirect URI as well.
        form["redirect_uri"] = redirect or ""
    return PreparedRequest(
        method="POST",
        url=_token_url(kind, accounts_server),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form_body=form,
    )


def revoke_request(
    kind: OAuthKind, *, refresh_token: str, accounts_server: str | None = None
) -> PreparedRequest | None:
    """The vendor call that withdraws our access, or None where no documented one exists
    (HubSpot — the client uninstalls the app in HubSpot instead)."""
    if not configured(kind):
        return None
    if kind in GOOGLE_KINDS:
        return PreparedRequest(
            method="POST",
            url=GOOGLE_REVOKE_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            form_body={"token": refresh_token},
        )
    if kind == "zoho_crm":
        client_id, secret, _ = _client(kind)
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        server = zoho_accounts_server(accounts_server) or _zoho_accounts_base()
        return PreparedRequest(
            method="POST",
            url=f"{server}/oauth/v2/revoke/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            form_body={"token": refresh_token, "token_type": "refresh_token"},
        )
    return None


def label(kind: OAuthKind) -> str:
    return _PROVIDERS[kind].label


__all__ = [
    "GOOGLE_CALENDAR_SCOPES",
    "GOOGLE_KINDS",
    "GOOGLE_SHEETS_SCOPES",
    "HUBSPOT_SCOPES",
    "OAUTH_KINDS",
    "STATE_TTL",
    "ZOHO_ACCOUNTS_HOSTS",
    "ZOHO_SCOPES",
    "OAuthKind",
    "authorize_url",
    "configured",
    "exchange_request",
    "label",
    "mint_state",
    "refresh_request",
    "require_configured",
    "revoke_request",
    "state_refused",
    "unavailable",
    "verify_state",
    "zoho_accounts_server",
]
