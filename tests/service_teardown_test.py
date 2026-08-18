"""Every client a process opens is closed when it drains — not just Redis.

THE STATE THIS EXISTS TO CATCH SHIPPED. `close_queue` (the ARQ enqueue pool, built the
first time a request or a job enqueues) and `close_admission` (the shared alert
suppression client) were both written, both exported, and called from nowhere at all —
`close_admission`'s own docstring said it was "called from the same shutdown path as
`close_redis`", which nothing had ever made true. The API lifespan closed Redis and
flushed spans; the worker's `on_shutdown` flushed spans and nothing else, under a
`job_completion_wait` comment that budgets fifteen seconds for "the pool teardown".

A leaked pool does not fail anything visibly: the process exits and the OS reaps the
sockets. It shows up as connection churn against Redis under `--reload`, in tests that
restart the app, and — the one that costs money — as a worker redeploy that leaves its
connections held until the server's own timeout.

The assertions are on the CALLS, not on the source: a teardown that imports a closer and
does not reach it reads identically to one that does.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.core import alert_admission, bootstrap
from apps.workers import settings as worker_settings


class _Spy:
    """Records that it ran, and (for the failure test) can refuse to."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls = 0
        self._raises = raises

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        if self._raises:
            raise RuntimeError("socket already gone")


class _AsyncSpy(_Spy):
    async def __call__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        self.calls += 1
        if self._raises:
            raise RuntimeError("socket already gone")


def _install(monkeypatch: pytest.MonkeyPatch, module: Any, **spies: _Spy) -> None:
    for name, spy in spies.items():
        monkeypatch.setattr(module, name, spy)


# --- the API lifespan ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_api_drain_closes_redis_the_queue_pool_and_the_alert_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis, queue, admission, tracing = _AsyncSpy(), _AsyncSpy(), _Spy(), _Spy()
    _install(monkeypatch, bootstrap, close_redis=redis, close_queue=queue, shutdown_tracing=tracing)
    # PATCHED AT ITS SOURCE, unlike the other three, because `core.bootstrap` imports it
    # inside the lifespan rather than at module scope: `core.bootstrap` is on
    # voice-runtime's pinned import surface (hard rule 3) and a module-level import grows
    # that surface by `alert_admission`. See the comment at the call site.
    monkeypatch.setattr(alert_admission, "close_admission", admission)
    # Signal handlers belong to the real server, not to a test process running under
    # pytest's own — installing them here would outlive this test.
    monkeypatch.setattr(bootstrap, "_install_signal_handlers", lambda: None)

    app = bootstrap.create_app(service="api", title="teardown-test", minimal=True)
    async with app.router.lifespan_context(app):
        pass

    assert (redis.calls, queue.calls, admission.calls) == (1, 1, 1)
    assert tracing.calls == 1


@pytest.mark.asyncio
async def test_one_closer_failing_does_not_cost_the_others_or_the_span_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drain is exactly when a socket is already half gone, and it is also exactly when
    the spans somebody is reading matter. An unguarded closer would take the flush with
    it."""
    redis, queue, admission, tracing = (
        _AsyncSpy(raises=True),
        _AsyncSpy(raises=True),
        _Spy(raises=True),
        _Spy(),
    )
    _install(monkeypatch, bootstrap, close_redis=redis, close_queue=queue, shutdown_tracing=tracing)
    monkeypatch.setattr(alert_admission, "close_admission", admission)
    monkeypatch.setattr(bootstrap, "_install_signal_handlers", lambda: None)

    app = bootstrap.create_app(service="api", title="teardown-test", minimal=True)
    async with app.router.lifespan_context(app):
        pass

    assert (redis.calls, queue.calls, admission.calls) == (1, 1, 1)
    assert tracing.calls == 1


# --- the worker's on_shutdown -------------------------------------------------


@pytest.mark.asyncio
async def test_the_worker_drain_closes_the_three_clients_a_job_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq closes its own worker pool. These three are ours: a job that enqueues another
    job builds `core/queue._pool`, everything that reads the big red switch or a rate
    limit builds `core/redis._client`, and the first alert builds the admission client."""
    redis, queue, admission, tracing = _AsyncSpy(), _AsyncSpy(), _Spy(), _Spy()
    _install(
        monkeypatch,
        worker_settings,
        close_redis=redis,
        close_queue=queue,
        close_admission=admission,
        shutdown_tracing=tracing,
    )

    await worker_settings.shutdown({})

    assert (redis.calls, queue.calls, admission.calls) == (1, 1, 1)
    assert tracing.calls == 1


@pytest.mark.asyncio
async def test_the_worker_drain_survives_a_closer_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis, queue, admission, tracing = (
        _AsyncSpy(raises=True),
        _AsyncSpy(raises=True),
        _Spy(raises=True),
        _Spy(),
    )
    _install(
        monkeypatch,
        worker_settings,
        close_redis=redis,
        close_queue=queue,
        close_admission=admission,
        shutdown_tracing=tracing,
    )

    await worker_settings.shutdown({})

    assert (redis.calls, queue.calls, admission.calls) == (1, 1, 1)
    assert tracing.calls == 1
