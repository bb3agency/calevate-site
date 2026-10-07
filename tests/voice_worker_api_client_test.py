"""`voice_worker.api_client` — which failures a write survives, and which it must not retry.

The settlement is the only producer of a Pipecat call's post-call outbox row (D-607), and
the flush in front of it is what puts the transcript there first. Both are idempotent on the
server (`(call_id, idx)` for turns, the `post-call:{calls.id}` outbox key for the
settlement), so a transient failure is retried; a refusal the same request would get again
is not. Everything here runs over `httpx.MockTransport`: no socket, no database.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pytest
from calevate_shared.worker_api import ObservationBatch, SettlementRequest
from voice_worker import api_client
from voice_worker.api_client import WorkerApiClient, WorkerApiError

_SETTLED = {
    "already_settled": False,
    "rows_written": 0,
    "refusals_recorded": 0,
    "post_call_enqueued": True,
}
_OBSERVED = {"turns_written": 0, "turns_already_present": 0, "status": "in_progress"}


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_client, "WRITE_RETRY_BACKOFF_S", 0.0)


def _client(
    answers: list[Callable[[httpx.Request], httpx.Response]],
) -> tuple[WorkerApiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers[min(len(seen), len(answers)) - 1](request)

    client = WorkerApiClient.from_config(
        base_url="https://api.test", token="t", transport=httpx.MockTransport(handler)
    )
    return client, seen


def _status(code: int, body: object | None = None) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(code, json=body if body is not None else {})


def _reset(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection reset", request=request)


def _settlement() -> SettlementRequest:
    return SettlementRequest(final_status="completed", direction="inbound", agent_id=uuid.uuid4())


@pytest.mark.parametrize(
    "first",
    [_status(502), _status(503), _status(429), _reset],
    ids=["502", "503", "429", "connection-reset"],
)
async def test_a_settlement_survives_one_transient_failure(
    first: Callable[[httpx.Request], httpx.Response],
) -> None:
    """One bad gateway at the end of a call used to lose its post-call pipeline for ever."""
    client, seen = _client([first, _status(200, _SETTLED)])
    async with client:
        answer = await client.post_settlement("pipecat:t:c", _settlement())

    assert answer.post_call_enqueued is True
    assert len(seen) == 2


async def test_a_flush_survives_one_transient_failure() -> None:
    client, seen = _client([_status(503), _status(200, _OBSERVED)])
    batch = ObservationBatch(agent_id=uuid.uuid4(), direction="inbound")
    async with client:
        await client.post_observations("pipecat:t:c", batch)

    assert len(seen) == 2


@pytest.mark.parametrize("code", [400, 401, 404, 409, 422])
async def test_a_refusal_is_not_retried(code: int) -> None:
    """The same body gets the same 4xx: retrying only delays the loud failure."""
    client, seen = _client([_status(code), _status(200, _SETTLED)])
    async with client:
        with pytest.raises(WorkerApiError):
            await client.post_settlement("pipecat:t:c", _settlement())

    assert len(seen) == 1


async def test_retries_are_bounded_and_the_last_failure_is_raised() -> None:
    client, seen = _client([_status(503)])
    async with client:
        with pytest.raises(WorkerApiError, match="503"):
            await client.post_settlement("pipecat:t:c", _settlement())

    assert len(seen) == api_client.WRITE_ATTEMPTS


async def test_the_session_read_is_not_retried_because_the_caller_is_ringing() -> None:
    """The ring has one wall-clock budget; a retry would spend it twice."""
    client, seen = _client([_status(503)])
    async with client:
        with pytest.raises(WorkerApiError):
            await client.session("pipecat:t:a")

    assert len(seen) == 1


# --------------------------------------------------------------------------------------
# The correlation id: one call followed from this container's log lines into the API's.
# --------------------------------------------------------------------------------------


async def test_every_call_scoped_request_carries_the_call_ref_as_the_correlation_id() -> None:
    from calevate_shared.engine import pipecat_call_ref

    call_ref = pipecat_call_ref(uuid.uuid4(), uuid.uuid4())
    client, seen = _client([_status(200, _SETTLED)])
    async with client:
        await client.post_settlement(call_ref, _settlement())
    assert seen[0].headers[api_client.CORRELATION_HEADER] == call_ref
    # A real ref is well inside the API's 128-character, colon-permitting pattern.
    assert api_client.CORRELATION_ID_PATTERN.fullmatch(call_ref)


async def test_an_id_the_api_would_not_adopt_is_not_sent() -> None:
    """Negative control: the API replaces an id outside its pattern, so sending one would
    only put a value in a header that no log line ever carries. Too long is not truncated."""
    client, seen = _client([_status(200, _OBSERVED)])
    async with client:
        batch = ObservationBatch(agent_id=uuid.uuid4(), direction="inbound")
        await client.post_observations("x" * 129, batch)
    assert api_client.CORRELATION_HEADER not in seen[0].headers
    assert api_client.correlation_headers("bad ref/with space") == {}
    assert api_client.correlation_headers(None) == {}


def test_the_pattern_is_the_one_the_api_adopts() -> None:
    from apps.api.core import middleware

    assert api_client.CORRELATION_ID_PATTERN.pattern == middleware._CALLER_CORRELATION_ID.pattern
    assert api_client.CORRELATION_HEADER == middleware.CORRELATION_HEADER
