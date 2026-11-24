"""Step outcomes hold for every caller, share one subject, and Pip rewrites only its own.

Founder, 24 Nov 2026: a step whose one scenario was an Android install got an Android-only
outcome though iPhone callers pass through it too, and the outcomes said "The farmer" in one
step and "The user" in the next. The model is a stub throughout: what is asserted is what the
code refuses, what it records, and which outcomes a later pass may touch.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.campaigns import step_outcomes as outcomes_api
from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, tenant_session
from apps.workers import step_outcomes as worker
from apps.workers.script_assist import UnusableAnswerError
from calevate_shared.call_script import (
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    ConversationStage,
    StepOutcome,
)
from sqlalchemy import text
from tests.dispatch_budget_test import _tenant
from tests.step_outcomes_test import (
    OWNER_OUTCOME,
    _campaign,
    _jobs,
    _past_debounce,
    _save_campaign,
    _script,
    _state,
    _stub_model,
    pip_on,  # noqa: F401  (a fixture)
)

pytestmark = pytest.mark.anyio

DEVICES_TASK = "Help each farmer install the app on an Android or iPhone and add their farm."


def _device_script() -> CallScript:
    """Step 2's only scenario is the Android case; the main task names iPhone too."""
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        stages=[
            ConversationStage(
                id="device", name="Which phone", step=1, instruction="Ask which phone they use."
            ),
            ConversationStage(
                id="android",
                name="Android installation",
                step=2,
                instruction="Guide the Android user to open the website in Chrome.",
            ),
            ConversationStage(
                id="farm", name="Add the farm", step=3, instruction="Ask them to add their farm."
            ),
        ],
    )


def _holder(
    script: CallScript, *, main_task: str = DEVICES_TASK, record: Any = None
) -> worker.Holder:
    return worker.Holder(
        kind="campaign",
        id=uuid.uuid4(),
        script=script,
        stored=None,
        version=None,
        main_task=main_task,
        aims="",
        source_ids=(),
        record=outcomes_api.PipRecord.read(record),
    )


def _row(step: int, outcome: str, quote: str) -> dict[str, Any]:
    return {"step": step, "outcome": outcome, "quote": quote}


# --- case-neutral outcomes -----------------------------------------------------------------


def test_case_sets_are_the_capitalised_alternatives_the_text_lists() -> None:
    assert worker.case_sets(DEVICES_TASK) == (frozenset({"Android", "iPhone"}),)
    assert worker.case_sets("Ask them, Telugu, English or Hindi.") == (
        frozenset({"Telugu", "English", "Hindi"}),
    )
    assert worker.case_sets("Pay by UPI/Card.") == (frozenset({"UPI", "Card"}),)
    # Lower-case pairs are not read as cases: they would refuse ordinary outcomes.
    assert worker.case_sets("Ask whether they remember or not.") == ()


def test_an_outcome_naming_one_case_of_the_main_tasks_two_is_refused() -> None:
    """FAILS IF: an outcome for a step whose only scenario is the Android case may say
    Android while the main task says Android or iPhone."""
    request = worker.request_text(_holder(_device_script()), business="", documents="")
    one_case = {
        "subject": "farmer",
        "alternatives": [],
        "outcomes": [
            _row(1, "The farmer says whether they use an Android or iPhone.", "Android or iPhone"),
            _row(2, "The farmer has the website open in Chrome on their Android.", "Chrome"),
            _row(3, "The farmer says their farm is added.", "add their farm"),
        ],
    }

    written, problems = worker.judged(one_case, request)

    assert 2 not in written.outcomes and set(written.outcomes) == {1, 3}
    assert any("names only Android" in p and "iPhone" in p for p in problems)
    with pytest.raises(UnusableAnswerError):
        worker.strict(one_case, request)


def test_a_case_neutral_outcome_is_kept_and_its_quote_may_come_from_the_main_task() -> None:
    request = worker.request_text(_holder(_device_script()), business="", documents="")
    neutral = {
        "subject": "farmer",
        "alternatives": [],
        "outcomes": [
            _row(1, "The farmer says which phone they use.", "Ask which phone they use"),
            # Grounded in the main task, not in the step's one scenario.
            _row(2, "The farmer has the app installed on their phone.", "install the app"),
            _row(3, "The farmer says their farm is added.", "add their farm"),
        ],
    }

    written = worker.strict(neutral, request)

    assert written is not None and set(written.outcomes) == {1, 2, 3}
    assert "ALTERNATIVES THE CALL NAMES\nAndroid / iPhone" in request.text


