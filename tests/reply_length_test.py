"""The longest reply an agent may give (D-769): ThinnestAI's `maxReplyTokens`.

Vendor shape: `thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/agents/
update-agent.md:703-709,839-845` and create-agent.md:760-768 — an integer 100-800, default
300, one ceiling for chat and calls, read back on the Agent the write answers with.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.agents import prompts, reply_length
from apps.api.agents.reply_length_routes import admin_router
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops.config_service import validated_value
from calevate_shared.engine import AgentConfig
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.call_handling_test import _make_live, _operator, _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import WS, _cfg, _engine, _recorder

REF = f"ag_1@{WS}"


def _body(cfg: AgentConfig) -> dict[str, Any]:
    return _engine(lambda _r: httpx.Response(500))._agent_body(cfg)


# --- the wire ------------------------------------------------------------------------


def test_every_agent_write_states_the_ceiling_default_or_its_own() -> None:
    assert _body(_cfg())["maxReplyTokens"] == 300
    assert _body(_cfg(max_reply_tokens=650))["maxReplyTokens"] == 650


@pytest.mark.parametrize("tokens", [99, 801])
def test_a_ceiling_outside_the_platforms_range_cannot_be_configured(tokens: int) -> None:
    with pytest.raises(ValidationError):
        AgentConfig(
            tenant_id="t",
            agent_id="a",
            name="n",
            direction="both",
            language_primary="te-IN",
            system_prompt="s",
            opening_line="o",
            max_reply_tokens=tokens,
        )


async def test_a_ceiling_the_platform_did_not_keep_refuses_the_publish() -> None:
    handler, _seen = _recorder(
        {("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1", "maxReplyTokens": 300})}
    )
    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(REF, _cfg(max_reply_tokens=650))
    assert caught.value.code == "engine_reply_length_not_saved"


async def test_a_ceiling_read_back_as_a_rounded_number_is_the_one_sent() -> None:
    handler, _seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(
                200, json={"id": "ag_1", "maxReplyTokens": 650.0}
            )
        }
    )
    await _engine(handler).update_agent(REF, _cfg(max_reply_tokens=650))


async def test_the_sweep_finds_a_moved_ceiling_and_puts_back_only_it() -> None:
    cfg = _cfg(max_reply_tokens=650)
    handler, seen = _recorder(
        {
            ("GET", "/agents/ag_1"): httpx.Response(
                200, json={**_body(cfg), "id": "ag_1", "maxReplyTokens": 300}
            ),
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
        }
    )
    engine = _engine(handler)
    drifted = await engine.settings_drift(REF, cfg)
    assert drifted == ["reply_length"]
    await engine.repair_settings(REF, cfg, drifted)
    [patch] = [r for r in seen if r.method == "PATCH" and r.url.path.endswith("/agents/ag_1")]
    assert json.loads(patch.content) == {"maxReplyTokens": 650}


async def test_a_ceiling_held_as_sent_is_not_drift() -> None:
    cfg = _cfg(max_reply_tokens=650)
    handler, _seen = _recorder(
        {("GET", "/agents/ag_1"): httpx.Response(200, json={**_body(cfg), "id": "ag_1"})}
    )
    assert "reply_length" not in await _engine(handler).settings_drift(REF, cfg)


# --- the console setting ---------------------------------------------------------------


def test_the_console_setting_takes_the_platforms_range_only() -> None:
    assert validated_value("thinnest_reply_length", 650) == 650
    with pytest.raises(ProblemError) as caught:
        validated_value("thinnest_reply_length", 900)
    assert caught.value.code == "config_value_invalid"


# --- storage, routes, publish ------------------------------------------------------------


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(admin_router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


async def _reply_length_queued_for(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
    """A pending live apply covering the agent carries the reason. Covering, not owned: a
    pending platform or tenant run another suite left coalesces this save into itself
    (`live_apply.queue_live_apply`), so the agent's own run may legitimately not exist."""
    async with untenanted_session() as session:
        found = (
            await session.execute(
                text(
                    "SELECT 1 FROM live_apply_runs WHERE status = 'pending' "
                    "AND reasons ? 'reply_length' AND (scope = 'platform' "
                    "OR (scope = 'tenant' AND tenant_id = :tid) "
                    "OR (scope = 'agent' AND agent_id = :aid))"
                ),
                {"tid": tenant_id, "aid": agent_id},
            )
        ).first()
    return found is not None


def _path(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    return f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/reply-length"


async def test_the_column_refuses_what_the_platform_refuses() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    for tokens in (99, 801):
        with pytest.raises(IntegrityError):
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text("UPDATE agents SET max_reply_tokens = :t WHERE id = :aid"),
                    {"t": tokens, "aid": agent_id},
                )


async def test_an_operator_sets_and_clears_the_ceiling_audited_and_applied_live() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    operator = await _operator()
    async with _client() as client:
        first = await client.get(_path(tenant_id, agent_id), headers=operator)
        assert first.status_code == 200, first.text
        assert first.json() == {
            "agent_id": str(agent_id),
            "max_reply_tokens": None,
            "default": 300,
            "effective": 300,
            "min": 100,
            "max": 800,
        }
        saved = await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"max_reply_tokens": 500}
        )
        assert saved.status_code == 200, saved.text
        assert (saved.json()["max_reply_tokens"], saved.json()["effective"]) == (500, 500)
        # The same value again moves nothing and queues nothing.
        await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"max_reply_tokens": 500}
        )
        cleared = await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"max_reply_tokens": None}
        )
        assert (cleared.json()["max_reply_tokens"], cleared.json()["effective"]) == (None, 300)
        refused = await client.patch(
            _path(tenant_id, agent_id), headers=operator, json={"max_reply_tokens": 900}
        )
        assert refused.status_code == 422, refused.text

    assert await _reply_length_queued_for(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        audits = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :tid "
                    "AND action = 'admin.agent_reply_length_set'"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    assert audits == 2


async def test_a_client_cannot_reach_the_operator_routes() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=headers)
    assert got.status_code in (401, 403)


async def test_the_publish_config_carries_the_agents_ceiling_else_the_consoles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        monkeypatch.setattr(get_settings(), "thinnest_reply_length", 400)
        inherited = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
        await reply_length.set_reply_length(
            session, tenant_id=tenant_id, agent_id=agent_id, tokens=700
        )
        own = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
    assert (inherited.max_reply_tokens, own.max_reply_tokens) == (400, 700)
    # Excluded from dumps, so stored configs and their digests do not move.
    assert "max_reply_tokens" not in own.model_dump()
