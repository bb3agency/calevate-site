"""CURATION: only the voices an operator enabled are selectable, in either realm (D-588).

WHAT THIS FILE IS DEFENDING. The founder asked for a Voices section in the admin console
where only the voices they enable are selectable by clients for their own agents and by
admins for anyone's. The "add" half of that request is not buildable — **Bolna's voice API
is READ-ONLY**, two GET routes and no create/update/delete anywhere in it
(VERIFIED-VENDOR-DOCS, hash-pinned mirror,
`bolna-findings/mirror/pages/api-reference/voice/overview.md:17-18`, every documented method
enumerated 11 Sep 2026) — so what shipped is the CURATION layer, and these are the clauses
that hold it to what it promised:

* an enabled voice is offered and a disabled or archived one is not, IN BOTH REALMS, on the
  read AND on the write;
* **a live agent on an archived voice is not broken** — the clause that reaches a phone
  line, and the reason archiving is allowed rather than refused;
* the four offerability grounds COMPOSE — a voice can be enabled and still unofferable for a
  priced reason, and the sentence a reader gets names the ground that actually decided;
* the ops API's own contract: list, move, audit, and a 404 for a voice that is not cached.

`platform_voice_catalog` is PLATFORM-scoped and shared with every other suite, so every
clause here restores the rows it moved (`tests/voice_fixture.seed_platform_voices`).
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.publishing import set_agent_voice
from apps.api.agents.voice_curation import (
    count_offered_voices,
    list_curated_voices,
    read_curation,
    set_curation_state,
)
from apps.api.agents.voice_offer import (
    ARCHIVED_REASON,
    DISABLED_REASON,
    NOT_CURATED_REASON,
    curation_unofferable_reason,
    offered_catalogue,
)
from apps.api.agents.voice_sync import load_voice_catalogue
from apps.api.agents.voices import ARRIVAL_CURATION_STATE, install_voice_catalogue
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.voice_fixture import TEST_VOICE_ID, seed_platform_voices

SECOND_VOICE_ID = "bulbul:v3:priya"


@pytest.fixture(autouse=True)
async def _restore_the_platforms_curation() -> object:
    """Every clause moves platform-wide state; every clause puts it back.

    Not a transaction rollback: several clauses go through HTTP-shaped writers that commit,
    and the rows are shared with every other suite in the run. Re-seeding is idempotent and
    only ever permissive, so two suites racing cannot leave the platform offering nothing.
    """
    yield
    await seed_platform_voices()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """One organisation with one LIVE agent already speaking `TEST_VOICE_ID`.

    Through `admin_service.create_organization` rather than a hand-written INSERT, for the
    reason every fixture in this tree that tried the shortcut discovered: the onboarding
    flow is what knows which columns, agreements and seeded rows an organisation needs, and
    a fixture that guesses fails on a schema change nobody made to it.
    """
    created = await admin_service.create_organization(
        name="Curation Co",
        slug=f"curation-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]
    await accept_agreements(uuid.UUID(str(tenant_id)))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', tts_voice = :voice, "
                "tts_provider = 'sarvam' WHERE id = :id"
            ),
            {"id": agent_id, "voice": TEST_VOICE_ID},
        )
        await session.commit()
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)), str(slug)


async def _set_state(voice_id: str, state: str) -> None:
    async with untenanted_session() as session:
        await set_curation_state(session, voice_id=voice_id, state=state)  # type: ignore[arg-type]
        await session.commit()


# --- the requirement itself -----------------------------------------------------


async def test_only_an_enabled_voice_is_offered_and_it_is_the_same_answer_in_both_realms() -> None:
    """THE FOUNDER'S REQUIREMENT, END TO END AND PER AUDIENCE.

    One source of truth (`voice_offer.offered_catalogue`), asked twice. A client picking for
    their own agent and an admin picking for anybody's must get the same VERDICTS — only the
    refusal wording forks, because the operator grounds name a vendor and two of our own
    settings and a client can act on none of them.
    """
    await _set_state(SECOND_VOICE_ID, "disabled")

    for audience in ("operator", "client"):
        rows = {row.voice.id: row for row in await offered_catalogue(audience=audience)}
        assert rows[TEST_VOICE_ID].offerable is True
        assert rows[SECOND_VOICE_ID].offerable is False, (
            f"a disabled voice was offered to the {audience} realm"
        )
        assert rows[SECOND_VOICE_ID].reason is not None

    operator = {row.voice.id: row.reason for row in await offered_catalogue(audience="operator")}
    client = {row.voice.id: row.reason for row in await offered_catalogue(audience="client")}
    assert operator[SECOND_VOICE_ID] == DISABLED_REASON
    assert client[SECOND_VOICE_ID] != operator[SECOND_VOICE_ID], (
        "the client was handed the operator's ground, which names a console they cannot open"
    )


async def test_an_unofferable_voice_is_still_listed_never_dropped() -> None:
    """A voice missing from the answer is indistinguishable from a voice this product does
    not have — so the client who asks for it is told nothing at all, and the operator who
    disabled it by accident has nothing to notice. Every voice comes back with its verdict."""
    before = {row.voice.id for row in await offered_catalogue()}
    await _set_state(SECOND_VOICE_ID, "archived")
    after = {row.voice.id for row in await offered_catalogue()}

    assert before == after, "curation shortened the list instead of annotating it"


async def test_an_archived_voice_cannot_be_newly_selected_for_any_agent() -> None:
    """THE WRITE ASKS THE SAME QUESTION THE PICKER ASKS. A picker that greys a voice out
    while the write accepts it is the divergence `voice_offer.py` exists to remove — and
    here it would put a client on a voice this platform has decided not to sell."""
    tenant_id, agent_id, _slug = await _tenant()
    await _set_state(SECOND_VOICE_ID, "archived")

    with pytest.raises(ProblemError) as raised:
        await set_agent_voice(tenant_id=tenant_id, agent_id=agent_id, voice_id=SECOND_VOICE_ID)

    assert raised.value.code == "voice_not_available"
    assert ARCHIVED_REASON[:30].lower() in (raised.value.detail or "").lower()
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT tts_voice FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar_one()
    assert stored == TEST_VOICE_ID, "the refused write moved the agent's voice anyway"


# --- the clause that reaches a phone line ---------------------------------------


async def test_archiving_a_voice_a_live_agent_is_on_does_not_break_that_agent() -> None:
    """**THE ONE THAT MATTERS.** An operator clicking Archive must never be able to make a
    caller hear silence.

    Three properties hold it and all three are asserted, because any one of them alone would
    be an accident rather than a design:

    1. **No agent row is touched.** The agent still holds the voice it held.
    2. **The id still RESOLVES.** `voices.catalogue()` is the LOOKUP layer and deliberately
       keeps a disabled voice, so `speech_for_voice_id` still splits it into the model and
       speaker the engine wants. If curation filtered the catalogue, the next publish or
       drift sweep would send `bulbul:v3:ashutosh` in the vendor's SPEAKER slot — a string no
       vendor has ever heard of.
    3. **The archive write itself succeeds**, rather than refusing because an agent is on
       the voice. Refusing would make a vendor's own withdrawal unfileable: the voice is gone
       from their platform whatever our table says, and a console that will not put it away
       just leaves it on every client's picker.
    """
    tenant_id, agent_id, _slug = await _tenant()
    from apps.api.agents.voices import get_voice, speech_for_voice_id

    await _set_state(TEST_VOICE_ID, "archived")

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT tts_voice FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar_one()
    assert stored == TEST_VOICE_ID, "archiving rewrote a live agent's voice"

    model, speaker = speech_for_voice_id(TEST_VOICE_ID)
    assert (model, speaker) == ("bulbul:v3", "ashutosh"), (
        "an archived voice stopped resolving, so the next publish would send our composed "
        "id in the vendor's speaker slot"
    )
    assert get_voice(TEST_VOICE_ID) is not None
    assert get_voice(TEST_VOICE_ID).label, "the label the engine requires beside the id is gone"


async def test_the_console_shows_how_many_live_agents_are_on_a_voice_before_it_is_archived() -> (
    None
):
    """Archiving is allowed rather than refused, so the operator makes the call with the
    number in view. A count that stayed at zero would make the permissive design reckless
    instead of deliberate."""
    _tenant_id, _agent_id, _slug = await _tenant()
    async with untenanted_session() as session:
        rows = {row.voice.id: row for row in await list_curated_voices(session)}

    assert rows[TEST_VOICE_ID].live_agents >= 1, (
        "a live agent on this voice was not counted, so the archive control would read as safe"
    )
    assert rows[SECOND_VOICE_ID].live_agents == 0


# --- the ops API ----------------------------------------------------------------


async def test_the_curation_write_is_idempotent_and_records_when_it_happened() -> None:
    """A double-clicked button is one outcome, not a conflict (RFC 9110 §9.2.2). And
    `curated_at` separates "reviewed and switched off" from "never reviewed", which the
    state column alone cannot express — the console renders those differently."""
    await _set_state(SECOND_VOICE_ID, "disabled")
    async with untenanted_session() as session:
        first = await set_curation_state(session, voice_id=SECOND_VOICE_ID, state="disabled")
        await session.commit()

    assert first.state == "disabled"
    assert first.curated_at is not None
    assert (await read_curation())[SECOND_VOICE_ID] == "disabled"


async def test_curating_a_voice_that_is_not_cached_is_a_404() -> None:
    """The operator is holding a stale table, and the fix is to refresh it — which is a
    different action from anything the three buttons do, so it is a 404 rather than a
    business rule about the voice."""
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await set_curation_state(
                session, voice_id="bulbul:v3:not-a-voice-on-this-account", state="enabled"
            )
    assert raised.value.status == 404


async def test_a_withdrawn_voice_is_not_offered_even_when_it_is_enabled() -> None:
    """Two different facts about one voice, and the vendor's outranks ours.

    An operator can enable a voice the platform has since stopped listing — the state is
    kept against the day it returns — but offering it would earn the live 400 that started
    all of this ("Provided voice: Anushka is not available for the provider: sarvam").
    `read_curation` drops withdrawn rows, and the offer seam reads a missing row as exactly
    that.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_voice_catalog SET curation_state = 'enabled', "
                "withdrawn_at = now() WHERE voice_id = :id"
            ),
            {"id": SECOND_VOICE_ID},
        )
        await session.commit()

    curation = await read_curation()
    assert SECOND_VOICE_ID not in curation, "a withdrawn voice is still being curated at"

    rows = {row.voice.id: row for row in await offered_catalogue()}
    if SECOND_VOICE_ID in rows:
        assert rows[SECOND_VOICE_ID].reason == NOT_CURATED_REASON

    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = NULL WHERE voice_id = :id"),
            {"id": SECOND_VOICE_ID},
        )
        await session.commit()