def test_alternatives_the_model_declares_count_only_where_the_material_has_them() -> None:
    script = _device_script()
    request = worker.request_text(
        _holder(script, main_task="Offer the gold plan or the silver plan."),
        business="",
        documents="",
    )
    answer = {
        "subject": "person",
        "alternatives": [["gold plan", "silver plan"], ["platinum plan", "gold plan"]],
        "outcomes": [
            _row(1, "The person picks the gold plan.", "Offer the gold plan"),
            _row(2, "The person says which plan suits them.", "Offer the gold plan"),
        ],
    }

    written, problems = worker.judged(answer, request)

    assert set(written.outcomes) == {2}
    assert any(p.startswith("step 1: the outcome names only gold plan") for p in problems)


# --- one subject ---------------------------------------------------------------------------


def test_every_outcome_shares_the_one_subject_the_pass_decides() -> None:
    """FAILS IF: one outcome may say "The farmer" and the next "The user"."""
    request = worker.request_text(_holder(_device_script()), business="", documents="")
    mixed = {
        "subject": "farmer",
        "alternatives": [],
        "outcomes": [
            _row(1, "The farmer says which phone they use.", "Ask which phone they use"),
            _row(2, "The user has the app installed on their phone.", "install the app"),
        ],
    }

    written, problems = worker.judged(mixed, request)

    assert written.subject == "farmer" and set(written.outcomes) == {1}
    assert 'step 2: begin the outcome with "The farmer"' in problems


def test_the_subject_is_a_word_the_main_task_uses_or_the_person() -> None:
    request = worker.request_text(_holder(_device_script()), business="", documents="")
    invented = {
        "subject": "customer",
        "alternatives": [],
        "outcomes": [_row(1, "The customer says which phone they use.", "which phone")],
    }

    written, problems = worker.judged(invented, request)

    assert written.subject == outcomes_api.DEFAULT_SUBJECT and not written.outcomes
    assert any(p.startswith("subject:") for p in problems)
    # One case of a set of alternatives is never the subject of every outcome.
    assert not worker.subject_holds(
        "Android", naming=DEVICES_TASK, cases=worker.case_sets(DEVICES_TASK)
    )


def test_a_recorded_subject_is_given_to_the_model_not_chosen_again() -> None:
    record = {"rules": 2, "subject": "farmer", "outcomes": {}}
    request = worker.request_text(
        _holder(_device_script(), record=record), business="", documents=""
    )

    assert request.subject == "farmer"
    assert 'Every outcome begins with "The farmer".' in request.text
    # The answer's own choice does not replace it.
    written, _ = worker.judged(
        {
            "subject": "person",
            "alternatives": [],
            "outcomes": [_row(1, "The farmer says which phone they use.", "which phone")],
        },
        request,
    )
    assert written.subject == "farmer" and set(written.outcomes) == {1}


# --- Pip's own outcomes, and only those ----------------------------------------------------


def test_pip_owns_an_outcome_only_while_it_holds_exactly_pips_text() -> None:
    record = outcomes_api.PipRecord.read(
        {
            "rules": 1,
            "subject": "person",
            "outcomes": {
                "2": {"outcome": "The person says the app is installed.", "rules": 1},
                "3": {"outcome": "The person says they are logged in.", "rules": 1},
            },
        }
    )
    script = _script(
        [
            StepOutcome(step=1, outcome=OWNER_OUTCOME),
            # Moved with its step: still Pip's.
            StepOutcome(step=3, outcome="The person says the app is installed."),
            # Edited by the owner: theirs.
            StepOutcome(step=2, outcome="The person says they are logged in now."),
        ]
    )

    assert outcomes_api.pip_steps(script, record) == {3: 1}
    assert outcomes_api.by_owner(script, record)
    assert outcomes_api.pip_outcomes_stale(script, record, 2)
    assert not outcomes_api.pip_outcomes_stale(script, record, 1)


