"""What a finished call left behind after the founder's 25 Nov 2026 01:37 test call.

An outbound set-up call on an eight-step script that stopped as the agent asked for step 4:
steps 1 to 3 reached, step 4 not. "Where the call got to" said so, and yet the notes said
"Setup Progress: First expense recorded", "Interaction Outcome: Setup successful" and
"Campaign Goal Met: Yes", the summary and the extra details said an expense was recorded,
and two details nobody spoke of ("Technical Comfort Level", "Primary Usage Interest") were
filled in. The transcript is an English stand-in; nothing here names any one business.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.crm.step_progress import StepProgress, StepReading, progress_values
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import extraction as extraction_module
from apps.workers import pipeline, step_truth
from apps.workers import step_progress as judge
from apps.workers.extraction import build_response_schema, extract_call
from apps.workers.pipeline import _settle_summaries, extractor_transcript
from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript, ConversationStage
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    MomentsBrief,
    build_extraction_prompt,
)
from sqlalchemy import text
from tests.dispatch_budget_test import _tenant
from tests.step_outcomes_test import _campaign

pytestmark = pytest.mark.anyio

STEPS = [
    "Check installation",
    "Login",
    "Add Farms",
    "Enter Expenses",
    "Enter Sales",
    "Dashboard",
    "Finalise the call",
    "Not registered",
]
SCRIPT = CallScript(
    schema_version=SCRIPT_SCHEMA_VERSION,
    goal="The farmer records their first expense in the app.",
    stages=[
        ConversationStage(id=f"s{n}", name=name, instruction=f"Guide them: {name}.", step=n)
        for n, name in enumerate(STEPS, 1)
    ],
)
GOAL = "The farmer records their first expense in the app."

LINES = [
    ("caller", "Hello."),
    ("agent", "Hello, I am calling about the farm app. Is now a good time?"),
    ("caller", "Go ahead."),
    (
        "agent",
        "Please check whether the app is on your home screen. If not, open the website and "
        "press install. Tell me when it is done.",
    ),
    ("caller", "Okay."),
    ("agent", "Okay, tell me when it is done. May I know your name?"),
    ("caller", "My name is Umesh."),
    ("agent", "Thanks Umesh. Have you installed the app?"),
    ("caller", "No, I have not."),
    ("agent", "Open Chrome and type the website address, will you?"),
    ("caller", "Done, it opened."),
    ("agent", "Do you see the install button?"),
    ("caller", "Yes, I can see it."),
    ("agent", "Press it and install the app. Tell me when it is done."),
    ("caller", "And."),
    ("agent", "Is it done? Open the app and log in with your phone number. Tell me then."),
    ("agent", "Did you see it?"),
    ("caller", "Hello."),
    ("agent", "Hello. Have you logged in?"),
    ("caller", "Not yet."),
    ("agent", "Open the app and log in, and tell me."),
    ("caller", "Tell me now."),
    ("agent", "Open the app and log in, and tell me."),
    ("caller", "I logged in with my phone number."),
    ("agent", "Now press My Farms and register your farm details. Tell me when it is done."),
    ("caller", "Done."),
    ("agent", "Now press Expenses and record one expense. Tell me when it is done."),
]


def _turns(call_id: str = "c") -> list[TranscriptTurn]:
    return [
        TranscriptTurn(call_id=call_id, idx=i, speaker=s, text=t)  # type: ignore[arg-type]
        for i, (s, t) in enumerate(LINES)
    ]


SPEC = ExtractionSchemaSpec(
    fields=[
        ExtractionField(key="name", label="Caller Name", type="text"),
        ExtractionField(key="installation_status", label="Installation Status", type="text"),
        ExtractionField(
            key="setup_progress",
            label="Setup Progress",
            type="enum",
            enum_values=[
                "App installed",
                "Logged in",
                "Farm added",
                "First expense recorded",
                "Fully set up",
            ],
        ),
        ExtractionField(
            key="interaction_outcome",
            label="Interaction Outcome",
            type="enum",
            enum_values=["Setup successful", "Help given", "Not interested"],
        ),
        ExtractionField(key="campaign_goal_met", label="Campaign Goal Met", type="bool"),
        ExtractionField(key="technical_comfort", label="Technical Comfort Level", type="text"),
        ExtractionField(key="usage_interest", label="Primary Usage Interest", type="text"),
        ExtractionField(key="notes", label="Extra Details", type="text"),
    ]
)
OUTCOMES = [
    BusinessOutcome(key="setup_done", label="Setup successful"),
    BusinessOutcome(key="help_given", label="Technical assistance provided"),
]

#: The reading as the model gave it on the real call, with the lines it cites. Prompt lines
#: are the turns numbered from 1: the caller's name is line 7, the agent's last line 27.
MODEL_ANSWER: dict[str, Any] = {
    "name": "Umesh",
    "installation_status": "Successfully installed",
    "setup_progress": "First expense recorded",
    "interaction_outcome": "Setup successful",
    "campaign_goal_met": True,
    "technical_comfort": "Very comfortable",
    "usage_interest": "Expense tracking",
    "notes": (
        "The caller installed the app, logged in, added farm details and recorded their "
        "first expense."
    ),
    "evidence": {
        "name": [7],
        "installation_status": [11, 13],
        "setup_progress": [26],
        "interaction_outcome": [26],
        "campaign_goal_met": [26],
        "technical_comfort": [],
        "usage_interest": [27],
        "notes": [24, 26],
    },
    "summary": (
        "The caller installed the app, logged in and added their farm details, and then "
        "recorded an expense. The call ended after the expense was recorded."
    ),
    "headline": "Asked for help setting up; recorded first expense",
    "next_step_why": "none",
    "next_step": "",
    "next_step_by": "nobody",
    "sentiment": "positive",
    "outcome_tag": "answered",
    "refusal_reason": None,
    "goal_reason": "The caller recorded their first expense.",
    "goal_reached": "yes",
    "business_outcome": "setup_done",
    "out_of_scope": False,
    "callback_requested": False,
    "requested_callback_date": None,
    "requested_callback_time": None,
    "moments": [],
}

JUDGE_ANSWER: dict[str, Any] = {
    "steps": [
        {"step": 1, "state": "unclear", "caller_turn": -1, "quote": "", "moved_on_turn": -1},
        {
            "step": 2,
            "state": "reached",
            "caller_turn": 23,
            "quote": "I logged in with my phone number",
            "moved_on_turn": -1,
        },
        {"step": 3, "state": "reached", "caller_turn": 25, "quote": "Done", "moved_on_turn": -1},
        *(
            {"step": n, "state": "not_reached", "caller_turn": -1, "quote": "", "moved_on_turn": -1}
            for n in range(4, 9)
        ),
    ],
    "fields": [
        {
            "key": "setup_progress",
            "choices": [
                {"choice": "App installed", "step": 1},
                {"choice": "Logged in", "step": 2},
                {"choice": "Farm added", "step": 3},
                {"choice": "First expense recorded", "step": 4},
                {"choice": "Fully set up", "step": 7},
            ],
        },
        {"key": "campaign_goal_met", "choices": [{"choice": "true", "step": 4}]},
    ],
    "goal_step": 4,
    "outcomes": [{"key": "setup_done", "step": 7}],
}


def _reading() -> StepProgress:
    return judge.checked(
        JUDGE_ANSWER,
        names=judge.step_names(SCRIPT),
        lines=judge.redacted_lines(_turns()),
        spec=SPEC,
        outcomes=OUTCOMES,
    )


def _model_output() -> ExtractionOutput:
    """The reading after `extract_call`: the two details with no caller line are gone
    already (`test_a_detail_with_no_line_behind_it_is_not_mentioned`)."""
    raw = {k: v for k, v in MODEL_ANSWER.items() if k != "evidence"}
    unsaid = {"technical_comfort", "usage_interest"}
    data = {f.key: raw[f.key] for f in SPEC.fields if f.key not in unsaid}
    return ExtractionOutput(
        data=data,
        summary=raw["summary"],
        headline=raw["headline"],
        goal_reached="yes",
        goal_reason=raw["goal_reason"],
        business_outcome="setup_done",
    )


def _no_expense(text: str) -> None:
    assert "expense" not in text.casefold(), text


def _assert_truthful(out: ExtractionOutput) -> None:
    for value in out.data.values():
        if isinstance(value, str):
            _no_expense(value)
    _no_expense(out.summary)
    _no_expense(out.headline)
    assert out.goal_reason == "The call did not get as far as Enter Expenses."
    assert out.data.get("campaign_goal_met") in (False, None)
    assert out.goal_reached in ("no", "unclear", None)


# --- the transcript's own bound, with no reading -------------------------------------------


def test_the_steps_have_their_own_words() -> None:
    terms = step_truth.step_terms(SCRIPT)
    assert terms[1] == {"instal"} and terms[3] == {"farm"} and terms[4] == {"expens"}
    # A step named only in general words, or for an absence, has none.
    assert 7 not in terms and 8 not in terms


def test_a_step_the_agent_raised_last_was_never_confirmed() -> None:
    possible, unconfirmed = step_truth.transcript_bound(step_truth.step_terms(SCRIPT), _turns())
    assert 1 in possible and 3 in possible
    assert unconfirmed == {4}


def test_with_pip_off_the_transcript_still_settles_the_notes() -> None:
    """FAILS IF: an account with no step reading keeps an expense claim, a met goal or a
    finished outcome on a call that ended as the agent asked for step 4."""
    facts = step_truth.facts_of(SCRIPT, None, _turns())
    assert facts.missed == {4} and facts.incomplete

    out, changed = step_truth.settle(_model_output(), facts, SPEC, goal=GOAL, outcomes=OUTCOMES)

    _assert_truthful(out)
    assert out.goal_reached == "no"
    assert "setup_progress" not in out.data
    assert "interaction_outcome" not in out.data
    assert out.data["campaign_goal_met"] is False
    assert out.business_outcome is None
    assert out.data["installation_status"] == "Successfully installed"
    assert out.data["notes"] == "The caller installed the app, logged in and added farm details."
    assert out.summary == "The caller installed the app, logged in and added their farm details."
    assert {"summary", "goal_reached", "setup_progress"} <= set(changed)


# --- the step reading governs --------------------------------------------------------------


def test_the_reading_maps_a_yes_no_detail_the_goal_and_the_outcomes() -> None:
    reading = _reading()
    assert reading.furthest == 3
    assert reading.fields["campaign_goal_met"] == {"true": 4}
    assert reading.goal_step == 4 and reading.outcomes == {"setup_done": 7}


def test_a_status_naming_a_later_step_falls_back_or_goes() -> None:
    reading = _reading()
    data = {"setup_progress": "First expense recorded", "campaign_goal_met": True}
    assert progress_values(reading, data, SPEC) == {
        "setup_progress": "Farm added",
        "campaign_goal_met": False,
    }
    nothing = StepProgress(
        steps=(StepReading(1, "a", "unclear"), StepReading(2, "b", "not_reached")),
        fields={"setup_progress": {"App installed": 1, "Logged in": 2}},
    )
    assert progress_values(nothing, {"setup_progress": "Logged in"}, SPEC) == {
        "setup_progress": None
    }
    assert progress_values(nothing, {"setup_progress": "Fully set up"}, SPEC) == {}


def test_with_a_reading_every_value_agrees_with_where_the_call_got_to() -> None:
    """FAILS IF: any detail, the goal verdict, the outcome tag, the summary or the headline
    still says a step after step 3 happened."""
    facts = step_truth.facts_of(SCRIPT, _reading(), _turns())
    assert facts.reached == {1, 2, 3} and facts.missed == {4, 5, 6, 7, 8}

    out, _changed = step_truth.settle(_model_output(), facts, SPEC, goal=GOAL, outcomes=OUTCOMES)

    _assert_truthful(out)
    assert out.data["setup_progress"] == "Farm added"
    assert "interaction_outcome" not in out.data
    assert out.goal_reached == "no"
    assert out.goal_reason == "The call did not get as far as Enter Expenses."
    assert out.business_outcome is None
    assert out.headline == "Asked for help setting up."


def test_an_unmapped_status_that_names_an_unreached_step_goes() -> None:
    """The judge's mapping is a model answer and may leave a detail out."""
    answer = {**JUDGE_ANSWER, "fields": []}
    reading = judge.checked(
        answer, names=judge.step_names(SCRIPT), lines=judge.redacted_lines(_turns()), spec=SPEC
    )
    facts = step_truth.facts_of(SCRIPT, reading, _turns())
    out, _ = step_truth.settle(_model_output(), facts, SPEC, goal=GOAL, outcomes=OUTCOMES)
    assert "setup_progress" not in out.data
    assert out.data["campaign_goal_met"] is False


