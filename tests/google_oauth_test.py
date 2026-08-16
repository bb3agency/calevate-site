"""The ONE Google service-account flow, tested as a CACHE rather than as a handshake.

`tests/sheets_adapter_test.py` and `tests/vertex_extraction_test.py` each prove the flow
works for their own caller — the assertion is minted, the scope is right, one bearer
serves many units of work. Neither can prove the properties that belong to the module
itself, because both hold one credential for the life of a test:

  1. **WHAT COUNTS AS THE SAME CREDENTIAL.** The cache key is the identity, and an
     identity that is too coarse serves a retired key's token for the better part of an
     hour. Rotating the KEY while keeping the ADDRESS is the ordinary rotation — it is
     what Google's console does — and `platform_config` classifies
     `gcp_service_account_json` as `live` on the strength of this.
  2. **WHICH CLOCK THE DEADLINE IS ON.** A wall clock steps; a cache deadline must not
     be read off one.
  3. **WHAT A RACE DOES.** Two arq jobs starting cold in one worker both miss.
  4. **THAT NOTHING LEAKS.** Key material and bearers never reach a log record.

Hard rule 6 throughout, and rule 9's neighbour: the RSA keys here are generated per run
and never leave the process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from apps.workers import google_oauth
from apps.workers.google_oauth import (
    TOKEN_REFRESH_SKEW_S,
    ServiceAccount,
    access_token,
    parse_service_account,
    reset_token_cache,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

EMAIL = "calevate-vertex@calevate-test.iam.gserviceaccount.com"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"
OTHER_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


#: Two DIFFERENT keys for ONE service account, which is exactly the state a rotation
#: passes through: Google lets an account hold several active keys, so the old one keeps
#: working while the new one is rolled out.
_PEM_OLD = _pem()
_PEM_NEW = _pem()


def _account(*, pem: str = _PEM_OLD, key_id: str | None = "kid-old", email: str = EMAIL) -> Any:
    payload: dict[str, Any] = {
        "type": "service_account",
        "client_email": email,
        "private_key": pem,
        "token_uri": google_oauth.TOKEN_URL,
    }
    if key_id is not None:
        payload["private_key_id"] = key_id
    account = parse_service_account(json.dumps(payload))
    assert account is not None
    return account


class FakeGoogle:
    """The token endpoint, recording every exchange and handing out numbered bearers.

    Numbered because the question every test here asks is "was this token minted again,
    or served from the cache" — and two identical strings cannot answer it.
    """

    def __init__(self, *, ttl: int = 3599) -> None:
        self.exchanges: list[dict[str, list[str]]] = []
        self.ttl = ttl
        self.status = 200

    async def handler(self, request: httpx.Request) -> httpx.Response:
        # ASYNC, AND IT YIELDS. `MockTransport` with a plain function never suspends, so
        # four `gather`ed callers ran strictly one after another and the race test passed
        # having raced nothing — it observed ONE exchange and would have observed one
        # against a cache with no concurrency safety at all. One `sleep(0)` is the
        # difference between exercising the interleaving and asserting about it.
        await asyncio.sleep(0)
        self.exchanges.append(parse_qs(request.content.decode()))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_grant"})
        return httpx.Response(
            200,
            json={"access_token": f"ya29.token-{len(self.exchanges)}", "expires_in": self.ttl},
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def _cold_cache() -> Any:
    reset_token_cache()
    yield
    reset_token_cache()


# --- 1. what counts as the same credential ----------------------------------------


async def test_the_same_account_key_and_scope_is_served_from_the_cache() -> None:
    """The property the cache exists for. One RS256 signature and one round trip an hour,
    not one per lead and one per assist."""
    google = FakeGoogle()
    async with google.client() as http:
        first = await access_token(http, _account(), scope=SCOPE)
        second = await access_token(http, _account(), scope=SCOPE)

    assert first == second == "ya29.token-1"
    assert len(google.exchanges) == 1, google.exchanges


async def test_rotating_the_key_on_one_account_takes_effect_on_the_next_call() -> None:
    """THE rotation case, and the one the cache key used to get wrong.

    A new key minted on the SAME service account is what an operator installs when they
    rotate — the address does not change, only `private_key_id` and the PEM. Keyed on the
    address alone, every worker kept sending the retired key's bearer for up to
    fifty-five minutes, and the only cures were a restart or an operator remembering a
    Python function. `platform_config` calls `gcp_service_account_json` `live`; this is
    the assertion that makes that word true.
    """
    google = FakeGoogle()
    async with google.client() as http:
        old = await access_token(http, _account(pem=_PEM_OLD, key_id="kid-old"), scope=SCOPE)
        new = await access_token(http, _account(pem=_PEM_NEW, key_id="kid-new"), scope=SCOPE)

    assert old == "ya29.token-1"
    assert new == "ya29.token-2", "the retired key's bearer was served to the new key"
    assert len(google.exchanges) == 2

    # The assertion the second exchange carried was signed by the NEW key — a cache that
    # merely missed would be no better if the flow then re-signed with the old one.
    import jwt

    header = jwt.get_unverified_header(google.exchanges[1]["assertion"][0])
    assert header["kid"] == "kid-new"


async def test_a_rotation_does_not_grow_the_cache() -> None:
    """The superseded slot goes when the replacement's first token lands.

    Dropped THEN and not at parse time: until a token actually comes back we do not know
    the new key works, and evicting early would turn a mistyped key into an outage
    instead of one failed call.
    """
    google = FakeGoogle()
    async with google.client() as http:
        await access_token(http, _account(pem=_PEM_OLD, key_id="kid-old"), scope=SCOPE)
        assert len(google_oauth._TOKENS) == 1
        await access_token(http, _account(pem=_PEM_NEW, key_id="kid-new"), scope=SCOPE)

    assert len(google_oauth._TOKENS) == 1, google_oauth._TOKENS
    assert next(iter(google_oauth._TOKENS))[1] == "kid-new"


async def test_one_account_and_key_serving_two_scopes_gets_two_bearers() -> None:
    """The behaviour the extraction into this module had to ADD. A `cloud-platform` caller
    handed a `spreadsheets` token meets a 403 naming neither the scope nor the cache."""
    google = FakeGoogle()
    async with google.client() as http:
        vertex = await access_token(http, _account(), scope=SCOPE)
        sheets = await access_token(http, _account(), scope=OTHER_SCOPE)

    assert vertex != sheets
    assert len(google.exchanges) == 2
    assert len(google_oauth._TOKENS) == 2, "one scope's token evicted the other's"


async def test_two_accounts_never_share_a_bearer() -> None:
    google = FakeGoogle()
    async with google.client() as http:
        one = await access_token(http, _account(email=EMAIL), scope=SCOPE)
        two = await access_token(
            http, _account(email="other@x.iam.gserviceaccount.com"), scope=SCOPE
        )

    assert one != two


async def test_a_key_file_with_no_key_id_still_caches() -> None:
    """Google always writes `private_key_id`, so this is the degradation path and not the
    normal one. It degrades to the PREVIOUS behaviour — cached on (address, scope) — and
    not to a cache miss per call, which would spend an RS256 signature on every assist."""
    google = FakeGoogle()
    async with google.client() as http:
        first = await access_token(http, _account(key_id=None), scope=SCOPE)
        second = await access_token(http, _account(key_id=None), scope=SCOPE)

    assert first == second
    assert len(google.exchanges) == 1


# --- 2. which clock ----------------------------------------------------------------


async def test_the_deadline_survives_a_wall_clock_that_jumps_backwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An NTP correction after a VPS resume moves `time.time()` backwards by minutes.

    On a wall-clock deadline that reads as "the token got younger", so an EXPIRED bearer
    is served as fresh and every request 401s until real time catches up. The deadline is
    `time.monotonic()`, which cannot go backwards, so the jump changes nothing — and the
    ASSERTION signed into the exchange still uses the wall clock, because Google
    validates `iat`/`exp` against real time and a monotonic instant there would be
    rejected outright. Two clocks, one job each.
    """
    google = FakeGoogle(ttl=600)
    async with google.client() as http:
        await access_token(http, _account(), scope=SCOPE)

        # Monotonic advances past the token's life; the wall clock lurches back a day.
        base = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: base + 601)
        monkeypatch.setattr(time, "time", lambda: 1_000_000.0)

        second = await access_token(http, _account(), scope=SCOPE)

    assert second == "ya29.token-2", "an expired bearer survived a backwards clock step"

    # And the OTHER half of "two clocks": the assertion Google receives is stamped with
    # the WALL clock, so a monotonic instant (a number of seconds since boot) never
    # reaches `iat` — where Google would read it as 1970 and refuse the exchange.
    import jwt

    claims = jwt.decode(
        google.exchanges[1]["assertion"][0],
        options={"verify_signature": False},
        audience=google_oauth.TOKEN_URL,
    )
    assert claims["iat"] == 1_000_000, claims["iat"]


