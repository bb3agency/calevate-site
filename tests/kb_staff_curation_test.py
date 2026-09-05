"""THE OWNER'S SWITCH, AND THE ADMIN PATH THAT NEVER NEEDED ONE.

The founder: "give the staff perms allowing option to owner and every admin should have
that permission." Two decisions, and only one of them was code.

**(A) THE OWNER'S OPTION** is `organizations.staff_may_curate_knowledge` +
`kb/curation.py`. What has to be true of it is not "staff can curate" — it is the set of
things that must STILL be false afterwards, and that is most of this file: off unless an
owner said so, off for the neighbour when this owner says so, unreachable by the staff it
grants, unreachable by an operator wearing the owner's face, and invisible to an owner,
whose behaviour must be byte-for-byte what it was in both positions of the switch.

**(B) EVERY ADMIN APPROVING** was ALREADY TRUE and this file proves it rather than
rebuilding it. `POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/approve` has existed
since the KB slice: `agents:write`, `realm="admin"`, reached by an admin AS THEMSELVES,
executing `kb_service.approve_source` — the same function the client path's queue waits
on — and writing `kb.approved` through `write_audit`, which resolves `actor_type="admin"`
(the realm) and `actor_id` (the identity) from the principal. `ROLE_PERMISSIONS` grants
`agents:write` to `operator` and, by derivation, to `superadmin`, so "every Calevate
admin" is already the population that can call it.

**NO HOLE WAS CARVED IN D-22, AND `test_the_admin_approval_path_is_shut_to_an_
impersonating_principal` IS THE PROOF.** The brief that produced this work assumed an
admin was blocked from approving because `kb:write` is in `MUTATING_PERMISSIONS` and D-22
refuses a mutating permission to an impersonating principal. That premise is true and its
conclusion is not: D-22 blocks the IMPERSONATED route, and the approval route is not one —
the admin is themselves on it, and the tenant is named in the path rather than inferred
from a borrowed session. The correct response to "an operator cannot mutate while wearing
a client's face" is a surface where they are not wearing it, which `admin/routes.py`
already is. Adding a second one would have been a second door into `kb_sources` for a
capability that already had one.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so this
file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.copilot import actions as copilot_actions
from apps.api.copilot import write_tools
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import curation
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.impersonation_grant_test import view_as_headers

SUBMIT = "/v1/kb/sources"
SWITCH = "/v1/kb/staff-curation"
APPROVE = "/v1/admin/tenants/{tenant_id}/kb/{source_id}/approve"

BODY = "A consultation costs 500 rupees.\n\nWe are open 9am to 8pm, Monday to Saturday."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """A usable account: (tenant_id, agent_id, slug), agreements accepted.

    The four agreements are supplied rather than assumed away, in the shape
    `kb_workflow_test._tenant_with_published_agent` established — a fixture without them
    reports `agreements_not_accepted` in place of the answer under test.
    """
    created = await admin_service.create_organization(
        name="Curation Clinic",
        slug=f"cur-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(uuid.UUID(str(created["id"])))
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"])), str(created["slug"])


async def _member(tenant_id: uuid.UUID, role: str) -> tuple[uuid.UUID, str]:
    """A user with a membership in `tenant_id`. Returns (user_id, dev bearer token) —
    `authz_audit_test._make_member`'s idiom."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return user_id, f"dev:client:{user_id}"


async def _admin(role: str = "operator") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


