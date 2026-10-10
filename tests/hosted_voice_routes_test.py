"""The admin Voices panel and the catalogue sync on an engine that hosts its voices (D-687).

Admin-only (`ops:manage`), audited; cloning, deleting a clone and switching Studio voices on
or off are step-up confirmed (D-688). The sync reads every band the engine lists and, while our
Cartesia key is on in the workspace, our own-key voices — never `list_voices`, which refuses on
this engine — and the Pipecat path is untouched: a Pipecat refresh reads no hosted list.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import hosted_voices
from apps.api.agents.hosted_voices import (
    language_note,
    parse_hosted_voice_id,
    read_hosted_voice,
    rung_of_source,
    rungs_awaiting_setup,
)
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_sync import sync_voice_catalogue
from apps.api.billing.payment_routes import voice_tier_not_offered
from apps.api.core.errors import ProblemError
from apps.api.core.middleware import MAX_BODY_BYTES
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine.catalogue import HostedVoice, HostedVoiceBand
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from apps.api.ops import hosted_voice_routes as routes
from apps.workers import storage
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text
from tests.hosted_voice_fakes import (
    MP3,
    OFF_KEY,
    READY_KEY,
    STUDIO_WS,
    WAV,
    CatalogueRows,
    HostingEngine,
    selected,
    use_studio_workspace,
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin() -> tuple[str, UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}", admin_id


@pytest.fixture
async def admin() -> AsyncIterator[dict[str, str]]:
    token, _ = await _admin()
    yield {"Authorization": f"Bearer {token}"}


@pytest.fixture
def previews(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """The object store, in memory: what was stored, and what a vendor link serves."""
    stored: dict[str, bytes] = {}

    async def _store(*, key: str, data: bytes, content_type: str) -> str:
        stored[key] = data
        return key

    async def _fetch(url: str) -> bytes:
        if "broken" in url:
            raise storage.RecordingUnavailableError("preview_unusable")
        return MP3

    monkeypatch.setattr(storage, "store_voice_preview", _store)
    monkeypatch.setattr(storage, "fetch_voice_preview", _fetch)
    return stored


async def _audits(action: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE action = :a"), {"a": action}
                )
            ).scalar_one()
        )


async def _entry(voice_id: str) -> PlatformVoiceCatalogEntry:
    async with admin_session() as session:
        return (
            await session.execute(
                select(PlatformVoiceCatalogEntry).where(
                    PlatformVoiceCatalogEntry.voice_id == voice_id
                )
            )
        ).scalar_one()


# --- the sync ------------------------------------------------------------------------


@pytest.fixture
def clear_on_studio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A deployment that sells Clear on ThinnestAI's Studio band (needs Pro)."""
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("THINNEST_CLEAR_VOICE_BAND", "studio")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("THINNEST_CLEAR_VOICE_BAND", raising=False)
    get_settings.cache_clear()


async def test_a_thinnest_refresh_reads_the_hosted_lists_and_never_list_voices(
    hosted_rows: CatalogueRows,
) -> None:
    vendor_id = f"s{uuid.uuid4().hex[:8]}"
    hosted_rows.track(f"engine:{vendor_id}")
    engine = HostingEngine(
        hosted=[
            HostedVoice(
                voice_id=vendor_id, label="Priya", source="engine", language="hi", band="premium"
            )
        ],
        key_state=OFF_KEY,
    )

    async def _never() -> Any:
        raise AssertionError("list_voices must not be called on an engine that hosts voices")

    engine.list_voices = _never  # type: ignore[method-assign]
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, engine)
    assert result.written == 1 and result.complete
    assert result.note == hosted_voices.STUDIO_KEY_OFF_REASON
    assert engine.own_keys_listed == 0
    entry = await _entry(f"engine:{vendor_id}")
    assert (
        entry.provider,
        entry.tts_model,
        entry.origin,
        entry.curation_state,
        entry.vendor_band,
    ) == ("thinnest", "engine", "synced", "disabled", "premium")
    assert entry.languages == ["te-IN", "hi-IN", "en-IN"]


async def test_our_voice_key_on_adds_its_voices_and_prunes_what_left(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Studio voices are listed through a Studio client workspace (D-717)."""
    use_studio_workspace(monkeypatch)
    gone = await hosted_rows.add("byok", label="Old", origin="synced", state="disabled")
    kept = f"k{uuid.uuid4().hex[:8]}"
    hosted_rows.track(f"byok:{kept}")
    engine = HostingEngine(
        own_key=[HostedVoice(voice_id=kept, label="Meera", source="byok", language="te")]
    )
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, engine)
    assert engine.own_keys_listed == 1 and engine.listed_in == [STUDIO_WS]
    assert result.note is None and result.pruned >= 1
    assert (await _entry(gone)).withdrawn_at is not None
    fresh = await _entry(f"byok:{kept}")
    assert (fresh.provider, fresh.languages, fresh.withdrawn_at) == ("cartesia", ["te-IN"], None)


async def test_no_studio_workspace_ready_keeps_the_studio_voices_last_listed(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not being able to read the list is not the list being empty (D-717): the rows stay,
    and the developer workspace, whose switch is off, is never asked for them."""
    voice = await hosted_rows.add("byok")
    use_studio_workspace(monkeypatch)
    engine = HostingEngine(key_state=OFF_KEY)
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, engine)
        assert await hosted_voices.studio_voices_ready(session)
    assert result.note == hosted_voices.STUDIO_KEY_OFF_REASON
    assert engine.own_keys_listed == 0
    assert (await _entry(voice)).withdrawn_at is None


async def test_an_own_key_of_another_provider_is_not_synced(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_studio_workspace(monkeypatch)
    alerts: list[str] = []
    monkeypatch.setattr(hosted_voices, "alert", lambda stage, code, **kw: alerts.append(code))
    engine = HostingEngine(
        own_key=[HostedVoice(voice_id="x", label="X", source="byok")],
        own_key_provider="elevenlabs",
    )
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, engine)
    assert "studio_voice_key_wrong_provider" in alerts
    assert result.note is not None and "elevenlabs" in result.note


async def test_empty_listings_are_refused_and_alarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(
        hosted_voices, "alert", lambda stage, code, **kw: alerts.append(kw["source"])
    )
    use_studio_workspace(monkeypatch)
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, HostingEngine())
    assert result.written == 0 and alerts == ["engine", "byok"]


