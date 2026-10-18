"""A LIVE agent's call cap, edited by the people whose phone line it is (D-586).

The founder wants an agent's per-agent settings editable while the agent is LIVE, taking
effect from the NEXT CALL, by the owner, by their staff, AND by an admin impersonating them.
The opening-notice toggles and caller memory are covered by `tests/agent_disclosure_test.py`
and `tests/caller_memory_test.py`; this file is about the maximum call duration, and about
the four properties that make "editable while live" a promise rather than a screen:

1. **THE WRITE REACHES THE ENGINE**, and the assertion is against the ENGINE's own store,
   never our mirror of it — the mirror is written by the same function that made the call,
   so a test that only read the column would pass against a publish that never happened.
2. **A REFUSED PUSH LEAVES THE ROW AND THE ENGINE AGREEING.** The push is inside the
   transaction, so a vendor 400 rolls the column back with it.
3. **THE PEOPLE.** Owner, staff, and — by declaration, see the census below — an admin
   viewing as them. `agents:write` is held by both client roles, and the census proves
   which client-realm routes that grant opens.
4. **HARD RULE 5 SURVIVES THE WRITE.** The republish re-sends the whole `AgentConfig`, so
   the truthful-answer directive is asserted on the engine AFTER the write.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing
from apps.api.agents.models import CALL_CAP_DEFAULT_S
from apps.api.agents.publishing_routes import router as publishing_router
from apps.api.agents.routes import router as agents_router
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import (
    MUTATING_PERMISSIONS,
    assert_policy_registry_complete,
    iter_api_routes,
    role_has,
    route_enforcement,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.voice_fixture import TEST_VOICE_ID

VOICE_ID = TEST_VOICE_ID
#: A second valid cap, distinct from `CALL_CAP_DEFAULT_S`, so "the write moved it" and
#: "the column was already that" are distinguishable.
SHORTER_CAP_S = 300


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    # ORDER IS THE CONTRACT, exactly as in `main._mount_routers`: the literal
    # `/v1/agents/{id}/call-cap` must be declared before
    # `/v1/agents/{agent_id}`, or FastAPI matches the parameterised route first.
    application.include_router(publishing_router)
    application.include_router(agents_router)
    assert_policy_registry_complete(application)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _member(tenant_id: UUID, role: str) -> str:
    """One more member of an existing account, and their local dev bearer."""
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
    return f"dev:client:{user_id}"


async def _live_agent() -> tuple[UUID, UUID, str, str, FakeEngine]:
    """A LIVE, published agent with a script, plus its owner's token and the engine.

    Published through `publish_agent` rather than by writing `engine_agent_ref` by hand,
    because half of what this suite asserts is what the ENGINE holds — a hand-written ref
    names an object the fake has never heard of, and every read-back after it would be
    measuring nothing.
    """
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Live Edit Clinic",
        slug=f"led-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8): every publish gate refuses
    # an organisation that has not, so a fixture without this reports
    # `agreements_not_accepted` in place of the answer under test.
    tenant_id = UUID(str(created["id"]))
    agent_id = UUID(str(created["agent_id"]))
    slug = str(created["slug"])
    await accept_agreements(tenant_id)

    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Live Edit Clinic.\n",
            notes=None,
            created_by=None,
        )
        await session.execute(
            # THE PROVIDER IS WRITTEN TO MATCH `TEST_VOICE_ID`'s OWN, not typed
            # independently: `tests/voice_fixture` seeds a CARTESIA voice, and this row said
            # `sarvam` — which was merely redundant while Sarvam was a provider and became a
            # row no catalogue could resolve when D-629 withdrew it.
            text("UPDATE agents SET tts_voice = :v, tts_provider = 'cartesia' WHERE id = :a"),
            {"v": VOICE_ID, "a": agent_id},
        )
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    from apps.api.agents.service import publish_agent

    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    token = await _member(tenant_id, "owner")
    return tenant_id, agent_id, slug, token, engine


async def _engine_config(engine: FakeEngine, tenant_id: UUID, agent_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    return engine._agents[str(ref)]


async def _row(tenant_id: UUID, agent_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT tts_voice, tts_provider, live_tts_voice, max_call_duration_s, "
                    "status, ai_disclosure_enabled, recording_notice_enabled, "
                    "ai_disclosure_line FROM agents WHERE id = :a"
                ),
                {"a": agent_id},
            )
        ).one()


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


# --- 1. the write reaches the engine ---------------------------------------------------


async def test_an_owner_sets_the_cap_on_their_own_live_agent_and_it_reaches_the_engine() -> None:
    """ "Longest one call may run", from the client's own screen.

    The cap always re-published correctly; what it did not have was a client door. The
    assertion that matters is the LAST one: the engine is holding the new number, so the
    guard is enforced where a runaway call actually runs rather than only in the column
    the screen reads back.
    """
    tenant_id, agent_id, slug, token, engine = await _live_agent()
    before = await _engine_config(engine, tenant_id, agent_id)
    assert before.max_call_duration_s == CALL_CAP_DEFAULT_S

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/call-cap",
            json={"max_call_duration_s": SHORTER_CAP_S},
            headers=_headers(token, slug),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_call_duration_s"] == SHORTER_CAP_S
    assert body["effective_call_cap_s"] == SHORTER_CAP_S
    assert body["is_platform_default"] is False
    assert body["engine_synced"] is True

    assert (await _row(tenant_id, agent_id))[3] == SHORTER_CAP_S
    after = await _engine_config(engine, tenant_id, agent_id)
    assert after.max_call_duration_s == SHORTER_CAP_S, (
        "a cap that only lands in our table protects nobody"
    )


# --- 2. the failure path ---------------------------------------------------------------


async def test_an_engine_refusal_rolls_the_cap_back_so_the_row_never_over_promises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six live refusals in one day is the observed rate this is written against.

    The row must not be left saying something the engine does not have — so the column
    write and the engine push share one transaction, and the vendor's refusal takes both
    down. The client sees the dependency problem rather than a success, which is the whole
    of the error ladder's answer here (BACKEND-PATTERNS §3): nothing the caller typed is
    wrong, so it is not `validation`, and swallowing it to make the path look green is the
    one thing forbidden.
    """
    tenant_id, agent_id, slug, token, engine = await _live_agent()
    before = await _row(tenant_id, agent_id)

    async def _refuse(*_args: object, **_kwargs: object) -> None:
        raise ProblemError(
            kind="dependency",
            code="engine_rejected",
            title="The voice platform refused the change",
            detail="The voice platform would not take this agent.",
        )

    monkeypatch.setattr(engine, "update_agent", _refuse)
    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/call-cap",
            json={"max_call_duration_s": SHORTER_CAP_S},
            headers=_headers(token, slug),
        )

    assert response.status_code >= 400, response.text
    problem = response.json()
    assert problem["kind"] == "dependency", problem
    assert await _row(tenant_id, agent_id) == before, "the column must roll back with the push"
    # And the engine is still holding the OLD cap, which is the other half of "they agree".
    assert (await _engine_config(engine, tenant_id, agent_id)).max_call_duration_s == (
        CALL_CAP_DEFAULT_S
    )
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'agent.call_cap_set' "
                    "AND tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    assert audited == 0, "nothing happened, so the ledger must not say something did"


