"""Tenant birth, provisioning and offboarding as the FAILURE MODES see them.

`tests/tenant_lifecycle_test.py` walks the lifecycle's happy route and its three
transition answers. This file is the other half: what happens when a step of the birth
does not land, when the wizard is re-run, when two operators race, when a business is
named in the script the product is built for, and when a key is cut for — or redeemed
into — an account that is already gone.

Every case here was a real behaviour of this repo, reached over HTTP as an operator or
an invitee would, and each one is named at its test. The five that were defects:

1. **A mistyped tenant id in the invite path was a 500.** `invitations` carries an FK to
   `organizations`, so `POST /v1/admin/tenants/{typo}/invitations` escaped as an
   IntegrityError with an `unhandled_exception` alert and nothing an operator could act
   on. D-65's third answer is a 404.
2. **A CLOSED account could still be given a key**, and a key already in an inbox could
   still be REDEEMED into one — a 201 and a 200. `core/auth.py` resolves memberships
   with `o.deleted_at IS NULL AND o.status <> 'churned'`, so the invitee burned their
   single-use token and was then told "You are not a member of this account" on their
   first request, with no way back.
3. **A soft-deleted client answered 200 to the lifecycle switch** while the directory
   route answered 404 for the same id on the same screen.
4. **Every business named in a non-Latin script became `/c/client`.** `slugify` folded
   Telugu, Hindi and Devanagari to the empty string and fell back to a constant, so the
   FIRST such client silently took the slug `client` — immutable, in every URL — and the
   SECOND was refused `slug_taken`, a 409 naming a slug nobody typed. On a Telugu-first
   product (D-36) that is the default path.
5. **The wizard's audit row was a second transaction.** A client account whose creation
   nobody recorded is exactly the row a later dispute needs, and it was the one write
   that could fail on its own.

CONCURRENCY: every case mints its own tenant, its own operator and its own addresses,
and asserts only on rows it created.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.commercial_terms_test import _make_admin, _tenant
from tests.conftest import FakeS3

TENANTS = "/v1/admin/tenants"
INVITATIONS = "/v1/admin/tenants/{tenant_id}/invitations"
STATUS = "/v1/admin/tenants/{tenant_id}/status"
ACCEPT = "/v1/auth/client/invitations/accept"


# --- harness ------------------------------------------------------------------


def _client(*, own_address: bool = False) -> AsyncClient:
    """`own_address` gives this client its OWN source IP, and only the signup case needs it.

    `assert_signup_quota` has a per-IP fixed window of 30 an hour, and every client built
    from a bare `ASGITransport` shares the transport's default address — so a suite re-run
    within the hour starts answering 429 on a test that is not about the quota, which is
    how a green sabotage baseline turns into a red one for no reason at all. The idiom is
    `tests/self_serve_test.py::_client`, where the same trap was found first.
    """
    transport = (
        ASGITransport(app=app, client=(f"198.51.100.{uuid.uuid4().int % 250 + 1}", 12345))
        if own_address
        else ASGITransport(app=app)
    )
    return AsyncClient(transport=transport, base_url="http://api")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_tenant(token: str, **body: Any) -> Any:
    async with _client() as http:
        return await http.post(TENANTS, headers=_auth(token), json=body)


async def _invite(token: str, tenant_id: UUID, email: str, role: str = "owner") -> Any:
    async with _client() as http:
        return await http.post(
            INVITATIONS.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"email": email, "role": role},
        )


async def _set_status(token: str, tenant_id: UUID, status: str, reason: str | None = None) -> Any:
    body: dict[str, Any] = {"status": status}
    if reason is not None:
        body["reason"] = reason
    async with _client() as http:
        return await http.post(STATUS.format(tenant_id=tenant_id), headers=_auth(token), json=body)


async def _founder(email: str) -> str:
    """A client-realm account with no membership — what `POST /v1/auth/signup` is for.

    Created directly rather than through a flow, because there is no public account-intake
    door today (AUTH-MIGRATION §11, C-11) and this test is about slug derivation.
    """
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": email},
        )
    return f"dev:client:{user_id}"


async def _accept(invite_token: str) -> Any:
    """Redemption as an invitee performs it (D-177): one call, and no prior account.

    The Clerk-era shape took a token from an ALREADY SIGNED-IN caller, so every test here
    had to mint a `users` row first and hand it a bearer credential. There is no such state
    now — `POST /v1/auth/client/invitations/accept` creates the account, sets its password
    and issues the session, and the address comes from the invitation. That deleted the
    `_clerk_user` fixture rather than renaming it: the "mirrored identity with no
    membership" it produced is not a state this product has.
    """
    async with _client() as http:
        return await http.post(
            ACCEPT, json={"token": invite_token, "password": "tenant-birth-invitee-password"}
        )


async def _soft_delete(tenant_id: UUID) -> None:
    # The tenant's OWN session: `organizations`' policy matches on `id`, so an untenanted
    # session would silently write no row and the fixture would assert nothing.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            # `status = 'churned'` in the same statement, because `deleted_at` is not a
            # free-standing flag: `ck_organizations_deleted_implies_churned` (D-122) makes
            # an erased tenant always a churned one, which is what lets the readers of the
            # column filter on different halves of "account closed" and still agree. The
            # real writer (`workers/retention.execute_tenant_erasure`) refuses to run at
            # all unless the account is already churned, so this fixture is now producing
            # a state the product can actually reach rather than one only a test could.
            text("UPDATE organizations SET deleted_at = now(), status = 'churned' WHERE id = :t"),
            {"t": tenant_id},
        )


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).scalar()


async def _org_count(*, slug: str | None = None, name: str | None = None) -> int:
    """How many accounts exist with this slug (or this name), ACROSS tenants.

    Counted through `admin_session` — the same widening the client directory uses and the
    only one that can see another tenant's `organizations` row. "Did a second account
    appear anywhere" is not a question a tenant-scoped session can answer, and answering
    it from inside one tenant is how a duplicate goes unnoticed.
    """
    from apps.api.db.session import admin_session

    async with admin_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM organizations WHERE "
                        "(CAST(:s AS text) IS NULL OR slug = :s) AND "
                        "(CAST(:n AS text) IS NULL OR name = :n)"
                    ),
                    {"s": slug, "n": name},
                )
            ).scalar_one()
        )


# ============================================================================
# 1. A key cannot be cut for an account that is not there or is not open
# ============================================================================


async def test_a_tenant_id_that_names_no_client_is_a_404_not_a_500() -> None:
    """The typo case, and it used to be the worst-behaved path on this surface.

    `invitations` has `fk_invitations_tenant_id_organizations`, so the INSERT for an id
    that names nothing raised an IntegrityError straight out of the route: a 500, an
    `unhandled_exception` alert page for the on-call, and an operator told only that
    something broke. The same 404 an unknown id gets everywhere else is both the honest
    answer and the one that does not confirm whether the account exists.
    """
    token = await _make_admin("operator")

    response = await _invite(token, uuid.uuid4(), "priya@clinic.example")

    assert response.status_code == 404, response.text
    assert response.json()["title"] == "Client not found"


async def test_a_closed_account_cannot_be_given_a_key() -> None:
    """FLOWS §9: churn starts the retention countdown. An account on its way out is not
    taking on staff, and the 201 this used to answer put a live owner credential for a
    dead tenant into somebody's inbox."""
    token = await _make_admin("operator")
    tenant_id = await _tenant()
    await _set_status(token, tenant_id, "churned", "offboarded at the client's request")

    response = await _invite(token, tenant_id, f"{uuid.uuid4().hex[:8]}@clinic.example")

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"].endswith("/account_closed")
    assert body["remediation"], "a refusal an operator cannot act on is not a refusal"