@pytest.mark.parametrize("status", [409, 502])
async def test_a_409_on_our_voices_is_a_stated_skip_and_an_outage_is_not(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_studio_workspace(monkeypatch)
    from apps.api.engine.vendor_http import EngineRejectedError

    engine = HostingEngine()

    async def _refused() -> Any:
        raise EngineRejectedError(status=status, vendor_error=None)

    engine.list_own_key_voices = _refused  # type: ignore[method-assign]
    async with admin_session() as session:
        if status == 409:
            result = await sync_voice_catalogue(session, engine)
            assert result.note == hosted_voices.STUDIO_KEY_OFF_REASON
        else:
            with pytest.raises(EngineRejectedError):
                await sync_voice_catalogue(session, engine)


async def test_a_pipecat_refresh_reads_no_hosted_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side: an engine that runs OUR voices never reaches the hosted sync."""

    async def _never(*a: Any, **k: Any) -> Any:
        raise AssertionError("the hosted sync ran on an engine that runs our voices")

    monkeypatch.setattr("apps.api.agents.voice_sync.sync_hosted_voices", _never)
    from apps.api.engine.pipecat import PipecatEngine

    async with admin_session() as session:
        result = await sync_voice_catalogue(session, PipecatEngine())
    assert result.skipped_reason is not None


# --- small pieces of the hosted catalogue -------------------------------------------


def test_the_rung_comes_from_the_billing_map_and_an_unsold_source_raises() -> None:
    assert rung_of_source("thinnest", "engine") == "clear"
    assert rung_of_source("thinnest", "byok") == "studio"
    with pytest.raises(ValueError):
        rung_of_source("pipecat", "engine")
    assert hosted_voices.source_rate_key("engine") == "premium"
    assert hosted_voices.source_rate_key("byok") == "byok_voice"


def test_the_band_sold_as_clear_follows_the_setting(clear_on_studio: None) -> None:
    from apps.api.billing.engine_minutes import client_rungs, client_voice_tier

    assert hosted_voices.sold_hosted_band() == "studio"
    assert client_rungs("thinnest") == {"studio": "clear", "byok_voice": "studio"}
    assert client_voice_tier("thinnest", "premium") is None
    assert hosted_voices.band_is_sold("engine", "studio")
    assert not hosted_voices.band_is_sold("engine", "premium")
    assert "Pro plan" in hosted_voices.no_sold_band_sentence(3)


def test_the_rate_card_holds_studio_back_until_our_voice_key_is_on() -> None:
    assert rungs_awaiting_setup("thinnest", studio_ready=False) == frozenset({"studio"})
    assert rungs_awaiting_setup("thinnest", studio_ready=True) == frozenset()
    assert rungs_awaiting_setup("pipecat", studio_ready=False) == frozenset()
    held = voice_tier_not_offered("thinnest", studio_ready=False)
    assert held is not None and held[0] == "studio"
    assert voice_tier_not_offered("thinnest", studio_ready=True) is None
    pipecat = voice_tier_not_offered("pipecat", studio_ready=False)
    assert pipecat is not None and pipecat[0] == "clear"


async def test_studio_is_on_sale_only_with_its_voices_listed_and_its_minute_attested(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from apps.api.billing import payment_routes

    now = datetime.now(UTC)
    attested: set[str] = set()

    async def _attested(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return frozenset(attested)

    monkeypatch.setattr(payment_routes, "attested_rate_keys", _attested)
    async with admin_session() as session:
        assert not await payment_routes._studio_on_sale(session, engine="pipecat", at=now)
        assert not await payment_routes._studio_on_sale(session, engine="thinnest", at=now)
        attested.add("byok_voice")
        await hosted_rows.add("byok")
        assert await payment_routes._studio_on_sale(session, engine="thinnest", at=now)


@pytest.mark.parametrize(
    ("voice_id", "accent", "note"),
    [
        ("engine:a", "hi", "Speaks the agent's language, with an accent: Hindi."),
        ("engine:a", "en-IN", "Speaks the agent's language, with an accent: Indian English."),
        ("engine:a", None, "Speaks the agent's language."),
        ("byok:a", "te", "Speaks Telugu."),
        ("byok:a", "xx-YY", "Speaks xx-YY."),
        ("byok:a", None, "The voice provider does not say which language."),
    ],
)
def test_the_language_note(voice_id: str, accent: str | None, note: str) -> None:
    row = PlatformVoiceCatalogEntry(voice_id=voice_id, engine_voice_id="a", accent=accent)
    assert language_note(row) == note


async def test_a_row_that_is_not_hosted_reads_as_absent() -> None:
    assert parse_hosted_voice_id("sonic-3.5:x") is None
    async with admin_session() as session:
        with pytest.raises(ProblemError):
            await read_hosted_voice(session, "sonic-3.5:x")
        with pytest.raises(ProblemError):
            await read_hosted_voice(session, "engine:nowhere")


# --- the panel -----------------------------------------------------------------------


async def test_the_panel_says_it_does_not_apply_on_an_engine_that_hosts_nothing(
    admin: dict[str, str],
) -> None:
    with selected(FakeEngine()):
        async with _client() as http:
            listed = await http.get("/v1/ops/voices/hosted", headers=admin)
            added = await http.post(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": "engine:x"}
            )
    assert listed.status_code == 200 and listed.json()["available"] is False
    assert added.json()["type"].rsplit("/", 1)[-1] == "voices_not_hosted"


async def test_a_client_cannot_reach_the_panel() -> None:
    async with _client() as http:
        response = await http.get(
            "/v1/ops/voices/hosted", headers={"Authorization": f"Bearer dev:client:{uuid.uuid4()}"}
        )
    assert response.status_code in {401, 403}


async def test_add_then_enable_puts_a_voice_on_offer(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    voice = await hosted_rows.add("engine", origin="synced", state="disabled", label="Rakesh")
    with selected(HostingEngine()):
        async with _client() as http:
            refused = await http.patch(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": voice, "state": "enabled"}
            )
            added = await http.post(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": voice}
            )
            enabled = await http.patch(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": voice, "state": "enabled"}
            )
            disabled = await http.patch(
                "/v1/ops/voices/hosted",
                headers=admin,
                json={"voice_id": voice, "state": "disabled"},
            )
            listed = await http.get("/v1/ops/voices/hosted?scope=all", headers=admin)
    assert (
        refused.status_code == 422
        and refused.json()["type"].rsplit("/", 1)[-1] == "voice_not_added"
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["voice"]["added"] and not body["voice"]["offered"]
    assert body["voice"]["rung"] == "clear" and "preview" in body["next_step"]
    assert enabled.json()["voice"]["offered"] is True
    assert "can now be chosen" in enabled.json()["next_step"]
    assert "can no longer be chosen" in disabled.json()["next_step"]
    rows = {v["voice_id"]: v for v in listed.json()["voices"]}
    assert voice in rows and listed.json()["available"] is True
    assert await _audits("ops.hosted_voice_added") >= 1


async def test_a_withdrawn_voice_cannot_be_added(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    voice = await hosted_rows.add("engine", origin="synced", withdrawn=True)
    with selected(HostingEngine()):
        async with _client() as http:
            response = await http.post(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": voice}
            )
    assert response.json()["type"].rsplit("/", 1)[-1] == "voice_withdrawn"


async def test_an_added_voice_with_a_preview_says_enable_next(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    voice = await hosted_rows.add("engine", origin="synced", state="disabled", preview=True)
    with selected(HostingEngine()):
        async with _client() as http:
            added = await http.post(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": voice}
            )
    assert added.json()["next_step"].endswith("Enable it to offer it to clients.")


# --- cloning ---------------------------------------------------------------------------


def _clone_form(**update: Any) -> dict[str, Any]:
    return {
        "name": "Founder",
        "consent_own_voice": "true",
        "consent_no_impersonation": "true",
        "language": "te",
        **update,
    }


async def test_a_clone_needs_the_confirmation_header(admin: dict[str, str]) -> None:
    with selected(HostingEngine()):
        async with _client() as http:
            response = await http.post(
                "/v1/ops/voices/clones",
                headers=admin,
                data=_clone_form(),
                files={"sample": ("a.wav", WAV, "audio/wav")},
            )
    assert response.json()["type"].rsplit("/", 1)[-1] == "step_up_required"


async def _clone(
    headers: dict[str, str],
    *,
    form: dict[str, Any] | None = None,
    sample: tuple[str, bytes, str] = ("founder.wav", WAV, "audio/wav"),
) -> Response:
    async with _client() as http:
        return await http.post(
            "/v1/ops/voices/clones",
            headers={**headers, "X-Confirm-Action": routes.CLONE_CONFIRMATION},
            data=form or _clone_form(),
            files={"sample": sample},
        )


async def test_a_clone_is_saved_added_disabled_with_its_preview_and_the_consents_audited(
    admin: dict[str, str], previews: dict[str, bytes], hosted_rows: CatalogueRows
) -> None:
    engine = HostingEngine()
    with selected(engine):
        response = await _clone(admin)
    assert response.status_code == 201, response.text
    body = response.json()
    hosted_rows.track(body["voice"]["voice_id"])
    voice = body["voice"]
    assert (voice["added"], voice["state"], voice["is_custom"], voice["deletable_clone"]) == (
        True,
        "disabled",
        True,
        True,
    )
    assert voice["preview_available"] and voice["preview_source"] == "vendor"
    assert "Listen to its preview" in body["next_step"]
    assert len(previews) == 1
    # The consents are the operator's: the clone is refused without both, and the audit row
    # records who gave them and when.
    async with untenanted_session() as session:
        actor = (
            await session.execute(
                text(
                    "SELECT actor_id FROM audit_log WHERE action = 'ops.voice_cloned' "
                    "AND object_id = :v"
                ),
                {"v": voice["voice_id"]},
            )
        ).scalar_one()
    assert actor is not None


async def test_a_clone_whose_preview_cannot_be_fetched_is_kept_and_asks_for_an_upload(
    admin: dict[str, str],
    previews: dict[str, bytes],
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = HostingEngine()
    real = engine.create_voice_clone

    async def _no_plan(sample: Any) -> Any:
        clone = await real(sample)
        return clone.model_copy(
            update={"preview_url": "https://files.example.com/broken", "usable_on_agents": False}
        )

    monkeypatch.setattr(engine, "create_voice_clone", _no_plan)
    with selected(engine):
        response = await _clone(admin)
    body = response.json()
    hosted_rows.track(body["voice"]["voice_id"])
    assert response.status_code == 201 and not body["voice"]["preview_available"]
    assert "Upload a preview" in body["next_step"] and "plan" in body["next_step"]


@pytest.mark.parametrize(
    ("form", "sample", "code"),
    [
        (
            _clone_form(consent_no_impersonation="false"),
            ("a.wav", WAV, "audio/wav"),
            "voice_clone_consent_missing",
        ),
        (_clone_form(), ("a.txt", b"hello", "text/plain"), "voice_clone_sample_format"),
        (_clone_form(), ("a.wav", b"", "audio/wav"), "voice_upload_empty"),
        (
            _clone_form(),
            ("a.wav", b"\0" * (MAX_BODY_BYTES + 1), "audio/wav"),
            "payload_too_large",
        ),
    ],
)
async def test_a_clone_request_that_cannot_be_sent_is_refused(
    admin: dict[str, str], form: dict[str, Any], sample: tuple[str, bytes, str], code: str
) -> None:
    engine = HostingEngine()
    with selected(engine):
        response = await _clone(admin, form=form, sample=sample)
    assert response.json()["type"].rsplit("/", 1)[-1] == code and engine.clones == {}


async def test_deleting_a_clone_warns_about_live_agents_then_withdraws_it(
    admin: dict[str, str], hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = await hosted_rows.add("engine", clone_id="vc_1")
    plain = await hosted_rows.add("engine")

    async def _live() -> dict[str, int]:
        return {voice: 2}

    monkeypatch.setattr(routes, "count_live_agents_by_engine_voice", _live)
    engine = HostingEngine()
    engine.moved = 2

    async def _delete(voice_id: str, *, confirm: bool = False) -> Response:
        async with _client() as http:
            return await http.delete(
                "/v1/ops/voices/clones",
                headers={**admin, "X-Confirm-Action": routes.delete_clone_confirmation(voice_id)},
                params={"voice_id": voice_id, "confirm": str(confirm).lower()},
            )

    with selected(engine):
        not_a_clone = await _delete(plain)
        warned = await _delete(voice)
        done = await _delete(voice, confirm=True)
    assert not_a_clone.json()["type"].rsplit("/", 1)[-1] == "voice_not_a_clone"
    assert (
        warned.status_code == 409
        and warned.json()["type"].rsplit("/", 1)[-1] == "voice_clone_in_use"
    )
    assert done.status_code == 200 and done.json()["moved_agents"] == 2
    assert "moved 2 agent(s)" in done.json()["next_step"]
    entry = await _entry(voice)
    assert entry.withdrawn_at is not None and entry.curation_state == "archived"


async def test_deleting_an_unused_clone_says_no_agent_was_on_it(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    voice = await hosted_rows.add("engine", clone_id="vc_2")
    with selected(HostingEngine()):
        async with _client() as http:
            done = await http.delete(
                "/v1/ops/voices/clones",
                headers={**admin, "X-Confirm-Action": routes.delete_clone_confirmation(voice)},
                params={"voice_id": voice},
            )
    assert done.json()["next_step"] == "The clone was deleted. No agent was on it."


# --- previews ----------------------------------------------------------------------------


async def test_an_uploaded_preview_must_be_mp3_or_wav(
    admin: dict[str, str], previews: dict[str, bytes], hosted_rows: CatalogueRows
) -> None:
    voice = await hosted_rows.add("engine")
    with selected(HostingEngine()):
        async with _client() as http:
            refused = await http.post(
                "/v1/ops/voices/hosted/preview",
                headers=admin,
                data={"voice_id": voice},
                files={"sample": ("a.ogg", b"OggS....", "audio/ogg")},
            )
            stored = await http.post(
                "/v1/ops/voices/hosted/preview",
                headers=admin,
                data={"voice_id": voice},
                files={"sample": ("a.wav", WAV, "audio/wav")},
            )
    assert refused.json()["type"].rsplit("/", 1)[-1] == "voice_preview_format"
    assert stored.status_code == 200, stored.text
    assert stored.json()["voice"]["preview_source"] == "upload"
    assert previews == {storage.voice_preview_key(voice): WAV}


async def test_a_studio_preview_needs_a_studio_client_workspace(
    admin: dict[str, str], hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Our developer workspace's switch is off, where the vendor refuses a preview with 409
    (preview-byok-voice.md:396-397), so with no Studio client the preview is refused here."""

    async def _none(*, limit: int = 1000) -> list[Any]:
        return []

    monkeypatch.setattr(hosted_voices, "studio_workspaces", _none)
    studio = await hosted_rows.add("byok")
    engine = HostingEngine()
    with selected(engine):
        async with _client() as http:
            response = await http.post(
                "/v1/ops/voices/hosted/preview/fetch",
                headers=admin,
                json={"voice_id": studio, "text": "Namaste"},
            )
    assert response.json()["type"].rsplit("/", 1)[-1] == "studio_preview_no_workspace"
    assert engine.previews == []


async def test_the_platforms_own_preview_is_stored_for_a_studio_voice_and_a_clone(
    admin: dict[str, str],
    previews: dict[str, bytes],
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Studio voice is spoken in a Studio client's workspace: ours is off (D-717)."""
    use_studio_workspace(monkeypatch)
    engine = HostingEngine()
    clone = await engine.create_voice_clone(
        routes.VoiceCloneSample(
            filename="a",
            content_type="audio/wav",
            data=WAV,
            name="F",
            consent_own_voice=True,
            consent_no_impersonation=True,
        )
    )
    cloned = await hosted_rows.add("engine", vendor_id=clone.voice_id, clone_id=clone.clone_id)
    studio = await hosted_rows.add("byok")
    stock = await hosted_rows.add("engine")
    with selected(engine):
        async with _client() as http:
            responses = [
                await http.post(
                    "/v1/ops/voices/hosted/preview/fetch",
                    headers=admin,
                    json={"voice_id": voice_id, "text": "Namaste", "language": "te-IN"},
                )
                for voice_id in (studio, cloned, stock)
            ]
    assert [r.status_code for r in responses[:2]] == [200, 200]
    assert engine.previews == [studio.removeprefix("byok:")]
    assert responses[2].json()["type"].rsplit("/", 1)[-1] == "voice_preview_unavailable"


def test_the_preview_sniff_reads_mp3_and_wav_only() -> None:
    assert routes.sniff_preview_type(MP3) == "audio/mpeg"
    assert routes.sniff_preview_type(b"\xff\xfb\x90\x00") == "audio/mpeg"
    assert routes.sniff_preview_type(WAV) == "audio/wav"
    assert routes.sniff_preview_type(b"OggS") is None


async def test_a_clone_with_no_preview_link_asks_for_an_upload(
    admin: dict[str, str],
    previews: dict[str, bytes],
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = HostingEngine()
    real = engine.create_voice_clone

    async def _no_link(sample: Any) -> Any:
        return (await real(sample)).model_copy(update={"preview_url": None})

    monkeypatch.setattr(engine, "create_voice_clone", _no_link)
    with selected(engine):
        response = await _clone(admin)
    body = response.json()
    hosted_rows.track(body["voice"]["voice_id"])
    assert not body["voice"]["preview_available"] and previews == {}
    assert "Upload a preview" in body["next_step"]


# --- Studio voices: our Cartesia key in the workspace (D-688) -----------------------------


@pytest.fixture
def cartesia_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    get_settings.cache_clear()


async def _routes_for(
    engine_refs: dict[str, str], *, workspace: str | None = None
) -> tuple[UUID, list[tuple[str, str]]]:
    """A new tenant with active `engine_agent_routes` rows (`{ref: rate_key}`), and, given
    `workspace`, an active voice workspace row for it."""
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Studio Switch",
        slug=f"ss-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant, agent = created["id"], created["agent_id"]
    rows: list[tuple[str, str]] = []
    async with tenant_session(tenant) as session:
        if workspace is not None:
            await session.execute(
                text(
                    "INSERT INTO tenant_engine_workspaces (id, tenant_id, engine, external_ref, "
                    "workspace_id, status, created_at, updated_at) VALUES (:id, :tid, "
                    "'thinnest', :ref, :ws, 'active', now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": tenant, "ref": f"calevate-{tenant}", "ws": workspace},
            )
        for ref, rate_key in engine_refs.items():
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, engine_rate_key, created_at, updated_at) VALUES "
                    "('thinnest', :ref, :tid, :aid, true, :key, now(), now())"
                ),
                {"ref": ref, "tid": tenant, "aid": agent, "key": rate_key},
            )
            rows.append((ref, rate_key))
    return tenant, rows


