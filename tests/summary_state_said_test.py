"""A call whose words reached us is never stored as one where nothing was said.

`summary_state = 'empty'` is what the Call logs row reads as "Nothing was said on this
call". A reading that came back with no summary over a call that has turns used to be
stored `empty`, so the row said nothing was said above a call with a conversation.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.workers import pipeline
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage


async def test_a_call_with_turns_and_no_summary_is_not_stored_as_nothing_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = pipeline.post_call_truth

    async def _no_engine_summary(*args: Any, **kwargs: Any) -> Any:
        snapshot = await original(*args, **kwargs)
        return snapshot.model_copy(update={"engine_summary": None})

    monkeypatch.setattr(pipeline, "post_call_truth", _no_engine_summary)
    tenant_id, execution_id, call_id = await _completed_call("said")

    await _run_pipeline(tenant_id, call_id, execution_id)

    turns = await _scalar(
        tenant_id, "SELECT count(*) FROM transcript_turns WHERE call_id = :c", c=call_id
    )
    summary = await _scalar(tenant_id, "SELECT summary FROM calls WHERE id = :c", c=call_id)
    assert turns > 0 and not summary, "the premise: words, and no summary written"
    assert (
        await _scalar(tenant_id, "SELECT summary_state FROM calls WHERE id = :c", c=call_id)
        == "failed"
    )
