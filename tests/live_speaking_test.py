"""Who is speaking on a live call: the worker's write, the store, and the browser's stream (D-656).

What is proved here:

1. **The worker's write is authenticated exactly like its other writes** — no token is 401,
   a ref the platform did not mint is 404 — and it lands in Redis under the tenant the ref
   names, with a TTL, never in a table.
2. **A late, older state cannot overwrite a newer one** (the `seq` compare-and-set).
3. **The browser read is tenant-scoped.** Another tenant's call is 404, exactly like a call
   that does not exist; no session is 401.
4. **The stream sends the state, each change once, and ends when the call does.**
5. **The hand-written TypeScript frame matches the Python model**, because FastAPI 0.140
   leaves the SSE item model out of the OpenAPI document under an included router.

SHARED STATE DISCIPLINE: every tenant and call is minted here, every Redis key is under a
tenant this file created, and each test deletes the keys it wrote.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.core.redis import get_redis
from apps.api.crm import live_speaking
from apps.api.crm.live_speaking import (
    SPEAKING_TTL_S,
    CallSpeakingOut,
    LiveCall,
    read_speaking,
    record_speaking,
    resolve_live_call,
    speaking_frames,
    speaking_key,
)
from apps.api.db.session import tenant_session
from apps.api.main import app
from calevate_shared.worker_api import SpeakingStateIn
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.worker_api_harness import call_ref, declare_pipecat_engine, worker_client
from voice_worker.api_client import WorkerApiError

pytestmark = [pytest.mark.rls]

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The worker routes refuse any other engine (D-627)."""
    yield from declare_pipecat_engine(monkeypatch)


def _state(speaker: str | None, seq: int) -> SpeakingStateIn:
    return SpeakingStateIn(speaker=speaker, seq=seq, at=datetime.now(UTC))  # type: ignore[arg-type]


async def _forget(tenant_id: uuid.UUID, ref: str) -> None:
    await get_redis().delete(speaking_key(tenant_id, ref))


async def _call(
    tenant_id: uuid.UUID, *, status: str = "in_progress", ref: str | None = None
) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                ":status, now(), now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": ref, "status": status},
        )
    return call_id


async def _set_status(tenant_id: uuid.UUID, call_id: uuid.UUID, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = :s WHERE id = :id"), {"s": status, "id": call_id}
        )


def _frames(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")
    ]


# --- the worker's write ---------------------------------------------------------------


async def test_the_worker_writes_an_expiring_key_under_the_refs_tenant(worker_token: None) -> None:
    tenant_id = uuid.uuid4()
    _, ref = call_ref(tenant_id)
    async with worker_client() as api:
        answer = await api.post_speaking(ref, _state("caller", 1))
    try:
        assert answer.accepted is True
        held = await get_redis().get(speaking_key(tenant_id, ref))
        assert held is not None
        assert json.loads(held)["speaker"] == "caller"
        ttl = await get_redis().ttl(speaking_key(tenant_id, ref))
        assert 0 < ttl <= SPEAKING_TTL_S
    finally:
        await _forget(tenant_id, ref)


async def test_an_older_state_cannot_overwrite_a_newer_one(worker_token: None) -> None:
    tenant_id = uuid.uuid4()
    _, ref = call_ref(tenant_id)
    async with worker_client() as api:
        assert (await api.post_speaking(ref, _state("agent", 5))).accepted is True
        assert (await api.post_speaking(ref, _state("caller", 4))).accepted is False
        assert (await api.post_speaking(ref, _state("agent", 5))).accepted is False
        assert (await api.post_speaking(ref, _state(None, 6))).accepted is True
    try:
        speaker, since = await read_speaking(tenant_id, ref)
        assert speaker is None and since is not None
    finally:
        await _forget(tenant_id, ref)


async def test_the_worker_write_needs_the_worker_token(worker_token: None) -> None:
    tenant_id = uuid.uuid4()
    _, ref = call_ref(tenant_id)
    async with worker_client(token="not-the-token") as api:
        with pytest.raises(WorkerApiError, match="401") as refused:
            await api.post_speaking(ref, _state("caller", 1))
    assert refused.value.retryable is False
    assert await get_redis().get(speaking_key(tenant_id, ref)) is None


async def test_a_ref_the_platform_did_not_mint_is_refused(worker_token: None) -> None:
    async with worker_client() as api:
        with pytest.raises(WorkerApiError, match="404"):
            await api.post_speaking("someone-elses-id", _state("caller", 1))