async def test_a_soft_deleted_account_cannot_be_given_a_key_either() -> None:
    """`deleted_at` and `status = 'churned'` are two spellings of gone — `core/auth.py`
    excludes both from every membership resolution — so one refusal has to cover both, or
    the erasure path becomes a way around the offboarding path."""
    token = await _make_admin("operator")
    tenant_id = await _tenant()
    await _soft_delete(tenant_id)

    response = await _invite(token, tenant_id, f"{uuid.uuid4().hex[:8]}@clinic.example")

    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/account_closed")


async def test_a_suspended_account_can_still_be_given_a_key() -> None:
    """THE DELIBERATE NON-REFUSAL, pinned so nobody tightens it by symmetry.

    Suspension stops OUTBOUND DIALLING and nothing else; it is reversible in one press
    (`_LIFECYCLE_FROM` sends `suspended` straight back to `active`), and an account
    suspended over non-payment is exactly when somebody needs to add the person who will
    pay the bill. Refusing here would silently turn a billing stop into an access stop.
    """
    token = await _make_admin("operator")
    tenant_id = await _tenant()
    await _set_status(token, tenant_id, "suspended", "card declined, chasing")

    response = await _invite(token, tenant_id, f"{uuid.uuid4().hex[:8]}@clinic.example")

    assert response.status_code == 201, response.text


