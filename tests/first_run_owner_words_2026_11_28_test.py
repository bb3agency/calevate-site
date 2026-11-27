"""The first run of 28 Nov 2026 (a trial owner's "Call people" brief, LOG.md C4-C12): the
campaign had no opening line, its plan bundled the owner's tasks and closed on "confirm all
steps are done", the owner's facts, rules and calling hours were left inside the main task,
and the follow-up questions asked what the brief already said or what an app does not have.
No model is reached: the writers are fakes."""

from __future__ import annotations

import time as clock
import uuid
from datetime import time
from typing import Any

import pytest
from apps.api.agents.owner_words import (
    calling_window,
    narrowed,
    owner_tasks,
    stated_facts,
    stated_rules,
)
from apps.api.db.session import tenant_session
from apps.api.first_run.questions import (
    ONE_THING,
    Given,
    QuestionWords,
    given_in,
    written_questions,
)
from apps.api.tenancy.business_profile import Profile
from apps.workers import script_heal, script_writer
from apps.workers.opening_line import WrittenOpening
from apps.workers.script_assist import JsonAnswer, ScriptBrief
from apps.workers.script_writer import WriteRequest, keeps_language, outline_task_problems
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.opening_notices import SaidNotices
from sqlalchemy import text
from tests.script_writer_rebuild_2026_11_26_test import CAP, _context

BRIEF = (
    "We are Acme Ledger, an app that helps people keep their expenses and sales on their "
    "phone. Call people who registered on our website but have not started using the app. "
    "Help them install it on their phone's home screen from acme.example (Android: Chrome, "
    "iPhone: Safari, Add to Home Screen), log in with their mobile number, set the app "
    "language to Telugu, add their shop in My Shops, then enter their first expense and "
    "their first sale. Go one step at a time and wait for them. If they are busy, ask when "
    "to call back. The app is free. We are based in Hyderabad, Telangana. Call only between "
    "9am and 6pm. Never share other customers' details. Never promise a call-back time."
)


# --- what the owner's words state -----------------------------------------------------------


def test_each_task_of_the_brief_is_read_in_its_order() -> None:
    assert owner_tasks(BRIEF) == [
        "install it on their phone's home screen from acme.example",
        "log in with their mobile number",
        "set the app language to Telugu",
        "add their shop in My Shops",
        "enter their first expense",
        "enter their first sale",
    ]


def test_one_task_with_two_details_stays_one() -> None:
    assert owner_tasks("Help them open the app, then log in with their number and password.") == [
        "open the app",
        "log in with their number and password",
    ]
    assert owner_tasks("Explain the offer and answer their questions.") == []


def test_facts_and_rules_are_the_owners_sentences_word_for_word() -> None:
    assert stated_facts(BRIEF) == [
        "We are Acme Ledger, an app that helps people keep their expenses and sales on their "
        "phone.",
        "The app is free.",
        "We are based in Hyderabad, Telangana.",
    ]
    assert stated_rules(BRIEF) == [
        "Never share other customers' details.",
        "Never promise a call-back time.",
    ]


@pytest.mark.parametrize(
    ("words", "window"),
    [
        (BRIEF, (time(9), time(18))),
        ("Call 9 to 6pm.", (time(9), time(18))),
        ("Calls from 10:30 to 17:00 only.", (time(10, 30), time(17))),
        ("Ring them 2-5pm.", (time(14), time(17))),
        ("Call 9am\u20136pm.", (time(9), time(18))),
        ("We are open 9am to 9pm.", None),
        ("Call between 9am and 1pm, or 4pm and 7pm.", None),
    ],
)
def test_a_calling_window_is_read_only_from_words_about_calling(
    words: str, window: tuple[time, time] | None
) -> None:
    assert calling_window(words) == window


def test_a_window_only_narrows_the_lawful_one() -> None:
    lawful = (time(9), time(21))
    assert narrowed((time(8), time(18)), lawful) == (time(9), time(18))
    assert narrowed((time(21, 30), time(23)), lawful) is None


# --- the plan --------------------------------------------------------------------------------

TASKS = ["install the app", "log in", "set the language", "add their shop"]


def _step(name: str, tasks: list[int], does: str = "Guide them.") -> dict[str, Any]:
    return {"name": name, "does": does, "outcome": "Done.", "ways_out": [], "tasks": tasks}


