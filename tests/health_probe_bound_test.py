"""The health probe answers, whatever the dependency does (D-182, R-6).

THE DEFECT. `_check_db` ran `SELECT 1` through `untenanted_session()` with no
`asyncio.timeout`, no statement timeout and no connect timeout, and `pool_pre_ping`'s own
`SELECT 1` hangs on exactly the same socket as the query it is checking. Against a
BLACKHOLED Postgres — a dropped NAT mapping, a firewall change, a host that stops
answering without sending RST, which is the ordinary shape of a network fault rather than
a process fault — the probe blocked for ever:

  * `/healthz/ready` is the go-live gate (OPERATIONS §8) and the line an operator curls
    during an incident. It hung instead of returning `503 db_down`, which is the one word
    it exists to produce.
  * `/healthz` is polled by `scripts/vps-deploy.sh` with `curl --max-time 5`, so the
    deploy was protected by the CALLER's bound rather than by any of its own — the right
    outcome by accident.
  * every hung probe held a pooled connection for the life of the request, so repeated
    probing during the outage exhausted the pool and made the rest of the service answer
    503 for the wrong reason.

An orchestrator cannot tell "sick" from "slow", and it can act on the first.

HOW THE HANG IS SIMULATED. Not with a packet-dropping Postgres — with a probe that sleeps
past its own budget, which is the same thing from the endpoint's point of view and is the
only part of it this module can decide. What is asserted is the endpoint's contract: it
answers, within a bound, with the verdict rather than with a stall.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from apps.api.core import health as health_module
from apps.api.main import app as api_app
from httpx import ASGITransport, AsyncClient, Response

#: Longer than `_PROBE_BUDGET_S`, and longer than any patience a caller has. Stands in for
#: "this socket will never answer".
FOREVER_S = 30.0


async def _hang() -> None:
    await asyncio.sleep(FOREVER_S)


async def _get(path: str) -> Response:
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get(path)


@pytest.fixture
async def blackholed_database(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Postgres accepts nothing and refuses nothing — the case with no bound of its own."""
    from apps.api.db import session as session_module

    class _NeverAnswers:
        async def __aenter__(self) -> None:
            await _hang()

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(health_module, "untenanted_session", lambda: _NeverAnswers())
    assert session_module.untenanted_session is not None  # the real one is untouched
    yield


async def _no_queue() -> tuple[int, float | None]:
    return 0, None


@pytest.mark.parametrize("path", ["/healthz", "/healthz/ready"])
async def test_a_blackholed_database_is_answered_not_waited_for(
    path: str, blackholed_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DEFECT, as the one fact that decides it: the probe returns."""
    monkeypatch.setattr(health_module, "runtime_config_missing_keys", lambda _settings: [])
    monkeypatch.setattr(health_module, "_queue_stats", _no_queue)

    started = time.monotonic()
    response = await asyncio.wait_for(_get(path), timeout=FOREVER_S / 2)
    elapsed = time.monotonic() - started

    assert response.status_code == 503, "a database that never answers is not a healthy one"
    # Both probes run in sequence, so the ceiling is two budgets plus the app's own
    # overhead — well inside `vps-deploy.sh`'s `curl --max-time 5`, which is the bound
    # this number was chosen against.
    assert elapsed < 4.5, (
        f"the probe took {elapsed:.1f}s: an orchestrator cannot tell a sick service from a "
        "slow one, and it can only act on the first"
    )


async def test_a_slow_queue_read_is_reported_as_redis_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_queue_stats` is the third unbounded wait on this surface. A Redis that accepts
    the connection and then stops talking must read as `redis_down`, not as a readiness
    probe that never resolves."""
    monkeypatch.setattr(health_module, "runtime_config_missing_keys", lambda _settings: [])

    async def hanging_queue() -> tuple[int, float | None]:
        await _hang()
        return 0, None

    monkeypatch.setattr(health_module, "_queue_stats", hanging_queue)

    response = await asyncio.wait_for(_get("/healthz/ready"), timeout=FOREVER_S / 2)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


async def test_the_probe_budget_stays_under_the_pool_wait() -> None:
    """The relationship, not the number. A probe allowed to outlast
    `_POOL_TIMEOUT_S` would sit in the pool's queue and report a database nobody can
    reach as healthy — and `/healthz` would stop fitting inside the deploy script's
    `curl --max-time 5`, which is what makes a bad deploy abort."""
    from apps.api.db.session import _POOL_TIMEOUT_S

    assert health_module._PROBE_BUDGET_S < _POOL_TIMEOUT_S
    assert 2 * health_module._PROBE_BUDGET_S < 5.0


async def test_a_healthy_deployment_still_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive half: a bound that fires when it should not would report a healthy
    fleet as down, which is a worse outage than the one it prevents."""
    monkeypatch.setattr(health_module, "runtime_config_missing_keys", lambda _settings: [])
    monkeypatch.setattr(health_module, "_queue_stats", _no_queue)

    response = await _get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
