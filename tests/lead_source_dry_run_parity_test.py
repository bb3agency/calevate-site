"""The lead-source dry run must refuse whatever the real delivery path refuses.

`POST /v1/lead-sources/{id}/test` promises "everything the real path would decide". It
answered `would_call: true` for a Meta Lead Ads source with no consent question, which
the real Meta receiver (`require_form_consent=True`) saves and never dials.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session
from apps.api.ingest.routes import META_SOURCE
from sqlalchemy import text
from tests.lead_ingest_test import _tenant_with_ingest


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the gate's calling-hours rule is not what this file measures."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _dry_run(tenant_id: UUID, webhook_id: UUID) -> object:
    # Imported here: at module level pytest would try to collect both `Test*`/`test_*`.
    from apps.api.ingest.routes import TestWebhookIn, test_webhook

    principal = Principal(
        realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner", impersonating=False
    )
    async with tenant_session(tenant_id) as session:
        return await test_webhook(
            webhook_id,
            TestWebhookIn(payload={"phone": "9876509993", "name": "Preview"}),
            session,
            principal,
        )


async def test_a_meta_source_without_a_consent_question_is_reported_as_never_calling() -> None:
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(
        mapping={"phone": "phone", "name": "name"}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_webhooks SET source = :s WHERE id = :i"),
            {"s": META_SOURCE, "i": webhook_id},
        )
    result = await _dry_run(tenant_id, webhook_id)
    assert result.would_call is False  # type: ignore[attr-defined]
    consent = next(s for s in result.steps if s.step == "form_consent")  # type: ignore[attr-defined]
    assert consent.ok is False


async def test_a_published_shared_secret_source_still_previews_a_call() -> None:
    """The control: the refusal does not fire where the real path would dial."""
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(
        mapping={"phone": "phone", "name": "name"}
    )
    result = await _dry_run(tenant_id, webhook_id)
    assert result.would_call is True  # type: ignore[attr-defined]
