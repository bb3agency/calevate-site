"""ONE Google service-account OAuth2 flow, for every Google API this platform reaches.

RFC 7523's JWT-bearer profile, which is what Google's server-to-server flow is: sign a
short-lived assertion with the service account's RS256 private key, POST it to the token
endpoint, get a bearer back, cache it until its refresh margin. Two callers today —
`workers/google_sheets.py` (a client's spreadsheet, scope `.../auth/spreadsheets`) and
`workers/extraction.py` (Vertex AI in `asia-south1`, scope `.../auth/cloud-platform`) —
and they differ in exactly one value, the scope.

WHY THIS MODULE EXISTS AT ALL: it is an extraction, not an invention. Every line here
was `google_sheets.py`'s, written and tested for the Sheets delivery path. D-127 needed
the same flow for Vertex, and the choice was between a second copy of a crypto handshake
and one home for it. "One way per problem, and migrate rather than accumulate" decides
that, and the migration is in the same change: `google_sheets.py` imports these names
rather than keeping its own.

--------------------------------------------------------------------------------------
WHY NOT `google-auth`, WHICH IS THE OBVIOUS ANSWER
--------------------------------------------------------------------------------------
Google publishes `google-auth`, and `google.oauth2.service_account.Credentials` does
precisely this. It was resolved and its lockfile diff read before this file was written
(hard rule 9 — the July 2025 ESLint `postinstall` incident is why that is a rule and not
a habit). What the resolution showed, at `google-auth 2.56.3`:

  google-auth → cryptography (already in this tree, via `pyjwt[crypto]`)
              → pyasn1-modules → pyasn1        ← the only two NEW packages

Two new pure-Python packages, no native build step, no install hooks — a modest and
honest diff, and not the reason it was declined. Three other things were:

1. **It would be the second implementation, not the first.** This repo already had the
   flow, shipped and covered by `tests/sheets_adapter_test.py`. Adding a library to do
   what one module already does is how two vocabularies for one handshake get born.
2. **Its refresh is synchronous.** `Credentials.refresh()` takes a transport, and the
   ones google-auth ships are `requests`- or `urllib3`-based — neither is in this tree,
   both are additional packages, and either would put a BLOCKING network call inside an
   arq worker's event loop. The alternative is writing an httpx transport adapter, which
   is writing this file with an extra dependency attached.
3. **PyJWT is already a declared dependency** (`pyjwt[crypto]>=2.10`) and already signs
   this repo's other RS256 assertion.

Recorded rather than assumed, so the next reader can re-decide with the same evidence
instead of re-deriving it: if a Google API this platform needs stops being reachable
with a bearer token, `google-auth` is the answer and this note is the argument it has to
beat.

--------------------------------------------------------------------------------------
WHAT THIS MODULE PROMISES ABOUT THE CREDENTIAL
--------------------------------------------------------------------------------------
The private key is held only for the moment of signing. It is never logged, never placed
in an exception message, never returned to a caller, and no function here raises with it
in scope — `access_token` returns `None` on every failure rather than propagating, so a
traceback cannot carry key material out of a worker. Google's own error body echoes the
assertion's claims, so only the STATUS is ever logged (hard rule 6).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Final

import httpx
import jwt

from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: Google's OAuth2 token endpoint. A key file names its own (`token_uri`); this is the
#: fallback so a key minted before Google moved the endpoint still works.
TOKEN_URL: Final = "https://oauth2.googleapis.com/token"

#: RFC 7523's grant type — the string that makes this a JWT-bearer exchange rather than
#: a password or a refresh-token one.
JWT_BEARER_GRANT: Final = "urn:ietf:params:oauth:grant-type:jwt-bearer"

#: Google caps an assertion's own lifetime at one hour; we ask for exactly that and then
#: refuse to USE a token in its last five minutes. That margin is load-bearing for error
#: mapping in the callers: a token we hand to Google is never more than 55 minutes old,
#: so a 401 is a statement about the KEY and not about staleness, and can be reported to
#: an operator as such instead of being retried into the same wall three times.
TOKEN_TTL_S: Final = 3600
TOKEN_REFRESH_SKEW_S: Final = 300


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    """The four fields of a Google service-account key that the JWT flow needs.

    `private_key` is PEM key material. It is held only for the moment of signing, never
    logged, never placed in an exception message, and never returned to a caller — which
    is why this dataclass has no `__str__` worth writing and nothing formats it.
    """

    client_email: str
    private_key: str
    token_uri: str
    private_key_id: str | None = None


def parse_service_account(raw: str) -> ServiceAccount | None:
    """The deployment's key, as injected from the secrets manager at deploy time.

    Returns None rather than raising on malformed material: a bad key is an operator
    error that must surface as a named refusal on the screen that needed it, not as a
    traceback in a worker whose next line would print the key.
    """
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    email = str(parsed.get("client_email") or "").strip()
    key = str(parsed.get("private_key") or "").strip()
    if not email or not key:
        return None
    key_id = parsed.get("private_key_id")
    return ServiceAccount(
        client_email=email,
        private_key=key,
        # The key file names its own token endpoint; falling back to the constant means
        # a key minted before Google moved the endpoint still works.
        token_uri=str(parsed.get("token_uri") or TOKEN_URL),
        private_key_id=str(key_id) if key_id else None,
    )


@dataclass(frozen=True, slots=True)
class _CachedToken:
    value: str
    expires_at: float


#: Module-level rather than instance-level because both callers build a fresh transport
#: per unit of work (they re-read settings so a config change takes effect, which is
#: right) — a token cached on the instance would be minted per lead and per assist, and
#: would spend a network round-trip and an RS256 signature on every one.
#:
#: KEYED ON (client_email, scope), NOT ON THE EMAIL ALONE, and that is the one behaviour
#: this extraction had to ADD rather than move. One service account can now be used for
#: two different scopes; a cache keyed on identity alone would hand the Vertex caller a
#: token minted for `.../auth/spreadsheets`, which Google answers with a 403 that names
#: neither the scope nor the cache — a bug that would look like a broken IAM grant.
_TOKENS: dict[tuple[str, str], _CachedToken] = {}


def reset_token_cache() -> None:
    """Drop every cached bearer. For tests, and for an operator rotating a key without
    a restart."""
    _TOKENS.clear()


def _assertion(account: ServiceAccount, *, scope: str, now: int) -> str:
    """The signed JWT Google exchanges for an access token (RFC 7523 profile).

    `aud` is the TOKEN endpoint, not the API being called: this assertion authenticates
    the token request itself, so a captured one cannot be replayed against anything else.
    """
    headers = {"kid": account.private_key_id} if account.private_key_id else None
    return jwt.encode(
        {
            "iss": account.client_email,
            "scope": scope,
            "aud": account.token_uri,
            "iat": now,
            "exp": now + TOKEN_TTL_S,
        },
        account.private_key,
        algorithm="RS256",
        headers=headers,
    )


async def access_token(
    http: httpx.AsyncClient, account: ServiceAccount, *, scope: str
) -> str | None:
    """A bearer for `scope`, cached until its refresh margin.

    None means the exchange failed. The caller decides what that means; this function
    deliberately does not raise, because the one thing that must never happen is a
    credential landing in a traceback.
    """
    now = time.time()
    cache_key = (account.client_email, scope)
    cached = _TOKENS.get(cache_key)
    if cached is not None and cached.expires_at - TOKEN_REFRESH_SKEW_S > now:
        return cached.value
    try:
        response = await http.post(
            account.token_uri,
            data={
                "grant_type": JWT_BEARER_GRANT,
                "assertion": _assertion(account, scope=scope, now=int(now)),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as exc:
        log.warning("google_token_transport_error", extra={"error": type(exc).__name__})
        return None
    if response.status_code != 200:
        # The status, never the body: Google's error body echoes the assertion's claims.
        log.warning("google_token_refused", extra={"status": response.status_code})
        return None
    try:
        body = response.json()
        token = str(body["access_token"])
        ttl = int(body.get("expires_in") or TOKEN_TTL_S)
    except (ValueError, KeyError, TypeError):
        log.warning("google_token_malformed")
        return None
    _TOKENS[cache_key] = _CachedToken(value=token, expires_at=now + ttl)
    return token


__all__ = [
    "JWT_BEARER_GRANT",
    "TOKEN_REFRESH_SKEW_S",
    "TOKEN_TTL_S",
    "TOKEN_URL",
    "ServiceAccount",
    "access_token",
    "parse_service_account",
    "reset_token_cache",
]