def test_an_outline_is_held_to_one_step_per_task_in_order() -> None:
    bundled = {
        "steps": [
            _step("Check interest", []),
            _step("Install", [1]),
            _step("Account setup", [2, 3]),
            _step("Close", [], "Confirm all steps are done and thank them."),
        ]
    }
    problems = outline_task_problems(bundled, TASKS)
    assert any("steps.2: does tasks 2" in p and "own step" in p for p in problems)
    assert any(p.startswith('task 4 ("add their shop") has no step') for p in problems)
    assert any("steps.3:" in p and "everything is done" in p for p in problems)
    good = {
        "steps": [
            _step("Check interest", []),
            *(_step(t, [n]) for n, t in enumerate(TASKS, 1)),
            _step("Close", [], "Thank them and say they can now use the app daily."),
        ]
    }
    assert outline_task_problems(good, TASKS) == []
    swapped = {"steps": [_step("A", [2]), _step("B", [1]), _step("C", [3]), _step("D", [4])]}
    assert any("out of their order" in p for p in outline_task_problems(swapped, TASKS))


async def test_a_bundled_outline_is_sent_back_and_its_repair_planned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import script_assist

    context = _context(main_task=BRIEF)
    tasks = owner_tasks(BRIEF)
    answers = [
        {"steps": [_step("Setup", list(range(1, 7)))]},
        {
            "steps": [
                _step("Check interest", []),
                *(_step(f"Task {n}", [n]) for n in range(1, 7)),
                _step("Close", [], "Thank them."),
            ]
        },
    ]
    asked: list[str] = []

    async def fake_ask(description: str, instruction: str, **kw: Any) -> JsonAnswer[Any]:
        asked.append(description)
        assert kw["azure_format"] is script_writer.OUTLINE_FORMAT
        try:
            value = kw["parse"](answers[0])
        except script_assist.UnusableAnswerError as sent_back:
            assert "give each its own step" in sent_back.problems
            value = kw["parse"](answers[1])
        return JsonAnswer(value=value, capability=CAP, model="fake")

    monkeypatch.setattr(script_writer, "ask_json", fake_ask)
    plan, _spends, _read = await script_writer.plan_for(context, None, clock.monotonic())
    assert "The owner's tasks for the person" in asked[0] and tasks[4] in asked[0]
    assert [s.name for s in plan.steps if not s.side][:8] == [
        "Check interest",
        *(f"Task {n}" for n in range(1, 7)),
        "Close",
    ]


# --- the opening -----------------------------------------------------------------------------


def test_the_names_a_placed_opening_must_say_are_no_english_sentence() -> None:
    indic = "".join(chr(0x0C15 + i) for i in range(6))
    line = f"{indic} Asha, Acme Ledger app {indic}?"
    assert not keeps_language("", line, "te-IN")
    assert keeps_language("", line, "te-IN", names=("Acme Ledger", "Asha"))
    assert not keeps_language("", f"{indic}. We call to help you today.", "te-IN", names=("Asha",))


async def test_an_empty_opening_is_asked_again_with_what_was_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    indic = "".join(chr(0x0C15 + i) for i in range(6))
    lines = [f"{indic}. We are calling to help you today.", f"{indic} Asha, Acme Farms {indic}?"]
    seen: list[tuple[str, tuple[str, ...]]] = []

    async def opening(brief: ScriptBrief, **kw: Any) -> JsonAnswer[WrittenOpening]:
        seen.append((kw["line"], tuple(kw["problems"])))
        said = lines[len(seen) - 1]
        return JsonAnswer(
            value=WrittenOpening(line=said, said=SaidNotices()), capability=CAP, model="fake"
        )

    monkeypatch.setattr(script_writer, "write_opening", opening)
    context = _context()
    context = replace(context, brief=replace(context.brief, language="te-IN"))
    base = CallScript(schema_version=2)
    result = await script_writer.write_script(WriteRequest("opening", context, base=base))
    assert result.script.opening_line == lines[1]
    assert seen[0] == ("", ())
    assert seen[1][0] == lines[0] and "own letters" in seen[1][1][0]


async def test_a_refused_empty_opening_gets_a_second_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    calls: list[str] = []

    async def opening(brief: ScriptBrief, **kw: Any) -> JsonAnswer[WrittenOpening]:
        calls.append(kw["line"])
        if len(calls) == 1:
            raise ProblemError.business_rule("assist_answer_unusable", "No.")
        return JsonAnswer(
            value=WrittenOpening(
                line="Hello, Asha from Acme Farms. Is now ok?", said=SaidNotices()
            ),
            capability=CAP,
            model="fake",
        )

    monkeypatch.setattr(script_writer, "write_opening", opening)
    result = await script_writer.write_script(
        WriteRequest("opening", _context(), base=CallScript(schema_version=2))
    )
    assert len(calls) == 2 and result.script.opening_line.startswith("Hello, Asha")
    assert len(result.spends) == 2, "the refusal is metered too"