async def test_a_store_outage_is_a_503_and_not_a_500(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Down:
        async def eval(self, *_args: Any) -> Any:
            raise RedisConnectionError("down")

    monkeypatch.setattr(live_speaking, "get_redis", lambda: _Down())
    _, ref = call_ref(uuid.uuid4())
    async with worker_client() as api:
        with pytest.raises(WorkerApiError, match="503") as failed:
            await api.post_speaking(ref, _state("caller", 1))
    assert failed.value.retryable is True


# --- the store's read ----------------------------------------------------------------


async def test_a_held_value_nobody_can_read_is_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    ref = f"pipecat:{tenant_id}:call-x"
    key = speaking_key(tenant_id, ref)
    try:
        assert await read_speaking(tenant_id, ref) == (None, None)
        await get_redis().set(key, "not json", ex=5)
        assert await read_speaking(tenant_id, ref) == (None, None)
        await get_redis().set(
            key, json.dumps({"speaker": "robot", "at": "2026-10-01T10:00:00+00:00"}), ex=5
        )
        speaker, since = await read_speaking(tenant_id, ref)
        assert speaker is None and since is not None
    finally:
        await get_redis().delete(key)

    class _Down:
        async def get(self, *_args: Any) -> Any:
            raise RedisConnectionError("down")

    monkeypatch.setattr(live_speaking, "get_redis", lambda: _Down())
    assert await read_speaking(tenant_id, ref) == (None, None)


# --- the stream ------------------------------------------------------------------------


async def test_the_stream_sends_each_change_once_and_ends_with_the_call() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    _, ref = call_ref(tenant_id)
    call_id = await _call(tenant_id, ref=ref)
    call = await resolve_live_call(tenant_id, call_id)
    clock = [0.0]
    script = iter(
        [
            ("caller", 1),
            ("caller", 2),  # a heartbeat: same speaker, not a change
            ("agent", 3),
            (None, 4),
            "end",
        ]
    )

    async def sleep(seconds: float) -> None:
        clock[0] += seconds
        step = next(script)
        if step == "end":
            await _set_status(tenant_id, call_id, "completed")
            clock[0] += live_speaking.STATUS_RECHECK_S
            return
        speaker, seq = step
        await record_speaking(tenant_id, ref, _state(speaker, seq))

    try:
        frames = [f async for f in speaking_frames(call, clock=lambda: clock[0], sleep=sleep)]
    finally:
        await _forget(tenant_id, ref)
    assert [(f.speaker, f.live) for f in frames] == [
        (None, True),
        ("caller", True),
        ("agent", True),
        (None, True),
        (None, False),
    ]


async def test_a_stream_is_bounded_in_time(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    _, ref = call_ref(tenant_id)
    call_id = await _call(tenant_id, ref=ref)
    call = await resolve_live_call(tenant_id, call_id)
    clock = [0.0]

    async def sleep(seconds: float) -> None:
        clock[0] += live_speaking.MAX_STREAM_S

    frames = [f async for f in speaking_frames(call, clock=lambda: clock[0], sleep=sleep)]
    # The status recheck is due too, and finds the call still live: the stream simply ends.
    assert [(f.speaker, f.live) for f in frames] == [(None, True)]


async def test_a_finished_or_unreached_call_answers_once() -> None:
    tenant_id = uuid.uuid4()
    done = LiveCall(
        tenant_id=tenant_id, call_id=uuid.uuid4(), engine_call_id="x", status="completed"
    )
    queued = LiveCall(
        tenant_id=tenant_id, call_id=uuid.uuid4(), engine_call_id=None, status="queued"
    )
    assert [f async for f in speaking_frames(done)] == [
        CallSpeakingOut(speaker=None, live=False, since=None)
    ]
    assert [f async for f in speaking_frames(queued)] == [
        CallSpeakingOut(speaker=None, live=True, since=None)
    ]


async def test_a_call_that_disappears_mid_stream_ends_it() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    _, ref = call_ref(tenant_id)
    call = LiveCall(
        tenant_id=tenant_id, call_id=uuid.uuid4(), engine_call_id=ref, status="in_progress"
    )
    clock = [0.0]

    async def sleep(seconds: float) -> None:
        clock[0] += live_speaking.STATUS_RECHECK_S

    frames = [f async for f in speaking_frames(call, clock=lambda: clock[0], sleep=sleep)]
    assert [(f.speaker, f.live) for f in frames] == [(None, True), (None, False)]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def test_the_browser_reads_its_own_call_over_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, slug, token = await _make_tenant()
    _, ref = call_ref(tenant_id)
    call_id = await _call(tenant_id, ref=ref)
    await record_speaking(tenant_id, ref, _state("agent", 1))
    # End the stream after its first frame, so the in-process transport can return.
    monkeypatch.setattr(live_speaking, "MAX_STREAM_S", 0.0)
    try:
        async with _client() as http:
            response = await http.get(
                f"/v1/calls/{call_id}/speaking",
                headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
            )
    finally:
        await _forget(tenant_id, ref)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    frames = _frames(response.text)
    assert [(f["speaker"], f["live"]) for f in frames] == [("agent", True)]
    assert set(frames[0]) == {"speaker", "live", "since"}


async def test_a_finished_call_ends_the_stream_with_live_false() -> None:
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call(tenant_id, status="completed", ref=call_ref(tenant_id)[1])
    async with _client() as http:
        response = await http.get(
            f"/v1/calls/{call_id}/speaking",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200
    assert _frames(response.text) == [{"speaker": None, "live": False, "since": None}]


async def test_another_tenants_call_is_a_404_and_no_session_is_a_401() -> None:
    owner, _owner_slug, _owner_token = await _make_tenant()
    call_id = await _call(owner, ref=call_ref(owner)[1])
    _stranger, slug, token = await _make_tenant()
    async with _client() as http:
        foreign = await http.get(
            f"/v1/calls/{call_id}/speaking",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
        missing = await http.get(
            f"/v1/calls/{uuid.uuid4()}/speaking",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
        anonymous = await http.get(f"/v1/calls/{call_id}/speaking")
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"]
    assert anonymous.status_code == 401


# --- the browser's hand-written frame type ------------------------------------------------


def test_the_typescript_frame_matches_the_python_model() -> None:
    source = (REPO / "apps/web/src/lib/api/callSpeaking.ts").read_text(encoding="utf-8")
    body = re.search(r"export interface CallSpeakingFrame \{(.*?)\n\}", source, re.S)
    assert body is not None, "callSpeaking.ts no longer declares CallSpeakingFrame"
    declared = set(re.findall(r"^\s+(\w+):", body.group(1), re.M))
    assert declared == set(CallSpeakingOut.model_fields)
