"""The agent's speed on a Clear voice (D-884): ThinnestAI's `voice.speakingSpeed`.

The one speed column serves both rungs: 0.7-1.3 in steps of 0.05 on a Clear voice, sent on
every write, read back at publish, reported and repaired as drift; null on a Studio voice,
whose speed goes with the byok-voice settings. A voice change fits the speed to the new rung.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents import lifecycle, prompts, voice_tuning
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from calevate_shared.engine import ByokVoiceTuning
from sqlalchemy import text
from tests.call_handling_test import _make_live, _runs, _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.studio_voice_tuning_test import VOICE, _client_app, _studio, _studio_client_agent
from tests.thinnest_engine_test import WS, _cfg, _engine, _recorder, tools_state

pytestmark = [pytest.mark.rls]

AGENT = f"ag_1@{WS}"


# --- the ranges ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("speed", "studio", "fitted"),
    [
        ("1.45", False, "1.30"),
        ("0.60", False, "0.70"),
        ("1.12", False, "1.10"),
        ("1.13", False, "1.15"),
        ("1.45", True, "1.45"),
        ("1.10", True, "1.10"),
    ],
)
def test_a_speed_is_fitted_to_the_rung(speed: str, studio: bool, fitted: str) -> None:
    assert voice_tuning.fit_speed(Decimal(speed), studio=studio) == Decimal(fitted)
    assert voice_tuning.fit_speed(None, studio=studio) is None


@pytest.mark.parametrize("speed", ["0.65", "1.35", "1.12"])
def test_a_clear_voice_refuses_a_speed_off_its_range_or_step(speed: str) -> None:
    tuning = ByokVoiceTuning(speed=Decimal(speed))
    with pytest.raises(ProblemError) as refused:
        voice_tuning.refuse_invalid_tuning(tuning, studio=False)
    assert refused.value.code == "voice_speed_out_of_range"
    # The same value is a Studio speed where it is inside 0.6-1.5.
    voice_tuning.refuse_invalid_tuning(tuning, studio=True)


# --- the adapter --------------------------------------------------------------------------


def test_every_write_states_the_speed_on_a_clear_voice_and_null_on_a_studio_one() -> None:
    engine = _engine(lambda r: httpx.Response(500))
    assert engine._agent_body(_cfg())["voice"]["speakingSpeed"] is None
    clear = _cfg(engine_speaking_speed=Decimal("1.15"))
    assert engine._agent_body(clear)["voice"]["speakingSpeed"] == 1.15
    # Excluded from dumps, so stored configs and their digests do not move.
    assert "engine_speaking_speed" not in clear.model_dump()
    studio = _studio(
        engine_speaking_speed=Decimal("1.15"),
        engine_byok_voice_tuning=ByokVoiceTuning(speed=Decimal("1.15")),
    )
    assert engine._agent_body(studio)["voice"]["speakingSpeed"] is None


async def test_a_speed_read_back_different_refuses_the_publish() -> None:
    cfg = _cfg(engine_speaking_speed=Decimal("1.2"))
    handler, _seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(
                200, json={"id": "ag_1", "voice": {"speakingSpeed": 1}}
            )
        }
    )
    with pytest.raises(ProblemError) as refused:
        await _engine(handler).update_agent(AGENT, cfg)
    assert refused.value.code == "engine_speaking_speed_not_saved"


@pytest.mark.parametrize("held", [None, 1, 1.0])
async def test_the_voices_own_pace_reads_back_as_null_or_1(held: object) -> None:
    handler, _seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(
                200, json={"id": "ag_1", "voice": {"speakingSpeed": held}}
            )
        }
    )
    await _engine(handler).update_agent(AGENT, _cfg())


async def test_the_drift_sweep_reports_and_repairs_the_speed() -> None:
    assert "speaking_speed" in AGENT_SETTING_LABELS
    cfg = _cfg(engine_speaking_speed=Decimal("1.2"))
    engine = _engine(lambda r: httpx.Response(500))
    wanted = engine._agent_body(cfg)
    # Changed in the vendor's console.
    held = {**wanted, "voice": {**wanted["voice"], "speakingSpeed": 0.9}}
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
        if request.method == "GET":
            return httpx.Response(200, json=held)
        sent.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={})

    engine = _engine(handler)
    drifted = await engine.settings_drift(AGENT, cfg)
    assert drifted == ["speaking_speed"]
    await engine.repair_settings(AGENT, cfg, drifted)
    assert sent == [{"voice": {"speakingSpeed": 1.2}}]
    same = {**wanted, "voice": {**wanted["voice"], "speakingSpeed": 1.20}}
    assert thinnest._settings_drift(wanted, same) == []


# --- storage, routes, publish ---------------------------------------------------------------


async def test_a_client_sets_a_clear_voices_speed_and_it_reaches_the_live_agent() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    path = f"/v1/agents/{agent_id}/voice-tuning"
    async with _client_app() as client:
        first = (await client.get(path, headers=headers)).json()
        assert first["studio"] is False
        options = first["options"]
        assert (options["speed_min"], options["speed_max"], options["speed_step"]) == (
            "0.7",
            "1.3",
            "0.05",
        )
        for refused_speed in (1.12, 1.4):
            refused = await client.patch(path, headers=headers, json={"speed": refused_speed})
            assert refused.status_code == 422, refused.text
            assert refused.json()["type"].endswith("/voice_speed_out_of_range")
        loud = await client.patch(path, headers=headers, json={"volume": 1.2})
        assert loud.status_code == 422, loud.text
        assert loud.json()["type"].endswith("/voice_tuning_needs_studio_voice")
        saved = await client.patch(path, headers=headers, json={"speed": 1.15})
        assert saved.status_code == 200, saved.text
        assert Decimal(saved.json()["speed"]) == Decimal("1.15")
    assert [reasons for _scope, _aid, reasons in await _runs(tenant_id)] == [["voice_tuning"]]


async def test_studio_settings_left_from_an_earlier_voice_do_not_block_the_speed() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET studio_voice_volume = 1.40 WHERE id = :aid"),
            {"aid": agent_id},
        )
    async with _client_app() as client:
        saved = await client.patch(
            f"/v1/agents/{agent_id}/voice-tuning", headers=headers, json={"speed": 0.9}
        )
    assert saved.status_code == 200, saved.text


async def test_the_publish_config_sends_the_speed_on_a_clear_voice_only() -> None:
    tenant_id, agent_id, _headers = await _tenant()
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
            session, tenant_id=tenant_id, agent_id=agent_id, changes={"speed": "1.25"}
        )
        clear = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
        await session.execute(
            text("UPDATE agents SET engine_voice_id = :v WHERE id = :aid"),
            {"v": f"byok:{VOICE}", "aid": agent_id},
        )
        studio = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
    assert clear.engine_speaking_speed == Decimal("1.25")
    assert studio.engine_speaking_speed is None
    assert studio.engine_byok_voice_tuning == ByokVoiceTuning(speed=Decimal("1.25"))


async def test_a_studio_speed_is_fitted_when_the_agent_moves_to_a_clear_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _headers = await _studio_client_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET studio_voice_speed = 1.45 WHERE id = :aid"),
            {"aid": agent_id},
        )

    async def _any_choice(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(lifecycle, "_check_engine_choice", _any_choice)
    async with tenant_session(tenant_id) as session:
        await lifecycle.update_agent(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            engine_voice_id="engine:anjali",
            set_engine_voice_id=True,
        )
        speed = (
            await session.execute(
                text("SELECT studio_voice_speed FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    assert speed == Decimal("1.30")
