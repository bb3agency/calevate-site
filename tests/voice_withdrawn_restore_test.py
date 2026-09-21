"""WHAT A WITHDRAWN VOICE MEANS WHEN THE ENGINE IS US, AND WHAT PUTS IT BACK.

`withdrawn_at` is written in exactly one place — `voice_sync`'s prune arm — and that arm
cannot run on an engine that lists no voices of its own (D-615). So on
`agent_hosting="owned_runtime"` the stamp is a fact left behind by a PREVIOUS engine that
no re-read will ever clear, and the copy that told an operator "it returns if the platform
lists it again" described a platform this product no longer has: the voice would sit
refused for the life of the deployment with no act named that would free it.

The act exists and always did — `voice_admission.admit_voice` writes `withdrawn_at = NULL`
on every add, so re-attesting the voice IS the restore path. These clauses hold the sentence
to it, and hold the OTHER engine shape to the sentence that is true there.

The rows are platform-scoped and shared with every other suite, so each clause takes back
out what it put in (`tests/voice_fixture.seed_platform_voices`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Final

import pytest
from apps.api.agents.voice_admission import OUR_PROVIDERS, VoiceFacts, admit_voice
from apps.api.agents.voice_offer import (
    NOT_CURATED_REASON,
    WITHDRAWN_NEEDS_REATTESTING_REASON,
    OfferedVoice,
    offered_catalogue,
)
from apps.api.agents.voice_sync import load_voice_catalogue
from apps.api.agents.voices import CARTESIA_TTS_MODEL, voice_id_for
from apps.api.db.session import untenanted_session
from apps.api.engine.fake import OWNED_RUNTIME_CAPABILITIES, FakeEngine
from apps.api.ops.voice_curation_routes import AddVoiceFormOut, CuratedVoiceOut, _form
from calevate_shared.engine import EngineVoice, EngineVoiceListing
from sqlalchemy import text
from tests.voice_fixture import seed_platform_voices

#: An operator-attested clone, in the shape a console add produces. Its id is opaque because
#: a cloned voice's is: a bug deriving the label from the id would pass against a persona.
CLONE_ID: Final = "withdrawn-restore-clone"
CLONE_NAME: Final = "Akshita"
CLONE_VOICE_ID: Final = voice_id_for(CARTESIA_TTS_MODEL, CLONE_ID)

_FACTS: Final = VoiceFacts(
    provider="cartesia",
    tts_model=CARTESIA_TTS_MODEL,
    engine_voice_id=CLONE_ID,
    label=CLONE_NAME,
    languages=("te-IN",),
)


#: What a VENDOR engine's catalogue says about this clone — the listing admission checks the
#: typed facts against on `control_plane`.
_VENDOR_LISTING: Final = EngineVoiceListing(
    voices=[
        EngineVoice(
            voice_id=CLONE_ID,
            label=CLONE_NAME,
            tts_model=CARTESIA_TTS_MODEL,
            languages=("te-IN",),
            is_custom=True,
        )
    ],
    complete=True,
    incomplete_reason=None,
)


class _VendorEngine(FakeEngine):
    """An engine that keeps a catalogue of its own — the suite's default hosting shape."""

    async def list_voices(self) -> EngineVoiceListing:
        return _VENDOR_LISTING


class _OwnedRuntimeEngine(FakeEngine):
    """An engine that IS us. `list_voices` RAISES rather than returning empty, so a clause
    below fails loudly if anything consults a catalogue on this shape at all.

    The capability set goes through the CONSTRUCTOR: `FakeEngine.__init__` assigns
    `self.capabilities` per instance, so a class attribute of that name is overwritten
    before the object is ever used.
    """

    def __init__(self) -> None:
        super().__init__(capabilities=OWNED_RUNTIME_CAPABILITIES)

    async def list_voices(self) -> EngineVoiceListing:
        raise AssertionError("an owned runtime has no catalogue to be asked for")


@pytest.fixture
def owned_runtime() -> Iterator[_OwnedRuntimeEngine]:
    """Make THIS PROCESS a deployment whose engine is us.

    It reaches into `apps.api.engine`'s instance cache because that is what
    `engine_capabilities()` resolves through — the seam every refusal sentence now asks —
    and restores it afterwards, since a leaked descriptor fails a suite far from here.
    """
    import apps.api.engine as engine_module

    engine = _OwnedRuntimeEngine()
    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = engine
    try:
        yield engine
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


@pytest.fixture(autouse=True)
async def _restore_the_platforms_voices() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_voice_catalog WHERE engine_voice_id = :vid"),
            {"vid": CLONE_ID},
        )
        await session.commit()
    await seed_platform_voices()
    async with untenanted_session() as session:
        await load_voice_catalogue(session)


async def _admit(engine: object) -> None:
    async with untenanted_session() as session:
        await admit_voice(session, engine, _FACTS)  # type: ignore[arg-type]
        await load_voice_catalogue(session)
        await session.commit()


async def _withdraw() -> None:
    """Stamp the row the way a sync's prune arm does, then reload the lookup snapshot.

    Written as SQL rather than by driving a sync, because the state under test is one no
    sync can produce any more: it is what a Bolna-era prune left behind on a deployment that
    has since become its own engine.
    """
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_voice_catalog SET withdrawn_at = now() WHERE voice_id = :id"),
            {"id": CLONE_VOICE_ID},
        )
        await load_voice_catalogue(session)
        await session.commit()


