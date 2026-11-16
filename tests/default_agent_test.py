"""The admin-set default agent (founder, 16 Nov 2026): the setting, its gate, and "Name and voice".

The voice list is replaced per test (`offered_hosted_voices`) rather than written into the
shared `platform_voice_catalog`, so no row outlives a test and the cases do not depend on
which hosted voices another suite left enabled.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from apps.api.agents import default_agent
from apps.api.agents.default_agent import DefaultAgent, read_default_agent
from apps.api.agents.hosted_voices import HostedVoiceRow
from apps.api.agents.voice_pick import choose_voice
from apps.api.core import platform_config as pc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run import routes as first_run_routes
from apps.api.main import app
from apps.api.ops.config_routes import config_confirmation
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_identity_test import _make_member
from tests.admin_security_test import _make_admin
from tests.first_run_test import _owner, _tenant, _voice

VOICE_KEY = "default_agent_voice_id"
NAME_KEY = "default_agent_name"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _offering(monkeypatch: pytest.MonkeyPatch, *rows: HostedVoiceRow) -> None:
    async def offered(_session: Any) -> tuple[HostedVoiceRow, ...]:
        return rows

    monkeypatch.setattr(default_agent, "offered_hosted_voices", offered)


def _configured(monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    configured = get_settings().model_copy(update=values)
    monkeypatch.setattr(default_agent, "get_settings", lambda: configured)


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_settings WHERE key = ANY(:keys)"),
            {"keys": [VOICE_KEY, NAME_KEY]},
        )
    pc.reset_for_test()
    await pc.refresh(force=True)


# ------------------------------------------------------------------ read_default_agent


async def test_unset_it_is_todays_anjali_with_a_womans_voice_picked_per_account() -> None:
    assert get_settings().default_agent_name == "Anjali"
    assert get_settings().default_agent_voice_id is None
    async with untenanted_session() as session:
        got = await read_default_agent(session)
    assert got == DefaultAgent(name="Anjali", voice_id=None, gender="female")


async def test_a_set_voice_brings_its_own_gender(monkeypatch: pytest.MonkeyPatch) -> None:
    ravi = _voice("byok:ravi", accent="te-IN", label="Ravi", source="byok", gender="Male")
    _offering(monkeypatch, ravi)
    _configured(monkeypatch, default_agent_name=" Ravi ", default_agent_voice_id="byok:ravi")
    async with untenanted_session() as session:
        got = await read_default_agent(session)
    assert got == DefaultAgent(name="Ravi", voice_id="byok:ravi", gender="male")


async def test_a_voice_no_longer_offered_is_not_handed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offering(monkeypatch)
    _configured(monkeypatch, default_agent_voice_id="byok:gone")
    async with untenanted_session() as session:
        got = await read_default_agent(session)
    assert got.voice_id is None and got.gender == "female"


async def test_a_voice_that_states_no_gender_keeps_the_default_gender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offering(monkeypatch, _voice("engine:u", accent="te-IN", label="Uma", gender=None))
    _configured(monkeypatch, default_agent_voice_id="engine:u")
    async with untenanted_session() as session:
        got = await read_default_agent(session)
    assert (got.voice_id, got.gender) == ("engine:u", "female")


async def test_unsetting_the_voice_is_always_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _offering(monkeypatch)
    async with untenanted_session() as session:
        await default_agent.assert_default_voice_offered(session, None)
        with pytest.raises(ProblemError) as refused:
            await default_agent.assert_default_voice_offered(session, "byok:any")
    assert refused.value.code == "default_agent_voice_not_offered"


# ------------------------------------------------------------------ choose_voice


def test_the_admins_voice_wins_where_this_account_may_use_it() -> None:
    sita = _voice("byok:s", accent="te-IN", label="Sita", source="byok")
    uma = _voice("byok:u", accent="te-IN", label="Uma", source="byok")
    bindu = _voice("engine:b", accent="te-IN", label="Bindu")
    gauri = _voice("engine:g", accent="te-IN", label="Gauri")

    got = choose_voice([sita, uma], [bindu], None, preferred="byok:u")
    assert got is not None and (got.row.label, got.rung, got.fallback) == ("Uma", "studio", None)
    # A Clear voice the admin chose carries no "instead of Studio" reason.
    got = choose_voice([sita], [bindu, gauri], None, preferred="engine:g")
    assert got is not None and (got.row.label, got.rung, got.fallback) == ("Gauri", "clear", None)
    # Studio closed to this account: its Studio choice gives way, with the reason.
    got = choose_voice([uma], [bindu], "studio_minutes_used", preferred="byok:u")
    assert got is not None and (got.row.label, got.fallback) == ("Bindu", "studio_minutes_used")
    # Not among this account's candidates (another language, or no longer offered).
    got = choose_voice([sita], [bindu], None, preferred="byok:other")
    assert got is not None and got.row.label == "Sita"


def test_a_mans_default_gets_a_mans_voice_and_no_womans_flags() -> None:
    ravi = _voice("byok:r", accent="te-IN", label="Ravi", source="byok", gender="male")
    sita = _voice("byok:s", accent="te-IN", label="Sita", source="byok")
    gopal = _voice("engine:g", accent="te-IN", label="Gopal", gender="male")
    bindu = _voice("engine:b", accent="te-IN", label="Bindu")

    got = choose_voice([sita, ravi], [bindu], None, gender="male")
    assert got is not None and (got.row.label, got.not_female) == ("Ravi", False)
    got = choose_voice([sita], [bindu, gopal], None, gender="male")
    assert got is not None and (got.row.label, got.fallback) == ("Gopal", "no_studio_voice")
    got = choose_voice([sita], [bindu], None, gender="male")
    assert got is not None and (got.row.label, got.not_female) == ("Sita", False)


# ------------------------------------------------------------------ the console setting


def _headers(token: str, key: str, etag: str = '"0"') -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Confirm-Action": config_confirmation(key),
        "If-Match": etag,
    }


async def test_the_setting_is_listed_in_its_section_with_a_voice_picker() -> None:
    token = await _make_admin()
    async with _client() as http:
        body = (
            await http.get("/v1/ops/config", headers={"Authorization": f"Bearer {token}"})
        ).json()
    fields = {f["key"]: f for f in body["fields"]}
    assert fields[NAME_KEY]["value"] == "Anjali"
    assert (fields[NAME_KEY]["section"], fields[NAME_KEY]["subsection"]) == (
        "speech",
        "default-agent",
    )
    voice = fields[VOICE_KEY]
    assert voice["control"]["kind"] == "entity_picker"
    assert voice["control"]["source"] == "client_voices"
    assert voice["value"] is None and voice["nullable"] is True


async def test_a_voice_not_enabled_for_clients_is_refused_plainly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offering(monkeypatch, _voice("byok:s", accent="te-IN", label="Sita", source="byok"))
    token = await _make_admin()
    async with _client() as http:
        refused = await http.put(
            f"/v1/ops/config/{VOICE_KEY}",
            headers=_headers(token, VOICE_KEY),
            json={"value": "byok:disabled", "reason": "New default voice"},
        )
        assert refused.status_code == 422, refused.text
        problem = refused.json()
        assert problem["type"].endswith("/default_agent_voice_not_offered")
        assert "Voices page" in problem["remediation"]

        stored = await http.put(
            f"/v1/ops/config/{VOICE_KEY}",
            headers=_headers(token, VOICE_KEY),
            json={"value": "byok:s", "reason": "New default voice"},
        )
    assert stored.status_code == 200, stored.text
    assert stored.json()["field"]["value"] == "byok:s"


async def test_a_name_is_trimmed_and_a_blank_or_dotted_one_refused() -> None:
    token = await _make_admin()
    async with _client() as http:
        blank = await http.put(
            f"/v1/ops/config/{NAME_KEY}",
            headers=_headers(token, NAME_KEY),
            json={"value": "   ", "reason": "rename"},
        )
        dotted = await http.put(
            f"/v1/ops/config/{NAME_KEY}",
            headers=_headers(token, NAME_KEY),
            json={"value": "Dr. Priya", "reason": "rename"},
        )
        stored = await http.put(
            f"/v1/ops/config/{NAME_KEY}",
            headers=_headers(token, NAME_KEY),
            json={"value": "  Priya ", "reason": "rename"},
        )
    assert blank.status_code == 422 and blank.json()["type"].endswith("/default_agent_name_blank")
    assert dotted.status_code == 422, dotted.text
    assert stored.status_code == 200, stored.text
    assert stored.json()["field"]["value"] == "Priya"


async def test_the_client_realm_cannot_read_or_change_it() -> None:
    tenant_id = await _tenant()
    token = await _make_member(tenant_id)
    async with _client() as http:
        read = await http.get("/v1/ops/config", headers={"Authorization": f"Bearer {token}"})
        write = await http.put(
            f"/v1/ops/config/{NAME_KEY}",
            headers=_headers(token, NAME_KEY),
            json={"value": "Priya", "reason": "should never land"},
        )
    assert read.status_code in (401, 403)
    assert write.status_code in (401, 403)
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM platform_settings WHERE key = :k"), {"k": NAME_KEY}
            )
        ).first()
    assert row is None


async def test_an_operator_without_platform_config_is_refused() -> None:
    token = await _make_admin("operator")
    async with _client() as http:
        write = await http.put(
            f"/v1/ops/config/{VOICE_KEY}",
            headers=_headers(token, VOICE_KEY),
            json={"value": None, "reason": "should never land"},
        )
    assert write.status_code == 403


# ------------------------------------------------------------------ "Name and voice" uses it


async def test_the_first_agent_gets_the_admins_voice_through_name_and_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ravi = _voice("byok:ravi", accent="en-IN", label="Ravi", source="byok", gender="male")
    _offering(monkeypatch, ravi)
    _configured(monkeypatch, default_agent_name="Ravi", default_agent_voice_id="byok:ravi")
    asked: dict[str, Any] = {}

    async def pick(_tenant_id: uuid.UUID, language: str, **default: Any) -> None:
        asked.update(default, language=language)

    monkeypatch.setattr(first_run_routes, "pick_voice", pick)
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        made = await http.put(
            "/v1/first-run/agent",
            headers=headers,
            json={"name": "Ravi", "language_primary": "en-IN", "languages_extra": []},
        )
    assert made.status_code == 200, made.text
    assert made.json()["default_agent"] == {
        "name": "Ravi",
        "voice_id": "byok:ravi",
        "gender": "male",
    }
    assert asked == {"preferred": "byok:ravi", "gender": "male", "language": "en-IN"}
    async with tenant_session(tenant_id) as session:
        name = (
            await session.execute(
                text("SELECT name FROM agents WHERE id = :a"), {"a": made.json()["agent_id"]}
            )
        ).scalar()
    assert name == "Ravi"
