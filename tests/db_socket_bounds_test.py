"""The database socket has bounds of its own, because the task deadlines do not reach it.

THE PREMISE, VERIFIED RATHER THAN QUOTED. `asyncio.timeout` cancels a task ONCE. Awaits
that run in a `finally` or an `__aexit__` after that cancellation is delivered are not
bounded by it — `test_a_deadline_does_not_bound_the_unwind_it_cancels` below is the
executable proof, and it is a test rather than a comment because the whole argument for
`db.session._CONNECT_ARGS` rests on it: if a future Python bounded the unwind, the right
response would be to revisit those values, not to discover the change by accident.

WHAT THAT COSTS HERE. `apps/voice-runtime/webhook_routes` runs `_claim_and_enqueue` under
`asyncio.timeout(_DURABLE_DEADLINE_S)`; its body is `async with untenanted_session()`,
whose exit issues a ROLLBACK over the connection. Against a SLOW database that is already
bounded and tested (`tests/voice_runtime_ack_budget_test.py` — psycopg's cancel travels a
live socket). Against a socket ACCEPTED AND THEN BLACKHOLED — the shape `core/health.py`
names — there was nothing at all: the unwind waited on the kernel, holding a pooled
connection and a task on the event loop carrying live calls, for as long as TCP was
willing to retransmit.

`connect_timeout`, `tcp_user_timeout` and the keepalive triple are libpq connection
parameters, so they are asserted where they are actually applied — read back out of the
live `PGconn` — and not by comparing our dict to itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator

import pytest
from apps.api.db.session import _CONNECT_ARGS, get_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


async def test_the_libpq_connection_really_carries_every_bound_we_declare() -> None:
    """Read the parameters back off the live connection the app's own engine hands out.

    `create_async_engine(connect_args=...)` forwards to `psycopg.AsyncConnection.connect`
    as keyword conninfo parameters, and an unknown one RAISES there — so this also proves
    every name in `_CONNECT_ARGS` is a real libpq parameter on the installed client rather
    than a plausible one. That is the half a dict comparison cannot see.
    """
    engine = get_engine()
    async with engine.connect() as connection:
        raw = (await connection.get_raw_connection()).driver_connection
        applied = raw.info.get_parameters()
    for name, value in _CONNECT_ARGS.items():
        assert applied.get(name) == str(value), (
            f"libpq reports {name}={applied.get(name)!r}, not {value!r}. The bound is "
            "declared and not applied, which is the shape of a fix that is not one."
        )


async def test_a_deadline_does_not_bound_the_unwind_it_cancels() -> None:
    """The premise `_CONNECT_ARGS` exists for. If this ever fails, re-read that constant.

    An `asyncio.timeout` cancels the task once; the context manager's exit then awaits
    freely. Written with `asyncio.sleep` rather than a database so it measures the
    LANGUAGE and not psycopg — which is the thing being relied on.
    """
    unwind = 0.4
    budget = 0.05

    @contextlib.asynccontextmanager
    async def rolls_back_on_exit() -> AsyncIterator[None]:
        try:
            yield
        finally:
            await asyncio.sleep(unwind)  # stands in for a ROLLBACK on a dead socket

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(budget), rolls_back_on_exit():
            await asyncio.sleep(10)
    elapsed = time.monotonic() - started
    assert elapsed >= unwind, (
        f"the whole block finished in {elapsed:.3f}s, inside its {unwind}s unwind — "
        "asyncio now bounds awaits after cancellation, so `db.session._CONNECT_ARGS`' "
        "argument has changed and its values should be re-derived"
    )


@pytest.fixture
def blackhole() -> Iterator[int]:
    """A port that ACCEPTS and never answers — a firewall or a dropped NAT mapping, which
    is not the same failure as a refused connection and is the one with no bound above it.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    held: list[socket.socket] = []

    def accept_forever() -> None:
        while True:
            try:
                accepted, _ = listener.accept()
            except OSError:
                return
            held.append(accepted)

    threading.Thread(target=accept_forever, daemon=True).start()
    try:
        yield int(listener.getsockname()[1])
    finally:
        listener.close()
        for held_socket in held:
            held_socket.close()


async def test_a_blackholed_socket_fails_inside_the_pool_wait_instead_of_hanging(
    blackhole: int,
) -> None:
    """The end-to-end proof, through the same construction `get_engine` uses.

    The outer `asyncio.timeout` is the INSTRUMENT, not the bound: it is what makes a
    regression fail in seconds instead of hanging the suite, and reaching it means the
    socket bounds did nothing. `_POOL_TIMEOUT_S` (5s) is the ceiling that matters — a
    connect that outlived the wait a caller already accepts for a free pooled slot would
    make "the pool is full" and "the database is gone" indistinguishable at the one moment
    they need different answers.
    """
    engine = create_async_engine(
        f"postgresql+psycopg://u:p@127.0.0.1:{blackhole}/db",
        connect_args=dict(_CONNECT_ARGS),
    )
    started = time.monotonic()
    try:
        with pytest.raises(Exception) as caught:
            async with asyncio.timeout(20):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    elapsed = time.monotonic() - started
    assert not isinstance(caught.value, TimeoutError), (
        f"the connect was still running after {elapsed:.1f}s and only the test's own "
        "instrument stopped it — nothing in _CONNECT_ARGS bounded the socket"
    )
    assert elapsed < 5.0, (
        f"a blackholed connect took {elapsed:.2f}s, at or past `_POOL_TIMEOUT_S`. It has "
        "to fail faster than the wait for a pooled connection, or an unreachable database "
        "and a saturated pool look the same to every caller."
    )