def test_a_script_with_steps_and_no_opening_is_one_the_heal_pass_opens() -> None:
    stage = ConversationStage(id="s1", name="Install", instruction="Guide them.")
    assert script_heal._unopened(CallScript(schema_version=2, stages=[stage]))
    assert not script_heal._unopened(
        CallScript(schema_version=2, stages=[stage], opening_line="Hello?")
    )
    assert not script_heal._unopened(CallScript(schema_version=2))


# --- the follow-up questions -----------------------------------------------------------------


def _q(prompt: str, kind: str = "text", options: list[str] | None = None) -> dict[str, Any]:
    return {"prompt": prompt, "hint": "", "kind": kind, "options": options or [], "maps_to": None}


def test_a_question_the_brief_answers_is_never_asked() -> None:
    given = given_in(BRIEF)
    assert given.calling_hours == "09:00 to 18:00" and len(given.rules) == 2
    app = QuestionWords(has_premises=False, goes_ahead=False)
    asked = written_questions(
        [
            _q("When may the agent call people?", "single_choice", ["9am to 6pm", "Any time"]),
            _q("What must the agent never say or promise?"),
            _q("What are the main districts you serve?"),
            _q("Do people pay anything for the app?"),
        ],
        Profile(tenant_id=uuid.uuid4()),
        app,
        given,
    )
    assert [q.prompt for q in asked] == ["Do people pay anything for the app?"]
    # With nothing given, the same questions are asked (the area one only of a business that
    # people come to or that goes to them).
    kept = written_questions(
        [_q("When may the agent call people?", "single_choice", ["9am to 6pm", "Any time"])],
        Profile(tenant_id=uuid.uuid4()),
        app,
        Given(),
    )
    assert len(kept) == 1


# --- the first run lands them ----------------------------------------------------------------


async def test_call_people_lands_the_owners_hours_facts_and_rules() -> None:
    from tests.first_run_test import _client, _owner, _tenant

    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        saved = await http.put("/v1/first-run/brief", headers=headers, json={"brief": BRIEF})
        assert saved.status_code == 200, saved.text
        made = await http.put(
            "/v1/first-run/agent",
            headers=headers,
            json={"name": "Anjali", "language_primary": "te-IN", "languages_extra": []},
        )
        assert made.status_code == 200, made.text
        drafted = await http.post("/v1/first-run/work", headers=headers, json={"job": "call_leads"})
    assert drafted.status_code == 200, drafted.text
    campaign_id = uuid.UUID(drafted.json()["campaign_id"])
    async with tenant_session(tenant_id) as session:
        hours = (
            await session.execute(
                text("SELECT calling_hours FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        pinned = [
            r[0]
            for r in await session.execute(
                text("SELECT text FROM kb_facts WHERE pinned ORDER BY position")
            )
        ]
    assert hours == {"start": "09:00", "end": "18:00"}
    assert pinned == [*stated_facts(BRIEF), *stated_rules(BRIEF)]


async def test_a_brief_that_states_a_fact_is_not_asked_the_one_thing() -> None:
    """The one thing every caller should know (D-945) is answered by a fact the brief
    states; a brief with none is still asked it."""
    from tests.first_run_test import _client, _owner, _tenant

    for brief, asked in (("Free app.", False), ("Flats", True)):
        tenant_id = await _tenant()
        headers = await _owner(tenant_id)
        async with _client() as http:
            saved = await http.put("/v1/first-run/brief", headers=headers, json={"brief": brief})
        ids = [item["id"] for item in saved.json()["questions"]["items"]]
        assert (ONE_THING.id in ids) is asked, brief


async def test_answers_set_the_window_and_pin_the_rules_ticked() -> None:
    from apps.api.first_run.work import calling_hours_of, owner_statements

    row = type(
        "Row",
        (),
        {
            "brief": "Call people who signed up and help them start.",
            "answers": [
                {"id": "q1", "prompt": "When may the agent call?", "choices": ["10am to 5pm"]},
                {
                    "id": "q2",
                    "prompt": "What must it never say?",
                    "choices": ["Never offer discounts", "Not sure"],
                },
                {"id": ONE_THING.id, "prompt": ONE_THING.prompt, "text": "Open since 1998."},
            ],
        },
    )()
    assert calling_hours_of(row) == {"start": "10:00", "end": "17:00"}
    assert owner_statements(row) == [
        ("", "Never offer discounts"),
        (ONE_THING.prompt, "Open since 1998."),
    ]