async def test_the_operators_table_lists_every_voice_withdrawn_ones_last() -> None:
    """NEVER A FILTERED LIST: telling "we do not have this voice" apart from "the platform
    dropped it" is the whole job of this screen, and a row that is simply absent answers
    neither."""
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = now() WHERE voice_id = :id"),
            {"id": SECOND_VOICE_ID},
        )
        await session.commit()
    async with untenanted_session() as session:
        rows = await list_curated_voices(session)

    ids = [row.voice.id for row in rows]
    assert SECOND_VOICE_ID in ids, "a withdrawn voice vanished from the operator's own table"
    assert ids[-1] == SECOND_VOICE_ID, "withdrawn rows must sort last; they need explaining"
    assert rows[-1].withdrawn is True
    assert rows[-1].offered is False, "a withdrawn voice cannot be offered whatever its state"

    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = NULL WHERE voice_id = :id"),
            {"id": SECOND_VOICE_ID},
        )
        await session.commit()


# --- hard rule 1: what the platform-scoped reads may and may not see -------------


async def test_the_same_catalogue_answers_every_tenant_and_the_counts_cross_them() -> None:
    """THE TWO HALVES OF PLATFORM SCOPE, AND BOTH ARE FAILURE MODES RLS CAN CAUSE SILENTLY.

    `platform_voice_catalog` carries no `tenant_id` and no RLS policy, and the written
    ground for that is in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`: one vendor account serves
    every tenant and its voice list is the same list for all of them. So:

    1. **The verdicts must be IDENTICAL for two different tenants.** A curation answer that
       varied by caller would mean the read had picked up a tenant scope from somewhere,
       which for a platform-wide decision is a bug in the direction nobody would notice —
       each client's picker would look plausible.
    2. **The live-agent count must CROSS tenants.** `admin_session()` widens `organizations`
       and nothing else, so a single `SELECT count(*) FROM agents` under it returns zero
       rows — honestly, and misleadingly. `count_live_agents_by_voice` therefore enumerates
       the directory and enters each tenant with its own GUC, and this is the clause that
       fails if that loop is ever replaced by the one-query version: two agents in two
       different accounts must both be counted.

    The second half is what an operator reads before archiving a voice, so a count that
    silently collapsed to zero would make the archive control read as safe on exactly the
    voice it is not safe on.
    """
    first_tenant, _first_agent, _slug = await _tenant()
    second_tenant, _second_agent, _slug2 = await _tenant()
    assert first_tenant != second_tenant

    # (1) one catalogue, one set of verdicts, whoever asks.
    await _set_state(SECOND_VOICE_ID, "disabled")
    curation = await read_curation()
    assert curation[SECOND_VOICE_ID] == "disabled"
    assert curation[TEST_VOICE_ID] == "enabled"

    # (2) both accounts' live agents are on TEST_VOICE_ID, and both are counted.
    async with untenanted_session() as session:
        rows = {row.voice.id: row for row in await list_curated_voices(session)}
    assert rows[TEST_VOICE_ID].live_agents >= 2, (
        "the cross-tenant count saw fewer agents than there are accounts holding the "
        "voice — the directory-then-enter-each-tenant loop has been replaced by a single "
        "query, which RLS answers with zero rows rather than an error"
    )


