"""What a picker may offer on an engine that hosts its voices (D-687, hard rule 7).

The voices are the operator's curated list, never the vendor's live catalogue: only a voice
an operator ADDED and ENABLED, that the engine still lists, is returned, and it is offerable
only while its minute is attested; a Studio voice is offered only while the account's Studio
publish would go through as last checked (D-806). The models are the engine's live list, to
operators only (a client is sent none), refused by name where the engine says they are too
slow or not on the plan. On any engine that does not host voices the route answers "no such
catalogue".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
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
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue
from apps.api.engine.fake import FakeEngine
from apps.workers import storage
from tests.hosted_voice_fakes import (
    MP3,
    OFF_KEY,
    PRANA,
    READY_KEY,
    SLOW,
    CatalogueRows,
    HostingEngine,
    selected,
)
from tests.workspace_support import give_own_workspace

LOCKED = CatalogueModel(model_id="gpt-x", label="X", call_capable=True, plan_allows=False)
NOTHING: frozenset[str] = frozenset()
EVERY_KEY = frozenset({"platform", "premium", "studio", "byok_voice"})


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
        vendor_label="Asha",
        display_label=None,
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
        band="studio" if source == "engine" else None,
        gender=None,
        languages=(),
        person_clone=False,
        consent=None,
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


def test_an_unpriced_minute_is_refused_by_its_rate_key() -> None:
    operator = hosted_voice_unofferable_reason(
        _row("engine"),
        attested=frozenset({"byok_voice"}),
        voice_key_priced=True,
        platform="ThinnestAI",
        audience="operator",
    )
    assert operator is not None and "'studio'" in operator
    client = hosted_voice_unofferable_reason(
        _row("byok"),
        attested=frozenset({"studio"}),
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
                voice_key_priced=True,
                platform="T",
                audience="client",
            )
            is None
        )


def test_hosted_ids_cannot_collide_with_catalogue_ids() -> None:
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


@pytest.fixture
def console_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Our Cartesia key in the console, which a paying client's first Studio publish installs
    in its workspace (`studio_voices.ensure_studio_in`)."""
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    get_settings.cache_clear()


@pytest.fixture
async def developer_check() -> AsyncIterator[None]:
    """The recorded developer-workspace check is one platform row; put it back after."""
    yield
    from apps.api.db.session import untenanted_session
    from apps.api.tenancy.engine_workspace import record_developer_studio_check

    async with untenanted_session() as session:
        await record_developer_studio_check(session, ready=False)


async def test_the_route_reads_nothing_on_an_engine_that_hosts_no_voices() -> None:
    with selected(FakeEngine()):
        out = await engine_catalogue(_client())
    assert out.available is False and out.voices == [] and out.models == []


async def test_the_route_lists_only_added_and_enabled_voices(
    priced: set[str], hosted_rows: CatalogueRows, console_key: None
) -> None:
    offered = await hosted_rows.add("engine", label="Offered", preview=True)
    studio = await hosted_rows.add("byok", label="Studio voice")
    hidden = [
        await hosted_rows.add("engine", label="Disabled", state="disabled"),
        await hosted_rows.add("engine", label="Not added", origin="synced"),
        await hosted_rows.add("engine", label="Gone", withdrawn=True),
        await hosted_rows.add("engine", label="Other band", band="standard"),
        await hosted_rows.add("byok", label="Key off", withdrawn=True),
    ]
    with selected(HostingEngine(complete=False)):
        out = await engine_catalogue(_client())
    by_id = {v.voice_id: v for v in out.voices}
    assert offered in by_id and studio in by_id
    assert not set(hidden) & set(by_id)
    assert by_id[offered].rung == "clear" and by_id[offered].offerable
    assert by_id[offered].preview_available
    assert by_id[offered].language_note == "Speaks the agent's language, with an accent: Hindi."
    # A paying client whose Studio publish can switch its own workspace on: offered at the
    # Studio rung.
    assert by_id[studio].rung == "studio" and by_id[studio].offerable
    # The client realm reads no model list, so a short one cannot make it incomplete.
    assert out.studio_available is True and out.complete is True
    # A client chooses a tier and is sent no engine models (D-679).
    assert out.models == []