async def _picker_row() -> OfferedVoice:
    rows = {row.voice.id: row for row in await offered_catalogue()}
    assert CLONE_VOICE_ID in rows, "the voice left the picker entirely"
    return rows[CLONE_VOICE_ID]


# --- the ops form no longer names a platform this product does not use -----------


def test_the_add_form_offers_only_providers_this_product_runs() -> None:
    """THE FORM IS THE DERIVED LIST AND NOTHING ELSE.

    It used to carry a second group — one entry, ElevenLabs, offered only to be refused —
    because a rented engine's Voice Lab cloned on ElevenLabs or Cartesia. That engine is
    gone, so the option was an operator's invitation to go and do something this product
    cannot use, and its refusal sent them to that platform's console for the remedy.
    """
    form = _form()
    assert form.providers, "the add form offers no provider at all"
    assert [option.provider for option in form.providers] == list(OUR_PROVIDERS)


def test_the_add_form_names_no_vendor_console_and_carries_no_link_to_one() -> None:
    """THE WHOLE PAYLOAD, not just the provider list.

    `voice_lab_url` was a field on this response holding a rented platform's URL, and the
    console printed it as the place to go and get a voice id. A field is the harder half to
    notice going stale, so the absence is asserted on the MODEL as well as on the copy.
    """
    assert "voice_lab_url" not in AddVoiceFormOut.model_fields
    body = _form().model_dump_json().lower()
    for residue in ("elevenlabs", "bolna", "voice lab", "http"):
        assert residue not in body, f"the add form still names {residue!r}"


# --- the withdrawn sentence, on each engine shape --------------------------------


async def test_a_withdrawn_voice_on_an_owned_runtime_names_the_act_that_restores_it(
    owned_runtime: _OwnedRuntimeEngine,
) -> None:
    """THE REFUSAL HAS TO BE ACTIONABLE, WHICH THE OLD ONE WAS NOT.

    On this engine `list_voices` reads `platform_voice_catalog WHERE origin = 'operator'` —
    our own table — and `sync_voice_catalogue` refuses to run at all (D-615), so nothing
    will ever clear the stamp by re-reading. Telling an operator the voice "returns if the
    platform lists it again" points at a platform that does not exist and leaves the row
    refused forever.
    """
    await _admit(owned_runtime)
    await _withdraw()

    row = await _picker_row()
    assert row.offerable is False, "a withdrawn voice was offered"
    assert row.reason == WITHDRAWN_NEEDS_REATTESTING_REASON
    assert "add the voice again" in (row.reason or "").lower()


async def test_re_attesting_the_voice_the_refusal_names_actually_restores_it(
    owned_runtime: _OwnedRuntimeEngine,
) -> None:
    """DO EXACTLY WHAT THE SENTENCE SAYS, AND CHECK IT WORKED.

    The two halves are asserted together on purpose: a refusal naming an act that does not
    restore the row, and a restore path nothing tells the operator about, are the same
    defect seen from two ends.
    """
    await _admit(owned_runtime)
    await _withdraw()
    assert (await _picker_row()).offerable is False

    await _admit(owned_runtime)

    async with untenanted_session() as session:
        withdrawn, state = (
            await session.execute(
                text(
                    "SELECT withdrawn_at, curation_state FROM platform_voice_catalog "
                    "WHERE voice_id = :id"
                ),
                {"id": CLONE_VOICE_ID},
            )
        ).one()
    assert withdrawn is None, "re-attesting the voice left the withdrawal stamp in place"
    assert state == "enabled"

    row = await _picker_row()
    assert row.offerable is True, f"the restored voice is still refused: {row.reason}"


async def test_a_withdrawn_voice_on_a_vendor_engine_still_reads_as_the_vendors_statement() -> None:
    """THE OTHER SHAPE IS UNCHANGED, AND THAT IS NOT AN OVERSIGHT.

    An engine that keeps a catalogue of its own really did drop the voice from OUR ACCOUNT
    there, no console click reverses that, and `sync_voice_catalogue` really will clear the
    stamp if the vendor lists it again. Re-attesting would be the wrong advice on that
    engine: admission checks the voice against the vendor's list and would refuse it.

    The suite's default engine is `control_plane`, so this needs no fixture — which is what
    makes it the guard against the fork being resolved one way for everybody.
    """
    await _admit(_VendorEngine())
    await _withdraw()

    row = await _picker_row()
    assert row.reason == NOT_CURATED_REASON
    assert row.reason != WITHDRAWN_NEEDS_REATTESTING_REASON


def test_the_console_row_carries_the_engines_own_withdrawn_sentence() -> None:
    """THE BROWSER MUST NOT COMPOSE THIS COPY.

    Which act clears a withdrawal stamp is a property of the ENGINE, and `withdrawn_at`
    alone cannot tell a page which engine this deployment runs — so a screen writing its own
    sentence here writes one that is true on one shape and false on the other. The field is
    on the wire for that reason, non-null exactly when the stamp is.
    """
    assert "withdrawn_note" in CuratedVoiceOut.model_fields
