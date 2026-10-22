"""The voice an agent is set to: the catalogue's lookup layer and the read that shows it.

1. **The catalogue is data we can stand behind.** Every entry must validate against its
   own lookup — an entry the validator would refuse is a voice the UI offers and the API
   rejects.

2. **CONFIGURED IS NOT LIVE, and the read says both.** `agents.tts_voice` is the voice on
   the row; `agents.live_tts_voice` (migration c8b3f14e7a29) is the voice `publish_agent`
   actually sent, and `GET /v1/agents/{agent_id}/pending` carries both. They differ on an
   agent published before the mirror existed or one that drifted, and the read says so
   rather than answering with one value.
"""

from __future__ import annotations

import uuid
from typing import get_args
from uuid import UUID

from apps.api.agents import prompts, publishing
from apps.api.agents.publishing_routes import router as publishing_router
from apps.api.agents.routes import router as agents_router
from apps.api.agents.service import publish_agent
from apps.api.agents.voice_sync import load_voice_catalogue
from apps.api.agents.voices import (
    Voice,
    VoiceProvider,
    catalogue,
    catalogue_note,
    get_voice,
    is_supported_voice,
    speech_for_voice_id,
    voice_id_for,
    voice_ids,
)
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist
from tests.voice_fixture import STUDIO_TTS_MODEL, TEST_SPEAKER, TEST_VOICE_ID

VOICE_ID = TEST_VOICE_ID


async def _curated(voice: Voice, state: str = "enabled") -> None:
    """Give a voice a `platform_voice_catalog` row, which is what the catalogue snapshot
    `load_voice_catalogue` reads."""
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_voice_catalog (voice_id, engine_voice_id, label, "
                " tts_model, provider, languages, is_custom, synced_at, curation_state) "
                "VALUES (:id, :speaker, :label, :model, :provider, :languages, false, now(), "
                " :state) "
                "ON CONFLICT (voice_id) DO UPDATE SET curation_state = :state"
            ),
            {
                "id": voice.id,
                "speaker": voice.speaker,
                "label": voice.label,
                "model": voice.tts_model,
                "provider": voice.provider,
                "languages": list(voice.languages),
                "state": state,
            },
        )
        await session.commit()


async def _uncurated(voice: Voice) -> None:
    """Take the row away again. `platform_voice_catalog` is PLATFORM state shared with every
    other suite, so a clause that adds a row removes it."""
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_voice_catalog WHERE voice_id = :id"), {"id": voice.id}
        )
        await session.commit()


def _cartesia_voice(speaker: str = "test-record-not-a-real-voice-id") -> Voice:
    """ONE Cartesia catalogue entry, as the ENGINE SYNC would build one.

    Built here rather than loaded: the only route into the catalogue is the engine's own
    voice-config API. The id is deliberately not a plausible Cartesia id — nothing in this
    tree has read one, and a fixture that looked real is how an invented id ends up quoted
    as fact.
    """
    return Voice(
        id=voice_id_for(STUDIO_TTS_MODEL, speaker),
        label="Test Persona",
        provider="cartesia",
        tts_model=STUDIO_TTS_MODEL,
        speaker=speaker,
        languages=("te-IN",),
        gender=None,
        verified=True,
        note=catalogue_note("cartesia"),
    )


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    # ORDER IS THE CONTRACT: the literal `/v1/agents/{id}/pending` must be declared before
    # `/v1/agents/{agent_id}`, or FastAPI matches the parameterised route first.
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
    created = await create_org_with_receptionist(
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


async def _set_voice(tenant_id: uuid.UUID, agent_id: uuid.UUID, voice_id: str) -> None:
    """Put a catalogue voice on the agent's row, as configuring it does."""
    voice = get_voice(voice_id)
    assert voice is not None, voice_id
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v, tts_provider = :p WHERE id = :aid"),
            {"v": voice_id, "p": voice.provider, "aid": agent_id},
        )


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


# --- The catalog itself -------------------------------------------------------


def test_the_catalog_is_not_empty_and_every_entry_validates() -> None:
    """A catalog whose own entries the validator refuses is worse than no catalog: the
    UI would offer voices the API rejects, and the bug would look like a server fault."""
    assert catalogue(), "an empty catalog makes the voice picker unusable"
    for voice in catalogue():
        assert is_supported_voice(voice.id), f"{voice.id} is offered but not accepted"
        assert get_voice(voice.id) == voice
        assert voice.id in voice_ids()
        assert voice.provider in get_args(VoiceProvider), "a provider this product runs"
        assert voice.label.strip(), "a voice with no label cannot be picked by a human"
        assert "te-IN" in voice.languages, "Telugu-first: a voice without Telugu is not ours"
        assert voice.languages[0] == "te-IN", "Telugu leads the list a picker renders"


