"""An impersonated write happens, and the ledger says WHO — D-587 (supersedes D-22).

D-22 made "view as client" read-only and gave one reason: no acting-as, so no dual
attribution, so every `audit_log` row unambiguously names who decided. D-587 reverses the
read-only half — an operator on a support call has to be able to fix the account they are
looking at — which means the ambiguity D-22 designed around is now reachable and is closed
by RECORDING instead of by refusing. **The recording is the claim this file exists to
prove**, and each test below is one half of it:

  1. an impersonated write LANDS, and its audit row names the OPERATOR (`actor_id` is the
     `admin_users.id`, `actor_type` is `admin`), the TENANT it landed in, and the GRANT it
     came through (`via_grant_id`) — which joins it to the `admin.impersonation_started`
     row naming who entered;
  2. that grant id is the SAME one the session started with, so start and act join
     exactly rather than by timestamp proximity;
  3. the same write performed by the CLIENT'S OWN OWNER carries no `via_grant_id`, so the
     column distinguishes the two rather than being decoration;
  4. RLS still scopes the write (hard rule 1): a grant for tenant A cannot touch tenant B,
     and the refusal is the grant binding, not a WHERE clause somebody remembered;
  5. the hash chain still verifies with the new field in the payload (the column is hashed
     only when present, so every pre-D-587 row keeps its own shape);
  6. hard rule 5's invariants survive: the D-163 toggles are switchable by an operator and
     audited as theirs, and nothing about the always-answer-truthfully promise moved.

Concurrency: this repo's tests share one Postgres. Everything is scoped to run-unique
tenants and nothing asserts a global row count.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.audit import verify_chain
from apps.api.compliance.disclosure import TRUTHFUL_ANSWER_PROMISE
from apps.api.core.rbac import (
    MUTATING_PERMISSIONS,
    VIEW_AS_MUTATIONS,
    VIEW_AS_WITHHELD_ACTS,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.impersonation_grant_test import _make_admin, view_as_headers

STARTED_ACTION = "admin.impersonation_started"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_org(prefix: str = "vw") -> dict[str, Any]:
    return await admin_service.create_organization(
        name="View-As Clinic",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _rows(action: str, tenant_id: uuid.UUID) -> list[Any]:
    """Audit rows for one action in one tenant, oldest first.

    `audit_log` is not tenant-RLS'd (the chain is global and the admin realm reads it
    across tenants), so this reads untenanted and filters itself — the same idiom the
    read-path suite uses.
    """
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, tenant_id, via_grant_id "
                    "FROM audit_log WHERE action = :a AND tenant_id = :t ORDER BY at ASC"
                ),
                {"a": action, "t": tenant_id},
            )
        ).all()


# ----------------------------------------------------------------- 1, 2: attribution


async def test_an_impersonated_write_lands_and_names_the_operator_and_the_grant() -> None:
    """THE CLAIM OF D-587, driven end to end on a compliance toggle (hard rule 5).

    `PATCH /v1/agents/{id}/disclosure` is the D-163 switch — what the agent VOLUNTEERS at
    the start of a call — and it is deliberately the surface chosen here rather than a
    lead's status: it is the one where "who did this" is legally load-bearing, so if
    attribution holds anywhere it must hold here.

    Four assertions, and all four are the row rather than the response: the write
    happened, the actor is the OPERATOR (not the tenant, not the client's owner), the
    tenant is the one entered, and the grant is on the row. Dropping any one of them is
    the laundering D-22 refused to risk.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        response = await http.patch(
            f"/v1/agents/{org['agent_id']}/disclosure",
            headers=headers,
            json={"ai_disclosure_enabled": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["ai_disclosure_enabled"] is False

    rows = await _rows("agent.ai_disclosure_disabled", tenant_id)
    assert len(rows) == 1, "one flip that moved is one row"
    actor_type, actor_id, row_tenant, via_grant = rows[0]
    assert actor_type == "admin", "an operator's act is an admin act, whatever face it wore"
    assert uuid.UUID(str(actor_id)) == admin_id, (
        "the row must name the OPERATOR. A row naming the client's owner — or naming "
        "nobody — is the attribution failure D-22 existed to prevent"
    )
    assert uuid.UUID(str(row_tenant)) == tenant_id
    assert via_grant is not None, (
        "without the grant id the row says 'an admin changed this client's setting' and "
        "cannot say the admin was inside the client's own session"
    )


async def test_the_write_names_the_same_grant_the_session_started_with() -> None:
    """The join. The `via_grant_id` on the act is the `jti` of the grant the console holds,
    which is the id `admin.impersonation_started` was written under — so an investigator
    goes from "this setting changed" to "this operator entered this tenant at this time
    from this address" without matching on timestamps.

    Decoded from the grant itself rather than read from a second table on purpose: there is
    no `impersonation_grants` table (`core/impersonation.py` argues why), and inventing one
    for this assertion would be testing a fixture instead of the design.
    """
    import jwt
    from apps.api.core.impersonation import GRANT_ALGORITHM, GRANT_AUDIENCE, _signing_key

    _admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        response = await http.patch(
            f"/v1/agents/{org['agent_id']}/disclosure",
            headers=headers,
            json={"recording_notice_enabled": False},
        )
        claims = jwt.decode(
            headers["X-Impersonation-Grant"],
            _signing_key(),
            algorithms=[GRANT_ALGORITHM],
            audience=GRANT_AUDIENCE,
        )

    assert response.status_code == 200, response.text
    rows = await _rows("agent.recording_notice_disabled", tenant_id)
    assert [str(row[3]) for row in rows] == [str(claims["jti"])]

    started = await _rows(STARTED_ACTION, tenant_id)
    assert started, "entering the tenant must still write its own row"
    assert all(row[3] is None for row in started), (
        "the START row is written by the mint route, which carries no grant of its own — "
        "if it ever gains one, this join has two meanings and the ledger has an ambiguity"
    )


async def test_the_clients_own_write_carries_no_grant() -> None:
    """The control. `via_grant_id` has to DISTINGUISH, so the same act by the account's
    own owner must leave it NULL — otherwise the column is decoration and an investigator
    reading it learns nothing.

    NULL here is not "unknown": it is the complete statement "this did not come through a
    view-as session", which is why the migration adds no default and backfills nothing.
    """
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    owner_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Owner', now(), now())"
            ),
            {"id": owner_id, "email": f"{owner_id}@example.test"},
        )
    # The membership goes in under the TENANT's own session: `memberships` is FORCE-RLS'd
    # and its WITH CHECK is `app.tenant_id`, so the untenanted session above can create the
    # global `users` row and nothing else (hard rule 1, and the idiom every other suite
    # here uses).
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": owner_id},
        )

    async with _client() as http:
        response = await http.patch(
            f"/v1/agents/{org['agent_id']}/disclosure",
            headers={
                "Authorization": f"Bearer dev:client:{owner_id}",
                "X-Org-Slug": str(org["slug"]),
            },
            json={"ai_disclosure_enabled": False},
        )

    assert response.status_code == 200, response.text
    rows = await _rows("agent.ai_disclosure_disabled", tenant_id)
    assert len(rows) == 1
    assert uuid.UUID(str(rows[0][1])) == owner_id
    assert rows[0][3] is None


