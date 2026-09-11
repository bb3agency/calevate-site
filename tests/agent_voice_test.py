"""The voice catalog: the allowlist, the two write doors, and the read that shows both.

Three things are under test and they are not the same thing.

1. **The catalog is data we can stand behind.** The single-tier voice decision locks ONE
   voice quality (Sarvam Bulbul v3) — no premium/value ladder — while keeping the persona
   dimension for future speakers. Every entry must validate against its own lookup — an
   entry the validator would refuse is a voice the UI offers and the API rejects.

2. **An unknown string never reaches an agent row.** That is the entire point:
   `agents.tts_voice` is free text whose next reader is a vendor API, so "typo stored,
   discovered at call time on a client's line" is the failure mode being closed.

3. **CONFIGURED IS NOT LIVE, and the read says both.** ⚠ **D-586 CHANGED WHEN THE TWO
   CONVERGE AND THIS PARAGRAPH USED TO SAY THE OPPOSITE.** The write now re-publishes a
   LIVE agent in the same transaction, so on a live agent they converge on the write
   itself; they remain two facts on a draft agent (nothing is on the engine), on a PAUSED
   one (an engine object still holds the old voice, and a voice write deliberately does
   not republish it — `publish_agent` writes `status = 'live'`) and on one published
   before the mirror existed. Answering with `tts_voice` alone would still be the "one
   number called the voice" defect that `live_prompt_id` was added to fix for the script.
   `agents.live_tts_voice` (migration c8b3f14e7a29) is the second answer, written by
   `publish_agent` from the config it actually sent, and
   `GET /v1/agents/{agent_id}/pending` carries both.

   The CLIENT-REALM half of this — the owner and their staff writing their own agent's
   voice and cap, and the engine push and its failure path — lives in
   `tests/agent_settings_live_edit_test.py`. What stays here is the catalogue, the
   allowlist and the admin door.

The router is deliberately NOT mounted in `main.py`, so the HTTP tests mount it here —
and mount it AHEAD of `agents.routes.router`, which is the order the real app must use
(`/v1/agents/{agent_id}` otherwise eats the literal `voices`). Running the boot
assertion over the assembled app keeps that contract honest: if either route ever loses
its `permission_meta`, mounting it anywhere starts failing.

THE ADMIN WRITE lives at `PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice`,
with the tenant in the path instead of the body — it was the one admin-realm route left
in the client path space, which cost it the `/v1/admin` rate-limit profile and an audit
trail readable from the URL. Since D-586 there is ALSO a client door at
`PATCH /v1/agents/{agent_id}/voice`, which is a different route rather than the old one
restored: client realm, no tenant in it at all. `tests/route_shape_test.py` asserts the
rule the move established — no ADMIN-realm route in the client path space — over the
whole route table; the cases below are the behaviour.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing, voice_routes
from apps.api.agents import voices as voices_module
from apps.api.agents.publishing_routes import router as publishing_router
from apps.api.agents.routes import router as agents_router
from apps.api.agents.service import publish_agent
from apps.api.agents.voice_offer import (
    NO_CARTESIA_CREDENTIAL_REASON,
    client_unofferable_reason,
)
from apps.api.agents.voice_routes import router as voice_router
from apps.api.agents.voices import (
    DEFAULT_SPEAKER,
    DEFAULT_VOICE_ID,
    VoiceSelectionCapability,
    catalogue,
    default_voice,
    get_voice,
    is_supported_voice,
    voice_ids,
)
from apps.api.billing.rates import voice_tier_label
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

# The catalogue id every test in this file writes. Named rather than typed 20 times: it is
# `<tts_model>:<speaker>` now (D-358's second half), and the whole point of the split is
# that the id, the model and the speaker are three different strings.
VOICE_ID = DEFAULT_VOICE_ID


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
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]

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
    return tenant_id, agent_id, str(slug), f"dev:client:{user_id}"


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
    assert catalogue(), "an empty catalog makes the voice picker unusable"
    for voice in catalogue():
        assert is_supported_voice(voice.id), f"{voice.id} is offered but not accepted"
        assert get_voice(voice.id) == voice
        assert voice.id in voice_ids()
        assert voice.provider in ("sarvam", "cartesia"), "the two tiers D-547 declares"
        assert voice.label.strip(), "a voice with no label cannot be picked by a human"
        assert "te-IN" in voice.languages, "Telugu-first: a voice without Telugu is not ours"
        assert voice.languages[0] == "te-IN", "Telugu leads the list a picker renders"


def test_the_catalog_carries_no_tier_field_and_no_sarvam_ladder() -> None:
    """**"ONE VOICE QUALITY" WAS THIS TEST'S CLAIM AND D-547 RETIRED IT** — the tier
    dimension came back as a second PROVIDER (Cartesia `sonic-3.5`), chosen per agent and
    priced per credit lot. What did NOT come back is the old premium/value LADDER inside
    Sarvam: Bulbul v2 stays withdrawn, and there is still no `tier` FIELD, because the tier
    is `provider` and a second spelling is where the two would come to disagree.

    The Sarvam half of the catalogue is still exactly one model. The Cartesia half is empty
    today by design (`voices.CARTESIA_CATALOG_SOURCE` — no id here has been read from the
    vendor), which `tests/voice_tier_test.py` is the file about.
    """
    assert {v.tts_model for v in catalogue() if v.provider == "sarvam"} == {"bulbul:v3"}
    assert not hasattr(default_voice(), "tier"), "the tier dimension is never a field"
    assert default_voice().tts_model == "bulbul:v3"
    assert default_voice().provider == "sarvam", "Cartesia is chosen, never inherited (Q9)"
    # v2 is no longer a voice we offer.
    assert get_voice("bulbul:v2:anushka") is None
    assert not is_supported_voice("bulbul:v2:anushka")


def test_an_unknown_voice_id_is_not_supported() -> None:
    """Exact match, no normalisation: the stored string is pasted into a vendor request
    verbatim, so a near-miss is as wrong as a typo."""
    for unknown in ("", "bulbul", "bulbul:v3", "bulbul:v4", "BULBUL:V3:ASHUTOSH", "ashutosh"):
        assert not is_supported_voice(unknown)
        assert get_voice(unknown) is None


def test_no_entry_claims_to_be_pilot_verified() -> None:
    """The docs name no voices and OPERATIONS §2 gate 3 still asks whether Bulbul V3 is
    even selectable on Bolna. Until that gate passes, presenting these ids as verified
    would be inventing fact. When the pilot answers, flip `verified` and this test."""
    assert all(not voice.verified for voice in catalogue())
    assert all(voice.gender is None for voice in catalogue()), "no speaker genders in the docs"


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
    assert len(body["voices"]) == len(catalogue())
    assert {entry["id"] for entry in body["voices"]} == set(voice_ids())
    assert {entry["tts_model"] for entry in body["voices"]} == {"bulbul:v3"}
    assert "tier" not in body["voices"][0], "the tier field was removed from the catalog"
    # EVERY VOICE CARRIES ITS OWN VERDICT (D-547 §4.C.2), never a filtered list: a voice
    # missing from the answer is indistinguishable from a tier this product does not sell,
    # so the picker could not tell an operator which of key / price / cap is still missing.
    assert all(entry["offerable"] is True for entry in body["voices"])
    assert all(entry["unavailable_reason"] is None for entry in body["voices"]), (
        "every Sarvam voice is offerable: its key is the engine account's own, its cost is "
        "on the rate card, and the Cartesia agent cap does not apply to it"
    )


async def test_an_unavailable_voice_is_returned_with_its_reason_never_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**THE PICKER IS NEVER HANDED A SHORTER LIST (D-547 §4.C.2).**

    A Cartesia voice missing from this response is indistinguishable from a Cartesia tier
    this product does not sell — so the operator who pasted the key an hour ago has no way
    to see that the PRICE is what is still missing, and the client who asks for the premium
    voice is told nothing at all. Every voice comes back; `unavailable_reason` says why an
    unavailable one is unavailable, in a sentence naming the ONE action that fixes it.

    The catalogue's own Cartesia half is empty today (no voice id in this tree has been read
    from the vendor), so the case is driven through the capability seam the route already
    reads — which is also the only place a surface could have filtered.
    """
    _tenant_id, _agent_id, slug, token = await _tenant()
    cartesia = voices_module._cartesia_entry(
        voices_module.CartesiaVoiceRecord(
            id="test-record-not-a-real-voice-id", name="Test Persona", languages=("te-IN",)
        )
    )
    real = voice_routes.voice_selection_capability

    def with_cartesia(engine: object | None = None) -> VoiceSelectionCapability:
        capability = real()
        return replace(capability, voices=(*capability.voices, cartesia))

    monkeypatch.setattr(voice_routes, "voice_selection_capability", with_cartesia)

    async with _client(_app()) as http:
        response = await http.get(
            "/v1/agents/voices",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    rows = {entry["id"]: entry for entry in response.json()["voices"]}
    assert cartesia.id in rows, "the unavailable voice was dropped instead of explained"
    assert rows[cartesia.id]["offerable"] is False
    assert rows[DEFAULT_VOICE_ID]["offerable"] is True
    # THE SENTENCE IS THE CLIENT'S, because the caller is one — the operator ground names
    # the vendor and the setting that fixes it, and this route is readable in both realms.
    # `test_the_refusal_a_client_reads_names_neither_the_vendor_nor_our_settings` below is
    # the case about that; here it is enough that the operator ground did not travel.
    assert rows[cartesia.id]["unavailable_reason"] == client_unofferable_reason(cartesia)
    assert rows[cartesia.id]["unavailable_reason"] != NO_CARTESIA_CREDENTIAL_REASON


async def test_the_refusal_a_client_reads_names_neither_the_vendor_nor_our_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**THE LEAK, ON THE WIRE.** Every one of `voice_offer`'s three grounds names Cartesia
    and two name a field only we can edit (`cartesia_api_key`, `cartesia_agent_cap`) — and
    this endpoint is `agents:read`, which a CLIENT holds. So the sentence forks by realm
    (`voice_routes._reason_audience`), the way `agents/llm_routes.py` already forks a
    blocked model's reason: the operator keeps the ground they can fix, the client is told
    the one action they have, in the tier's own client-facing name.

    The CLIENT half is asserted over HTTP because that is where the leak would happen; the
    operator half is `test_the_reason_audience_is_the_realm` below, which drives the fork
    directly — an admin principal reaches this path only by impersonation
    (`core/auth.current_any`), and minting a view-as grant here would test the grant flow
    rather than the fork.
    """
    _tenant_id, _agent_id, slug, token = await _tenant()
    cartesia = voices_module._cartesia_entry(
        voices_module.CartesiaVoiceRecord(
            id="test-record-not-a-real-voice-id", name="Test Persona", languages=("te-IN",)
        )
    )
    real = voice_routes.voice_selection_capability

    def with_cartesia(engine: object | None = None) -> VoiceSelectionCapability:
        capability = real()
        return replace(capability, voices=(*capability.voices, cartesia))

    monkeypatch.setattr(voice_routes, "voice_selection_capability", with_cartesia)

    async with _client(_app()) as http:
        response = await http.get(
            "/v1/agents/voices",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    row = {entry["id"]: entry for entry in response.json()["voices"]}[cartesia.id]
    reason = row["unavailable_reason"]

    assert reason == client_unofferable_reason(cartesia)
    assert voice_tier_label(cartesia.provider) in reason
    for ours in ("cartesia", "sarvam", "cartesia_api_key", "cartesia_agent_cap", "ops console"):
        assert ours not in reason.lower(), f"{ours!r} crossed the wire to a client"
    # OFFERABILITY ITSELF DID NOT FORK — only the sentence did. A client sees the same row,
    # refused, with the same tier name; what changed is whose language the refusal is in.
    assert row["offerable"] is False
    assert row["tier_label"] == voice_tier_label(cartesia.provider)


def test_the_reason_audience_is_the_realm_and_impersonation_does_not_change_it() -> None:
    """WHO gets the operator ground, decided from the realm and nothing else.

    An impersonating admin (D-22, read-only) is an OPERATOR here, which is the opposite of
    the call `llm_routes` makes — and deliberately: that endpoint has one route per realm,
    while this one is shared, and `current_any` lets an admin principal through only WITH
    the impersonation header. So the admin console's own voice picker arrives impersonating,
    and reading that as a client would delete the actionable ground from the only screen an
    operator installs a Cartesia key from.
    """
    admin = Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="superadmin")
    viewing = replace(admin, tenant_id=uuid.uuid4(), impersonating=True)
    client = Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")

    assert voice_routes._reason_audience(admin) == "operator"
    assert voice_routes._reason_audience(viewing) == "operator"
    assert voice_routes._reason_audience(client) == "client"


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
                json={"voice_id": VOICE_ID},
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


async def test_a_client_token_is_refused_on_the_admin_door_and_accepted_on_its_own() -> None:
    """The realms do not share session logic (TRD §11), so a client token is not an admin
    token even for an owner — and that survived D-586 opening a client door beside it.

    ⚠ **THIS TEST USED TO BE `test_a_client_realm_principal_cannot_set_the_voice` AND
    ASSERTED THE FEATURE THAT NOW EXISTS.** D-21's "clients read, admins change
    engine-facing config" was the ground, and the founder withdrew it for this class of
    setting: a voice is delivery on the client's own phone line. What is still true — and
    is the half worth a test — is that the ADMIN path is admin-only. Two positive controls
    sit beside the refusal so it cannot be a broken credential: the same token reads the
    catalogue AND writes the voice on the client route.

    `in (401, 403)` USED TO BE THE ASSERTION and it accepted two different worlds: 401 is
    "wrong realm" and 403 is "right realm, missing permission". It is the exact answer.

    **WHAT THIS TEST CANNOT SEE, MEASURED RATHER THAN ASSUMED.** Changing
    `AdminVoiceSetter` to `realm="client"` and re-running this case leaves it GREEN,
    because the handler also takes `session: AdminSession`, and `core.deps.admin_db`
    depends on `current_admin` — so the client token meets a second, identical 401 from
    the session dependency. So the DECLARATION is pinned where it can be read directly:
    `route_shape_test::test_no_route_in_the_admin_path_space_admits_a_client_realm_principal`
    walks the live route table and fails on exactly that downgrade.
    """
    tenant_id, agent_id, slug, token = await _tenant()
    before = await _stored_voice(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": VOICE_ID},
            headers=headers,
        )
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

    # THE POSITIVE CONTROL THAT MAKES THE REFUSAL MEAN SOMETHING NARROW: the same owner,
    # the same token, their own agent, on their own route. If this ever fails the refusal
    # above has stopped being about the PATH and started being about the client realm.
    async with _client(_app()) as http:
        allowed = await http.patch(
            f"/v1/agents/{agent_id}/voice", json={"voice_id": VOICE_ID}, headers=headers
        )
    assert allowed.status_code == 200, allowed.text
    assert await _stored_voice(tenant_id, agent_id) == (VOICE_ID, "sarvam")


async def test_an_admin_can_set_the_voice_and_it_is_persisted_and_audited() -> None:
    """The happy path, and the two things that make it trustworthy: the row changed,
    and there is an append-only record of who changed it (hard rules 4 and 5)."""
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()
    assert await _stored_voice(tenant_id, agent_id) == (None, None), "wizard sets no voice"

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": VOICE_ID},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["voice"]["id"] == VOICE_ID
    assert body["voice"]["tts_model"] == "bulbul:v3"
    # A DRAFT agent has no `engine_agent_ref`, so there is nothing on the platform to
    # update and nothing to republish. `engine_synced` is a measurement now (D-586), not
    # the hard-coded False it used to be — `test_a_live_agent_is_re_voiced_on_the_spot`
    # is the other arm.
    assert body["engine_synced"] is False
    assert body["published"] is False
    assert body["republish_required"] is False
    assert body["changed"] is True

    # The provider rides along: the adapter sends provider + voice as one object, and
    # a voice with a NULL provider is a half-configured synthesizer.
    assert await _stored_voice(tenant_id, agent_id) == (VOICE_ID, "sarvam")

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


async def test_a_live_agent_is_re_voiced_on_the_spot() -> None:
    """⚠ **THIS TEST USED TO BE `test_a_published_agent_is_told_the_change_needs_a_republish`
    AND ASSERTED THE OPPOSITE.** `set_agent_voice` re-published nothing, so the engine
    only learned about a voice on the next publish and the response said so. D-586 made
    the write reach the engine in the same transaction; the sentence that justified the
    old behaviour — "saying otherwise on the admin screen would be a lie the client hears
    on their phone line" — is now the argument FOR this one, because the row is what would
    have been lying.
    """
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()
    reset_engine_cache()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    ref = f"fakeagent_vox_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": VOICE_ID},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_status"] == "live"
    assert body["published"] is True
    assert body["engine_synced"] is True, "a live agent's voice must reach the platform"
    assert body["republish_required"] is False, "nothing is left to publish"
    assert "next call" in body["next_step"].lower()
    assert await _stored_voice(tenant_id, agent_id) == (VOICE_ID, "sarvam")
    # THE ENGINE ITSELF, not our mirror of it: the mirror is written by the same function
    # that made the call, so asserting only on the column would pass against a publish
    # that never happened.
    assert engine._agents[ref].models.tts_voice == DEFAULT_SPEAKER


async def test_an_engine_refusal_leaves_the_row_and_the_engine_agreeing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure path, which is the whole reason the push is INSIDE the transaction.

    Six live refusals in one day is the observed rate this is written against. If the
    platform 400s, the column write must roll back with it — otherwise the row says one
    voice, the phone line speaks another, and no screen in the product can tell.
    """
    tenant_id, agent_id, _slug, _client_token = await _tenant()
    admin_token = await _admin_token()
    reset_engine_cache()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    ref = f"fakeagent_vox_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    before = await _stored_voice(tenant_id, agent_id)

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
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
            json={"voice_id": VOICE_ID},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code >= 400, response.text
    assert response.json()["kind"] == "dependency", response.text
    assert await _stored_voice(tenant_id, agent_id) == before, (
        "a refused engine push must roll the column back with it"
    )
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'agent.voice_set' "
                    "AND tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    assert audited == 0, "nothing happened, so the ledger must not say something did"


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
            json={"voice_id": VOICE_ID},
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

    await _set_voice(tenant_id, agent_id, VOICE_ID)

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.configured is not None
    assert state.voice.configured.voice_id == VOICE_ID
    assert state.voice.configured.provider == "sarvam"
    assert state.voice.configured.catalog is not None
    assert state.voice.configured.catalog.tts_model == "bulbul:v3", "the picker renders the voice"
    assert state.published is False
    assert state.voice.live is None
    assert state.voice.republish_required is False


async def test_publishing_records_the_voice_the_engine_was_actually_sent() -> None:
    """`publish_agent` is the only place a voice reaches the engine, so it is the only
    place that can say what the engine has. The mirror is asserted against what the
    FAKE ENGINE received, not against the row it was copied from — a mirror checked
    against its own source proves nothing."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, VOICE_ID)
    engine = await _publish(tenant_id, agent_id)

    ref = next(iter(engine._agents))
    assert engine._agents[ref].models.tts_voice == DEFAULT_SPEAKER

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.published is True
    assert state.voice.live is not None
    assert state.voice.live.voice_id == VOICE_ID
    assert state.voice.live.provider == "sarvam"
    assert state.voice.republish_required is False
    assert "Callers hear" in state.voice.headline


async def test_a_stale_live_voice_is_closed_by_the_next_write_not_left_for_a_publish() -> None:
    """THE TEST THIS SLICE EXISTS FOR, re-aimed by D-586: the read reports the CONFIGURED
    voice AND what the caller is still hearing, and the WRITE now closes the gap.

    There is one voice quality now (the single-tier voice decision), so an operator can no
    longer change to a DIFFERENT catalog voice — but the configured-vs-live machinery still
    has to work when the two diverge for any reason (a legacy publish, drift). Divergence is
    simulated here by writing a stale `live_tts_voice` directly, which is exactly the shape
    a pre-mirror or drifted agent has.

    ⚠ **THIS USED TO ASSERT THAT THE WRITE REPORTED `republish_required: True` AND LEFT THE
    DIVERGENCE STANDING.** It is now the case that proves the re-assertion arm is real:
    `changed` is False (the row already held this voice) and the engine is pushed ANYWAY,
    because `changed` alone would have skipped exactly the agent a second click is trying
    to fix. Answering with one value would still be the defect.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, VOICE_ID)
    engine = await _publish(tenant_id, agent_id)
    ref = next(iter(engine._agents))

    # Simulate the engine holding a stale voice (a legacy/drifted live value), so
    # configured (the split id) and live diverge.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET live_tts_voice = 'bulbul:legacy' WHERE id = :a"),
            {"a": agent_id},
        )
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.republish_required is True, "the read sees the divergence"
    assert "Callers still hear" in state.voice.headline
    # The voice is NOT reported through `pending`/Apply: that list is version numbers
    # and Undo cannot undo a voice.
    assert [change.field for change in state.pending] == []
    assert state.has_pending is False

    written = await _set_voice(tenant_id, agent_id, VOICE_ID)
    assert written["published"] is True
    assert written["changed"] is False, "the row already held this voice"
    assert written["engine_synced"] is True, "the ENGINE did not, which is what matters"
    assert written["live_voice_id"] == VOICE_ID
    assert written["republish_required"] is False

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.configured is not None and state.voice.configured.voice_id == VOICE_ID
    assert state.voice.live is not None and state.voice.live.voice_id == VOICE_ID
    assert state.voice.republish_required is False
    assert engine._agents[ref].models.tts_voice == DEFAULT_SPEAKER