def _h(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _submission() -> dict[str, str]:
    return {"agent_id": "", "name": "Consultation fee", "body": BODY, "kind": "text"}


async def _submit(http: AsyncClient, token: str, slug: str, agent_id: uuid.UUID):  # type: ignore[no-untyped-def]
    payload = _submission() | {"agent_id": str(agent_id)}
    return await http.post(SUBMIT, headers=_h(token, slug), json=payload)


# --- (A) the owner's switch --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_staff_member_in_an_untouched_tenant_is_refused_exactly_as_before() -> None:
    """DEFAULT OFF, and the migration is what makes this a statement about EVERY account.

    `staff_may_curate_knowledge` is `NOT NULL DEFAULT false`, so this account received the
    column without anybody choosing anything — which is the state every account on the
    platform is in the moment the migration lands. A staff member here gets the same 403
    they got yesterday from `requires("kb:write")`.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, staff = await _member(tenant_id, "staff")
    async with _client() as http:
        response = await _submit(http, staff, slug, agent_id)
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/forbidden"), response.text

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(text("SELECT staff_may_curate_knowledge FROM organizations"))
        ).scalar()
    assert stored is False, "a new account must not arrive with the switch already on"


@pytest.mark.asyncio
async def test_an_owner_turns_it_on_and_that_tenants_staff_may_then_curate() -> None:
    """The whole point, end to end through HTTP — and the source still lands UNAPPROVED.

    The second assertion is the one that keeps this a delegation rather than a bypass: a
    staff submission goes through `kb.service.submit_source`, the same one door
    `kb/proposals.py` documents, and comes out `pending_approval` like everybody else's.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    _, staff = await _member(tenant_id, "staff")

    async with _client() as http:
        flipped = await http.put(
            SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True}
        )
        assert flipped.status_code == 200, flipped.text
        assert flipped.json() == {"staff_may_curate_knowledge": True}

        submitted = await _submit(http, staff, slug, agent_id)
    assert submitted.status_code == 201, submitted.text

    source_id = submitted.json()["id"]
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE id = :s"), {"s": source_id}
            )
        ).scalar()
    assert status == "pending_approval", (
        "the preview-and-approve gate must apply to a staff submission identically — a "
        "staff member who could submit straight to live would be the bypass the switch "
        "was carefully written not to be"
    )


@pytest.mark.asyncio
async def test_one_owners_switch_does_not_reach_the_neighbours_staff() -> None:
    """HARD RULE 1, driven through the new column specifically.

    The switch is read with no `tenant_id` predicate — `organizations`' RLS policy matches
    on `id` and does the scoping — so the failure this guards against is not a forgotten
    WHERE clause but a reader that opened the wrong session. Two accounts, one switched
    on, and the other's staff must be refused.
    """
    on_tenant, on_agent, on_slug = await _tenant()
    off_tenant, off_agent, off_slug = await _tenant()
    _, on_owner = await _member(on_tenant, "owner")
    _, on_staff = await _member(on_tenant, "staff")
    _, off_staff = await _member(off_tenant, "staff")

    async with _client() as http:
        await http.put(
            SWITCH, headers=_h(on_owner, on_slug), json={"staff_may_curate_knowledge": True}
        )
        mine = await _submit(http, on_staff, on_slug, on_agent)
        theirs = await _submit(http, off_staff, off_slug, off_agent)

    assert mine.status_code == 201, mine.text
    assert theirs.status_code == 403, (
        "a neighbour's owner switching staff curation on must not widen this account — "
        f"got {theirs.status_code}: {theirs.text}"
    )