def _stale_cases() -> list[tuple[CallScript, dict[str, Any] | None, int]]:
    pip_text = "The person says the app is installed."
    script = _script([StepOutcome(step=2, outcome=pip_text)])
    entry = {"outcome": pip_text, "rules": 1}
    return [
        (script, None, 2),
        (script, {"rules": 1, "outcomes": {"2": entry}}, 2),
        (script, {"rules": 1, "outcomes": {"2": entry}}, 1),
        # The last pass ran under this version already: the sweep waits for the next.
        (script, {"rules": 2, "outcomes": {"2": entry}}, 2),
        (script, {"rules": 1, "outcomes": {"2": {"outcome": "Other words.", "rules": 1}}}, 2),
        (script, {"rules": 1, "outcomes": {"2": {"outcome": pip_text, "rules": 2}}}, 2),
        (script, {"rules": "x", "outcomes": []}, 2),
        (_script(), {"rules": 0, "outcomes": {"2": entry}}, 2),
    ]


async def test_the_sql_stale_rule_agrees_with_the_python_rule() -> None:
    async with admin_session() as session:
        for script, raw, rules in _stale_cases():
            sql = (
                await session.execute(
                    text(
                        "SELECT script_pip_outcomes_stale(CAST(:s AS jsonb), CAST(:p AS jsonb), :r)"
                    ),
                    {"s": script.model_dump_json(), "p": json.dumps(raw), "r": rules},
                )
            ).scalar_one()
            python = outcomes_api.pip_outcomes_stale(
                script, outcomes_api.PipRecord.read(raw), rules
            )
            assert sql is python, (raw, rules)


def _answer(words: str) -> dict[str, Any]:
    return {
        "subject": "person",
        "alternatives": [],
        "outcomes": [
            _row(1, f"The person {words} remembers the app.", "Rytu Khata"),
            _row(2, f"The person {words} has the app installed.", "install the app"),
            _row(3, f"The person {words} is logged in.", "log in"),
        ],
    }


