"""Post-call truth (first-call review 10 Oct 2026, F-4..F-7; founder decisions 1, 4-8, 12).

The live call that produced these: a caller asked for a call back in Telugu script, the
agent booked one, and the call read "Resolved", its summary was the agent's last words, the
lead was a "campaign" lead, and the trial account's call back sat "Waiting" for two hours.
Each test below pins one of those as fixed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.compliance.trial_access import (
    TRIAL_CALLBACK_REASON,
    TRIAL_CALLBACK_RULE,
)
from apps.api.core.errors import ProblemError
from apps.api.crm import service as crm
from apps.api.crm.outcomes import CallFacts, derive_outcome, hint_of, normalise
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import call_language, pipeline
from apps.workers.call_language import LanguagePass
from apps.workers.extraction import OfflineExtractor, extract_call
from apps.workers.pipeline import _settle_summaries, after_call_status
from calevate_shared.extraction import (
    ExtractionOutput,
    ExtractionSchemaSpec,
    clip_headline,
)
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar

# The recording copy is an environment concern; the stub is `pipeline_audit_test`'s.
from tests.pipeline_audit_test import _stub_storage as _stub_storage

TELUGU_CALL_BACK = "కాల్ బ్యాక్"
TELUGU_SUMMARY = "కాలర్ చిల్లీ"


def _facts(**overrides: Any) -> CallFacts:
    base: dict[str, Any] = {
        "status": "completed",
        "duration_s": 64,
        "caller_turns": 5,
        "callback_booked": False,
        "handoff_outcome": None,
        "hint": "answered",
        "callback_requested": False,
        "out_of_scope": False,
    }
    base.update(overrides)
    return CallFacts(**base)


# --- 1. the outcome is derived from facts ---------------------------------------------


def test_a_booked_call_back_always_reads_as_one() -> None:
    """F-4: the model said `answered`; the row says a call back was booked. The row wins."""
    assert derive_outcome(_facts(callback_booked=True)) == "call_back_booked"
    assert derive_outcome(_facts(callback_booked=True, hint="needs_you")) == "call_back_booked"
    assert (
        derive_outcome(_facts(callback_booked=True, handoff_outcome="connected"))
        == "call_back_booked"
    )


def test_the_precedence_of_the_other_facts() -> None:
    assert derive_outcome(_facts(status="no_answer", callback_booked=True)) == "missed"
    assert derive_outcome(_facts(handoff_outcome="connected")) == "transferred"
    assert derive_outcome(_facts(handoff_outcome="unreached")) == "needs_you"
    assert derive_outcome(_facts(duration_s=9, caller_turns=1)) == "hung_up_early"
    assert derive_outcome(_facts(callback_requested=True)) == "needs_you"
    assert derive_outcome(_facts(out_of_scope=True)) == "needs_you"
    # A transfer the model imagined is not one we hold: the caller is still owed a person.
    assert derive_outcome(_facts(hint="transferred")) == "needs_you"
    assert derive_outcome(_facts()) == "answered"


def test_nothing_is_ever_defaulted_to_a_verdict() -> None:
    """No model reading and no fact that decides: unknown, never `resolved`/`answered`."""
    assert derive_outcome(_facts(hint=None)) is None


def test_the_stored_legacy_words_read_as_the_new_ones() -> None:
    assert normalise("resolved") == "answered"
    assert normalise("needs_follow_up") == "needs_you"
    assert normalise("dropped") == "hung_up_early"
    assert normalise("transferred") == "transferred"
    assert normalise("call_back_booked") == "call_back_booked"
    assert normalise(None) is None and normalise("nonsense") is None
    assert hint_of("NEEDS_YOU") == "needs_you" and hint_of("resolved") == "answered"
    assert hint_of("call_back_booked") is None, "the model cannot claim a booking"


# --- 2. the extractors -------------------------------------------------------------------

SPEC = ExtractionSchemaSpec(fields=[])


async def test_the_offline_runner_hears_a_call_back_asked_for_in_telugu_script() -> None:
    """F-4: "ఆ కాల్ బ్యాక్ చేయండి అండి" was missed because only Latin letters counted."""
    transcript = (
        f"agent: మీకు call back చేయించమంటారా?\ncaller: ఆ {TELUGU_CALL_BACK} చేయండి అండి\nagent: ధన్యవాదాలు అండి"
    )
    result = await OfflineExtractor().run(SPEC, transcript)
    assert result["callback_requested"] is True
    assert result["outcome_tag"] == "needs_you"
    # F-6: never the last line of the transcript as a summary.
    assert result["summary"] == "" and result["headline"] == ""


async def test_the_offline_runner_hears_hindi_script_too() -> None:
    result = await OfflineExtractor().run(SPEC, "caller: मुझे वापस कॉल करना")
    assert result["callback_requested"] is True


class _Writes:
    model_name = "stub"

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return self.raw


async def test_a_model_copying_a_transcript_line_gets_no_summary_and_no_verdict() -> None:
    out = await extract_call(
        SPEC,
        "caller: hello",
        extractor=_Writes(
            {
                "summary": "agent: thank you sir",
                "headline": "caller: hello",
                "outcome_tag": "resolved-ish",
            }
        ),
    )
    assert out.summary == "" and out.headline == ""
    assert out.outcome_tag is None


async def test_the_headline_is_one_line_of_at_most_ninety_characters() -> None:
    out = await extract_call(
        SPEC,
        "caller: hello",
        extractor=_Writes({"headline": "word " * 40, "outcome_tag": "needs_you"}),
    )
    assert len(out.headline) <= 90 and "\n" not in out.headline
    assert clip_headline("short line") == "short line"


# --- 3. which summary is which ---------------------------------------------------------


def test_the_engine_summary_comes_first_and_its_script_says_which_one_it_is() -> None:
    english, local, source = _settle_summaries(
        engine_summary="Caller asked about chilli; call back booked.",
        model_summary="Model words.",
        stored_local="",
        language="te-IN",
    )
    assert (english, local, source) == (
        "Caller asked about chilli; call back booked.",
        "",
        "engine",
    )

    english, local, source = _settle_summaries(
        engine_summary=TELUGU_SUMMARY,
        model_summary="Asked about chilli.",
        stored_local="",
        language="te-IN",
    )
    assert (english, local, source) == ("Asked about chilli.", TELUGU_SUMMARY, "extraction")

    # An English call has one summary.
    _, local, _ = _settle_summaries(
        engine_summary=TELUGU_SUMMARY, model_summary="", stored_local="", language="en-IN"
    )
    assert local == ""


def test_the_call_language_is_read_from_the_script() -> None:
    assert call_language.call_language([TELUGU_SUMMARY], agent_language="hi-IN") == "te-IN"
    assert call_language.call_language(["hello there"], agent_language="te-IN") == "te-IN"
    assert call_language.call_language(["मुझे"], agent_language="mr-IN") == "mr-IN"
    assert call_language.is_english("en-IN") and not call_language.is_english("te-IN")


# --- 4. lead status rules ----------------------------------------------------------------


def test_lead_status_moves_by_rules() -> None:
    assert (
        after_call_status(
            outcome="call_back_booked", connected=True, callback_requested=False, sentiment=None
        )
        == "interested"
    )
    assert (
        after_call_status(
            outcome="answered", connected=True, callback_requested=False, sentiment="neutral"
        )
        == "contacted"
    )
    assert (
        after_call_status(
            outcome="missed", connected=False, callback_requested=False, sentiment=None
        )
        is None
    )


# --- 5. the pipeline, end to end --------------------------------------------------------


def _with_engine_summary(monkeypatch: pytest.MonkeyPatch, summary: str | None) -> None:
    original = pipeline.post_call_truth

    async def _truth(*args: Any, **kwargs: Any) -> Any:
        snapshot = await original(*args, **kwargs)
        return snapshot.model_copy(update={"engine_summary": summary})

    monkeypatch.setattr(pipeline, "post_call_truth", _truth)


async def _book_on(tenant_id: UUID, call_id: UUID, *, minutes: int = 30) -> UUID:
    async with tenant_session(tenant_id) as session:
        agent_id, phone = (
            await session.execute(
                text("SELECT agent_id, from_e164 FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).one()
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=call_id,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=phone,
            requested_at=datetime.now(UTC) + timedelta(minutes=minutes),
            booked_at=datetime.now(UTC),
            note="chilli",
            language="te",
        )
    assert booked is not None
    return booked[0]


async def test_a_call_with_a_booked_call_back_reads_call_back_booked_everywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-4 + F-7: outcome, Follow up, the call screens and the lead all read the booking."""
    _with_engine_summary(monkeypatch, "Caller asked if chilli is in stock. A call back was booked.")
    tenant_id, execution_id, call_id = await _completed_call("booked")
    callback_id = await _book_on(tenant_id, call_id)

    await _run_pipeline(tenant_id, call_id, execution_id)

    assert (
        await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
        == "call_back_booked"
    )
    assert (
        await _scalar(tenant_id, "SELECT model FROM call_extractions WHERE call_id = :c", c=call_id)
        == "offline-heuristic"
    ), "the row says which runner read the call"

    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
        listed = next(c for c in await crm.list_calls(session) if c.id == call_id)
        assert detail.lead_id is not None
        lead = await crm.get_lead(session, detail.lead_id)
        with pytest.raises(ProblemError) as refused:
            await crm.plan_callback(session, call_id)
        linked = (
            await session.execute(
                text("SELECT lead_id FROM scheduled_callbacks WHERE id = :i"), {"i": callback_id}
            )
        ).scalar()

    assert detail.outcome_tag == listed.outcome_tag == "call_back_booked"
    assert detail.callback is not None and detail.callback.id == callback_id
    assert detail.callback.status == "scheduled"
    assert listed.callback is not None and listed.callback.id == callback_id
    # The engine's English summary is the summary, and the headline is drawn from it.
    assert detail.summary_source == "engine" and detail.summary_state == "ready"
    assert detail.summary is not None and detail.summary.startswith("Caller asked if chilli")
    assert listed.headline == "Caller asked if chilli is in stock."
    assert refused.value.code == "callback_already_booked"
    assert linked == detail.lead_id, "the call back is linked to the lead"
    # `hot` when the sample call also trips a hot-lead field rule; never below `interested`.
    assert lead.status in ("interested", "hot") and lead.status_set_by == "system"
    assert lead.next_callback_at is not None
    assert lead.last_call_headline == "Caller asked if chilli is in stock."
    assert lead.last_call_outcome == "call_back_booked"


