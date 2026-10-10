"""Edges of the D-697/D-699 money paths that no flow test reaches: an unreadable capture,
the attested-rate filter, a payment after a trial that ended unsold, the trial-minutes bound
and the operator's smoke-call route."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import engine_minutes, payment_events, trial_routes
from apps.api.billing.first_payment import on_payment_credited
from apps.api.billing.trials import TRIAL_STOPPED, end_trial, read_trial, start_trial
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from fastapi import Request

pytestmark = [pytest.mark.rls]


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Edge Clinic",
        slug=f"edge-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def test_a_capture_that_is_not_an_object_credits_nothing() -> None:
    with pytest.raises(ProblemError) as refused:
        await payment_events.apply_captured(
            "not an object", event="payment.captured", event_id=None
        )
    assert refused.value.code == "payment_payload_unrecognized"


async def test_only_attested_rate_keys_may_be_sold(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _prices(_session: Any, *, engine: str, at: datetime) -> dict[str, Any]:
        assert engine == "thinnest"
        return {"platform": object(), "byok_voice": object()}

    monkeypatch.setattr(engine_minutes, "attested_minute_prices", _prices)
    keys = await engine_minutes.attested_rate_keys(
        None,  # type: ignore[arg-type]
        engine="thinnest",
        at=datetime.now(UTC),
    )
    assert keys == frozenset({"platform", "byok_voice"})
    with pytest.raises(ProblemError) as unknown:
        await engine_minutes.attested_rate_keys(
            None,  # type: ignore[arg-type]
            engine="pipecat",
            at=datetime.now(UTC),
        )
    assert unknown.value.code == "engine_minute_price_unknown_engine"


async def test_a_first_payment_after_an_unsold_trial_cancels_the_scheduled_erasure() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
        await end_trial(session, tenant_id=tenant_id, outcome=TRIAL_STOPPED, reason="test")
        stopped = await read_trial(session, tenant_id=tenant_id)
    assert stopped is not None and stopped.erase_after is not None

    async with tenant_session(tenant_id) as session:
        first = await on_payment_credited(
            session, tenant_id=tenant_id, amount_inr=Decimal("500.00"), via="manual_topup"
        )
        trial = await read_trial(session, tenant_id=tenant_id)
    assert first is True
    assert trial is not None
    assert trial.status == TRIAL_STOPPED, "the trial's own outcome stands"
    assert trial.erase_after is None, "a client who bought keeps what they built"


async def test_a_trial_with_free_minutes_out_of_range_is_refused() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await start_trial(
                session, tenant_id=tenant_id, days=14, actor_user_id=None, free_minutes=0
            )
    assert refused.value.code == "invalid_trial_minutes"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/admin/tenants/x/trial/test-call",
            "headers": [],
            "query_string": b"",
            "client": ("203.0.113.7", 1234),
        }
    )


async def test_the_smoke_call_needs_an_idempotency_key_then_runs_the_clients_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    operator = Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="operator")
    payload = trial_routes.TrialSmokeCallIn(agent_id=uuid.uuid4(), number="9876543210")
    with pytest.raises(ProblemError) as missing:
        await trial_routes.smoke_trial_call(tenant_id, payload, _request(), operator, None)
    assert missing.value.code == "idempotency_key_required"
    assert missing.value.status == 400

    monkeypatch.setattr(get_settings(), "trial_caller_number", None)
    out = await trial_routes.smoke_trial_call(
        tenant_id, payload, _request(), operator, str(uuid.uuid4())
    )
    assert out.status == "blocked"
    assert out.blocked_rule == "trial_calling_not_ready"
    assert out.call_handle is None