@pytest.mark.asyncio
async def test_staff_cannot_turn_the_switch_on_for_themselves() -> None:
    """A grant its own beneficiary can award is not a delegation, it is an escalation.

    `PUT /v1/kb/staff-curation` declares `org:manage`, which `ROLE_PERMISSIONS["staff"]`
    does not hold — and deliberately NOT `requires_kb_curation()`, which would have made
    the switch guard itself.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, staff = await _member(tenant_id, "staff")
    async with _client() as http:
        attempt = await http.put(
            SWITCH, headers=_h(staff, slug), json={"staff_may_curate_knowledge": True}
        )
        assert attempt.status_code == 403, attempt.text
        # And the refusal actually stored nothing: a 403 that had already written would be
        # the worst of both answers.
        after = await _submit(http, staff, slug, agent_id)
    assert after.status_code == 403, after.text

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(text("SELECT staff_may_curate_knowledge FROM organizations"))
        ).scalar()
    assert stored is False


@pytest.mark.asyncio
async def test_an_impersonating_admin_cannot_turn_the_switch_on() -> None:
    """D-22 on the switch itself: flipping a permission is a mutation.

    `org:manage` is in `MUTATING_PERMISSIONS`, so `requires()` refuses it to an
    impersonating principal — which means the repo-wide sweep
    `realm_boundary_test::test_no_route_declaring_a_mutating_permission_is_reachable_
    while_impersonating` already walks this route. It is driven HERE as well and only
    here, because the sweep proves the rule holds for the whole route table and this
    proves it holds for the one route where being wrong would let an operator hand a
    client's staff a capability the client never granted.
    """
    tenant_id, _agent_id, slug = await _tenant()
    token = await _admin()
    async with _client() as http:
        headers = await view_as_headers(http, token, slug)
        response = await http.put(
            SWITCH, headers=headers, json={"staff_may_curate_knowledge": True}
        )
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/forbidden"), response.text

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(text("SELECT staff_may_curate_knowledge FROM organizations"))
        ).scalar()
    assert stored is False, "a view-as session must not have moved the client's switch"


@pytest.mark.asyncio
@pytest.mark.parametrize("switch", [False, True])
async def test_owner_behaviour_is_unchanged_in_both_positions_of_the_switch(
    switch: bool,
) -> None:
    """THE ADDITIVITY CLAIM, driven rather than argued.

    `requires_kb_curation()` runs `requires("kb:write")`'s ladder first and unchanged and
    only then asks the extra question, so an owner can never notice the switch exists.
    Both positions, same 201, same resulting status.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    async with _client() as http:
        if switch:
            flipped = await http.put(
                SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True}
            )
            assert flipped.status_code == 200, flipped.text
        response = await _submit(http, owner, slug, agent_id)
    assert response.status_code == 201, response.text

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE id = :s"),
                {"s": response.json()["id"]},
            )
        ).scalar()
    assert status == "pending_approval"


