"""What a call page says after the call (4 Nov 2026 call review): who must act, the call back
the caller asked for, the campaign goal and the outcome agreeing, moments that match their
labels, which details were unclear, the business's own spelling and the person's list name."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.campaigns import service as campaigns
from apps.api.crm import service as crm
from apps.api.crm.captured import unclear_fields, with_known_name
from apps.api.crm.lead_dial import calling_hours_reason
from apps.api.crm.outcomes import CallFacts, derive_outcome
from apps.api.crm.schemas import CapturedFieldOut
from apps.api.db.session import tenant_session
from apps.workers import extraction as extraction_module
from apps.workers.after_call_callbacks import caller_slot, default_slot
from apps.workers.extraction import CallSetting, build_response_schema, extract_call
from apps.workers.moments import model_moments, prompt_line_turns
from apps.workers.pipeline import reconcile_goal
from apps.workers.redaction import redact
from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.calling_window import IST
from calevate_shared.extraction import (
    ExtractionOutput,
    ExtractionSchemaSpec,
    MomentCandidate,
    build_extraction_prompt,
    clean_moment_candidates,
    corrected_moment_kind,
    spell_business_name,
)
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage

SPEC = ExtractionSchemaSpec(fields=[])
GOAL = "App installed successfully"
OUTCOMES = (
    BusinessOutcome(key="app_installed", label="App installed successfully"),
    BusinessOutcome(key="tech_help", label="Technical assistance provided"),
)


def _facts(**overrides: Any) -> CallFacts:
    base: dict[str, Any] = {
        "status": "completed",
        "duration_s": 110,
        "caller_turns": 6,
        "callback_booked": False,
        "handoff_outcome": None,
        "hint": "answered",
        "callback_requested": False,
        "out_of_scope": False,
    }
    return CallFacts(**{**base, **overrides})


# --- 2. "Needs you" only when the business must act -------------------------------------


def test_a_next_step_the_caller_takes_is_not_needs_you() -> None:
    waits = _facts(next_step_due=True, next_step_by="caller")
    assert derive_outcome(waits) == "answered", "waiting for them to WhatsApp is nobody's task"
    assert derive_outcome(_facts(next_step_due=True, next_step_by="business")) == "needs_you"
    assert derive_outcome(_facts(hint="needs_you", next_step_by="caller")) == "answered"
    assert derive_outcome(_facts(hint="needs_you", next_step_by="business")) == "needs_you"


def test_a_reading_from_before_the_question_keeps_the_older_rule() -> None:
    assert derive_outcome(_facts(next_step_due=True)) == "needs_you"
    assert derive_outcome(_facts(hint="needs_you")) == "needs_you"


def test_an_unbooked_call_back_still_needs_the_business() -> None:
    asked = _facts(callback_requested=True, next_step_by="caller")
    assert derive_outcome(asked) == "needs_you"
    assert derive_outcome(_facts(callback_requested=True, callback_booked=True)) == (
        "call_back_booked"
    )


# --- the prompt and the schema -----------------------------------------------------------


def test_the_prompt_asks_who_acts_when_to_call_back_and_names_the_business() -> None:
    called = datetime(2026, 11, 4, 14, 56, tzinfo=UTC)
    prompt = build_extraction_prompt(
        SPEC, "caller: later", business_name="Rytu Khata", called_at=called, goal=GOAL
    )
    assert '"next_step_by"' in prompt and "business  the business or its team" in prompt
    assert '"requested_callback_date"' in prompt and '"requested_callback_time"' in prompt
    assert 'The business is called "Rytu Khata"' in prompt
    assert "2026-11-04" in prompt, "a named day resolves against the call's own date"
    assert "whether it happened before the call or during it" in prompt
    assert prompt.index('"goal_reason"') < prompt.index('"goal_reached"'), "reason first"
    assert "said they are busy and to call" in prompt


def test_the_outcome_follows_the_goal_in_the_prompt_and_the_schema() -> None:
    prompt = build_extraction_prompt(SPEC, "caller: yes", outcomes=OUTCOMES, goal=GOAL)
    assert prompt.index('"goal_reached"') < prompt.index('"business_outcome"')
    assert "The campaign goal comes first" in prompt
    keys = list(build_response_schema(SPEC, outcomes=OUTCOMES, goal=GOAL)["properties"])
    assert keys.index("goal_reason") < keys.index("goal_reached") < keys.index("business_outcome")
    schema = build_response_schema(SPEC)["properties"]
    assert schema["next_step_by"] == {"type": "string", "enum": ["business", "caller", "nobody"]}
    assert schema["requested_callback_date"] == {"type": ["string", "null"]}


class _Runner:
    """A model runner that reads every context and answers with `answer`."""

    model_name = "fake-model"
    reads_goal = True
    reads_outcomes = True
    reads_setting = True

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.setting: CallSetting | None = None

    async def run(
        self,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        outcomes: Sequence[BusinessOutcome] = (),
        goal: str | None = None,
        setting: CallSetting | None = None,
    ) -> dict[str, Any]:
        self.setting = setting
        return dict(self.answer)


async def test_the_new_answers_are_read_and_cleaned() -> None:
    runner = _Runner(
        {
            "summary": "s",
            "outcome_tag": "answered",
            "next_step_by": "Caller",
            "goal_reason": "They said they had installed it.",
            "goal_reached": "yes",
            "callback_requested": True,
            "requested_callback_date": "2026-11-05",
            "requested_callback_time": "9:30",
        }
    )
    out = await extract_call(SPEC, "caller: avunu", extractor=runner, goal=GOAL)
    assert out.next_step_by == "caller"
    assert out.goal_reason == "They said they had installed it."
    assert (out.requested_callback_date, out.requested_callback_time) == ("2026-11-05", "09:30")
    runner.answer.update(requested_callback_date="5 Nov", requested_callback_time="25:00")
    bad = await extract_call(SPEC, "caller: avunu", extractor=runner)
    assert (bad.requested_callback_date, bad.requested_callback_time) == (None, None)
    assert bad.goal_reason == "", "no goal asked, no reason kept"


# --- 1. the goal and the outcome agree ----------------------------------------------------


def test_the_goal_verdict_decides_the_outcome_that_names_it() -> None:
    reached = ExtractionOutput(goal_reached="yes", business_outcome="tech_help")
    assert reconcile_goal(reached, goal=GOAL, outcomes=OUTCOMES).business_outcome == (
        "app_installed"
    )
    unclear = ExtractionOutput(goal_reached="unclear", business_outcome="app_installed")
    assert reconcile_goal(unclear, goal=GOAL, outcomes=OUTCOMES).business_outcome is None
    other = ExtractionOutput(goal_reached="no", business_outcome="tech_help")
    assert reconcile_goal(other, goal=GOAL, outcomes=OUTCOMES) == other
    no_match = ExtractionOutput(goal_reached="yes", business_outcome="tech_help")
    assert reconcile_goal(no_match, goal="They book a visit", outcomes=OUTCOMES) == no_match


# --- 3. call backs ----------------------------------------------------------------------


def _ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def test_the_default_call_back_is_the_next_day_at_the_hour_they_answered() -> None:
    now = _ist(4, 20, 30).astimezone(UTC)
    assert default_slot(_ist(4, 16, 10), now=now).astimezone(IST) == _ist(5, 16, 10)
    # 20:26 is past 19:00, the latest a slot may be and keep its two-hour grace in hours.
    assert default_slot(_ist(4, 20, 26), now=now).astimezone(IST) == _ist(5, 19, 0)
    assert default_slot(_ist(4, 8, 0), now=now).astimezone(IST) == _ist(5, 10, 0)


def test_a_time_the_caller_named_is_kept_and_an_unlawful_one_moves() -> None:
    call_at = _ist(4, 20, 26)
    now = call_at.astimezone(UTC) + timedelta(minutes=2)
    named = ExtractionOutput(requested_callback_date="2026-11-05", requested_callback_time="17:00")
    assert caller_slot(named, call_at, now=now) == _ist(5, 17, 0).astimezone(UTC)
    time_only = ExtractionOutput(requested_callback_time="10:00")
    assert caller_slot(time_only, call_at, now=now) == _ist(5, 10, 0).astimezone(UTC)
    night = ExtractionOutput(requested_callback_date="2026-11-04", requested_callback_time="22:00")
    assert caller_slot(night, call_at, now=now) == _ist(5, 9, 0).astimezone(UTC)
    assert caller_slot(ExtractionOutput(), call_at, now=now) is None


def test_who_booked_a_call_back_is_read_from_its_key() -> None:
    assert callbacks.booked_by("after-call-default:x") == "after_call"
    assert callbacks.time_from("after-call-default:x") == "default"
    assert callbacks.time_from("after-call:x") == "caller"
    assert callbacks.booked_by("client-schedule:x") == "person"
    assert callbacks.booked_by("exec_123") == "in_call"
    assert callbacks.time_from("exec_123") is None


def test_the_calling_hours_refusal_says_when_calls_open_again() -> None:
    now = _ist(4, 21, 40).astimezone(UTC)
    assert calling_hours_reason(_ist(5, 9, 0), now=now) == (
        "Calls can only be placed between 9 am and 9 pm. You can call back from 9:00 am tomorrow."
    )
    early = _ist(4, 7, 0).astimezone(UTC)
    assert calling_hours_reason(_ist(4, 9, 0), now=early).endswith("9:00 am today.")


async def test_a_caller_who_will_talk_later_gets_a_call_back_booked_after_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner(
        {
            "summary": "They want a slower walkthrough and will talk again later.",
            "next_step": "Call them back to walk through the app step by step.",
            "next_step_by": "business",
            "outcome_tag": "needs_you",
            "callback_requested": True,
            "requested_callback_date": None,
            "requested_callback_time": None,
        }
    )
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    tenant_id, execution_id, call_id = await _completed_call("later")
    await _run_pipeline(tenant_id, call_id, execution_id)

    assert await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id) == (
        "call_back_booked"
    )
    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    assert detail.callback is not None
    assert detail.callback.booked_by == "after_call" and detail.callback.time_from == "default"
    assert detail.callback.next_try_at == detail.callback.due_at
    assert detail.next_step_by == "business"
    assert runner.setting is not None and runner.setting.called_at is not None

    # A re-drive books nothing more.
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert (
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM scheduled_callbacks WHERE source_call_id = :c",
            c=call_id,
        )
        == 1
    )


async def test_a_caller_who_asked_for_nothing_gets_no_call_back_and_no_needs_you(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner(
        {
            "summary": "Installed and uses it; will WhatsApp if stuck.",
            "next_step": "Wait for them to WhatsApp if they have doubts.",
            "next_step_by": "caller",
            "outcome_tag": "answered",
            "callback_requested": False,
        }
    )
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    tenant_id, execution_id, call_id = await _completed_call("nothing")
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id) == (
        "answered"
    )
    assert (
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM scheduled_callbacks WHERE source_call_id = :c",
            c=call_id,
        )
        == 0
    )


async def test_the_call_page_carries_the_goal_and_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner(
        {
            "summary": "s",
            "outcome_tag": "answered",
            "next_step_by": "nobody",
            "goal_reason": "They said they had installed it and use it.",
            "goal_reached": "yes",
        }
    )
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    tenant_id, execution_id, call_id = await _completed_call("goalreason")
    agent_id = await _scalar(tenant_id, "SELECT agent_id FROM calls WHERE id = :c", c=call_id)
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=f"Goal {uuid.uuid4().hex[:4]}",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            purpose="Check whether they installed the app",
            goal=GOAL,
        )
        await session.execute(
            text("UPDATE calls SET campaign_id = :g WHERE id = :c"),
            {"g": campaign_id, "c": call_id},
        )
    await _run_pipeline(tenant_id, call_id, execution_id)
    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    assert detail.goal is not None
    assert (detail.goal.goal, detail.goal.reached) == (GOAL, "yes")
    assert detail.goal.reason == "They said they had installed it and use it."
    assert detail.next_step_by == "nobody"


# --- 4. moments match their labels ------------------------------------------------------


def test_a_call_back_labelled_as_a_buying_signal_is_a_call_back() -> None:
    assert corrected_moment_kind("strong_interest", "Caller ends call to call back later") == (
        "callback_agreed"
    )
    assert corrected_moment_kind("will_buy_or_visit", "Said they will call you again") == (
        "callback_agreed"
    )
    assert corrected_moment_kind("strong_interest", "Caller ends the call") is None
    assert corrected_moment_kind("will_buy_or_visit", "Will visit the shop on Sunday") == (
        "will_buy_or_visit"
    )
    assert corrected_moment_kind("complaint", "Says you call back too often") == "complaint"
    cleaned = clean_moment_candidates(
        [{"line": 2, "kind": "strong_interest", "label": "Caller ends call to call back later"}],
        SPEC,
    )
    assert [c.kind for c in cleaned] == ["callback_agreed"]


class _Turn:
    def __init__(self, idx: int, speaker: str, text_: str, start_ms: int | None) -> None:
        self.idx, self.speaker, self.text, self.start_ms = idx, speaker, text_, start_ms
        self.start_approximate = False


def test_something_the_caller_did_cannot_sit_on_the_agents_line() -> None:
    turns = [_Turn(0, "agent", "Shall I book it?", 1_000), _Turn(1, "caller", "Yes!", 3_000)]
    placed = model_moments(
        [
            MomentCandidate(line=1, kind="strong_interest", label="Keen"),
            MomentCandidate(line=2, kind="strong_interest", label="Keen"),
        ],
        line_turns=prompt_line_turns(turns),
        field_labels={},
        redact=lambda label: redact(label).text,
        captured=set(),
    )
    assert [m["turn_idx"] for m in placed] == [1]


# --- 5. which details were unclear ------------------------------------------------------


def _field(key: str, label: str, value: Any = None, **extra: Any) -> CapturedFieldOut:
    return CapturedFieldOut(
        key=key, label=label, type="text", core=False, current=True, value=value, **extra
    )


def test_each_unclear_detail_is_named_with_a_reason_and_no_value() -> None:
    fields = [
        _field("help", "Help required"),
        _field("satisfaction", "Satisfaction level"),
        _field("count", "Plants"),
    ]
    errors = {
        "help": "Help required is required but was not captured",
        "satisfaction": "'very very happy' is not one of ['High', 'Low']",
        "count": "could not read a number from Plants",
        "_model": "HTTPError",
    }
    unclear = unclear_fields(errors, fields)
    assert [(u.key, u.label, u.kind) for u in unclear] == [
        ("satisfaction", "Satisfaction level", "not_a_choice"),
        ("count", "Plants", "not_a_number"),
    ], "a detail nobody mentioned is not unclear, and the reading failing is no one field's"
    assert all("happy" not in u.reason for u in unclear), "the caller's words never reach it"


# --- 7. the person's name from the list -------------------------------------------------


def test_a_name_the_call_did_not_capture_comes_from_the_list() -> None:
    fields = [_field("caller_name", "Caller Name"), _field("crop", "Crop name")]
    filled = with_known_name(fields, list_name="Akshita", lead_name="Someone")
    assert (filled[0].value, filled[0].source) == ("Akshita", "list")
    assert filled[1].value is None, "only a field that holds the person's name"
    said = [_field("name", "Name", value="Umesh")]
    assert with_known_name(said, list_name="Akshita", lead_name=None)[0].value == "Umesh"
    from_lead = with_known_name([_field("name", "Name")], list_name=None, lead_name="Radhika")
    assert (from_lead[0].value, from_lead[0].source) == ("Radhika", "lead")


# --- 6. the business's own spelling -----------------------------------------------------


def test_the_business_name_is_spelt_the_way_the_business_spells_it() -> None:
    summary = "The customer installed the Raitu Khata app and uses it for orders."
    assert spell_business_name(summary, "Rytu Khata") == (
        "The customer installed the Rytu Khata app and uses it for orders."
    )
    assert spell_business_name("rytu khata works", "Rytu Khata") == "Rytu Khata works"
    untouched = "They asked about the price of seeds."
    assert spell_business_name(untouched, "Rytu Khata") == untouched
    assert spell_business_name("Raitu Khata", None) == "Raitu Khata"
    assert spell_business_name("Ramu", "Raju") == "Ramu", "short names are never rewritten"
