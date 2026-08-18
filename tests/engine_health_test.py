"""`engine_error_spike` — OPERATIONS §4's "engine 5xx spike", which nothing raised.

WHAT THESE TESTS WOULD HAVE CAUGHT. Before `apps/api/engine/health.py` existed, a voice
platform failing every request produced `engine_error` at WARNING and no page at all. The
first test here drives the real condition through the real adapter and asserts the alarm;
without the wiring it fails.

THE SECOND TEST IS THE ONE THAT MATTERS MORE. A threshold that fires below the retry
ladder is an alarm that goes off whenever one call has a bad afternoon, and an alarm that
fires on healthy traffic is one nobody reads when a real one arrives. `SPIKE_THRESHOLD` is
`3 * WORKER_MAX_TRIES + 1` precisely so a single operation exhausting its retries cannot
reach it, and `test_one_operation_exhausting_its_retries_is_not_a_spike` is what pins that.

THE THIRD is the reading of "5xx spike" this module deliberately does NOT take. A platform
that is entirely down refuses connections rather than answering 502, so counting only 5xx
would leave the alarm silent through a total outage and loud only through a partial one.

They drive the DATABASE, not a stub: the whole reason the counter is a table is that a
process-local one would mean something different per process (D-160's defect), and a test
against an in-memory fake would have proved nothing about that.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.engine import health
from apps.api.engine.bolna import BolnaEngine
from sqlalchemy import text


class _Alerts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, stage: str, code: str, *, detail: str = "", **kw: Any) -> None:
        self.calls.append((stage, code, detail))

    def codes(self) -> list[str]:
        return [code for _, code, _ in self.calls]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> _Alerts:
    captured = _Alerts()
    monkeypatch.setattr(health, "alert", captured)
    return captured


async def _clear(engine_name: str) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_engine_health WHERE engine = :e"), {"e": engine_name}
        )


async def _counts(engine_name: str) -> tuple[int, int]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT coalesce(sum(server_errors), 0), coalesce(sum(unreachable), 0) "
                    "FROM platform_engine_health WHERE engine = :e"
                ),
                {"e": engine_name},
            )
        ).one()
    return int(row[0]), int(row[1])


def _bolna(handler: Any) -> BolnaEngine:
    """A real adapter over a mock transport, so `_request`'s own branches are exercised —
    the throttle ladder, the 4xx/5xx split and the `absent_is_success` case all live there
    and a stubbed adapter would test none of them."""
    return BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("83"),
        client=httpx.AsyncClient(
            base_url="https://api.example.invalid",
            transport=httpx.MockTransport(handler),
        ),
    )


async def test_a_run_of_5xx_raises_the_spike_alarm(alerts: _Alerts) -> None:
    name = "spike-5xx"
    await _clear(name)
    for _ in range(health.SPIKE_THRESHOLD):
        await health.record_engine_failure(name, kind="server_error")
    assert "engine_error_spike" in alerts.codes()
    stage, _, detail = next(call for call in alerts.calls if call[1] == "engine_error_spike")
    assert stage == "CORE_LOGIC"
    assert f"{health.SPIKE_THRESHOLD} failed engine requests" in detail
    await _clear(name)


async def test_one_operation_exhausting_its_retries_is_not_a_spike(alerts: _Alerts) -> None:
    """The threshold's whole argument, as an assertion.

    An arq job retries `WORKER_MAX_TRIES` times, so one genuinely unlucky dial produces
    that many failures on its own. If this ever goes red, the threshold has been lowered
    to the point where a single call pages a human.
    """
    name = "spike-retry-ladder"
    await _clear(name)
    for _ in range(WORKER_MAX_TRIES):
        await health.record_engine_failure(name, kind="server_error")
    assert alerts.codes() == []
    await _clear(name)


async def test_an_engine_that_answers_nothing_still_trips_the_alarm(alerts: _Alerts) -> None:
    """The reading of "5xx spike" that would have been silent through a TOTAL outage."""
    name = "spike-unreachable"
    await _clear(name)
    for _ in range(health.SPIKE_THRESHOLD):
        await health.record_engine_failure(name, kind="unreachable")
    assert "engine_error_spike" in alerts.codes()
    detail = next(call for call in alerts.calls if call[1] == "engine_error_spike")[2]
    assert "got no answer" in detail
    await _clear(name)


async def test_the_adapter_counts_a_5xx_and_not_a_4xx(alerts: _Alerts) -> None:
    """The wiring, through the real `_request`. A 4xx is OUR request being wrong and would
    drown the signal; only the 5xx may be counted."""
    await _clear("bolna")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no"})

    engine = _bolna(handler)
    with pytest.raises(ProblemError):
        await engine.get_agent("agent-1")
    assert await _counts("bolna") == (0, 0)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    engine = _bolna(failing)
    with pytest.raises(ProblemError):
        await engine.get_agent("agent-1")
    assert await _counts("bolna") == (1, 0)
    await _clear("bolna")


async def test_a_transport_failure_is_counted_as_unreachable() -> None:
    await _clear("bolna")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    engine = _bolna(refused)
    with pytest.raises(ProblemError):
        await engine.get_agent("agent-1")
    assert await _counts("bolna") == (0, 1)
    await _clear("bolna")


async def test_a_broken_database_costs_the_signal_and_never_the_caller(
    alerts: _Alerts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`record_engine_failure` is called from the failure branch of an adapter that is
    already reporting a problem. If it could raise, a database hiccup would replace the
    vendor's error with ours — on the path whose whole job is saying what the vendor did.
    """

    def explode() -> Any:
        raise RuntimeError("no database")

    monkeypatch.setattr("apps.api.db.session.untenanted_session", explode)
    await health.record_engine_failure("spike-nodb", kind="server_error")
    assert alerts.codes() == []
