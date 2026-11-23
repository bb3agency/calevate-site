"""`put_job_notes_live` runs the put-live a committed change to what a job notes queued."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from apps.api.campaigns import notes_live
from apps.api.core.errors import ProblemError
from apps.workers import job_notes_live


def _payload(tenant_id: UUID, *jobs: tuple[str, UUID]) -> dict[str, object]:
    return {
        "tenant_id": str(tenant_id),
        "jobs": [{"kind": kind, "job_id": str(job_id)} for kind, job_id in jobs],
    }


async def test_each_queued_job_is_put_live_and_a_refusal_does_not_stop_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the worker does not put each queued campaign and line live, or one refusal
    stops the others or is reported as done."""
    tenant_id, campaign_id, line_id = uuid4(), uuid4(), uuid4()
    seen: list[tuple[UUID, str, UUID]] = []

    async def _put_live(tenant: UUID, kind: str, job_id: UUID) -> None:
        seen.append((tenant, kind, job_id))
        if kind == "campaign":
            raise ProblemError.business_rule("not_ready", "Not ready.")

    monkeypatch.setattr(notes_live, "put_live", _put_live)
    payload = _payload(tenant_id, ("campaign", campaign_id), ("line", line_id))
    assert await job_notes_live.put_job_notes_live({}, payload) == "refused:1"
    assert seen == [(tenant_id, "campaign", campaign_id), (tenant_id, "line", line_id)]

    seen.clear()
    assert await job_notes_live.put_job_notes_live({}, _payload(tenant_id, ("line", line_id))) == (
        "done"
    )
    assert seen == [(tenant_id, "line", line_id)]


def test_the_worker_answers_to_the_name_the_queue_uses() -> None:
    assert job_notes_live.JOB_NAME == notes_live.PUT_LIVE_JOB


async def test_an_empty_list_queues_nothing() -> None:
    """FAILS IF: a change that left every list as it was queues a put-live; the session is
    never touched (it is not a session at all here)."""
    await notes_live.queue_put_live(object(), tenant_id=uuid4(), jobs=[])  # type: ignore[arg-type]
