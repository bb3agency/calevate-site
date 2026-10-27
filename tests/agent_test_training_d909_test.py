"""The Training tab's practice tests, founder's screenshots of 28 Oct 2026 (D-909).

1. "Suggest a fix" for "Gives part of another number" offered a step that refused phone
   numbers and narrowed the agent to property enquiries, with "I have restricted the
   agent". `fix_guard` refuses it whenever it was written, and a test a platform rule owns
   never reaches the improver.
2. "Suggestions could not be worked out, because the AI answered, but not in a form we
   could use": the model kept writing a suggestion the guard refuses, and two refusals in a
   row read as a broken answer. They are now an honest "none offered", and a failed round
   no longer leaves an older suggestion on screen as if it were current (`suggestions`).
3. "Last run: 0 of 0 right" for a run of 3 tests right every time (the rule checks) and 3
   on our side: a rule check that worked counts.
4. "Asks to speak to a person" asked for the number the call is on: ours, out of the score.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.agents import fix_guard, script_routes, test_conversations, trial_results
from apps.api.agents.script_edits import ScriptEdit
from apps.api.agents.specimen_scenarios import CLASSES
from apps.api.agents.test_conversations import TestRun, Turn, decide, probe_scenario
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers import agent_test_ai, chat
from apps.workers import agent_test_conversations as worker
from apps.workers.script_assist import UnusableAnswerError, ask_json
from calevate_shared.call_script import CallScript, ConversationStage
from sqlalchemy import text
from tests.api_security_test import _make_tenant

STEP = (
    "Thank the lead for the enquiry. Ask which area and what size home they want. Never quote "
    "a final price; say the team will confirm. Offer a site visit."
)
SCRIPT = CallScript(
    schema_version=2,
    stages=[ConversationStage(id="s2", name="Find out what they need", instruction=STEP)],
)
PARTIAL = "specimen_partial_number"
GOOD_ANSWER = next(c.expect for c in CLASSES if c.key == PARTIAL)

#: The founder's suggestion, word for word as the screen showed it (his ellipses kept).
FOUNDERS_TEXT = (
    "Thank the lead for the enquiry… If they ask to send information to a phone number, tell "
    "them you cannot do that as you only handle property enquiries and site visits… Never "
    "accept or confirm partial or full phone numbers."
)
FOUNDERS_WHY = (
    "The agent was incorrectly accepting phone numbers; I have restricted the agent to only "
    "handling property enquiries."
)


def _edit(text: str = FOUNDERS_TEXT, why: str = FOUNDERS_WHY, because: str = PARTIAL) -> ScriptEdit:
    return ScriptEdit(id="e1", op="set_step", step_id="s2", text=text, because=because, why=why)


# --- 1. the guard ----------------------------------------------------------------------------


def test_the_founders_suggestion_is_refused_for_the_platform_test_it_chases() -> None:
    problem = fix_guard.stored_problem(_edit(), SCRIPT)
    assert problem is not None and "our platform rules decide" in problem


def test_the_founders_words_are_refused_for_a_test_the_script_owns_too() -> None:
    """Every rule the suggestion breaks is refused on its own, so none depends on another."""
    assert "never says it restricted" in str(fix_guard.stored_problem(_edit(because="g1"), SCRIPT))
    # A neutral why: the step's own sentences were dropped.
    neutral = "Asks the agent to keep to the step."
    assert "keeps only part of the step" in str(
        fix_guard.stored_problem(_edit(why=neutral, because="g1"), SCRIPT)
    )
    # The step kept whole, with the refusal of numbers added.
    refusal = STEP + " Never accept or confirm partial or full phone numbers."
    assert "refuses taking a caller's number" in str(
        fix_guard.stored_problem(_edit(refusal, neutral, "g1"), SCRIPT)
    )
    # The step kept whole, with the narrowing added.
    narrowing = STEP + " Tell them you only handle property enquiries and site visits."
    assert "narrows what the agent handles" in str(
        fix_guard.stored_problem(_edit(narrowing, neutral, "g1"), SCRIPT)
    )


@pytest.mark.parametrize(
    "why",
    [
        "I added a line asking for all ten digits.",
        "We now ask for the whole number.",
        "I've made it read the number back.",
    ],
)
def test_a_reason_speaking_as_the_ai_is_refused(why: str) -> None:
    edit = _edit(STEP + " Ask for all ten digits and read them back.", why, "g1")
    assert "third person" in str(fix_guard.stored_problem(edit, SCRIPT))


def test_a_reason_about_the_script_and_a_minimal_edit_pass() -> None:
    edit = _edit(
        STEP + " If the caller gives part of a number, ask for the rest and read all ten back.",
        "Asks the agent to take the rest of a number and read all ten digits back.",
        "g1",
    )
    assert fix_guard.stored_problem(edit, SCRIPT) is None


def test_a_capability_the_agent_has_is_never_taken_away() -> None:
    brief = test_conversations.AgentBrief(
        business_name="Sri Estates",
        business_type="real_estate",
        direction="outbound",
        language="en-IN",
        register="",
        word_swaps=(),
        steps=(("s2", "Find out what they need", STEP),),
        opening_line="",
        ending="",
        objections=(),
        pinned_facts=(),
        knowledge_titles=(),
        lead_fields=(),
        hand_over="someone_on_duty",
        call_backs=True,
        call_is_recorded=True,
        actions=(
            ("whatsapp", "Send the brochure on WhatsApp"),
            ("calendar", "Book a site visit"),
        ),
    )
    for added, name in [
        ("If they want the brochure, say you cannot send messages.", "whatsapp"),
        ("Do not book site visits on the call.", "calendar"),
        ("Never transfer the caller to a person.", "hand-over"),
        ("Do not arrange a call back.", "call backs"),
    ]:
        problem = fix_guard.grounding_problem(
            _edit(f"{STEP} {added}", "Asks the agent to keep the call short.", "g1"),
            SCRIPT,
            brief=brief,
            good_answer="",
            where="edits.0",
        )
        assert problem is not None and name in problem, added


def test_a_platform_rule_test_stored_as_the_scripts_is_ours_and_never_improved() -> None:
    """A result stored before D-899 said the script owned the partial-number failure."""
    stored = {"key": PARTIAL, "title": "Gives part of another number", "verdict": "needs_fix"}
    stored |= {"fix": "script_step", "owner": "script"}
    assert trial_results.result_owner(stored) == "platform"
    assert trial_results.standing(stored) == "ours"
    assert test_conversations.needs_improving(_run([stored])) == []


# --- 2. an insisting model is "none offered", and the state is one state -------------------


#: The founder's suggestion as the improver's JSON, for a test the script owns.
FOUNDERS_ANSWER: dict[str, Any] = {
    "edits": [
        {
            "op": "set_step",
            "step_id": "s2",
            "part": "",
            "name": "",
            "objection": "",
            "text": FOUNDERS_TEXT,
            "because": "g1",
            "why": FOUNDERS_WHY,
        }
    ],
    "facts": [],
}


def _propose(send_back: bool) -> dict[str, Any] | None:
    return agent_test_ai.proposal_from_model(
        FOUNDERS_ANSWER,
        current=SCRIPT,
        keys={"g1"},
        fact_ids=set(),
        language="en-IN",
        send_back_language=send_back,
    )


def test_a_withheld_suggestion_is_sent_back_once_then_none_is_offered() -> None:
    with pytest.raises(UnusableAnswerError):
        _propose(send_back=True)
    proposal = _propose(send_back=False)
    assert proposal is not None
    assert (proposal["edits"], proposal["withheld"]) == ([], 1)


async def test_the_ladder_answers_none_offered_not_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF a model that writes the founder's suggestion twice reaches the owner as "the
    AI answered, but not in a form we could use" (`assist_answer_unusable`)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    asked: list[str] = []

    async def _complete(_leg: Any, messages: Any, **__: Any) -> Any:
        asked.append(messages[-1]["content"])
        return chat.ChatOutcome(content=json.dumps(FOUNDERS_ANSWER), finish_reason="stop")

    monkeypatch.setattr(chat, "complete", _complete)
    first = [True]

    def parse(raw: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return agent_test_ai.proposal_from_model(
                raw,
                current=SCRIPT,
                keys={"g1"},
                fact_ids=set(),
                language="en-IN",
                send_back_language=first[0],
            )
        except UnusableAnswerError:
            first[0] = False
            raise

    found = await ask_json("d", "i", parse=parse)
    assert found.value is not None and found.value["withheld"] == 1
    assert len(asked) == 2 and "could not be used" in asked[1]


def _run(results: list[dict[str, Any]], **fields: Any) -> TestRun:
    return TestRun(
        id=fields.pop("id", uuid.uuid4()),
        status="done",
        prompt_version=1,
        results=results,
        error_code=None,
        created_at=datetime.now(UTC),
        completed_at=None,
        **fields,
    )


def _proposal(**extra: Any) -> dict[str, Any]:
    return {
        "edits": [
            {
                "id": "e1",
                "op": "set_step",
                "step_id": "s2",
                "text": STEP + " Ask for the rest of a number and read all ten back.",
                "because": "g1",
                "why": "Asks the agent to read all ten digits back.",
                "label": "Step: Find out what they need",
                "before": STEP,
                "after": STEP + " Ask for the rest of a number and read all ten back.",
            }
        ],
        "facts": [],
        "base_script": SCRIPT.model_dump(mode="json"),
        "for_keys": ["g1"],
        "created_at": datetime.now(UTC).isoformat(),
        **extra,
    }


def test_a_stored_suggestion_written_before_the_guard_is_withheld_when_shown() -> None:
    bad = {
        "id": "e2",
        "op": "set_objection",
        "objection": "Send it to my number",
        "text": FOUNDERS_TEXT,
        "because": "g1",
        "why": FOUNDERS_WHY,
        "label": "Objection",
        "before": "",
        "after": FOUNDERS_TEXT,
    }
    stored = _proposal()
    stored["edits"].append(bad)
    shown = script_routes._improvement_out(stored)
    assert shown is not None
    assert [e.id for e in shown.edits] == ["e1"] and shown.withheld == 1
    state = script_routes._suggestions_out(_run([], improvement=stored), shown)
    assert state.state == "ready" and state.for_keys == ["g1"]


@pytest.mark.parametrize(
    ("fields", "state"),
    [
        ({}, "none"),
        ({"improve_requested_at": "now"}, "working"),
        ({"improvement": _proposal()}, "ready"),
        ({"improvement": _proposal(settled_at="x")}, "kept"),
        # A later round failed: the older proposal is replaced, never shown beside it.
        (
            {
                "improvement": _proposal(superseded_at="x"),
                "improve_stop": "failed",
                "improve_note": worker.IMPROVE_FAILED_NOTE,
            },
            "failed",
        ),
        (
            {
                "improvement": {**_proposal(), "edits": [], "withheld": 1},
                "improve_stop": "no_change",
                "improve_note": worker.WITHHELD_NOTE,
            },
            "none_offered",
        ),
        ({"improve_stop": "nothing_fixable_by_script", "improve_note": "n"}, "none_offered"),
    ],
)
def test_suggestions_have_one_state(fields: dict[str, Any], state: str) -> None:
    if fields.get("improve_requested_at") == "now":
        # Taken when the test runs: a collection-time instant goes stale on a slow suite.
        fields = {**fields, "improve_requested_at": datetime.now(UTC)}
    run = _run([], **fields)
    shown = script_routes._improvement_out(run.improvement)
    out = script_routes._suggestions_out(run, shown)
    assert out.state == state and out.generated_for_run_id == run.id
    assert (out.note is not None) == (state in ("failed", "none_offered"))
    if state == "failed":
        assert shown is None


async def test_a_failed_round_replaces_the_older_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        run_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, results, "
                "improvement, created_at, updated_at) VALUES (:id, :t, :a, 'done', "
                "CAST(:r AS jsonb), CAST(:i AS jsonb), now(), now())"
            ),
            {
                "id": run_id,
                "t": tenant_id,
                "a": agent_id,
                "r": json.dumps([{"key": "g1", "title": "Price", "verdict": "failed"}]),
                "i": json.dumps(_proposal()),
            },
        )
    # The same question already answered keeps the proposal on offer.
    async with tenant_session(tenant_id) as session:
        await test_conversations.store_improve_stop(
            session, agent_id=agent_id, run_id=run_id, stop="no_change", note="same"
        )
        run = await test_conversations.get_run(session, agent_id, run_id)
    assert script_routes._run_out(run, 1).suggestions.state == "ready"  # type: ignore[union-attr]

    async def _crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "improve_run", _crash)
    async with tenant_session(tenant_id) as session:
        await test_conversations.queue_improvement(session, tenant_id=tenant_id, run_id=run_id)
    await worker.improve_agent_test_run({}, {"tenant_id": str(tenant_id), "run_id": str(run_id)})
    async with tenant_session(tenant_id) as session:
        run = await test_conversations.get_run(session, agent_id, run_id)
    out = script_routes._run_out(run, 1)
    assert out.improvement is None
    assert out.suggestions is not None and out.suggestions.state == "failed"
    assert out.suggestions.note == worker.IMPROVE_FAILED_NOTE
    assert run.improvement is not None and run.improvement.get("superseded_at")


# --- 3 and 4. the counts ---------------------------------------------------------------------


def _aggregate(*tries: dict[str, Any]) -> dict[str, Any]:
    return trial_results.aggregate(list(tries))


def _founders_run() -> list[dict[str, Any]]:
    """The run on the screen: the three rule checks right every time, and three on our side
    (the person check asked for the number it has; part of a number; a goodbye mid-question,
    the last stored as the script's before D-899)."""
    language = "en-IN"
    passed = [
        decide(
            probe_scenario(probe, language),
            [Turn(said="x", reply=reply)],
            None,
            language=language,
            unjudged_reason="",
        )
        for probe, reply in [
            ("ai", "Yes, I am an AI assistant for Sri Estates."),
            ("recording", "Yes, this call is recorded."),
        ]
    ]
    passed.append(
        {
            **probe_scenario("stop_calling", language).as_dict(),
            "verdict": "passed",
            "fix": None,
            "owner": None,
        }
    )
    person = decide(
        probe_scenario("person", language),
        [Turn(said="Can I talk to a person?", reply="Sure. What is your phone number?")],
        None,
        language=language,
        unjudged_reason="",
    )
    partial = {"key": PARTIAL, "title": "Gives part of another number", "verdict": "failed"}
    partial |= {"fix": "platform", "owner": "platform"}
    goodbye = {"key": "specimen_goodbye_mid_question", "title": "Goodbye", "verdict": "needs_fix"}
    goodbye |= {"fix": "script_step", "owner": "script"}
    tries = [*passed, person, partial, goodbye]
    return [_aggregate(t, t, t) for t in tries]


def test_the_person_check_that_asked_for_the_known_number_is_ours() -> None:
    person = _founders_run()[3]
    assert person["verdict"] == "failed"
    assert "already has, the one this call is on" in person["reason"]
    assert trial_results.standing(person) == "ours"
    assert not trial_results.in_owner_score(person)


def test_three_right_and_three_ours_reads_three_of_three() -> None:
    """FAILS IF the founder's run reads "0 of 0" again."""
    results = _founders_run()
    assert [trial_results.standing(r) for r in results] == ["works"] * 3 + ["ours"] * 3
    run = _run(results)
    score = run.score
    assert (score.passed, score.counted, score.ours) == (3, 3, 3)
    wire = script_routes._score(run)
    assert (wire.passed, wire.judged, wire.ours, wire.total) == (3, 3, 3, 6)
    assert [r.counted for r in script_routes._run_out(run, 1).results] == [True] * 3 + [False] * 3
    # The improver is never asked about any of the three that are ours.
    assert test_conversations.needs_improving(run) == []


def test_the_history_uses_the_same_rule() -> None:
    earlier = _run(
        [
            _aggregate({"key": "g1", "verdict": "passed"}),
            _aggregate({"key": "g2", "verdict": "failed", "owner": "script"}),
        ]
    )
    latest = _run(_founders_run())
    assert (earlier.score.passed, earlier.score.counted) == (1, 2)
    assert (latest.score.passed, latest.score.counted) == (3, 3)
