"""Entering a client's account needs no code; staying in one keeps the session's clock.

`POST /v1/admin/impersonation-grants` is the single door through which an operator
reaches a tenant's leads, calls and transcripts — `_load_admin_principal` refuses every
impersonated request without a grant, and grants exist only there. D-791 removed the
per-entry code D-210 and D-730 had put on that door; what this file pins is what is left:

  1. a cold entry on a signed-in admin session mints and writes the start row naming the
     operator, and a half-signed-in session still cannot reach the door;
  2. RENEWAL: a live grant for this tenant is continued and the ledger links the two
     start rows; the renew route refuses another tenant's grant, another operator's, a
     forged one, an expired one and one whose hour has run out;
  3. a renewal INHERITS `auth_time` rather than restamping it, so no chain of renewals
     outlives the entry that started it.

These drive the ROUTE over HTTP with a real first-party admin cookie, the credential this
route has in production, rather than the `dev:` bearer the sibling suites use.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, the fixture
deletes exactly those, and nothing counts globally.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import pytest_asyncio
from apps.api.authn.cookies import cookie_name
from apps.api.authn.sessions import issue_session
from apps.api.authn.stepup import REAUTH_MAX_AGE
from apps.api.core import impersonation as grant_module
from apps.api.core.impersonation import (
    ACTOR_CLAIM,
    AUTH_TIME_CLAIM,
    GRANT_ALGORITHM,
    GRANT_AUDIENCE,
    GRANT_TTL,
    VIEW_AS_MAX_AGE,
    mint_grant,
)
from apps.api.db.session import credential_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

GRANT_PATH = "/v1/admin/impersonation-grants"
RENEW_PATH = f"{GRANT_PATH}/renew"
STARTED_ACTION = "admin.impersonation_started"

#: The cookie the API reads on a plain-HTTP test transport. `_is_secure(request)` picks
#: the name, and `base_url="http://api"` is not secure — same choice the API makes.
ADMIN_COOKIE = cookie_name("admin", secure=False)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest_asyncio.fixture
async def operator() -> AsyncIterator[uuid.UUID]:
    """One `superadmin` in `admin_users`, which is also the session's subject.

    `superadmin` rather than `operator` only because a fixture that holds every
    permission cannot be the reason a test fails.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Step Up Door', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    try:
        yield admin_id
    finally:
        async with credential_session() as session:
            for table in ("auth_otp_challenges", "auth_sessions"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": admin_id}
                )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})


async def _cookie_for(admin_id: uuid.UUID, *, factor_age: timedelta | None) -> str:
    """A live admin session token whose second factor was proved `factor_age` ago.

    `None` means the column stays NULL — a session that answered a password and never a
    code. The column is written directly rather than by driving `sign_in` plus an emailed
    code, for the reason `authn_stepup_test` gives: what is under test is the READ.
    """
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=admin_id, now=at)
        if factor_age is not None:
            await session.execute(
                text("UPDATE auth_sessions SET mfa_verified_at = :when WHERE id = :id"),
                {"when": at - factor_age, "id": issued.session_id},
            )
    return issued.token


async def _make_org() -> dict[str, Any]:
    return await create_org_with_receptionist(
        name="Door Clinic",
        slug=f"dr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _mint(http: AsyncClient, cookie: str, slug: str, *, renew: str | None = None) -> Any:
    body: dict[str, Any] = {"slug": slug}
    if renew is not None:
        body["renew"] = renew
    return await http.post(GRANT_PATH, cookies={ADMIN_COOKIE: cookie}, json=body)


async def _renew(http: AsyncClient, cookie: str, slug: str, renew: str) -> Any:
    return await http.post(
        RENEW_PATH, cookies={ADMIN_COOKIE: cookie}, json={"slug": slug, "renew": renew}
    )


async def _started_rows(tenant_id: uuid.UUID) -> list[Any]:
    """`admin.impersonation_started` for ONE tenant, oldest first.

    `audit_log` is not tenant-RLS'd (the hash chain is global), so this reads under the
    untenanted session and filters by tenant itself — same as the sibling suites.

    The SUMMARY is deliberately not selected: `audit_log` has no such column (hashing a
    field the row does not carry would make the chain unverifiable), so the summary goes
    to the log stream keyed by entry id. `_summaries` below reads it there.
    """
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id FROM audit_log "
                    "WHERE action = :action AND tenant_id = :tid ORDER BY at ASC, id ASC"
                ),
                {"action": STARTED_ACTION, "tid": tenant_id},
            )
        ).all()


def _summaries(caplog: pytest.LogCaptureFixture) -> list[Any]:
    """The audit SUMMARIES this test produced, oldest first — the `audit` log records.

    `write_audit` emits one per entry that has a summary, sanitized by `redact_mapping`
    and carrying the same `entry_id` as the row. Reading them here is what lets a test
    assert on `renews` and `auth_time`, which exist nowhere else.
    """
    return [record for record in caplog.records if record.msg == "audit"]