# --- 4. who may do it ------------------------------------------------------------------


async def test_a_staff_member_may_edit_their_accounts_agent_settings() -> None:
    """The founder's decision, driven rather than read off the role table.

    Staff run the phone line day to day. The person who notices a call stuck at nine
    minutes, or that the agent sounds wrong, is as likely to be staff as the owner, and
    making them fetch the owner is the support ticket this decision removes.
    """
    tenant_id, agent_id, slug, _owner, engine = await _live_agent()
    staff = await _member(tenant_id, "staff")

    async with _client(_app()) as http:
        cap = await http.patch(
            f"/v1/agents/{agent_id}/call-cap",
            json={"max_call_duration_s": SHORTER_CAP_S},
            headers=_headers(staff, slug),
        )

    assert cap.status_code == 200, cap.text
    assert (await _engine_config(engine, tenant_id, agent_id)).max_call_duration_s == SHORTER_CAP_S


async def test_the_staff_grant_is_agents_write_and_not_a_widening_of_org_manage() -> None:
    """The narrowest grant that answers the ask — the refusal `copilot:use` and
    `wallet:read` are both in the role table for.

    `org:manage` would have been the neighbouring choice and carries billing, members and
    every organization setting with it: the largest possible widening for the narrowest
    possible ask. It stays absent from `staff`, and this is what says so out loud.
    """
    assert role_has("staff", "agents:write")
    assert role_has("owner", "agents:write")
    assert not role_has("staff", "org:manage"), "staff still may not buy credit or edit members"
    assert not role_has("staff", "kb:write")
    assert not role_has("staff", "calls:read_raw")
    # It is a MUTATING permission, which is what makes every guard in `requires()` apply
    # to these routes unchanged — including the archived-agent refusal and whatever
    # D-22 currently says about a view-as session.
    assert "agents:write" in MUTATING_PERMISSIONS


