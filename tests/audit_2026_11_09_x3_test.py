"""Backend audit round 4, lane X3 (workers, jobs and reliability).

X3-01: a CRM delivery's outbox message is the body its retries, "Send again" and the
LeadSquared echo check read after the first run succeeded. `mark_outbox_consumed` used to
blank every payload on success, so through the registered (consumer-wrapped) job a
scheduled retry was sent `{}` and crashed on every claim, and LeadSquared's echo of our own
write was ingested as a new lead.

X3-02: the KYC decision email is keyed on `kyc_records.submitted_at`, which a signatory run
(`record_kyc(status='submitted')`) kept from an earlier, already decided submission, so the
second decision's email was swallowed by the spent key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.compliance.kyc import record_kyc
from apps.api.compliance.kyc_review import decide_kyc_review
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service as integrations_service
from apps.api.reliability.service import KEEP_PAYLOAD_AFTER_RUN_JOBS, mark_outbox_consumed
from apps.workers import outbound_webhooks
from apps.workers.outbound_webhooks import retry_outbound_deliveries
from apps.workers.outbox_consumer import consume_outbox_once
from sqlalchemy import text
from tests.decision_notices_test import _admin_id, _decision_notices, _submitted
from tests.decision_notices_test import _tenant as _kyc_tenant
from tests.lead_source_portals_test import (
    _lead_from_another_source,
    _leads,
    _leadsquared,
    _push,
    _tenant_with_source,
)
from tests.webhook_retry_schedule_test import (
    _answering,
    _capture_enqueue,
    _endpoint,
    _make_due,
    _mine,
    _queued,
    _row,
    _tenant,
)


def test_the_kept_job_is_the_crm_delivery_job() -> None:
    assert frozenset({integrations_service.OUTBOUND_WEBHOOK_JOB}) == KEEP_PAYLOAD_AFTER_RUN_JOBS
    assert outbound_webhooks.JOB_NAME == integrations_service.OUTBOUND_WEBHOOK_JOB


async def test_a_retry_after_the_registered_job_ran_carries_the_whole_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job as the worker registers it: the first attempt schedules its retry and
    returns, the consumer records the success, and the retry still gets the body."""
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    message_id, payload = await _queued(tenant_id, endpoint_id)
    _answering(monkeypatch, 503)
    enqueued = _capture_enqueue(monkeypatch)
    registered = consume_outbox_once(outbound_webhooks.deliver_outbound_webhook)

    outcome = await registered(
        {"job_try": 1, "job_id": f"deliver_outbound_webhook:{message_id}"}, payload
    )
    assert str(outcome).startswith("retry 2 at"), outcome
    await _make_due(payload["delivery_id"])
    await retry_outbound_deliveries({})

    ((again, _job_id),) = _mine(enqueued, payload)
    assert again == {**payload, "attempt": 2}


async def test_a_body_blanked_before_the_fix_ends_the_retry_instead_of_looping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row an earlier release scrubbed to `{}` is not held: the retry ends `failed` and
    "Send again" is refused, rather than a body-less job crashing on every claim."""
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    message_id, payload = await _queued(tenant_id, endpoint_id)
    _answering(monkeypatch, 503)
    enqueued = _capture_enqueue(monkeypatch)
    await outbound_webhooks.deliver_outbound_webhook(
        {"job_try": 1, "job_id": f"deliver_outbound_webhook:{message_id}"}, payload
    )
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE outbox_messages SET payload = '{}'::jsonb WHERE id = :i"),
            {"i": message_id},
        )
    await _make_due(payload["delivery_id"])
    await retry_outbound_deliveries({})

    assert _mine(enqueued, payload) == []
    status, _attempts, _next, _message, reason = await _row(payload["delivery_id"])
    assert (status, reason) == ("failed", "delivery_body_not_held")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await integrations_service.resend_delivery(
                session, delivery_id=uuid.UUID(payload["delivery_id"])
            )
    assert refused.value.code == "delivery_body_not_held"


async def test_leadsquared_echo_is_recognised_after_the_consumer_recorded_the_delivery() -> None:
    tenant_id, agent_id, webhook_id = await _tenant_with_source("leadsquared")
    await _lead_from_another_source(tenant_id, agent_id, "+919876507811", sent_to_leadsquared=True)
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM outbox_messages WHERE job = :job AND payload->>'tenant_id' = :t"
                ),
                {"job": integrations_service.OUTBOUND_WEBHOOK_JOB, "t": str(tenant_id)},
            )
        ).all()
        assert len(rows) == 1
        await session.execute(
            text("UPDATE outbox_messages SET status = 'published' WHERE id = :i"),
            {"i": rows[0][0]},
        )
        await mark_outbox_consumed(
            session, message_id=rows[0][0], job=integrations_service.OUTBOUND_WEBHOOK_JOB
        )

    echo = await _push(webhook_id, _leadsquared(phone="9876507811"))
    assert echo.json()["duplicate"] == 1, echo.text
    assert len(await _leads(tenant_id)) == 1


async def test_other_jobs_still_forget_their_payload_on_success() -> None:
    message_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "created_at, updated_at) VALUES (:i, 'default', 'notify_hot_lead', "
                "CAST(:p AS jsonb), 'published', 1, :at, :at)"
            ),
            {
                "i": message_id,
                "p": '{"tenant_id": "x", "phone": "+919800000000"}',
                "at": datetime.now(UTC) - timedelta(seconds=1),
            },
        )
        await mark_outbox_consumed(session, message_id=message_id, job="notify_hot_lead")
        payload: Any = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE id = :i"), {"i": message_id}
            )
        ).scalar_one()
    assert payload == {}


@pytest.mark.rls
async def test_a_signatory_run_after_a_rejection_is_told_its_own_decision() -> None:
    tenant_id, _slug = await _kyc_tenant()
    await _submitted(tenant_id, at=datetime.now(UTC) - timedelta(days=2))
    admin_id = await _admin_id()
    async with tenant_session(tenant_id) as session:
        await decide_kyc_review(
            session,
            tenant_id=tenant_id,
            decision="reject",
            document_ref=None,
            reason="The name on the PAN card does not match the owner name you gave.",
            pan_checked=False,
            admin_id=admin_id,
        )
    # The client then verifies its signatory through the aggregator, which moves the
    # record back to review through `record_kyc` (`kyc_verification.apply_outcome`).
    async with tenant_session(tenant_id) as session:
        await record_kyc(
            session,
            tenant_id=tenant_id,
            status="submitted",
            entity_type="llp",
            verification_source="aggregator",
            verification_provider="fake",
            verification_reference=f"run-{uuid.uuid4().hex[:8]}",
            verified_name="Ravi Kumar",
        )
        await decide_kyc_review(
            session,
            tenant_id=tenant_id,
            decision="reject",
            document_ref=None,
            reason="The business registry entry names a different partner.",
            pan_checked=False,
            admin_id=admin_id,
        )
    assert await _decision_notices(tenant_id) == ["reject", "reject"]