async def test_an_address_already_on_another_clients_team_can_still_be_invited() -> None:
    """The refusal is "already on THIS team", and the tenancy control is the RLS policy
    rather than a WHERE clause.

    A person can genuinely work for two of our clients — an accountant, a group's
    regional manager — so refusing them would be wrong on its own. It would also be a
    disclosure: "is this address already on the platform" is not a question an operator
    of one account may ask about another. `create_invitation` reads `memberships` with no
    tenant filter precisely so that the policy answers it, and this fails the moment
    somebody runs that read outside a tenant session.
    """
    token = await _make_admin("operator")
    shared_email = f"accountant-{uuid.uuid4().hex[:8]}@example.com"
    first, second = await _tenant(), await _tenant()

    minted = await _invite(token, first, shared_email)
    accepted = await _accept(minted.json()["token"])
    elsewhere = await _invite(token, second, shared_email)

    assert minted.status_code == 201 and accepted.status_code == 200, accepted.text
    assert elsewhere.status_code == 201, (
        "a person on one client's team must still be invitable to another — and asking "
        "the question must not reveal that they are on the first"
    )


# ============================================================================
# 2. A key already in an inbox, redeemed after the account closed
# ============================================================================


async def test_a_key_cut_before_the_account_closed_cannot_be_redeemed_after() -> None:
    """The 200 that was worse than a refusal.

    The invitee's token burned, a `memberships` row appeared, the response said `role:
    owner` — and their very first authenticated request was refused "You are not a member
    of this account", because `core/auth.py` filters churned orgs out of the resolution.
    Single-use token spent, membership row on a dead tenant, and nothing anywhere telling
    the person what actually happened.
    """
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    email = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"
    minted = await _invite(operator, tenant_id, email)
    invite_token = minted.json()["token"]
    await _set_status(operator, tenant_id, "churned", "client sold the business")

    response = await _accept(invite_token)

    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/account_closed")


async def test_the_refused_redemption_does_not_burn_the_link() -> None:
    """`accept_invitation` checks the account AFTER the CAS that burns the token, because
    the CAS is what supplies the tenant id atomically — so the refusal is only safe if the
    rollback really undoes the burn. A closed account quietly eating somebody's single-use
    link would be a worse defect than the one the refusal closes."""
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    email = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"
    invitation_id = (await _invite(operator, tenant_id, email)).json()["id"]
    await _soft_delete(tenant_id)

    await _accept("irrelevant-the-refusal-comes-first" + "x" * 20)
    used_at = await _scalar(
        tenant_id, "SELECT used_at FROM invitations WHERE id = :i", i=invitation_id
    )

    assert used_at is None, "a refused acceptance must leave the invitation redeemable"


async def test_a_refused_redemption_creates_no_membership() -> None:
    """The other half of the rollback, and the one with the security consequence: a
    membership row on a closed tenant is invisible to `core/auth.py` today and would
    become live the moment anybody wrote a reinstatement path."""
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    email = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"
    invite_token = (await _invite(operator, tenant_id, email)).json()["token"]
    await _set_status(operator, tenant_id, "churned", "offboarded")

    await _accept(invite_token)
    members = await _scalar(tenant_id, "SELECT count(*) FROM memberships")

    assert members == 0