async def test_re_selecting_the_voice_the_engine_already_holds_asks_for_no_republish() -> None:
    """`republish_required` used to be `== published`, so an operator who re-picked the
    running voice was told to publish for nothing. With the mirror the answer is a
    measurement: same voice, same engine, no work. A screen that cries wolf about a
    divergence is a screen nobody reads when there is one."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, VOICE_ID)
    await _publish(tenant_id, agent_id)

    written = await _set_voice(tenant_id, agent_id, VOICE_ID)

    assert written["published"] is True
    assert written["live_voice_id"] == VOICE_ID
    assert written["republish_required"] is False
    assert written["changed"] is False
    assert written["engine_synced"] is False, "the engine already holds it; nothing to send"
    assert "nothing to send" in str(written["next_step"])

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.republish_required is False


async def test_a_paused_agent_is_written_but_not_re_published() -> None:
    """The legacy row AND the paused guard, which are the same row under D-586.

    `live_tts_voice` is NULL — published before the mirror existed, so we cannot PROVE what
    the engine holds — and the agent is PAUSED. Neither fact may be rounded up: the write
    must not republish, because `publish_agent` writes `status = 'live'` and a delivery
    change must never put a switched-off phone line back into service; and the unknown live
    voice must resolve towards "publish again", never towards a claim of sync, which is the
    only direction of error a statement about a live phone line may have.

    ⚠ **THIS USED TO USE `status = 'live'`**, which under D-586 would republish and so
    would no longer be able to observe either property.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'paused' WHERE id = :a"),
            {"r": f"fakeagent_legacy_{uuid.uuid4().hex[:8]}", "a": agent_id},
        )

    written = await _set_voice(tenant_id, agent_id, VOICE_ID)
    assert written["agent_status"] == "paused"
    assert written["engine_synced"] is False, "a paused agent must not be republished"
    assert written["live_voice_id"] is None
    assert written["republish_required"] is True
    assert "not on the frontline" in str(written["next_step"])

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM agents WHERE id = :a"), {"a": agent_id})
        ).scalar_one()
    assert status == "paused", "a voice change must not put a paused agent back on the frontline"

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
    reason `list_voices` states — they get to hear what their agent sounds like. What stays
    admin-only is the WRITE (D-21), which `test_a_client_realm_principal_cannot_set_the_voice`
    pins.
    """
    tenant_id, agent_id, slug, token = await _tenant()
    await _set_voice(tenant_id, agent_id, VOICE_ID)

    async with _client(_app()) as http:
        response = await http.get(
            f"/v1/agents/{agent_id}/pending",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    voice = response.json()["voice"]
    assert voice["configured"]["voice_id"] == VOICE_ID
    assert voice["configured"]["catalog"]["tts_model"] == "bulbul:v3"
    assert voice["live"] is None
    assert voice["republish_required"] is False
    assert voice["headline"]


async def test_a_second_tenant_cannot_read_or_write_the_live_voice_columns() -> None:
    """The cross-tenant zero-rows test that ships with migration c8b3f14e7a29. Both new
    columns are read AND written from a second tenant's RLS scope; a column is not a
    separate security object, and this is where that claim gets checked (hard rule 1)."""
    tenant_a, agent_a, _slug_a, _token_a = await _tenant()
    await _set_voice(tenant_a, agent_a, VOICE_ID)
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
    assert state.voice.live is not None and state.voice.live.voice_id == VOICE_ID


async def test_the_pending_read_of_a_foreign_agent_carries_no_voice_at_all() -> None:
    """Reading someone else's agent is `not_found`, not a stripped-down payload — under
    RLS the row is invisible, so there is nothing to partially disclose."""
    _tenant_a, agent_a, _slug_a, _token_a = await _tenant()
    await _set_voice(_tenant_a, agent_a, VOICE_ID)
    _tenant_b, _agent_b, slug_b, token_b = await _tenant()

    async with _client(_app()) as http:
        response = await http.get(
            f"/v1/agents/{agent_a}/pending",
            headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b},
        )

    assert response.status_code == 404, response.text
    assert "bulbul" not in response.text
