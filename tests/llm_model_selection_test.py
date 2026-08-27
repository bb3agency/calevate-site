"""A client chooses which language model their agents run — and the menu cannot lie (D-454).

FOUR CLAIMS, and they are different claims:

1. **The fallback is three levels deep and always says which one answered.** `agents
   .llm_model` -> `organizations.default_llm_model` -> the platform's own model, with the
   source reported on every response. "Never a silent default" is only checkable if the
   provenance travels with the value.
2. **THE MENU MAY NOT CONTAIN A DISH THE KITCHEN CANNOT COOK.** The offered set, the set
   the write path accepts, and the set the wire can actually address are ONE SET — asserted
   in both directions, under both arms of the switch. This is the invariant the whole
   feature rests on: `gpt-4.1-mini` costs 2.7x `gpt-4o-mini`, so a picker that offered a
   model with no Azure deployment behind it would quote and meter a client at the dearer
   rate for calls that ran the cheaper deployment — a charge for something we did not
   deliver, with nothing in a transcript or an execution payload to reveal it (hard rule 7).
3. **Every selectable model is priced.** An unpriced one is unmetered spend and a
   `ValueError` on the assist path; a priced one nobody can select is a figure that rots.
   Held equal in both directions, against the rate card and against the migration's frozen
   copy of the allow-list.
4. **A neighbour's account is not reachable through any of it.** The new column is on
   `organizations`, whose policy matches on `id`, and the cross-tenant read returns zero
   rows through the new column specifically (hard rule 1).

WHY THE UNIT HALF MONKEYPATCHES SETTINGS RATHER THAN USING A FIXTURE DEPLOYMENT: the
question "can this platform address this model" is answered from three settings, and the
interesting answers are the ones a real deployment is never in for long — a model with no
deployment, a map naming the platform's own model, a half-cleared field. Those are states
to construct, not to wait for.
"""