# ------------------------------------------------------------------- 4: tenancy (RLS)


async def test_a_view_as_write_cannot_reach_another_tenant() -> None:
    """HARD RULE 1 UNDER THE NEW POWER. A write through impersonation is scoped to the
    tenant the grant names, and nothing about D-587 opens a cross-tenant path.

    THE ATTACK, STATED: an operator legitimately inside tenant A presents A's grant and
    addresses tenant B's slug. Two independent things refuse it — `verify_grant` matches
    `sub` against the tenant the header resolved (`impersonation_grant_tenant_mismatch`),
    and the request's session would carry `app.tenant_id = B` regardless, so B's agent is
    not visible to A's grant either. The FIRST is what answers here, and the second is why
    a bug in the first is not a cross-tenant write: the session GUC is set from the
    resolved tenant, never from the grant.

    The assertion is on the ROW COUNT in B as well as the status, because a 403 that had
    already written is the failure mode a status-only test cannot see.
    """
    _admin_id, token = await _make_admin()
    victim = await _make_org("victim")
    other = await _make_org("other")

    async with _client() as http:
        grant_for_other = (await view_as_headers(http, token, str(other["slug"])))[
            "X-Impersonation-Grant"
        ]
        response = await http.patch(
            f"/v1/agents/{victim['agent_id']}/disclosure",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Impersonate-Org": str(victim["slug"]),
                "X-Impersonation-Grant": grant_for_other,
            },
            json={"ai_disclosure_enabled": False},
        )

    assert response.status_code == 403, response.text
    # RFC-9457 problem+json: the machine code is `type`'s last segment, which is how every
    # other suite here reads it — `code` is the field name in `ProblemError`, not on the wire.
    assert "tenant_mismatch" in response.text, response.text
    assert await _rows("agent.ai_disclosure_disabled", uuid.UUID(str(victim["id"]))) == []


