"""Background jobs that wedged, re-sent or lost a tick (backend audit lane T3, 8 Nov 2026).

Each test fails on the tree before its fix:

1. The monthly number meter fired only on the 1st, and arq never runs a missed cron tick.
2. "Read it again" on a scanned PDF had no overall model budget, so it outran the job limit
   and the row stayed `reading`; a reading killed outright was never settled.
3. A teach-question draft whose run died kept the question "being drafted" for ever.
4. One failing healer notice rolled back the stamps of notices already sent, so the owner
   was sent them again every minute with no alarm.
5. A re-run of the weekly knowledge digest re-mailed every agent it had reached.
6. A business-outcomes draft that died before its claim stayed `queued` for good.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import call_outcomes
from apps.api.db.session import tenant_session
from apps.api.healer import ledger, protection
from apps.workers import document_ocr, healer, interrupted_work, kb_aggregation, kb_read
from apps.workers.settings import CRON_JOBS
from calevate_shared.document_ingest import ExtractedText
from sqlalchemy import text
from tests.conftest import FakeS3, create_org_with_receptionist
from tests.healer_flow_test import _incident, _notice_state, _org
from tests.kb_read_copy_test import PRICE_PAGE, _pdf, _pdf_upload, _upload_row
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.teach_questions_test import _list
from tests.teach_questions_test import _tenant as _teach_tenant

# --- 1. the number meter ----------------------------------------------------------------


def test_the_number_meter_runs_every_day_so_a_missed_first_is_caught_up() -> None:
    job = next(j for j in CRON_JOBS if j.name == "cron:meter_number_rentals")
    assert job.day is None, "a cron tick missed on the 1st is never run by arq"
    assert (job.hour, job.minute) == ({7}, {28})


# --- 2. reading a scanned PDF again -----------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_scanned_pages_stop_at_the_reading_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    asked: list[int] = []

    async def _slow_page(images: Any, **_: Any) -> ExtractedText:
        asked.append(images[0].position)
        clock.now += document_ocr.OCR_TIMEOUT_S
        return ExtractedText(
            text=f"page {images[0].position}",
            kind="image",
            provenance="ocr",
            unit_count=1,
            unit_name="images",
            needs_confirmation=True,
        )

    monkeypatch.setattr(kb_read, "_clock", clock)
    monkeypatch.setattr(document_ocr, "ocr_images", _slow_page)
    scans = [(n, b"x", "image/png") for n in range(1, 21)]
    reading = await kb_read._read_scans(
        None,  # type: ignore[arg-type]  # nothing is metered: the fake reports no model
        tenant_id=uuid.uuid4(),
        scans=scans,
        deadline=100.0,
    )
    # 0 -> 45 -> 90; a third page would end at 135, past the budget.
    assert asked == [1, 2]
    assert [n for n, _ in reading.pages] == [1, 2]
    assert reading.missed == 18
    assert kb_read.READ_MODEL_BUDGET_S + kb_read.MAX_PDF_READ_S < 300


async def test_picture_retries_one_at_a_time_are_held_to_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    requests: list[int] = []

    async def _read_batch(_leg: Any, batch: Any, _http: Any) -> tuple[Any, Any, str]:
        requests.append(len(batch))
        clock.now += document_ocr.OCR_TIMEOUT_S
        if len(batch) > 1:
            return None, None, "provider_rejected_400"
        return [document_ocr.PictureText(batch[0].position, "words", None)], None, ""

    monkeypatch.setattr(document_ocr, "time", SimpleNamespace(monotonic=clock))
    monkeypatch.setattr(document_ocr, "ocr_leg", lambda: object())
    monkeypatch.setattr(document_ocr, "_read_batch", _read_batch)
    images = [
        document_ocr.OcrImage(data=b"x", mime_type="image/png", position=n) for n in (1, 2, 3, 4)
    ]
    out = await document_ocr.ocr_pictures(images, deadline_s=60.0)
    # The batch at 0, one picture alone at 45; at 90 the deadline has passed.
    assert requests == [4, 1]
    assert [p.reason for p in out.pictures] == [
        None,
        "not_attempted",
        "not_attempted",
        "not_attempted",
    ]


async def test_a_reading_left_reading_is_settled_by_the_interrupted_work_sweep(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    stale = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE), name="Old menu")
    live = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE), name="New menu")
    async with tenant_session(tenant_id) as session:
        for row, age in ((stale, timedelta(hours=1)), (live, timedelta(minutes=1))):
            await session.execute(
                text(
                    "UPDATE kb_uploads SET read_state = 'reading', updated_at = :at WHERE id = :id"
                ),
                {"at": datetime.now(UTC) - age, "id": row["id"]},
            )

    async def _only(_now: datetime) -> list[UUID]:
        return [tenant_id]

    monkeypatch.setattr(interrupted_work, "tenants_with_recent_work", _only)
    outcome = await interrupted_work.end_interrupted_work({})
    assert outcome.endswith("readings=1")
    assert (await _upload_row(tenant_id, stale["id"]))["read_state"] in ("ready", "failed")
    assert (await _upload_row(tenant_id, live["id"]))["read_state"] == "reading"


# --- 3. a teach-question draft that died ------------------------------------------------


async def test_a_draft_queued_past_the_window_is_no_longer_shown_as_drafting() -> None:
    tenant_id, _agent_id, _ = await _teach_tenant()
    first = await _list(tenant_id, queue_drafts=True)
    assert first.items and all(q.drafting for q in first.items)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE teach_questions SET updated_at = now() - make_interval(mins => :m) "
                "WHERE draft_status = 'queued'"
            ),
            {"m": 16},
        )
    again = await _list(tenant_id, queue_drafts=True)
    assert again.items and not any(q.drafting for q in again.items)


# --- 4. the healer's client notices -----------------------------------------------------


async def _loud_notice(tenant_id: UUID, agent_id: UUID) -> UUID:
    incident_id = await _incident(tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        row_id = await protection.client_incident(
            session,
            tenant_id=tenant_id,
            incident_id=incident_id,
            agent_id=agent_id,
            kind="line_protected",
        )
        await session.execute(
            text(
                "UPDATE heal_client_incidents SET protection = 'forwarded', "
                "opened_at = now() - interval '2 hours' WHERE id = :id"
            ),
            {"id": row_id},
        )
    return row_id


async def test_one_failing_notice_keeps_the_stamps_of_those_already_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _ = await _org("notice-row")
    first = await _loud_notice(tenant_id, agent_id)
    second = await _loud_notice(tenant_id, agent_id)
    real = ledger.record
    calls = 0

    async def _second_fails(session: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("ledger write failed")
        return await real(session, **kwargs)

    monkeypatch.setattr(ledger, "record", _second_fails)
    failures: Counter[str] = Counter()
    assert await healer._notify_tenant(tenant_id, failures) == 1
    assert failures["notice_row_failed"] == 1
    stamped = [(await _notice_state(row, tenant_id))[0] is not None for row in (first, second)]
    assert sorted(stamped) == [False, True], "the delivered notice keeps its stamp"


async def test_a_notice_failure_reaches_the_healer_step_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _tenants_fail(tenant_id: UUID, failures: Any = None) -> int:
        raise RuntimeError("down")

    async def _one_tenant(*_: Any, **__: Any) -> Any:
        class _Rows:
            def all(self) -> list[tuple[str]]:
                return [(str(uuid.uuid4()),)]

        return _Rows()

    class _Session:
        execute = staticmethod(_one_tenant)

        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

    monkeypatch.setattr(healer, "untenanted_session", _Session)
    monkeypatch.setattr(healer, "_notify_tenant", _tenants_fail)
    tally: Counter[str] = Counter()
    with pytest.raises(healer.NoticeDeliveryError):
        await healer._deliver_client_notices(tally)
    assert tally["notice_failed"] == 1


# --- 5. the weekly knowledge digest -----------------------------------------------------


async def test_a_digest_re_run_in_the_same_week_does_not_mail_the_agent_again() -> None:
    agent_id = uuid.uuid4()
    week = datetime(2026, 11, 2, tzinfo=UTC)
    assert await kb_aggregation._claim_week(agent_id, week)
    assert not await kb_aggregation._claim_week(agent_id, week)
    await kb_aggregation._release_week(agent_id, week)
    assert await kb_aggregation._claim_week(agent_id, week), "a failed send is sent again"
    assert await kb_aggregation._claim_week(agent_id, week + timedelta(days=7))


# --- 6. a business-outcomes draft that never ran ----------------------------------------


async def test_a_draft_queued_past_the_window_can_be_asked_for_again() -> None:
    created = await create_org_with_receptionist(
        name="Outcomes Shop",
        slug=f"t3-out-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET business_outcomes = NULL, business_outcomes_draft = 'queued' "
                "WHERE id = :a"
            ),
            {"a": agent_id},
        )
        assert not await call_outcomes.request_draft(
            session, tenant_id=tenant_id, agent_id=agent_id
        ), "a fresh queued draft is not queued twice"
        await session.execute(
            text("UPDATE agents SET updated_at = now() - make_interval(mins => :m) WHERE id = :a"),
            {"a": agent_id, "m": call_outcomes.DRAFT_STALE_MINUTES + 1},
        )
        assert await call_outcomes.request_draft(session, tenant_id=tenant_id, agent_id=agent_id)