def _auth_time_of(wire: str) -> datetime:
    """The `auth_time` a grant carries, read off the wire rather than off our own record.

    Decoded with verification OFF on purpose: this is a test reading a field, not a
    verifier accepting a token, and turning the checks on here would make an unrelated
    expiry failure look like a missing claim.
    """
    claims = jwt.decode(wire, options={"verify_signature": False}, audience=GRANT_AUDIENCE)
    return datetime.fromtimestamp(int(claims[AUTH_TIME_CLAIM]), UTC)


# ═══════════════ who can reach the door ═══════════════


@pytest.mark.asyncio
async def test_a_signed_in_operator_enters_with_no_code_and_the_start_row_names_them(
    operator: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """D-791: the admin session and `admin:impersonate` open the door, however long ago
    the sign-in factor was proved, and the entry is audited exactly as before (D-22)."""
    cookie = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=10))
    org = await _make_org()

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await _mint(http, cookie, str(org["slug"]))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == str(org["slug"])

    # A cold entry dates the session from the mint itself.
    auth_time = _auth_time_of(body["grant"])
    now = datetime.now(UTC)
    assert now - auth_time < timedelta(minutes=1)
    assert datetime.fromisoformat(body["expires_at"]) > now

    rows = await _started_rows(uuid.UUID(str(org["id"])))
    assert len(rows) == 1
    actor_type, actor_id = rows[0]
    assert actor_type == "admin"
    assert uuid.UUID(str(actor_id)) == operator, "D-22: the start row must name who entered"

    summaries = _summaries(caplog)
    assert len(summaries) == 1
    assert summaries[0].renews is None, "a cold entry renews nothing"
    assert summaries[0].auth_time == auth_time.isoformat()


@pytest.mark.asyncio
async def test_a_session_that_never_proved_a_factor_cannot_even_reach_the_door(
    operator: uuid.UUID,
) -> None:
    """A half-authenticated admin session — password accepted, code unanswered — is
    refused by `verify_token`'s `_require_second_factor`, so no route change can make a
    partial session reach the tenant door."""
    cookie = await _cookie_for(operator, factor_age=None)
    org = await _make_org()

    async with _client() as http:
        response = await _mint(http, cookie, str(org["slug"]))

    assert response.status_code == 401, response.text
    assert response.json()["type"].endswith("/second_factor_required")
    assert await _started_rows(uuid.UUID(str(org["id"]))) == []


# ═══════════════ renewal ═══════════════


@pytest.mark.asyncio
async def test_renewal_is_its_own_route_and_continues_the_session(operator: uuid.UUID) -> None:
    """`/impersonation-grants/renew` is what the client console may call; it continues a
    grant on the clock of the entry that started it."""
    org = await _make_org()
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))
    async with _client() as http:
        first = await _mint(http, cookie, str(org["slug"]))
        assert first.status_code == 200, first.text
        renewed = await _renew(http, cookie, str(org["slug"]), first.json()["grant"])

    assert renewed.status_code == 200, renewed.text
    assert _auth_time_of(renewed.json()["grant"]) == _auth_time_of(first.json()["grant"])


