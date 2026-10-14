"""How a Studio voice sounds on one agent (operators only, 13 Oct 2026).

Vendor shapes are the 13 Oct snapshot's (`thinnest-findings/mirror/snapshots/2026-10-13/pages/
api-reference/bring-your-own-keys.md:362-419`, `agents/set-agent-byok-voice.md:587-627`): a
partial `PUT /agents/{id}/byok-voice` whose answer carries the saved settings (`agentModel` for
the agent's own model), a `GET` with each setting null while unset, `400 validation_failed`
naming the refused `field`, and `POST /byok/voices/preview` taking the same fields.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents import prompts, voice_tuning, voice_tuning_routes
from apps.api.agents.hosted_voices import StudioListingWorkspace
from apps.api.agents.service import _load_agent, _to_config
from apps.api.agents.voice_tuning_routes import admin_router
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session
from calevate_shared.engine import ByokVoiceTuning
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.call_handling_test import _make_live, _operator, _runs, _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import WS, _cfg, _engine, _recorder

VOICE = "cv-1"
TUNED = ByokVoiceTuning(
    speed=Decimal("0.95"), volume=Decimal("1.40"), emotion="calm", model="sonic-3.6"
)


def _studio(**update: Any) -> Any:
    return _cfg(engine_byok_voice_id=VOICE, engine_own_voice_key=True, **update)


def _puts(seen: list[httpx.Request]) -> list[dict[str, Any]]:
    return [
        json.loads(r.content)
        for r in seen
        if r.method == "PUT" and r.url.path.endswith("/byok-voice")
    ]


def _saved(**held: Any) -> httpx.Response:
    base: dict[str, Any] = {
        "voice": VOICE,
        "provider": "cartesia",
        "speed": None,
        "volume": None,
        "emotion": None,
        "agentModel": None,
        "pronunciationDictId": None,
    }
    return httpx.Response(200, json={**base, **held})


# --- the adapter ---------------------------------------------------------------------


async def test_a_publish_sends_the_voice_with_every_setting_held() -> None:
    handler, seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("PUT", "/agents/ag_1/byok-voice"): _saved(
                speed=0.95, volume=1.4, emotion="calm", agentModel="sonic-3.6"
            ),
        }
    )
    await _engine(handler).update_agent(f"ag_1@{WS}", _studio(engine_byok_voice_tuning=TUNED))
    assert _puts(seen) == [
        {"voice": VOICE, "speed": 0.95, "volume": 1.4, "emotion": "calm", "model": "sonic-3.6"}
    ]


async def test_a_cleared_setting_the_platform_still_holds_is_reset_with_null() -> None:
    answers = iter([_saved(volume=1.4, pronunciationDictId="pdict_1"), _saved()])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/byok-voice"):
            return next(answers)
        base, _ = _recorder({("PATCH", "/agents/ag_1"): httpx.Response(200, json={})})
        return base(request)

    await _engine(handler).update_agent(f"ag_1@{WS}", _studio())
    assert _puts(seen) == [{"voice": VOICE}, {"volume": None, "pronunciationDictId": None}]


async def test_settings_read_back_different_refuse_the_publish() -> None:
    handler, _seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("PUT", "/agents/ag_1/byok-voice"): _saved(speed=1.0, volume=1.4, emotion="calm"),
        }
    )
    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(f"ag_1@{WS}", _studio(engine_byok_voice_tuning=TUNED))
    assert caught.value.code == "engine_voice_tuning_not_saved"


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("speed", "voice_speed_not_for_this_voice"),
        ("emotion", "voice_tuning_not_for_this_model"),
        ("pronunciationDictId", "voice_tuning_refused"),
    ],
)
async def test_a_setting_the_platform_refuses_is_said_in_our_words(field: str, code: str) -> None:
    refusal = httpx.Response(
        400, json={"error": "Not allowed.", "code": "validation_failed", "field": field}
    )
    handler, _seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("PUT", "/agents/ag_1/byok-voice"): refusal,
        }
    )
    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(f"ag_1@{WS}", _studio(engine_byok_voice_tuning=TUNED))
    assert caught.value.code == code
    # Client-facing words name no provider and no vendor model (D-679).
    words = f"{caught.value.title} {caught.value.detail} {caught.value.remediation}".lower()
    assert "cartesia" not in words and "sonic" not in words and "thinnest" not in words


async def test_the_sweep_reads_the_settings_back_and_repairs_them() -> None:
    cfg = _studio(engine_byok_voice_tuning=TUNED)
    body = _engine(lambda r: httpx.Response(500))._agent_body(cfg)
    handler, seen = _recorder(
        {
            ("GET", "/agents/ag_1"): httpx.Response(200, json={**body, "id": "ag_1"}),
            ("GET", "/agents/ag_1/byok-voice"): _saved(speed=0.95, volume=1.0, emotion="calm"),
            ("PUT", "/agents/ag_1/byok-voice"): _saved(
                speed=0.95, volume=1.4, emotion="calm", agentModel="sonic-3.6"
            ),
        }
    )
    engine = _engine(handler)
    drifted = await engine.settings_drift(f"ag_1@{WS}", cfg)
    assert drifted == ["voice_tuning"]
    await engine.repair_settings(f"ag_1@{WS}", cfg, drifted)
    assert _puts(seen)[-1]["volume"] == 1.4
    # Nothing else was rewritten.
    assert not any(r.method == "PATCH" for r in seen)


async def test_an_agent_on_a_platform_voice_reads_no_settings() -> None:
    cfg = _cfg()
    body = _engine(lambda r: httpx.Response(500))._agent_body(cfg)
    handler, seen = _recorder(
        {("GET", "/agents/ag_1"): httpx.Response(200, json={**body, "id": "ag_1"})}
    )
    assert await _engine(handler).settings_drift(f"ag_1@{WS}", cfg) == []
    assert not any(r.url.path.endswith("/byok-voice") for r in seen)


async def test_a_preview_speaks_the_settings_sent() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    audio = await _engine(handler).preview_own_key_voice(
        voice_id=VOICE, text=None, language="te-IN", tuning=TUNED
    )
    assert audio.content_type == "audio/mpeg"
    assert seen == [
        {
            "voice": VOICE,
            "language": "te-IN",
            "speed": 0.95,
            "volume": 1.4,
            "emotion": "calm",
            "model": "sonic-3.6",
        }
    ]


# --- what may be chosen --------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"speed": "0.5"}, "voice_speed_out_of_range"),
        ({"speed": "0.955"}, "voice_speed_out_of_range"),
        ({"volume": "2.5"}, "voice_volume_out_of_range"),
        ({"emotion": "furious"}, "voice_emotion_unknown"),
        ({"model": "sonic-1"}, "voice_model_unknown"),
        ({"dictionary_id": "a b"}, "voice_dictionary_id_invalid"),
        ({"model": "sonic-2", "emotion": "calm"}, "voice_tuning_needs_newer_model"),
    ],
)
def test_what_the_platform_refuses_is_refused_first(values: dict[str, str], code: str) -> None:
    with pytest.raises(ProblemError) as caught:
        voice_tuning.refuse_invalid_tuning(voice_tuning.tuning_of(values))
    assert caught.value.code == code


def test_the_older_model_alone_and_a_dictionary_are_accepted() -> None:
    voice_tuning.refuse_invalid_tuning(
        voice_tuning.tuning_of({"model": "sonic-2", "dictionary_id": "pdict_123"})
    )


# --- storage, routes, publish ----------------------------------------------------------


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(admin_router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


async def _studio_agent() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id, _headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_voice_id = :v WHERE id = :aid"),
            {"v": f"byok:{VOICE}", "aid": agent_id},
        )
    return tenant_id, agent_id


def _path(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    return f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning"


async def test_the_columns_refuse_what_the_platform_refuses() -> None:
    tenant_id, agent_id = await _studio_agent()
    for assignment in (
        "studio_voice_speed = 1.6",
        "studio_voice_volume = 0.4",
        "studio_voice_emotion = 'furious'",
        "studio_voice_model = 'sonic-1'",
        "studio_voice_dictionary_id = 'a b'",
        "studio_voice_model = 'sonic-2', studio_voice_speed = 1.0",
    ):
        with pytest.raises(IntegrityError):
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(f"UPDATE agents SET {assignment} WHERE id = :aid"), {"aid": agent_id}
                )


async def test_an_operator_sets_and_clears_settings_audited_and_applied_live() -> None:
    tenant_id, agent_id = await _studio_agent()
    await _make_live(tenant_id, agent_id)
    operator = await _operator()
    async with _client() as client:
        first = await client.get(_path(tenant_id, agent_id), headers=operator)
        assert first.status_code == 200, first.text
        assert first.json()["studio"] is True and first.json()["speed"] is None
        assert "sonic-3.6" in first.json()["options"]["models"]

        saved = await client.patch(
            _path(tenant_id, agent_id),
            headers=operator,
            json={"speed": 0.95, "emotion": "calm"},
        )
        assert saved.status_code == 200, saved.text
        assert (Decimal(saved.json()["speed"]), saved.json()["emotion"]) == (
            Decimal("0.95"),
            "calm",
        )
        # A field left out is kept; null clears one.
        cleared = await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"emotion": None}
        )
        assert cleared.json()["emotion"] is None
        assert Decimal(cleared.json()["speed"]) == Decimal("0.95")

        refused = await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"volume": 3}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["type"].endswith("/voice_volume_out_of_range")

    assert [reasons for _scope, _aid, reasons in await _runs(tenant_id)] == [["voice_tuning"]]
    async with tenant_session(tenant_id) as session:
        actions = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :tid "
                    "AND action = 'admin.agent_voice_tuning_set'"
                ),
                {"tid": tenant_id},
            )
        ).all()
    assert len(actions) == 2


async def test_an_agent_on_a_platform_voice_takes_no_settings() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    operator = await _operator()
    async with _client() as client:
        refused = await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"speed": 1.1}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["type"].endswith("/voice_tuning_needs_studio_voice")
        assert (await client.get(_path(tenant_id, agent_id), headers=operator)).json()[
            "studio"
        ] is False


async def test_a_client_cannot_reach_the_operator_routes() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=headers)
    assert got.status_code in (401, 403)


async def test_the_publish_config_carries_the_settings_for_a_studio_voice_only() -> None:
    tenant_id, agent_id = await _studio_agent()
    async with tenant_session(tenant_id) as session:
        await voice_tuning.set_voice_tuning(
            session, tenant_id=tenant_id, agent_id=agent_id, changes={"volume": "1.40"}
        )
        row = await _load_agent(session, tenant_id, agent_id)
    tuning = voice_tuning.config_tuning(row["voice_tuning"], byok_voice_id=VOICE)
    assert tuning is not None and tuning.volume == Decimal("1.40")
    assert voice_tuning.config_tuning(row["voice_tuning"], byok_voice_id=None) is None
    # Nothing set is no tuning at all, so an untuned agent publishes as before.
    assert voice_tuning.config_tuning((None,) * 5, byok_voice_id=VOICE) is None


async def test_the_config_built_for_publish_names_the_settings() -> None:
    tenant_id, agent_id = await _studio_agent()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )
        await voice_tuning.set_voice_tuning(
            session, tenant_id=tenant_id, agent_id=agent_id, changes={"emotion": "happy"}
        )
        row = await _load_agent(session, tenant_id, agent_id)
    cfg = _to_config(tenant_id, row, engine=HostingEngine())
    assert cfg.engine_byok_voice_id == VOICE
    assert cfg.engine_byok_voice_tuning == ByokVoiceTuning(emotion="happy")
    # Excluded from dumps, so stored configs and their digests do not move.
    assert "engine_byok_voice_tuning" not in cfg.model_dump()


async def test_the_preview_speaks_the_agents_studio_voice_with_the_settings_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _studio_agent()
    engine = HostingEngine()
    monkeypatch.setattr(voice_tuning_routes, "get_engine", lambda: engine)

    async def _ready(_engine: object) -> StudioListingWorkspace:
        return StudioListingWorkspace(workspace="org_studio")

    monkeypatch.setattr(voice_tuning_routes, "studio_listing_workspace", _ready)
    operator = await _operator()
    async with _client() as client:
        heard = await client.post(
            f"{_path(tenant_id, agent_id)}/preview",
            headers=operator,
            json={"volume": 1.4, "emotion": "calm"},
        )
        assert heard.status_code == 200, heard.text
        assert heard.headers["content-type"] == "audio/mpeg"
        refused = await client.post(
            f"{_path(tenant_id, agent_id)}/preview", headers=operator, json={"speed": 9}
        )
        assert refused.status_code == 422
    assert engine.previews == [VOICE]
    [tuning] = engine.preview_tunings
    assert tuning is not None and (tuning.volume, tuning.emotion) == (Decimal("1.4"), "calm")