async def test_every_client_route_holding_agents_write_is_declared() -> None:
    """THE CENSUS, and the reason the grant is safe to make at all.

    `ROLE_PERMISSIONS` is one flat dict over both realms, so a client role holding
    `agents:write` holds the same string a dozen `/v1/admin/**` routes declare. What keeps
    a tenant out of the console is `requires(..., realm="admin")`, never the permission —
    `core/rbac.py`'s own docstring says so and names `agents:write` as the example. That is
    a property of the route table, so it is asserted over the route table rather than
    trusted: every route declaring `agents:write` is either one of the client doors
    listed here, or admin-realm.

    A future client-realm route declaring `agents:write` therefore has to be a deliberate
    act — adding it here — rather than an authority somebody inherits without noticing.
    """
    from apps.api.main import app

    client_doors = {
        "/v1/agents/{agent_id}/call-cap",
        # D-719's improvement loop: a client saves, runs and deletes tests of its own agent
        # and chats with it to try a change. They act on the agent the way its voice does,
        # so they take the same authority, and none of them changes what callers hear.
        "/v1/agents/{agent_id}/test-cases",
        "/v1/agents/{agent_id}/test-cases/{case_id}",
        "/v1/agents/{agent_id}/test-cases/run",
        "/v1/calls/{call_id}/test-case",
        # D-822: discarding the test Pip prepared from a call, the save above's undo.
        "/v1/calls/{call_id}/test-case-draft/pending",
        "/v1/agents/{agent_id}/try-chat",
    }
    open_to_clients: set[str] = set()
    for route in iter_api_routes(app):
        permissions, _identified = route_enforcement(route)
        if "agents:write" not in permissions:
            continue
        realms = {
            getattr(dependency.call, "calevate_realm", None)
            for dependency in route.dependant.dependencies
        }
        if "admin" not in realms:
            open_to_clients.add(route.path)
    assert open_to_clients == client_doors, (
        f"a client-realm route gained `agents:write` without a decision: {open_to_clients}"
    )


async def test_the_call_cap_door_admits_an_impersonating_admin_by_declaration() -> None:
    """ "AND by an admin impersonating them" — asserted as the DECLARATION, deliberately.

    `requires()` with the default `realm="any"` resolves through `current_any`, which
    admits an ADMIN principal only when the impersonation header is present
    (`core/auth.py`). So `("agents:write", "any")` on this route IS the statement
    that a view-as operator reaches them, and `realm="client"` would be the one change
    that silently takes it away.

    WHETHER a view-as session may then MUTATE is D-22's answer, given once in `requires()`
    for every route in the app, and it is not this slice's to make or to pin — a test here
    driving an impersonated write would be asserting somebody else's decision from the
    wrong file, and would go red on the day they change it for reasons that have nothing
    to do with the cap.
    """
    from apps.api.main import app

    declared = {
        route.path: {
            (
                getattr(dependency.call, "calevate_permission", None),
                getattr(dependency.call, "calevate_realm", None),
            )
            for dependency in route.dependant.dependencies
        }
        for route in iter_api_routes(app)
        if route.path == "/v1/agents/{agent_id}/call-cap"
    }
    assert len(declared) == 1, declared
    for path, enforced in declared.items():
        assert ("agents:write", "any") in enforced, (
            f"{path} must stay realm-agnostic or a view-as operator loses it"
        )


# --- 5. hard rule 5 --------------------------------------------------------------------


async def test_a_cap_change_leaves_the_truthful_answer_rule_on_the_engine() -> None:
    """The same property on the other setting, because the two take different code paths
    into `publish_agent` and a compliance guarantee asserted on one of two paths is
    asserted on neither."""
    tenant_id, agent_id, slug, token, engine = await _live_agent()

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/call-cap",
            json={"max_call_duration_s": SHORTER_CAP_S},
            headers=_headers(token, slug),
        )
    assert response.status_code == 200, response.text

    drift = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    assert drift.truthful_answer_applied is True, drift.detail
    assert drift.in_sync is True, drift.detail
    assert (await _engine_config(engine, tenant_id, agent_id)).max_call_duration_s == SHORTER_CAP_S