def test_a_clause_about_asking_for_the_step_is_kept() -> None:
    facts = step_truth.facts_of(SCRIPT, _reading(), _turns())
    said = "The caller added their farm details. The agent asked them to record an expense."
    assert step_truth.without_unreached(said, facts) == said


def test_a_finished_call_keeps_its_success() -> None:
    finished = StepProgress(
        steps=tuple(
            StepReading(n, STEPS[n - 1], "not_reached" if n == 8 else "reached", turn_idx=1)
            for n in range(1, 9)
        )
    )
    facts = step_truth.facts_of(SCRIPT, finished, _turns())
    out, changed = step_truth.settle(_model_output(), facts, SPEC, goal=GOAL, outcomes=OUTCOMES)
    assert changed == []
    assert out.data["interaction_outcome"] == "Setup successful"


# --- the summary ---------------------------------------------------------------------------


def test_an_engine_summary_that_claims_the_step_gives_way_to_ours() -> None:
    facts = step_truth.facts_of(SCRIPT, _reading(), _turns())
    engine = "The customer installed the app, logged in, added a farm and recorded an expense."
    ours = "The caller installed the app, logged in and added their farm details."

    english, _local, source, _ = _settle_summaries(
        engine_summary=engine, model_summary=ours, stored_local="", language="en-IN", facts=facts
    )
    assert (english, source) == (ours, "extraction")

    alone, _local, source, _ = _settle_summaries(
        engine_summary=engine, model_summary="", stored_local="", language="en-IN", facts=facts
    )
    assert source == "engine"
    assert alone == "The customer installed the app, logged in and added a farm."