async def test_the_owner_of_a_closed_account_is_told_it_closed_not_that_they_are_a_stranger() -> (
    None
):
    """The wall the people who were ALREADY inside hit (D-189).

    The two tests above close the door on a key cut for a dead account. Nobody had
    walked the other half: the owner who has been signing in for months, whose account
    an operator closes on Friday, and who opens the dashboard on Monday. `core/auth.py`
    resolves memberships with `o.status <> 'churned'`, so the resolution came back empty
    and they were told "You are not a member of this account" — on their own account, in
    a product whose offboarding flow (FLOWS §9) hands them an export of the very data
    that screen shows. It is false, and it names nothing they can do.

    `account_closed` is the name `assert_account_open` and the dial gate already give
    this state; the remediation is the one thing left that a person in this position can
    actually act on.
    """
    operator = await _make_admin("operator")
    tenant_id = await _tenant()
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"owner-{user_id.hex[:8]}@clinic.example"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    token = f"dev:client:{user_id}"

    async with _client() as http:
        before = await http.get("/v1/leads", headers=_auth(token))
    assert before.status_code == 200, before.text

    await _set_status(operator, tenant_id, "churned", "contract ended")

    async with _client() as http:
        after = await http.get("/v1/leads", headers=_auth(token))
    assert after.status_code == 403, after.text
    body = after.json()
    assert body["type"].endswith("/account_closed"), body
    assert "closed" in body["detail"]
    assert body["remediation"], "a person who has just lost their data needs a next step"


async def test_a_genuine_stranger_is_still_told_they_are_not_a_member() -> None:
    """The other branch, which the fix must not swallow.

    A caller with no membership anywhere must keep getting the neutral refusal — telling
    them "this account is closed" would be inventing a fact about an account they have
    nothing to do with, and would answer a question they are not entitled to ask.
    """
    token = await _founder(f"stranger-{uuid.uuid4().hex[:8]}@example.com")

    async with _client() as http:
        response = await http.get("/v1/leads", headers=_auth(token))

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/forbidden")


# ============================================================================
# 3. The lifecycle switch and the directory must describe one client
# ============================================================================


async def test_a_soft_deleted_client_is_not_one_the_lifecycle_switch_can_move() -> None:
    """Two admin surfaces disagreed about whether an account existed, in one screen.

    `transition_status` keys on the row id and knows nothing about `deleted_at`, so a
    soft-deleted tenant answered `200 {"changed": true}` to a suspend while
    `GET /v1/admin/tenants/{id}` — which filters `deleted_at IS NULL` — answered 404 for
    the same id. `service.tenant_exists` is the one definition of "live organization" and
    both routes ask it now.
    """
    token = await _make_admin("operator")
    tenant_id = await _tenant()
    await _soft_delete(tenant_id)

    moved = await _set_status(token, tenant_id, "suspended", "typo — this client is gone")
    async with _client() as http:
        directory = await http.get(f"{TENANTS}/{tenant_id}", headers=_auth(token))

    assert moved.status_code == 404, moved.text
    assert directory.status_code == 404, "the two surfaces have to agree"
    assert (
        await _scalar(
            tenant_id,
            "SELECT status FROM organizations WHERE id = :t",
            t=tenant_id,
            # `churned` because `_soft_delete` now sets it: `deleted_at` is a refinement of
            # `churned` and the database says so (D-122). What this asserts is unchanged —
            # the refused SUSPEND wrote nothing — and the point stands more sharply than
            # before, since `churned` is the state the switch would otherwise have moved.
        )
        == "churned"
    ), "the refused transition wrote nothing"