@pytest.mark.asyncio
async def test_the_switch_is_reversible_and_every_flip_lands_in_the_ledger() -> None:
    """On, repeat, off — the capability closes again and all three requests are on record.

    THE ASSERTION IS ON THE LEDGER ROWS, NOT ON `summary`, and that is a fact about
    `audit_log` rather than a compromise: the table's columns are actor, tenant, action,
    object, ip and the chain hashes — `summary` rides the LOG STREAM keyed by entry id and
    is deliberately not a column (the discipline `core/auth.py::record_admin_tenant_read`
    states, so a route template or a value can never reach the hashed row). So what the
    ledger can be asked is who did it, to which account, and how many times — and the
    idempotent repeat is REQUIRED to be one of those rows, because a request somebody made
    is a request an investigator must see even when it moved nothing.
    """
    tenant_id, agent_id, slug = await _tenant()
    owner_id, owner = await _member(tenant_id, "owner")
    _, staff = await _member(tenant_id, "staff")

    async with _client() as http:
        await http.put(SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True})
        opened = await _submit(http, staff, slug, agent_id)
        assert opened.status_code == 201, opened.text

        repeat = await http.put(
            SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True}
        )
        assert repeat.status_code == 200, repeat.text

        await http.put(SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": False})
        after = await _submit(http, staff, slug, agent_id)
    assert after.status_code == 403, "turning it back off must close the capability again"

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, object_type FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'organization.staff_kb_curation_set' "
                    "ORDER BY at"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert len(rows) == 3, (
        "three PUTs are three entries — the idempotent repeat changed nothing and is "
        f"still a request somebody made; got {len(rows)}"
    )
    assert {r[0] for r in rows} == {"user"}, "a client owner's act is a client-realm row"
    assert {str(r[1]) for r in rows} == {str(owner_id)}, "and it names WHICH owner"
    assert {r[2] for r in rows} == {"organization"}


@pytest.mark.asyncio
async def test_the_grant_reaches_the_three_curation_routes_and_stops_there() -> None:
    """THE NARROWNESS, as behaviour rather than as a docstring promise.

    A staff member in a switched-on account may curate, and must STILL be refused the
    `org:manage` surfaces — billing, members, organization settings, and the switch itself
    — because the column grants ONE capability and `ROLE_PERMISSIONS["staff"]` is untouched
    by it.

    THE COPILOT IS DELIBERATELY NOT ASSERTED HERE ANY MORE. This test used to require a 403
    from `POST /v1/copilot/ask` on the ground that staff hold no `org:manage`; the founder
    then decided staff must be able to use the assistant, and that is now `copilot:use`
    (`core/rbac.py`). Copilot access and knowledge curation are TWO grants with two
    different shapes — one a flat role fact, one an owner's per-account switch — and
    `test_the_two_grants_are_independent` below drives exactly the combination that would
    catch anyone collapsing them back into one.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    _, staff = await _member(tenant_id, "staff")

    async with _client() as http:
        await http.put(SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True})
        assert (await _submit(http, staff, slug, agent_id)).status_code == 201

        escalation = await http.put(
            SWITCH, headers=_h(staff, slug), json={"staff_may_curate_knowledge": False}
        )
        settings = await http.put(
            "/v1/organization/llm-defaults",
            headers=_h(staff, slug),
            json={"default_llm_model": "gpt-4o-mini"},
        )
    assert escalation.status_code == 403, "staff must not be able to change the switch"
    assert settings.status_code == 403, (
        "curating knowledge must not have carried the account's model choice with it"
    )


@pytest.mark.asyncio
async def test_me_reports_the_effective_permission_so_the_screen_agrees_with_the_server() -> None:
    """**THE HALF-WIRING THIS EXISTS TO PREVENT**, and it is a defect the API alone cannot
    show.

    `apps/web/src/lib/api/hooks.ts::useWriteAccess` decides whether to ENABLE a mutating
    control by looking for its permission in `/v1/me`'s `permissions`. `kb:write` is no
    longer a role fact alone, so an endpoint reporting the raw role table would have left a
    switched-on account's staff staring at a greyed-out Add-Knowledge form with a tooltip
    explaining a refusal the server would not have made — the screen and the API
    disagreeing about one person, which is the exact failure class the effective set exists
    to close.

    Both directions are driven, because only reporting it when ON is half the property: an
    owner who switches it back OFF must see the control disable again.
    """
    tenant_id, _agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    _, staff = await _member(tenant_id, "staff")

    async with _client() as http:
        off = await http.get("/v1/me", headers=_h(staff, slug))
        assert off.status_code == 200, off.text
        assert "kb:write" not in off.json()["permissions"]

        await http.put(SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True})
        on = await http.get("/v1/me", headers=_h(staff, slug))
        assert "kb:write" in on.json()["permissions"], (
            "with the owner's switch on, the screen must enable the form the server accepts"
        )
        # ...and nothing else came with it. `/v1/me` is the screen's whole picture of what
        # this person may do, so a leak here enables controls all over the dashboard.
        assert "org:manage" not in on.json()["permissions"]
        assert set(on.json()["permissions"]) - set(off.json()["permissions"]) == {"kb:write"}

        await http.put(SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": False})
        again = await http.get("/v1/me", headers=_h(staff, slug))
    assert "kb:write" not in again.json()["permissions"], "turning it off must close the form"


@pytest.mark.asyncio
async def test_an_owners_own_me_is_unchanged_in_both_positions_of_the_switch() -> None:
    """The additivity claim, on the identity endpoint this time.

    An owner holds `kb:write` from the role table, so the effective-set branch must be
    invisible to them — same list, same bytes, switch on or off.
    """
    tenant_id, _agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    async with _client() as http:
        before = (await http.get("/v1/me", headers=_h(owner, slug))).json()["permissions"]
        await http.put(SWITCH, headers=_h(owner, slug), json={"staff_may_curate_knowledge": True})
        after = (await http.get("/v1/me", headers=_h(owner, slug))).json()["permissions"]
    assert before == after
    assert "kb:write" in before


@pytest.mark.asyncio
async def test_the_two_grants_are_independent() -> None:
    """**THE COMBINATION THAT PROVES THE TWO DECISIONS DID NOT COLLAPSE INTO ONE SWITCH.**

    Staff, in an account whose owner has NOT turned curation on:

    * may open the assistant and use its READ tools — `copilot:use` is a flat role fact and
      owes nothing to this account's settings;
    * is refused the moment a knowledge entry has to be COMPLETED — `actions.may_act`
      routes `kb:write` to `kb/curation.may_curate_knowledge`, which reads the owner's
      switch, so the assistant gives exactly the answer the Add-Knowledge form gives.

    If somebody ever wires copilot access to the owner's column, the first assertion fails.
    If somebody ever lets `copilot:use` stand in for `kb:write` at the tool gate, the second
    does. The two failures are the two ways this could go wrong.
    """
    tenant_id, agent_id, slug = await _tenant()
    user_id, staff = await _member(tenant_id, "staff")

    async with tenant_session(tenant_id) as session:
        switch = (
            await session.execute(text("SELECT staff_may_curate_knowledge FROM organizations"))
        ).scalar()
    assert switch is False, "this test is about the UNTOUCHED account"

    # The door: open, on nothing but the role table.
    from apps.api.core.rbac import role_has

    assert role_has("staff", "copilot:use"), "staff must be able to open the assistant"

    # The tool gate: shut, on the owner's switch.
    actor = write_tools.actor_for(
        Principal(realm="client", user_id=user_id, tenant_id=tenant_id, role="staff")
    )
    assert actor is not None
    async with tenant_session(tenant_id) as session:
        assert await copilot_actions.may_act(session, actor, "leads:write"), (
            "a plain role fact must be unaffected by the knowledge switch"
        )
        assert not await copilot_actions.may_act(session, actor, "kb:write"), (
            "with the owner's switch OFF, the assistant must refuse to complete a knowledge "
            "entry — the same answer POST /v1/kb/sources gives"
        )

    # And the form agrees, over HTTP, which is the answer a person actually sees.
    async with _client() as http:
        assert (await _submit(http, staff, slug, agent_id)).status_code == 403


@pytest.mark.asyncio
async def test_the_role_table_itself_is_untouched() -> None:
    """The mechanism must not have been a role edit wearing a column's clothes.

    If `kb:write` had been added to `ROLE_PERMISSIONS["staff"]` every assertion above about
    the OFF state would still pass in an account nobody switched on — because the tests
    drive routes, and a role edit moves routes only where a route exists. This asks the
    table directly, which is the only place that distinction is visible.
    """
    from apps.api.core.rbac import ROLE_PERMISSIONS, role_has

    assert not role_has("staff", "kb:write")
    assert not role_has("staff", "org:manage")
    # `copilot:use` IS in this set and was the only thing THAT change added — the founder's
    # separate decision that staff may use the assistant. Spelling the whole set out is what
    # makes each addition visible: a permission quietly added to `staff` fails here rather
    # than being discovered from behaviour, which is exactly what happened next.
    #
    # `wallet:read` (2 Sep 2026) is the second, and it is here for the same shape of reason
    # and by the same instrument — a founder decision, narrowly drawn. Everyone on a client's
    # team may SEE the calling-credit balance and its ledger "so an operator understands why
    # dialling stopped"; only the owner may BUY (`org:manage`, asserted absent above). It is
    # a new permission rather than a widening of `billing:read`, which would have carried the
    # spend breakdown, the caps and the monthly statement with it — SEC-COMP §5 scopes those
    # to the owner and the founder decided nothing about them.
    assert ROLE_PERMISSIONS["staff"] == frozenset(
        {
            "agents:read",
            "calls:read",
            "copilot:use",
            "leads:read",
            "leads:write",
            "org:read",
            "wallet:read",
        }
    )
    # And the wallet grant is a READ: it is not in `MUTATING_PERMISSIONS`, so a D-22 view-as
    # operator keeps it on a support call — while the purchase, which is, they do not.
    from apps.api.core.rbac import MUTATING_PERMISSIONS

    assert "wallet:read" not in MUTATING_PERMISSIONS
    assert "org:manage" in MUTATING_PERMISSIONS


@pytest.mark.asyncio
async def test_the_predicate_refuses_an_admin_realm_principal_the_column_could_widen() -> None:
    """Conjunct 1 of `may_curate_knowledge`, asked directly.

    It is unreachable through HTTP — an admin-realm principal with a client role is not a
    thing `current_any` builds — and it is asserted anyway, because the clause is what
    stops a CLIENT-WRITABLE column from ever widening an ADMIN principal. A defence that
    is only true by the accident of what the resolver happens to construct is one refactor
    away from being false.
    """
    tenant_id, _agent_id, _slug = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE organizations SET staff_may_curate_knowledge = true"))
        for realm, impersonating in (("admin", False), ("admin", True), ("client", True)):
            allowed = await curation.may_curate_knowledge(
                session, realm=realm, role="staff", impersonating=impersonating
            )
            assert not allowed, (
                f"realm={realm} impersonating={impersonating} must not be lifted by a "
                "client-writable column"
            )


# --- (B) every admin, as themselves, with D-22 intact -------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("admin_role", ["operator", "superadmin"])
async def test_every_admin_tier_approves_as_themselves_and_the_row_names_realm_and_identity(
    admin_role: str,
) -> None:
    """DECISION (B), AND IT NEEDED NO NEW CODE.

    Both admin tiers hold `agents:write` — `operator` by an explicit line in
    `ROLE_PERMISSIONS` and `superadmin` by derivation from `KNOWN_PERMISSIONS` — so "every
    Calevate admin" is already the population this route admits. The audit row is checked
    for both halves an investigator needs: `actor_type` is the REALM and `actor_id` is the
    IDENTITY, resolved by `write_audit` from the principal rather than passed by the
    handler.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    token = await _admin(admin_role)

    async with _client() as http:
        submitted = await _submit(http, owner, slug, agent_id)
        assert submitted.status_code == 201, submitted.text
        source_id = submitted.json()["id"]

        approved = await http.post(
            APPROVE.format(tenant_id=tenant_id, source_id=source_id),
            headers={"Authorization": f"Bearer {token}"},
        )
    assert approved.status_code == 200, approved.text
    assert approved.json() == {"status": "approved"}

    admin_id = token.rsplit(":", 1)[-1]
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'kb.approved' AND object_id = :o"
                ),
                {"t": tenant_id, "o": source_id},
            )
        ).first()
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE id = :s"), {"s": source_id}
            )
        ).scalar()
    assert row is not None, "an operator putting words into a client's agent must be findable"
    assert row[0] == "admin", f"the row must name the actor's REALM; got {row[0]!r}"
    assert str(row[1]) == admin_id, "the row must name WHICH admin"
    assert status == "approved", "and it must have gone through the same gated service call"