from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle, llm_models, prompts
from apps.api.agents.llm_models import (
    CLIENT_UNAVAILABLE_REASON,
    LLM_MODEL_SOURCES,
    available_models,
    deployment_for,
    every_selectable_model_is_priced,
    offerable_models,
    resolve_llm_model,
    selectable_models,
    unofferable_reason,
    validate_llm_model,
)
from apps.api.agents.llm_routes import admin_router as llm_admin_router
from apps.api.agents.llm_routes import router as llm_router
from apps.api.agents.routes import router as agents_router
from apps.api.agents.service import publish_agent
from apps.api.billing.rates import PRICED_LLM_MODELS, llm_cost_inr_per_minute
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import (
    AZURE_OPENAI_DEFAULT_MODEL,
    AZURE_OPENAI_MODELS,
    GOOGLE_DIRECT_MODELS,
    LLM_MODEL_NAMES,
    LLM_MODELS,
    OPENAI_DIRECT_MODELS,
    SELECTABLE_LLM_MODELS,
    AgentConfig,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import accept_agreements

# `-m rls` picks the cross-tenant case up with the rest of the isolation suite.
pytestmark = [pytest.mark.rls]

RESOURCE = "calevate-voice"
API_KEY = "azure-static-key-under-test"
#: The deployment for the PLATFORM's model. Deliberately unlike any model identifier, so a
#: test that confuses a deployment with a model fails rather than coincidentally passing.
DEFAULT_DEPLOYMENT = "calevate-voice-default"
#: The deployment an operator would create for the OTHER allow-listed model.
ALTERNATE_DEPLOYMENT = "calevate-voice-alt"

#: The allow-listed model that is NOT the shipped default — named by derivation rather
#: than typed, so a change to the Literal moves this file with it (D-104).
ALTERNATE_MODEL = next(iter(AZURE_OPENAI_MODELS - {AZURE_OPENAI_DEFAULT_MODEL}))


def _load_revision(stem: str) -> ModuleType:
    """One alembic revision, loaded from its file the way alembic itself loads it.

    Same idiom as `tests/disclosure_toggle_test.py`, and for the same reason: a revision
    is not an importable module (`alembic/versions` is not a package), and a test that
    re-typed the constant it is checking would be checking itself.
    """
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _azure(monkeypatch: pytest.MonkeyPatch, *, deployments: str = "") -> None:
    """A deployment with a complete Azure leg, and whatever extra deployments are named."""
    settings = get_settings()
    for field, value in (
        ("azure_openai_resource", RESOURCE),
        ("azure_openai_api_key", API_KEY),
        ("azure_openai_deployment", DEFAULT_DEPLOYMENT),
        ("azure_openai_model", AZURE_OPENAI_DEFAULT_MODEL),
        ("azure_openai_deployments", deployments),
    ):
        monkeypatch.setattr(settings, field, value, raising=False)


def _no_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local, CI and any staging without a resource — the arm where the model itself is
    what the engine is sent."""
    settings = get_settings()
    for field in ("azure_openai_resource", "azure_openai_api_key", "azure_openai_deployment"):
        monkeypatch.setattr(settings, field, None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployments", "", raising=False)


# --- 1. the three levels ---------------------------------------------------------------


def test_the_agents_own_choice_wins_and_says_so() -> None:
    resolved = resolve_llm_model(agent_model=ALTERNATE_MODEL, organization_model="gpt-4o-mini")
    assert (resolved.model, resolved.source) == (ALTERNATE_MODEL, "agent")


def test_the_account_default_answers_when_the_agent_has_not_chosen() -> None:
    resolved = resolve_llm_model(agent_model=None, organization_model=ALTERNATE_MODEL)
    assert (resolved.model, resolved.source) == (ALTERNATE_MODEL, "organization")


def test_the_platform_answers_last_and_is_the_live_setting_not_the_frozen_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ONE PLACE THIS DEPARTS FROM "fall back to `AZURE_OPENAI_DEFAULT_MODEL`", and
    the reason is D-105's shape: `azure_openai_model` is `applies: live`, so an operator
    who flips it and points the deployment at a matching model has changed which model
    every un-chosen account runs. Reporting the frozen constant then would tell every
    client on that deployment the wrong model — and price it wrong. On a deployment nobody
    has flipped the two are the same string, which is why this is strictly more correct
    rather than differently correct."""
    monkeypatch.setattr(get_settings(), "azure_openai_model", ALTERNATE_MODEL, raising=False)
    resolved = resolve_llm_model(agent_model=None, organization_model=None)
    assert (resolved.model, resolved.source) == (ALTERNATE_MODEL, "platform")


def test_the_three_levels_are_the_whole_vocabulary() -> None:
    """Derived from the Literal, so a fourth level cannot appear on the wire without
    appearing in the type first."""
    assert LLM_MODEL_SOURCES == ("agent", "organization", "platform")


# --- 2. the menu and the kitchen ---------------------------------------------------------


def test_with_no_azure_leg_every_azure_model_is_offerable_and_no_other_leg_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no deployment indirection on this arm: `in_call_llm` sends the model itself,
    so anything the Azure catalogue admits can genuinely run.

    **AND THE OTHER TWO LEGS ARE NOT OFFERED, WHICH IS THE ASYMMETRY WORTH PINNING.** Their
    credential lives in the ENGINE's own store, so "unconfigured" there is not a passthrough
    — it is an agent that 401s on its first turn. `installed_llm_providers()` answers
    Azure-only with nothing installed, which reproduces this repository's behaviour from
    before there was a second leg: CI and every local run see exactly what they always saw.
    """
    _no_azure(monkeypatch)
    assert offerable_models() == AZURE_OPENAI_MODELS
    assert not offerable_models() & (OPENAI_DIRECT_MODELS | GOOGLE_DIRECT_MODELS)


def test_with_an_azure_leg_only_the_models_with_a_deployment_are_addressable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _azure(monkeypatch)
    assert offerable_models() == {AZURE_OPENAI_DEFAULT_MODEL}
    _azure(monkeypatch, deployments=f"{ALTERNATE_MODEL}={ALTERNATE_DEPLOYMENT}")
    assert offerable_models() == AZURE_OPENAI_MODELS


def test_the_platform_models_deployment_comes_from_its_own_field_and_the_map_cannot_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two fields, no model named twice — and if one ever is, the field the engine's
    credential store is populated from wins. Letting the map win would point published
    agents at one deployment and the vendor's own credential entry at another."""
    _azure(monkeypatch, deployments=f"{AZURE_OPENAI_DEFAULT_MODEL}=someone-elses-deployment")
    assert deployment_for(AZURE_OPENAI_DEFAULT_MODEL) == DEFAULT_DEPLOYMENT


def test_a_cleared_deployment_field_is_not_a_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator clearing the console input leaves `""`, and an empty string is not a
    deployment id — returning it would build a URL addressing a host and no model."""
    _azure(monkeypatch)
    monkeypatch.setattr(get_settings(), "azure_openai_deployment", "   ", raising=False)
    assert deployment_for(AZURE_OPENAI_DEFAULT_MODEL) is None


@pytest.mark.parametrize(
    ("deployments", "why"),
    [
        ("", "nothing configured beyond the platform's own model"),
        (f"{ALTERNATE_MODEL}={ALTERNATE_DEPLOYMENT}", "both models deployed"),
    ],
)
def test_the_offered_set_and_the_addressable_set_are_the_same_set(
    monkeypatch: pytest.MonkeyPatch, deployments: str, why: str
) -> None:
    """**THE INVARIANT.** A model that can be offered must be one the wire can address,
    and a model the wire can address must be offered — in both directions, so neither
    side can drift by an edit to the other.

    Asserted three ways because there are three surfaces that could disagree: what the
    menu marks available, what the validator accepts, and what `offerable_models()`
    says can run.
    """
    _azure(monkeypatch, deployments=deployments)
    addressable = offerable_models()

    offered = {option.model for option in available_models() if option.is_available}
    assert offered == addressable, why

    accepted = set()
    for model in selectable_models():
        try:
            validate_llm_model(model, field="llm_model")
        except ProblemError:
            continue
        accepted.add(model)
    assert accepted == addressable, why


def test_an_unavailable_model_is_shown_with_a_reason_rather_than_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing row tells an operator nothing; a row that says what is missing tells them
    the one thing they can act on. It is still unselectable — the client-facing behaviour
    is identical, and only the operator-facing behaviour differs."""
    _azure(monkeypatch)
    rows = {option.model: option for option in available_models()}
    # EVERY PERMITTED MODEL IS A ROW, including the two legs this platform holds no key for
    # — a missing row tells an operator nothing.
    assert set(rows) == SELECTABLE_LLM_MODELS
    blocked = rows[ALTERNATE_MODEL]
    assert blocked.is_available is False
    assert blocked.unavailable_reason is not None
    assert "deployment" in blocked.unavailable_reason
    assert rows[AZURE_OPENAI_DEFAULT_MODEL].unavailable_reason is None
    # THE THREE GROUNDS ARE THREE SENTENCES, because they have three different owners: a
    # portal deployment, a pasted key, an invoice figure. A screen that could not tell them
    # apart would send all three to support.
    for other_leg in sorted(OPENAI_DIRECT_MODELS | GOOGLE_DIRECT_MODELS):
        if other_leg not in rows:
            continue
        reason = rows[other_leg].unavailable_reason
        assert reason is not None and "API key" in reason, other_leg
        assert reason != blocked.unavailable_reason, other_leg


def test_the_client_audience_hides_the_operator_ground_but_not_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE AUDIENCE SPLIT. A client has no ops console, no keys and no vendor portal, so the
    three operator grounds (a deployment, a key, a price) collapse to the ONE action a client
    has — ask their Calevate team. What must NOT change between audiences is WHICH models are
    available: only the wording of a blocked row's reason forks, never the flag."""
    _azure(monkeypatch)

    operator = {o.model: o for o in available_models(audience="operator")}
    client = {o.model: o for o in available_models(audience="client")}

    # Availability is one fact for both audiences — the set of blocked models is identical.
    assert {m for m, o in client.items() if not o.is_available} == {
        m for m, o in operator.items() if not o.is_available
    }

    # Every blocked row a client sees carries the SAME client sentence, and it never leaks an
    # operator ground — no "ops console", no "API key", no "deployment", no "attest".
    forbidden = ("ops console", "api key", "deployment", "attest", "credential", "authenticate")
    for model, option in client.items():
        if option.is_available:
            assert option.unavailable_reason is None
            continue
        assert option.unavailable_reason == CLIENT_UNAVAILABLE_REASON
        assert not any(term in option.unavailable_reason.lower() for term in forbidden), model
        # …while the operator sees the actionable ground for the very same model.
        assert operator[model].unavailable_reason is not None
        assert operator[model].unavailable_reason != option.unavailable_reason

    # `None` (offerable) is audience-independent at the predicate too.
    for model in selectable_models():
        both_none = (
            unofferable_reason(model, audience="operator") is None
            and unofferable_reason(model, audience="client") is None
        )
        assert both_none == (unofferable_reason(model) is None), model


def test_the_client_validator_refusal_names_no_operator_ground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client submitting a blocked model (the picker disables it, but a hand-built request
    can still reach the validator) is told to ask their Calevate team — never to edit a
    deployments setting or install a key."""
    _azure(monkeypatch)
    with pytest.raises(ProblemError) as refused:
        validate_llm_model(ALTERNATE_MODEL, field="default_llm_model", audience="client")
    assert refused.value.code == "llm_model_not_deployed"
    assert CLIENT_UNAVAILABLE_REASON in refused.value.detail
    for term in ("ops console", "deployment", "API key", "attest"):
        assert term not in refused.value.detail
    # The operator audience still gets the ground on the identical selection.
    with pytest.raises(ProblemError) as operator:
        validate_llm_model(ALTERNATE_MODEL, field="default_llm_model", audience="operator")
    assert "deployment" in operator.value.detail


def test_the_two_refusals_are_different_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "not a model we run" is the caller's mistake; "we run it, but not here yet" is an
    operator's to fix. A screen that could not tell them apart would send a client to
    support for a configuration change."""
    _azure(monkeypatch)

    with pytest.raises(ProblemError) as unknown:
        validate_llm_model("gpt-9-omni", field="llm_model")
    assert unknown.value.code == "llm_model_not_available"
    assert unknown.value.status == 422
    # The message names what WOULD have worked — a refusal a caller cannot act on is a
    # refusal that becomes a support ticket.
    assert AZURE_OPENAI_DEFAULT_MODEL in unknown.value.detail
    assert unknown.value.fields == [
        {"name": "llm_model", "reason": "not one of the available language models"}
    ]

    with pytest.raises(ProblemError) as undeployed:
        validate_llm_model(ALTERNATE_MODEL, field="default_llm_model")
    assert undeployed.value.code == "llm_model_not_deployed"
    assert undeployed.value.status == 422


def test_null_is_always_accepted_because_it_means_inherit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing a choice can never be refused: it is how an account goes back to the
    platform, and a validator that refused it would strand whoever chose first."""
    _azure(monkeypatch)
    assert validate_llm_model(None, field="llm_model") is None


def test_the_chosen_model_picks_the_deployment_and_the_priced_half_agrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire half of the whole feature: choosing the dearer model addresses the DEARER
    model's deployment, not the default one. Before D-454 this call returned
    `DEFAULT_DEPLOYMENT` whatever was chosen."""
    from apps.api.agents import service

    _azure(monkeypatch, deployments=f"{ALTERNATE_MODEL}={ALTERNATE_DEPLOYMENT}")
    assert service.in_call_llm(ALTERNATE_MODEL)["llm_model"] == ALTERNATE_DEPLOYMENT
    assert service.in_call_llm(None)["llm_model"] == DEFAULT_DEPLOYMENT


# --- 3. every selectable model is priced -------------------------------------------------


def test_the_allow_list_and_the_rate_card_are_the_same_set() -> None:
    """Both directions. A selectable model nobody priced is unmetered spend; a priced
    model nobody can select is a number that rots unnoticed."""
    assert every_selectable_model_is_priced()
    assert PRICED_LLM_MODELS == SELECTABLE_LLM_MODELS


def test_every_offered_row_carries_a_price_derived_from_the_rate_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NUMERIC, never a float, and never a figure typed in the picker: the value is the
    rate card's own function called with this row's model (hard rule 7)."""
    _no_azure(monkeypatch)
    for option in available_models():
        assert isinstance(option.inr_per_minute, Decimal)
        assert option.inr_per_minute == llm_cost_inr_per_minute(5, model=option.model)
        assert option.inr_per_minute > 0


def test_the_dearer_model_really_is_dearer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason any of this matters: the two models are 2.7x apart, so running one and
    billing the other is a real amount of somebody's money."""
    _no_azure(monkeypatch)
    prices = {option.model: option.inr_per_minute for option in available_models()}
    assert prices[ALTERNATE_MODEL] > prices[AZURE_OPENAI_DEFAULT_MODEL]


def test_the_migrations_frozen_allow_list_still_matches_the_live_one() -> None:
    """A migration is a historical artefact, so `b7d2f10c93ae` copies the allow-list
    rather than importing it — and this is what makes the copy honest. Adding a model to
    the Literal fails HERE, while the fix is still free: widen the CHECK in a new
    revision, or the database will refuse the value the API just accepted."""
    original = _load_revision("b7d2f10c93ae_a_client_chooses_the_model_their_agents_run")
    widened = _load_revision("d3a7c81f45be_a_client_chooses_a_model_on_any_declared_leg")
    # THE LIVE CONSTRAINT IS THE LATER REVISION'S, AND IT IS THE WHOLE CATALOGUE. A CHECK is
    # a FLOOR against values no writer should produce; which models may be CHOSEN depends on
    # a live credential and a live attestation, facts a constraint cannot see (see that
    # revision's docstring for the argument in full).
    assert set(widened.ALLOWED_LLM_MODELS) == LLM_MODEL_NAMES
    # AND THE EARLIER REVISION'S COPY IS FROZEN AT WHAT IT ADMITTED, which is what the
    # downgrade path restores — so the two are checked against each other rather than one
    # being quietly re-pointed at today's set.
    assert set(original.ALLOWED_LLM_MODELS) == set(widened.PRIOR_ALLOWED_LLM_MODELS)
    assert set(original.ALLOWED_LLM_MODELS) < set(widened.ALLOWED_LLM_MODELS)


# --- 4. the API, end to end ---------------------------------------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(agents_router)
    application.include_router(llm_router)
    application.include_router(llm_admin_router)
    # A new route that forgets its `permission_meta` fails here rather than silently in
    # production with an open door.
    assert_policy_registry_complete(application)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """(tenant_id, seeded receptionist id, client owner bearer) for a fresh account."""
    created = await admin_service.create_organization(
        name="Model Picker Clinic",
        slug=f"mp-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
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
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return tenant_id, agent_id, f"dev:client:{user_id}"


async def _operator() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def test_an_agent_reports_its_model_and_which_level_chose_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole client-facing contract in one route, walked down all three rungs."""
    _no_azure(monkeypatch)
    tenant_id, agent_id, bearer = await _tenant()
    app = _app()
    headers = {"Authorization": f"Bearer {bearer}"}

    async with _client(app) as client:
        # Nothing chosen anywhere: the platform answers, and it says so.
        first = await client.get(f"/v1/agents/{agent_id}", headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["llm_model"] is None
        assert first.json()["llm_model_effective"] == get_settings().azure_openai_model
        assert first.json()["llm_model_source"] == "platform"

        # The account chooses: every agent that has not chosen follows it.
        put = await client.put(
            "/v1/organization/llm-defaults",
            headers=headers,
            json={"default_llm_model": ALTERNATE_MODEL},
        )
        assert put.status_code == 200, put.text
        assert put.json()["default_llm_model"] == ALTERNATE_MODEL
        assert put.json()["effective_default"] == ALTERNATE_MODEL

        inherited = await client.get(f"/v1/agents/{agent_id}", headers=headers)
        assert inherited.json()["llm_model"] is None
        assert inherited.json()["llm_model_effective"] == ALTERNATE_MODEL
        assert inherited.json()["llm_model_source"] == "organization"

        # The agent overrides its account.
        patched = await client.patch(
            f"/v1/agents/{agent_id}",
            headers=headers,
            json={"llm_model": AZURE_OPENAI_DEFAULT_MODEL},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["llm_model"] == AZURE_OPENAI_DEFAULT_MODEL
        assert patched.json()["llm_model_effective"] == AZURE_OPENAI_DEFAULT_MODEL
        assert patched.json()["llm_model_source"] == "agent"

        # And `null` on the agent is INHERIT, not "leave it alone" — the one field on this
        # PATCH where an explicit null is a request rather than an absence.
        cleared = await client.patch(
            f"/v1/agents/{agent_id}", headers=headers, json={"llm_model": None}
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["llm_model"] is None
        assert cleared.json()["llm_model_source"] == "organization"

        # Omitting the field entirely leaves the choice alone — the other half of the
        # tri-state, and the half a `str | None` model alone could not express.
        #
        # ⚠ THE AGENT IS PUT BACK ON ITS OWN MODEL FIRST, and that is the whole test. This
        # assertion used to run while the agent was already inheriting, so it read
        # `source == "organization"` before AND after and passed identically whether the
        # omission was honoured or silently cleared the column — a test of the tri-state
        # that could not fail on the half it was named for.
        rechosen = await client.patch(
            f"/v1/agents/{agent_id}",
            headers=headers,
            json={"llm_model": AZURE_OPENAI_DEFAULT_MODEL},
        )
        assert rechosen.status_code == 200, rechosen.text
        assert rechosen.json()["llm_model_source"] == "agent"

        renamed = await client.patch(
            f"/v1/agents/{agent_id}", headers=headers, json={"name": "Front desk"}
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Front desk"
        assert renamed.json()["llm_model"] == AZURE_OPENAI_DEFAULT_MODEL
        assert renamed.json()["llm_model_source"] == "agent"

        # ...and the column itself, not only the rendering of it: a `coalesce` on this
        # column would have written NULL here and the roster would still have said
        # "organization" for a different reason.
        async with tenant_session(tenant_id) as check:
            assert (
                await check.execute(
                    text("SELECT llm_model FROM agents WHERE id = :aid"), {"aid": agent_id}
                )
            ).scalar() == AZURE_OPENAI_DEFAULT_MODEL

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(text("SELECT default_llm_model FROM organizations"))
        ).scalar()
    assert stored == ALTERNATE_MODEL


async def test_the_roster_carries_the_same_three_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    """One resolver behind the list and the detail route: a screen that reads a roster and
    a screen that opens one agent must not be able to disagree."""
    _no_azure(monkeypatch)
    _tenant_id, agent_id, bearer = await _tenant()
    async with _client(_app()) as client:
        rows = await client.get("/v1/agents", headers={"Authorization": f"Bearer {bearer}"})
    assert rows.status_code == 200, rows.text
    row = next(r for r in rows.json() if r["id"] == str(agent_id))
    assert row["llm_model_source"] == "platform"
    assert row["llm_model_effective"] == get_settings().azure_openai_model


async def test_choosing_a_model_this_platform_cannot_run_is_refused_at_both_doors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offer and the wire cannot diverge, asserted through HTTP rather than only
    through the validator: a selection the platform has no deployment for is a 422 on the
    agent and on the account, in problem+json, naming what is wrong."""
    _azure(monkeypatch)
    _tenant_id, agent_id, bearer = await _tenant()
    headers = {"Authorization": f"Bearer {bearer}"}

    async with _client(_app()) as client:
        listing = await client.get("/v1/organization/llm-defaults", headers=headers)
        assert listing.status_code == 200, listing.text
        rows = {row["model"]: row for row in listing.json()["available"]}
        assert rows[ALTERNATE_MODEL]["is_available"] is False
        assert rows[ALTERNATE_MODEL]["unavailable_reason"]

        refused = await client.put(
            "/v1/organization/llm-defaults",
            headers=headers,
            json={"default_llm_model": ALTERNATE_MODEL},
        )
        assert refused.status_code == 422, refused.text
        assert refused.headers["content-type"].startswith("application/problem+json")
        assert refused.json()["type"].endswith("/llm_model_not_deployed")
        assert refused.json()["remediation"]

        on_agent = await client.patch(
            f"/v1/agents/{agent_id}", headers=headers, json={"llm_model": ALTERNATE_MODEL}
        )
        assert on_agent.status_code == 422, on_agent.text
        assert on_agent.json()["type"].endswith("/llm_model_not_deployed")

        unknown = await client.patch(
            f"/v1/agents/{agent_id}", headers=headers, json={"llm_model": "gpt-9-omni"}
        )
        assert unknown.status_code == 422, unknown.text
        assert unknown.json()["type"].endswith("/llm_model_not_available")
        # Naming the permitted values is the difference between a refusal a screen can act
        # on and one it can only show.
        assert AZURE_OPENAI_DEFAULT_MODEL in unknown.json()["detail"]


async def test_prices_reach_the_wire_as_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard rule 7 at the boundary: a JSON float cannot hold a rupee amount exactly, so
    the value is a string all the way to the screen and reads back as the same Decimal."""
    _no_azure(monkeypatch)
    _tenant_id, _agent_id, bearer = await _tenant()
    async with _client(_app()) as client:
        body = await client.get(
            "/v1/organization/llm-defaults", headers={"Authorization": f"Bearer {bearer}"}
        )
    assert body.status_code == 200, body.text
    for row in body.json()["available"]:
        assert isinstance(row["platform_cost_inr_per_minute"], str)
        assert Decimal(row["platform_cost_inr_per_minute"]) == llm_cost_inr_per_minute(
            5, model=row["model"]
        )
        # THE PROVIDER FOLLOWS THE MODEL, not the product: three legs are declared, so a
        # row's leg is a property of the model it names (`leg_for_model`), and a hard-coded
        # "azure_openai" here was correct only while there was one leg to name.
        assert row["provider"] == LLM_MODELS[row["model"]].provider
    assert [row["model"] for row in body.json()["available"]] == list(selectable_models())
    assert sum(1 for row in body.json()["available"] if row["is_platform_default"]) == 1


async def test_an_operator_can_set_it_for_any_client_and_the_change_is_audited(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Changing which model a client's calls run on is a configuration change with a price
    attached, so it lands in the hash-chained ledger and its summary carries the VALUE — a
    model identifier is a platform constant, not anybody's personal data, and WHICH model
    was chosen is the whole of what an auditor reconstructing a bill needs."""
    _no_azure(monkeypatch)
    tenant_id, _agent_id, _bearer = await _tenant()
    operator = await _operator()

    with caplog.at_level("INFO", logger="apps.api.compliance.audit"):
        caplog.clear()
        async with _client(_app()) as client:
            written = await client.put(
                f"/v1/admin/organizations/{tenant_id}/llm-defaults",
                headers={"Authorization": f"Bearer {operator}"},
                json={"default_llm_model": ALTERNATE_MODEL},
            )
            assert written.status_code == 200, written.text
            assert written.json()["default_llm_model"] == ALTERNATE_MODEL

            read_back = await client.get(
                f"/v1/admin/organizations/{tenant_id}/llm-defaults",
                headers={"Authorization": f"Bearer {operator}"},
            )
            assert read_back.status_code == 200, read_back.text
            assert read_back.json()["effective_default"] == ALTERNATE_MODEL

    assert "admin.organization_llm_default_set" in await _audited_actions(tenant_id)
    assert _summaries(caplog) == [{"default_llm_model": ALTERNATE_MODEL, "changed": True}]


async def test_a_client_setting_their_own_default_is_audited(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _no_azure(monkeypatch)
    tenant_id, _agent_id, bearer = await _tenant()
    with caplog.at_level("INFO", logger="apps.api.compliance.audit"):
        caplog.clear()
        async with _client(_app()) as client:
            response = await client.put(
                "/v1/organization/llm-defaults",
                headers={"Authorization": f"Bearer {bearer}"},
                json={"default_llm_model": ALTERNATE_MODEL},
            )
    assert response.status_code == 200, response.text

    assert await _audited_actions(tenant_id) >= {"organization.llm_default_set"}
    assert _summaries(caplog) == [{"default_llm_model": ALTERNATE_MODEL, "changed": True}]


async def _audited_actions(tenant_id: uuid.UUID) -> set[str]:
    """Every action this account's hash-chained ledger holds."""
    async with untenanted_session() as session:
        return set(
            (
                await session.execute(
                    text("SELECT action FROM audit_log WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            ).scalars()
        )


#: The audit summary keys these tests care about. `audit_log` has NO summary column — the
#: row carries actor, tenant, object and ip, and `write_audit` sends the summary to the LOG
#: stream keyed by the same entry id (`compliance/audit.py`). So "the entry records WHICH
#: model" is a claim about a log line, and it is asserted on the log line.
_SUMMARY_KEYS = ("default_llm_model", "changed", "fields", "llm_model")


def _summaries(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """The audit summaries captured, in order, with only the keys under test.

    Read through the same redactor production uses (`redact_mapping` runs before the
    record is emitted), which is the point: a summary that does not SURVIVE redaction is
    a summary nobody can read, and asserting on the dict we passed in would not have
    noticed. `fields` used to be a list, and `_redact_value` collapses every sequence to
    "[3 items]".
    """
    return [
        {key: getattr(record, key) for key in _SUMMARY_KEYS if hasattr(record, key)}
        for record in caplog.records
        if record.message == "audit"
    ]


async def test_the_agents_own_model_change_is_audited_with_the_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Four write paths move which model answers a client's phone, and all four record it.

    This one recorded the field NAME and not the value, so the entry said "somebody
    changed this agent's model" and refused to say what to — the one fact a bill dispute
    or a quality complaint turns on. A model identifier is a platform configuration
    constant and not anybody's personal data, which is the same argument the account-level
    write already made for putting the value in. `null` is recorded as itself, and a PATCH
    that never named the field carries no model key at all — the third state, in the entry
    as well as on the wire.
    """
    _no_azure(monkeypatch)
    _tenant_id, agent_id, bearer = await _tenant()
    headers = {"Authorization": f"Bearer {bearer}"}

    with caplog.at_level("INFO", logger="apps.api.compliance.audit"):
        caplog.clear()
        async with _client(_app()) as client:
            for body in (
                {"llm_model": ALTERNATE_MODEL},
                {"llm_model": None},
                {"name": "Front desk"},
            ):
                response = await client.patch(f"/v1/agents/{agent_id}", headers=headers, json=body)
                assert response.status_code == 200, response.text

    assert _summaries(caplog) == [
        {"fields": "llm_model", "llm_model": ALTERNATE_MODEL},
        {"fields": "llm_model", "llm_model": None},
        {"fields": "name"},
    ]


async def _engine_model(engine: FakeEngine, ref: str) -> str | None:
    """What this engine is HOLDING for that agent, on the LLM leg.

    Through `get_agent`, the adapter's own read-back, rather than by reaching into its
    dictionary: `publish_agent` verifies through the same call, so a test that read the
    private store could pass while the read-back a publish depends on answered otherwise.
    """
    snapshot = await engine.get_agent(ref)
    assert snapshot.models is not None
    return snapshot.models.llm_model


async def _published(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    """A genuinely LIVE agent: a script, then a real publish through the engine adapter.

    Not the `UPDATE agents SET status = 'live'` shortcut other suites use, because the
    thing under test is what the ENGINE ends up holding — an agent marked live that the
    adapter never saw would make every assertion below vacuous.
    """
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller in Telugu and take their appointment details.",
            notes=None,
            created_by=None,
        )
        return await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def test_moving_the_account_default_reaches_the_agents_it_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ACCOUNT DEFAULT IS ENGINE-BOUND, so writing the column is only half of it.

    `_to_config` resolves this rung at PUBLISH time, so before the write re-published
    them every live agent inheriting the account default kept calling the model it was
    last published against — while the settings screen, the agent screen and the admin
    console all reported the new one as in force, and the client screen said "this takes
    effect on the next call". That is the screen and the phone line disagreeing about
    which model is running, which is the single failure `agents/llm_models.py` exists to
    prevent. Every other engine-bound writer in this tree (`set_call_cap`,
    `set_disclosure_posture`, `lifecycle.update_agent`) already re-published in the same
    transaction; this one did not.

    A DRAFT AGENT IS NOT PUBLISHED BY IT, which is the other half: a query that forgot
    `status = 'live'` would put an unfinished agent on the phone as a side effect of a
    settings change.
    """
    _no_azure(monkeypatch)
    tenant_id, agent_id, bearer = await _tenant()
    ref = await _published(tenant_id, agent_id)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    # Nobody has chosen, so on this arm the engine is sent no model at all and runs the
    # platform's own — `chosen_llm_model` answers None for the platform rung.
    assert await _engine_model(engine, ref) is None

    draft_id = await _second_agent(tenant_id)
    async with _client(_app()) as client:
        put = await client.put(
            "/v1/organization/llm-defaults",
            headers={"Authorization": f"Bearer {bearer}"},
            json={"default_llm_model": ALTERNATE_MODEL},
        )
        assert put.status_code == 200, put.text

    assert await _engine_model(engine, ref) == ALTERNATE_MODEL
    async with tenant_session(tenant_id) as session:
        draft = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :aid"),
                {"aid": draft_id},
            )
        ).first()
    assert draft is not None
    assert (str(draft[0]), draft[1]) == ("draft", None)


async def test_an_agent_with_its_own_model_is_left_where_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account default moves the agents that INHERIT it and no others — the sentence
    both screens print, checked against the config the engine is actually holding."""
    _no_azure(monkeypatch)
    tenant_id, agent_id, bearer = await _tenant()
    ref = await _published(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {bearer}"}

    async with _client(_app()) as client:
        pinned = await client.patch(
            f"/v1/agents/{agent_id}",
            headers=headers,
            json={"llm_model": AZURE_OPENAI_DEFAULT_MODEL},
        )
        assert pinned.status_code == 200, pinned.text
        moved = await client.put(
            "/v1/organization/llm-defaults",
            headers=headers,
            json={"default_llm_model": ALTERNATE_MODEL},
        )
        assert moved.status_code == 200, moved.text

    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert await _engine_model(engine, ref) == AZURE_OPENAI_DEFAULT_MODEL


async def test_re_sending_the_value_already_on_file_pushes_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A PUT states the whole resource, so a repeat is idempotent — and a double-clicked
    Save must not become a fleet-wide re-publish. The entry says `changed: false`, which
    is what tells an auditor reading a run of identical entries which one moved a phone
    line."""
    _no_azure(monkeypatch)
    tenant_id, agent_id, bearer = await _tenant()
    ref = await _published(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {bearer}"}
    body = {"default_llm_model": ALTERNATE_MODEL}

    published: list[str] = []
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    original = engine.update_agent

    async def counting(agent_ref: str, config: AgentConfig) -> None:
        published.append(str(agent_ref))
        await original(agent_ref, config)

    monkeypatch.setattr(engine, "update_agent", counting)

    with caplog.at_level("INFO", logger="apps.api.compliance.audit"):
        caplog.clear()
        async with _client(_app()) as client:
            for _ in range(2):
                response = await client.put(
                    "/v1/organization/llm-defaults", headers=headers, json=body
                )
                assert response.status_code == 200, response.text

    assert published == [ref]
    assert _summaries(caplog) == [
        {"default_llm_model": ALTERNATE_MODEL, "changed": True},
        {"default_llm_model": ALTERNATE_MODEL, "changed": False},
    ]
    assert (await _read_org_default(tenant_id)) == ALTERNATE_MODEL


async def _read_org_default(tenant_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(text("SELECT default_llm_model FROM organizations"))
        ).scalar()
    return str(value) if value is not None else None


async def _second_agent(tenant_id: uuid.UUID) -> uuid.UUID:
    """A DRAFT agent beside the seeded one, so "only live agents are published" is a
    claim with something to be false about."""
    async with tenant_session(tenant_id) as session:
        return await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Overflow desk",
            direction="inbound",
            language_primary="te-IN",
            max_call_duration_s=None,
        )


async def test_a_model_whose_deployment_was_removed_refuses_the_go_live_in_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REFUSAL A CLIENT ACTUALLY MEETS, at the button that puts an agent on the phone.

    `in_call_llm` refuses to publish a model with no deployment, and the unit test for that
    calls the decision point directly. This is the other half: what the person pressing
    "go live" is told. It must be a 422 problem+json naming the model and what to do — a
    `business_rule`, not a 500 — because the state is reachable by an operator removing a
    `model=deployment` entry under an account that had already chosen, and the client who
    then cannot activate their agent has to be told something they can act on.
    """
    _azure(monkeypatch, deployments=f"{ALTERNATE_MODEL}={ALTERNATE_DEPLOYMENT}")
    tenant_id, agent_id, bearer = await _tenant()
    headers = {"Authorization": f"Bearer {bearer}"}
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller in Telugu and take their appointment details.",
            notes=None,
            created_by=None,
        )

    async with _client(_app()) as client:
        chosen = await client.put(
            "/v1/organization/llm-defaults",
            headers=headers,
            json={"default_llm_model": ALTERNATE_MODEL},
        )
        assert chosen.status_code == 200, chosen.text

        # The operator removes the deployment the account is now on.
        _azure(monkeypatch)

        refused = await client.post(f"/v1/agents/{agent_id}/activate", headers=headers)

    assert refused.status_code == 422, refused.text
    assert refused.headers["content-type"].startswith("application/problem+json")
    body = refused.json()
    assert body["type"].endswith("/llm_model_not_deployed")
    assert body["kind"] == "business_rule"
    assert ALTERNATE_MODEL in body["detail"]
    assert body["remediation"]
    # And nothing was half-done: the agent is still a draft, not a live agent nobody can
    # publish.
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    assert str(status) == "draft"


# --- 5. hard rule 1 ------------------------------------------------------------------------


async def test_a_neighbours_model_default_is_invisible_and_unwritable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-tenant zero rows THROUGH THE NEW COLUMN specifically. `organizations`' policy
    matches on `id`, and adding a column to a table under RLS inherits it — "inherits" is a
    sentence that stays true until somebody's `ALTER TABLE` turns FORCE off, so it is read
    back rather than asserted."""
    _no_azure(monkeypatch)
    mine, _agent_id, bearer = await _tenant()
    theirs, their_agent, _their_bearer = await _tenant()

    async with tenant_session(theirs) as session:
        await session.execute(
            text("UPDATE organizations SET default_llm_model = :m"),
            {"m": ALTERNATE_MODEL},
        )

    # The neighbour's row is not readable from my session, through the new column.
    async with tenant_session(mine) as session:
        rows = (
            await session.execute(text("SELECT id, default_llm_model FROM organizations"))
        ).all()
    assert [r[0] for r in rows] == [mine]
    assert rows[0][1] is None

    # ...and my write cannot reach it either: RLS makes the UPDATE match nothing.
    async with tenant_session(mine) as session:
        result = await session.execute(
            text("UPDATE organizations SET default_llm_model = :m WHERE id = :other"),
            {"m": AZURE_OPENAI_DEFAULT_MODEL, "other": theirs},
        )
        assert result.rowcount == 0
    async with tenant_session(theirs) as session:
        assert (
            await session.execute(text("SELECT default_llm_model FROM organizations"))
        ).scalar() == ALTERNATE_MODEL

    # And through the HTTP surface: a neighbour's agent id is a 404, not their model.
    async with _client(_app()) as client:
        response = await client.get(
            f"/v1/agents/{their_agent}", headers={"Authorization": f"Bearer {bearer}"}
        )
    assert response.status_code == 404


async def test_the_database_refuses_a_model_the_api_would_have_refused() -> None:
    """The CHECK is not belt-and-braces for the validator: a restore that lands without
    constraints, an importer, or an operator's hand-run UPDATE during an incident all
    reach these columns without passing a Pydantic model, and `in_call_llm` reads the
    result on a live phone line."""
    tenant_id, agent_id, _bearer = await _tenant()
    for statement, params in (
        ("UPDATE organizations SET default_llm_model = :m", {"m": "gpt-9-omni"}),
        ("UPDATE agents SET llm_model = :m WHERE id = :aid", {"m": "sarvam-105b", "aid": agent_id}),
    ):
        with pytest.raises(IntegrityError):
            async with tenant_session(tenant_id) as session:
                await session.execute(text(statement), params)


async def test_the_module_exposes_no_second_allow_list() -> None:
    """One way per problem, checked rather than promised: everything this module offers is
    derived from `AZURE_OPENAI_MODELS`, so a second hand-written tuple of model names
    would show up here as a set that is not that set."""
    assert set(selectable_models()) == SELECTABLE_LLM_MODELS
    assert set(llm_models.selectable_models()) == set(PRICED_LLM_MODELS)


async def test_an_account_that_does_not_exist_is_a_404_on_both_admin_doors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator naming an account that is not there gets `not_found`, not an empty
    settings page and not a 200 for a write that stored nothing. Under RLS the read and
    the write both simply match no rows, so the refusal has to be authored rather than
    inferred from an exception nobody raises."""
    _no_azure(monkeypatch)
    operator = await _operator()
    headers = {"Authorization": f"Bearer {operator}"}
    absent = uuid.uuid4()

    async with _client(_app()) as client:
        missing = await client.get(
            f"/v1/admin/organizations/{absent}/llm-defaults", headers=headers
        )
        assert missing.status_code == 404, missing.text
        assert missing.headers["content-type"].startswith("application/problem+json")

        written = await client.put(
            f"/v1/admin/organizations/{absent}/llm-defaults",
            headers=headers,
            json={"default_llm_model": None},
        )
        assert written.status_code == 404, written.text


async def test_a_patch_that_names_nothing_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding `llm_model` to the PATCH body must not make an empty body legal: answering
    200 for a request that changed nothing writes an audit row describing a decision
    nobody took."""
    _no_azure(monkeypatch)
    _tenant_id, agent_id, bearer = await _tenant()
    async with _client(_app()) as client:
        response = await client.patch(
            f"/v1/agents/{agent_id}", headers={"Authorization": f"Bearer {bearer}"}, json={}
        )
    assert response.status_code == 422, response.text