def test_an_unknown_voice_id_is_not_supported() -> None:
    """Exact match, no normalisation: the stored string is pasted into a vendor request
    verbatim, so a near-miss is as wrong as a typo."""
    for unknown in ("", "sonic", "sonic-3.5", "sonic-4", "SONIC-3.5:ASHUTOSH", "ashutosh"):
        assert not is_supported_voice(unknown)
        assert get_voice(unknown) is None


def test_every_entry_was_listed_by_the_engine_and_none_claims_a_gender() -> None:
    """⚠ **THE `verified` HALF OF THIS CLAUSE REVERSED, AND THE REVERSAL IS D-585/D-588.**

    It used to assert `verified is False` on every entry, because the ids were copied from
    the MODEL vendor's SDK and nobody had confirmed the engine would accept them. There is
    no such entry any more: every voice in the catalogue is there because the ENGINE's own
    voice-config API listed it, on our own account, for a model we offer. That is exactly
    what `verified` claims and nothing more — it is not an ear test, and OPERATIONS §2
    gate 3's listening half is still open.

    The gender half is unchanged: no vendor enumeration this tree reads carries one, and a
    name is not evidence of a voice (hard rule 11).
    """
    assert catalogue(), "the suite's platform offers no voices; the fixture did not run"
    assert all(voice.verified for voice in catalogue())
    assert all(voice.gender is None for voice in catalogue()), "no speaker genders in the docs"


# --- CONFIGURED vs LIVE (migration c8b3f14e7a29) ------------------------------
#
# What makes the read more than a getter is that there are TWO
# answers — the voice on the row and the voice the engine is holding — and they are
# allowed to differ. Every test below pins one of the states they can be in.


async def test_the_read_returns_the_configured_voice() -> None:
    """Set it, read it back, get the same voice.

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
    assert state.voice.configured.provider == "cartesia"
    assert state.voice.configured.catalog is not None
    assert state.voice.configured.catalog.tts_model == "sonic-3.5", "the picker renders the voice"
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
    assert engine._agents[ref].models.tts_voice == TEST_SPEAKER

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.published is True
    assert state.voice.live is not None
    assert state.voice.live.voice_id == VOICE_ID
    assert state.voice.live.provider == "cartesia"
    assert state.voice.republish_required is False
    assert "Callers hear" in state.voice.headline


async def test_a_stale_live_voice_is_reported_beside_the_configured_one() -> None:
    """The read reports the CONFIGURED voice AND what the caller is still hearing.

    Divergence is simulated by writing a stale `live_tts_voice` directly, which is exactly
    the shape a pre-mirror or drifted agent has. Answering with one value would be the
    defect.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    await _set_voice(tenant_id, agent_id, VOICE_ID)
    await _publish(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET live_tts_voice = 'sonic:legacy' WHERE id = :a"),
            {"a": agent_id},
        )
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.republish_required is True, "the read sees the divergence"
    assert "Callers still hear" in state.voice.headline
    # The voice is NOT reported through `pending`/Apply: that list is version numbers
    # and Undo cannot undo a voice.
    assert [change.field for change in state.pending] == []
    assert state.has_pending is False


async def test_a_legacy_publish_with_no_live_voice_reads_as_publish_again() -> None:
    """`live_tts_voice` is NULL — published before the mirror existed, so we cannot PROVE
    what the engine holds. The unknown live voice must resolve towards "publish again",
    never towards a claim of sync, which is the only direction of error a statement about a
    live phone line may have. PAUSED, because a paused agent still has an engine object
    holding a voice.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'paused' WHERE id = :a"),
            {"r": f"fakeagent_legacy_{uuid.uuid4().hex[:8]}", "a": agent_id},
        )
    await _set_voice(tenant_id, agent_id, VOICE_ID)

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
                "UPDATE agents SET tts_voice = 'retired-model:v1', tts_provider = 'cartesia' "
                "WHERE id = :a"
            ),
            {"a": agent_id},
        )

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.voice.configured is not None
    assert state.voice.configured.voice_id == "retired-model:v1"
    assert state.voice.configured.catalog is None, "we do not offer it, so we cannot describe it"
    assert "retired-model:v1" in state.voice.headline, (
        "named by its id rather than silently dropped"
    )


async def test_a_client_can_read_which_voice_their_own_agent_speaks_in() -> None:
    """Client-realm `agents:read`, and that is the deliberate answer to "is this client
    information?".

    A client is legally the Principal Entity and gets to hear what their agent sounds like.
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
    assert voice["configured"]["catalog"]["tts_model"] == "sonic-3.5"
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
                "UPDATE agents SET live_tts_voice = 'retired-model:v2', "
                "live_tts_provider = 'nobody' "
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
    assert VOICE_ID not in response.text