async def test_the_write_lands_in_the_entered_tenant_and_nowhere_else() -> None:
    """The other direction of the same rule: a legitimate view-as write must land in
    exactly one tenant. Two accounts, one operator, one grant — and the neighbouring
    account's agent is untouched.

    This is the test that would fail if a future "operator" session ever widened
    `app.tenant_id` or reached for the admin DB role to make a write work (hard rule 1
    forbids both, and `core/deps.db` is the one session a client-realm route gets).
    """
    _admin_id, token = await _make_admin()
    entered = await _make_org("in")
    neighbour = await _make_org("nb")

    async with _client() as http:
        headers = await view_as_headers(http, token, str(entered["slug"]))
        response = await http.patch(
            f"/v1/agents/{entered['agent_id']}/disclosure",
            headers=headers,
            json={"ai_disclosure_enabled": False},
        )
        crossed = await http.patch(
            f"/v1/agents/{neighbour['agent_id']}/disclosure",
            headers=headers,
            json={"ai_disclosure_enabled": False},
        )

    assert response.status_code == 200, response.text
    # RLS answers "no such agent" for one that is not this session's tenant, which is the
    # correct answer and the one a leak would turn into a 200.
    assert crossed.status_code == 404, crossed.text
    assert await _rows("agent.ai_disclosure_disabled", uuid.UUID(str(neighbour["id"]))) == []


# ------------------------------------------------------- 5: the chain still verifies


async def test_the_hash_chain_verifies_with_an_impersonated_write_in_it() -> None:
    """`via_grant_id` is INSIDE the hash when it is set, so an insider who edited it would
    break the row. That is only worth anything if the chain still verifies with such a row
    in it — including all the rows around it, which were signed over a payload shape that
    has no such field at all.

    The walk is the whole log, which is what `verify_chain`'s default does and what makes
    this a regression test for the shape change rather than for one row.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        response = await http.patch(
            f"/v1/agents/{org['agent_id']}/disclosure",
            headers=headers,
            json={"ai_disclosure_enabled": False},
        )
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        verdict = await verify_chain(session)
    assert [b for b in verdict.breaks if b.kind == "content"] == [], (
        "a content break after this change means the payload shape moved for rows that "
        "carry no grant — the conditional key in `write_audit` is what prevents it"
    )


# --------------------------------------------------- 6: the compliance invariants


async def test_the_truthful_answer_promise_is_not_touchable_from_a_view_as_session() -> None:
    """HARD RULE 5, ASSERTED AS A PROPERTY OF THE SURFACE RATHER THAN OF A CALLER.

    The D-163 toggles decide what an agent VOLUNTEERS and are legitimately switchable —
    the test above drives an operator switching one. What may never be switchable is the
    answer an agent gives when ASKED, and the reason it cannot be is that no field carries
    it: it is composed server-side by `compose_engine_prompt` and returned to every caller
    as a constant. So this asserts the response still states it after an operator flipped
    both switches off, which is the shape a regression would take — a payload that let the
    promise travel would show up here as a field, not as a failure elsewhere.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        response = await http.patch(
            f"/v1/agents/{org['agent_id']}/disclosure",
            headers=headers,
            json={"ai_disclosure_enabled": False, "recording_notice_enabled": False},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_disclosure_enabled"] is False
    assert body["recording_notice_enabled"] is False
    assert body["truthful_answer_rule"] == TRUTHFUL_ANSWER_PROMISE, (
        "switching off what is VOLUNTEERED must never move what is ANSWERED — and the "
        "surface says so in the same response, so an operator reads it as they flip"
    )


async def test_every_mutating_permission_has_a_view_as_ruling() -> None:
    """THE REGISTRY IS COMPLETE, WHICH IS WHAT MAKES IT A REGISTRY.

    `withheld_from_view_as` fails closed on an unclassified permission, so a missing entry
    costs a support person a refusal rather than costing a client an unreviewed change —
    but a fail-closed default is a backstop, not a decision. This is the decision: a
    permission added to `MUTATING_PERMISSIONS` tomorrow turns this red until somebody
    writes down whether a view-as session may exercise it and why not, beside every other
    such ruling. That is the difference between a registry and a memory.
    """
    assert set(VIEW_AS_MUTATIONS) == set(MUTATING_PERMISSIONS), (
        "every mutating permission needs a view-as ruling: "
        f"unruled={sorted(MUTATING_PERMISSIONS - set(VIEW_AS_MUTATIONS))}, "
        f"stale={sorted(set(VIEW_AS_MUTATIONS) - MUTATING_PERMISSIONS)}"
    )
    for permission, ground in VIEW_AS_MUTATIONS.items():
        assert ground is None or len(ground) > 40, (
            f"{permission} is withheld with a ground too short to act on — this string is "
            "what an operator reads instead of the control they came for"
        )


# ------------------------------------------------- the two defences against OURSELVES


async def test_a_write_that_cannot_be_attributed_is_refused() -> None:
    """THE FAIL-CLOSED ARM, DRIVEN — and it is a defence against US, not against a caller.

    Nothing a caller can send produces an impersonating principal without a grant:
    `_load_admin_principal` sets both in one branch, from a grant `verify_grant` has
    already matched to this operator and this tenant. What this guards is a future code
    path of OURS that manufactures such a principal — a test helper promoted to a fixture,
    a cached principal rebuilt from fewer fields — because the row it would write says the
    TENANT changed its own settings, which is precisely the laundering D-587 may not
    produce. The refusal is cheap; discovering it in a ledger a year later is not.

    Driven by handing `requires()` the principal directly, since authentication cannot
    make one. That is the point: the branch exists for the case authentication does not
    cover.
    """
    from apps.api.core import auth as auth_module
    from apps.api.core.context import Principal
    from apps.api.core.errors import ProblemError

    dependency = auth_module.requires("leads:write")
    unattributable = Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role="operator",
        impersonating=True,
    )

    async def _principal(_request: object) -> Principal:
        return unattributable

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auth_module, "current_any", _principal)
        with pytest.raises(ProblemError) as refused:
            await dependency(cast("Request", object()))

    assert refused.value.status == 403
    assert "attributed" in refused.value.detail


