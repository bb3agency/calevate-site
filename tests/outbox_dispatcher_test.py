"""The dispatcher loop and its two housekeeping crons (`apps/workers/dispatcher.py`).

The outbox's first half — "write the side effect as a row in the domain transaction" —
is exercised by every feature that uses it. The SECOND half is this loop, and until now
nothing ran it: `claim_outbox_batch` has its own tests, `enqueue` has its own tests, and
the function that turns one into the other had none. What that leaves untested is
exactly what the loop exists for:

- **a claimed row becomes a queued job AND is recorded as published.** A message that is
  enqueued but never marked would be re-enqueued on the next tick — the duplicate
  delivery `mark_outbox_published`'s CAS is written to prevent;
- **one poisoned message does not stop the batch.** The `except` around the publish is
  the whole reason a single bad payload cannot stall every other tenant's
  notifications, and an `except` nobody has ever entered is a claim, not a control;
- **the stall alarm stays quiet when nothing is stalled.** `ops_resilience_test` proves
  it fires; an alarm that ALSO fires when the pipeline is healthy is an alarm operators
  learn to ignore, which is the same failure as not having one.

Cross-suite courtesy: the outbox is platform-wide by design (one loop for every
tenant), so this module's rows are backdated to be claimed first and deleted on the way
out — BY ID, collected as they are created. They used to be found again by
`payload->>'marker'`, which stopped being possible the day publishing began scrubbing the
payload (`reliability.service.mark_outbox_published`): a published row has no marker any
more, so a marker-keyed cleanup would silently leave every SUCCESSFUL row behind in a
database this suite shares.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.queue import enqueue as real_enqueue
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import dispatcher
from arq.jobs import SerializationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

RUN = uuid.uuid4().hex[:12]

#: Every outbox row this module writes. The id survives the publish scrub; the marker in
#: the payload does not.
_WRITTEN: list[UUID] = []


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(message_id) for message_id in _WRITTEN]},
        )
        await session.execute(
            text("DELETE FROM idempotency_records WHERE idempotency_key LIKE :m"),
            {"m": f"%{RUN}"},
        )


async def _outbox_row(job: str, marker: str) -> UUID:
    """One pending outbox row, backdated so this module's rows lead the oldest-first
    claim rather than queueing behind whatever another suite left pending."""
    message_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "created_at, updated_at) VALUES (:id, 'default', :job, CAST(:payload AS jsonb), "
                "'pending', 0, now() - interval '10 years', now())"
            ),
            {"id": message_id, "job": job, "payload": json.dumps({"marker": marker})},
        )
    _WRITTEN.append(message_id)
    return message_id


async def _status(message_id: UUID) -> tuple[str, str | None, str | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT status, job_id, last_error FROM outbox_messages WHERE id = :id"),
                {"id": message_id},
            )
        ).first()
    assert row is not None
    return str(row[0]), row[1], row[2]


# ------------------------------------------------------------------ dispatch_outbox


async def test_a_claimed_message_is_enqueued_and_recorded_as_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two halves of one step. Enqueueing without recording it re-delivers the job
    on the next tick — for `deliver_outbound_webhook` that is a duplicate POST into a
    client's CRM — and recording without enqueueing loses the side effect silently.

    The job id the loop stores is the one `enqueue` returned, so the row can be traced
    to the job that carries it.
    """
    marker = f"outbox-good-{RUN}"
    message_id = await _outbox_row("cron:dispatch_outbox_probe", marker)

    seen: list[tuple[str, str | None]] = []

    async def _spy(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
        seen.append((job, job_id))
        return await real_enqueue(job, *args, job_id=job_id, **kwargs)

    monkeypatch.setattr(dispatcher, "enqueue", _spy)

    result = await dispatcher.dispatch_outbox({})

    status, job_id, last_error = await _status(message_id)
    assert status == "published", f"{status}: a published message must never be claimed again"
    assert job_id, "the job id is the trace from the row to the work it became"
    assert last_error is None
    assert ("cron:dispatch_outbox_probe", f"cron:dispatch_outbox_probe:{message_id}") in seen, (
        "the job is keyed on the message id, so a re-publish dedupes rather than doubles"
    )
    assert result.startswith("published="), result
    assert int(result.split("=")[1]) >= 1


async def test_one_poisoned_message_does_not_stop_the_rest_of_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A publish that raises is recorded against ITS OWN row and the loop carries on.

    Without the `except`, one message whose payload the queue refuses would abort the
    tick — and since the claim is committed, every other tenant's notifications would
    sit behind it until somebody noticed. The failed message stays `pending` (it has
    attempts left) with the error recorded, which is what lets it walk to the DLQ
    instead of looping forever.

    `SerializationError` rather than a bare `RuntimeError` because that is what a poison
    payload ACTUALLY raises — arq wraps every serializer failure in it
    (`arq/jobs.py:serialize_job`) — and because the handler is now scoped to the
    exceptions a payload can produce (D-182). A test that simulated poison with an
    exception no payload can raise was pinning the branch's width rather than its
    subject.
    """
    poison_marker = f"outbox-poison-{RUN}"
    good_marker = f"outbox-after-poison-{RUN}"
    poisoned = await _outbox_row("cron:dispatch_outbox_probe", poison_marker)
    after = await _outbox_row("cron:dispatch_outbox_probe", good_marker)

    async def _refuse_the_poison(
        job: str, *args: Any, job_id: str | None = None, **kwargs: Any
    ) -> str | None:
        if job_id and str(poisoned) in job_id:
            raise SerializationError('unable to serialize job "cron:dispatch_outbox_probe"')
        return await real_enqueue(job, *args, job_id=job_id, **kwargs)

    monkeypatch.setattr(dispatcher, "enqueue", _refuse_the_poison)

    await dispatcher.dispatch_outbox({})

    poison_status, poison_job, poison_error = await _status(poisoned)
    after_status, after_job, _ = await _status(after)
    assert poison_status == "pending", "attempts left, so it is retried rather than dead-lettered"
    assert poison_job is None, "a message that never reached the queue has no job id"
    assert poison_error is not None and poison_error.startswith("SerializationError:"), poison_error
    assert after_status == "published", "the message behind the poison one still went out"
    assert after_job


async def test_a_database_fault_ends_the_tick_instead_of_being_recorded_as_poison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-8: the failure report was the second casualty of the fault it exists to report.

    `mark_outbox_published` writes through the CALLER's session, inside the same `try` as
    the publish, and the handler that used to catch everything answers by issuing another
    statement on that same session. So a `DBAPIError` from the status write landed in the
    poison branch, `mark_outbox_failed` met a failed transaction, and the tick aborted
    anyway — with the batch's status writes rolled back and up to fifty messages charged
    an attempt each pass until `_dead_letter_exhausted_claims` retired them as poison they
    never were.

    What must happen instead: the database error ESCAPES. arq's retry is the right
    response to "the database is gone", and the row must not be labelled `failed` with a
    `DBAPIError` in `last_error` as though its payload were at fault.
    """
    marker = f"outbox-dbfault-{RUN}"
    message_id = await _outbox_row("cron:dispatch_outbox_probe", marker)

    async def _database_is_gone(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("UPDATE outbox_messages ...", {}, Exception("server closed"))

    monkeypatch.setattr(dispatcher, "mark_outbox_published", _database_is_gone)

    with pytest.raises(OperationalError):
        await dispatcher.dispatch_outbox({})

    status, job_id, last_error = await _status(message_id)
    assert status == "pending", (
        "a message the database could not be told about is still owed, not dead-lettered"
    )
    assert last_error is None, (
        "a database fault was recorded against the message as if its payload were poison"
    )
    assert job_id is None


# ------------------------------------------------------------------- sweep_expired


async def test_the_idempotency_sweep_removes_only_records_whose_window_has_closed() -> None:
    """The replay window is 24 hours, and the table is swept so its unique index stays
    small enough to matter. Sweeping a LIVE record would be worse than not sweeping at
    all: the key that stops a double-click placing two calls would vanish while the
    client's browser is still holding it.
    """
    live_key = f"live-{RUN}"
    dead_key = f"dead-{RUN}"
    async with untenanted_session() as session:
        for key, expires in ((live_key, "+1 hour"), (dead_key, "-1 hour")):
            await session.execute(
                text(
                    "INSERT INTO idempotency_records (id, scope_key, route, method, "
                    "idempotency_key, request_hash, status, expires_at, created_at, updated_at) "
                    "VALUES (:id, :scope, '/v1/probe', 'POST', :key, 'hash', 'processing', "
                    "now() + CAST(:expires AS interval), now(), now())"
                ),
                {"id": uuid7(), "scope": f"scope-{RUN}", "key": key, "expires": expires},
            )

    removed = await dispatcher.sweep_expired({})

    async with untenanted_session() as session:
        surviving = {
            str(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT idempotency_key FROM idempotency_records "
                        "WHERE idempotency_key IN (:live, :dead)"
                    ),
                    {"live": live_key, "dead": dead_key},
                )
            ).all()
        }
    assert surviving == {live_key}, "the open window survives, the closed one does not"
    assert removed.startswith("idempotency_swept="), removed
    assert int(removed.split("=")[1]) >= 1