# --- the extraction: evidence, and the prompt ----------------------------------------------


class _Runner:
    model_name = "fake-model"
    reads_moments = True
    reads_goal = True
    reads_outcomes = True
    reads_setting = True

    def __init__(self) -> None:
        self.setting: Any = None

    async def run(self, spec: ExtractionSchemaSpec, transcript: str, **context: Any) -> Any:
        self.setting = context.get("setting")
        return json.loads(json.dumps(MODEL_ANSWER))


async def test_a_detail_with_no_line_behind_it_is_not_mentioned() -> None:
    """FAILS IF: "Technical Comfort Level" (no line) or "Primary Usage Interest" (only the
    agent's line) is kept."""
    out = await extract_call(
        SPEC,
        extractor_transcript(_turns()),
        extractor=_Runner(),
        moments=MomentsBrief(),
        outcomes=OUTCOMES,
        goal=GOAL,
    )
    assert "technical_comfort" not in out.data
    assert "usage_interest" not in out.data
    assert out.data["name"] == "Umesh"
    assert out.data["setup_progress"] == "First expense recorded"  # settled by the steps


def test_the_prompt_asks_for_evidence_and_states_where_the_call_got_to() -> None:
    facts = step_truth.facts_of(SCRIPT, _reading(), _turns())
    note = step_truth.prompt_note(facts)
    assert note == (
        "Reached: Check installation; Login; Add Farms\n"
        "Not reached: Enter Expenses; Enter Sales; Dashboard; Finalise the call; Not registered"
    )
    prompt = build_extraction_prompt(SPEC, "caller: hello", moments=MomentsBrief(), steps=note)
    assert '- "evidence": an object holding every key of the first list' in prompt
    assert "WHERE THE CALL GOT TO." in prompt and note in prompt
    assert "A detail nobody on the call talked about is null." in prompt
    # Without the numbered lines or a reading, neither section is asked.
    plain = build_extraction_prompt(SPEC, "caller: hello")
    assert '"evidence"' not in plain and "WHERE THE CALL GOT TO" not in plain
    schema = build_response_schema(SPEC, moments=True)
    keys = list(schema["properties"])
    assert keys.index("evidence") < keys.index("summary")
    assert schema["properties"]["evidence"]["required"] == [f.key for f in SPEC.fields]
    assert "evidence" not in build_response_schema(SPEC)["properties"]


