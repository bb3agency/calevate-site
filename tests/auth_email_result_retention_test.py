"""A delivered authentication email leaves no copy of its secret in Redis.

`authn/service._enqueue_auth_email` puts a live one-time credential — a reset token, an
invitation or operator-setup link, an OTP — in the job's arguments, and the outbox scrubs
its own copy at publish so the exposure is "the length of a dispatch tick"
(`tests/outbox_payload_scrub_test.py`). arq then undid that: `serialize_result` writes the
job's ARGS into `arq:result:<id>` and keeps it for `keep_result` — 3600 s, the whole life
of a reset link — so anybody who could read Redis could sign in as whoever last asked for
a reset. The auth-email job keeps no result.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.queue import get_queue, job_id_for
from apps.workers import auth_email
from apps.workers.settings import FUNCTIONS, WorkerSettings
from arq.connections import ArqRedis
from arq.constants import result_key_prefix
from arq.worker import Worker, func

SECRET = f"tok_live_reset_{uuid.uuid4().hex}"


class _Sent:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.bodies.append(body)
        return True


def test_the_auth_email_job_is_registered_to_keep_no_result() -> None:
    registered = {f.name: f for f in map(func, FUNCTIONS)}
    assert registered["deliver_auth_email"].keep_result_s == 0
    # The worker-wide default is untouched: every other job keeps its dedupe window.
    assert WorkerSettings.keep_result == 3600


@pytest.mark.asyncio
async def test_a_delivered_reset_email_leaves_no_result_key_holding_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _Sent()
    monkeypatch.setattr(auth_email, "get_transport", lambda: sent)
    queue_name = f"arq:test-auth-email-{uuid.uuid4().hex[:8]}"
    job_id = job_id_for("deliver_auth_email", uuid.uuid4().hex)
    payload: dict[str, Any] = {
        "kind": "password_reset",
        "realm": "client",
        "to": "owner@calevate-test.example",
        "secret": SECRET,
    }
    redis: ArqRedis = await get_queue()
    await redis.enqueue_job("deliver_auth_email", payload, _job_id=job_id, _queue_name=queue_name)

    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        queue_name=queue_name,
        keep_result=WorkerSettings.keep_result,
        burst=True,
        poll_delay=0.01,
        handle_signals=False,
        ctx={},
    )
    try:
        await worker.main()
    finally:
        await worker.close()

    assert any(SECRET in body for body in sent.bodies), "the email was not delivered"
    assert await redis.get(result_key_prefix + job_id) is None, (
        "the job's result key holds the plaintext credential for keep_result seconds"
    )
