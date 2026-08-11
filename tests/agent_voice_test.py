"""The voice catalog: the allowlist, and the admin-only write that respects it.

Two things are under test and they are not the same thing.

1. **The catalog is data we can stand behind.** D-36 locks a premium/value ladder
   (Bulbul v3 default, v2 as the value tier), so a catalog missing either rung has
   drifted from the decision. Every entry must validate against its own lookup —
   an entry the validator would refuse is a voice the UI offers and the API rejects.

2. **An unknown string never reaches an agent row.** That is the entire point:
   `agents.tts_voice` is free text whose next reader is a vendor API, so "typo stored,
   discovered at call time on a client's line" is the failure mode being closed.

The router is deliberately NOT mounted in `main.py`, so the HTTP tests mount it here —
and mount it AHEAD of `agents.routes.router`, which is the order the real app must use
(`/v1/agents/{agent_id}` otherwise eats the literal `voices`). Running the boot
assertion over the assembled app keeps that contract honest: if either route ever loses
its `permission_meta`, mounting it anywhere starts failing.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from apps.api.agents.routes import router as agents_router
from apps.api.agents.voice_routes import router as voice_router
from apps.api.agents.voices import (
    CATALOG,
    default_voice,
    get_voice,
    is_supported_voice,
    voice_ids,
)
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    # ORDER IS THE CONTRACT: the literal `/v1/agents/voices` must be declared before
    # `/v1/agents/{agent_id}`, or FastAPI matches the parameterised route first and
    # answers 422 about a UUID nobody sent.
    application.include_router(voice_router)
    application.include_router(agents_router)
    assert_policy_registry_complete(application)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin_token(role: str = "superadmin") -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant_id, agent_id, org slug, client dev bearer) for a fresh org with a member."""
    created = await admin_service.create_organization(
        name="Voice Clinic",
        slug=f"vox-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]

    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, agent_id, str(slug), f"dev:client:{clerk_id}"


async def _stored_voice(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[str | None, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT tts_voice, tts_provider FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).first()
    assert row is not None
    return row[0], row[1]


# --- The catalog itself -------------------------------------------------------


def test_the_catalog_is_not_empty_and_every_entry_validates() -> None:
    """A catalog whose own entries the validator refuses is worse than no catalog: the
    UI would offer voices the API rejects, and the bug would look like a server fault."""
    assert CATALOG, "an empty catalog makes the voice picker unusable"
    for voice in CATALOG:
        assert is_supported_voice(voice.id), f"{voice.id} is offered but not accepted"
        assert get_voice(voice.id) == voice
        assert voice.id in voice_ids()
        assert voice.provider == "sarvam", "D-36 locks the Sarvam stack"
        assert voice.label.strip(), "a voice with no label cannot be picked by a human"
        assert "te-IN" in voice.languages, "Telugu-first: a voice without Telugu is not ours"
        assert voice.languages[0] == "te-IN", "Telugu leads the list a picker renders"


def test_both_the_value_and_premium_tiers_are_represented() -> None:
    """D-36 in one assertion: "Sarvam Bulbul v3 default, v2 as the value tier". A
    catalog with only the premium rung silently deletes the cost lever D-35 recovered
    when it corrected D-20's "v2 is discontinued"."""
    tiers = {voice.tier for voice in CATALOG}
    assert tiers == {"premium", "value"}, "the D-36 ladder needs both rungs"

    premium = [voice for voice in CATALOG if voice.tier == "premium"]
    value = [voice for voice in CATALOG if voice.tier == "value"]
    assert {voice.tts_model for voice in premium} == {"bulbul:v3"}
    assert {voice.tts_model for voice in value} == {"bulbul:v2"}
    # The default is v3 per D-36 — a written decision, not a measurement of ours.
    assert default_voice().tts_model == "bulbul:v3"
    assert default_voice().tier == "premium"


def test_an_unknown_voice_id_is_not_supported() -> None:
    """Exact match, no normalisation: the stored string is pasted into a vendor request
    verbatim, so a near-miss is as wrong as a typo."""
    for unknown in ("", "bulbul", "bulbul:v4", "Bulbul:V3", " bulbul:v3", "anushka"):
        assert not is_supported_voice(unknown)
        assert get_voice(unknown) is None


def test_no_entry_claims_to_be_pilot_verified() -> None:
    """The docs name no voices and OPERATIONS §2 gate 3 still asks whether Bulbul V3 is
    even selectable on Bolna. Until that gate passes, presenting these ids as verified
    would be inventing fact. When the pilot answers, flip `verified` and this test."""
    assert all(not voice.verified for voice in CATALOG)
    assert all(voice.gender is None for voice in CATALOG), "no speaker genders in the docs"


# --- The endpoints ------------------------------------------------------------


async def test_a_client_can_read_the_catalog() -> None:
    """A client is the Principal Entity; they get to hear what their agent sounds like.
    Also pins the mount order — a 422 here means the router was mounted too late."""
    _tenant_id, _agent_id, slug, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.get(
            "/v1/agents/voices",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == len(CATALOG)
    assert {entry["id"] for entry in body} == set(voice_ids())
    assert {entry["tier"] for entry in body} == {"premium", "value"}


async def test_a_client_realm_principal_cannot_set_the_voice() -> None:
    """D-21's boundary: clients read, admins change engine-facing config. The realms do
    not share session logic (TRD §11), so a client token is not an admin token even for
    an owner — and the agent row must be untouched afterwards."""
    tenant_id, agent_id, slug, token = await _tenant()
    before = await _stored_voice(tenant_id, agent_id)

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/voice",
            json={"tenant_id": str(tenant_id), "voice_id": "bulbul:v2"},
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code in (401, 403), response.text
    assert await _stored_voice(tenant_id, agent_id) == before, "a refused write wrote nothing"


async def test_an_admin_can_set_the_voice_and_it_is_persisted_and_audited() -> None:
    """The happy path, and the two things that make it trustworthy: the row changed,
    and there is an append-only record of who changed it (hard rules 4 and 5)."""
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()
    assert await _stored_voice(tenant_id, agent_id) == (None, None), "wizard sets no voice"

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/voice",
            json={"tenant_id": str(tenant_id), "voice_id": "bulbul:v2"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["voice"]["id"] == "bulbul:v2"
    assert body["voice"]["tier"] == "value"
    assert body["engine_synced"] is False, "this endpoint never talks to the engine"
    # A draft agent has no engine_agent_ref, so there is nothing to republish yet.
    assert body["published"] is False
    assert body["republish_required"] is False

    # The provider rides along: the adapter sends provider + voice as one object, and
    # a voice with a NULL provider is a half-configured synthesizer.
    assert await _stored_voice(tenant_id, agent_id) == ("bulbul:v2", "sarvam")

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type, object_id FROM audit_log "
                    "WHERE action = 'agent.voice_set' AND tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert row is not None, "an unaudited config change to a client's agent is a rule-5 gap"
    assert row[0] == "admin"
    assert row[1] == "agent"
    assert str(row[2]) == str(agent_id)


async def test_a_published_agent_is_told_the_change_needs_a_republish() -> None:
    """`publish_agent` re-reads `tts_voice` from the row, so the engine only learns
    about this on the NEXT publish. Saying otherwise on the admin screen would be a
    lie the client hears on their phone line."""
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": f"fakeagent_vox_{uuid.uuid4().hex[:8]}", "a": agent_id},
        )

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/voice",
            json={"tenant_id": str(tenant_id), "voice_id": "bulbul:v3"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_status"] == "live"
    assert body["published"] is True
    assert body["republish_required"] is True
    assert body["engine_synced"] is False
    assert "publish" in body["next_step"].lower()
    assert await _stored_voice(tenant_id, agent_id) == ("bulbul:v3", "sarvam")


async def test_an_unknown_voice_id_is_refused_with_a_named_problem() -> None:
    """The reason the catalog exists: the refusal happens BEFORE the row is written, so
    a typo can never become a broken call. RFC-9457, and the code is switchable."""
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}/voice",
            json={"tenant_id": str(tenant_id), "voice_id": "elevenlabs:rachel"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["type"].endswith("/unknown_voice")
    assert problem["kind"] == "business_rule"
    assert problem["retryable"] is False
    assert problem["fields"][0]["field"] == "voice_id"
    # The remediation names the real options, so the caller can fix it without docs.
    assert all(vid in problem["remediation"] for vid in voice_ids())

    assert await _stored_voice(tenant_id, agent_id) == (None, None), "nothing was written"


async def test_setting_the_voice_of_another_tenants_agent_is_a_404() -> None:
    """The write runs inside the named tenant's RLS scope, so an agent belonging to
    somebody else matches zero rows. Under RLS "not found" and "not yours" are the same
    answer, deliberately (hard rule 1)."""
    tenant_a, agent_a, _slug_a, _token_a = await _tenant()
    tenant_b, _agent_b, _slug_b, _token_b = await _tenant()
    admin_token = await _admin_token()

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_a}/voice",
            json={"tenant_id": str(tenant_b), "voice_id": "bulbul:v3"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 404, response.text
    assert await _stored_voice(tenant_a, agent_a) == (None, None), "tenant A is untouched"
