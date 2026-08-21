"""Object-store calls must not block the event loop they are awaited on.

boto3 is synchronous. Every function in `apps/workers/storage.py` that talks to the
object store is called from an async context — arq jobs share ONE event loop across every
job in the worker, and `read_delivery_body` is reached from a FastAPI request handler,
where the loop is shared across every tenant's request. A synchronous `put_object` there
does not slow one job down; it stops the whole process for the length of a network round
trip to the object store.

`archive_payload` (D-157) established the fix and named the rest of the module as a known
defect: "the rest of `workers/storage.py` is still synchronous boto3 called from async
workers". This is the sweep that closes it, and this file is the reason it stays closed.

TWO TESTS, BECAUSE THEY FAIL FOR DIFFERENT REASONS.

The BEHAVIOURAL one proves the property a user cares about — other work progresses while
a slow store is answering. It is the honest test, and on its own it is not enough: it can
only cover the functions somebody remembers to add to it.

The STRUCTURAL one is an AST scan proving no boto3 call in the module sits on a coroutine's
own stack, and it covers functions that do not exist yet. A new `head_object` helper added
next month is caught by the scan and invisible to the behavioural test, which is precisely
the failure mode that let this defect survive `archive_payload` fixing one function.

WHY NOT aioboto3 OR httpx-AGAINST-S3: a second object-store client library for one
property `asyncio.to_thread` already delivers, on a path whose call volume is a handful
per call record. `to_thread` is stdlib, it is already the pattern in this module, and one
way per problem beats a marginally tidier second way.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from apps.workers import storage
from tests.conftest import FakeS3
from uuid_utils.compat import uuid7

REPO_ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = REPO_ROOT / "apps" / "workers" / "storage.py"

#: How long the fake store sleeps. Long enough that a blocked loop is unmistakable and
#: short enough that eight of them do not slow the suite: the assertion is on the ratio
#: of ticks, not on wall clock, so this does not need to be large to be decisive.
_STALL_S = 0.20

#: How often the witness coroutine wakes. An order of magnitude under `_STALL_S`, so a
#: non-blocking implementation yields many ticks and a blocking one yields at most one.
_TICK_S = 0.01


class SlowS3(FakeS3):
    """A store that takes its time, SYNCHRONOUSLY — the way the real one does.

    `time.sleep`, deliberately, never `asyncio.sleep`. The bug under test is a synchronous
    call made without a thread, and only a synchronous sleep reproduces it: an
    `asyncio.sleep` here would yield to the loop and the test would pass against the very
    implementation it exists to reject.
    """

    def _check(self) -> None:
        super()._check()
        time.sleep(_STALL_S)


@pytest.fixture
def slow_s3(monkeypatch: pytest.MonkeyPatch) -> SlowS3:
    fake = SlowS3()
    monkeypatch.setattr(storage, "_client", lambda: fake)
    return fake


async def _ticks_during(work: Any) -> int:
    """Run `work` while a witness coroutine counts how often the loop let it run.

    The witness is the measurement. A call that hands its blocking work to a thread lets
    the loop keep scheduling, so the count is high; one that blocks holds the only thread
    the loop has and the count is 0 or 1 — the tick that happened to be pending.
    """
    counter = 0
    stop = False

    async def witness() -> None:
        nonlocal counter
        while not stop:
            await asyncio.sleep(_TICK_S)
            counter += 1

    watcher = asyncio.create_task(witness())
    await asyncio.sleep(0)  # let the witness reach its first await before work starts
    try:
        await work
    finally:
        stop = True
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
    return counter


#: Below this, the loop was blocked. A non-blocking call yields ~`_STALL_S / _TICK_S` = 20
#: ticks; a blocking one yields 0 or 1. Asserting 5 rather than 15 leaves room for a loaded
#: CI box to be slow without turning a real property into a flaky one — the gap between
#: the two behaviours is an order of magnitude, so the threshold does not need to be tight.
_MIN_TICKS = 5


@pytest.mark.asyncio
async def test_a_slow_store_does_not_freeze_the_loop_for_a_write(slow_s3: SlowS3) -> None:
    """`store_delivery_body` is an arq job's write; a stall here stalls sibling jobs."""
    ticks = await _ticks_during(
        storage.store_delivery_body(
            key="t/deliveries/x.json",
            delivery_id=uuid7(),
            endpoint_id=uuid7(),
            event="lead.created",
            subject_type="lead",
            subject_id=str(uuid7()),
            body='{"name":"Priya"}',
        )
    )
    assert ticks >= _MIN_TICKS, (
        f"the loop advanced only {ticks} times while the store was answering — "
        "store_delivery_body is blocking every other job in the worker"
    )


@pytest.mark.asyncio
async def test_a_slow_store_does_not_freeze_the_loop_for_a_read(slow_s3: SlowS3) -> None:
    """The worst of the set: this one is reached from an API request handler
    (`integrations/routes.py`), so blocking it freezes every tenant's request, not one."""
    slow_s3.objects["t/deliveries/x.json"] = b'{"body": "{}"}'
    ticks = await _ticks_during(storage.read_delivery_body("t/deliveries/x.json"))
    assert ticks >= _MIN_TICKS, (
        f"the loop advanced only {ticks} times while the store was answering — "
        "read_delivery_body is freezing the API event loop for every tenant"
    )


