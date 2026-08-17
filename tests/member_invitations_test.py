"""Invitations issued BY a client owner (ROADMAP M3), and who can redeem them.

An invitation is a key to an account sitting in somebody's inbox, so the interesting
tests are not "does it create a membership" — `tests/platform_audit_test.py` already
pins the redemption path — but the four ways one can be turned into an escalation:

1. an owner issuing a role they do not themselves hold (`assert_role_is_grantable`)
2. `staff` issuing one at all (`org:manage`)
3. the redeemed account being somebody other than the addressee (D-177: the address
   comes from the INVITATION, so there is no comparison left to get wrong)
4. redeeming one after it was revoked, or twice

Plus the rule that stops this surface leaking: a pending invitation is listed with a
MASKED address, because `email` is in `check_redaction_exposure`'s `RAW_PII_FIELDS` and
this route is neither role-gated nor audited on read (nor should it be).

CONCURRENCY: every test mints its own organization; nothing here reads another suite's
rows.
"""

from __future__ import annotations

import uuid

import httpx
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.members_test import _colleague, _headers, _owner_user_id


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


#: Long enough for `hashing.MIN_PASSWORD_CHARS` and fixed, because nothing here is about
#: what a good password is.
REDEMPTION_PASSWORD = "invitee-redemption-password"


async def _redeem(http: httpx.AsyncClient, raw_token: str) -> httpx.Response:
    """Redeem an invitation the way an invitee actually does (D-177).

    ONE call, and NO credential: `POST /v1/auth/client/invitations/accept` creates the
    account, sets its password, burns the invitation and issues a session. The invitee has
    no account before this — that is the whole difference from the Clerk-era pair, where
    they signed up with the vendor first and this route only made the membership.
    """
    return await http.post(
        "/v1/auth/client/invitations/accept",
        json={"token": raw_token, "password": REDEMPTION_PASSWORD},
    )


async def _audit_actions(tenant_id: uuid.UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :t ORDER BY at, id"),
                {"t": tenant_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


# --- issuing ------------------------------------------------------------------


async def test_an_owner_invites_a_colleague_and_the_list_never_shows_the_address() -> None:
    tenant_id, slug, token = await _make_tenant("owner")
    address = f"priya-{uuid.uuid4().hex[:8]}@clinic.example"

    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "staff"},
            headers=_headers(slug, token),
        )
        listed = await http.get("/v1/invitations", headers=_headers(slug, token))

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["role"] == "staff"
    assert len(body["token"]) >= 20, "the raw token is returned exactly once"
    assert address not in created.text, "the address is masked even in the create response"
    assert body["email_masked"].startswith("p•") and body["email_masked"].endswith(
        "@clinic.example"
    )

    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()] == [body["id"]]
    assert address not in listed.text
    assert "member.invited:staff" in await _audit_actions(tenant_id)

    # And the token is not recoverable from our own database (hashed at rest).
    async with tenant_session(tenant_id) as session:
        stored = (await session.execute(text("SELECT token_hash FROM invitations"))).scalar()
    assert stored != body["token"]


async def test_an_invitation_cannot_carry_a_role_its_sender_does_not_hold() -> None:
    """`staff` cannot invite at all (no `org:manage`), which is the same escalation as a
    self-promotion wearing a different hat: an invitation the sender could not have
    granted directly is a way around the role table."""
    tenant_id, slug, _owner_token = await _make_tenant("owner")
    _staff_id, staff_token = await _colleague(tenant_id, role="staff")

    async with _client() as http:
        refused = await http.post(
            "/v1/invitations",
            json={"email": "outsider@example.com", "role": "owner"},
            headers=_headers(slug, staff_token),
        )

    assert refused.status_code == 403, refused.text
    async with tenant_session(tenant_id) as session:
        count = (await session.execute(text("SELECT count(*) FROM invitations"))).scalar()
    assert count == 0, "a refused invitation must not exist"


async def test_a_second_live_invitation_for_one_address_is_refused() -> None:
    """Two valid keys to one account in one inbox is one key too many; and quietly
    revoking the first would break a link that may already be in transit."""
    _tenant_id, slug, token = await _make_tenant("owner")
    address = f"dup-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        first = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "staff"},
            headers=_headers(slug, token),
        )
        second = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "staff"},
            headers=_headers(slug, token),
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["type"].endswith("/invitation_already_pending")


async def test_inviting_someone_already_on_the_team_is_refused() -> None:
    tenant_id, slug, token = await _make_tenant("owner")
    owner_id = await _owner_user_id(tenant_id)
    async with untenanted_session() as session:
        email = (
            await session.execute(text("SELECT email FROM users WHERE id = :u"), {"u": owner_id})
        ).scalar()

    async with _client() as http:
        refused = await http.post(
            "/v1/invitations",
            json={"email": str(email).upper(), "role": "staff"},
            headers=_headers(slug, token),
        )

    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/member_already_on_team")


# --- redeeming ----------------------------------------------------------------