# --- end to end, through the stored rows ---------------------------------------------------


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    campaign_id = await _campaign(tenant_id, agent_id)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb), goal = :g WHERE id = :c"),
            {"s": SCRIPT.model_dump_json(), "g": GOAL, "c": campaign_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', 'completed', :g, now(), now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "g": campaign_id,
            },
        )
    return call_id


@pytest.mark.parametrize("pip", [True, False])
async def test_the_call_page_rows_claim_no_unreached_step(
    pip: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: the stored notes, the goal verdict, the outcome or the summary of the
    25 Nov call claim the expense step, with Pip on or off."""

    async def consent(_session: Any, *, tenant_id: uuid.UUID) -> bool:
        return pip

    async def fake_ask_json(request: str, _instruction: str, **kwargs: Any) -> Any:
        return SimpleNamespace(value=kwargs["parse"](JUDGE_ANSWER), earlier=(), model=None)

    async def no_meter(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(judge, "account_content_may_reach_models", consent)
    monkeypatch.setattr(judge, "ask_json", fake_ask_json)
    monkeypatch.setattr(judge.crm_assist, "meter_assist", no_meter)
    monkeypatch.setattr(judge.crm_assist, "meter_earlier", no_meter)
    runner = _Runner()
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)

    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"truth_{uuid.uuid4().hex[:10]}",
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        from_e164="+911140000000",
        to_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        engine="fake",
        transcript=_turns(str(call_id)),
        engine_summary="The customer installed the app, logged in and recorded an expense.",
    )

    facts = await pipeline._step_facts(tenant_id, call_id, snapshot, SPEC, OUTCOMES)
    assert facts is not None and (facts.progress is not None) is pip
    extraction = await pipeline._extract_stage(
        tenant_id,
        call_id,
        snapshot,
        spec=SPEC,
        agent_id=agent_id,
        transcript_text=extractor_transcript(snapshot.transcript),
        opt_out_signal=None,
        business_outcomes=OUTCOMES,
        direction="outbound",
        reuse=False,
        facts=facts,
    )
    assert extraction is not None
    assert "Not reached: Enter Expenses" in runner.setting.steps
    await pipeline._record_reading(tenant_id, call_id, snapshot, extraction, facts=facts)

    async with tenant_session(tenant_id) as session:
        data, outcome = (
            await session.execute(
                text("SELECT data, business_outcome FROM call_extractions WHERE call_id = :c"),
                {"c": call_id},
            )
        ).one()
        goal, reason, summary = (
            await session.execute(
                text("SELECT goal_reached, goal_reason, summary FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).one()
    for value in data.values():
        if isinstance(value, str):
            _no_expense(value)
    _no_expense(summary or "")
    assert reason == "The call did not get as far as Enter Expenses."
    assert goal == "no"
    assert data.get("campaign_goal_met") in (False, None)
    assert "technical_comfort" not in data and "usage_interest" not in data
    assert outcome is None
    assert data["name"] == "Umesh"
