"""What a picker may offer on an engine that hosts its voices (D-687, hard rule 7).

The voices are the operator's curated list, never the vendor's live catalogue: only a voice
an operator ADDED and ENABLED, that the engine still lists, is returned, and it is offerable
only while its minute is attested and — for a Studio voice — the Studio workspace is set
up. The models are the engine's live list, refused by name where the engine says they are
too slow or not on the plan. On any engine that does not host voices the route answers "no
such catalogue", so the Pipecat path reads nothing new.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import engine_catalogue_offer as offer
from apps.api.agents import engine_catalogue_routes
from apps.api.agents.engine_catalogue_routes import engine_catalogue, engine_voice_preview
from apps.api.agents.hosted_voices import (
    HostedVoiceRow,
    hosted_voice_unofferable_reason,
    parse_hosted_voice_id,
)
from apps.api.agents.llm_tiers import engine_model_token
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue
from apps.api.engine.fake import FakeEngine
from apps.workers import storage
from tests.hosted_voice_fakes import MP3, PRANA, SLOW, CatalogueRows, HostingEngine, selected

LOCKED = CatalogueModel(model_id="gpt-x", label="X", call_capable=True, plan_allows=False)
NOTHING: frozenset[str] = frozenset()
EVERY_KEY = frozenset({"platform", "studio", "byok_voice"})


def _client() -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")


def _operator() -> Principal:
    return Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="superadmin")


def _row(source: str, **update: Any) -> HostedVoiceRow:
    from datetime import UTC, datetime

    base = HostedVoiceRow(
        voice_id=f"{source}:v1",
        source=source,  # type: ignore[arg-type]
        vendor_id="v1",
        label="Asha",
        provider="thinnest",
        accent="hi",
        description=None,
        language_note="",
        is_custom=False,
        state="enabled",
        origin="operator",
        synced_at=datetime.now(UTC),
        curated_at=None,
        withdrawn_at=None,
        preview_available=False,
        preview_source=None,
        clone_id=None,
    )
    from dataclasses import replace

    return replace(base, **update)


# --- the model grounds -------------------------------------------------------------


def test_with_no_base_rate_no_model_is_offered() -> None:
    models = offer.offered_models(
        EngineCatalogue(models=[PRANA], complete=True),
        attested=NOTHING,
        platform="ThinnestAI",
        audience="operator",
    )
    assert not models[0].offerable and "ThinnestAI" in (models[0].reason or "")


def test_model_grounds_are_the_engines_own_statements() -> None:
    base = frozenset({"platform"})
    assert (
        offer.model_unofferable_reason(PRANA, attested=base, platform="T", audience="operator")
        is None
    )
    slow = offer.model_unofferable_reason(SLOW, attested=base, platform="T", audience="operator")
    assert slow is not None and "too slow" in slow
    locked = offer.model_unofferable_reason(
        LOCKED, attested=base, platform="T", audience="operator"
    )
    assert locked is not None and "plan" in locked


def test_a_client_never_reads_the_vendor_name_on_a_model() -> None:
    for model in (SLOW, LOCKED):
        reason = offer.model_unofferable_reason(
            model, attested=frozenset({"platform"}), platform="ThinnestAI", audience="client"
        )
        assert reason is not None and "ThinnestAI" not in reason
    reason = offer.model_unofferable_reason(
        PRANA, attested=NOTHING, platform="ThinnestAI", audience="client"
    )
    assert reason is not None and "ThinnestAI" not in reason


# --- the voice grounds -------------------------------------------------------------


@pytest.mark.parametrize("audience", ["client", "operator"])
def test_a_studio_voice_waits_on_the_studio_workspace(audience: str) -> None:
    reason = hosted_voice_unofferable_reason(
        _row("byok"),
        attested=EVERY_KEY,
        studio_ready=False,
        voice_key_priced=True,
        platform="ThinnestAI",
        audience=audience,  # type: ignore[arg-type]
    )
    assert reason is not None and "Studio" in reason
    if audience == "client":
        assert "ThinnestAI" not in reason and "Cartesia" not in reason


def test_an_unpriced_minute_is_refused_by_its_rate_key() -> None:
    operator = hosted_voice_unofferable_reason(
        _row("engine"),
        attested=frozenset({"byok_voice"}),
        studio_ready=True,
        voice_key_priced=True,
        platform="ThinnestAI",
        audience="operator",
    )
    assert operator is not None and "'studio'" in operator
    client = hosted_voice_unofferable_reason(
        _row("byok"),
        attested=frozenset({"studio"}),
        studio_ready=True,
        voice_key_priced=True,
        platform="ThinnestAI",
        audience="client",
    )
    assert client == "Not available yet: this voice has not been priced."


def test_a_priced_voice_is_offerable_on_either_rung() -> None:
    for source in ("engine", "byok"):
        assert (
            hosted_voice_unofferable_reason(
                _row(source),
                attested=EVERY_KEY,
                studio_ready=True,
                voice_key_priced=True,
                platform="T",
                audience="client",
            )
            is None
        )


def test_hosted_ids_cannot_collide_with_pipecat_ids() -> None:
    from typing import get_args

    from apps.api.agents.voices import TtsModel

    assert parse_hosted_voice_id("engine:abc") is not None
    assert parse_hosted_voice_id("byok:abc:def") is not None
    for model in get_args(TtsModel):
        assert parse_hosted_voice_id(f"{model}:speaker") is None
    for bad in (None, "", "engine:", "studio:abc", "abc"):
        assert parse_hosted_voice_id(bad) is None


# --- the route ---------------------------------------------------------------------


@pytest.fixture
def priced(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    keys = set(EVERY_KEY)

    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        assert engine == "thinnest"
        return frozenset(keys)

    monkeypatch.setattr(engine_catalogue_routes, "attested_rate_keys", _keys)
    monkeypatch.setattr(engine_catalogue_routes, "tts_price_is_billable", lambda provider: True)
    return keys


async def test_the_route_reads_nothing_on_an_engine_that_hosts_no_voices() -> None:
    with selected(FakeEngine()):
        out = await engine_catalogue(_client())
    assert out.available is False and out.voices == [] and out.models == []


async def test_the_route_lists_only_added_and_enabled_voices(
    priced: set[str], hosted_rows: CatalogueRows
) -> None:
    offered = await hosted_rows.add("engine", label="Offered", preview=True)
    studio = await hosted_rows.add("byok", label="Studio voice")
    hidden = [
        await hosted_rows.add("engine", label="Disabled", state="disabled"),
        await hosted_rows.add("engine", label="Not added", origin="synced"),
        await hosted_rows.add("engine", label="Gone", withdrawn=True),
    ]
    with selected(HostingEngine(complete=False)):
        out = await engine_catalogue(_client())
    by_id = {v.voice_id: v for v in out.voices}
    assert offered in by_id and studio in by_id
    assert not set(hidden) & set(by_id)
    assert by_id[offered].rung == "clear" and by_id[offered].offerable
    assert by_id[offered].preview_available
    assert by_id[offered].language_note == "Speaks the agent's language, with an accent: Hindi."
    # No Studio workspace on this deployment: listed, refused, and said plainly.
    assert by_id[studio].rung == "studio" and not by_id[studio].offerable
    assert out.studio_available is False and out.complete is False
    assert [m.usable_with_studio_voice for m in out.models][:2] == [True, False]


async def test_a_studio_voice_is_offered_once_the_workspace_is_set_up(
    priced: set[str], hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    studio = await hosted_rows.add("byok", label="Studio voice")
    with selected(HostingEngine()):
        out = await engine_catalogue(_client())
    assert out.studio_available is True
    assert {v.voice_id: v.offerable for v in out.voices}[studio] is True


async def test_an_unpriced_rung_is_listed_and_refused(
    priced: set[str], hosted_rows: CatalogueRows
) -> None:
    priced.discard("studio")
    voice = await hosted_rows.add("engine")
    with selected(HostingEngine()):
        out = await engine_catalogue(_client())
    row = {v.voice_id: v for v in out.voices}[voice]
    assert not row.offerable and row.reason == "Not available yet: this voice has not been priced."


async def test_a_client_reads_tiers_and_opaque_ids_never_the_engines_model_names(
    priced: set[str],
) -> None:
    """D-679/D-680: a client reads our tier word and an opaque id; the operator keeps the
    engine's own name, and the id is opaque in both realms."""
    tiered = PRANA.model_copy(update={"tier": "standard"})
    unnamed = SLOW.model_copy(update={"tier": None})
    engine = HostingEngine(models=(tiered, unnamed))
    with selected(engine):
        client_view = await engine_catalogue(_client())
        operator_view = await engine_catalogue(_operator())
    assert [m.label for m in client_view.models] == ["Standard", "Additional model 1"]
    assert [m.model_id for m in client_view.models] == [
        engine_model_token("prana-voice"),
        engine_model_token("gpt-slow"),
    ]
    body = client_view.model_dump_json().lower()
    for leaked in ("prana", "gpt"):
        assert leaked not in body, leaked
    assert [m.label for m in operator_view.models] == ["Prana", "Slow"]


