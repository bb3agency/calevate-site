"""Our Cartesia key reaches every workspace that holds it, and every Studio client workspace is
kept on it (D-717).

`ops/secret_routes.set_secret_route` enqueues `push_studio_voice_key` through the outbox for a
`cartesia_api_key` version. It replaces the key held in our developer workspace (its switch
untouched) and fans out one `push_studio_voice_key_to_workspace` per Studio client workspace,
each with its own retries and alarm. The hourly `sweep_studio_workspaces` verifies each Studio
workspace, repairs one found off (Clear agents kept off first), and alarms when our developer
workspace's switch is on, which it never turns off itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from apps.api.ops import secret_routes
from apps.workers import studio_voice_key
from arq import Retry
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.hosted_voice_fakes import (
    OFF_KEY,
    READY_KEY,
    STUDIO_WS,
    HostingEngine,
    selected,
    use_studio_workspace,
)

HELD = OFF_KEY.model_copy(update={"voice_provider": "cartesia"})


@pytest.fixture
def stored_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str | None]]:
    """The key the store resolves, as a dict a test edits."""
    holder: dict[str, str | None] = {"key": "sk_car_new"}

    async def _key() -> str | None:
        return holder["key"]

    monkeypatch.setattr(studio_voice_key, "_current_key", _key)
    yield holder


@pytest.fixture
def fanned(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The per-workspace jobs a rotation enqueued, captured instead of written."""
    jobs: list[dict[str, Any]] = []

    async def _enqueue(session: Any, *, job: str, payload: dict[str, Any]) -> uuid.UUID:
        jobs.append({"job": job, **payload})
        return uuid.uuid4()

    monkeypatch.setattr(studio_voice_key, "enqueue_outbox", _enqueue)
    return jobs


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        studio_voice_key,
        "alert",
        lambda stage, code, **kw: raised.append((code, str(kw.get("detail")))),
    )
    return raised


async def test_a_rotation_replaces_the_held_key_and_fans_out_one_push_per_studio_workspace(
    stored_key: dict[str, str | None],
    fanned: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = use_studio_workspace(monkeypatch)
    engine = HostingEngine(key_state=HELD)
    with selected(engine):
        result = await studio_voice_key.push_studio_voice_key({}, {"version": 2})
    assert result == "developer=pushed workspaces=1"
    # The model is kept by the platform, so only the key is sent; ours is never switched on.
    assert engine.installed == [("cartesia", None)] and engine.installed_in == [None]
    assert engine.enabled == 0
    assert fanned == [
        {"job": studio_voice_key.PUSH_TO_WORKSPACE_JOB, "tenant_id": str(row.tenant_id)}
    ]


async def test_a_developer_workspace_holding_no_key_still_fans_out(
    stored_key: dict[str, str | None],
    fanned: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_studio_workspace(monkeypatch)
    engine = HostingEngine(key_state=OFF_KEY)
    with selected(engine):
        result = await studio_voice_key.push_studio_voice_key({}, {})
    assert result == "developer=not_held workspaces=1"
    assert engine.installed == [] and len(fanned) == 1


async def test_nothing_is_pushed_without_a_key_or_on_an_engine_hosting_no_voices(
    stored_key: dict[str, str | None], fanned: list[dict[str, Any]]
) -> None:
    with selected(FakeEngine()):
        assert await studio_voice_key.push_studio_voice_key({}, {}) == "not_hosted"
    stored_key["key"] = None
    engine = HostingEngine(key_state=HELD)
    with selected(engine):
        assert await studio_voice_key.push_studio_voice_key({}, {}) == "no_key"
    assert engine.installed == [] and fanned == []


async def test_a_workspace_push_installs_the_key_in_that_clients_workspace(
    stored_key: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ws(tenant_id: Any) -> str:
        return STUDIO_WS

    monkeypatch.setattr(studio_voice_key, "workspace_for_tenant", _ws)
    engine = HostingEngine(key_state=OFF_KEY)
    with selected(engine):
        result = await studio_voice_key.push_studio_voice_key_to_workspace(
            {"job_try": 1}, {"tenant_id": str(uuid.uuid4())}
        )
    assert result == "pushed" and engine.installed_in == [STUDIO_WS]


@pytest.mark.parametrize("attempt", [1, 99])
async def test_a_failed_workspace_push_retries_then_pages_without_the_key(
    stored_key: dict[str, str | None],
    alarms: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    attempt: int,
) -> None:
    async def _ws(tenant_id: Any) -> str:
        return STUDIO_WS

    monkeypatch.setattr(studio_voice_key, "workspace_for_tenant", _ws)
    engine = HostingEngine()

    async def _refused(**kw: Any) -> None:
        raise ProblemError(kind="dependency", code="engine_unavailable", title="x", detail="x")

    engine.install_own_voice_key = _refused  # type: ignore[method-assign]
    payload = {"tenant_id": str(uuid.uuid4())}
    with selected(engine):
        if attempt == 1:
            with pytest.raises(Retry):
                await studio_voice_key.push_studio_voice_key_to_workspace(
                    {"job_try": attempt}, payload
                )
            assert alarms == []
            return
        result = await studio_voice_key.push_studio_voice_key_to_workspace(
            {"job_try": attempt}, payload
        )
    assert result == "failed"
    assert [code for code, _ in alarms] == ["studio_voice_key_push_failed"]
    assert "sk_car_new" not in alarms[0][1]


async def test_the_hourly_check_records_a_ready_workspace_and_repairs_one_found_off(
    alarms: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings

    use_studio_workspace(monkeypatch)
    ready = HostingEngine(key_state=OFF_KEY)
    ready.workspace_keys[STUDIO_WS] = READY_KEY
    with selected(ready):
        assert "ok=1 repaired=0 failed=0" in await studio_voice_key.sweep_studio_workspaces({})
    assert ready.enabled == 0 and alarms == []

    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    get_settings.cache_clear()
    try:
        drifted = HostingEngine(key_state=OFF_KEY)
        drifted.workspace_keys[STUDIO_WS] = OFF_KEY
        with selected(drifted):
            summary = await studio_voice_key.sweep_studio_workspaces({})
    finally:
        monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
        get_settings.cache_clear()
    assert "repaired=1" in summary
    assert drifted.installed_in == [STUDIO_WS] and drifted.enabled == 1
    assert drifted.workspace_keys[STUDIO_WS].speaks_on_own_voice
    assert [code for code, _ in alarms] == ["studio_workspace_repaired"]


async def test_a_workspace_that_cannot_be_repaired_pages(
    alarms: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.settings import get_settings

    use_studio_workspace(monkeypatch)
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    get_settings.cache_clear()
    engine = HostingEngine(key_state=OFF_KEY)
    engine.workspace_keys[STUDIO_WS] = OFF_KEY
    try:
        with selected(engine):
            summary = await studio_voice_key.sweep_studio_workspaces({})
    finally:
        get_settings.cache_clear()
    assert "failed=1" in summary and engine.enabled == 0
    assert [code for code, _ in alarms] == ["studio_workspace_drift"]


async def test_our_developer_switch_found_on_is_alarmed_and_never_switched_off_here(
    alarms: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _none(*, limit: int = 1000) -> list[Any]:
        return []

    monkeypatch.setattr(studio_voice_key, "studio_workspaces", _none)
    engine = HostingEngine(key_state=READY_KEY)
    with selected(engine):
        summary = await studio_voice_key.sweep_studio_workspaces({})
    assert summary.startswith("developer_on=True")
    assert [code for code, _ in alarms] == ["studio_developer_switch_on"]
    assert engine.disabled == 0


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
            installed=True,
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