async def _account(*, trial: bool) -> uuid.UUID:
    from apps.api.admin import service as admin_service
    from apps.api.billing.trials import start_trial
    from apps.api.db.session import tenant_session

    created = await admin_service.create_organization(
        name="Tea House",
        slug=f"st-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    if trial:
        async with tenant_session(tenant_id) as session:
            await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
    else:
        await give_own_workspace(tenant_id)
    return tenant_id


def _client_of(tenant_id: uuid.UUID) -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")


async def test_a_trial_is_not_offered_studio_while_its_studio_publish_would_be_refused(
    priced: set[str], hosted_rows: CatalogueRows, console_key: None, developer_check: None
) -> None:
    """Studio voices listed, our developer workspace not on our key: a trial agent's Studio
    publish is refused (`require_developer_studio`, D-727), so the trial's picker must not
    offer a Studio voice (D-806). Our console key does not change that: a trial's agents
    live in the developer workspace."""
    from apps.api.agents.studio_voices import STUDIO_ACCOUNT_NOT_READY, require_developer_studio
    from apps.workers.studio_voice_key import check_developer_studio

    studio = await hosted_rows.add("byok", label="Studio voice")
    tenant_id = await _account(trial=True)
    engine = HostingEngine(key_state=OFF_KEY)
    with selected(engine):
        assert await check_developer_studio(engine) == "not_set_up"
        with pytest.raises(ProblemError) as refused:
            await require_developer_studio(engine)
        out = await engine_catalogue(_client_of(tenant_id))
    assert refused.value.code == STUDIO_ACCOUNT_NOT_READY
    assert out.studio_available is False
    assert out.studio_note == engine_catalogue_routes.STUDIO_NOT_READY_NOTE
    offer_of = {v.voice_id: v for v in out.voices}[studio]
    assert not offer_of.offerable
    assert offer_of.reason == engine_catalogue_routes.STUDIO_NOT_READY_NOTE


async def test_a_trial_is_offered_studio_once_the_hourly_check_finds_our_key_on(
    priced: set[str], hosted_rows: CatalogueRows, developer_check: None
) -> None:
    from apps.api.agents.studio_voices import require_developer_studio
    from apps.workers.studio_voice_key import check_developer_studio

    studio = await hosted_rows.add("byok", label="Studio voice")
    tenant_id = await _account(trial=True)
    engine = HostingEngine(key_state=READY_KEY)
    with selected(engine):
        assert await check_developer_studio(engine) == "ok"
        await require_developer_studio(engine)
        out = await engine_catalogue(_client_of(tenant_id))
    assert out.studio_available is True and out.studio_note is None
    assert {v.voice_id: v for v in out.voices}[studio].offerable


async def test_a_paying_client_is_offered_studio_by_its_own_workspace_not_ours(
    priced: set[str], hosted_rows: CatalogueRows, developer_check: None
) -> None:
    """A paying client's Studio publish switches its OWN workspace on (D-717): with no
    Cartesia key in our console that needs the workspace to be on already, and our developer
    workspace being off changes nothing for it."""
    from apps.api.db.session import tenant_session
    from apps.api.tenancy.engine_workspace import record_studio_check

    await hosted_rows.add("byok", label="Studio voice")
    tenant_id = await _account(trial=False)
    with selected(HostingEngine(key_state=OFF_KEY)):
        before = await engine_catalogue(_client_of(tenant_id))
        async with tenant_session(tenant_id) as session:
            await record_studio_check(session, tenant_id, error_code=None)
        after = await engine_catalogue(_client_of(tenant_id))
        async with tenant_session(tenant_id) as session:
            await record_studio_check(session, tenant_id, error_code="studio_workspace_not_ready")
        broken = await engine_catalogue(_client_of(tenant_id))
    assert before.studio_available is False
    assert after.studio_available is True
    assert broken.studio_available is False


async def test_an_unpriced_rung_is_listed_and_refused(
    priced: set[str], hosted_rows: CatalogueRows
) -> None:
    priced.discard("studio")
    voice = await hosted_rows.add("engine")
    with selected(HostingEngine()):
        out = await engine_catalogue(_client())
    row = {v.voice_id: v for v in out.voices}[voice]
    assert not row.offerable and row.reason == "Not available yet: this voice has not been priced."


async def test_no_voices_yet_is_said_plainly(
    priced: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _none(session: Any) -> tuple[()]:
        return ()

    monkeypatch.setattr(engine_catalogue_routes, "offered_hosted_voices", _none)
    with selected(HostingEngine()):
        out = await engine_catalogue(_client())
    assert out.voices == [] and out.note == "No voices have been made available yet."


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
        voice_key_priced=False,
        platform="ThinnestAI",
        audience=audience,  # type: ignore[arg-type]
    )
    assert clear is None
