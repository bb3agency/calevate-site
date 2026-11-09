"""Every Studio agent speaks the dated Cartesia release unless an operator picks another model
(D-977): `sonic-3.6` "follows Cartesia's latest stable snapshot, the dated one never changes"
(thinnest-findings/mirror/snapshots/2026-10-29/pages/api-reference/agents/
set-agent-byok-voice.md:9).

New Studio agents get the model where they get the default emotion (`lifecycle.update_agent`);
migration e5a9c3d7b2f8 moves the Studio agents that existed with none, and its downgrade
clears exactly those. The migration runs against the migrated database in one transaction
that is rolled back, as `tests/nudge_floor_migration_test.py` exercises its revision."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents import voice_tuning
from apps.api.agents.models import (
    STUDIO_VOICE_MODELS,
    STUDIO_VOICE_OLD_MODEL,
    STUDIO_VOICE_PINNED_MODEL,
)
from apps.api.agents.service import _load_agent
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from calevate_shared.engine import ByokVoiceTuning
from sqlalchemy import Connection, create_engine, text
from tests.call_handling_test import _make_live, _tenant
from tests.studio_voice_tuning_test import VOICE, _choose_voice, _puts, _saved, _studio
from tests.thinnest_engine_test import WS, _engine, _recorder

PINNED = "sonic-3.6-2026-08-27"
STEM = "e5a9c3d7b2f8_studio_voice_model_pinned"


async def _model(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT studio_voice_model FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    return None if value is None else str(value)


async def _set_model(tenant_id: uuid.UUID, agent_id: uuid.UUID, model: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET studio_voice_model = :m WHERE id = :aid"),
            {"m": model, "aid": agent_id},
        )


def test_the_pinned_model_is_an_offered_dated_release() -> None:
    assert STUDIO_VOICE_PINNED_MODEL == PINNED
    assert STUDIO_VOICE_PINNED_MODEL in STUDIO_VOICE_MODELS
    assert STUDIO_VOICE_PINNED_MODEL != STUDIO_VOICE_OLD_MODEL
    assert voice_tuning.DEFAULT_STUDIO_MODEL == STUDIO_VOICE_PINNED_MODEL


async def test_a_new_agent_given_a_studio_voice_gets_the_pinned_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _choose_voice(monkeypatch, tenant_id, agent_id, f"byok:{VOICE}")
    assert await _model(tenant_id, agent_id) == PINNED


async def test_an_agent_switched_to_studio_with_no_model_gets_the_pinned_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _choose_voice(monkeypatch, tenant_id, agent_id, "engine:anjali")
    assert await _model(tenant_id, agent_id) is None, "a Clear voice takes no voice model"
    await _choose_voice(monkeypatch, tenant_id, agent_id, f"byok:{VOICE}")
    assert await _model(tenant_id, agent_id) == PINNED


async def test_an_operators_model_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _set_model(tenant_id, agent_id, "sonic-3.5")
    assert await _choose_voice(monkeypatch, tenant_id, agent_id, f"byok:{VOICE}") == "calm"
    assert await _model(tenant_id, agent_id) == "sonic-3.5"


async def test_the_older_model_stays_untuned(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _set_model(tenant_id, agent_id, STUDIO_VOICE_OLD_MODEL)
    assert await _choose_voice(monkeypatch, tenant_id, agent_id, f"byok:{VOICE}") is None
    assert await _model(tenant_id, agent_id) == STUDIO_VOICE_OLD_MODEL


async def test_a_null_model_is_still_an_operators_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _choose_voice(monkeypatch, tenant_id, agent_id, f"byok:{VOICE}")
    async with tenant_session(tenant_id) as session:
        await voice_tuning.set_voice_tuning(
            session, tenant_id=tenant_id, agent_id=agent_id, changes={"model": None}
        )
    await _choose_voice(monkeypatch, tenant_id, agent_id, "byok:cv-2")
    assert await _model(tenant_id, agent_id) is None


async def test_the_publish_sends_the_pinned_model(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _choose_voice(monkeypatch, tenant_id, agent_id, f"byok:{VOICE}")
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)
    tuning = voice_tuning.config_tuning(row["voice_tuning"], byok_voice_id=VOICE)
    assert tuning == ByokVoiceTuning(emotion="calm", model=PINNED)
    handler, seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("PUT", "/agents/ag_1/byok-voice"): _saved(emotion="calm", agentModel=PINNED),
        }
    )
    await _engine(handler).update_agent(f"ag_1@{WS}", _studio(engine_byok_voice_tuning=tuning))
    assert _puts(seen) == [{"voice": VOICE, "emotion": "calm", "model": PINNED}]


async def test_the_record_is_invisible_to_another_tenant() -> None:
    tenant_id, agent_id, _ = await _tenant()
    other_tenant, _other_agent, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO studio_voice_model_pins (tenant_id, agent_id, model) "
                "VALUES (:tid, :aid, :m)"
            ),
            {"tid": tenant_id, "aid": agent_id, "m": PINNED},
        )
    async with tenant_session(other_tenant) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM studio_voice_model_pins WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    assert seen == 0
    async with tenant_session(tenant_id) as session:
        own = (
            await session.execute(
                text("SELECT count(*) FROM studio_voice_model_pins WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    assert own == 1


# --- migration e5a9c3d7b2f8 ---------------------------------------------------------------


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as(connection: Connection, tenant: uuid.UUID) -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})


def _voice(connection: Connection, tenant: uuid.UUID, agent: uuid.UUID, voice: str) -> None:
    _as(connection, tenant)
    connection.execute(
        text("UPDATE agents SET engine_voice_id = :v WHERE id = :id"), {"v": voice, "id": agent}
    )


def _held(connection: Connection, tenant: uuid.UUID, agent: uuid.UUID) -> str | None:
    _as(connection, tenant)
    value = connection.execute(
        text("SELECT studio_voice_model FROM agents WHERE id = :id"), {"id": agent}
    ).scalar_one()
    return None if value is None else str(value)


def _set(connection: Connection, tenant: uuid.UUID, agent: uuid.UUID, model: str) -> None:
    _as(connection, tenant)
    connection.execute(
        text("UPDATE agents SET studio_voice_model = :m WHERE id = :id"),
        {"m": model, "id": agent},
    )


def _runs(connection: Connection, agent: uuid.UUID) -> list[str | None]:
    """The `min_revision` of each pin live-apply queued for `agent`."""
    rows = connection.execute(
        text(
            "SELECT o.min_revision FROM live_apply_runs r JOIN outbox_messages o "
            "ON o.payload ->> 'run_id' = r.id::text WHERE r.agent_id = :a AND r.scope = 'agent' "
            "AND r.reasons ? 'voice_model_pinned' ORDER BY r.created_at"
        ),
        {"a": agent},
    ).all()
    return [r[0] for r in rows]


async def test_the_migration_pins_studio_agents_and_its_downgrade_reverts_only_those() -> None:
    live_t, live_a, _ = await _tenant()  # a live Studio agent with no model
    draft_t, draft_a, _ = await _tenant()  # a draft Studio agent with no model
    chosen_t, chosen_a, _ = await _tenant()  # a Studio agent an operator put on sonic-3
    clear_t, clear_a, _ = await _tenant()  # a Clear agent with no model
    await _make_live(live_t, live_a)

    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    for tenant, agent in (
                        (live_t, live_a),
                        (draft_t, draft_a),
                        (chosen_t, chosen_a),
                    ):
                        _voice(connection, tenant, agent, f"byok:{VOICE}")
                    _set(connection, chosen_t, chosen_a, "sonic-3")
                    _voice(connection, clear_t, clear_a, "engine:anjali")

                    revision.upgrade()

                    assert _held(connection, live_t, live_a) == PINNED
                    assert _held(connection, draft_t, draft_a) == PINNED
                    assert _held(connection, chosen_t, chosen_a) == "sonic-3"
                    assert _held(connection, clear_t, clear_a) is None
                    assert _runs(connection, live_a) == [revision.revision]
                    assert _runs(connection, draft_a) == [], "the engine holds no draft"
                    assert _runs(connection, chosen_a) == []

                    # An operator moves the draft on; the downgrade leaves that choice alone.
                    _set(connection, draft_t, draft_a, "sonic-3.5")
                    revision.downgrade()

                    assert _held(connection, live_t, live_a) is None
                    assert _held(connection, draft_t, draft_a) == "sonic-3.5"
                    assert _held(connection, chosen_t, chosen_a) == "sonic-3"
                    assert _held(connection, clear_t, clear_a) is None
                    assert _runs(connection, live_a) == [revision.revision, None]

                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
