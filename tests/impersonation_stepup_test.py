"""Entering a client's account takes a second factor; staying in one does not (D-210).

`POST /v1/admin/impersonation-grants` is the single door through which an operator
reaches a tenant's leads, calls and transcripts — `_load_admin_principal` refuses every
impersonated request without a grant, and grants exist only there. BACKEND-PATTERNS §7
names raw-transcript access a step-up action, and the route that serves it
(`GET /v1/calls/{id}/transcript/raw`) is on the CLIENT realm, where there is no second
factor to check. So the check belongs on the door, and this file is what pins it there.

WHAT IS ASSERTED, in the order a reviewer should read it:

  1. the two halves of the gate, each refused on its own — no echo, and a stale factor;
  2. that a refusal leaves NO `admin.impersonation_started` row, which is what makes the
     console's retry-after-the-prompt safe and keeps the ledger honest about who entered;
  3. the happy path, and that the grant records the instant the factor was proved;
  4. RENEWAL: a console holding a live grant for this tenant is not challenged again —
     and every way that could have become a bypass is refused. Another tenant's grant,
     another operator's, a forged one, an expired one and one whose hour has run out are
     all "no renewal", i.e. all send the caller back to the second factor.
  5. THE PROPERTY THE WHOLE DESIGN RESTS ON: a renewal INHERITS `auth_time` rather than
     restamping it, so no chain of renewals outlives the one step-up that started it.

These drive the ROUTE over HTTP with a real first-party admin cookie rather than the
`dev:` bearer the sibling suites use, and that is deliberate: `core/stepup.py` waives the
freshness half for `dev:` tokens (`APP_ENV=local` with no `PLATFORM_KEK`), so a `dev:`
token could only ever exercise the echo. The cookie is the credential this route has in
production.

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
from apps.api.admin import service as admin_service
from apps.api.admin.routes import view_as_confirmation
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

GRANT_PATH = "/v1/admin/impersonation-grants"
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
    permission cannot be the reason a test fails. BOTH tiers reach a raw transcript
    through this door since the founder's correction to D-457 put `calls:read_raw` in
    `ROLE_PERMISSIONS["operator"]` — which makes this gate matter MORE than it did, not
    less: the second factor now stands in front of every admin who can enter a client's
    account, rather than in front of the one who could also read the transcript.
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
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = :s"), {"s": admin_id}
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
    return await admin_service.create_organization(
        name="Door Clinic",
        slug=f"dr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _mint(
    http: AsyncClient,
    cookie: str,
    slug: str,
    *,
    confirm: str | None = None,
    renew: str | None = None,
) -> Any:
    body: dict[str, Any] = {"slug": slug}
    if renew is not None:
        body["renew"] = renew
    headers = {} if confirm is None else {"X-Confirm-Action": confirm}
    return await http.post(GRANT_PATH, headers=headers, cookies={ADMIN_COOKIE: cookie}, json=body)


async def _started_rows(tenant_id: uuid.UUID) -> list[Any]:
    """`admin.impersonation_started` for ONE tenant, oldest first.

    `audit_log` is not tenant-RLS'd (the hash chain is global), so this reads under the
    untenanted session and filters by tenant itself — same as the sibling suites.

    The SUMMARY is deliberately not selected: `audit_log` has no such column and never
    had one (`compliance/audit.py` — hashing a field the row does not carry would make
    the chain unverifiable), so the summary goes to the log stream keyed by entry id.
    `_summaries` below reads it there, which is where an auditor reads it too.
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


# ═══════════════ the gate, each half refused on its own ═══════════════


@pytest.mark.asyncio
async def test_entering_a_client_without_the_confirmation_is_refused(
    operator: uuid.UUID,
) -> None:
    """THE ECHO HALF. A console that meant to do something else cannot start a view-as.

    The refusal prints the exact string to send, on purpose (`core/stepup.py`): it is not
    a secret, it is an ops procedure, and an operator who cannot get past a gate reads the
    source next.
    """
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=5))
    org = await _make_org()

    async with _client() as http:
        response = await _mint(http, cookie, str(org["slug"]))

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/step_up_required")
    assert view_as_confirmation(str(org["slug"])) in response.json()["remediation"]
    # A refused entry leaves no claim that authority was ever issued.
    assert await _started_rows(uuid.UUID(str(org["id"]))) == []


