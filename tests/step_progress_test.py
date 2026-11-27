"""Where a call got to against its script's step outcomes (founder, 24 Nov 2026: the outcomes
must "actually do something").

The model is a stub, so what is asserted is the code that stands behind its answer: a reached
step needs the person's own words, quote-checked; the furthest step reached decides a
progress-type detail; a step left before its outcome is a mistake on the call; the reading is
stored once, per tenant, and shown on the call page.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import call_mistakes, turn_checks
from apps.api.crm import service as crm_service
from apps.api.crm.step_progress import (
    StepProgress,
    StepReading,
    progress_values,
    stored_progress,
)
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import pipeline, step_truth
from apps.workers import step_progress as judge
from calevate_shared.call_script import StepOutcome
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import ExtractionField, ExtractionOutput, ExtractionSchemaSpec
from sqlalchemy import text
from tests.dispatch_budget_test import _tenant
from tests.step_outcomes_test import _campaign, _script

pytestmark = pytest.mark.anyio

NAMES = {1: "Remembers the app", 2: "Installs it", 3: "Logs in"}
SCENARIOS = {1: ("Remembers the app",), 2: ("Installs it", "Already has it"), 3: ("Logs in",)}
SPEC = ExtractionSchemaSpec(
    fields=[
        ExtractionField(
            key="app_status",
            label="App status",
            type="enum",
            enum_values=["Not interested", "Remembers", "Installed", "Logged in"],
        ),
        ExtractionField(key="crop", label="Crop", type="enum", enum_values=["Paddy", "Cotton"]),
    ]
)


def _turns(call_id: uuid.UUID | str = "c") -> list[TranscriptTurn]:
    lines = [
        ("agent", "Do you remember the Rytu Khata app?"),
        ("caller", "Yes I remember it, my son showed me."),
        ("agent", "Please install it from Play Store."),
        ("caller", "Okay, it is installing now."),
        ("agent", "Now log in with your number."),
        ("caller", "Later, I am in the field."),
    ]
    return [
        TranscriptTurn(call_id=str(call_id), idx=i, speaker=s, text=t)  # type: ignore[arg-type]
        for i, (s, t) in enumerate(lines)
    ]


def _raw() -> dict[str, Any]:
    return {
        "steps": [
            {
                "step": 1,
                "state": "reached",
                "caller_turn": 1,
                "quote": "Yes I remember it",
                "moved_on_turn": -1,
            },
            {
                "step": 2,
                "state": "reached",
                "caller_turn": 3,
                "quote": "it is installing now",
                "moved_on_turn": -1,
            },
            {"step": 3, "state": "not_reached", "caller_turn": -1, "quote": "", "moved_on_turn": 4},
        ],
        "fields": [
            {
                "key": "app_status",
                "choices": [
                    {"choice": "remembers", "step": 1},
                    {"choice": "Installed", "step": 2},
                    {"choice": "Logged in", "step": 3},
                    {"choice": "Not a choice", "step": 2},
                ],
            },
            {"key": "crop", "choices": [{"choice": "Paddy", "step": 1}]},
        ],
    }


def test_a_reached_step_needs_the_persons_own_words() -> None:
    lines = judge.redacted_lines(_turns())
    raw = _raw()
    raw["steps"][0]["quote"] = "I know the app well"  # not in the line: a paraphrase
    # The agent's line, quoting the agent: no caller line near it says it.
    raw["steps"][1].update(caller_turn=2, quote="Please install it from Play Store")
    got = judge.checked(raw, names=NAMES, lines=lines, spec=SPEC)
    assert [s.state for s in got.steps] == ["unclear", "unclear", "not_reached"]
    assert got.furthest is None


def test_a_line_numbered_one_off_stands_on_the_caller_line_it_quotes() -> None:
    raw = _raw()
    raw["steps"][1]["caller_turn"] = 2  # the agent's line; the quote is the next line's
    got = judge.checked(raw, names=NAMES, lines=judge.redacted_lines(_turns()), spec=SPEC)
    assert (got.steps[1].state, got.steps[1].turn_idx) == ("reached", 3)


#: A call in a script other than Latin: each step's action, and the person's short reply.
_TELUGU = [
    ("agent", "ఇప్పుడు ఆ బటన్ మీద నొక్కండి అండి."),
    ("caller", "ఆ నొక్కానండి."),
    ("agent", "ఇప్పుడు స్క్రీన్ మీద ఐకాన్ కనిపిస్తుందా అండి?"),
    ("caller", "యాప్‌లో కనపడుతుంది."),
    ("agent", "ఇప్పుడు ఆ బాక్సులో మీ నంబర్ను ఎంటర్ చేయండి అండి."),
    ("caller", "ఓకే చేశానండి, వచ్చింది వర్క్ అయింది యాడ్ అయింది మొత్తం."),
]


def _reached(step: int, turn: int, quote: str, scenario: str = "") -> dict[str, Any]:
    return {
        "step": step,
        "state": "reached",
        "caller_turn": turn,
        "quote": quote,
        "scenario": scenario,
        "moved_on_turn": -1,
    }


def _telugu_states(*rows: dict[str, Any]) -> list[str]:
    turns = [
        TranscriptTurn(call_id="c", idx=i, speaker=s, text=t)  # type: ignore[arg-type]
        for i, (s, t) in enumerate(_TELUGU)
    ]
    got = judge.checked(
        {"steps": list(rows)}, names=NAMES, lines=judge.redacted_lines(turns), spec=SPEC
    )
    return [s.state for s in got.steps]


def test_a_quote_in_telugu_letters_checks_out_as_the_model_copies_it() -> None:
    """FAILS IF: a caller's Telugu "done" reads "Not clear" because the model's copy of it
    differs from the transcript by an invisible join mark or a letter."""
    assert _telugu_states(
        _reached(1, 1, "ఆ నొక్కానండి"),
        # The line has the join mark Telugu print puts after a virama; the copy has none.
        _reached(2, 3, "యాప్లో కనపడుతుంది"),
        # One vowel sign left out of a long quote.
        _reached(3, 5, "ఓకే చేశానండి, వచ్చింది వర్క్ అయింది యాడ్ అయింద మొత్తం"),
    ) == ["reached", "reached", "reached"]


def test_a_quote_the_line_does_not_hold_is_still_refused() -> None:
    assert _telugu_states(
        _reached(1, 1, "aa nokkanandi"),  # transliterated
        _reached(2, 3, "It is showing"),  # translated
        _reached(3, 5, "చేయలేదు"),  # words of a different line
    ) == ["unclear", "unclear", "unclear"]
    # A short quote must match exactly: one letter there can be the whole meaning.
    assert _telugu_states(_reached(2, 3, "కనపడదు")) == ["unclear", "unclear", "unclear"]


def test_a_step_is_named_by_the_scenario_the_call_went_through() -> None:
    """FAILS IF: a step with a side step reads as both, "Installs it, Already has it"."""
    lines = judge.redacted_lines(_turns())
    raw = _raw()
    raw["steps"][1]["scenario"] = " already HAS it "
    got = judge.checked(raw, names=NAMES, lines=lines, spec=SPEC, scenarios=SCENARIOS)
    assert [s.name for s in got.steps] == ["Remembers the app", "Already has it", "Logs in"]
    raw["steps"][1]["scenario"] = "Not a scenario of step 2"
    got = judge.checked(raw, names=NAMES, lines=lines, spec=SPEC, scenarios=SCENARIOS)
    assert got.steps[1].name == "Installs it"


def test_the_reading_keeps_what_checks_out() -> None:
    got = judge.checked(_raw(), names=NAMES, lines=judge.redacted_lines(_turns()), spec=SPEC)
    assert got.steps == (
        StepReading(1, NAMES[1], "reached", turn_idx=1),
        StepReading(2, NAMES[2], "reached", turn_idx=3),
        StepReading(3, NAMES[3], "not_reached", moved_on_turn=None),
    )
    # Moving on from the last step is impossible, so its moved-on turn is dropped; a detail
    # whose choices map onto one step only does not follow the steps.
    assert got.fields == {"app_status": {"Remembers": 1, "Installed": 2, "Logged in": 3}}
    assert got.furthest == 2


def test_a_step_the_model_left_out_is_unclear() -> None:
    raw = {"steps": [_raw()["steps"][0]], "fields": []}
    got = judge.checked(raw, names=NAMES, lines=judge.redacted_lines(_turns()), spec=SPEC)
    assert [s.state for s in got.steps] == ["reached", "unclear", "unclear"]


def test_the_progress_detail_is_the_furthest_step_reached() -> None:
    mapping = {"app_status": {"Remembers": 1, "Installed": 2, "Logged in": 3}}
    reached_two = StepProgress(
        steps=(
            StepReading(1, "a", "reached", 1),
            StepReading(2, "b", "reached", 3),
            StepReading(3, "c", "not_reached"),
        ),
        fields=mapping,
    )
    assert progress_values(reached_two, {"app_status": "Logged in"}, SPEC) == {
        "app_status": "Installed"
    }
    assert progress_values(reached_two, {"crop": "Paddy"}, SPEC) == {}
    nothing = StepProgress(steps=(StepReading(1, "a", "unclear"),), fields=mapping)
    assert progress_values(nothing, {"app_status": "Not interested"}, SPEC) == {}


def test_a_step_left_before_its_outcome_is_a_mistake_on_the_call() -> None:
    progress = StepProgress(
        steps=(
            StepReading(1, "a", "not_reached", moved_on_turn=6),
            StepReading(2, "b", "not_reached", moved_on_turn=4),
            StepReading(3, "c", "reached", 9),
        )
    )
    turns = [
        TranscriptTurn(call_id="c", idx=i, speaker="agent" if i % 2 == 0 else "caller", text="ok")
        for i in range(10)
    ]
    assert call_mistakes.step_mistakes(progress, turns) == {"moved_on_unconfirmed": 4}
    assert call_mistakes.step_mistakes(None, turns) == {}
    unnamed = StepProgress(steps=(StepReading(1, "a", "not_reached"),))
    assert call_mistakes.step_mistakes(unnamed, turns) == {}
    assert "moved_on_unconfirmed" in turn_checks.JOB_KINDS
    lesson = call_mistakes.LESSONS["moved_on_unconfirmed"]
    assert lesson.label and lesson.instead


def test_a_call_the_agent_said_nothing_on_has_moved_on_from_nothing() -> None:
    """FAILS IF: a reading whose moved-on line is not a spoken agent line of this transcript
    (a re-run replaced it) is counted as "Moved on before the step was done"."""
    progress = StepProgress(steps=(StepReading(1, "a", "not_reached", moved_on_turn=2),))
    callers_only = [
        TranscriptTurn(call_id="c", idx=i, speaker="caller", text="Hello?") for i in range(4)
    ]
    assert call_mistakes.step_mistakes(progress, callers_only) == {}
    silent_agent = [
        TranscriptTurn(call_id="c", idx=i, speaker=s, text=t)  # type: ignore[arg-type]
        for i, (s, t) in enumerate([("caller", "Hello?"), ("caller", "Hello?"), ("agent", " ")])
    ]
    assert call_mistakes.step_mistakes(progress, silent_agent) == {}


# --- the database seam ----------------------------------------------------------------------


@pytest.fixture
def pip_on(monkeypatch: pytest.MonkeyPatch) -> None:
    async def yes(_session: Any, *, tenant_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(judge, "account_content_may_reach_models", yes)


def _stub_model(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    async def fake_ask_json(request: str, _instruction: str, **kwargs: Any) -> Any:
        asked.append(request)
        assert kwargs["gemini_only"] is True
        return SimpleNamespace(value=kwargs["parse"](_raw()), earlier=(), model=None)

    async def no_meter(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(judge, "ask_json", fake_ask_json)
    monkeypatch.setattr(judge.crm_assist, "meter_assist", no_meter)
    monkeypatch.setattr(judge.crm_assist, "meter_earlier", no_meter)
    return asked


async def _campaign_call(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    campaign_id = await _campaign(tenant_id, agent_id)
    script = _script([StepOutcome(step=n, outcome=f"Step {n} is done.") for n in (1, 2, 3)])
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
            {"s": script.model_dump_json(), "c": campaign_id},
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
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "valid, created_at, updated_at) VALUES (:id, :t, :c, 1, CAST(:d AS jsonb), "
                "true, now(), now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "d": json.dumps({"app_status": "Logged in", "crop": "Paddy"}),
            },
        )
    return call_id


async def test_the_reading_is_stored_once_and_reused(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _campaign_call(tenant_id, agent_id)
    asked = _stub_model(monkeypatch)

    first = await judge.judge_call_steps(tenant_id, call_id, _turns(call_id), SPEC)
    again = await judge.judge_call_steps(tenant_id, call_id, _turns(call_id), SPEC)

    assert first is not None and first == again
    assert len(asked) == 1
    # The request names the steps by their outcomes and the details' choices; words are
    # redacted before they leave.
    assert "Step 2 (scenarios: Installs it; Already has it): Step 2 is done." in asked[0]
    assert "app_status (App status): Not interested; Remembers; Installed; Logged in" in asked[0]
    async with tenant_session(tenant_id) as session:
        stored = await stored_progress(session, call_id)
    assert stored == first


async def test_an_account_with_pip_off_is_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no(_session: Any, *, tenant_id: uuid.UUID) -> bool:
        return False

    monkeypatch.setattr(judge, "account_content_may_reach_models", no)
    asked = _stub_model(monkeypatch)
    tenant_id, agent_id = await _tenant()
    call_id = await _campaign_call(tenant_id, agent_id)

    assert await judge.judge_call_steps(tenant_id, call_id, _turns(call_id), SPEC) is None
    assert asked == []


async def test_the_pipeline_notes_the_furthest_step_over_the_models_guess(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: the extraction's "Logged in" stands on a call whose evidence ends at step 2."""
    tenant_id, agent_id = await _tenant()
    call_id = await _campaign_call(tenant_id, agent_id)
    _stub_model(monkeypatch)
    snapshot = SimpleNamespace(transcript=_turns(call_id))
    extraction = ExtractionOutput(data={"app_status": "Logged in", "crop": "Paddy"})

    facts = await pipeline._step_facts(tenant_id, call_id, snapshot, SPEC, [])  # type: ignore[arg-type]
    assert facts is not None
    out, changed = step_truth.settle(extraction, facts, SPEC, goal=None, outcomes=[])

    assert out.data == {"app_status": "Installed", "crop": "Paddy"}
    assert changed == ["app_status"]
    async with tenant_session(tenant_id) as session:
        detail = await crm_service.get_call(session, call_id)
    # "Where the call got to" on the call page.
    assert [(s.step, s.state, s.turn_idx) for s in detail.steps] == [
        (1, "reached", 1),
        (2, "reached", 3),
        (3, "not_reached", None),
    ]
    assert detail.steps[1].name == "Installs it"


async def test_a_model_failure_leaves_the_extraction_standing(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _campaign_call(tenant_id, agent_id)

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("model down")

    monkeypatch.setattr(judge, "ask_json", broken)
    extraction = ExtractionOutput(data={"app_status": "Logged in"})
    snapshot = SimpleNamespace(transcript=_turns(call_id))

    facts = await pipeline._step_facts(tenant_id, call_id, snapshot, SPEC, [])  # type: ignore[arg-type]

    assert facts is not None and facts.progress is None
    out, changed = step_truth.settle(extraction, facts, SPEC, goal=None, outcomes=[])
    assert out is extraction and changed == []


async def test_another_account_cannot_read_a_calls_reading(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    call_id = await _campaign_call(tenant_a, agent_a)
    _stub_model(monkeypatch)
    await judge.judge_call_steps(tenant_a, call_id, _turns(call_id), SPEC)

    async with tenant_session(tenant_b) as session:
        assert await stored_progress(session, call_id) is None
        seen = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE step_progress IS NOT NULL")
            )
        ).scalar_one()
    assert seen == 0
