"""A service's startup hook has a SECOND half, and it runs. Hard rule 3, and the drain.

`create_app(on_startup=...)` takes an async generator per service. It used to be driven as

    async for _ in on_startup():
        break

— run to the first `yield` and abandoned there. Everything a service wrote AFTER that
`yield` was dead code that looked live: the generator was left to the garbage collector,
which closed it at a moment of its own choosing, in no relation to the shutdown. So the
protocol could not express teardown at all, and both services that used it leaked exactly
what a protocol without teardown leaks — `apps/api/main.py` started three background polls
(config, pricing, FX) and `apps/voice-runtime/main.py` one, and NOTHING stopped any of
them. The lifespan's own `finally` closed the Redis client, the ARQ pool and the alert
admission client and knew nothing about the polls.

What that costs is not theoretical and is worst where it is least welcome: on every
ordinary deploy the polls keep reading through a session pool being torn down under them,
which logs failures indistinguishable from a real outage — and under `--reload` and inside
a test process each restart leaves another poller running against the same stores. That is
the identical leak `core/bootstrap.py`'s own teardown comment records as already fixed for
the pools and the clients, reintroduced one layer up.

`tests/service_teardown_test.py` is the sibling and the split is deliberate: that file
asserts the SHARED drain closes every client a process opens (Redis, the ARQ pool, the
alert admission client, the span flush). This one is about the per-service half — that a
service can have a teardown at all, that it runs before the shared one, and that the two
ASGI services use it to cancel the polls they start.

The worker never had the bug and says why (`apps/workers/settings.shutdown`): "a poll still
running while the pool it borrows from is torn down logs a failure that reads like a real
one". This file pins the same property for the two ASGI services, plus the protocol change
that makes it expressible — because fixing two call sites without fixing the protocol would
leave the next service to write a `finally` that never runs.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import AsyncIterator
from typing import Any

import main as voice_runtime_main
import pytest
from apps.api import main as api_main
from apps.api.core import bootstrap, platform_config
from apps.api.ops import fx_rates, pricing_snapshot

# --- 1. the protocol: a hook may express teardown, and it is honoured ---------


async def test_the_startup_hook_resumes_after_its_yield_at_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The structural half. Without it, every assertion below is about dead code.

    Driven through `create_app` rather than against a hand-rolled lifespan, because the
    thing under test is what `create_app` DOES with the hook — that is where the
    `async for ... break` lived.
    """
    events: list[str] = []

    async def hook() -> AsyncIterator[None]:
        events.append("startup")
        try:
            yield
        finally:
            events.append("teardown")

    # Signal handlers belong to the real server, not to a test process running under
    # pytest's own — `tests/service_teardown_test.py` patches them out for the same reason.
    monkeypatch.setattr(bootstrap, "_install_signal_handlers", lambda: None)
    app = bootstrap.create_app(
        service="lifespan-protocol-test",
        title="lifespan protocol",
        minimal=True,
        on_startup=hook,
    )
    async with app.router.lifespan_context(app):
        assert events == ["startup"], "the hook did not run to its first yield"
    assert events == ["startup", "teardown"], (
        "the startup hook was consumed to its first yield and abandoned: a service cannot "
        "stop what it started, and everything after `yield` is dead code that reads live"
    )