@pytest.mark.asyncio
async def test_entering_a_client_with_a_stale_second_factor_is_refused(
    operator: uuid.UUID,
) -> None:
    """THE FRESHNESS HALF, which is the one this route did not have at all.

    A live admin cookie, a perfectly correct confirmation, and a second factor proved
    just outside the window — the unattended-laptop case, and the stolen-cookie case,
    both refused at the door rather than inside the tenant.
    """
    cookie = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))
    org = await _make_org()

    async with _client() as http:
        response = await _mint(
            http, cookie, str(org["slug"]), confirm=view_as_confirmation(str(org["slug"]))
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required")
    # The way out is printed, both endpoints and the header.
    assert "/v1/auth/admin/step-up" in response.json()["remediation"]
    assert await _started_rows(uuid.UUID(str(org["id"]))) == []


@pytest.mark.asyncio
async def test_a_session_that_never_proved_a_factor_cannot_even_reach_the_door(
    operator: uuid.UUID,
) -> None:
    """A half-authenticated admin session — password accepted, code unanswered — is
    refused BEFORE the step-up gate, by `verify_token`'s `_require_second_factor`.

    Written as an assertion rather than left implicit because the two refusals mean
    different things and a reader will otherwise expect this one to be
    `reauthentication_required`: 401 says "finish signing in", 403 says "you are signed in,
    prove it is still you". The gate's own answer to a NULL `mfa_verified_at` is pinned at
    the unit level (`authn_stepup_test`); what this adds is that no route change can make
    a partial session reach the tenant door at all.
    """
    cookie = await _cookie_for(operator, factor_age=None)
    org = await _make_org()

    async with _client() as http:
        response = await _mint(
            http, cookie, str(org["slug"]), confirm=view_as_confirmation(str(org["slug"]))
        )

    assert response.status_code == 401, response.text
    assert response.json()["type"].endswith("/second_factor_required")
    assert await _started_rows(uuid.UUID(str(org["id"]))) == []


@pytest.mark.asyncio
async def test_a_confirmation_for_one_client_does_not_open_another(operator: uuid.UUID) -> None:
    """The binding, so a confirmation captured on one account is not a key to the next."""
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=5))
    tenant_a = await _make_org()
    tenant_b = await _make_org()

    async with _client() as http:
        response = await _mint(
            http, cookie, str(tenant_b["slug"]), confirm=view_as_confirmation(str(tenant_a["slug"]))
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/step_up_required")


# ═══════════════ the happy path, and what it records ═══════════════


@pytest.mark.asyncio
async def test_a_fresh_factor_opens_the_door_and_the_grant_dates_it(
    operator: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """The control has to work, or every refusal above is asserting a broken feature.

    Also pins D-22's audit obligation through the new gate: the start row still exists and
    still NAMES THE ACTOR. A step-up that quietly moved the audit write would be a fix
    that broke the thing the route exists for.
    """
    cookie = await _cookie_for(operator, factor_age=timedelta(seconds=30))
    org = await _make_org()

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await _mint(
                http, cookie, str(org["slug"]), confirm=view_as_confirmation(str(org["slug"]))
            )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == str(org["slug"])

    # The grant dates the factor, not the mint: `auth_time` is ~30s old, `exp` is ahead.
    auth_time = _auth_time_of(body["grant"])
    now = datetime.now(UTC)
    assert timedelta(seconds=5) < now - auth_time < timedelta(minutes=2)
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


# ═══════════════ renewal: the reason this is not an OTP every 14 minutes ═══════════════


@pytest.mark.asyncio
async def test_a_live_grant_renews_without_a_second_factor(
    operator: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """STAYING in a client's account does not re-challenge, and the ledger says so.

    The second mint is made with a session whose factor is now STALE and with no
    confirmation header at all — i.e. one that would be refused outright on a cold start.
    It succeeds because the caller presented the grant it already holds, which is evidence
    of both intent and presence that the two halves of the gate were asking for.
    """
    org = await _make_org()
    fresh = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            first = await _mint(
                http, fresh, str(org["slug"]), confirm=view_as_confirmation(str(org["slug"]))
            )
            assert first.status_code == 200, first.text
            held = first.json()["grant"]

            stale = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=10))
            renewed = await _mint(http, stale, str(org["slug"]), renew=held)

    assert renewed.status_code == 200, renewed.text
    rows = await _started_rows(uuid.UUID(str(org["id"])))
    assert len(rows) == 2, "a renewal is still an entry, and still audited"
    assert uuid.UUID(str(rows[1].actor_id)) == operator, "D-22: a renewal still names the actor"

    summaries = _summaries(caplog)
    assert len(summaries) == 2
    assert summaries[0].renews is None
    assert summaries[1].renews == summaries[0].grant_id, (
        "the ledger must say WHICH session this extended, or a renewal is "
        "indistinguishable from a fresh entry that skipped the gate"
    )


@pytest.mark.asyncio
async def test_a_renewal_inherits_auth_time_rather_than_restamping_it(
    operator: uuid.UUID,
) -> None:
    """THE PROPERTY THE DESIGN RESTS ON, and the one a plausible refactor would break.

    If a renewal took `now` as its `auth_time` — the natural thing to write — then
    `VIEW_AS_MAX_AGE` would bound nothing at all: each link would restart the hour and a
    console could hold a view-as session open forever on one second factor. So the
    inherited value is asserted to the second across two hops, not merely "still in the
    past".
    """
    org = await _make_org()
    fresh = await _cookie_for(operator, factor_age=timedelta(minutes=2))
    confirm = view_as_confirmation(str(org["slug"]))

    async with _client() as http:
        first = await _mint(http, fresh, str(org["slug"]), confirm=confirm)
        assert first.status_code == 200, first.text
        one = first.json()["grant"]

        second = await _mint(http, fresh, str(org["slug"]), renew=one)
        assert second.status_code == 200, second.text
        two = second.json()["grant"]

        third_response = await _mint(http, fresh, str(org["slug"]), renew=two)
        assert third_response.status_code == 200, third_response.text
        three = third_response.json()["grant"]

    origin = _auth_time_of(one)
    assert _auth_time_of(two) == origin
    assert _auth_time_of(three) == origin, "three hops, one step-up, one clock"


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
    stale = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))

    async with _client() as http:
        response = await _mint(
            http,
            stale,
            str(org["slug"]),
            confirm=view_as_confirmation(str(org["slug"])),
            renew=elapsed,
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required")
    assert await _started_rows(tenant_id) == []


@pytest.mark.asyncio
async def test_another_tenants_grant_renews_nothing(operator: uuid.UUID) -> None:
    """The replay the grant design already refuses, refused again on the renewal input.

    A grant for client A offered while minting for client B does not extend anything and
    does not leak an entry: the caller is sent to the second factor, exactly as if they
    had offered nothing.
    """
    tenant_a = await _make_org()
    tenant_b = await _make_org()
    fresh = await _cookie_for(operator, factor_age=timedelta(seconds=30))

    async with _client() as http:
        first = await _mint(
            http, fresh, str(tenant_a["slug"]), confirm=view_as_confirmation(str(tenant_a["slug"]))
        )
        assert first.status_code == 200, first.text
        grant_a = first.json()["grant"]

        stale = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))
        crossed = await _mint(
            http,
            stale,
            str(tenant_b["slug"]),
            confirm=view_as_confirmation(str(tenant_b["slug"])),
            renew=grant_a,
        )

    assert crossed.status_code == 403, crossed.text
    assert crossed.json()["type"].endswith("/reauthentication_required")
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
    stale = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))

    async with _client() as http:
        response = await _mint(
            http,
            stale,
            str(org["slug"]),
            confirm=view_as_confirmation(str(org["slug"])),
            renew=somebody_else,
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required")


@pytest.mark.asyncio
@pytest.mark.parametrize("offered", ["", "not-a-token", "a.b.c"])
async def test_junk_offered_as_a_renewal_is_a_challenge_not_a_crash(
    operator: uuid.UUID, offered: str
) -> None:
    """Every unreadable `renew` value must land on the STRICTER path, never a 500."""
    org = await _make_org()
    stale = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))

    async with _client() as http:
        response = await _mint(
            http,
            stale,
            str(org["slug"]),
            confirm=view_as_confirmation(str(org["slug"])),
            renew=offered,
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required")


@pytest.mark.asyncio
async def test_an_expired_grant_renews_nothing(operator: uuid.UUID) -> None:
    """A console that slept through its own expiry starts again rather than continuing."""
    org = await _make_org()
    stale_instant = datetime.now(UTC) - GRANT_TTL - timedelta(minutes=1)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(grant_module, "datetime", _FrozenClock(stale_instant))
        expired, _ = mint_grant(
            tenant_id=uuid.UUID(str(org["id"])), admin_id=operator, auth_time=stale_instant
        )

    cookie = await _cookie_for(operator, factor_age=REAUTH_MAX_AGE + timedelta(minutes=1))
    async with _client() as http:
        response = await _mint(
            http,
            cookie,
            str(org["slug"]),
            confirm=view_as_confirmation(str(org["slug"])),
            renew=expired,
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/reauthentication_required")


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
