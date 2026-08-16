"""The voice catalog: the allowlist, the admin-only write, and the read that shows it.

Three things are under test and they are not the same thing.

1. **The catalog is data we can stand behind.** D-36 locks a premium/value ladder
   (Bulbul v3 default, v2 as the value tier), so a catalog missing either rung has
   drifted from the decision. Every entry must validate against its own lookup —
   an entry the validator would refuse is a voice the UI offers and the API rejects.

2. **An unknown string never reaches an agent row.** That is the entire point:
   `agents.tts_voice` is free text whose next reader is a vendor API, so "typo stored,
   discovered at call time on a client's line" is the failure mode being closed.

3. **CONFIGURED IS NOT LIVE, and the read says both.** `set_agent_voice` writes our row
   and does not touch the engine, so between a voice change and the next publish the
   agent is configured for one voice and speaking another. The write shipped with no
   read at all, so a picker could set a voice and never show one — and the moment a read
   existed, answering it with `tts_voice` alone would have shipped the "one number
   called the voice" defect that `live_prompt_id` was added to fix for the script.
   `agents.live_tts_voice` (migration c8b3f14e7a29) is the second answer, written by
   `publish_agent` from the config it actually sent, and
   `GET /v1/agents/{agent_id}/pending` carries both.

The router is deliberately NOT mounted in `main.py`, so the HTTP tests mount it here —
and mount it AHEAD of `agents.routes.router`, which is the order the real app must use
(`/v1/agents/{agent_id}` otherwise eats the literal `voices`). Running the boot
assertion over the assembled app keeps that contract honest: if either route ever loses
its `permission_meta`, mounting it anywhere starts failing.

THE WRITE MOVED to `PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice`, with
the tenant in the path instead of the body — it was the one admin-realm route left in
the client path space, which cost it the `/v1/admin` rate-limit profile and an audit
trail readable from the URL. `tests/route_shape_test.py` asserts the rule over the
whole route table and that the old path is gone; the cases below are the behaviour.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing
from apps.api.agents.publishing_routes import router as publishing_router
from apps.api.agents.routes import router as agents_router
from apps.api.agents.service import publish_agent
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
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    # ORDER IS THE CONTRACT: the literal `/v1/agents/voices` and `/v1/agents/{id}/pending`
    # must be declared before `/v1/agents/{agent_id}`, or FastAPI matches the
    # parameterised route first and answers 422 about a UUID nobody sent.
    application.include_router(voice_router)
    application.include_router(publishing_router)
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
        # A SCRIPT, because publishing without one is now refused by name
        # (`agent_has_no_script`): the wizard mints the receptionist row before step 3,
        # and `publish_agent` no longer substitutes a hardcoded English placeholder for
        # the client's own prompt. This suite is about voices, so it needs the agent to
        # be publishable at all rather than to be about scripts.
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=UUID(str(agent_id)),
            body="[IDENTITY]\nYou are the receptionist for Voice Clinic.\n",
            notes=None,
            created_by=None,
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


async def _set_voice(tenant_id: uuid.UUID, agent_id: uuid.UUID, voice_id: str) -> dict[str, object]:
    """The admin write, over HTTP — the only supported way a voice reaches a row."""
    admin_token = await _admin_token()
    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": voice_id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> FakeEngine:
    """Push the agent onto the fake engine, which is what writes the live mirror.

    Returns the engine THIS publish used, and the caller must rebind it: the cache reset
    mints a fresh `FakeEngine` with an empty agent store, so a variable held across two
    publishes would be reading the first engine's memory of a config the second one was
    sent. The ref is a stable hash of the ids, so the same key indexes both.
    """
    reset_engine_cache()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return engine


@contextmanager
def _dictating_engine() -> Iterator[FakeEngine]:
    """Run the block against an engine that SUPPLIES ITS OWN VOICES.

    The same `FakeEngine` class with a different capability descriptor — no speculative
    adapter and no imagined vendor API, because every difference that matters here is an
    ANSWER rather than an endpoint (`fake.DICTATED_SPEECH_CAPABILITIES`).

    It reaches into `apps.api.engine`'s instance cache because that is what the route
    resolves through, and it restores the cache afterwards so the next test gets the
    ordinary BYOK engine back — a leaked descriptor would make an unrelated suite fail
    somewhere far from here.
    """
    import apps.api.engine as engine_module

    engine = FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)
    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = engine
    try:
        yield engine
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


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
    Also pins the mount order — a 422 here means the router was mounted too late.

    The response is an ENVELOPE, not a bare list (D-93). On an engine that supplies its
    own voices the honest answer is "no selection here, and that is normal", and a bare
    list can only say that with `[]` — which the console renders as "this agent has no
    voices available", a claim about the product rather than about the engine. So the
    verdict travels beside the rows: `selectable` and `control` say whether choosing is
    possible at all, and `note` is the sentence a surface prints either way.
    """
    _tenant_id, _agent_id, slug, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.get(
            "/v1/agents/voices",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    # `ENGINE=fake` in tests, and the fake adapter is BYOK on every leg, so the full
    # catalog is offerable here — which is also Bolna's answer (`BOLNA_CAPABILITIES`).
    assert body["control"] == "ours"
    assert body["selectable"] is True
    assert body["note"]
    assert len(body["voices"]) == len(CATALOG)
    assert {entry["id"] for entry in body["voices"]} == set(voice_ids())
    assert {entry["tier"] for entry in body["voices"]} == {"premium", "value"}


async def test_the_catalog_is_closed_and_the_write_refused_when_the_engine_dictates_tts() -> None:
    """The TTS answer for an engine that supplies its own voices (D-93).

    Both halves are asserted together because the failure this prevents is precisely the
    two halves disagreeing: a picker built from a catalog the write endpoint will refuse.
    `selectable: false` with an EMPTY `voices` and a `note` is the whole contract — a
    surface that renders the note says something true and calm, and one that renders the
    (empty) list has nothing to offer, which is now the correct outcome rather than an
    accident that reads as a broken product.

    The refusal names the capability rather than the voice: on such an engine there is no
    voice id that would have worked, so `unknown_voice` would send an operator hunting
    for the right string forever.
    """
    tenant_id, agent_id, slug, token = await _tenant()
    admin_token = await _admin_token()
    before = await _stored_voice(tenant_id, agent_id)

    with _dictating_engine():
        async with _client(_app()) as http:
            catalogue = await http.get(
                "/v1/agents/voices",
                headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
            )
            write = await http.patch(
                f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
                json={"voice_id": "bulbul:v3"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )

    assert catalogue.status_code == 200, catalogue.text
    listing = catalogue.json()
    assert listing["selectable"] is False
    assert listing["control"] == "engine"
    assert listing["voices"] == [], "a voice this engine cannot speak is not an option"
    assert "supplies its own voices" in listing["note"]

    assert write.status_code >= 400, write.text
    problem = write.json()
    assert problem["type"].rsplit("/", 1)[-1] == "engine_capability_absent"
    assert problem["remediation"], "an operator must be told what to do instead"
    # Nothing was written. A refusal that still stored the voice would leave the row
    # claiming a voice no caller will ever hear — the exact state this refuses to create.
    assert await _stored_voice(tenant_id, agent_id) == before


async def test_a_client_realm_principal_cannot_set_the_voice() -> None:
    """D-21's boundary: clients read, admins change engine-facing config. The realms do
    not share session logic (TRD §11), so a client token is not an admin token even for
    an owner — and the agent row must be untouched afterwards.

    `in (401, 403)` USED TO BE THE ASSERTION and it accepted two different worlds: 401 is
    "wrong realm" and 403 is "right realm, missing permission". It is now the exact
    answer, with a POSITIVE CONTROL beside it — the same token is accepted on the
    client-realm voice READ in the same breath — so the refusal cannot be a broken or
    expired credential, which is the only thing a bare 401 proves on its own.

    **WHAT THIS TEST STILL CANNOT SEE, MEASURED RATHER THAN ASSUMED.** Changing
    `VoiceSetter` to `realm="client"` and re-running this case leaves it GREEN, because
    the handler also takes `session: AdminSession`, and `core.deps.admin_db` depends on
    `current_admin` — so the client token meets a second, identical 401 from the session
    dependency. That is a real backstop rather than a coincidence (every admin-realm
    handler in this repo opens `admin_db` or `tenant_session` under an admin principal),
    but it means no request-level assertion can distinguish "this route declares
    `realm="admin"`" from "this route happens to need an admin session".

    So the DECLARATION is pinned where it can be read directly:
    `route_shape_test::test_no_route_in_the_admin_path_space_admits_a_client_realm_principal`
    walks the live route table and fails on exactly that downgrade — verified by making
    it and watching that assertion, and only that assertion, name this path.
    """
    tenant_id, agent_id, slug, token = await _tenant()
    before = await _stored_voice(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": "bulbul:v2"},
            headers=headers,
        )
        # The catalogue read D-21 deliberately leaves open to a client, on the same
        # credential: if THIS fails the token is simply not working and the refusal above
        # is evidence of nothing.
        control = await http.get("/v1/agents/voices", headers=headers)

    assert control.status_code == 200, (
        f"the control failed: this client token is not usable at all ({control.text}), "
        "so the refusal below proves nothing about realms"
    )
    assert response.status_code == 401, response.text
    body = response.json()
    assert body["kind"] == "auth", body
    assert "realm" in body["detail"].lower(), body
    assert await _stored_voice(tenant_id, agent_id) == before, "a refused write wrote nothing"


async def test_an_admin_can_set_the_voice_and_it_is_persisted_and_audited() -> None:
    """The happy path, and the two things that make it trustworthy: the row changed,
    and there is an append-only record of who changed it (hard rules 4 and 5)."""
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()
    assert await _stored_voice(tenant_id, agent_id) == (None, None), "wizard sets no voice"

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": "bulbul:v2"},
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
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": "bulbul:v3"},
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
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": "elevenlabs:rachel"},
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
            f"/v1/admin/tenants/{tenant_b}/agents/{agent_a}/voice",
            json={"voice_id": "bulbul:v3"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 404, response.text
    assert await _stored_voice(tenant_a, agent_a) == (None, None), "tenant A is untouched"


# --- CONFIGURED vs LIVE (migration c8b3f14e7a29) ------------------------------
#
# The gap this closes: the write existed and no read did, so the picker that set a
# voice could not display one. What makes it more than a getter is that there are TWO
# answers — the voice on the row and the voice the engine is holding — and they are
# allowed to differ. Every test below pins one of the states they can be in.


async def test_the_read_returns_the_voice_the_write_just_set() -> None:
    """The plain closing of the gap: set it, read it back, get the same voice.

    On an unpublished agent `live` is null and `republish_required` is False — there is
    no engine object and therefore no caller to mislead. That is a different null from
    the published case below, which is why `published` is asserted alongside it.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.configured is None, "the onboarding wizard sets no voice"
    assert state.voice.headline == "No voice has been set on this agent."

    await _set_voice(tenant_id, agent_id, "bulbul:v2")

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.configured is not None
    assert state.voice.configured.voice_id == "bulbul:v2"
    assert state.voice.configured.provider == "sarvam"
    assert state.voice.configured.catalog is not None
    assert state.voice.configured.catalog.tier == "value", "the picker renders the tier"
    assert state.published is False
    assert state.voice.live is None
    assert state.voice.republish_required is False


async def test_publishing_records_the_voice_the_engine_was_actually_sent() -> None:
    """`publish_agent` is the only place a voice reaches the engine, so it is the only
    place that can say what the engine has. The mirror is asserted against what the
    FAKE ENGINE received, not against the row it was copied from — a mirror checked
    against its own source proves nothing."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, "bulbul:v3")
    engine = await _publish(tenant_id, agent_id)

    ref = next(iter(engine._agents))
    assert engine._agents[ref].models.tts_voice == "bulbul:v3"

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.published is True
    assert state.voice.live is not None
    assert state.voice.live.voice_id == "bulbul:v3"
    assert state.voice.live.provider == "sarvam"
    assert state.voice.republish_required is False
    assert "Callers hear" in state.voice.headline


async def test_a_change_after_a_publish_moves_configured_and_leaves_live_alone() -> None:
    """THE TEST THIS SLICE EXISTS FOR: the read reports what the write set AND what the
    caller is still hearing, at the same time.

    Answering with one value here — either one — is the defect. `tts_voice` alone would
    tell an operator the new voice is in force on a live phone line that is still
    speaking the old one; `live_tts_voice` alone would hide the change they just made.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, "bulbul:v3")
    engine = await _publish(tenant_id, agent_id)
    ref = next(iter(engine._agents))

    written = await _set_voice(tenant_id, agent_id, "bulbul:v2")
    assert written["published"] is True
    assert written["republish_required"] is True
    assert written["live_voice_id"] == "bulbul:v3", "the write reports what callers hear"
    assert written["engine_synced"] is False
    assert "publish" in str(written["next_step"]).lower()

    # The engine still holds the old voice — the whole reason the two columns exist.
    assert engine._agents[ref].models.tts_voice == "bulbul:v3"

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.configured is not None and state.voice.configured.voice_id == "bulbul:v2"
    assert state.voice.live is not None and state.voice.live.voice_id == "bulbul:v3"
    assert state.voice.republish_required is True
    assert "Callers still hear" in state.voice.headline
    # The voice is NOT reported through `pending`/Apply: that list is version numbers
    # and Undo cannot undo a voice. A publish closes this, and the headline says so.
    assert [change.field for change in state.pending] == []
    assert state.has_pending is False

    # And a republish closes it, with no other step.
    engine = await _publish(tenant_id, agent_id)
    assert engine._agents[ref].models.tts_voice == "bulbul:v2"
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.live is not None and state.voice.live.voice_id == "bulbul:v2"
    assert state.voice.republish_required is False


async def test_re_selecting_the_voice_the_engine_already_holds_asks_for_no_republish() -> None:
    """`republish_required` used to be `== published`, so an operator who re-picked the
    running voice was told to publish for nothing. With the mirror the answer is a
    measurement: same voice, same engine, no work. A screen that cries wolf about a
    divergence is a screen nobody reads when there is one."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, "bulbul:v3")
    await _publish(tenant_id, agent_id)

    written = await _set_voice(tenant_id, agent_id, "bulbul:v3")

    assert written["published"] is True
    assert written["live_voice_id"] == "bulbul:v3"
    assert written["republish_required"] is False
    assert "nothing to publish" in str(written["next_step"])

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.republish_required is False


async def test_a_published_agent_with_no_recorded_live_voice_still_asks_for_a_republish() -> None:
    """The legacy row: published before the mirror existed, so `live_tts_voice` is NULL
    and we cannot PROVE what the engine holds. That resolves towards "publish again",
    never towards a claim of sync — the only direction of error a statement about a
    live phone line may have. It self-heals on the next publish."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": f"fakeagent_legacy_{uuid.uuid4().hex[:8]}", "a": agent_id},
        )

    written = await _set_voice(tenant_id, agent_id, "bulbul:v2")
    assert written["live_voice_id"] is None
    assert written["republish_required"] is True

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.published is True
    assert state.voice.live is None
    assert state.voice.republish_required is True
    # The headline distinguishes "we do not know" from "nothing is live", because the
    # remedy is the same but the sentence a client reads is not.
    assert "no record of which" in state.voice.headline


async def test_a_voice_outside_the_catalog_reads_back_as_itself() -> None:
    """The column is free text and the allowlist lives at the API, so a row can hold a
    voice we no longer offer. It must read back as an id we cannot describe — NOT as
    "no voice", which would send an operator to set a voice that is already set."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET tts_voice = 'bulbul:v1', tts_provider = 'sarvam' WHERE id = :a"
            ),
            {"a": agent_id},
        )

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.voice.configured is not None
    assert state.voice.configured.voice_id == "bulbul:v1"
    assert state.voice.configured.catalog is None, "we do not offer it, so we cannot describe it"
    assert "bulbul:v1" in state.voice.headline, "named by its id rather than silently dropped"


async def test_a_client_can_read_which_voice_their_own_agent_speaks_in() -> None:
    """Client-realm `agents:read`, and that is the deliberate answer to "is this client
    information?".

    A client is legally the Principal Entity and already reads the catalogue for the
    reason `list_voices` states — they get to hear what their agent sounds like. D-36's
    ladder is also a PRICE ladder (premium and value bill at different rates,
    SURFACES §2b's honest degraded-tier billing), so a client billed by rung must be
    able to read the rung. What stays admin-only is the WRITE (D-21), which
    `test_a_client_realm_principal_cannot_set_the_voice` pins.
    """
    tenant_id, agent_id, slug, token = await _tenant()
    await _set_voice(tenant_id, agent_id, "bulbul:v2")

    async with _client(_app()) as http:
        response = await http.get(
            f"/v1/agents/{agent_id}/pending",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    voice = response.json()["voice"]
    assert voice["configured"]["voice_id"] == "bulbul:v2"
    assert voice["configured"]["catalog"]["tier"] == "value"
    assert voice["live"] is None
    assert voice["republish_required"] is False
    assert voice["headline"]


async def test_a_second_tenant_cannot_read_or_write_the_live_voice_columns() -> None:
    """The cross-tenant zero-rows test that ships with migration c8b3f14e7a29. Both new
    columns are read AND written from a second tenant's RLS scope; a column is not a
    separate security object, and this is where that claim gets checked (hard rule 1)."""
    tenant_a, agent_a, _slug_a, _token_a = await _tenant()
    await _set_voice(tenant_a, agent_a, "bulbul:v3")
    await _publish(tenant_a, agent_a)
    other_id, _other_agent, _slug_b, _token_b = await _tenant()

    async with tenant_session(other_id) as session:
        rows = (
            await session.execute(
                text("SELECT live_tts_voice, live_tts_provider FROM agents WHERE id = :aid"),
                {"aid": agent_a},
            )
        ).all()
        assert rows == [], "another tenant read the live voice off our agent"

        written = await session.execute(
            text(
                "UPDATE agents SET live_tts_voice = 'bulbul:v2', live_tts_provider = 'nobody' "
                "WHERE id = :aid"
            ),
            {"aid": agent_a},
        )
        assert written.rowcount == 0, "another tenant wrote the live voice on our agent"

    # And the victim's row is untouched.
    state = await publishing.pending_state_for(tenant_id=tenant_a, agent_id=agent_a)
    assert state.voice.live is not None and state.voice.live.voice_id == "bulbul:v3"


async def test_the_pending_read_of_a_foreign_agent_carries_no_voice_at_all() -> None:
    """Reading someone else's agent is `not_found`, not a stripped-down payload — under
    RLS the row is invisible, so there is nothing to partially disclose."""
    _tenant_a, agent_a, _slug_a, _token_a = await _tenant()
    await _set_voice(_tenant_a, agent_a, "bulbul:v3")
    _tenant_b, _agent_b, slug_b, token_b = await _tenant()

    async with _client(_app()) as http:
        response = await http.get(
            f"/v1/agents/{agent_a}/pending",
            headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b},
        )

    assert response.status_code == 404, response.text
    assert "bulbul" not in response.text
