"""An unverified address cannot carry a membership into a second organisation (D-185).

WHAT THIS FILE MEASURES, and why it is worth a file of its own. The 17 Aug security audit's
S-2 located "`users.email` is an authorization input with no verification check" in
`apps/api/core/clerk_identity.py`. D-177 deleted that file. The finding's QUESTION outlived
its evidence, and the answer is that the property the vendor was assumed to supply — that a
`users.email` is an address somebody proved they receive mail at — was never replaced.

THE ESCALATION, exactly as `test_a_squatted_account_cannot_be_handed_a_second_membership`
drives it and with no defect anywhere else in the chain:

  1. An owner of ANY tenant — a trial signup is enough — issues an invitation to an address
     they do not control. `POST /v1/invitations` returns the RAW TOKEN in its own 201 body,
     deliberately, because the client realm has no invitation mailer.
  2. The issuer redeems it themselves. `users` is global and `uq_users_email_lower` makes
     that the ONLY row for the address, so the attacker now holds the victim's address with
     a password they chose.
  3. The victim's real organisation invites the victim. `_find_or_create_user` finds the
     squatter's row, `has_password` is true so the password is deliberately NOT overwritten
     (overwriting would be its own takeover), and the membership attaches to the attacker's
     account.
  4. The attacker signs in with their own password. `MFA_REQUIRED_REALMS` is `{"admin"}`,
     so on the client realm a password is the entire credential.

Step 3 is the one this closes: a reused account that already carries a credential may only
take on a NEW membership once its address has been proven by an `email_verify` round trip.
Step 4 is then unreachable because step 3 never happened. What is NOT closed, and is
asserted here rather than claimed away, is the squat itself — the address stays hostage
until the token is emailed rather than handed to the inviter.

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
            headers=_headers(slug, token),
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


@pytest.mark.asyncio
async def test_a_squatted_account_cannot_be_handed_a_second_membership(
    planted: Planted,
) -> None:
    """S-2, end to end. WITHOUT D-185 the last assertion is what fails: the victim's
    membership lands on the attacker's account and the attacker signs into it."""
    attacker_tenant, attacker_slug, attacker_session = await planted.tenant()
    victim_tenant, victim_slug, victim_session = await planted.tenant()
    address = planted.address("finance")

    # 1-2. The squat: the attacker invites an address they do not control, into their
    # own tenant, and redeems their own invitation with a password only they know.
    squat_token = await _invite(attacker_slug, attacker_session, address, "staff")
    squat = await _redeem(squat_token, ATTACKER_PASSWORD)
    assert squat.status_code == 200, squat.text

    # The row exists, and it is the only one there can be for this address.
    assert await _user_id(address) is not None
    assert await _verified_at(address) is None, (
        "an address claimed through a token that was handed to the inviter has not been "
        "proven, and must not be recorded as verified"
    )

    # 3. The victim's real organisation invites the real person, as OWNER.
    real_token = await _invite(victim_slug, victim_session, address, "owner")
    hijack = await _redeem(real_token, REDEMPTION_PASSWORD)

    assert hijack.status_code == 422, hijack.text
    assert hijack.json()["type"].endswith("/invitation_account_unverified")

    # The membership never happened, so there is nothing for step 4 to sign in to.
    assert await _memberships(attacker_tenant, address) == 1, "the squat itself is unchanged"
    assert await _memberships(victim_tenant, address) == 0, (
        "the victim's tenant must not have attached a membership to an account whose "
        "address was claimed by somebody else"
    )


@pytest.mark.asyncio
async def test_the_refusal_leaves_the_invitation_redeemable(planted: Planted) -> None:
    """A refusal that burned the token would turn a security control into a lockout: the
    real owner of the mailbox could never redeem it even after verifying. So the refusal
    lands BEFORE `admin_service.accept_invitation`'s CAS, and the same token works once the
    address is proven."""
    _attacker_tenant, attacker_slug, attacker_session = await planted.tenant()
    victim_tenant, victim_slug, victim_session = await planted.tenant()
    address = planted.address("reopen")

    squat_token = await _invite(attacker_slug, attacker_session, address, "staff")
    assert (await _redeem(squat_token, ATTACKER_PASSWORD)).status_code == 200

    real_token = await _invite(victim_slug, victim_session, address, "owner")
    assert (await _redeem(real_token, REDEMPTION_PASSWORD)).status_code == 422

    # The person proves the mailbox — `POST /v1/auth/client/otp/verify`.
    await _mark_verified(address)

    second_try = await _redeem(real_token, REDEMPTION_PASSWORD)

    assert second_try.status_code == 200, second_try.text
    assert second_try.json()["tenant_id"] == str(victim_tenant)
    assert await _memberships(victim_tenant, address) == 1


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