async def test_no_voices_yet_is_said_plainly(
    priced: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _none(session: Any) -> tuple[()]:
        return ()

    monkeypatch.setattr(engine_catalogue_routes, "offered_hosted_voices", _none)
    with selected(HostingEngine()):
        out = await engine_catalogue(_client())
    assert out.voices == [] and out.note == "No voices have been made available yet."


def test_the_adapter_classifies_the_models_it_knows() -> None:
    from apps.api.engine import thinnest

    assert thinnest._MODEL_TIERS == {
        "prana-voice": "standard",
        "gpt-5-mini": "plus",
        "gpt-4.1": "pro",
    }


# --- the preview route -------------------------------------------------------------


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes | None]:
    objects: dict[str, bytes | None] = {}

    async def _read(key: str) -> bytes | None:
        return objects.get(key, MP3)

    monkeypatch.setattr(storage, "read_voice_preview", _read)
    return objects


async def test_a_client_plays_an_offered_voice_and_an_admin_plays_any(
    hosted_rows: CatalogueRows, stored: dict[str, bytes | None]
) -> None:
    offered = await hosted_rows.add("engine", preview=True)
    disabled = await hosted_rows.add("engine", state="disabled", preview=True)
    response = await engine_voice_preview(_client(), voice_id=offered)
    assert response.body == MP3 and response.media_type == "audio/mpeg"
    assert response.headers["cache-control"] == engine_catalogue_routes.PREVIEW_CACHE_CONTROL
    with pytest.raises(ProblemError) as caught:
        await engine_voice_preview(_client(), voice_id=disabled)
    assert caught.value.status == 404
    assert (await engine_voice_preview(_operator(), voice_id=disabled)).body == MP3


