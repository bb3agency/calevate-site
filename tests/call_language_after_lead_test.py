"""The lead first, the English after (D-931, founder 29 Oct 2026).

Most calls are in Telugu. The language pass (up to `LANGUAGE_PASS_BUDGET_S`) used to run
inside STEP 3d, before the lead, the minutes and the alerts. It now runs as its own job
queued by STEP 10, and everything a client waits on is committed without it. What is
pinned: the order; the outcome and the hot-lead decision read nothing the pass writes; the
English, when it lands, reaches the screen through the live note and the client's CRM
through `call.updated`; the job is keyed per call, retried on its ladder, and its last
failure leaves the call's own summary standing with a quiet `attention` alarm.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.crm import service as crm
from apps.api.db.session import tenant_session
from apps.api.integrations import service as integrations
from apps.workers import call_language, call_translation, pipeline
from apps.workers.call_language import LanguagePass
from sqlalchemy import text
from tests.live_updates_test import captured as captured
from tests.pipeline_audit_test import _completed_call, _outbox_rows, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage
from tests.post_call_truth_test import _with_engine_summary
from tests.postcall_crm_events_test import BROWSING, READY, give_agent_outcomes, reads_as, subscribe

TELUGU_SUMMARY = "కాలర్ పచ్చి మిర్చి కావాలి అన్నారు. రేపు కాల్ చేయమన్నారు."
ENGLISH = "The caller wants green chilli. They asked to be called back tomorrow."


def _provider(monkeypatch: pytest.MonkeyPatch, key: str | None = "k") -> None:
    monkeypatch.setattr(
        call_translation, "get_settings", lambda: SimpleNamespace(sarvam_api_key=key)
    )


async def _queued(call_id: UUID) -> list[dict[str, Any]]:
    return await _outbox_rows(call_translation.JOB_NAME, {"call_id": str(call_id)})


async def _run_queued(call_id: UUID, *, attempt: int = 1) -> str:
    (payload,) = await _queued(call_id)
    return await call_translation.translate_call_job({"job_try": attempt}, payload)


def _forbid_pass_inside_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _never(**_kwargs: Any) -> LanguagePass:
        raise AssertionError("the language pass ran inside the post-call pipeline")

    monkeypatch.setattr(call_language, "run_language_pass", _never)


async def test_the_lead_is_saved_before_the_language_pass_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: STEP 3d runs the pass again, or STEP 10 queues it before the lead."""
    _with_engine_summary(monkeypatch, "The caller wants a callback about chilli.")
    _provider(monkeypatch)
    _forbid_pass_inside_pipeline(monkeypatch)
    tenant_id, execution_id, call_id = await _completed_call("lead_first")

    await _run_pipeline(tenant_id, call_id, execution_id)

    assert await _scalar(tenant_id, "SELECT lead_id FROM calls WHERE id = :c", c=call_id)
    assert await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
    assert (
        await _scalar(tenant_id, "SELECT translation_state FROM calls WHERE id = :c", c=call_id)
        == "pending"
    )
    queued = await _queued(call_id)
    assert [q["payer"] for q in queued] == ["pipeline"]
    assert pipeline.LANGUAGE_PASS_JOB == call_translation.JOB_NAME

    seen: dict[str, Any] = {}

    async def _pass(**kwargs: Any) -> LanguagePass:
        async with tenant_session(tenant_id) as session:
            seen["lead"] = (
                await session.execute(
                    text("SELECT lead_id FROM calls WHERE id = :c"), {"c": call_id}
                )
            ).scalar()
        seen.update(kwargs)
        return LanguagePass(
            turns_en={idx: f"english {idx}" for idx, _ in kwargs["turns"]},
            summary_local=TELUGU_SUMMARY,
        )

    monkeypatch.setattr(call_language, "run_language_pass", _pass)
    assert await _run_queued(call_id) == "ready"

    assert seen["lead"] is not None, "the lead was written before the pass ran"
    assert all("9876543210" not in body for _, body in seen["turns"]), "redacted text only"
    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    assert detail.translation_state == "ready"
    assert detail.transcript and all(t.text_en for t in detail.transcript)
    assert detail.summary_local == TELUGU_SUMMARY and detail.summary_language == "te-IN"

    # A re-drive owing nothing queues nothing and pays for nothing.
    _forbid_pass_inside_pipeline(monkeypatch)
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert len(await _queued(call_id)) == 1


