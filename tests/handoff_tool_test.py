"""The mid-call handover notice, on the latency-critical receiver (D-533).

**IT IS THE ONLY SIGNAL THAT EXISTS WHILE THE CALL IS STILL HAPPENING**, and it is the
transfer tool's PRE-CALL WEBHOOK rather than a function the model calls — the vendor fires
it as a background task, before the leg is placed, with errors swallowed
(VERIFIED-OSS: `bolna-ai/bolna@cd2e192`, `bolna/agent_manager/task_manager.py:3143-3160`).
So nothing this endpoint answers can stop a handover, and everything it does has to happen
in the ack budget anyway: a slow endpoint is dead air on a live call whether or not the
vendor promises it will not block. A vendor's promise is not a budget we get to spend.

The obligations asserted here are the ones every tool on this router shares
(`tests/call_optout_test.py`, `tests/callback_tool_test.py`): verify the source before a
byte of body, ack fast, write nothing, and name a job the worker actually registers. The
one that is specific to this endpoint is the last test — the model's own prose about a live
conversation crosses the queue and is REDACTED by the worker, never by this service and
never into a log line.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import tool_routes
from apps.workers.handoff import HANDOFF_JOB, MAX_BRIEF_CHARS, _bounded
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

pytestmark = pytest.mark.anyio

ENGINE_EGRESS_IP = "198.51.100.7"
EDGE_PROXY_IP = "127.0.0.1"
ATTACKER_IP = "203.0.113.9"
HANDOFF = "/tools/v1/bolna/handoff"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}


@pytest.fixture
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str = EDGE_PROXY_IP) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def test_the_endpoint_and_the_worker_name_the_same_job() -> None:
    """`tool_routes` cannot import `apps.workers` (hard rule 3), so the name is spelled
    twice. A drift here is a handover the client never sees recorded, on a call where their
    own staff answered a customer — the mid-call notice is the ONLY producer of that row."""
    assert tool_routes.HANDOFF_JOB == HANDOFF_JOB


async def test_a_stranger_cannot_forge_a_handover_notice(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint is unsigned, so the source check is the whole authenticity control.
    A forged notice would write a `handoff_attempts` row against a real tenant claiming
    one of their callers was put through to a member of their staff."""
    enqueued: list[str] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        enqueued.append(job)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(
            HANDOFF,
            json={"execution_id": "exec_x", "reason": "wants a person"},
            headers={"CF-Connecting-IP": ATTACKER_IP},
        )
    assert response.status_code == 401
    assert enqueued == []
    assert "X-Ack-Ms" in response.headers, "a refusal is measured too"


async def test_a_notice_naming_no_execution_is_refused_rather_than_acked(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A handover we cannot attribute to a conversation is a row we could only write into
    somebody's account at random. 422, and nothing queued."""
    enqueued: list[str] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        enqueued.append(job)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(HANDOFF, json={"reason": "wants a person"}, headers=HEADERS)
    assert response.status_code == 422
    assert enqueued == []


async def test_the_notice_queues_the_job_and_writes_nothing(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard rule 3: ack fast, defer everything. The model's `reason` and `summary` cross the
    queue because they exist nowhere else — the execution record's own summary is not
    populated until the call ends, and by then the phone has stopped ringing."""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        captured.append((job, payload))
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(
            HANDOFF,
            json={
                "execution_id": "exec_handoff",
                "reason": "caller asked for the owner",
                "summary": "Asked about a refund on an order from last week.",
                "event": "handoff_started",
            },
            headers=HEADERS,
        )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert len(captured) == 1
    job, payload = captured[0]
    assert job == HANDOFF_JOB
    assert payload["execution_id"] == "exec_handoff"
    assert payload["reason"] == "caller asked for the owner"
    # NOT the destination: the number is never sent to us and is never asked for. We chose
    # it, and asking the vendor to echo a staff mobile back onto a webhook path would put
    # PII where nothing reads it (hard rule 6).
    assert "call_transfer_number" not in payload


async def test_the_ack_carries_the_measurement_every_tool_on_this_router_does(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRD §6.2's in-call budget is measured per endpoint, not pooled: this one lands in
    `tool_ack_ms` beside the other three, so a regression here is visible as itself."""

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(HANDOFF, json={"execution_id": "e1"}, headers=HEADERS)
    assert response.status_code == 202
    assert float(response.headers["X-Ack-Ms"]) >= 0


def test_the_models_prose_is_redacted_and_bounded_before_it_is_stored() -> None:
    """SEC-COMP §4 applies to a handover brief exactly as it applies to a transcript. The
    summary is written by a language model about a live conversation, so it can carry
    anything the caller said out loud — and it lands in a column a client reads and (once a
    channel exists) in a message delivered to somebody's handset."""
    brief = _bounded("Caller read out card 4111 1111 1111 1111 and wants the owner")
    assert brief is not None
    assert "4111" not in brief, "a card number reached a handover brief"
    assert _bounded("x" * (MAX_BRIEF_CHARS + 500)) == "x" * MAX_BRIEF_CHARS
    assert _bounded("   ") is None
    assert _bounded(None) is None
