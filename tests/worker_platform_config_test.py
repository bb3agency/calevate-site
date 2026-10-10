"""The worker adopts the ops console's settings and sealed keys at startup.

Without `start_config_refresher` the workers process ran on `.env` plus code defaults: the
webhook sweep read `webhook_base_url` as `http://localhost:8100` on the VPS and refused
with `engine_webhook_url_not_public`, and every key saved only in the console was invisible
to the jobs that call that vendor.

Asserted through the REAL `startup` and `shutdown`, against a VALUE rather than a flag, as
`tests/platform_config_test.py::test_voice_runtime_adopts_console_config_when_it_boots`
does for voice-runtime: the store's figure must be what `get_settings()` answers with when
`startup` returns, before any job runs. The parts of `startup` that need a tracing provider
or the other two polls are stubbed; the config adoption is not.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core import platform_config as pc
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.workers import settings as worker_settings
from sqlalchemy import text

KEY = "self_serve_inr_per_min"


async def _write_row(value: str) -> None:
    async with untenanted_session() as session:
        admin = (await session.execute(text("SELECT id FROM admin_users LIMIT 1"))).scalar()
        if admin is None:
            admin = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                    "VALUES (:i, 'Worker Config Test', 'superadmin', now(), now())"
                ),
                {"i": admin},
            )
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by, note) "
                "VALUES (:k, CAST(:v AS jsonb), :by, 'worker_platform_config_test') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
            ),
            {"k": KEY, "v": value, "by": admin},
        )


@pytest.fixture
async def _cold_process(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """A process that has never read the store, with the rest of `startup` inert."""
    await pc.stop_config_refresher()
    pc.reset_for_test()
    for name in (
        "validate_bootstrap_env",
        "configure_logging",
        "install_arq_terminal_alerter",
        "start_fx_refresher",
        "start_pricing_refresher",
        "shutdown_tracing",
        "close_admission",
    ):
        monkeypatch.setattr(worker_settings, name, lambda *a, **k: None)
    monkeypatch.setattr(worker_settings, "init_observability", lambda *_: "off")

    async def _quiet(*_: Any) -> None:
        return None

    for name in ("stop_fx_refresher", "stop_pricing_refresher", "close_redis", "close_queue"):
        monkeypatch.setattr(worker_settings, name, _quiet)
    yield
    await pc.stop_config_refresher()
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": KEY})
    pc.reset_for_test()


@pytest.mark.usefixtures("_cold_process")
async def test_startup_adopts_console_config_and_shutdown_stops_the_poll() -> None:
    assert pc.snapshot().loaded_at is None, "this test must start from a process that never read"
    await _write_row('"13.75"')

    await worker_settings.startup({})

    # Read already, not left to the first poll: a job starting now sees the console.
    assert pc.snapshot().loaded_at is not None
    in_force = get_settings().self_serve_inr_per_min
    assert in_force == Decimal("13.75") and str(in_force) == "13.75"
    # The worker calls vendors, so it adopts the sealed keys too.
    assert pc._secrets_adopted is True
    task = pc._refresher
    assert task is not None and not task.done()

    await worker_settings.shutdown({})

    assert task.done()
    assert pc._refresher is None


def test_the_worker_calls_the_real_config_doors() -> None:
    """The stubs above replace the other polls, never these; pin that they are the module's."""
    assert worker_settings.start_config_refresher is pc.start_config_refresher
    assert worker_settings.stop_config_refresher is pc.stop_config_refresher
    assert worker_settings.refresh_platform_config is pc.refresh