async def test_the_outcome_and_the_hot_lead_need_no_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The business outcome, the lead's move to hot and its alert are all decided from the
    extraction, before any English exists."""
    _with_engine_summary(monkeypatch, TELUGU_SUMMARY)
    _forbid_pass_inside_pipeline(monkeypatch)
    tenant_id, execution_id, call_id = await _completed_call("hot_untranslated")
    await give_agent_outcomes(tenant_id, [READY, BROWSING])
    reads_as(monkeypatch, "ready_to_buy")

    await _run_pipeline(tenant_id, call_id, execution_id)

    assert (
        await _scalar(tenant_id, "SELECT business_outcome FROM calls WHERE id = :c", c=call_id)
        == "ready_to_buy"
    )
    assert (
        await _scalar(
            tenant_id,
            "SELECT l.status FROM calls c JOIN leads l ON l.id = c.lead_id WHERE c.id = :c",
            c=call_id,
        )
        == "hot"
    )
    assert len(await _outbox_rows("notify_hot_lead", {"call_id": str(call_id)})) == 1
    assert await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
    assert len(await _queued(call_id)) == 1, "the English is still owed, after all of it"


async def test_the_english_summary_fills_in_live_and_the_crm_hears_it_once(
    monkeypatch: pytest.MonkeyPatch, captured: list[tuple[UUID | None, frozenset[str]]]
) -> None:
    """The engine wrote Telugu and the model wrote no summary: `call.completed` goes out
    with the lead and the outcome and no summary, the screen shows the Telugu with
    "Translating…", and the English then lands on the screen (the `calls` live note) and in
    the CRM as one `call.updated`."""
    _with_engine_summary(monkeypatch, TELUGU_SUMMARY)
    _provider(monkeypatch)
    _forbid_pass_inside_pipeline(monkeypatch)
    tenant_id, execution_id, call_id = await _completed_call("fill_in")
    await subscribe(tenant_id, [integrations.CALL_COMPLETED_EVENT, integrations.CALL_UPDATED_EVENT])

    await _run_pipeline(tenant_id, call_id, execution_id)

    async with tenant_session(tenant_id) as session:
        before = await crm.get_call(session, call_id)
    assert before.summary is None and before.summary_local == TELUGU_SUMMARY
    assert before.summary_state == "ready" and before.translation_state == "pending"
    completed = await _outbox_rows(
        "deliver_outbound_webhook", {"event": "call.completed", "data": {"call_id": str(call_id)}}
    )
    assert [c["data"]["summary"] for c in completed] == [None]

    async def _pass(**kwargs: Any) -> LanguagePass:
        assert kwargs["summary_local"] and not kwargs["summary_en"]
        return LanguagePass(
            turns_en={idx: f"english {idx}" for idx, _ in kwargs["turns"]}, summary_en=ENGLISH
        )

    monkeypatch.setattr(call_language, "run_language_pass", _pass)
    captured.clear()
    assert await _run_queued(call_id) == "ready"

    async with tenant_session(tenant_id) as session:
        after = await crm.get_call(session, call_id)
    assert after.summary == ENGLISH and after.summary_local == TELUGU_SUMMARY
    assert any(tenant == tenant_id and "calls" in topics for tenant, topics in captured)
    updated = await _outbox_rows(
        "deliver_outbound_webhook", {"event": "call.updated", "data": {"call_id": str(call_id)}}
    )
    assert [u["data"]["summary"] for u in updated] == [ENGLISH]
    assert set(updated[0]["data"]) == set(integrations.CALL_EVENT_COLUMNS)
    assert updated[0]["data"]["outcome"] == completed[0]["data"]["outcome"]
    assert updated[0]["data"]["lead_id"] == completed[0]["data"]["lead_id"]
    headline = await _scalar(tenant_id, "SELECT headline FROM calls WHERE id = :c", c=call_id)
    assert headline == "The caller wants green chilli."

    # A second delivery of the job does nothing, and tells the CRM nothing twice.
    assert await _run_queued(call_id) == "skipped"
    assert (
        len(
            await _outbox_rows(
                "deliver_outbound_webhook",
                {"event": "call.updated", "data": {"call_id": str(call_id)}},
            )
        )
        == 1
    )


async def test_a_provider_failure_is_retried_on_the_ladder_then_left_quietly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_engine_summary(monkeypatch, TELUGU_SUMMARY)
    _provider(monkeypatch)
    _forbid_pass_inside_pipeline(monkeypatch)
    tenant_id, execution_id, call_id = await _completed_call("pass_fails")
    await _run_pipeline(tenant_id, call_id, execution_id)

    tries: list[int] = []

    async def _fails(**kwargs: Any) -> LanguagePass:
        tries.append(len(kwargs["turns"]))
        return LanguagePass(failed=True)

    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(call_language, "run_language_pass", _fails)
    monkeypatch.setattr(
        call_translation, "alert", lambda stage, code, **_kw: fired.append((stage, code))
    )
    for attempt in (1, 2):
        with pytest.raises(call_translation.Retry):
            await _run_queued(call_id, attempt=attempt)
        assert (
            await _scalar(tenant_id, "SELECT translation_state FROM calls WHERE id = :c", c=call_id)
            == "pending"
        ), "still on its way between tries"
    assert fired == []
    assert await _run_queued(call_id, attempt=3) == "failed"

    assert len(tries) == 3
    assert fired == [("WORKER_DELIVERY", "call_language_pass_exhausted")]
    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    assert detail.translation_state == "failed"
    assert detail.summary_local == TELUGU_SUMMARY and detail.summary_state == "ready"


async def test_a_romanised_summary_stands_until_the_pass_writes_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The romanised summary is shown as the call's own words at once, sent to the pass as
    the source of both, and replaced by the real two; if the pass cannot write them it
    stands in the English slot, as it did before D-931."""
    romanised = (
        "Customer Badangpet lo 5-bedroom house kavali ani, budget 45 lakhs undi ani chepparu."
    )
    telugu = "కస్టమర్ బడంగ్‌పేట్ లో ఇల్లు కావాలి అన్నారు."
    english = "The caller wants a 5-bedroom house in Badangpet."
    _with_engine_summary(monkeypatch, romanised)
    _provider(monkeypatch)
    _forbid_pass_inside_pipeline(monkeypatch)
    tenant_id, execution_id, call_id = await _completed_call("romanised_first")
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert await _scalar(tenant_id, "SELECT summary_local FROM calls WHERE id = :c", c=call_id) == (
        romanised
    )
    assert await _scalar(tenant_id, "SELECT summary FROM calls WHERE id = :c", c=call_id) is None

    seen: dict[str, Any] = {}

    async def _pass(**kwargs: Any) -> LanguagePass:
        seen.update(kwargs)
        return LanguagePass(summary_en=english, summary_local=telugu)

    monkeypatch.setattr(call_language, "run_language_pass", _pass)
    assert await _run_queued(call_id) in ("ready", "not_needed")
    assert seen["summary_romanised"] == romanised
    assert seen["summary_en"] == "" and seen["summary_local"] == ""
    assert await _scalar(tenant_id, "SELECT summary FROM calls WHERE id = :c", c=call_id) == english
    assert await _scalar(tenant_id, "SELECT summary_local FROM calls WHERE id = :c", c=call_id) == (
        telugu
    )


async def test_a_romanised_summary_the_pass_could_not_rewrite_stays_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    romanised = (
        "Customer Badangpet lo 5-bedroom house kavali ani, budget 45 lakhs undi ani chepparu."
    )
    _with_engine_summary(monkeypatch, romanised)
    _provider(monkeypatch, key=None)
    _forbid_pass_inside_pipeline(monkeypatch)
    tenant_id, execution_id, call_id = await _completed_call("romanised_kept")
    await _run_pipeline(tenant_id, call_id, execution_id)

    assert await _run_queued(call_id) == "failed"
    assert await _scalar(tenant_id, "SELECT summary FROM calls WHERE id = :c", c=call_id) == (
        romanised
    )
    assert await _scalar(tenant_id, "SELECT summary_local FROM calls WHERE id = :c", c=call_id) is (
        None
    )
    assert await _scalar(tenant_id, "SELECT headline FROM calls WHERE id = :c", c=call_id)