# ---------------------------------------------------------- report_stalled_pipeline


async def test_a_healthy_pipeline_raises_no_stall_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of `ops_resilience_test`'s alarm test, and the half that decides
    whether anybody still reads it. A completed call whose extraction landed is a call
    the pipeline finished; if the alarm fired for it too, "postcall_pipeline_stalled"
    would page ops on every tick and stop meaning anything.

    `_callable_tenants` is pinned to this test's own tenant because the probe is
    platform-wide by design and every other suite's data is in the same database — the
    enumeration itself is proved by `ops_resilience_test`, and what is measured here is
    the verdict for a tenant that is genuinely healthy.
    """
    created = await admin_service.create_organization(
        name="Quiet Clinic",
        slug=f"quiet-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "to_e164, started_at, ended_at, duration_s, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :ecid, 'outbound', 'completed', '+919876500222', "
                "now() - interval '40 minutes', now() - interval '38 minutes', 95, now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"exec_{call_id.hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "valid, created_at, updated_at) VALUES (:id, :tid, :cid, 1, "
                "CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "cid": call_id},
        )

    fired: list[str] = []
    monkeypatch.setattr(
        dispatcher, "alert", lambda stage, code, **kwargs: fired.append(f"{stage}:{code}")
    )

    async def _only_this_tenant() -> list[UUID]:
        return [tenant_id]

    monkeypatch.setattr(dispatcher, "_callable_tenants", _only_this_tenant)

    result = await dispatcher.report_stalled_pipeline({})

    # `unreached=0` is asserted alongside, because a sweep that failed for every tenant
    # would also report zero stalled calls — the two together are what "healthy" means
    # (P6.2).
    assert result == "stalled=0 unreached=0", result
    assert fired == [], "an extracted call is not a stall, and a false page is a lost alarm"