async def test_the_offered_count_is_the_same_number_the_table_shows() -> None:
    """TWO READERS OF ONE PREDICATE, HELD TOGETHER.

    The Voices page's table derives `offered` per row (`CuratedVoice.offered`); the write's
    response prints a COUNT that is deliberately one SQL `count(*)` instead of a second pass
    over the rows — because building the rows walks every tenant to fill `live_agents`, which
    is right for a page load and absurd for a number in a mutation response.

    Two spellings of one predicate is exactly the drift this repo treats as a defect even
    when both are right today, so this is the clause that fails if they part: enable one,
    disable one, withdraw one, and the count must agree with the rows every time.
    """
    await _set_state(SECOND_VOICE_ID, "disabled")
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = now() WHERE voice_id = :id"),
            {"id": "bulbul:v3:pooja"},
        )
        await session.commit()

    async with untenanted_session() as session:
        rows = await list_curated_voices(session)
        counted = await count_offered_voices(session)

    assert counted == sum(1 for row in rows if row.offered)
    assert counted >= 1, "the fixture platform offers nothing; the clause proves nothing"


async def test_a_newly_synced_voice_arrives_in_the_state_the_founder_asked_for() -> None:
    """THE REQUIREMENT, AS A COLUMN DEFAULT — and the two spellings of it held together.

    *Only the voices they enable are selectable.* The whole of that is the DEFAULT on
    `platform_voice_catalog.curation_state`: a voice defaulting to enabled would mean the
    vendor adding a persona to their platform silently puts it in front of every client of
    every tenant with no operator in the loop, which is the failure direction that cannot be
    undone by noticing it later.

    The default exists in two places — the database (migration `e4b7a10c92d6`) and
    `voices.ARRIVAL_CURATION_STATE`, which is what every comment and docstring in this tree
    cites. This is the clause that stops them parting: it inserts a row the way the SYNC
    does, naming every column the sync names and no others, and reads back what the database
    chose.
    """
    probe = "bulbul:v3:arrival-probe-not-a-real-voice"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_voice_catalog "
                "(voice_id, engine_voice_id, label, tts_model, provider, languages, "
                " is_custom, synced_at) "
                "VALUES (:id, 'arrival-probe', 'Arrival Probe', 'bulbul:v3', 'sarvam', "
                " ARRAY['te-IN']::text[], false, now())"
            ),
            {"id": probe},
        )
        await session.commit()
    try:
        async with untenanted_session() as session:
            state = (
                await session.execute(
                    text("SELECT curation_state FROM platform_voice_catalog WHERE voice_id = :id"),
                    {"id": probe},
                )
            ).scalar_one()
        assert state == ARRIVAL_CURATION_STATE, (
            "a voice the sync has just seen arrived in a state nobody chose — the column "
            "default and `voices.ARRIVAL_CURATION_STATE` have parted"
        )
        assert ARRIVAL_CURATION_STATE == "disabled", (
            "the arrival state is no longer 'disabled', which inverts the founder's one "
            "requirement: a synced voice would be selectable before anybody decided"
        )
        # ...and it is NOT offerable, which is the consequence that actually matters.
        assert curation_unofferable_reason(ARRIVAL_CURATION_STATE) is not None
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_voice_catalog WHERE voice_id = :id"), {"id": probe}
            )
            await session.commit()