async def test_redemption_creates_the_invited_address_and_no_other() -> None:
    """The vector: a forwarded email, a shared mailbox, a link pasted in a group chat.

    THIS TEST CHANGED SHAPE WITH D-177 AND THE CHANGE IS THE FINDING, so it is written
    down rather than left in the diff. It used to assert `invitation_wrong_recipient`: the
    invitee signed up with the vendor first, so redemption COMPARED the address they had
    signed in with against the invitation's, and a mismatch was refused. There is no
    comparison now, because there is no prior account and the request carries no address —
    the redeemed account IS the invited address by construction.

    What that trades: a link holder no longer has to already control a verified mailbox at
    the invited address, so a forwarded link now yields an account for that address to
    whoever opens it first. What it buys: an honest invitee whose mailbox is a different
    address from the one their vendor account used can no longer be locked out by a
    refusal they cannot act on, and there is no second address for the two to disagree
    about. The link is still single-use, hash-at-rest, 72h and CAS-burned; those are what
    bound the window, and `tests/authn_flow_rls_test.py` owns them.
    """
    tenant_id, slug, token = await _make_tenant("owner")
    intended = f"intended-{uuid.uuid4().hex[:8]}@example.com"
    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": intended, "role": "staff"},
            headers=_headers(slug, token),
        )
        raw = created.json()["token"]
        accepted = await _redeem(http, raw)

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "staff"

    # THE ACCOUNT THIS CREATED IS THE INVITED ADDRESS, and that is the assertion that
    # replaced `invitation_wrong_recipient` (D-177). The refusal existed because two
    # addresses had to be COMPARED: the account already existed, minted with the vendor,
    # and might have been minted with a different address. One of them is now the only
    # one — the request carries no address at all — so the property is that the row
    # matches the invitation rather than that a mismatch is caught.
    async with tenant_session(tenant_id) as session:
        addresses = set(
            (
                await session.execute(
                    text(
                        "SELECT lower(u.email) FROM users u "
                        "JOIN memberships m ON m.user_id = u.id"
                    )
                )
            ).scalars()
        )
    assert intended.lower() in addresses, "the redeemed account is the invited address"

    async with tenant_session(tenant_id) as session:
        members = (await session.execute(text("SELECT count(*) FROM memberships"))).scalar()
    assert members == 2, "the founder and the invitee — and nobody else"


async def test_a_revoked_invitation_cannot_be_redeemed_afterwards() -> None:
    tenant_id, slug, token = await _make_tenant("owner")
    address = f"revoked-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "owner"},
            headers=_headers(slug, token),
        )
        body = created.json()
        revoked = await http.delete(f"/v1/invitations/{body['id']}", headers=_headers(slug, token))
        replayed = await _redeem(http, body["token"])
        remaining = await http.get("/v1/invitations", headers=_headers(slug, token))

    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["role"] == "owner"
    assert replayed.status_code == 422, "a revoked key opens nothing"
    assert replayed.json()["type"].endswith("/invitation_invalid")
    assert remaining.json() == []
    async with tenant_session(tenant_id) as session:
        members = (await session.execute(text("SELECT count(*) FROM memberships"))).scalar()
    assert members == 1
    assert "member.invitation_revoked:owner" in await _audit_actions(tenant_id)


async def test_an_invitation_cannot_be_redeemed_twice() -> None:
    """The burn is a CAS on `used_at IS NULL` (`admin.service.accept_invitation`); this
    pins that the client-issued path inherits it rather than reimplementing it."""
    tenant_id, slug, token = await _make_tenant("owner")
    address = f"twice-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "staff"},
            headers=_headers(slug, token),
        )
        raw = created.json()["token"]
        first = await _redeem(http, raw)
        second = await _redeem(http, raw)

    assert first.status_code == 200, first.text
    assert second.status_code == 422
    async with tenant_session(tenant_id) as session:
        members = (await session.execute(text("SELECT count(*) FROM memberships"))).scalar()
    assert members == 2


async def test_an_invitation_of_another_tenant_is_invisible_and_unrevokable() -> None:
    """`invitations` is FORCE-RLS'd; the id being a UUID is not the control."""
    tenant_b, _slug_b, token_b = await _make_tenant("owner")
    _tenant_a, slug_a, token_a = await _make_tenant("owner")

    async with _client() as http:
        theirs = await http.post(
            "/v1/invitations",
            json={"email": f"b-{uuid.uuid4().hex[:8]}@example.com", "role": "staff"},
            headers=_headers(_slug_b, token_b),
        )
        their_id = theirs.json()["id"]
        stolen = await http.delete(f"/v1/invitations/{their_id}", headers=_headers(slug_a, token_a))
        mine = await http.get("/v1/invitations", headers=_headers(slug_a, token_a))

    assert stolen.status_code == 404, stolen.text
    assert mine.json() == []
    async with tenant_session(tenant_b) as session:
        alive = (
            await session.execute(text("SELECT count(*) FROM invitations WHERE used_at IS NULL"))
        ).scalar()
    assert alive == 1, "tenant B's invitation is untouched"