async def _drop_routes(refs: list[str], tenant: UUID | None = None) -> None:
    async with admin_session() as session:
        await session.execute(
            text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = ANY(:refs)"),
            {"refs": refs},
        )
        if tenant is not None:
            await session.execute(
                text("DELETE FROM tenant_engine_workspaces WHERE tenant_id = :tid"),
                {"tid": tenant},
            )


def _only_routes_of(monkeypatch: pytest.MonkeyPatch, tenant: UUID) -> None:
    """The route table is global and other tests leave rows in it; the developer-switch
    check reads every tenant's, so these tests see only their own."""
    from apps.api.agents import studio_voices as studio_module

    real = studio_module.published_routes

    async def _mine(session: Any, *, engine: str) -> list[Any]:
        return [r for r in await real(session, engine=engine) if r.tenant_id == tenant]

    monkeypatch.setattr(studio_module, "published_routes", _mine)


def _ws() -> str:
    return f"org_ss{uuid.uuid4().hex[:10]}"


async def test_studio_readiness_says_what_is_missing_and_that_the_developer_switch_stays_off(
    admin: dict[str, str],
) -> None:
    with selected(HostingEngine(key_state=OFF_KEY)):
        async with _client() as http:
            bare = (await http.get("/v1/ops/voices/studio-voices", headers=admin)).json()
    held = OFF_KEY.model_copy(update={"voice_provider": "cartesia"})
    with selected(HostingEngine(key_state=held)):
        async with _client() as http:
            holding = (await http.get("/v1/ops/voices/studio-voices", headers=admin)).json()
    with selected(HostingEngine(key_state=READY_KEY)):
        async with _client() as http:
            legacy = (await http.get("/v1/ops/voices/studio-voices", headers=admin)).json()
    assert bare["ready"] is False and bare["developer_holds_key"] is False
    assert any("Studio ready" in step for step in bare["missing"])
    assert holding["developer_holds_key"] is True and holding["developer_switch_on"] is False
    assert "switch off" in holding["explanation"]
    assert legacy["developer_switch_on"] is True and "ON" in legacy["note"]