async def test_a_person_set_status_is_never_moved_by_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_engine_summary(monkeypatch, None)
    caller = f"+9197{uuid.uuid4().int % 100000000:08d}"
    tenant_id, execution_id, call_id = await _completed_call("person1", caller=caller)
    await _run_pipeline(tenant_id, call_id, execution_id)
    async with tenant_session(tenant_id) as session:
        lead_id = (
            await session.execute(text("SELECT lead_id FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar()
        assert lead_id is not None
        await crm.set_lead_status(session, lead_id, status="lost", actor="test")
    await _book_on(tenant_id, call_id)
    await _run_pipeline(tenant_id, call_id, execution_id)
    async with tenant_session(tenant_id) as session:
        lead = await crm.get_lead(session, lead_id)
    assert (lead.status, lead.status_set_by) == ("lost", "person")


async def test_a_test_call_makes_a_test_call_lead_that_is_never_a_repeat_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-7 + founder decision 7."""
    _with_engine_summary(monkeypatch, None)
    caller = f"+9196{uuid.uuid4().int % 100000000:08d}"
    tenant_id, execution_id, call_id = await _completed_call("trialcall", caller=caller)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET trial_call = true WHERE id = :c"), {"c": call_id}
        )
    await _run_pipeline(tenant_id, call_id, execution_id)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT l.source, l.is_repeat_caller, l.id FROM leads l "
                    "JOIN calls c ON c.lead_id = l.id WHERE c.id = :c"
                ),
                {"c": call_id},
            )
        ).one()
        listed = next(c for c in await crm.list_calls(session) if c.id == call_id)
    assert (row[0], row[1]) == ("test_call", False)
    assert listed.test_call is True


async def test_the_english_turns_and_the_call_language_summary_are_written_after_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Founder decisions 4 and 5, with the language pass stubbed at its one seam."""
    _with_engine_summary(monkeypatch, "The caller wants a callback about chilli.")
    seen: dict[str, Any] = {}

    async def _pass(**kwargs: Any) -> LanguagePass:
        seen.update(kwargs)
        return LanguagePass(
            turns_en={idx: f"english {idx}" for idx, _ in kwargs["turns"]},
            summary_local=TELUGU_SUMMARY,
        )

    monkeypatch.setattr(call_language, "run_language_pass", _pass)
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(sarvam_api_key="k"))
    tenant_id, execution_id, call_id = await _completed_call("lang")
    await _run_pipeline(tenant_id, call_id, execution_id)

    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    # The fake engine's sample call is romanised Telugu on a Telugu agent.
    assert seen["language"] == "te-IN"
    assert all("9876543210" not in body for _, body in seen["turns"]), "redacted text only"
    assert detail.translation_state == "ready"
    assert detail.transcript and all(t.text_en for t in detail.transcript)
    assert detail.summary_local == TELUGU_SUMMARY and detail.summary_language == "te-IN"


# --- 6. trial accounts promise no call backs ------------------------------------------


async def test_a_trial_account_books_no_call_back_and_the_agent_is_told_what_to_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.worker import tools
    from calevate_shared.worker_api import CallbackBookIn

    async def _restricted(session: Any, *, tenant_id: UUID) -> object:
        return object()

    async def _never_located(session: Any) -> Any:
        raise AssertionError("a trial booking must not reach the call lookup")

    monkeypatch.setattr(tools, "restricting_trial", _restricted)
    out = await tools.book_callback_for(
        uuid.uuid4(),
        "exec_trial",
        CallbackBookIn.model_validate(
            {"callback_date": "2026-10-11", "callback_time": "11:00", "confirmed": True}
        ),
        locate=_never_located,
    )
    assert out.status == "not_booked" and out.reason == TRIAL_CALLBACK_RULE
    assert "follow up" in out.say


async def test_a_trial_blocked_call_back_ends_at_once_with_a_clear_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-5: it sat "Waiting" for two hours. Now it ends `refused`, saying why."""
    from apps.api.compliance import service as compliance_service
    from apps.workers.callbacks import dispatch_due_callbacks
    from tests.trial_test_calls_test import _trial_tenant

    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: True)
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164="+919812345670",
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC),
            note=None,
            language=None,
        )
    assert booked is not None
    await dispatch_due_callbacks(tenant_id, 5)
    async with tenant_session(tenant_id) as session:
        row = await callbacks.get_callback(session, booked[0])
    assert row is not None
    assert row["status"] == "refused"
    assert row["last_refusal_reason"] == TRIAL_CALLBACK_REASON


# --- 7. the extraction output still carries the reading --------------------------------


def test_the_reading_fields_are_part_of_the_extraction_output() -> None:
    out = ExtractionOutput(headline="x", next_step="y", outcome_tag="needs_you")
    assert out.outcome_tag == "needs_you" and ExtractionOutput().outcome_tag is None