@pytest.mark.parametrize("case", ["no_preview", "not_hosted", "unknown", "object_gone"])
async def test_a_preview_that_cannot_be_served_is_a_404(
    hosted_rows: CatalogueRows, stored: dict[str, bytes | None], case: str
) -> None:
    if case == "no_preview":
        voice_id = await hosted_rows.add("engine")
    elif case == "not_hosted":
        voice_id = "sonic-3.5:abc"
    elif case == "unknown":
        voice_id = "engine:does-not-exist"
    else:
        voice_id = await hosted_rows.add("engine", preview=True)
        stored[f"voice-previews/{voice_id}"] = None
    with pytest.raises(ProblemError) as caught:
        await engine_voice_preview(_operator(), voice_id=voice_id)
    assert caught.value.status == 404


@pytest.mark.parametrize("audience", ["client", "operator"])
def test_a_studio_voice_needs_our_voice_keys_synthesis_priced(audience: str) -> None:
    """A Studio minute carries Cartesia's synthesis as a second cost (hard rule 7)."""
    reason = hosted_voice_unofferable_reason(
        _row("byok"),
        attested=EVERY_KEY,
        studio_ready=True,
        voice_key_priced=False,
        platform="ThinnestAI",
        audience=audience,  # type: ignore[arg-type]
    )
    assert reason is not None
    if audience == "client":
        assert reason == "Not available yet: this voice has not been priced."
    else:
        assert "Cartesia" in reason
    clear = hosted_voice_unofferable_reason(
        _row("engine"),
        attested=EVERY_KEY,
        studio_ready=True,
        voice_key_priced=False,
        platform="ThinnestAI",
        audience=audience,  # type: ignore[arg-type]
    )
    assert clear is None