# --- D-617: a voice the PLATFORM withdrew, and the panel that could not name it ---------


async def _withdraw(voice_id: str) -> None:
    """Stamp `withdrawn_at` on one catalogue row — what a complete sync that no longer
    names the voice does (`voice_sync.sync_voice_catalogue`'s prune arm)."""
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = now() WHERE voice_id = :id"),
            {"id": voice_id},
        )
        await session.commit()


async def test_a_withdrawn_voice_an_agent_is_set_to_is_still_nameable() -> None:
    """THE FOUNDER'S BUG, END TO END (D-617).

    A live client's agent was configured on `sonic-3.5:b6dafaa0-…`; a sync stamped that
    row `withdrawn_at`; `read_cached_catalogue` excluded withdrawn rows from the snapshot
    `voices.catalogue()` serves — and that snapshot is the LOOKUP layer, the one
    `get_voice` and `speech_for_voice_id` answer from. So the panel printed the raw engine
    ref under both "Callers hear now" and "Configured", the picker lost the whole Studio
    section (it keeps the row an agent is already set to, and could not keep a row that was
    not there), and the next publish would have sent our own composed catalogue id in the
    vendor's speaker slot with no model beside it.

    Two properties, in the order they failed: the catalogue can still NAME it, and the read
    reports it by its label.
    """
    voice = _cartesia_voice("b6dafaa0-3a87-40b2-823c-1e4cf3c07314")
    await _curated(voice)
    try:
        tenant_id, agent_id, _slug, _token = await _tenant()
        async with untenanted_session() as session:
            assert await load_voice_catalogue(session) > 0
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET tts_voice = :v, tts_provider = :p WHERE id = :aid"),
                {"v": voice.id, "p": voice.provider, "aid": agent_id},
            )

        await _withdraw(voice.id)
        async with untenanted_session() as session:
            await load_voice_catalogue(session)

        # 1. THE LOOKUP LAYER STILL NAMES IT — this is what `get_voice` answers on every
        #    publish, every drift sweep and every read-back a console renders.
        named = get_voice(voice.id)
        assert named is not None and named.label == voice.label
        # ...and the splitter therefore still hands the adapter a MODEL, which is the half
        # that reaches a phone line: without it the Cartesia arm refuses the publish.
        assert speech_for_voice_id(voice.id) == (voice.tts_model, voice.speaker)

        # 2. THE PANEL NAMES IT rather than printing the ref, and says nothing about a
        #    voice it cannot name, because it can.
        state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
        assert state.voice.configured is not None
        assert state.voice.configured.catalog is not None
        assert voice.label in state.voice.headline
        assert state.voice.unnamed_note is None
    finally:
        await _uncurated(voice)


async def test_a_voice_nothing_can_name_is_printed_with_a_sentence_saying_so() -> None:
    """A RAW ENGINE REF IS NEVER SHOWN BARE (D-617).

    `_reading` degrades an unrecognised id to the id itself on purpose — an operator can
    search for an id and "unknown" reads as a fault rather than as a voice we no longer
    list. What was missing is the sentence beside it. This is the row that no longer has a
    catalogue entry AT ALL (deleted, or free text written before the catalogue existed),
    which is the one state the fix above cannot recover.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v, tts_provider = 'cartesia' WHERE id = :aid"),
            {"v": "sonic-3.5:not-in-any-catalogue", "aid": agent_id},
        )

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.voice.configured is not None
    assert state.voice.configured.catalog is None, "the fixture stopped being the case"
    assert state.voice.unnamed_note == publishing.VOICE_NOT_IN_CATALOGUE_NOTE
    # The sentence is what a CLIENT reads on their own screen, so it names no vendor and
    # no setting of ours (hard rule: the client realm reads this endpoint).
    note = state.voice.unnamed_note.lower()
    assert "cartesia" not in note and "sarvam" not in note and "bolna" not in note
