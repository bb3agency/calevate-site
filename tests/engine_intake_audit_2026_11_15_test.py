"""Engine boundary audit, 15 Nov 2026: regressions for the defects it fixed."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest
import webhook_routes
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import body_hash, mark_inbox_failed
from fastapi import Response


def _opt_out_work(token: str) -> webhook_routes.InboxWork:
    execution_id = f"evt_{token}"
    event_name = f"contact.opted_out:evt_{token}"
    return webhook_routes.InboxWork(
        provider="fake",
        key_id=execution_id,
        event_name=event_name,
        payload_hash=body_hash(
            {"engine": "fake", "execution_id": execution_id, "raw_status": event_name}
        ),
        redis_key=f"calevate:wh:fake:{execution_id}:{event_name}",
        job=webhook_routes.ENGINE_OPT_OUT_JOB,
        job_id=f"{webhook_routes.ENGINE_OPT_OUT_JOB}:fake:{execution_id}:{token}",
        job_payload={"engine": "fake", "execution_id": execution_id},
    )


async def _settle(work: webhook_routes.InboxWork, body: bytes) -> dict[str, str]:
    return await webhook_routes.settle(
        work,
        body,
        response=Response(),
        started=time.perf_counter(),
        meter=webhook_routes.WEBHOOK_ACK,
        signed=True,
    )


async def test_a_resent_event_whose_job_failed_is_taken_again() -> None:
    """An opt-out whose job gave up marks its inbox row failed so a re-send can take it,
    and the abandonment alarm tells the operator to re-send it from the vendor console.
    The receiver's Redis fast path still held the first delivery's key for an hour, so the
    re-send was answered `duplicate` before the inbox was asked and the opt-out was never
    filed (hard rule 5)."""
    token = uuid.uuid4().hex[:12]
    work = _opt_out_work(token)
    body = json.dumps({"id": f"evt_{token}", "event": "contact.opted_out"}).encode()
    queued: list[dict[str, Any]] = []

    async def _enqueue(_job: str, payload: dict[str, Any], *, job_id: str) -> str:
        queued.append(payload)
        return f"{job_id}:{len(queued)}"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(webhook_routes, "enqueue", _enqueue)
        first = await _settle(work, body)
        assert first["status"] == "accepted"

        # The worker abandons the job (`engine_signals._abandon`).
        async with untenanted_session() as session:
            await mark_inbox_failed(
                session, row_id=uuid.UUID(queued[0]["inbox_row_id"]), error="OperationalError"
            )

        resent = await _settle(work, body)

    assert resent["status"] == "accepted", resent
    assert len(queued) == 2
