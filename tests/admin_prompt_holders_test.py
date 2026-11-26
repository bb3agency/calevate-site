"""The admin "What it is told" screen, one anatomy per engine holder (D-882 over D-1019).

1. A campaign's anatomy is composed from the campaign's own script and settings, not the
   agent's, and shows the drift verdict recorded on the campaign's own route.
2. The greeting, steps, settings and tools sections are the adapter's own body for a config.
3. A publish records what it sent on the route; a change to the holder reads as "changed
   since last publish" until the next publish.
4. Another tenant's routes never appear, and the read stays admin-only and audited.
5. The company training gives way where a script leaves it no room, rather than the publish
   being refused, and the cut is recorded for the owner.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.company_training import (
    TRAINING_HEADER,
    give_way,
    shortened_for,
    with_training,
)
from apps.api.agents.prompt_routes import router
from apps.api.agents.prompt_size import measure_config
from apps.api.core.auth import ADMIN_TENANT_READ_ACTION
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session
from apps.api.engine.publish_view import publish_view
from apps.api.engine.thinnest import (
    CALL_INSTRUCTIONS_FIELD,
    INSTRUCTIONS_MAX_CHARS,
    ThinnestEngine,
    _steps_body,
)
from calevate_shared.call_script import NativeStep
from calevate_shared.engine import (
    LAYER_SEPARATOR,
    AgentConfig,
    compose_engine_prompt,
    compose_first_utterance,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.call_handling_test import _operator
from tests.campaign_engine_agents_test import OTHER, _campaign, _live_agent, _publish
from tests.thinnest_engine_test import _cfg

pytestmark = pytest.mark.rls


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


def _path(tenant_id: UUID, agent_id: UUID) -> str:
    return f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt/layers"


async def _read(tenant_id: UUID, agent_id: UUID) -> dict[str, Any]:
    async with _client() as client:
        got = await client.get(_path(tenant_id, agent_id), headers=await _operator())
    assert got.status_code == 200, got.text
    body: dict[str, Any] = got.json()
    return body


def _holder(body: dict[str, Any], kind: str, holder_id: UUID | None = None) -> dict[str, Any]:
    [found] = [
        h
        for h in body["holders"]
        if h["kind"] == kind and (holder_id is None or h["holder_id"] == str(holder_id))
    ]
    return found


def _layer(holder: dict[str, Any], key: str) -> str:
    [layer] = [x for x in holder["layers"] if x["key"] == key]
    return str(layer["text"])


async def _route_ref(tenant_id: UUID, campaign_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    return str(ref)


# --- 1. one anatomy per holder ------------------------------------------------------------


async def test_a_campaigns_anatomy_is_its_own_script_and_overrides_not_the_agents() -> None:
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(
        tenant_id, agent_id, script=OTHER, status="running", overrides={"language_primary": "hi-IN"}
    )
    await _publish(tenant_id, campaign_id)

    body = await _read(tenant_id, agent_id)

    campaign = _holder(body, "campaign", campaign_id)
    own = _holder(body, "agent")
    assert campaign["name"].startswith("Calls ") and campaign["status"] == "running"
    # The two scripts differ only in their opening, which the model reads quoted as already
    # said, under START OF THE CALL.
    assert "evening hours" in _layer(campaign, "notices")
    assert "evening hours" not in _layer(own, "notices")
    async with tenant_session(tenant_id) as session:
        cfg = await agents_service.campaign_config(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert cfg.language_primary == "hi-IN"
    joined = LAYER_SEPARATOR.join(layer["text"] for layer in campaign["layers"])
    assert joined == compose_engine_prompt(cfg)
    assert campaign["total_chars"] == len(joined)
    assert campaign["sent_now"]["greeting"] == compose_first_utterance(cfg)


async def test_each_holder_shows_the_drift_verdict_on_its_own_route() -> None:
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=OTHER, status="running")
    await _publish(tenant_id, campaign_id)
    ref = await _route_ref(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET drift_state = 'not_applied', "
                "drift_checked_at = now() WHERE engine_agent_ref = :r"
            ),
            {"r": ref},
        )

    body = await _read(tenant_id, agent_id)

    campaign = _holder(body, "campaign", campaign_id)
    assert campaign["drift_state"] == "not_applied" and campaign["drift_checked_at"]
    assert _holder(body, "agent")["drift_state"] != "not_applied"


# --- 2. the sections are the adapter's own body -------------------------------------------


def _thinnest() -> ThinnestEngine:
    # The body builders make no request, so no transport is needed.
    return ThinnestEngine(api_key="ta_live_test")


def test_the_settings_and_tools_sections_match_the_adapters_body() -> None:
    engine = _thinnest()
    cfg = _cfg(
        script_steps=(NativeStep(title="Greet", detail="Say who you are."),),
        temperature=0.4,
        interrupt_words=3,
        max_call_duration_s=420,
        filler_lines=("One moment.", "Let me check."),
        turn_detection="ear",
    )
    body = engine._agent_body(cfg)
    tools = ThinnestEngine.built_in_tools_body(cfg)

    view = publish_view(engine, cfg)

    assert view.greeting == body["greeting"]
    assert [(s.title, s.detail) for s in view.steps] == [
        (s["title"], s["detail"]) for s in _steps_body(cfg)
    ]
    settings = {s.key: s.value for s in view.settings}
    assert settings["temperature"] == f"{body['temperature']:g}"
    assert settings["max_call_seconds"] == f"{body['voice']['maxCallSeconds']} s"
    assert settings["interrupt_words"] == str(body["voice"]["interruptWords"])
    assert settings["byok"] == body["byok"]
    assert settings["acknowledgements"] == ("on" if body["voice"]["acknowledgements"] else "off")
    assert settings["languages"] == ", ".join(body["languages"])
    rules = body["voice"][CALL_INSTRUCTIONS_FIELD]
    assert settings["call_instructions"] == (
        f"ours, {len(rules):,} characters" if rules else "the platform's defaults"
    )
    assert list(view.thinking_lines) == body["voice"]["thinkingLines"]
    switches = {t.key: t.on for t in view.built_in_tools}
    assert {k: switches[k] for k in tools["tools"]} == tools["tools"]
    assert view.digest.instructions_chars == len(body["instructions"])
    # The hand-over phone is never in the view (hard rule 6).
    assert "phone" not in json.dumps([s.value for s in view.settings])


def test_the_digest_moves_with_what_is_sent_and_only_with_it() -> None:
    engine = _thinnest()
    cfg = _cfg()
    same = publish_view(engine, cfg).digest
    assert publish_view(engine, cfg.model_copy()).digest == same
    assert publish_view(engine, cfg.model_copy(update={"temperature": 0.9})).digest != same
    # A field no request carries leaves it alone.
    assert publish_view(engine, cfg.model_copy(update={"training_cut_chars": 5})).digest == same


# --- 3. what was sent last ----------------------------------------------------------------


async def test_a_publish_records_what_it_sent_and_a_change_reads_as_changed_since() -> None:
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=OTHER, status="running")
    await _publish(tenant_id, campaign_id)
    ref = await _route_ref(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        first = (
            await session.execute(
                text(
                    "SELECT published_digest, published_at, published_instructions_chars "
                    "FROM engine_agent_routes WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    assert first[0] and first[1] and first[2] > 0

    body = await _read(tenant_id, agent_id)
    campaign = _holder(body, "campaign", campaign_id)
    assert campaign["changed_since_publish"] is False
    assert campaign["published"]["instructions_chars"] == campaign["sent_now"]["instructions_chars"]

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET settings_overrides = CAST(:o AS jsonb) WHERE id = :c"),
            {"o": json.dumps({"language_primary": "hi-IN"}), "c": campaign_id},
        )
    assert _holder(await _read(tenant_id, agent_id), "campaign", campaign_id)[
        "changed_since_publish"
    ]

    await _publish(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        second = (
            await session.execute(
                text(
                    "SELECT published_digest, published_at FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    assert second[0] != first[0] and second[1] >= first[1]
    assert (
        _holder(await _read(tenant_id, agent_id), "campaign", campaign_id)["changed_since_publish"]
        is False
    )


# --- 4. isolation, permission and audit ----------------------------------------------------


async def test_another_tenants_routes_never_appear() -> None:
    tenant_a, agent_a = await _live_agent()
    tenant_b, agent_b = await _live_agent()
    campaign_b = await _campaign(tenant_b, agent_b, script=OTHER, status="running")
    await _publish(tenant_b, campaign_b)
    # A route of B's that names A's agent: the routing table has no foreign key, so only the
    # tenant predicate keeps it out.
    async with tenant_session(tenant_b) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": f"fake_cross_{uuid.uuid4().hex[:8]}", "t": tenant_b, "a": agent_a},
        )

    body = await _read(tenant_a, agent_a)

    assert [h["kind"] for h in body["holders"]] == ["agent"]
    assert "evening hours" not in json.dumps(body)
    async with _client() as client:
        got = await client.get(_path(tenant_a, agent_b), headers=await _operator())
    assert got.status_code == 404, got.text


async def test_it_is_admin_only_and_each_read_is_audited() -> None:
    from tests.call_handling_test import _tenant

    tenant_id, agent_id, client_headers = await _tenant()
    async with _client() as client:
        refused = await client.get(_path(tenant_id, agent_id), headers=client_headers)
        allowed = await client.get(_path(tenant_id, agent_id), headers=await _operator())
    assert refused.status_code in (401, 403)
    assert allowed.status_code == 200, allowed.text
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE tenant_id = :tid AND action = :action"),
                {"tid": tenant_id, "action": ADMIN_TENANT_READ_ACTION},
            )
        ).scalar_one()
    assert rows == 1


# --- 5. the company training gives way ----------------------------------------------------


def _training(lines: int) -> str:
    return "\n".join(
        f"- Point {i}: the shop is open from nine to seven and takes orders by phone."
        for i in range(lines)
    )


def test_the_training_gives_way_line_by_line_rather_than_the_publish_being_refused() -> None:
    engine = _thinnest()
    base = _cfg(system_prompt="[IDENTITY]\n" + "You take orders for the shop. " * 300)
    training = _training(80)

    def compose(value: str) -> AgentConfig:
        return with_training(base, value)

    assert not measure_config(compose(training), engine).fits, "the fixture must overflow"
    fitted = give_way(compose, training, engine)

    size = measure_config(fitted, engine)
    assert size.fits and size.total <= INSTRUCTIONS_MAX_CHARS
    assert fitted.training_cut_chars > 0
    assert TRAINING_HEADER in fitted.system_prompt and "Point 0:" in fitted.system_prompt
    assert "Point 79:" not in fitted.system_prompt
    # The adapter accepts what the publish would send.
    assert engine._agent_body(fitted)["instructions"]


def test_a_training_that_fits_is_left_whole() -> None:
    engine = _thinnest()
    base = _cfg(system_prompt="[IDENTITY]\nYou take orders for the shop.")
    training = _training(10)
    whole = give_way(lambda value: with_training(base, value), training, engine)
    assert whole.training_cut_chars == 0 and "Point 9:" in whole.system_prompt


def test_a_script_over_on_its_own_still_refuses_with_no_training_in_it() -> None:
    engine = _thinnest()
    base = _cfg(system_prompt="[IDENTITY]\n" + "You take orders for the shop. " * 800)
    fitted = give_way(lambda value: with_training(base, value), _training(20), engine)
    assert TRAINING_HEADER not in fitted.system_prompt
    assert not measure_config(fitted, engine).fits
    assert fitted.training_cut_chars > 0


async def test_a_recorded_cut_is_listed_for_the_owner() -> None:
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=OTHER, status="running")
    await _publish(tenant_id, campaign_id)
    ref = await _route_ref(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET published_training_cut_chars = 1564 "
                "WHERE engine_agent_ref = :r"
            ),
            {"r": ref},
        )
        found = await shortened_for(session, tenant_id)
    assert [(s.kind, s.holder_id, s.cut_chars) for s in found] == [("campaign", campaign_id, 1564)]