async def _run_pass(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> str:
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    return await worker.write_step_outcomes(
        {}, {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    )


def _outcomes(raw: Any) -> dict[int, str]:
    return {o.step: o.outcome for o in CallScript.model_validate(raw).step_outcomes}


async def _record(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> outcomes_api.PipRecord:
    async with tenant_session(tenant_id) as session:
        raw = (
            await session.execute(
                text("SELECT step_outcomes_pip FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    return outcomes_api.PipRecord.read(raw)


def _bump(monkeypatch: pytest.MonkeyPatch, version: int) -> None:
    monkeypatch.setattr(worker, "RULES_VERSION", version)
    monkeypatch.setattr(outcomes_api, "RULES_VERSION", version)
    monkeypatch.setattr(worker, "HOLDERS_PER_TICK", 100_000)


async def test_pips_outcomes_are_rewritten_on_a_rules_bump_and_the_owners_never(
    pip_on: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a rules-version bump leaves Pip's outcomes as they were, or touches one the
    owner typed or edited."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(
        tenant_id, campaign_id, _script([StepOutcome(step=1, outcome=OWNER_OUTCOME)])
    )
    _stub_model(monkeypatch, lambda: _answer("first"))
    assert await _run_pass(tenant_id, campaign_id) == "saved"
    record = await _record(tenant_id, campaign_id)
    assert record.rules == outcomes_api.RULES_VERSION and record.subject == "person"
    assert set(record.written) == {
        "The person first has the app installed.",
        "The person first is logged in.",
    }

    # The owner edits Pip's step 3 and saves; nothing is missing, so nothing is queued.
    _state_now, _at, _inputs, raw = await _state(tenant_id, "campaigns", campaign_id)
    edited = {**_outcomes(raw), 3: "The person says they logged in with their number."}
    await _save_campaign(
        tenant_id,
        campaign_id,
        _script([StepOutcome(step=n, outcome=t) for n, t in sorted(edited.items())]),
    )
    async with tenant_session(tenant_id) as session:
        out = await workspace.read_workspace(session, campaign_id)
        assert out.step_outcomes_by_owner

    _bump(monkeypatch, outcomes_api.RULES_VERSION + 1)
    await worker.sweep_step_outcomes({})
    assert (await _state(tenant_id, "campaigns", campaign_id))[0] == "queued"
    asked = _stub_model(monkeypatch, lambda: _answer("second"))

    assert await _run_pass(tenant_id, campaign_id) == "saved"

    _state_now, _at, _inputs, raw = await _state(tenant_id, "campaigns", campaign_id)
    assert _outcomes(raw) == {
        1: OWNER_OUTCOME,
        2: "The person second has the app installed.",
        3: "The person says they logged in with their number.",
    }
    assert "STEP 2\n" in asked[0] and "STEP 1\n" not in asked[0] and "STEP 3\n" not in asked[0]
    record = await _record(tenant_id, campaign_id)
    assert record.rules == outcomes_api.RULES_VERSION
    assert record.written == {"The person second has the app installed.": record.rules}
    # Rewritten under the new version: the next sweep leaves it alone.
    await worker.sweep_step_outcomes({})
    assert (await _state(tenant_id, "campaigns", campaign_id))[0] == "done"


async def test_an_android_only_outcome_is_never_saved(
    pip_on: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET main_task = :t WHERE id = :c"),
            {"t": DEVICES_TASK, "c": campaign_id},
        )
    await _save_campaign(
        tenant_id,
        campaign_id,
        _device_script().model_copy(
            update={
                "step_outcomes": [
                    StepOutcome(step=1, outcome="The farmer says which phone they use."),
                    StepOutcome(step=3, outcome="The farmer says their farm is added."),
                ]
            }
        ),
    )
    _stub_model(
        monkeypatch,
        lambda: {
            "subject": "farmer",
            "alternatives": [],
            "outcomes": [_row(2, "The farmer has Chrome open on their Android.", "Chrome")],
        },
    )

    assert await _run_pass(tenant_id, campaign_id) == "assist_answer_unusable"
    _state_now, _at, _inputs, raw = await _state(tenant_id, "campaigns", campaign_id)
    assert 2 not in _outcomes(raw)


# --- outcomes written by 0.5.33, before the record ----------------------------------------


async def test_outcomes_written_before_the_record_are_the_owners_until_handed_back(
    pip_on: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0.5.33 kept a hash of its request, not the text it wrote, so nothing tells its
    outcomes from the owner's: they are never rewritten until the owner gives them back,
    which is one action."""

    async def consent(_session: Any, *, tenant_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(outcomes_api, "require_consent", consent)
    monkeypatch.setattr(worker, "HOLDERS_PER_TICK", 100_000)
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    old = _script(
        [
            StepOutcome(step=1, outcome="The farmer remembers the app."),
            StepOutcome(step=2, outcome="The user has the app on their Android."),
            StepOutcome(step=3, outcome="The farmer is logged in."),
        ]
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET script = CAST(:s AS jsonb), step_outcomes_state = 'done', "
                "step_outcomes_inputs = :d, step_outcomes_at = now(), step_outcomes_pip = NULL "
                "WHERE id = :c"
            ),
            {"s": old.model_dump_json(), "d": "0" * 64, "c": campaign_id},
        )

    await worker.sweep_step_outcomes({})
    assert await _jobs(tenant_id, campaign_id) == []
    async with tenant_session(tenant_id) as session:
        assert (await workspace.read_workspace(session, campaign_id)).step_outcomes_by_owner
        assert await outcomes_api.hand_back_to_pip(session, "campaign", campaign_id)
    assert len(await _jobs(tenant_id, campaign_id)) == 1
    _stub_model(monkeypatch, lambda: _answer("now"))

    assert await _run_pass(tenant_id, campaign_id) == "saved"

    _state_now, _at, _inputs, raw = await _state(tenant_id, "campaigns", campaign_id)
    assert _outcomes(raw) == {
        1: "The person now remembers the app.",
        2: "The person now has the app installed.",
        3: "The person now is logged in.",
    }
    async with tenant_session(tenant_id) as session:
        assert not (await workspace.read_workspace(session, campaign_id)).step_outcomes_by_owner


async def test_another_account_cannot_hand_back_or_read_the_record(
    pip_on: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    campaign_id = await _campaign(tenant_a, agent_a)
    await _save_campaign(tenant_a, campaign_id, _script())
    _stub_model(monkeypatch, lambda: _answer("own"))
    assert await _run_pass(tenant_a, campaign_id) == "saved"

    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as refused:
            await outcomes_api.hand_back_to_pip(session, "campaign", campaign_id)
        rows = (
            await session.execute(
                text("SELECT count(*) FROM campaigns WHERE step_outcomes_pip IS NOT NULL")
            )
        ).scalar_one()
    assert refused.value.code == "not_found"
    assert rows == 0
    assert (await _record(tenant_a, campaign_id)).written