async def test_the_service_teardown_runs_before_the_shared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order, and it is the whole reason the shared drain is registered first.

    A service's teardown cancels polls that borrow the Redis client, the ARQ pool and the
    database session pool. Closing those FIRST — which a naive `finally` around the shared
    block would do — is the failure `apps/workers/settings.shutdown` describes: the poll is
    still in flight, its store disappears under it, and the error it logs on the way out
    reads like a live incident during a routine deploy.
    """
    order: list[str] = []

    async def _noop_close_redis() -> None:
        order.append("shared")

    monkeypatch.setattr(bootstrap, "close_redis", _noop_close_redis)

    async def hook() -> AsyncIterator[None]:
        yield
        order.append("service")

    # Signal handlers belong to the real server, not to a test process running under
    # pytest's own — `tests/service_teardown_test.py` patches them out for the same reason.
    monkeypatch.setattr(bootstrap, "_install_signal_handlers", lambda: None)
    app = bootstrap.create_app(
        service="lifespan-order-test",
        title="lifespan order",
        minimal=True,
        on_startup=hook,
    )
    async with app.router.lifespan_context(app):
        pass

    assert order == ["service", "shared"], (
        "the shared drain (Redis, the ARQ pool, the alert client, the tracing flush) ran "
        "before the service's own teardown; a poll cancelled after its pool is gone is the "
        "error that reads like an outage"
    )


async def test_a_hook_that_raises_at_teardown_still_gets_the_shared_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One service's bad teardown may not cost the process its connection drain."""
    drained: list[str] = []

    async def _noop_close_redis() -> None:
        drained.append("shared")

    monkeypatch.setattr(bootstrap, "close_redis", _noop_close_redis)

    async def hook() -> AsyncIterator[None]:
        yield
        raise RuntimeError("this service's teardown is broken")

    # Signal handlers belong to the real server, not to a test process running under
    # pytest's own — `tests/service_teardown_test.py` patches them out for the same reason.
    monkeypatch.setattr(bootstrap, "_install_signal_handlers", lambda: None)
    app = bootstrap.create_app(
        service="lifespan-raise-test",
        title="lifespan raise",
        minimal=True,
        on_startup=hook,
    )
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            pass

    assert drained == ["shared"], (
        "a raising service teardown skipped the shared drain: the exit stack must unwind "
        "every remaining callback whatever one of them does"
    )


# --- 2. the two services actually stop what they start -----------------------


def _calls_in(function: Any) -> set[str]:
    """Names called at any depth inside `function`'s own body.

    AST rather than a substring, for `tests/worker_pricing_readers_test.py`'s reason: a
    call cannot be satisfied by the word appearing in a comment or a docstring that merely
    says the service ought to make it — which is exactly the state `apps/api/main.py` was
    in, with three `start_*` calls and a docstring about adoption.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize(
    ("service", "startup"),
    [("api", api_main._startup), ("voice-runtime", voice_runtime_main._startup)],
)
def test_every_refresher_a_service_starts_is_also_stopped(service: str, startup: Any) -> None:
    """DERIVED from the starts rather than listed, so a fourth poll cannot be added quietly.

    `tests/worker_pricing_readers_test.py` pins this for the worker and had no counterpart
    for either ASGI service — which is how three unstopped polls in `api` and one in
    voice-runtime survived. The pairing rule is the same one that file states: any
    `start_*_refresher` a process calls, that process cancels.
    """
    calls = _calls_in(startup)
    starts = {name for name in calls if name.startswith("start_") and name.endswith("_refresher")}
    assert starts, f"{service} starts no refresher; this test is now aimed wrong"
    for start in sorted(starts):
        stop = start.replace("start_", "stop_", 1)
        assert stop in calls, (
            f"{service}'s startup hook calls {start} and never {stop}: the poll outlives "
            "the drain meant to end it, keeps reading through a session pool that is going "
            "away, and logs a failure on every ordinary deploy that reads like a real "
            "outage — while each `--reload` restart leaks another one"
        )


@pytest.mark.parametrize(
    ("module", "name", "expected"),
    [
        (api_main, "stop_config_refresher", platform_config.stop_config_refresher),
        (api_main, "stop_pricing_refresher", pricing_snapshot.stop_pricing_refresher),
        (api_main, "stop_fx_refresher", fx_rates.stop_fx_refresher),
        (voice_runtime_main, "stop_config_refresher", platform_config.stop_config_refresher),
    ],
)
def test_the_name_each_service_calls_is_the_real_one(module: Any, name: str, expected: Any) -> None:
    """Half the wiring is that the call exists; the other half is what it resolves to."""
    assert getattr(module, name) is expected


async def test_the_voice_runtime_lifespan_leaves_no_polling_task_behind() -> None:
    """The end-to-end version, on the service where a leaked poll costs the most.

    The AST checks above prove the line is there. This proves the line does what it says
    through the real lifespan: after the drain there is no task, so nothing is left holding
    a session pool that has just been closed.
    """
    await platform_config.stop_config_refresher()
    app = voice_runtime_main.app
    async with app.router.lifespan_context(app):
        task = platform_config._refresher
        assert task is not None and not task.done(), (
            "voice-runtime's lifespan started no config poll — its adoption is the source "
            "of the source-IP allowlist an operator changes without a deploy"
        )
    assert platform_config._refresher is None
    assert task.cancelled() or task.done()