async def test_not_on_offer_is_the_operator_ground_in_both_audiences() -> None:
    """THE FIELD THE CLIENT PICKER FILTERS ON, ASSERTED WHERE IT WAS SILENTLY FALSE.

    `OfferedVoiceOut.not_on_offer` is what stops a console rendering four hundred and
    sixteen "Cannot be chosen" rows to offer two. It was first derived by matching the
    voice's `reason` against the three curation sentences — correct for an operator, and
    FALSE FOR EVERY CLIENT, because `unofferable_reason` collapses all four grounds into
    `CLIENT_NOT_OFFERED_REASON` for that audience. So the filter did nothing in the client
    console, which is the console the founder was looking at, and nothing in the suite
    noticed because every existing clause read the operator's answer.

    The claim is therefore audience-INDEPENDENCE, not the value: a verdict a screen
    branches on must not be recoverable from a human sentence, because the sentence is
    allowed to vary for reasons the verdict is not.
    """
    disabled_id = "bulbul:v3:not-on-offer-probe"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_voice_catalog "
                "(voice_id, engine_voice_id, label, tts_model, provider, languages, "
                " is_custom, synced_at, curation_state) "
                "VALUES (:id, 'not-on-offer-probe', 'Probe', 'bulbul:v3', 'sarvam', "
                " ARRAY['te-IN']::text[], false, now(), 'disabled')"
            ),
            {"id": disabled_id},
        )
        await session.commit()
    try:
        async with untenanted_session() as session:
            await load_voice_catalogue(session)

        for audience in ("operator", "client"):
            offered = await offered_catalogue(audience=audience)  # type: ignore[arg-type]
            row = next((o for o in offered if o.voice.id == disabled_id), None)
            assert row is not None, f"the probe vanished from the {audience} catalogue"
            assert row.not_on_offer is True, (
                f"a DISABLED voice reads as on-offer to the {audience} — the client picker "
                "filters on this, so it renders every unoffered voice as a refusal"
            )
            assert row.offerable is False
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_voice_catalog WHERE voice_id = :id"),
                {"id": disabled_id},
            )
            await session.commit()
        install_voice_catalogue(None)