def test_an_unclassified_mutating_permission_is_withheld() -> None:
    """`withheld_from_view_as` FAILS CLOSED, driven rather than asserted from the source.

    `tests/impersonation_writes_test.test_every_mutating_permission_has_a_view_as_ruling`
    refuses a build where a mutating permission has no entry, so this arm is unreachable
    in a green tree — which is exactly why it needs a test: an arm nobody exercises is an
    arm nobody knows the shape of, and this one decides whether a permission somebody
    forgot to classify costs a support person a refusal or costs a client an unreviewed
    change.
    """
    from types import MappingProxyType

    from apps.api.core import rbac

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rbac, "VIEW_AS_MUTATIONS", MappingProxyType({}))
        ground = rbac.withheld_from_view_as("leads:write")
    assert ground is not None
    assert "has not been cleared" in ground
    # And the same call outside the patch is the ordinary answer, so this cannot pass by
    # breaking the function.
    assert rbac.withheld_from_view_as("leads:write") is None


def test_every_named_withheld_act_is_actually_guarded_somewhere() -> None:
    """A registry entry nobody spends is a refusal nobody makes.

    `VIEW_AS_WITHHELD_ACTS` reads as the enumeration of what a view-as session may not do,
    and the sentences in it are quoted in docstrings and in this file — so an entry whose
    `assert_view_as_may` call was deleted (or never written) would keep advertising a
    control that is not there. That is the half-wired shape CLAUDE.md names, one level
    below the routers `scripts/check_wiring` walks: nothing errors, and the only symptom is
    an act somebody believes is refused.

    A SOURCE SCAN rather than a driven request, because the routes carrying these guards
    are five different modules with five different fixtures, and the property is about the
    registry rather than about any one of them. The sweep in `realm_boundary_test` drives
    the ones that sit on a mutating-permission route.
    """
    import pathlib

    source = "\n".join(
        path.read_text()
        for path in pathlib.Path("apps/api").rglob("*.py")
        if "__pycache__" not in str(path)
    )
    unspent = [
        act
        for act in VIEW_AS_WITHHELD_ACTS
        if f'assert_view_as_may(principal, "{act}")' not in source
    ]
    assert not unspent, (
        f"these view-as refusals are declared and never enforced: {unspent} — either the "
        "guard was lost or the entry should go"
    )


# ------------------------------------------- the acts that stay with the client, driven


async def test_a_view_as_session_cannot_own_a_saved_view() -> None:
    """A saved view belongs to ONE signed-in person, and a view-as session is not one.

    `lead_saved_views.user_id` is an FK to `users`; an operator's id is an `admin_users`
    row. While view-as was read-only that difference could never reach a write — now it
    can, and the answer has to be a sentence rather than a foreign-key violation on a
    support call. `Principal.client_user_id` is what makes it structural (it answers
    `None` for an operator); this drives the sentence.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        created = await http.post(
            "/v1/leads/views",
            headers=headers,
            json={"name": "Mine", "filters": {}},
        )

    assert created.status_code == 403, created.text
    assert "signed-in person" in created.json()["detail"], created.text


async def test_a_view_as_session_cannot_attest_on_the_accounts_behalf() -> None:
    """Switching caller memory ON carries an ATTESTATION, and an operator cannot make it.

    The flip itself is `org:manage` — writable in a view-as session — but `accept: true`
    records that a named person of that account read what these calls collect and agreed
    to it. `organizations.caller_memory_attested_by` is a `users.id`, and an attestation
    stored against nobody is worse than no attestation, so the request is refused before
    anything is written. The client makes it from their own console.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        attested = await http.patch(
            f"/v1/agents/{org['agent_id']}/caller-memory",
            headers=headers,
            json={"enabled": True, "accept": True},
        )

    assert attested.status_code == 403, attested.text
    assert "statement the account makes" in attested.json()["detail"], attested.text