async def test_a_token_inside_its_refresh_margin_is_re_minted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The margin is not decoration: it is what lets the callers treat a 401 as a
    statement about the KEY rather than about staleness. A bearer is never handed to
    Google inside its last five minutes."""
    google = FakeGoogle(ttl=3600)
    async with google.client() as http:
        await access_token(http, _account(), scope=SCOPE)
        base = time.monotonic()

        monkeypatch.setattr(time, "monotonic", lambda: base + 3600 - TOKEN_REFRESH_SKEW_S - 5)
        assert await access_token(http, _account(), scope=SCOPE) == "ya29.token-1"

        monkeypatch.setattr(time, "monotonic", lambda: base + 3600 - TOKEN_REFRESH_SKEW_S + 5)
        assert await access_token(http, _account(), scope=SCOPE) == "ya29.token-2"


# --- 3. what a race does -----------------------------------------------------------


async def test_two_jobs_racing_a_cold_cache_both_get_a_usable_bearer() -> None:
    """Recorded rather than fixed, because the outcome is correct and the cost is small.

    Two arq jobs starting on a cold worker both miss and both mint. Google issues both;
    neither invalidates the other; the last write wins and every later call is a hit. The
    cost is N-1 extra signatures ONCE per worker lifetime, and the fix — a per-key
    `asyncio.Lock` in a module-level dict — buys that back at the price of a lock created
    on one event loop and awaited on another, which is a `RuntimeError` in exactly the
    place (a test suite, a re-entered runner) where it is hardest to read. This test is
    the evidence that the unlocked version is safe, so the next reader can decline the
    lock with the same evidence instead of re-deriving it.
    """
    google = FakeGoogle()
    async with google.client() as http:
        tokens = await asyncio.gather(
            *(access_token(http, _account(), scope=SCOPE) for _ in range(4))
        )

        assert all(token is not None for token in tokens)
        assert len(google.exchanges) == 4, "the race did not actually race"

        settled = await access_token(http, _account(), scope=SCOPE)

    assert len(google.exchanges) == 4, "the cache did not converge after the race"
    assert settled in tokens


# --- 4. what leaks -----------------------------------------------------------------


async def test_no_bearer_key_or_error_body_reaches_a_log_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6, and the one specific to this module: Google's token-error body echoes
    the assertion's claims, so only the STATUS is ever logged."""
    google = FakeGoogle()
    google.status = 401
    account: ServiceAccount = _account()

    with caplog.at_level(logging.DEBUG):
        async with google.client() as http:
            assert await access_token(http, account, scope=SCOPE) is None
            google.status = 200
            token = await access_token(http, account, scope=SCOPE)

    assert token is not None
    blob = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert token not in blob, "a bearer reached a log record"
    assert account.private_key not in blob, "PEM key material reached a log record"
    assert "invalid_grant" not in blob, "the vendor's error body reached a log record"
    assert "google_token_refused" in blob, "a refused exchange left no operator trail"
    assert "401" in blob, "the status — the one fact an operator needs — was not logged"


async def test_a_refused_exchange_does_not_poison_the_cache() -> None:
    """None means "no token this time", never "no token from now on"."""
    google = FakeGoogle()
    google.status = 500
    async with google.client() as http:
        assert await access_token(http, _account(), scope=SCOPE) is None
        assert google_oauth._TOKENS == {}
        google.status = 200
        assert await access_token(http, _account(), scope=SCOPE) == "ya29.token-2"
