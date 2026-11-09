"""Backend audit round 5, lane Z10 (10 Nov 2026): the machinery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.core.loadshed import set_platform_status
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.whatsapp import accounts, signup
from apps.workers import call_translation
from apps.workers.fleet_walk import FLEET_CURSOR_KEY
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.whatsapp_embedded_signup_test import _client as _whatsapp_client
from tests.whatsapp_embedded_signup_test import (  # noqa: F401 - pytest fixtures
    _connect,
    _waba,
    fake_graph,
    meta_app,
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_the_slowdown_reason_is_kept_and_shown_until_the_platform_returns_to_normal() -> None:
    """Z10-01: the console promises whoever finds the platform slowed reads the reason."""
    token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}"}
    reason = "database under heavy load — lift when replication catches up"
    try:
        async with _client() as http:
            shed = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "set_load_shed:reduced"},
                json={"load_shed_mode": "reduced", "reason": reason},
            )
            assert shed.status_code == 200, shed.text
            assert shed.json()["load_shed_reason"] == reason

            # A different operator, later: the read must answer why.
            read = await http.get("/v1/ops/platform", headers=auth)
            assert read.json()["load_shed_mode"] == "reduced"
            assert read.json()["load_shed_reason"] == reason

            # A halt in the same incident does not erase why the platform was slowed.
            halted = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "halt_outbound"},
                json={"outbound_halted": True, "reason": "dials failing"},
            )
            assert halted.json()["load_shed_reason"] == reason

            # A maintenance window flipping the mode carries no operator reason, so the
            # slowdown's reason is not shown beside a mode it did not explain.
            await set_platform_status(mode="maintenance", actor_id=None)
            read = await http.get("/v1/ops/platform", headers=auth)
            assert read.json()["load_shed_mode"] == "maintenance"
            assert read.json()["load_shed_reason"] is None

            back = await http.post(
                "/v1/ops/platform",
                headers={
                    **auth,
                    "X-Confirm-Action": "release_outbound+set_load_shed:normal",
                },
                json={
                    "outbound_halted": False,
                    "load_shed_mode": "normal",
                    "reason": "load is back to normal",
                },
            )
            assert back.status_code == 200, back.text
            assert back.json()["load_shed_reason"] is None
    finally:
        await set_platform_status(
            mode="normal", outbound_halted=False, halt_reason=None, actor_id=None
        )


async def test_one_account_that_raises_does_not_stop_the_translation_backfill_for_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Z10-03: `resumed_walk` walks an item whose body raised first again next tick, so an
    uncaught error for one account stopped the backfill for every account, every tick."""
    poison, healthy = sorted([uuid.uuid4(), uuid.uuid4()])
    healthy_call = uuid.uuid4()
    monkeypatch.setattr(
        call_translation,
        "_LIVE_TENANTS_SQL",
        f"SELECT unnest(ARRAY['{poison}', '{healthy}']::uuid[])",
    )

    async def _settle(tenant_id: uuid.UUID) -> int:
        if tenant_id == poison:
            raise RuntimeError("this account's read fails")
        return 0

    async def _candidates(tenant_id: uuid.UUID, budget: Any) -> list[tuple[Any, uuid.UUID]]:
        return [(datetime.now(UTC), healthy_call)] if tenant_id == healthy else []

    queued: list[str] = []

    async def _enqueue(job: str, payload: dict[str, str], *, job_id: str) -> str:
        queued.append(payload["call_id"])
        return job_id

    monkeypatch.setattr(call_translation, "_settle_interrupted", _settle)
    monkeypatch.setattr(call_translation, "_untried_candidates", _candidates)
    monkeypatch.setattr(call_translation, "enqueue", _enqueue)
    await get_redis().delete(FLEET_CURSOR_KEY.format(walk="call_translations"))

    await call_translation.backfill_call_translations({})
    assert queued == [str(healthy_call)]


async def _template_seeds(account_id: uuid.UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'account_id' = :aid"
                    ),
                    {"job": signup.SEED_TEMPLATES_JOB, "aid": str(account_id)},
                )
            ).scalar_one()
        )


async def test_finishing_set_up_after_a_failed_template_seed_queues_the_seed_again(
    meta_app: None,  # noqa: F811
    fake_graph: dict[str, list[Any]],  # noqa: F811
) -> None:
    """Z10-02: the connect's `whatsapp-templates:<account>` key is spent forever, so the
    re-seed `finish_setup` promises for an account left unstamped was swallowed."""
    tenant_id, _ = await _whatsapp_client()
    outcome = await _connect(tenant_id, uuid.uuid4(), _waba())
    assert outcome.status == "connected"
    assert await _template_seeds(outcome.account_id) == 1

    # The seed failed (nothing stamped `templates_seeded_at`); the owner finishes set-up.
    async with tenant_session(tenant_id) as session:
        again = await accounts.finish_setup(
            session, tenant_id=tenant_id, account_id=outcome.account_id
        )
    assert again.status == "connected"
    assert await _template_seeds(outcome.account_id) == 2
