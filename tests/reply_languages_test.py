"""Each agent's reply languages (D-815, founder 18 Oct 2026).

Up to four languages per agent, its main language first and the one it falls back to; a new
agent starts from the business profile's languages, else Telugu then English. The list is the
agent's own (`agents.language_primary`
then `agents.languages_extra`), shown on the roster, and reaches ThinnestAI as `languages`
only while `Settings.thinnest_reply_languages` is on: until ThinnestAI confirms that release
the adapter keeps sending the single `language` (snapshots/2026-10-18/pages/api-reference/
agents/update-agent.md:754-780).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.agents.languages import default_extra_languages
from apps.api.agents.routes import AgentCreateIn, AgentUpdateIn
from apps.api.agents.service import _load_agent
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import (
    ThinnestEngine,
    _settings_drift,
)
from pydantic import ValidationError
from sqlalchemy import text
from tests.agent_lifecycle_test import _app, _client, _code, _tenant
from tests.thinnest_engine_test import WS, _agent_write, _body, _cfg, _engine, _recorder

pytestmark = [pytest.mark.rls]

AGENT = f"ag_1@{WS}"


@pytest.fixture
def languages_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_reply_languages", True)


# --- the request ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("languages", "why"),
    [
        ([], "at least one"),
        (["te-IN", "en-IN", "te-IN"], "only once"),
        (["te-IN", "hi-IN", "en-IN", "te-IN", "hi-IN"], "at most 4"),
    ],
)
def test_a_list_that_cannot_be_sent_is_refused_in_words(languages: list[str], why: str) -> None:
    with pytest.raises(ValidationError) as refused:
        AgentUpdateIn.model_validate({"reply_languages": languages})
    assert why in str(refused.value)


def test_the_first_reply_language_is_the_main_language() -> None:
    update = AgentUpdateIn.model_validate({"reply_languages": ["en-IN", "te-IN"]})
    assert update.main_language == "en-IN" and update.extra_languages == ["te-IN"]
    with pytest.raises(ValidationError):
        AgentUpdateIn.model_validate(
            {"language_primary": "te-IN", "reply_languages": ["en-IN", "te-IN"]}
        )
    created = AgentCreateIn.model_validate({"name": "Front desk", "reply_languages": ["hi-IN"]})
    assert created.main_language == "hi-IN" and created.extra_languages == []


@pytest.mark.parametrize(
    ("primary", "business", "expected"),
    [
        # No business list: the main language, then Telugu, then English.
        ("te-IN", None, ["en-IN"]),
        ("en-IN", [], ["te-IN"]),
        ("hi-IN", None, ["te-IN", "en-IN"]),
        # The business list is the starting list, in its order, without the main language.
        ("te-IN", ["hi-IN", "te-IN"], ["hi-IN"]),
        ("en-IN", ["en-IN"], []),
    ],
)
def test_a_new_agent_starts_from_the_business_list_else_telugu_then_english(
    primary: str, business: list[str] | None, expected: list[str]
) -> None:
    assert default_extra_languages(primary, business) == expected


# --- the store and the roster --------------------------------------------------------------


async def _roster_languages(token: str, agent_id: uuid.UUID) -> list[str]:
    async with _client(_app()) as http:
        response = await http.get(
            f"/v1/agents/{agent_id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    return list(response.json()["reply_languages"])


async def test_a_new_agent_replies_in_telugu_then_english() -> None:
    _tenant_id, _seeded, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.post(
            "/v1/agents",
            json={"name": "Front desk", "direction": "inbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
        english = await http.post(
            "/v1/agents",
            json={"name": "Desk two", "direction": "inbound", "language_primary": "en-IN"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201, response.text
    assert response.json()["reply_languages"] == ["te-IN", "en-IN"]
    assert english.json()["reply_languages"] == ["en-IN", "te-IN"]


async def test_the_owner_sets_the_order_and_the_main_language_follows() -> None:
    tenant_id, agent_id, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}",
            json={"reply_languages": ["hi-IN", "en-IN", "te-IN"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["language_primary"] == "hi-IN"
    assert response.json()["reply_languages"] == ["hi-IN", "en-IN", "te-IN"]
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)
    assert row["language_primary"] == "hi-IN"
    assert list(row["languages_extra"]) == ["en-IN", "te-IN"]


async def test_a_new_main_language_alone_leaves_the_others_and_is_not_repeated() -> None:
    _tenant_id, agent_id, token = await _tenant()
    headers = {"Authorization": f"Bearer {token}"}
    async with _client(_app()) as http:
        await http.patch(
            f"/v1/agents/{agent_id}", json={"reply_languages": ["te-IN", "en-IN"]}, headers=headers
        )
        response = await http.patch(
            f"/v1/agents/{agent_id}", json={"language_primary": "en-IN"}, headers=headers
        )
    assert response.status_code == 200, response.text
    assert await _roster_languages(token, agent_id) == ["en-IN"]


async def test_the_database_refuses_a_language_the_product_does_not_sell() -> None:
    tenant_id, agent_id, _token = await _tenant()
    with pytest.raises(Exception, match="ck_agents_languages_extra_offered"):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET languages_extra = ARRAY['ta-IN'] WHERE id = :aid"),
                {"aid": agent_id},
            )


async def test_a_refusal_names_its_reason_for_the_client() -> None:
    _tenant_id, agent_id, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}",
            json={"reply_languages": ["te-IN", "te-IN"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422
    assert "only once" in response.text
    assert _code(response.json())


# --- what the voice platform is sent ---------------------------------------------------------


def test_while_the_switch_is_off_one_language_is_sent_and_several_follow_the_caller() -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg())
    assert body["language"] == "Telugu" and "languages" not in body
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(languages_extra=["en-IN"]))
    assert body["language"] == "auto" and "languages" not in body
    assert body["voice"]["language"] is None


def test_with_the_switch_on_the_list_is_sent_in_order_instead(languages_on: None) -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(
        _cfg(language_primary="hi-IN", languages_extra=["en-IN", "te-IN"])
    )
    assert body["languages"] == ["Hindi", "English", "Telugu"]
    assert "language" not in body
    assert body["voice"]["language"] is None
    single = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg())
    assert single["languages"] == ["Telugu"] and single["voice"]["language"] == "Telugu"


async def test_a_platform_that_did_not_keep_the_list_refuses_the_publish(
    languages_on: None,
) -> None:
    handler, _seen = _recorder({("PATCH", "/agents/ag_1"): httpx.Response(200, json={})})
    with pytest.raises(ProblemError) as refused:
        await _engine(handler).update_agent(AGENT, _cfg(languages_extra=["en-IN"]))
    assert refused.value.code == "engine_languages_not_saved"


async def test_a_platform_that_kept_the_list_publishes(languages_on: None) -> None:
    def saved(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"languages": json.loads(request.content)["languages"]})

    seen: list[httpx.Request] = []
    handler, _ = _recorder({})

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PATCH" and request.url.path.endswith("/agents/ag_1"):
            return saved(request)
        return handler(request)

    await _engine(answer).update_agent(AGENT, _cfg(languages_extra=["en-IN"]))
    assert _body(_agent_write(seen))["languages"] == ["Telugu", "English"]


def test_the_read_back_compares_the_list_and_tolerates_what_we_do_not_send(
    languages_on: None,
) -> None:
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(languages_extra=["en-IN"]))
    held: dict[str, Any] = json.loads(json.dumps(wanted))
    # ThinnestAI reads `language` back as `auto` beside a list, and a re-ask delay we leave
    # at its default (update-agent.md:906-919; channels/voice.md `reaskAfterSeconds`).
    held["language"] = "auto"
    held["voice"]["reaskAfterSeconds"] = None
    held["languages"] = ["te-IN", "English"]
    assert _settings_drift(wanted, held) == []
    held["languages"] = ["English", "Telugu"]
    assert _settings_drift(wanted, held) == ["reply_languages"]
    del held["languages"]
    assert _settings_drift(wanted, held) == ["reply_languages"]


def test_with_the_switch_off_a_list_held_by_the_platform_is_not_drift() -> None:
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg())
    held: dict[str, Any] = json.loads(json.dumps(wanted))
    held["languages"] = []
    held["voice"]["reaskAfterSeconds"] = 2.5
    assert _settings_drift(wanted, held) == []


async def test_a_repair_sends_the_list_without_the_single_language(languages_on: None) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    await _engine(handler).repair_settings(AGENT, _cfg(), ["reply_languages"])
    assert sent == [{"languages": ["Telugu"]}]