async def test_a_churned_client_still_reaches_the_transition_and_gets_its_409() -> None:
    """Closed and deleted are different facts, and only the 404 case is about existence.
    A churned account is still an account: the operator asking to reopen it must be told
    `churned` — the state `transition_status` found — not "no such client"."""
    token = await _make_admin("operator")
    tenant_id = await _tenant()
    await _set_status(token, tenant_id, "churned", "offboarded")

    response = await _set_status(token, tenant_id, "active")

    assert response.status_code == 409, response.text
    assert "churned" in response.text


# ============================================================================
# 4. A business name we cannot build a URL from
# ============================================================================


TELUGU_NAME = "మా క్లినిక్"
HINDI_NAME = "नमस्ते क्लिनिक"
#: U+0C66..U+0C6F. A test needing a UNIQUE name that still yields no ASCII cannot reach
#: for `uuid4().hex` — that would be Latin, and the derivation it is probing would
#: succeed on the suffix alone.
TELUGU_DIGITS = "౦౧౨౩౪౫౬౭౮౯"


def _unique_telugu_name() -> str:
    return (
        TELUGU_NAME + " " + "".join(TELUGU_DIGITS[int(d)] for d in uuid.uuid4().hex if d.isdigit())
    )


@pytest.mark.parametrize("name", [TELUGU_NAME, HINDI_NAME, "Om", "🏥🏥"])
async def test_a_name_that_yields_no_web_address_is_asked_about_never_guessed(name: str) -> None:
    """THE DEFAULT PATH ON A TELUGU-FIRST PRODUCT, not an edge case.

    Every character of these names is outside `[a-z0-9]`, so the derivation produced the
    empty string and `slugify` substituted the constant `"client"`. The first such client
    took `/c/client` — immutable, in every URL their staff types — and the second was
    refused `slug_taken`, a 409 naming a slug nobody had typed and offering no way
    forward. `"Om"` is the same defect from the other end: two characters is a legal
    business name and an illegal slug, and the refusal used to be `invalid_slug` pointing
    at a `slug` field the operator had deliberately left blank.

    Transliteration would be the nicer answer and is not available here — see
    `admin.service.slugify` for the three things that were tried.
    """
    token = await _make_admin("operator")

    response = await _create_tenant(token, name=name, vertical_template="clinic")

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["type"].endswith("/slug_not_derivable")
    assert [field["field"] for field in body["fields"]] == ["slug"], (
        "the refusal has to name the input the operator must fill in"
    )
    assert body["remediation"]


async def test_two_clients_named_in_telugu_do_not_collide_on_one_derived_slug() -> None:
    """The consequence the constant fallback actually had. Both accounts are creatable —
    the operator answers the question once each — where before, the second one could not
    be created at all without knowing that `client` was already taken by an unrelated
    business."""
    token = await _make_admin("operator")
    first_slug = f"ma-clinic-{uuid.uuid4().hex[:6]}"
    second_slug = f"vere-clinic-{uuid.uuid4().hex[:6]}"

    first = await _create_tenant(token, name=TELUGU_NAME, slug=first_slug)
    second = await _create_tenant(token, name="వేరే క్లినిక్", slug=second_slug)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["slug"] == first_slug and second.json()["slug"] == second_slug


async def test_the_refused_name_creates_no_account_at_all() -> None:
    """A validation refusal that had already written the org row would leave the slug
    held by an account nobody meant to create — and the slug is immutable."""
    token = await _make_admin("operator")
    name = _unique_telugu_name()

    await _create_tenant(token, name=name)

    assert await _org_count(name=name) == 0, (
        "a refused derivation must write nothing — under the old constant fallback this "
        "business was born at /c/client"
    )


