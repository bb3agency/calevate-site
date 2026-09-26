"""A call whose extraction model never answered has NO outcome, not a `resolved` one.

`extract_call`'s failure ladder returns an `ExtractionOutput` carrying `errors["_model"]`
and the type's defaults — `outcome_tag="resolved"`, `sentiment="neutral"` — so the call, the
lead and the metering survive an outage. Those defaults are not a reading of the call, and
`calls.outcome_tag = 'resolved'` is what the default A/B conversion metric counts
(`agents/models.DEFAULT_CONVERSION_METRIC`) and what the client's own CRM is told on
`call.completed`. An outage must not report every call it touched as resolved.
"""

from __future__ import annotations

from typing import Any

from apps.workers import pipeline
from calevate_shared.extraction import ExtractionOutput
from tests.pipeline_audit_test import (
    _completed_call,
    _outbox_rows,
    _run_pipeline,
    _scalar,
    _stub_storage,
    _subscribe_crm_endpoint,
)

# The recording copy is an environment concern; the stub is `pipeline_audit_test`'s.
_stub_storage = _stub_storage


async def _failing_extract(*args: Any, **kwargs: Any) -> ExtractionOutput:
    return ExtractionOutput(valid=False, errors={"_model": "HTTPStatusError"})


async def test_a_model_failure_records_no_outcome_and_tells_the_crm_none() -> None:
    tenant_id, execution_id, call_id = await _completed_call("nooutcome")
    await _subscribe_crm_endpoint(tenant_id)

    original = pipeline.extract_call
    pipeline.extract_call = _failing_extract  # type: ignore[assignment]
    try:
        await _run_pipeline(tenant_id, call_id, execution_id)
    finally:
        pipeline.extract_call = original  # type: ignore[assignment]

    outcome = await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
    sentiment = await _scalar(tenant_id, "SELECT sentiment FROM calls WHERE id = :c", c=call_id)
    assert outcome is None, "a call nobody analysed was recorded as resolved"
    assert sentiment is None

    (row,) = await _outbox_rows("deliver_outbound_webhook", {"data": {"call_id": str(call_id)}})
    assert row["data"]["outcome"] is None
    assert row["data"]["sentiment"] is None

    # The healthy re-drive repairs the row, and the outcome arrives with it.
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert (
        await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
        is not None
    )
