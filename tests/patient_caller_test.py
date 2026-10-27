"""Asking an unanswered question again as a call setting, and the "Patient caller" preset (D-907).

`voice.reaskAfterSeconds` resolves agent -> account -> Calevate's 5 s like the other call
settings, is stated on every publish (0 is never) and is drift-checked under `reask_wait`. The
preset sets the silence settings for a caller who follows along on their phone and raises the
longest call, on one agent, as ordinary values the owner can change after.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import patient_caller
from apps.api.agents.call_handling import (
    REASK_AFTER_DEFAULT_MS,
    CallSettings,
    refuse_invalid_settings,
    resolve_settings,
)
from apps.api.agents.languages import BUILT_LANGUAGES
from apps.api.agents.models import NUDGE_PHRASE_MAX_CHARS
from apps.api.agents.service import _call_settings_fields
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import PLATFORM_VOICE_VALUES, ThinnestEngine
from sqlalchemy import text
from tests.call_handling_test import _client, _make_live, _operator, _runs, _tenant
from tests.thinnest_engine_test import _cfg

pytestmark = [pytest.mark.rls]


def _voice(**update: object) -> dict[str, Any]:
    voice: dict[str, Any] = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(**update))[
        "voice"
    ]
    return voice


# --- the re-ask wait: the wire, drift and resolution ----------------------------------------


def test_the_wait_is_the_agents_and_always_stated() -> None:
    assert "reaskAfterSeconds" not in PLATFORM_VOICE_VALUES
    assert _voice()["reaskAfterSeconds"] == 5
    assert _voice(reask_after_ms=2500)["reaskAfterSeconds"] == 2.5
    # 0 is the vendor's "never ask again", never null, which is its 2.5 s.
    assert _voice(reask_after_ms=0)["reaskAfterSeconds"] == 0
    assert "reask_after_ms" not in _cfg(reask_after_ms=0).model_dump()


def test_a_console_change_is_drift_and_the_same_seconds_are_not() -> None:
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(reask_after_ms=0))
    for held_value in (2.5, None, 5):
        held = {**wanted, "voice": {**wanted["voice"], "reaskAfterSeconds": held_value}}
        assert thinnest._settings_drift(wanted, held) == ["reask_wait"]
    same = {**wanted, "voice": {**wanted["voice"], "reaskAfterSeconds": 0.0}}
    assert thinnest._settings_drift(wanted, same) == []


def test_it_resolves_agent_then_account_then_calevate() -> None:
    platform = resolve_settings(CallSettings(), CallSettings())
    assert (platform.values.reask_after_ms, platform.sources["reask_after_ms"]) == (
        REASK_AFTER_DEFAULT_MS,
        "platform",
    )
    account = resolve_settings(CallSettings(), CallSettings(reask_after_ms=3000))
    assert account.sources["reask_after_ms"] == "organization"
    own = resolve_settings(CallSettings(reask_after_ms=0), CallSettings(reask_after_ms=3000))
    assert (own.values.reask_after_ms, own.sources["reask_after_ms"]) == (0, "agent")
    row: Any = {"call_settings": CallSettings(reask_after_ms=0)}
    assert _call_settings_fields(row, languages=("te-IN",))["reask_after_ms"] == 0


@pytest.mark.parametrize("ms", [0, 1500, 2500, 10_000])
def test_never_or_tenths_from_one_and_a_half_to_ten_seconds(ms: int) -> None:
    refuse_invalid_settings(CallSettings(reask_after_ms=ms))


@pytest.mark.parametrize("ms", [100, 1400, 1550, 10_100, -100])
def test_anything_else_is_refused_in_words(ms: int) -> None:
    with pytest.raises(ProblemError) as refused:
        refuse_invalid_settings(CallSettings(reask_after_ms=ms))
    assert refused.value.code == "call_setting_out_of_range"


async def test_the_columns_hold_the_vendor_range() -> None:
    tenant_id, agent_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET reask_after_ms = 0 WHERE id = :aid"), {"aid": agent_id}
        )
        await session.execute(text("UPDATE organizations SET default_reask_after_ms = 1500"))
    for sql in (
        "UPDATE agents SET reask_after_ms = 1550 WHERE id = :aid",
        "UPDATE organizations SET default_reask_after_ms = 1000",
    ):
        with pytest.raises(Exception, match="reask_after_range"):
            async with tenant_session(tenant_id) as session:
                await session.execute(text(sql), {"aid": agent_id})


async def test_the_owner_sets_it_for_one_agent_or_all_and_the_live_agent_follows() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    path = f"/v1/agents/{agent_id}/call-handling"
    async with _client() as client:
        before = (await client.get(path, headers=headers)).json()
        own = await client.patch(path, headers=headers, json={"reask_after_ms": 0})
        refused = await client.patch(path, headers=headers, json={"reask_after_ms": 900})
        everyone = await client.post(
            "/v1/organization/call-handling/all-agents",
            headers=headers,
            json={"reask_after_ms": 3000},
        )
        after = (await client.get(path, headers=headers)).json()
    assert (before["reask_after_ms_effective"], before["reask_after_ms_source"]) == (
        5000,
        "platform",
    )
    bounds = before["bounds"]
    assert (bounds["reask_after_min_ms"], bounds["reask_after_max_ms"]) == (1500, 10_000)
    assert (bounds["reask_after_step_ms"], bounds["platform_reask_after_ms"]) == (100, 5000)
    assert own.status_code == 200, own.text
    assert (own.json()["reask_after_ms"], own.json()["reask_after_ms_source"]) == (0, "agent")
    assert refused.status_code == 422, refused.text
    assert everyone.status_code == 200, everyone.text
    assert everyone.json()["agents_reset"] == 1
    assert everyone.json()["organization"]["reask_after_ms"] == 3000
    assert (after["reask_after_ms"], after["reask_after_ms_effective"]) == (None, 3000)
    assert any("call_handling" in reasons for _scope, _aid, reasons in await _runs(tenant_id))


# --- the preset -----------------------------------------------------------------------------


def test_a_question_for_every_language_an_agent_can_speak() -> None:
    assert set(patient_caller.NUDGE_PHRASES) == set(BUILT_LANGUAGES)
    for phrase in patient_caller.NUDGE_PHRASES.values():
        assert phrase.strip() == phrase and 0 < len(phrase) <= NUDGE_PHRASE_MAX_CHARS
    assert patient_caller.nudge_phrase_for("te-IN") == "కనిపించిందా అండి?"
    # A language with none asks the platform's own question in the caller's language.
    assert patient_caller.nudge_phrase_for("xx-IN") == ""


def test_the_values_are_valid_settings_and_leave_every_question_an_answer_window() -> None:
    changes = patient_caller.preset_changes("te-IN")
    refuse_invalid_settings(CallSettings(**changes))  # type: ignore[arg-type]
    # Counted from the caller's last words, the hang-up comes after every question and its
    # answer window (the platform's floor), whether or not a question restarts the count.
    floor = patient_caller.NUDGE_AFTER_S * (patient_caller.NUDGE_COUNT + 1)
    assert floor < patient_caller.END_AFTER_SILENCE_S
    assert patient_caller.REASK_AFTER_MS == 0
    assert patient_caller.CALL_CAP_S <= thinnest.CALL_SECONDS_MAX


async def test_one_tap_sets_the_agent_and_raises_its_longest_call() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    path = f"/v1/agents/{agent_id}/call-handling"
    async with _client() as client:
        before = (await client.get(path, headers=headers)).json()
        applied = await client.post(f"{path}/give-callers-time", headers=headers)
    assert before["patient_caller"]["applied"] is False
    assert before["patient_caller"]["nudge_phrase"] == "కనిపించిందా అండి?"
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["patient_caller"]["applied"] is True
    assert (body["nudge_after_seconds"], body["nudge_count"]) == (20, 3)
    assert (body["end_after_silence_seconds"], body["reask_after_ms"]) == (120, 0)
    assert body["nudge_phrase"] == "కనిపించిందా అండి?"
    assert body["nudge_after_seconds_source"] == "agent"
    async with tenant_session(tenant_id) as session:
        cap = (
            await session.execute(
                text("SELECT max_call_duration_s FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'agent.patient_caller_applied' "
                    "AND object_id = :aid"
                ),
                {"aid": str(agent_id)},
            )
        ).scalar_one()
    assert cap == patient_caller.CALL_CAP_S
    assert audited == 1
    runs = await _runs(tenant_id)
    assert any("call_handling" in reasons for _scope, _aid, reasons in runs)


async def test_a_longer_call_is_kept_and_a_tweak_reads_as_not_applied() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET max_call_duration_s = 1200 WHERE id = :aid"), {"aid": agent_id}
        )
    path = f"/v1/agents/{agent_id}/call-handling"
    async with _client() as client:
        await client.post(f"{path}/give-callers-time", headers=headers)
        tweaked = await client.patch(path, headers=headers, json={"nudge_count": 2})
    async with tenant_session(tenant_id) as session:
        cap = (
            await session.execute(
                text("SELECT max_call_duration_s FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    assert cap == 1200
    assert tweaked.json()["patient_caller"]["applied"] is False


async def test_only_the_owner_and_an_operator_apply_it_and_never_across_tenants() -> None:
    tenant_id, agent_id, _owner = await _tenant()
    _other_tenant, _other_agent, other_owner = await _tenant()
    _t, _a, staff = await _tenant(role="staff")
    operator = await _operator()
    async with _client() as client:
        foreign = await client.post(
            f"/v1/agents/{agent_id}/call-handling/give-callers-time", headers=other_owner
        )
        by_staff = await client.post(
            f"/v1/agents/{_a}/call-handling/give-callers-time", headers=staff
        )
        by_operator = await client.post(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling/give-callers-time",
            headers=operator,
        )
        missing = await client.post(
            f"/v1/admin/tenants/{tenant_id}/agents/{uuid.uuid4()}/call-handling/give-callers-time",
            headers=operator,
        )
    assert foreign.status_code == 404, foreign.text
    assert by_staff.status_code == 403, by_staff.text
    assert by_operator.status_code == 200, by_operator.text
    assert by_operator.json()["patient_caller"]["applied"] is True
    assert missing.status_code == 404, missing.text