@pytest.mark.asyncio
async def test_the_admin_approval_path_is_shut_to_an_impersonating_principal() -> None:
    """**THE TEST THAT PROVES NO HOLE WAS CARVED IN D-22.**

    The same admin, the same route, the same source — but reached while wearing the
    client's face. `agents:write` is in `MUTATING_PERMISSIONS`, so `requires()` refuses,
    and the source is still sitting in the review queue afterwards. That is the property
    the whole of decision (B) rests on: an operator approves knowledge as an operator, on
    a surface where the audit row can only ever say `admin`, and never as the client.
    """
    tenant_id, agent_id, slug = await _tenant()
    _, owner = await _member(tenant_id, "owner")
    token = await _admin()

    async with _client() as http:
        submitted = await _submit(http, owner, slug, agent_id)
        source_id = submitted.json()["id"]

        headers = await view_as_headers(http, token, slug)
        refused = await http.post(
            APPROVE.format(tenant_id=tenant_id, source_id=source_id), headers=headers
        )
    assert refused.status_code == 403, refused.text
    assert refused.json()["type"].endswith("/forbidden"), refused.text

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE id = :s"), {"s": source_id}
            )
        ).scalar()
    assert status == "pending_approval", (
        "D-22 must have stopped the write, not merely the response — a refusal that had "
        "already approved would be the hole this test exists to rule out"
    )
