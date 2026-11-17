"""Every object-store call is bounded as a whole, as the recording upload is
(`RECORDING_UPLOAD_DEADLINE_S`): botocore's per-operation timeouts, retried, outlast the
worker's `job_timeout` on their own, and arq never retries a job it timed out.

A store that never answers is a client whose method sleeps past a shrunken deadline. Each
caller keeps its own failure contract: the best-effort payload archive returns None, the
rest raise `StorageUnavailableError` into the retry ladder.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from apps.workers import storage
from apps.workers.storage import StorageUnavailableError

DEADLINE_S = 0.2
STALL_S = 1.0


class _StalledClient:
    """Every S3 method the module calls, each one hanging past the deadline."""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def stall(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            time.sleep(STALL_S)
            return {}

        return stall


@pytest.fixture
def stalled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _StalledClient()
    monkeypatch.setattr(storage, "STORE_CALL_DEADLINE_S", DEADLINE_S)
    monkeypatch.setattr(storage, "STORE_BULK_DEADLINE_S", DEADLINE_S)
    monkeypatch.setattr(storage, "_client", lambda: client)
    monkeypatch.setattr(storage, "_upload_client", lambda: (client, "uploads"))


async def _timed(call: Callable[[], Awaitable[Any]]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = await call()
    return result, time.perf_counter() - started


@pytest.mark.usefixtures("stalled")
async def test_the_payload_archive_gives_up_inside_its_deadline() -> None:
    """FAILS IF: a stalled store holds the post-call pipeline on a debugging aid."""
    result, spent = await _timed(
        lambda: storage.archive_payload(
            tenant_id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            engine="fake",
            execution_id="exec_1",
            document=b"{}",
        )
    )
    assert result is None
    assert spent < STALL_S * 0.8, spent


@pytest.mark.usefixtures("stalled")
@pytest.mark.parametrize(
    "call",
    [
        lambda: storage.read_kb_object("kb-uploads/x"),
        lambda: storage.objects_under("recordings/x/"),
        lambda: storage.delete_objects(["recordings/x/1.wav"]),
        lambda: storage.object_exists("recordings/x/1.wav"),
        lambda: storage.upload_read("copilot-uploads/x", max_bytes=10),
        lambda: storage.upload_keys_under("copilot-uploads/x/"),
        lambda: storage.delete_uploads(["copilot-uploads/x/1"]),
    ],
    ids=[
        "kb_read",
        "list",
        "delete",
        "head",
        "upload_read",
        "upload_list",
        "upload_delete",
    ],
)
async def test_a_stalled_store_is_refused_into_the_retry_ladder_inside_its_deadline(
    call: Callable[[], Awaitable[Any]],
) -> None:
    """FAILS IF: an upload, download, listing or delete waits on the store past its
    deadline, or reports the stall as anything but storage being unavailable."""
    started = time.perf_counter()
    with pytest.raises(StorageUnavailableError):
        await call()
    assert time.perf_counter() - started < STALL_S * 0.8


def test_the_deadlines_fit_the_worker_budget() -> None:
    from apps.workers import settings as worker_settings

    budget = float(worker_settings.WorkerSettings.job_timeout)
    assert storage.STORE_CALL_DEADLINE_S <= storage.STORE_BULK_DEADLINE_S < budget / 2