@pytest.mark.asyncio
async def test_a_live_grant_renews_and_the_ledger_links_the_two_entries(
    operator: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """A renewal is still an audited entry, and its start row names the grant it extends."""
    org = await _make_org()
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            first = await _mint(http, cookie, str(org["slug"]))
            assert first.status_code == 200, first.text
            renewed = await _mint(http, cookie, str(org["slug"]), renew=first.json()["grant"])

    assert renewed.status_code == 200, renewed.text
    rows = await _started_rows(uuid.UUID(str(org["id"])))
    assert len(rows) == 2, "a renewal is still an entry, and still audited"
    assert uuid.UUID(str(rows[1].actor_id)) == operator, "D-22: a renewal still names the actor"

    summaries = _summaries(caplog)
    assert len(summaries) == 2
    assert summaries[0].renews is None
    assert summaries[1].renews == summaries[0].grant_id, (
        "the ledger must say WHICH session this extended, or a renewal is "
        "indistinguishable from a fresh entry"
    )


@pytest.mark.asyncio
async def test_a_renewal_inherits_auth_time_rather_than_restamping_it(
    operator: uuid.UUID,
) -> None:
    """THE PROPERTY THE WINDOW RESTS ON, and the one a plausible refactor would break.

    If a renewal took `now` as its `auth_time` — the natural thing to write — then
    `VIEW_AS_MAX_AGE` would bound nothing at all: each link would restart the hour and the
    client console could hold a view-as session open forever without returning to the
    operator console. So the inherited value is asserted to the second across two hops,
    not merely "still in the past".
    """
    org = await _make_org()
    cookie = await _cookie_for(operator, factor_age=timedelta(minutes=2))

    async with _client() as http:
        first = await _mint(http, cookie, str(org["slug"]))
        assert first.status_code == 200, first.text
        one = first.json()["grant"]

        second = await _mint(http, cookie, str(org["slug"]), renew=one)
        assert second.status_code == 200, second.text
        two = second.json()["grant"]

        third_response = await _mint(http, cookie, str(org["slug"]), renew=two)
        assert third_response.status_code == 200, third_response.text
        three = third_response.json()["grant"]

    origin = _auth_time_of(one)
    assert _auth_time_of(two) == origin
    assert _auth_time_of(three) == origin, "three hops, one entry, one clock"


@pytest.mark.asyncio
async def test_a_renewal_stops_at_the_view_as_window(operator: uuid.UUID) -> None:
    """The hour is a CEILING on the chain, not a rolling window.

    Minted by hand with an `auth_time` just past the bound and an `exp` still ahead, so
    what refuses it is `VIEW_AS_MAX_AGE` and not the grant's own expiry — the two are
    different clocks and only one of them is under test here.
    """
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    elapsed, _ = mint_grant(
        tenant_id=tenant_id,
        admin_id=operator,
        auth_time=datetime.now(UTC) - VIEW_AS_MAX_AGE - timedelta(minutes=1),
    )
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    async with _client() as http:
        response = await _renew(http, cookie, str(org["slug"]), elapsed)

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/view_as_renewal_refused")
    assert await _started_rows(tenant_id) == []


@pytest.mark.asyncio
async def test_another_tenants_grant_renews_nothing(operator: uuid.UUID) -> None:
    """A grant for client A offered to renew client B extends nothing and leaves no entry."""
    tenant_a = await _make_org()
    tenant_b = await _make_org()
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    async with _client() as http:
        first = await _mint(http, cookie, str(tenant_a["slug"]))
        assert first.status_code == 200, first.text
        crossed = await _renew(http, cookie, str(tenant_b["slug"]), first.json()["grant"])

    assert crossed.status_code == 403, crossed.text
    assert crossed.json()["type"].endswith("/view_as_renewal_refused")
    assert await _started_rows(uuid.UUID(str(tenant_b["id"]))) == []


@pytest.mark.asyncio
async def test_another_operators_grant_renews_nothing(operator: uuid.UUID) -> None:
    """A grant is one operator's, on the renewal input as much as on the wire."""
    org = await _make_org()
    somebody_else, _ = mint_grant(
        tenant_id=uuid.UUID(str(org["id"])),
        admin_id=uuid.uuid4(),
        auth_time=datetime.now(UTC),
    )
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    async with _client() as http:
        response = await _renew(http, cookie, str(org["slug"]), somebody_else)

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/view_as_renewal_refused")


@pytest.mark.asyncio
@pytest.mark.parametrize("offered", ["not-a-token", "a.b.c"])
async def test_junk_offered_as_a_renewal_is_refused_not_a_crash(
    operator: uuid.UUID, offered: str
) -> None:
    """Every unreadable `renew` value is a refusal, never a 500."""
    org = await _make_org()
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    async with _client() as http:
        response = await _renew(http, cookie, str(org["slug"]), offered)

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/view_as_renewal_refused")


@pytest.mark.asyncio
async def test_an_expired_grant_renews_nothing(operator: uuid.UUID) -> None:
    """A console that slept through its own expiry cannot continue from the client console."""
    org = await _make_org()
    stale_instant = datetime.now(UTC) - GRANT_TTL - timedelta(minutes=1)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(grant_module, "datetime", _FrozenClock(stale_instant))
        expired, _ = mint_grant(
            tenant_id=uuid.UUID(str(org["id"])), admin_id=operator, auth_time=stale_instant
        )

    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))
    async with _client() as http:
        response = await _renew(http, cookie, str(org["slug"]), expired)

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/view_as_renewal_refused")


# ═══════════════ the claim itself ═══════════════


def test_a_grant_whose_auth_time_is_unreadable_is_refused_not_defaulted() -> None:
    """A correctly SIGNED grant with a nonsense `auth_time` is malformed, not "now".

    `bool` is the case worth writing down: it is an `int` in Python, so a naive
    `int(claims[...])` would read `true` as the epoch and a chain would silently date from
    1970. The verifier refuses instead — an unenforceable window is not a window.
    """
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    now = int(datetime.now(UTC).timestamp())
    for bad in (True, "yesterday", None, [1]):
        wire = jwt.encode(
            {
                "aud": GRANT_AUDIENCE,
                "sub": str(tenant_id),
                ACTOR_CLAIM: {"sub": str(admin_id)},
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + 600,
                AUTH_TIME_CLAIM: bad,
            },
            grant_module._signing_key(),
            algorithm=GRANT_ALGORITHM,
        )
        assert grant_module.renewable_grant(wire, admin_id=admin_id, tenant_id=tenant_id) is None, (
            f"auth_time={bad!r} must not be readable as an instant"
        )


class _FrozenClock:
    """`datetime` with `now()` pinned — the sibling suite's stub, same reasoning."""

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self, tz: Any = None) -> datetime:
        del tz
        return self._instant

    @staticmethod
    def fromtimestamp(value: float, tz: Any = None) -> datetime:
        return datetime.fromtimestamp(value, tz)