async def test_studio_ready_holds_our_key_in_the_developer_workspace_and_never_switches_it_on(
    admin: dict[str, str], cartesia_key: None
) -> None:
    engine = HostingEngine(key_state=OFF_KEY)
    with selected(engine):
        async with _client() as http:
            refused = await http.post("/v1/ops/voices/studio-voices/enable", headers=admin, json={})
            done = await http.post(
                "/v1/ops/voices/studio-voices/enable",
                headers={**admin, "X-Confirm-Action": routes.STUDIO_ENABLE_CONFIRMATION},
                json={"model": "sonic-3"},
            )
    assert refused.json()["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert done.status_code == 200, done.text
    assert engine.installed == [("cartesia", "sonic-3")] and engine.installed_in == [None]
    assert engine.enabled == 0 and engine.key_state.enabled is False
    assert done.json()["developer_holds_key"] is True
    assert await _audits("ops.studio_voices_prepared") >= 1


async def test_studio_ready_needs_our_cartesia_key(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings

    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    get_settings.cache_clear()
    engine = HostingEngine(key_state=OFF_KEY)
    try:
        with selected(engine):
            async with _client() as http:
                missing = await http.post(
                    "/v1/ops/voices/studio-voices/enable",
                    headers={**admin, "X-Confirm-Action": routes.STUDIO_ENABLE_CONFIRMATION},
                    json={},
                )
    finally:
        get_settings.cache_clear()
    assert missing.json()["type"].rsplit("/", 1)[-1] == "studio_voice_key_missing"
    assert engine.installed == [] and engine.enabled == 0


async def test_naming_a_client_switches_studio_on_in_its_workspace_with_clear_agents_off_first(
    admin: dict[str, str], cartesia_key: None
) -> None:
    ws = _ws()
    clear, studio = f"ag_{uuid.uuid4().hex[:8]}@{ws}", f"ag_{uuid.uuid4().hex[:8]}@{ws}"
    elsewhere = f"ag_{uuid.uuid4().hex[:8]}"
    tenant, _ = await _routes_for(
        {clear: "premium", studio: "byok_voice", elsewhere: "premium"}, workspace=ws
    )
    engine = HostingEngine(key_state=OFF_KEY)
    engine.workspace_keys[ws] = OFF_KEY
    engine.own_voice_key[clear] = True
    engine.own_voice_key[elsewhere] = True
    try:
        with selected(engine):
            async with _client() as http:
                done = await http.post(
                    "/v1/ops/voices/studio-voices/enable",
                    headers={**admin, "X-Confirm-Action": routes.STUDIO_ENABLE_CONFIRMATION},
                    json={"tenant_id": str(tenant)},
                )
        async with tenant_session(tenant) as session:
            enabled_at = (
                await session.execute(
                    text(
                        "SELECT studio_enabled_at FROM tenant_engine_workspaces "
                        "WHERE tenant_id = :tid"
                    ),
                    {"tid": tenant},
                )
            ).scalar_one()
    finally:
        await _drop_routes([clear, studio, elsewhere], tenant)
    assert done.status_code == 200, done.text
    assert engine.own_voice_key[clear] is False and studio not in engine.own_voice_key
    # An agent outside that workspace is not this switch's business.
    assert engine.own_voice_key[elsewhere] is True
    assert engine.installed_in == [None, ws] and engine.enabled == 1
    assert engine.workspace_keys[ws].speaks_on_own_voice
    assert engine.key_state.enabled is False
    assert enabled_at is not None


@pytest.mark.parametrize("failure", ["refused", "stuck"])
async def test_a_client_workspace_is_not_switched_on_while_a_clear_agent_cannot_be_kept_off(
    admin: dict[str, str], cartesia_key: None, failure: str
) -> None:
    ws = _ws()
    clear = f"ag_{uuid.uuid4().hex[:8]}@{ws}"
    tenant, _ = await _routes_for({clear: "premium"}, workspace=ws)
    engine = HostingEngine(key_state=OFF_KEY)
    engine.workspace_keys[ws] = OFF_KEY
    engine.own_voice_key[clear] = True
    (engine.refuse_switch if failure == "refused" else engine.stuck_switch).add(clear)
    try:
        with selected(engine):
            async with _client() as http:
                response = await http.post(
                    "/v1/ops/voices/studio-voices/enable",
                    headers={**admin, "X-Confirm-Action": routes.STUDIO_ENABLE_CONFIRMATION},
                    json={"tenant_id": str(tenant)},
                )
    finally:
        await _drop_routes([clear], tenant)
    assert response.json()["type"].rsplit("/", 1)[-1] == "studio_agents_not_kept_off"
    assert engine.installed_in == [None] and engine.enabled == 0


async def test_the_developer_switch_goes_off_only_once_no_studio_agent_depends_on_it(
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _ws()
    on_developer = f"ag_{uuid.uuid4().hex[:8]}"
    on_client = f"ag_{uuid.uuid4().hex[:8]}@{ws}"
    tenant, _ = await _routes_for({on_developer: "byok_voice", on_client: "byok_voice"})
    _only_routes_of(monkeypatch, tenant)
    engine = HostingEngine(key_state=READY_KEY)
    engine.workspace_keys[ws] = READY_KEY
    headers = {**admin, "X-Confirm-Action": routes.STUDIO_DISABLE_CONFIRMATION}
    try:
        with selected(engine):
            async with _client() as http:
                blocked = await http.post("/v1/ops/voices/studio-voices/disable", headers=headers)
                async with tenant_session(tenant) as session:
                    await session.execute(
                        text(
                            "UPDATE engine_agent_routes SET active = false "
                            "WHERE engine_agent_ref = :ref"
                        ),
                        {"ref": on_developer},
                    )
                done = await http.post("/v1/ops/voices/studio-voices/disable", headers=headers)
    finally:
        await _drop_routes([on_developer, on_client], tenant)
    assert blocked.json()["type"].rsplit("/", 1)[-1] == "studio_clients_not_moved"
    assert "developer workspace" in blocked.json()["detail"]
    assert done.status_code == 200, done.text
    assert engine.disabled == 1 and done.json()["developer_switch_on"] is False
    assert engine.workspace_keys[ws].speaks_on_own_voice
    assert await _audits("ops.studio_developer_switch_off") >= 1


async def test_a_client_workspace_inheriting_ours_also_blocks_the_developer_switch_off(
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _ws()
    studio = f"ag_{uuid.uuid4().hex[:8]}@{ws}"
    tenant, _ = await _routes_for({studio: "byok_voice"})
    _only_routes_of(monkeypatch, tenant)
    engine = HostingEngine(key_state=READY_KEY)
    # Inheriting ours rather than on its own key: switching ours off would silence it.
    engine.workspace_keys[ws] = READY_KEY.model_copy(update={"using": "developer"})
    try:
        with selected(engine):
            async with _client() as http:
                blocked = await http.post(
                    "/v1/ops/voices/studio-voices/disable",
                    headers={**admin, "X-Confirm-Action": routes.STUDIO_DISABLE_CONFIRMATION},
                )
    finally:
        await _drop_routes([studio], tenant)
    assert blocked.json()["type"].rsplit("/", 1)[-1] == "studio_clients_not_moved"
    assert engine.disabled == 0


# --- the operator's preview player ---------------------------------------------------


@pytest.fixture
def stored_audio(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes | None]:
    objects: dict[str, bytes | None] = {}

    async def _read(key: str) -> bytes | None:
        return objects.get(key, MP3)

    monkeypatch.setattr(storage, "read_voice_preview", _read)
    return objects


async def test_an_operator_plays_any_hosted_voice_from_the_console(
    admin: dict[str, str], hosted_rows: CatalogueRows, stored_audio: dict[str, bytes | None]
) -> None:
    """Added or not, enabled or not: the console has no tenant, so it cannot use the client
    route, and an operator previews a voice BEFORE deciding to offer it."""
    synced = await hosted_rows.add("engine", origin="synced", state="disabled", preview=True)
    archived = await hosted_rows.add("byok", state="archived", preview=True)
    async with _client() as http:
        for voice_id in (synced, archived):
            response = await http.get(
                "/v1/ops/voices/hosted/preview", headers=admin, params={"voice_id": voice_id}
            )
            assert response.status_code == 200, response.text
            assert response.content == MP3
            assert response.headers["content-type"] == "audio/mpeg"
            assert response.headers["cache-control"] == "private, max-age=3600"


@pytest.mark.parametrize("case", ["no_preview", "unknown", "object_gone"])
async def test_an_operator_preview_that_cannot_be_served_is_a_404(
    admin: dict[str, str],
    hosted_rows: CatalogueRows,
    stored_audio: dict[str, bytes | None],
    case: str,
) -> None:
    if case == "no_preview":
        voice_id = await hosted_rows.add("engine")
    elif case == "unknown":
        voice_id = "engine:does-not-exist"
    else:
        voice_id = await hosted_rows.add("engine", preview=True)
        stored_audio[f"voice-previews/{voice_id}"] = None
    async with _client() as http:
        response = await http.get(
            "/v1/ops/voices/hosted/preview", headers=admin, params={"voice_id": voice_id}
        )
    assert response.status_code == 404


@pytest.mark.parametrize("token", [None, "client"])
async def test_the_operator_preview_refuses_a_client_and_nobody(
    hosted_rows: CatalogueRows, stored_audio: dict[str, bytes | None], token: str | None
) -> None:
    voice_id = await hosted_rows.add("engine", state="disabled", preview=True)
    headers = {"Authorization": f"Bearer dev:client:{uuid.uuid4()}"} if token == "client" else {}
    async with _client() as http:
        response = await http.get(
            "/v1/ops/voices/hosted/preview", headers=headers, params={"voice_id": voice_id}
        )
    assert response.status_code in {401, 403}


# --- bands: every band cached, only the band sold as Clear offered (D-687, D-688) -----


def _no_stranded_studio_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Other suites leave Studio routes in the shared database; this test is about bands."""

    async def _none(session: Any, *, engine: str) -> int:
        return 0

    monkeypatch.setattr(hosted_voices, "live_studio_agents", _none)


def _voice(band: HostedVoiceBand | None, *, label: str = "V") -> HostedVoice:
    vendor_id = f"b{uuid.uuid4().hex[:10]}"
    return HostedVoice(voice_id=vendor_id, label=label, source="engine", band=band)


async def test_a_listing_without_the_sold_band_is_cached_and_raises_the_plan_alarm(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_stranded_studio_agents(monkeypatch)
    alerts: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        hosted_voices,
        "alert",
        lambda stage, code, **kw: alerts.append((code, kw.get("detail"))),
    )
    standard, studio = _voice("standard", label="Anjali"), _voice("studio", label="Rakesh")
    for voice in (standard, studio):
        hosted_rows.track(f"engine:{voice.voice_id}")
    async with admin_session() as session:
        result = await sync_voice_catalogue(
            session, HostingEngine(hosted=[standard, studio], key_state=OFF_KEY)
        )
    assert result.hosted is not None and result.hosted.sold_band_missing
    assert result.written == 2
    assert dict(result.hosted.bands) == {"standard": 1, "studio": 1}
    assert [code for code, _ in alerts] == [hosted_voices.NO_SOLD_BAND_CODE]
    detail = alerts[0][1] or ""
    assert "none in the ThinnestAI Premium band" in detail
    assert "ThinnestAI voice band sold as Clear" in detail
    assert "credential" not in detail
    assert (await _entry(f"engine:{standard.voice_id}")).vendor_band == "standard"
    assert (await _entry(f"engine:{studio.voice_id}")).vendor_band == "studio"


async def test_a_listing_with_nothing_at_all_still_raises_the_empty_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_stranded_studio_agents(monkeypatch)
    codes: list[str] = []
    monkeypatch.setattr(hosted_voices, "alert", lambda stage, code, **kw: codes.append(code))
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, HostingEngine(key_state=OFF_KEY))
    assert codes == ["voice_catalogue_empty"]
    assert result.hosted is not None and not result.hosted.sold_band_missing


async def _refresh_on(engine: HostingEngine, admin: dict[str, str]) -> dict[str, Any]:
    with selected(engine):
        async with _client() as http:
            response = await http.post("/v1/ops/voices/refresh", headers=admin)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_thinnest_refresh_without_the_sold_band_names_the_setting_not_the_credential(
    admin: dict[str, str], hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_voices, "alert", lambda *a, **k: None)
    voices = [_voice("standard"), _voice("standard"), _voice("studio")]
    for voice in voices:
        hosted_rows.track(f"engine:{voice.voice_id}")
    body = await _refresh_on(HostingEngine(hosted=voices, key_state=OFF_KEY), admin)
    note = body["note"]
    assert note.startswith(
        "ThinnestAI listed 3 voice(s) but none in the ThinnestAI Premium band, the band sold as "
        "Clear ('ThinnestAI voice band sold as Clear' in the ops console)."
    )
    assert "ThinnestAI bands 2 Standard, 0 Premium, 1 Studio" in note
    assert "credential" not in note and "previous catalogue" not in note
    assert body["bands"] == {"standard": 2, "studio": 1}


async def test_on_studio_a_refresh_with_no_studio_voices_names_the_pro_plan(
    admin: dict[str, str],
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
    clear_on_studio: None,
) -> None:
    monkeypatch.setattr(hosted_voices, "alert", lambda *a, **k: None)
    voices = [_voice("standard"), _voice("premium"), _voice("premium")]
    for voice in voices:
        hosted_rows.track(f"engine:{voice.voice_id}")
    body = await _refresh_on(HostingEngine(hosted=voices, key_state=OFF_KEY), admin)
    assert body["note"].startswith(
        "ThinnestAI listed 3 voice(s) but none in the ThinnestAI Studio band"
    )
    assert hosted_voices.STUDIO_NEEDS_PRO in body["note"]
    # The free preview voice and the Cartesia switch are the two things an operator reaches
    # for; the sentence rules out both.
    assert "listening sample" in body["note"]
    assert "Switching on Studio voices (our Cartesia key) does not change this" in body["note"]
    assert "credential" not in body["note"]


async def test_a_voice_in_a_tier_the_adapter_does_not_read_is_named_in_the_refresh(
    admin: dict[str, str], hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_voices, "alert", lambda *a, **k: None)
    voices = [_voice("premium")]
    for voice in voices:
        hosted_rows.track(f"engine:{voice.voice_id}")
    engine = HostingEngine(hosted=voices, key_state=OFF_KEY)
    engine.unread_bands = {"studio_preview": 1}
    body = await _refresh_on(engine, admin)
    assert (
        "Also listed in a tier we do not read, so not cached or sellable: 1 in 'studio_preview'."
        in body["note"]
    )


async def test_clear_cannot_move_to_a_band_the_last_refresh_did_not_list(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pay-as-you-go lists no Studio voice, so selling Clear on Studio would sell nothing.
    Refused before the per-key lock, so nothing is written."""
    from apps.api.ops import config_service

    _no_stranded_studio_agents(monkeypatch)
    monkeypatch.setattr(hosted_voices, "alert", lambda *a, **k: None)
    voices = [_voice("standard"), _voice("premium")]
    for voice in voices:
        hosted_rows.track(f"engine:{voice.voice_id}")
    async with admin_session() as session:
        await sync_voice_catalogue(session, HostingEngine(hosted=voices, key_state=OFF_KEY))
        await session.commit()
    _, admin_id = await _admin()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await config_service.set_value(
                session,
                key="thinnest_clear_voice_band",
                value="studio",
                note="hosted_voice_routes_test",
                actor_id=admin_id,
                expected_revision=0,
            )
        stored = (
            await session.execute(
                text("SELECT count(*) FROM platform_settings WHERE key = :k"),
                {"k": "thinnest_clear_voice_band"},
            )
        ).scalar_one()
    assert raised.value.code == "voice_band_not_listed"
    assert hosted_voices.STUDIO_NEEDS_PRO in (raised.value.detail or "")
    assert stored == 0


@pytest.mark.parametrize(
    ("bands", "band"),
    [({}, "studio"), ({"premium": 2, "studio": 1}, "studio"), ({"premium": 2}, "premium")],
)
async def test_a_band_is_allowed_when_listed_or_when_nothing_was_ever_read(
    monkeypatch: pytest.MonkeyPatch, bands: dict[str, int], band: str
) -> None:
    async def _bands(_: Any) -> dict[str, int]:
        return bands

    monkeypatch.setattr(hosted_voices, "count_listed_bands", _bands)
    await hosted_voices.assert_clear_band_listed(object(), band)  # type: ignore[arg-type]


async def test_a_thinnest_refresh_with_the_sold_band_counts_each_band(
    admin: dict[str, str], hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_voices, "alert", lambda *a, **k: None)
    voices = [_voice("standard"), _voice("premium")]
    for voice in voices:
        hosted_rows.track(f"engine:{voice.voice_id}")
    body = await _refresh_on(HostingEngine(hosted=voices, key_state=OFF_KEY), admin)
    assert body["note"].startswith(
        "ThinnestAI listed 2 voice(s): ThinnestAI bands 1 Standard, 1 Premium, 0 Studio. Only "
        "ThinnestAI Premium band voices can be offered as Clear."
    )
    assert f"Studio voices: {hosted_voices.STUDIO_KEY_OFF_REASON}." in body["note"]
    assert body["bands"] == {"standard": 1, "premium": 1}


async def test_a_thinnest_refresh_of_an_empty_listing_does_not_blame_the_credential(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_voices, "alert", lambda *a, **k: None)
    body = await _refresh_on(HostingEngine(key_state=OFF_KEY), admin)
    assert "listed no voices at all" in body["note"]
    assert "credential" not in body["note"] and "previous catalogue" not in body["note"]
    assert body["bands"] == {}


def test_the_pipecat_refresh_sentences_are_unchanged() -> None:
    """The other side: the Pipecat note is word for word what it was before the bands."""
    from apps.api.agents.voice_sync import VoiceSyncResult
    from apps.api.ops.routes import _voice_refresh_note

    empty = VoiceSyncResult(seen=3, written=0, pruned=None, complete=True)
    assert _voice_refresh_note(empty, in_force=405) == (
        "The voice platform returned no usable voices, so nothing was changed and the "
        "previous catalogue (405 voice(s)) is still being offered. Check the voice platform "
        "credential in the ops console, then try again."
    )
    done = VoiceSyncResult(seen=3, written=3, pruned=1, complete=True)
    assert _voice_refresh_note(done, in_force=3) == (
        "3 voice(s) cached and 1 withdrawn by the voice platform. 3 voice(s) are in the "
        "catalogue — a newly seen voice arrives disabled, so enable the ones clients should "
        "be able to choose."
    )
    assert empty.hosted is None


async def test_a_refresh_on_an_engine_that_runs_our_voices_reports_no_bands(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An engine that does not host voices gets the Pipecat-shaped answer, with no bands."""
    from apps.api.agents.voice_sync import VoiceSyncResult

    async def _sync(session: Any, engine: Any, **kw: Any) -> VoiceSyncResult:
        return VoiceSyncResult(seen=2, written=0, pruned=None, complete=True)

    monkeypatch.setattr("apps.api.ops.routes.sync_voice_catalogue", _sync)
    with selected(FakeEngine()):
        async with _client() as http:
            response = await http.post("/v1/ops/voices/refresh", headers=admin)
    body = response.json()
    assert body["bands"] is None
    assert body["note"].startswith("The voice platform returned no usable voices")
    assert "previous catalogue" in body["note"]


async def test_a_voice_outside_the_sold_band_cannot_be_added_and_is_shown_why(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    standard = await hosted_rows.add(
        "engine", origin="synced", state="disabled", label="Anjali", band="standard"
    )
    with selected(HostingEngine()):
        async with _client() as http:
            refused = await http.post(
                "/v1/ops/voices/hosted", headers=admin, json={"voice_id": standard}
            )
            listed = await http.get("/v1/ops/voices/hosted?scope=all", headers=admin)
    problem = refused.json()
    assert refused.status_code == 422
    assert problem["type"].rsplit("/", 1)[-1] == "voice_band_not_sold"
    assert "Only ThinnestAI Premium band voices are sold as Clear" in problem["detail"]
    assert "Anjali is in the ThinnestAI Standard band" in problem["detail"]
    assert "ThinnestAI voice band sold as Clear" in problem["remediation"]
    assert (await _entry(standard)).origin == "synced"
    body = listed.json()
    row = {v["voice_id"]: v for v in body["voices"]}[standard]
    assert (row["band"], row["sold"], row["rung"]) == ("standard", False, None)
    assert "Only ThinnestAI Premium band voices" in row["not_sold_reason"]
    assert body["bands"].get("standard", 0) >= 1 and body["clear_band"] == "premium"


async def test_an_added_voice_the_platform_moved_out_of_the_band_cannot_be_enabled_or_offered(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    moved = await hosted_rows.add("engine", state="enabled", band="standard")
    unbanded = await hosted_rows.add("engine", state="enabled", band=None)
    async with admin_session() as session:
        rows = {r.voice_id for r in await hosted_voices.offered_hosted_voices(session)}
        assert moved not in rows and unbanded not in rows
        row = await read_hosted_voice(session, moved)
        assert not row.sold and not row.offered and row.rate_key == "standard"
        with pytest.raises(ProblemError) as caught:
            await hosted_voices.set_hosted_curation(session, voice_id=unbanded, state="enabled")
        assert (await read_hosted_voice(session, unbanded)).rate_key == "premium"
    assert caught.value.code == "voice_band_not_sold"
    assert caught.value.detail is not None and "no band we sell" in caught.value.detail
    with selected(HostingEngine()):
        async with _client() as http:
            response = await http.patch(
                "/v1/ops/voices/hosted",
                headers=admin,
                json={"voice_id": moved, "state": "enabled"},
            )
    assert response.json()["type"].rsplit("/", 1)[-1] == "voice_band_not_sold"


async def test_the_panel_explains_a_platform_with_none_of_the_sold_band(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _bands(session: Any) -> dict[str, int]:
        return {"standard": 4, "studio": 2}

    monkeypatch.setattr(routes, "count_listed_bands", _bands)
    with selected(HostingEngine()):
        async with _client() as http:
            body = (await http.get("/v1/ops/voices/hosted", headers=admin)).json()
    assert body["bands"] == {"standard": 4, "studio": 2}
    assert body["plan_note"].startswith(
        "ThinnestAI listed 6 voice(s) but none in the ThinnestAI Premium band"
    )


async def test_the_panel_says_nothing_about_the_plan_when_the_sold_band_is_listed(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    await hosted_rows.add("engine", origin="synced", state="disabled", band="premium")
    with selected(HostingEngine()):
        async with _client() as http:
            body = (await http.get("/v1/ops/voices/hosted", headers=admin)).json()
    assert body["bands"].get("premium", 0) >= 1 and body["plan_note"] is None


async def test_a_clone_is_recorded_in_the_studio_band_and_sold_only_on_studio(
    hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    vendor_id = f"c{uuid.uuid4().hex[:8]}"
    hosted_rows.track(f"engine:{vendor_id}")
    async with admin_session() as session:
        row = await hosted_voices.record_clone(
            session,
            engine="thinnest",
            vendor_voice_id=vendor_id,
            clone_id="vc_1",
            label="Mine",
            language=None,
            description=None,
        )
        await session.commit()
    assert row.band == "studio" and not row.sold
    monkeypatch.setattr(hosted_voices, "sold_hosted_band", lambda: "studio")
    assert row.sold