async def test_self_serve_signup_asks_for_the_web_address_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other motion, over its own route, because the derivation is shared and the
    consequence is not.

    D-34's whole argument is one product with two doors; `tenancy/signup.derive_slug`
    delegates to the wizard's so a business gets the same URL either way. It has to get
    the same SENTENCE either way as well — and here it matters more, because there is no
    operator watching: a prospect typing their business name in Telugu on the public
    signup form was the person most likely to be handed `/c/client` and never told.
    """
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", True)
    founder = await _founder(f"founder-{uuid.uuid4().hex[:8]}@example.com")

    async with _client(own_address=True) as http:
        response = await http.post(
            "/v1/auth/signup",
            headers=_auth(founder),
            json={"business_name": HINDI_NAME, "vertical_template": "clinic"},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/slug_not_derivable")


async def test_a_long_name_is_never_cut_into_a_slug_ending_in_a_hyphen() -> None:
    """The derived slug is IMMUTABLE and lives in every URL, so a cosmetic defect here is
    permanent. `SLUG_RE` accepts `sunrise-clinic-and-diagnostics-centre-` — truncating
    after the hyphen strip rather than before is how one gets written. The name below is
    built so the 40-character cut lands exactly on the separator.
    """
    token = await _make_admin("operator")
    # Exactly 39 characters, and unique per run — the slug is immutable and this suite
    # runs against a database other cases have already written to.
    lead = "a" * 31 + uuid.uuid4().hex[:8]

    created = await _create_tenant(token, name=f"{lead} clinic")

    assert created.status_code == 201, created.text
    assert created.json()["slug"] == lead, "the trailing separator must be gone"


async def test_a_reserved_slug_is_refused_at_the_write_not_only_in_the_form() -> None:
    """`scripts/seed` loads 43 reserved slugs and the console has no idea what is on that
    list. The check has to be where the row is written, or a client ends up at
    `/c/billing`."""
    token = await _make_admin("operator")

    response = await _create_tenant(token, name="Billing Services Ltd", slug="billing")

    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/slug_reserved")


# ============================================================================
# 5. Re-running the wizard: after success, and twice at once
# ============================================================================


async def test_re_running_the_wizard_on_a_created_account_does_not_make_a_second_one() -> None:
    """What an operator actually does when the first response scrolls away or a tab is
    left open. The slug is the identity: the second attempt is refused by name and the
    account is not duplicated."""
    token = await _make_admin("operator")
    slug = f"repeat-{uuid.uuid4().hex[:8]}"

    first = await _create_tenant(token, name="Sunrise Clinic", slug=slug)
    second = await _create_tenant(token, name="Sunrise Clinic", slug=slug)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["type"].endswith("/slug_taken")
    assert await _org_count(slug=slug) == 1


async def test_two_operators_creating_one_slug_at_once_produce_exactly_one_account() -> None:
    """The probe in `create_organization` runs in its own transaction one round trip
    before the INSERT, so two concurrent creates can BOTH pass it. The UNIQUE index is
    the arbiter that cannot be raced, and the loser's IntegrityError is translated back
    into the same 409 the probe would have given — a 500 here would be indistinguishable
    from a real outage on the one screen where an operator retries.
    """
    token = await _make_admin("operator")
    slug = f"race-{uuid.uuid4().hex[:8]}"

    responses = await asyncio.gather(
        _create_tenant(token, name="Race Clinic", slug=slug),
        _create_tenant(token, name="Race Clinic", slug=slug),
    )

    codes = sorted(response.status_code for response in responses)
    assert codes == [201, 409], [response.text for response in responses]
    assert await _org_count(slug=slug) == 1


async def test_a_second_invitation_for_one_address_is_refused_in_the_admin_realm_too() -> None:
    """The wizard's Create-invite button, pressed twice. Both refusals live in
    `admin.service.create_invitation` — the one statement that mints the row — so the
    admin realm inherits what the client realm enforces (FLOWS §1 step 8)."""
    token = await _make_admin("operator")
    tenant_id = await _tenant()
    email = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"

    first = await _invite(token, tenant_id, email)
    second = await _invite(token, tenant_id, email)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["type"].endswith("/invitation_already_pending")


# ============================================================================
# 6. The record of a birth commits with the birth
# ============================================================================


async def test_the_wizard_writes_its_audit_row_inside_the_birth_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure the second transaction had: a client account nobody recorded creating.

    Driven by making the audit write fail, which is the only way to tell "same
    transaction" from "two transactions that both happened to succeed". The tenant must
    not exist afterwards — and the slug must be free for the retry, which is the property
    `tests/signup_atomicity_test.py` established for the other motion.
    """
    token = await _make_admin("operator")
    slug = f"audit-{uuid.uuid4().hex[:8]}"

    async def _explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit chain unavailable")

    monkeypatch.setattr("apps.api.admin.routes.write_audit", _explode)
    with pytest.raises(RuntimeError):
        await _create_tenant(token, name="Audited Clinic", slug=slug)

    assert await _org_count(slug=slug) == 0, "an unrecorded client account must not exist"


