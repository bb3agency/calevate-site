"""The admin realm's invitation stopped handing the operator a live credential (D-198).

D-190 moved `POST /v1/tenants/invitations` — the CLIENT realm's invite — onto the mailer
and deleted `token` from its response, because "the squat is possible for exactly as long
as anyone but the invitee can see the token" (D-185). The onboarding wizard's twin,
`POST /v1/admin/tenants/{tenant_id}/invitations`, was left behind: it still returned the
raw token and mailed nothing at all.

WHAT THAT COST, and neither half needs a defect anywhere else:

  * **the squat.** An operator holds `admin:tenants`, an invitation may name any address,
    and redeeming one creates the GLOBAL `users` row for that address with a password the
    redeemer chose (`uq_users_email_lower` guarantees it is the only row). D-185 stopped the
    real person's later redemption being hijacked and said in as many words that it could
    not stop the squat — the token reaching only the invitee is what closes it.
  * **the seam.** Nothing sent the invitee anything. The wizard rendered the token on
    screen and an operator was expected to carry it by hand, so the one flow that onboards
    every client depended on a human copying a credential out of an API response.

`tests/member_invitations_test.py` asserts the same three properties on the client realm.
This file is the admin realm's copy of that assertion, not a second rule.

SHARED DATABASE DISCIPLINE (`tests/shared_state_assertion_guard_test.py`): every row hangs
off a tenant and an address this module mints; nothing counts globally.
"""

from __future__ import annotations

import uuid

import httpx
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.commercial_terms_test import _make_admin, _tenant
from tests.member_invitations_test import mailed_invitation_token

INVITATIONS = "/v1/admin/tenants/{tenant_id}/invitations"
ACCEPT = "/v1/auth/client/invitations/accept"
REDEMPTION_PASSWORD = "admin-invited-owner-password"


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _invite(token: str, tenant_id: uuid.UUID, email: str) -> httpx.Response:
    async with _client() as http:
        return await http.post(
            INVITATIONS.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email, "role": "owner"},
        )


async def test_the_operator_is_not_handed_the_token_and_the_invitee_is_mailed_it() -> None:
    """THE REGRESSION, in one test, because the two halves are one change.

    A response that stopped returning the token and did not start sending one would pass a
    "no token in the body" assertion while leaving the invitee no way in at all — which is
    why the mail is asserted in the same test rather than in a sibling.
    """
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    address = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"

    created = await _invite(operator, tenant_id, address)
    assert created.status_code == 201, created.text
    body = created.json()

    assert "token" not in body, (
        "the admin realm still hands the raw invitation token to the operator — anyone "
        "holding it can redeem it and take the global users row for that address"
    )
    assert body["delivery"] == "queued"

    # Exactly one email, addressed to the INVITEE and nobody else.
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages "
                    "WHERE job = 'deliver_auth_email' "
                    "AND payload->>'kind' = 'invite_password' "
                    "AND payload->>'to' = :to"
                ),
                {"to": address},
            )
        ).all()
    assert len(queued) == 1, "the invitee was told by nobody — the seam is not finished"

    # And the secret is not recoverable from our own database, so the mailbox really is the
    # only copy once the outbox row is dispatched and deleted.
    mailed = await mailed_invitation_token(address)
    async with tenant_session(tenant_id) as session:
        stored = (await session.execute(text("SELECT token_hash FROM invitations"))).scalar()
    assert stored != mailed

    # The mailed token is the one that WORKS — proving the two are the same secret rather
    # than two long strings that happen to coexist.
    async with _client() as http:
        redeemed = await http.post(ACCEPT, json={"token": mailed, "password": REDEMPTION_PASSWORD})
    assert redeemed.status_code in (200, 201), redeemed.text
    assert redeemed.json()["role"] == "owner"


async def test_a_rolled_back_invitation_queues_no_mail() -> None:
    """One transaction, one fate (BACKEND-PATTERNS §4).

    `create_invitation` refuses a second live token for one address, and that refusal has
    to roll the enqueue back with it — otherwise a refused request still mails a link, and
    the link names a row that the caller was told does not exist.
    """
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    address = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"

    first = await _invite(operator, tenant_id, address)
    assert first.status_code == 201, first.text
    blocked = await _invite(operator, tenant_id, address)
    assert blocked.status_code == 409, blocked.text

    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE job = 'deliver_auth_email' "
                    "AND payload->>'kind' = 'invite_password' "
                    "AND payload->>'to' = :to"
                ),
                {"to": address},
            )
        ).scalar()
    assert queued == 1, (
        "a refused invitation still queued an email, so the invitee holds a link for a "
        "row the API said it would not create"
    )


async def test_the_two_realms_queue_the_same_shape_of_mail() -> None:
    """One mailer, one payload — the guard against the admin path drifting onto its own.

    `authn.service.enqueue_invitation_email` is the single writer, and the reason this is
    asserted rather than assumed is that the admin route reached it a release later than
    the client route did: a second spelling here is how the invitee's link would come to
    point at the wrong console (`INVITE_EMAIL_REALM`).
    """
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    address = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"
    assert (await _invite(operator, tenant_id, address)).status_code == 201

    async with untenanted_session() as session:
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages "
                    "WHERE job = 'deliver_auth_email' AND payload->>'to' = :to"
                ),
                {"to": address},
            )
        ).scalar()
    assert payload is not None
    assert payload["kind"] == "invite_password"
    assert payload["realm"] == "client", (
        "an invitation mailed under the admin realm links to admin.calevate.tech, where "
        "the redemption page does not exist"
    )
    assert payload["to"] == address