@pytest.mark.asyncio
async def test_a_slow_store_does_not_freeze_the_loop_for_a_listing(slow_s3: SlowS3) -> None:
    """The DPDP erasure lists a tenant's prefix before it deletes anything."""
    slow_s3.objects["t/deliveries/x.json"] = b"{}"
    ticks = await _ticks_during(storage.keys_under("t/"))
    assert ticks >= _MIN_TICKS, (
        f"the loop advanced only {ticks} times while the store was listing — "
        "keys_under is blocking the retention worker's loop"
    )


@pytest.mark.asyncio
async def test_a_slow_store_does_not_freeze_the_loop_for_a_delete(slow_s3: SlowS3) -> None:
    """The erasure's actual destruction, and the one that runs over the most keys."""
    slow_s3.objects["t/deliveries/x.json"] = b"{}"
    ticks = await _ticks_during(storage.delete_objects(["t/deliveries/x.json"]))
    assert ticks >= _MIN_TICKS, (
        f"the loop advanced only {ticks} times while the store was deleting — "
        "delete_objects is blocking the retention worker's loop"
    )


@pytest.mark.asyncio
async def test_a_recording_upload_does_not_freeze_the_loop(
    slow_s3: SlowS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`copy_recording`'s fetch was already async and its UPLOAD was not, so the cheap
    half yielded and the expensive half — a whole recording — did not."""

    async def _fake_fetch(source_url: str) -> bytes:
        return b"RIFF-audio"

    monkeypatch.setattr(storage, "_fetch_recording", _fake_fetch)
    ticks = await _ticks_during(
        storage.copy_recording(
            source_url="https://vendor.example/rec.wav",
            tenant_id=UUID(str(uuid7())),
            call_id=UUID(str(uuid7())),
        )
    )
    assert ticks >= _MIN_TICKS, (
        f"the loop advanced only {ticks} times while the recording uploaded — "
        "copy_recording's put_object is blocking the pipeline's loop"
    )


# --- the structural half ---------------------------------------------------------------


def _to_thread_bodies(tree: ast.Module) -> set[int]:
    """Line numbers of every function DEFINED to be run off the loop.

    A nested `def` whose name is handed to `asyncio.to_thread` anywhere in the module.
    Matching by name rather than by identity is enough here and deliberately loose: the
    module is one file, the nested helpers are uniquely named, and a stricter scope
    analysis would be a second implementation of Python's own for no extra catch.
    """
    threaded_names = {
        node.args[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_thread"
        and node.args
        and isinstance(node.args[0], ast.Name)
    }
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in threaded_names:
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


#: `presigned_url` is the ONE sync exception and it is not a network call: S3 presigning is
#: a local HMAC over the request, so there is nothing to wait for and a thread hop would be
#: pure overhead. Named here rather than left implicit, so the next reader learns why one
#: function is allowed to look like the bug.
_LOCAL_ONLY = {"presigned_url"}


def test_no_object_store_call_sits_on_a_coroutines_own_stack() -> None:
    """Every `_client()` use is inside a function handed to `asyncio.to_thread`.

    This is the clause that covers code nobody has written yet. The behavioural tests above
    each name one function; a `head_object` helper added next month would be blocking, and
    invisible to all of them. That is exactly how this defect outlived `archive_payload`
    fixing a single function while four others kept the old shape.
    """
    tree = ast.parse(STORAGE_PATH.read_text(encoding="utf-8"))
    safe = _to_thread_bodies(tree)

    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                # Innermost wins: nested helpers are visited after their parent only by
                # luck, so prefer the definition that starts latest and still contains it.
                if line not in enclosing or node.lineno > 0:
                    enclosing.setdefault(line, node.name)

    offenders = [
        f"line {node.lineno} (in {enclosing.get(node.lineno, '?')})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_client"
        and node.lineno not in safe
        and enclosing.get(node.lineno) not in _LOCAL_ONLY
    ]
    assert not offenders, (
        "these object-store calls run on the event loop's own thread: "
        + ", ".join(offenders)
        + ". boto3 blocks, and every caller in this module is reached from an arq job or "
        "an API request handler — wrap the call in a nested function and hand it to "
        "`asyncio.to_thread`, the way `archive_payload` does."
    )


def test_every_public_store_function_is_awaitable() -> None:
    """The signature half of the same guarantee.

    A function can be non-blocking and still be a trap: if it is `def` rather than
    `async def`, a caller writes `storage.thing(...)` and mypy is happy, so the day
    somebody adds a round trip to it there is no `await` to remind them. Making the whole
    network-touching surface `async` means the blocking version cannot be reintroduced
    without a signature change that every call site has to acknowledge.
    """
    tree = ast.parse(STORAGE_PATH.read_text(encoding="utf-8"))
    network = {
        "copy_recording",
        "archive_payload",
        "store_delivery_body",
        "read_delivery_body",
        "keys_under",
        "delete_objects",
    }
    sync = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in network
    }
    assert not sync, (
        f"{sorted(sync)} talk to the object store but are not `async def`, so a caller "
        "cannot tell from the call site that a network round trip happens here"
    )