async def test_an_invitation_and_the_record_of_who_cut_it_commit_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live owner credential with nothing saying who issued it is the single worst row
    in this table to be missing — and it was written on a different session, after the
    invitation had already committed."""
    token = await _make_admin("operator")
    tenant_id = await _tenant()

    async def _explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit chain unavailable")

    monkeypatch.setattr("apps.api.admin.routes.write_audit", _explode)
    with pytest.raises(RuntimeError):
        await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")

    assert await _scalar(tenant_id, "SELECT count(*) FROM invitations") == 0, (
        "an owner credential exists that no audit row accounts for"
    )


async def test_a_created_account_carries_the_audit_row_that_names_its_operator() -> None:
    """The positive half: same transaction, and the row still says what it always said."""
    token = await _make_admin("operator")
    slug = f"recorded-{uuid.uuid4().hex[:8]}"

    created = await _create_tenant(token, name="Recorded Clinic", slug=slug)
    tenant_id = UUID(created.json()["id"])

    actions = await _scalar(
        tenant_id,
        "SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = 'admin.tenant_created'",
        t=tenant_id,
    )
    assert actions == 1


# ============================================================================
# 7. Offboarding: FLOWS §9's countdown, asserted through the real transition
# ============================================================================


async def test_churning_a_client_leaves_its_data_on_the_retention_clock(s3: FakeS3) -> None:
    """FLOWS §9: "client churns → … → retention countdown per policy".

    `tests/pipeline_audit_test.py` pins the SOFT-DELETED half of this (D-115, and the
    sweep is deliberately unfiltered on `organizations.deleted_at`). The half that was
    never asserted is the one an operator actually produces: `POST
    /v1/admin/tenants/{id}/status` with `churned`, which is the only way the status is
    ever written. A sweep that skipped ended accounts — the obvious "don't waste ticks on
    dead tenants" optimisation — would stop exactly the countdown the offboarding starts,
    and it would look like a performance win in review.

    Driven through the ROUTE rather than by writing the column, because the claim is
    about what churning a client does.
    """
    from apps.workers.retention import apply_retention
    from tests.retention_test import _tenant_with_old_call

    token = await _make_admin("operator")
    tenant_id, call_id = await _tenant_with_old_call(
        200, f"+9198765{uuid.uuid4().int % 100000:05d}"
    )
    # The sweep destroys the OBJECT and only then clears the reference; with no store
    # reachable it deliberately DEFERS rather than dropping the only handle on the bytes
    # (D-115). Without this fixture the assertion below would be reading the deferral.
    key = await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    s3.objects[str(key)] = b"audio"

    closed = await _set_status(token, tenant_id, "churned", "offboarded, export delivered")
    await apply_retention({})

    assert closed.status_code == 200, closed.text
    recording = await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    assert recording is None, (
        "churn starts the retention countdown — an offboarded client's recordings must "
        "still expire on schedule"
    )


# ============================================================================
# 8. Tenancy (hard rule 1)
# ============================================================================


async def test_the_account_check_cannot_see_a_neighbours_organization() -> None:
    """`assert_account_open` runs under the caller's own tenant session and
    `organizations`' policy matches on `id`, so a neighbour's id is INVISIBLE rather than
    merely filtered — the 404 is produced by the policy, not by a WHERE clause somebody
    could delete.

    At service level deliberately: the route always opens the session for the id in its
    own path, so the only way to express "a session pointed at the wrong tenant" is to
    build one.
    """
    from apps.api.admin.service import assert_account_open

    tenant_id = await _tenant()
    neighbour_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await assert_account_open(session, tenant_id=neighbour_id)

    assert raised.value.status == 404
