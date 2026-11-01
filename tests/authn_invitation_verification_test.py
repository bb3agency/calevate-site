"""Invitations against accounts that already exist: proved, unproved, Google-only.

The 17 Aug security audit's S-2: `users.email` is an authorization input, so an account
holding an address nobody proved is a pre-hijack waiting for its victim — register the
address with your own password, wait for the real person to be invited, sign in as them.

- An UNPROVED account with a password is reclaimed by whoever redeems a token mailed to the
  address (D-955, amending D-185's refusal): the redeemer's password replaces the old one,
  every old session is revoked, and the address is marked proved.
- A PROVED account keeps its password; the redeemer must type it.
- A Google-only account is refused a password.
- The inviter is never handed the token (D-190), so the mailbox is the only place it exists.

CONCURRENCY: every test mints its own organizations and its own random addresses, and
deletes the `users` rows it planted. Nothing here reads another suite's rows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.members_test import _headers

REDEMPTION_PASSWORD = "invitee-redemption-password"
ATTACKER_PASSWORD = "attacker-chosen-password-9"


def _client() -> httpx.AsyncClient:
    """One client per ACTOR, never one per test.

    `POST /v1/auth/client/invitations/accept` sets the session cookie, and an
    `httpx.AsyncClient` keeps its cookie jar — so a test that redeemed an invitation and
    then issued the next one through the same client would be sending the invitee's
    session alongside the owner's bearer token, and `core/auth` prefers the cookie. The
    403 that produces ("You are not a member of this account") is an artefact of the
    fixture and would have looked exactly like the control working.
    """
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


class Planted:
    """The rows a test caused to exist, so the shared database gets them back.

    Addresses are recorded rather than ids: the whole point of these tests is that the
    `users` row is created by a code path under test, so its id is not known until that path
    has run — and on the paths that are supposed to REFUSE, it may not exist at all.

    Tenants have to be recorded separately because `memberships` is RLS'd: an
    `untenanted_session` deletes zero rows from it and the `users` delete then fails on the
    foreign key, which is a green test leaving litter for every later run.
    """

    def __init__(self) -> None:
        self.addresses: list[str] = []
        self.tenants: list[uuid.UUID] = []

    def address(self, prefix: str) -> str:
        chosen = f"{prefix}-{uuid.uuid4().hex[:10]}@calevate-test.example"
        self.addresses.append(chosen)
        return chosen

    async def tenant(self, role: str = "owner") -> tuple[uuid.UUID, str, str]:
        made = await _make_tenant(role)
        self.tenants.append(made[0])
        return made


@pytest_asyncio.fixture
async def planted() -> AsyncIterator[Planted]:
    ledger = Planted()
    try:
        yield ledger
    finally:
        needles = [a.casefold() for a in ledger.addresses]
        for tenant_id in ledger.tenants:
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "DELETE FROM memberships WHERE user_id IN "
                        "(SELECT id FROM users WHERE lower(email) = ANY(:emails))"
                    ),
                    {"emails": needles},
                )
        async with untenanted_session() as session:
            subjects = [
                str(row[0])
                for row in (
                    await session.execute(
                        text("SELECT id FROM users WHERE lower(email) = ANY(:emails)"),
                        {"emails": needles},
                    )
                ).all()
            ]
            for table in (
                "auth_sessions",
                "auth_credentials",
                "auth_otp_challenges",
                "auth_email_tokens",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = ANY(:ids)"),
                    {"ids": subjects},
                )
            await session.execute(
                text("DELETE FROM users WHERE lower(email) = ANY(:emails)"), {"emails": needles}
            )


async def _invite(slug: str, token: str, email: str, role: str) -> str:
    """Issue an invitation and return the raw token, read out of the queued EMAIL.

    Its docstring used to say "the way its issuer receives it", and D-190 removed the way
    an issuer receives it — the response carries no token, because a token the inviter can
    read is a token the inviter can redeem, which is the squat this file is about. The only
    readable copy is now the mail addressed to the invitee, so that is where these tests
    read it from: the same path a real invitee's link travels.
    """
    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": email, "role": role},
            headers={
                **_headers(slug, token),
                # An owner invitation takes a code typed for that address.
                **({"X-Confirm-Action": f"invite_owner:{slug}:{email}"} if role == "owner" else {}),
            },
        )
    assert created.status_code == 201, created.text
    assert "token" not in created.json(), "D-190: the response must not carry the secret"
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages "
                    "WHERE job = 'deliver_auth_email' "
                    "AND payload->>'kind' = 'invite_password' "
                    "AND payload->>'to' = :to "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"to": email},
            )
        ).first()
    assert row is not None, f"no invitation email was queued for {email!r}"
    return str(row[0]["secret"])


async def _redeem(raw_token: str, password: str) -> httpx.Response:
    async with _client() as http:
        return await http.post(
            "/v1/auth/client/invitations/accept",
            json={"token": raw_token, "password": password},
        )


async def _verified_at(email: str) -> datetime | None:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text("SELECT email_verified_at FROM users WHERE lower(email) = :e"),
                {"e": email.casefold()},
            )
        ).scalar()


async def _mark_verified(email: str) -> None:
    """What `POST /v1/auth/client/otp/verify` does on success, reached directly.

    Through `subjects.mark_email_verified` rather than through an UPDATE, so this test
    breaks if the ONE writer of that column changes shape — a fixture that wrote the column
    itself would keep passing after the real verification path stopped setting it.
    """
    from apps.api.authn.subjects import mark_email_verified

    user_id = await _user_id(email)
    assert user_id is not None
    await mark_email_verified("client", user_id, at=datetime.now(UTC))


async def _user_id(email: str) -> uuid.UUID | None:
    async with untenanted_session() as session:
        found = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = :e"), {"e": email.casefold()}
            )
        ).scalar()
    return uuid.UUID(str(found)) if found is not None else None


async def _memberships(tenant_id: uuid.UUID, email: str) -> int:
    """How many memberships this address holds IN ONE TENANT.

    Scoped rather than global because `memberships` is RLS'd: an `untenanted_session`
    counts zero for every address, which is the answer these tests want to see and would
    have got for the wrong reason.
    """
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM memberships m JOIN users u ON u.id = m.user_id "
                        "WHERE lower(u.email) = :e"
                    ),
                    {"e": email.casefold()},
                )
            ).scalar()
            or 0
        )


# ═══════════════ the finding ═══════════════


async def _password_signs_in(user_id: uuid.UUID, password: str) -> bool:
    from apps.api.authn.credentials import authenticate_subject
    from apps.api.db.session import credential_session

    async with credential_session() as session:
        return await authenticate_subject(
            session, realm="client", subject_id=user_id, password=password
        )


async def _open_session(user_id: uuid.UUID) -> str:
    """A live session for this account, as signing in with its password would leave."""
    from apps.api.authn.sessions import issue_session
    from apps.api.db.session import credential_session

    async with credential_session() as session:
        issued = await issue_session(session, realm="client", subject_id=user_id)
    return issued.token


async def _session_live(token: str) -> bool:
    from apps.api.authn.sessions import verify_session

    return (await verify_session(token=token, realm="client")).session is not None


async def _reclaim_audits(tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log "
                        "WHERE action = 'auth.invitation_reclaimed_unverified_account' "
                        "AND object_id = :s"
                    ),
                    {"s": str(user_id)},
                )
            ).scalar_one()
        )


@pytest.mark.asyncio
async def test_the_mailbox_owner_reclaims_an_unverified_account(planted: Planted) -> None:
    """D-955. An account whose address was never proved holds a password nobody showed
    belongs to the mailbox owner — a pre-hijacker's, in the worst case. Redeeming a token
    that was mailed to the address IS that proof, so the redeemer's password replaces the
    old one, every old session dies, and the address is marked proved. Under D-185 this
    redemption was refused with `invitation_account_unverified`."""
    first_tenant, first_slug, first_session = await planted.tenant()
    owned_tenant, owned_slug, owned_session = await planted.tenant()
    address = planted.address("reclaim")

    first = await _invite(first_slug, first_session, address, "staff")
    assert (await _redeem(first, ATTACKER_PASSWORD)).status_code == 200
    user_id = await _user_id(address)
    assert user_id is not None
    assert await _verified_at(address) is None
    old_session = await _open_session(user_id)

    real_token = await _invite(owned_slug, owned_session, address, "owner")
    reclaimed = await _redeem(real_token, REDEMPTION_PASSWORD)

    assert reclaimed.status_code == 200, reclaimed.text
    assert reclaimed.json()["tenant_id"] == str(owned_tenant)
    assert await _memberships(owned_tenant, address) == 1
    assert await _user_id(address) == user_id, "the account is reclaimed, not replaced"
    assert await _verified_at(address) is not None
    assert not await _password_signs_in(user_id, ATTACKER_PASSWORD)
    assert await _password_signs_in(user_id, REDEMPTION_PASSWORD)
    assert not await _session_live(old_session), "a session the old password opened survived"
    assert await _reclaim_audits(owned_tenant, user_id) == 1
    assert await _memberships(first_tenant, address) == 1, "earlier memberships are kept"


@pytest.mark.asyncio
async def test_a_refused_password_leaves_an_unverified_account_untouched(
    planted: Planted,
) -> None:
    """The reclaim happens only once the new password passes the policy: a refusal must not
    have already revoked sessions or marked the address, and the token must still work."""
    _first_tenant, first_slug, first_session = await planted.tenant()
    owned_tenant, owned_slug, owned_session = await planted.tenant()
    address = planted.address("retype")

    first = await _invite(first_slug, first_session, address, "staff")
    assert (await _redeem(first, ATTACKER_PASSWORD)).status_code == 200
    user_id = await _user_id(address)
    assert user_id is not None
    old_session = await _open_session(user_id)

    real_token = await _invite(owned_slug, owned_session, address, "owner")
    weak = await _redeem(real_token, "password1234")

    assert weak.status_code == 422, weak.text
    assert await _verified_at(address) is None
    assert await _password_signs_in(user_id, ATTACKER_PASSWORD)
    assert await _session_live(old_session)
    assert await _memberships(owned_tenant, address) == 0

    retyped = await _redeem(real_token, REDEMPTION_PASSWORD)
    assert retyped.status_code == 200, retyped.text
    assert not await _session_live(old_session)


@pytest.mark.asyncio
async def test_a_first_time_invitee_is_unaffected(planted: Planted) -> None:
    """The common case must not pay for the control. A brand-new address has no account and
    no password, so the condition is not reached: one call still creates the user, sets the
    password, makes the membership and issues a session."""
    tenant_id, slug, session_token = await planted.tenant()
    address = planted.address("newcomer")

    raw = await _invite(slug, session_token, address, "staff")
    accepted = await _redeem(raw, REDEMPTION_PASSWORD)

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tenant_id"] == str(tenant_id)
    assert await _memberships(tenant_id, address) == 1
    assert await _verified_at(address) is None, (
        "a first membership rides on the inviter vouching inside their own tenant; it is "
        "not evidence about the mailbox, and must not be recorded as if it were"
    )


@pytest.mark.asyncio
async def test_a_verified_account_still_joins_a_second_organisation(planted: Planted) -> None:
    """The legitimate shape the control must not break: one person, staff at two client
    businesses. `memberships` is a many-to-many because this is ordinary."""
    first_tenant, first_slug, first_session = await planted.tenant()
    second_tenant, second_slug, second_session = await planted.tenant()
    address = planted.address("twohats")

    first = await _invite(first_slug, first_session, address, "staff")
    assert (await _redeem(first, REDEMPTION_PASSWORD)).status_code == 200
    await _mark_verified(address)

    second = await _invite(second_slug, second_session, address, "staff")
    joined = await _redeem(second, REDEMPTION_PASSWORD)

    assert joined.status_code == 200, joined.text
    assert joined.json()["tenant_id"] == str(second_tenant)
    assert await _memberships(first_tenant, address) == 1
    assert await _memberships(second_tenant, address) == 1


@pytest.mark.asyncio
async def test_a_forwarded_link_does_not_sign_its_holder_into_an_existing_account(
    planted: Planted,
) -> None:
    """The typed password used to be ignored for an account that already had one, and the
    holder of the link got a session as that account in every organisation it belongs to."""
    _first_tenant, first_slug, first_session = await planted.tenant()
    second_tenant, second_slug, second_session = await planted.tenant()
    address = planted.address("forwarded")

    first = await _invite(first_slug, first_session, address, "staff")
    assert (await _redeem(first, REDEMPTION_PASSWORD)).status_code == 200
    await _mark_verified(address)

    second = await _invite(second_slug, second_session, address, "staff")
    guessed = await _redeem(second, "a-colleague-guessing-123")

    assert guessed.status_code == 401, guessed.text
    assert guessed.json()["type"].endswith("/invitation_existing_account_password")
    assert not guessed.cookies, "no session for a holder who did not prove the account"
    assert await _memberships(second_tenant, address) == 0
    # The invitation is not burned: the real person redeems it with their password.
    joined = await _redeem(second, REDEMPTION_PASSWORD)
    assert joined.status_code == 200, joined.text
    assert await _memberships(second_tenant, address) == 1


@pytest.mark.asyncio
async def test_an_invitation_cannot_give_a_google_account_a_password(planted: Planted) -> None:
    from apps.api.authn.service import has_password
    from apps.api.authn.subjects import create_verified_client

    tenant_id, slug, session_token = await planted.tenant()
    address = planted.address("google")
    user_id = await create_verified_client(email=address, name=None, at=datetime.now(UTC))
    assert user_id is not None

    token = await _invite(slug, session_token, address, "staff")
    refused = await _redeem(token, "link-holder-chosen-pass-1")

    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/invitation_use_google")
    assert not await has_password("client", user_id)
    assert await _memberships(tenant_id, address) == 0


# ═══════════════ the residual, and its closure ═══════════════


@pytest.mark.asyncio
async def test_the_inviter_is_handed_nothing_they_could_redeem(planted: Planted) -> None:
    """D-190 closes D-185's residual, and this is the assertion that says so.

    D-185 turned an ACCOUNT TAKEOVER into a DENIAL OF SERVICE and could go no further: the
    attacker still ended up holding the address, because `InvitationCreatedOut.token`
    handed them the secret. The test that stood here pinned that residual and said it would
    close "when the invitation token is emailed instead of returned to its issuer". That is
    D-190, so it is replaced by its inverse rather than deleted.

    IT IS DELIBERATELY WRITTEN FROM THE ATTACKER'S SIDE, using only what the API gives
    them. `_invite` above now reads the token out of the outbox, which is a database
    privilege no caller has — a squat test built on that helper would prove nothing,
    because it would grant itself the very access the fix removes. So this one calls the
    route directly and inspects the RESPONSE, which is the whole of what an inviter sees.
    """
    _attacker_tenant, attacker_slug, attacker_session = await planted.tenant()
    address = planted.address("hostage")

    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "staff"},
            headers=_headers(attacker_slug, attacker_session),
        )

    assert created.status_code == 201, created.text
    body = created.json()
    # Nothing in the response is redeemable: no `token` field, and no credential-shaped
    # value anywhere in it. The second check is what stops a future field quietly carrying
    # the secret back under another name.
    assert "token" not in body
    assert body["delivery"] == "queued"
    smuggled = [
        key
        for key, value in body.items()
        if isinstance(value, str)
        and len(value) >= 20
        # The invited ADDRESS, which is long and hyphen-free and is not a credential
        # (D-436 renamed it from `email_masked`). The token is what this filter hunts.
        and key != "email"
        and "-" not in value
    ]
    assert smuggled == [], f"a credential-shaped value survives in the response: {smuggled}"

    # And with nothing to redeem, the address is still free — the squat is not merely
    # harder, it is unreachable from where an attacker stands.
    assert await _user_id(address) is None
