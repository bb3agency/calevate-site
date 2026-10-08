"""The admin Voices panel and the catalogue sync on an engine that hosts its voices (D-687).

Admin-only (`ops:manage`), audited; cloning, deleting a clone and setting up the Studio
workspace are step-up confirmed. The sync reads the engine's own Studio band and, once a
Studio workspace exists, our own-key voices there — never `list_voices`, which refuses on
this engine — and the Pipecat path is untouched: a Pipecat refresh reads no hosted list.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import hosted_voices
from apps.api.agents.hosted_voices import (
    HostedVoiceRef,
    language_note,
    parse_hosted_voice_id,
    read_hosted_voice,
    rung_of_source,
    rungs_awaiting_setup,
    thinnest_workspace_for,
)
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_sync import sync_voice_catalogue
from apps.api.billing.payment_routes import voice_tier_not_offered
from apps.api.core.errors import ProblemError
from apps.api.core.middleware import MAX_BODY_BYTES
from apps.api.db.session import admin_session, untenanted_session
from apps.api.engine.catalogue import HostedVoice
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from apps.api.ops import hosted_voice_routes as routes
from apps.workers import storage
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text
from tests.hosted_voice_fakes import MP3, OFF_KEY, WAV, CatalogueRows, HostingEngine, selected


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


async def test_a_thinnest_refresh_reads_the_hosted_lists_and_never_list_voices(
    hosted_rows: CatalogueRows,
) -> None:
    vendor_id = f"s{uuid.uuid4().hex[:8]}"
    hosted_rows.track(f"engine:{vendor_id}")
    engine = HostingEngine(
        hosted=[HostedVoice(voice_id=vendor_id, label="Rakesh", source="engine", language="hi")]
    )

    async def _never() -> Any:
        raise AssertionError("list_voices must not be called on an engine that hosts voices")

    engine.list_voices = _never  # type: ignore[method-assign]
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, engine)
    assert result.written == 1 and result.complete
    assert result.note is not None and "Studio workspace" in result.note
    assert engine.own_keys_listed == []
    entry = await _entry(f"engine:{vendor_id}")
    assert (entry.provider, entry.tts_model, entry.origin, entry.curation_state) == (
        "thinnest",
        "engine",
        "synced",
        "disabled",
    )
    assert entry.languages == ["te-IN", "hi-IN", "en-IN"]


async def test_a_studio_workspace_adds_its_own_key_voices_and_prunes_what_left(
    hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    gone = await hosted_rows.add("byok", label="Old", origin="synced", state="disabled")
    kept = f"k{uuid.uuid4().hex[:8]}"
    hosted_rows.track(f"byok:{kept}")
    engine = HostingEngine(
        own_key=[HostedVoice(voice_id=kept, label="Meera", source="byok", language="te")]
    )
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, engine)
    assert engine.own_keys_listed == [studio_workspace]
    assert result.note is None and result.pruned >= 1
    assert (await _entry(gone)).withdrawn_at is not None
    fresh = await _entry(f"byok:{kept}")
    assert (fresh.provider, fresh.languages, fresh.withdrawn_at) == ("cartesia", ["te-IN"], None)


async def test_a_studio_key_of_another_provider_is_not_synced(
    hosted_rows: CatalogueRows, studio_workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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


async def test_empty_listings_are_refused_and_alarmed(
    studio_workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(
        hosted_voices, "alert", lambda stage, code, **kw: alerts.append(kw["source"])
    )
    async with admin_session() as session:
        result = await sync_voice_catalogue(session, HostingEngine())
    assert result.written == 0 and alerts == ["engine", "byok"]


@pytest.mark.parametrize("status", [409, 502])
async def test_a_studio_workspace_not_on_our_key_is_a_stated_skip_and_an_outage_is_not(
    studio_workspace: str, status: int
) -> None:
    from apps.api.engine.vendor_http import EngineRejectedError

    engine = HostingEngine()

    async def _refused(*, workspace: str) -> Any:
        raise EngineRejectedError(status=status, vendor_error=None)

    engine.list_own_key_voices = _refused  # type: ignore[method-assign]
    async with admin_session() as session:
        if status == 409:
            result = await sync_voice_catalogue(session, engine)
            assert result.note is not None and "not running on our voice key" in result.note
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
    assert HostedVoiceRef("byok", "x").rate_key == "byok_voice"


def test_the_workspace_follows_the_rung(studio_workspace: str) -> None:
    assert thinnest_workspace_for(uuid.uuid4(), "clear") is None
    assert thinnest_workspace_for(uuid.uuid4(), "studio") == studio_workspace


def test_a_studio_agent_with_no_workspace_is_refused() -> None:
    with pytest.raises(ProblemError) as caught:
        thinnest_workspace_for(uuid.uuid4(), "studio")
    assert caught.value.code == "engine_studio_workspace_missing"


def test_the_rate_card_holds_studio_back_only_until_the_workspace_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert rungs_awaiting_setup("thinnest") == frozenset({"studio"})
    assert rungs_awaiting_setup("pipecat") == frozenset()
    held = voice_tier_not_offered("thinnest")
    assert held is not None and held[0] == "studio"
    monkeypatch.setattr(hosted_voices, "studio_workspace_ready", lambda: True)
    assert voice_tier_not_offered("thinnest") is None
    pipecat = voice_tier_not_offered("pipecat")
    assert pipecat is not None and pipecat[0] == "clear"


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


async def test_the_platforms_own_preview_is_stored_for_a_studio_voice_and_a_clone(
    admin: dict[str, str],
    previews: dict[str, bytes],
    hosted_rows: CatalogueRows,
    studio_workspace: str,
) -> None:
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
    assert engine.previews == [(studio_workspace, studio.removeprefix("byok:"))]
    assert responses[2].json()["type"].rsplit("/", 1)[-1] == "voice_preview_unavailable"


async def test_a_studio_preview_without_a_workspace_is_refused(
    admin: dict[str, str], hosted_rows: CatalogueRows
) -> None:
    studio = await hosted_rows.add("byok")
    with selected(HostingEngine()):
        async with _client() as http:
            response = await http.post(
                "/v1/ops/voices/hosted/preview/fetch", headers=admin, json={"voice_id": studio}
            )
    assert response.json()["type"].rsplit("/", 1)[-1] == "engine_studio_workspace_missing"


def test_the_preview_sniff_reads_mp3_and_wav_only() -> None:
    assert routes.sniff_preview_type(MP3) == "audio/mpeg"
    assert routes.sniff_preview_type(b"\xff\xfb\x90\x00") == "audio/mpeg"
    assert routes.sniff_preview_type(WAV) == "audio/wav"
    assert routes.sniff_preview_type(b"OggS") is None


# --- the Studio workspace ------------------------------------------------------------------


async def test_the_studio_workspace_reads_as_not_set_up_then_set(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = HostingEngine(key_state=OFF_KEY)
    with selected(engine):
        async with _client() as http:
            unset = await http.get("/v1/ops/voices/studio-workspace", headers=admin)
        monkeypatch.setenv("THINNEST_STUDIO_WORKSPACE_ID", "org_s")
        from apps.api.core.settings import get_settings

        get_settings.cache_clear()
        try:
            async with _client() as http:
                half = await http.get("/v1/ops/voices/studio-workspace", headers=admin)
            engine.key_state = engine.key_state.model_copy(
                update={
                    "enabled": True,
                    "scope": "voice",
                    "complete": True,
                    "using": "own",
                    "voice_provider": "cartesia",
                }
            )
            async with _client() as http:
                ready = await http.get("/v1/ops/voices/studio-workspace", headers=admin)
        finally:
            monkeypatch.delenv("THINNEST_STUDIO_WORKSPACE_ID")
            get_settings.cache_clear()
    assert unset.json() == {
        "workspace_id": None,
        "key": None,
        "ready": False,
        "note": "Not set up: Studio voices are not offered.",
    }
    assert half.json()["ready"] is False and "not speaking" in half.json()["note"]
    assert ready.json()["ready"] is True and ready.json()["key"]["speaks_on_own_voice"]


async def test_setting_up_the_studio_workspace_installs_our_key_and_records_it(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings
    from apps.api.ops import config_service

    propagated: list[bool] = []

    async def _propagate() -> int:
        propagated.append(True)
        return 0

    monkeypatch.setattr(config_service, "propagate", _propagate)
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    get_settings.cache_clear()
    engine = HostingEngine()
    try:
        with selected(engine):
            async with _client() as http:
                refused = await http.post("/v1/ops/voices/studio-workspace", headers=admin, json={})
                done = await http.post(
                    "/v1/ops/voices/studio-workspace",
                    headers={**admin, "X-Confirm-Action": routes.STUDIO_SETUP_CONFIRMATION},
                    json={"model": "sonic-3"},
                )
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_settings WHERE key = 'thinnest_studio_workspace_id'")
            )
        get_settings.cache_clear()
    assert refused.json()["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert done.status_code == 200, done.text
    assert done.json()["workspace_id"] == "org_created" and done.json()["ready"] is True
    assert engine.created_workspaces == [routes.STUDIO_WORKSPACE_EXTERNAL_ID]
    assert engine.installed == [("org_created", "cartesia", "sonic-3")]
    assert engine.enabled == ["org_created"]
    assert propagated == [True]


async def test_the_studio_setup_needs_our_cartesia_key(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings

    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    get_settings.cache_clear()
    with selected(HostingEngine()):
        async with _client() as http:
            response = await http.post(
                "/v1/ops/voices/studio-workspace",
                headers={**admin, "X-Confirm-Action": routes.STUDIO_SETUP_CONFIRMATION},
                json={"workspace_id": "org_given"},
            )
    get_settings.cache_clear()
    assert response.json()["type"].rsplit("/", 1)[-1] == "studio_voice_key_missing"


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


async def test_the_studio_setup_uses_a_given_workspace_and_a_repeat_changes_nothing(
    admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings
    from apps.api.ops import config_service

    propagated: list[bool] = []

    async def _propagate() -> int:
        propagated.append(True)
        return 0

    monkeypatch.setattr(config_service, "propagate", _propagate)
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    get_settings.cache_clear()
    engine = HostingEngine()
    headers = {**admin, "X-Confirm-Action": routes.STUDIO_SETUP_CONFIRMATION}
    try:
        with selected(engine):
            async with _client() as http:
                first = await http.post(
                    "/v1/ops/voices/studio-workspace",
                    headers=headers,
                    json={"workspace_id": "org_given"},
                )
                again = await http.post(
                    "/v1/ops/voices/studio-workspace",
                    headers=headers,
                    json={"workspace_id": "org_given"},
                )
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_settings WHERE key = 'thinnest_studio_workspace_id'")
            )
        get_settings.cache_clear()
    assert first.status_code == 200 and again.status_code == 200, again.text
    assert engine.created_workspaces == []
    assert engine.installed == [("org_given", "cartesia", None)] * 2
    assert propagated == [True]


async def test_the_studio_setup_needs_an_operator_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A principal with no admin row cannot be the author of a configuration change."""
    from apps.api.core.context import Principal
    from apps.api.core.settings import get_settings
    from apps.api.core.stepup import StepUp

    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    get_settings.cache_clear()
    nobody = Principal(realm="admin", user_id=None, tenant_id=None, role="superadmin")
    try:
        with selected(HostingEngine()), pytest.raises(ProblemError) as caught:
            await routes.setup_studio_workspace(
                routes.StudioSetupIn(),
                None,  # type: ignore[arg-type]
                None,  # type: ignore[arg-type]
                None,  # type: ignore[arg-type]
                nobody,
                StepUp(present=False, verified_at=None),
                routes.STUDIO_SETUP_CONFIRMATION,
            )
    finally:
        get_settings.cache_clear()
    assert caught.value.code == "config_actor_unknown"


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
