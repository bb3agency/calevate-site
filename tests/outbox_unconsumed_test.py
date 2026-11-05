"""Outbox work is never lost to a deploy or a dropped job (L5-01, L5-03, L5-04, L5-11).

FAILS IF: a bulk job is published while no live bulk worker advertises it; a held bulk job is
retired as "no worker runs job"; a migration-queued message is claimed by an image that
lacks its revision; a published message keeps no payload to re-run from, or keeps it after
its run succeeded; a published message no run finished is never alarmed and put back; a
re-publish arq refuses because an earlier run FAILED is recorded as published; or a future
migration queues outbox work without stamping its revision.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from apps.api.authn.service import AUTH_EMAIL_JOB
from apps.api.core import queue as core_queue
from apps.api.core.queue import (
    BULK_CONSUMER_KEY_PREFIX,
    advertise_bulk_consumer,
    bulk_jobs_served,
    get_queue,
    withdraw_bulk_consumer,
)
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability import service as rel
from apps.api.team_alerts.service import CODE_JOB
from apps.workers import dispatcher
from sqlalchemy import text

RUN = uuid.uuid4().hex[:12]
_WRITTEN: list[UUID] = []
ROOT = Path(__file__).resolve().parents[1]

#: A real bulk job, so the dispatcher's routing is the production one. Its payload here is
#: never run: every row this module writes is deleted by id.
BULK_JOB = "recheck_call_quality"
PROBE_JOB = f"outbox_unconsumed_probe_{RUN}"


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(i) for i in _WRITTEN]},
        )


async def _row(
    job: str,
    *,
    status: str = "pending",
    attempts: int = 0,
    min_revision: str | None = None,
    published_ago_s: int | None = None,
) -> UUID:
    """One outbox row, backdated so it leads the oldest-first claim."""
    message_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
                "min_revision, published_at, consume_by, job_id, created_at, updated_at) "
                "VALUES (:id, :job, CAST(:payload AS jsonb), :status, :attempts, :rev, "
                "CASE WHEN CAST(:ago AS integer) IS NULL THEN NULL "
                "ELSE now() - make_interval(secs => CAST(:ago AS integer)) END, "
                "CASE WHEN CAST(:ago AS integer) IS NULL THEN NULL "
                "ELSE now() - interval '1 second' END, "
                "CASE WHEN CAST(:ago AS integer) IS NULL THEN NULL "
                "ELSE CAST(:job AS text) || ':' || CAST(:id AS text) END, "
                "now() - interval '10 years', now())"
            ),
            {
                "id": message_id,
                "job": job,
                "payload": json.dumps({"tenant_id": str(uuid.uuid4()), "marker": RUN}),
                "status": status,
                "attempts": attempts,
                "rev": min_revision,
                "ago": published_ago_s,
            },
        )
    _WRITTEN.append(message_id)
    return message_id


async def _read(message_id: UUID) -> dict[str, Any]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, payload, consume_by IS NOT NULL, consumed_at IS NOT NULL, "
                    "last_error FROM outbox_messages WHERE id = :id"
                ),
                {"id": message_id},
            )
        ).one()
    return {
        "status": row[0],
        "payload": dict(row[1]),
        "has_deadline": row[2],
        "consumed": row[3],
        "error": row[4],
    }


# ------------------------------------------------------------------ payload and consume


def test_the_credential_jobs_are_named_by_their_producers() -> None:
    assert {AUTH_EMAIL_JOB, CODE_JOB} == rel.SCRUB_AT_PUBLISH_JOBS


async def test_a_published_message_keeps_its_payload_until_its_run_succeeds() -> None:
    message_id = await _row(PROBE_JOB)
    async with untenanted_session() as session:
        await rel.mark_outbox_published(session, message_id=message_id, job_id="j")
    published = await _read(message_id)
    assert published["payload"].get("marker") == RUN, "nothing to re-run from"
    assert published["has_deadline"]

    async with untenanted_session() as session:
        await rel.mark_outbox_consumed(session, message_id=message_id, job=PROBE_JOB)
    consumed = await _read(message_id)
    assert consumed["consumed"]
    assert consumed["payload"] == {}, "a finished message keeps no personal data"


async def test_a_credential_is_still_forgotten_at_publish() -> None:
    message_id = await _row(AUTH_EMAIL_JOB)
    async with untenanted_session() as session:
        await rel.mark_outbox_published(session, message_id=message_id, job_id="j")
    state = await _read(message_id)
    assert state["payload"] == {}
    assert not state["has_deadline"], "a scrubbed message can never be re-published"


# ------------------------------------------------------------------ the unconsumed sweep


async def test_a_published_message_no_run_finished_is_put_back_and_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(rel, "alert", lambda stage, code, **_: raised.append(code))
    lost = await _row(PROBE_JOB, status="published", attempts=1, published_ago_s=9000)
    spent = await _row(
        PROBE_JOB, status="published", attempts=rel.OUTBOX_MAX_ATTEMPTS, published_ago_s=9000
    )

    async with untenanted_session() as session:
        swept = await rel.sweep_unconsumed_outbox(session)

    assert swept.republished >= 1 and swept.dead_lettered >= 1
    again = await _read(lost)
    assert again["status"] == "pending" and again["payload"].get("marker") == RUN
    assert "no run succeeded" in (again["error"] or "")
    dead = await _read(spent)
    assert dead["status"] == "failed" and dead["payload"].get("marker") == RUN
    assert "outbox_unconsumed" in raised and "outbox_dead_letter" in raised


async def test_a_consumed_or_pre_migration_message_is_left_alone() -> None:
    consumed = await _row(PROBE_JOB, status="published", published_ago_s=9000)
    old = await _row(PROBE_JOB, status="published", published_ago_s=9000)
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE outbox_messages SET consumed_at = now() WHERE id = :id"),
            {"id": consumed},
        )
        # Published before f5a9c3e1d7b2: no deadline, because its payload is already gone.
        await session.execute(
            text("UPDATE outbox_messages SET consume_by = NULL WHERE id = :id"), {"id": old}
        )
        await rel.sweep_unconsumed_outbox(session)
    assert (await _read(consumed))["status"] == "published"
    assert (await _read(old))["status"] == "published"


# ------------------------------------------------------------------ claim filters


async def _claimed(message_id: UUID, **kwargs: Any) -> bool:
    async with untenanted_session() as session:
        batch = await rel.claim_outbox_batch(session, limit=500, jobs=[PROBE_JOB], **kwargs)
    return any(m.id == message_id for m in batch)


async def test_a_held_job_is_left_pending_and_not_retired_as_unknown() -> None:
    message_id = await _row(PROBE_JOB)
    assert not await _claimed(message_id, held=[PROBE_JOB])
    assert (await _read(message_id))["status"] == "pending"


async def test_a_migration_queued_message_waits_for_an_image_with_its_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(rel, "alert", lambda stage, code, **_: raised.append(code))
    message_id = await _row(PROBE_JOB, min_revision=f"rev_{RUN}")
    assert not await _claimed(message_id, revisions={"older"})
    assert "outbox_held_for_release" in raised, "a hold past the alarm age is said aloud"
    assert await _claimed(message_id, revisions={"older", f"rev_{RUN}"})


# ------------------------------------------------------------------ bulk advertisement


async def test_bulk_jobs_served_is_what_every_live_bulk_worker_runs() -> None:
    redis = await get_queue()
    for key in [k async for k in redis.scan_iter(match=BULK_CONSUMER_KEY_PREFIX + "*")]:
        await redis.delete(key)
    assert await bulk_jobs_served(redis) == frozenset()
    await advertise_bulk_consumer(redis, f"a-{RUN}", ["x", "y"])
    await advertise_bulk_consumer(redis, f"b-{RUN}", ["y", "z"])
    try:
        assert await bulk_jobs_served(redis) == {"y"}, "an old worker still reading the queue"
    finally:
        await withdraw_bulk_consumer(redis, f"a-{RUN}")
        await withdraw_bulk_consumer(redis, f"b-{RUN}")
    assert await bulk_jobs_served(redis) == frozenset()


async def test_the_dispatcher_publishes_a_bulk_job_only_when_a_bulk_worker_runs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REGRESSION (L5-01): the new main worker published `recheck_call_quality` onto
    `arq:bulk` while the old bulk worker, which lacked it, still read the queue."""
    redis = await get_queue()
    for key in [k async for k in redis.scan_iter(match=BULK_CONSUMER_KEY_PREFIX + "*")]:
        await redis.delete(key)
    published: list[str] = []

    async def _spy(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
        published.append(job)
        return job_id

    monkeypatch.setattr(dispatcher, "enqueue", _spy)
    message_id = await _row(BULK_JOB)
    ctx = {dispatcher.REGISTERED_JOBS: frozenset({BULK_JOB})}

    await dispatcher.dispatch_outbox(ctx)
    assert (await _read(message_id))["status"] == "pending", "no bulk worker runs it yet"

    await advertise_bulk_consumer(redis, f"old-{RUN}", ["ingest_kb_source"])
    try:
        await dispatcher.dispatch_outbox(ctx)
        assert (await _read(message_id))["status"] == "pending", "the old bulk worker lacks it"
        await withdraw_bulk_consumer(redis, f"old-{RUN}")
        await advertise_bulk_consumer(redis, f"new-{RUN}", [BULK_JOB, "ingest_kb_source"])
        await dispatcher.dispatch_outbox(ctx)
    finally:
        await withdraw_bulk_consumer(redis, f"old-{RUN}")
        await withdraw_bulk_consumer(redis, f"new-{RUN}")
    assert (await _read(message_id))["status"] == "published"
    assert BULK_JOB in published


async def test_a_re_publish_refused_for_a_failed_earlier_run_is_dead_lettered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L5-11: "deduped" because arq holds a FAILED result is not "already done"."""

    async def _refused(*_args: Any, **_kwargs: Any) -> str | None:
        return None

    async def _failed(job: str, job_id: str) -> bool:
        return job == PROBE_JOB

    monkeypatch.setattr(dispatcher, "enqueue", _refused)
    monkeypatch.setattr(dispatcher, "earlier_run_failed", _failed)
    monkeypatch.setattr(rel, "alert", lambda *_a, **_k: None)
    message_id = await _row(PROBE_JOB)

    await dispatcher.dispatch_outbox({dispatcher.REGISTERED_JOBS: frozenset({PROBE_JOB})})

    state = await _read(message_id)
    assert state["status"] == "failed", "nothing will run it; the DLQ is where a person sees it"
    assert "earlier run" in (state["error"] or "")
    assert state["payload"].get("marker") == RUN


async def test_earlier_run_failed_reads_arq_result_for_the_job() -> None:
    """No result at all is not a failure: the run is still queued or long gone."""
    assert not await core_queue.earlier_run_failed(PROBE_JOB, f"{PROBE_JOB}:{uuid.uuid4()}")


# ------------------------------------------------------------------ migrations


def test_every_migration_from_now_on_stamps_the_outbox_work_it_queues() -> None:
    """L5-04: a message a migration queues carries that migration's revision, so the release
    still running between migrate and swap cannot run it with old code."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    unstamped = []
    for revision in script.iterate_revisions("heads", "f5a9c3e1d7b2"):
        source = Path(revision.path).read_text(encoding="utf-8")
        if "INSERT INTO outbox_messages" in source and "min_revision" not in source:
            unstamped.append(revision.revision)
    assert unstamped == []
