"""A rotated Cartesia key reaches the voice platform, and our key switched off there under live
Studio agents is alarmed, not silently re-enabled (D-688).

`ops/secret_routes.set_secret_route` enqueues `push_studio_voice_key` through the outbox for a
`cartesia_api_key` version; the job replaces the workspace's Cartesia voice key (the model is
kept by the platform) only while one is installed. The hourly voice sync reads `GET /byok` and
raises `studio_voice_key_off_with_agents` when our key is off while Studio agents are
published; it never switches it back on.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from apps.api.agents import hosted_voices
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from apps.api.ops import secret_routes
from apps.workers import studio_voice_key
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.hosted_voice_fakes import OFF_KEY, HostingEngine, selected


@pytest.fixture
def stored_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str | None]]:
    """The key the store resolves, as a dict a test edits."""
    holder: dict[str, str | None] = {"key": "sk_car_new"}

    async def _key() -> str | None:
        return holder["key"]

    monkeypatch.setattr(studio_voice_key, "_current_key", _key)
    yield holder


async def test_a_rotated_key_replaces_the_installed_one_and_keeps_its_model(
    stored_key: dict[str, str | None],
) -> None:
    engine = HostingEngine()
    with selected(engine):
        assert await studio_voice_key.push_studio_voice_key({}, {"version": 2}) == "pushed"
    assert engine.installed == [("cartesia", None)]


async def test_nothing_is_pushed_where_studio_has_no_key_or_the_engine_hosts_no_voices(
    stored_key: dict[str, str | None],
) -> None:
    engine = HostingEngine(key_state=OFF_KEY)
    with selected(engine):
        assert await studio_voice_key.push_studio_voice_key({}, {}) == "no_studio_key"
    with selected(FakeEngine()):
        assert await studio_voice_key.push_studio_voice_key({}, {}) == "not_hosted"
    assert engine.installed == []


async def test_no_key_in_the_store_pushes_nothing(stored_key: dict[str, str | None]) -> None:
    stored_key["key"] = None
    engine = HostingEngine()
    with selected(engine):
        assert await studio_voice_key.push_studio_voice_key({}, {}) == "no_key"
    assert engine.installed == []


async def test_a_refused_push_pages_without_the_key(
    stored_key: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        studio_voice_key,
        "alert",
        lambda stage, code, **kw: raised.append((code, str(kw.get("detail")))),
    )
    engine = HostingEngine()

    async def _refused(**kw: Any) -> None:
        raise ProblemError(
            kind="business_rule", code="engine_voice_key_rejected", title="x", detail="x"
        )

    engine.install_own_voice_key = _refused  # type: ignore[method-assign]
    with selected(engine):
        assert await studio_voice_key.push_studio_voice_key({}, {}) == "failed"
    assert [code for code, _ in raised] == ["studio_voice_key_push_failed"]
    assert "sk_car_new" not in raised[0][1]


async def test_the_key_is_read_from_the_store_and_falls_back_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.settings import get_settings
    from apps.api.ops.secret_service import ResolvedSecrets

    async def _resolved(session: Any) -> ResolvedSecrets:
        return ResolvedSecrets(values={}, unreadable=())

    monkeypatch.setattr(studio_voice_key, "resolve_secrets", _resolved)
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_env")
    get_settings.cache_clear()
    try:
        assert await studio_voice_key._current_key() == "sk_env"
    finally:
        get_settings.cache_clear()


async def test_saving_the_cartesia_key_enqueues_one_push_per_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.ops import secret_routes as routes_module

    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    from apps.api.ops.secret_service import SecretRecord

    version = 900_000 + uuid.uuid4().int % 99_999

    async def _stored(session: Any, *, key: str, value: str, actor_id: Any) -> SecretRecord:
        # Not the real store: a stored Cartesia key would reach every later test's settings.
        return SecretRecord(
            key=key,
            env_var=key.upper(),
            version=version,
            last_four="abcd",
            kek_id=1,
            created_at="2026-10-08T00:00:00Z",
            created_by=None,
            shadowed_by_env=False,
            versions=version,
            applies="live",
            caveat=None,
        )

    async def _quiet() -> int:
        return 0

    monkeypatch.setattr(routes_module, "set_secret", _stored)
    monkeypatch.setattr(routes_module, "propagate", _quiet)
    monkeypatch.setattr(routes_module, "alert", lambda *a, **k: None)
    headers = {
        "Authorization": f"Bearer dev:admin:{admin_id}",
        "X-Confirm-Action": f"set_secret:{secret_routes.STUDIO_VOICE_SECRET}",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.put(
            f"/v1/ops/secrets/{secret_routes.STUDIO_VOICE_SECRET}",
            headers=headers,
            json={"value": f"sk_car_{uuid.uuid4().hex}", "reason": "rotation test"},
        )
    assert response.status_code == 200, response.text
    async with admin_session() as session:
        jobs = (
            await session.execute(
                text("DELETE FROM outbox_messages WHERE dedupe_key = :k RETURNING job"),
                {"k": f"studio-voice-key:{version}"},
            )
        ).all()
    assert [row[0] for row in jobs] == [secret_routes.PUSH_STUDIO_VOICE_KEY_JOB]


async def test_our_key_off_under_live_studio_agents_is_alarmed_and_not_switched_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(hosted_voices, "alert", lambda stage, code, **kw: raised.append(code))

    async def _live(session: Any, *, engine: str) -> int:
        return 2

    monkeypatch.setattr(hosted_voices, "live_studio_agents", _live)
    engine = HostingEngine(key_state=OFF_KEY)
    async with admin_session() as session:
        await hosted_voices.sync_hosted_voices(session, engine, engine_name="thinnest")
    assert "studio_voice_key_off_with_agents" in raised
    assert engine.enabled == 0 and engine.installed == []


async def test_our_key_off_with_no_studio_agent_is_only_a_stated_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(hosted_voices, "alert", lambda stage, code, **kw: raised.append(code))

    async def _live(session: Any, *, engine: str) -> int:
        return 0

    monkeypatch.setattr(hosted_voices, "live_studio_agents", _live)
    async with admin_session() as session:
        result = await hosted_voices.sync_hosted_voices(
            session, HostingEngine(key_state=OFF_KEY), engine_name="thinnest"
        )
    assert "studio_voice_key_off_with_agents" not in raised
    assert result.studio_skipped_reason == hosted_voices.STUDIO_KEY_OFF_REASON
