"""A client's endpoint that HANGS — which is not a client's endpoint that is DOWN.

**Why this file exists.** `integrations/service.deliver` sets `DELIVERY_TIMEOUT_S = 10.0`
and the constant's comment says "slow is normal, hanging is not". Nothing measured that.
`httpx.Timeout(10.0)` is FOUR ten-second budgets — connect, write, read and pool — and
the READ one is the maximum wait for *a chunk*, not for the response: it restarts on
every byte that arrives. Measured against a real loopback socket before this test was
written: a receiver that answered `200 OK`, declared a hundred-megabyte body and then
wrote one byte every three seconds held `deliver` for over 45 seconds under a budget the
constant calls ten. Nothing in this repo would ever have stopped it except arq's
`job_timeout` (300s, `workers/dispatcher.py`) — which cancels the JOB, so
`record_delivery` never runs and the attempt is MISSING from the client's own delivery
screen rather than failed on it. Ten of those is every delivery slot on the worker.

**A REFUSED connection is not this test, and that is why all three are in one file.** A
refused connect answers in microseconds; it satisfies any "what if the endpoint is down"
test while the two cases below — a receiver that dribbles, and a receiver that goes
silent — walk straight past it. `outbound_sync_test.py` covers the refused case; this
file covers what that case cannot see.

Real sockets, not `httpx.MockTransport`: a mock transport cannot stall between chunks, so
a test written against one is the "outage test that missed the 60-second hold" again.
Loopback is reachable here because `APP_ENV=local` relaxes the egress guard for `127.
0.0.1` only (`egress_guard.loopback_is_allowed`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import pytest
from apps.api.integrations import service

pytestmark = pytest.mark.asyncio

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Coroutine[Any, Any, None]]

#: How much longer than the transport's own budget a delivery may take before this suite
#: calls it a hang. Generous — the assertion is "bounded", not "fast", and a CI box under
#: contention must not turn a correctness test into a timing one (D-29).
SLACK_S = 10.0


@asynccontextmanager
async def _receiver(handler: Handler) -> AsyncIterator[str]:
    """A hostile webhook receiver on loopback. Yields the URL to point an endpoint at.

    Connection tasks are tracked and CANCELLED on the way out rather than waited for.
    `Server.wait_closed()` on 3.12 waits for every handler to return, and a handler that
    is deliberately wedged — which is the entire point of the receivers below — never
    does. Left alone that turns a passing assertion into a hung suite, which is a worse
    outcome than the defect these tests exist to catch.
    """
    live: set[asyncio.Task[None]] = set()

    async def tracked(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            live.add(task)
        try:
            await handler(reader, writer)
        finally:
            writer.close()
            if task is not None:
                live.discard(task)

    server = await asyncio.start_server(tracked, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    try:
        yield f"http://127.0.0.1:{port}/hook"
    finally:
        for task in list(live):
            task.cancel()
        server.close()
        await server.wait_closed()


async def _deliver(url: str) -> tuple[service.DeliveryResult, float]:
    started = time.monotonic()
    result = await asyncio.wait_for(
        service.deliver(
            url=url,
            secret="shh",
            event="lead.created",
            envelope=service.build_envelope(
                event="lead.created",
                tenant_id=service.uuid7(),
                delivery_id=service.uuid7(),
                data={"lead_id": "1"},
            ),
        ),
        # Twice the budget these tests assert, so a regression fails as a FAILED
        # assertion carrying a measured number rather than as a hung suite.
        timeout=(service.DELIVERY_TIMEOUT_S + SLACK_S) * 2,
    )
    return result, time.monotonic() - started


async def test_a_body_we_never_read_cannot_hold_the_delivery_worker() -> None:
    """THE MEASURED DEFECT. A byte every three seconds is never a read timeout.

    `deliver` reads a status code off the response and nothing else, so this asserts
    the two halves of that at once: the drip cannot delay us (the old shape returned
    only when the receiver stopped dripping), and a receiver's declared hundred
    megabytes cannot become a hundred megabytes of worker heap either. The 200 stands:
    the status line is the receiver's own verdict on the request, and a body we do not
    parse has no vote in it.
    """

    async def trickle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100000000\r\n\r\n")
            await writer.drain()
            while True:
                writer.write(b"x")
                await writer.drain()
                # Comfortably under DELIVERY_TIMEOUT_S, so the per-chunk read timeout
                # this test exists to disbelieve never fires.
                await asyncio.sleep(service.DELIVERY_TIMEOUT_S / 3)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass

    async with _receiver(trickle) as url:
        result, elapsed = await _deliver(url)

    assert elapsed < service.DELIVERY_TIMEOUT_S, (
        f"a trickling receiver held the delivery worker for {elapsed:.1f}s while "
        f"{service.DELIVERY_TIMEOUT_S}s was the whole budget"
    )
    assert result.delivered is True
    assert result.status_code == 200


async def test_a_receiver_that_answers_nothing_at_all_is_cut_off_at_the_budget() -> None:
    """The other hang: the connection is accepted, the request is read, silence follows.

    Bounded before this change too — a response line that never arrives IS a read
    timeout — and pinned here because it is the case a reader will assume the trickling
    one already covers. It does not: the two differ by exactly one byte every few
    seconds, and that byte is the whole defect.

    A failure with no status code, which `outbound_webhooks._is_transient` reads as a
    transport blip and gives the retry ladder — the right verdict for a receiver that is
    wedged now and may be fine in thirty seconds.
    """

    async def silence(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            # Returns b"" the moment the delivery hangs up, which is the event under
            # test. A sleep here would outlive the assertion.
            await reader.read()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass

    async with _receiver(silence) as url:
        result, elapsed = await _deliver(url)

    assert elapsed < service.DELIVERY_TIMEOUT_S + SLACK_S, (
        f"a silent receiver held the delivery worker for {elapsed:.1f}s under a "
        f"{service.DELIVERY_TIMEOUT_S}s budget"
    )
    assert result.delivered is False
    assert result.status_code is None
    # The exception TYPE, never its string (hard rule 6) — and `sent_body` is still
    # reported, so the retention path files what we put on the wire either way.
    assert result.error is not None
    assert result.sent_body is not None


async def test_a_refused_connection_still_fails_fast_and_says_so() -> None:
    """The case that already passed, kept beside the two that did not.

    A refused connect returns in microseconds and looks identical to a hang from the
    outside — same `delivered=False`, same absent status code. Keeping all three in one
    file is what stops the next reader concluding that one of them covers the others.
    """
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    server.close()
    await server.wait_closed()

    result, elapsed = await _deliver(f"http://127.0.0.1:{port}/hook")

    assert result.delivered is False
    assert result.status_code is None
    assert elapsed < service.DELIVERY_TIMEOUT_S
