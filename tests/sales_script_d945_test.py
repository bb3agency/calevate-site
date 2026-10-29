"""D-945 (founder, 30 Oct 2026): selling without promising.

The research behind it is `docs/research/reports/Sales call scripts and generation.md`. Pinned
here: the "who is this?" rule stops and waits; the week ahead is written into every call; the
opener of a call to a known lead checks the name; the script lint; the value and close steps
and the objection set; the turn checks for stacked questions, a re-asked name, an unbacked
promise and a wrong weekday; the advisory scorecard; the sixth owner question; and the
calendar reminder only where a calendar changes the call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from apps.api.agents import readiness, roster, script_builder, starters, trial_results
from apps.api.agents.capability_manifest import (
    books_visits,
    lint_context_for,
    manifest_for,
    owner_facts,
)
from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    other_persona,
    plain,
    script_problems,
    unbacked_promise,
    unknown_figure,
)
from apps.api.agents.service import dial_first_words
from apps.api.agents.test_conversations import (
    SCORECARD_ITEMS,
    Judged,
    RuleContext,
    Scenario,
    Turn,
    decide,
    hard_check,
    scorecard_from,
)
from apps.api.agents.trade_playbooks import (
    JOB_SHAPES,
    TRADE_WORDS,
    VALUE_STEP_TITLE,
    playbook_for,
    playbook_guidance,
)
from apps.api.agents.turn_checks import JOB_KINDS, SOUND_KINDS, conversation_problems, wrong_weekday
from apps.api.db.session import tenant_session
from apps.api.first_run.questions import ONE_THING, with_one_thing
from apps.api.main import app
from apps.workers import agent_test_ai
from apps.workers.script_assist import (
    OWNER_QUESTIONS,
    VALUE_FACT_NOTE,
    ScriptBrief,
    language_problems,
)
from calevate_shared.call_script import CallScript, ConversationStage, ExampleLine, ScriptPolicies
from calevate_shared.engine import (
    DAYS_RULE,
    NAME_VARIABLE,
    OPENING_CONTINUES_RULE,
    named_lead_opening,
    today_value,
)
from calevate_shared.spoken_style import (
    NAME_CHECK_KEY,
    OPENING_KEYS,
    REASON_KEY,
    name_check_in,
    opening_in,
    reason_clause,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

NOTHING = CapabilityManifest()
EVERYTHING = CapabilityManifest(
    booking_tool=True, whatsapp=True, call_backs=True, hand_over=True, team_alerts=True
)


# --- the start of the call --------------------------------------------------------------


def test_who_is_this_gets_who_and_why_then_a_stop() -> None:
    assert "Asked who or why? Say both in one line, then stop and wait." in OPENING_CONTINUES_RULE
    assert "then your first question." not in OPENING_CONTINUES_RULE.split("Asked who")[1][:60]


def test_every_call_reads_the_week_ahead_in_ist() -> None:
    # 30 Oct 2026, 20:00 UTC is already Saturday 31 Oct in India.
    value = today_value(datetime(2026, 10, 30, 20, 0, tzinfo=UTC))
    assert value == (
        "Saturday, 31 October 2026; then Sun 1 Nov, Mon 2 Nov, Tue 3 Nov, Wed 4 Nov, "
        "Thu 5 Nov, Fri 6 Nov"
    )
    assert len(value) <= 150
    assert "THIS CALL's days" in DAYS_RULE


def test_the_introduced_call_to_a_lead_keeps_its_reason() -> None:
    line = opening_in("te-IN", "outbound", introduced=True)
    assert line == "మేము {business} నుండి కాల్ చేస్తున్నాము. ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా?"
    assert opening_in("te-IN", "outbound", introduced=True, with_reason=False) == (
        "ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా?"
    )
    # A written reason clause wins over the fallback, and is data, not code.
    assert REASON_KEY in OPENING_KEYS and NAME_CHECK_KEY in OPENING_KEYS
    assert reason_clause({REASON_KEY: "about your enquiry.", "outbound": "Hi, x. Free?"}) == (
        "about your enquiry."
    )
    assert reason_clause({"outbound": "Hi, we are calling from {business}. Free now?"}) == (
        "we are calling from {business}."
    )
    assert reason_clause({}) == ""


def test_a_known_lead_is_asked_for_by_name_where_a_line_is_written() -> None:
    assert name_check_in("en-IN") == "Am I speaking with {name}?"
    # Telugu and Hindi wait for the founder's line: nothing changes for them yet.
    assert name_check_in("te-IN") is None and name_check_in("hi-IN") is None
    assert named_lead_opening("హాయ్ అండి, మేము X. ఫ్రీయేనా?", language="te-IN", introduced=False) is None
    token = f"{{{{{NAME_VARIABLE}}}}}"
    plain = named_lead_opening(
        "Hello, we are calling from Acme. Are you free now?", language="en-IN", introduced=False
    )
    assert plain == f"Hello, Am I speaking with {token}?"
    after_intro = named_lead_opening(
        "We are calling about your enquiry. Are you free now?", language="en-IN", introduced=True
    )
    assert after_intro == f"We are calling about your enquiry. Am I speaking with {token}?"
    assert named_lead_opening("", language="en-IN", introduced=False) is None


def _row(direction: str, language: str, prompt: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "name": "Anjali",
        "direction": direction,
        "language_primary": language,
        "prompt": prompt,
        "business_name": "Acme",
        "ai_disclosure_line": "This is the AI assistant for Acme.",
        "ai_disclosure_enabled": False,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": False,
        "caller_memory_notice_line": "x",
        "caller_memory_enabled": False,
    }


def test_the_dial_opens_with_the_name_check_only_for_a_known_lead() -> None:
    body = "[OPENING]\nHello, we are calling from Acme. Are you free now?"
    row = _row("outbound", "en-IN", body)
    named = dial_first_words(row, test_call=False, call_is_recorded=True, lead_name="Ravi")
    assert named == f"Hello, Am I speaking with {{{{{NAME_VARIABLE}}}}}?"
    assert dial_first_words(row, test_call=False, call_is_recorded=True) is None
    assert dial_first_words(row, test_call=True, call_is_recorded=True, lead_name="Ravi") is None
    telugu = _row("outbound", "te-IN", "[OPENING]\nహాయ్ అండి, మేము Acme. ఫ్రీయేనా?")
    assert dial_first_words(telugu, test_call=False, call_is_recorded=True, lead_name="R") is None
    inbound = _row("inbound", "en-IN", body)
    assert dial_first_words(inbound, test_call=False, call_is_recorded=True, lead_name="R") is None


def test_a_promise_outside_the_manifest_is_caught_unless_it_is_conditional_or_negated() -> None:
    assert unbacked_promise("I'll send it on WhatsApp now.", NOTHING)
    assert unbacked_promise("I'll send it on WhatsApp now.", EVERYTHING) is None
    assert unbacked_promise("The team will call you back.", NOTHING)
    assert unbacked_promise("Let me book that for you.", NOTHING)
    assert unbacked_promise("I will connect you to the manager.", NOTHING)
    assert unbacked_promise("Only if you can offer a call back, offer two times.", NOTHING) is None
    assert unbacked_promise("I can't connect you right now.", NOTHING) is None


def test_figures_names_and_questions() -> None:
    assert unknown_figure("It starts at ₹ 45,00,000.", "A 2BHK starts at 60 lakh.") == "₹ 45,00,000"
    assert unknown_figure("It is 60 lakh.", "A 2BHK starts at 60 lakh.") is None
    assert other_persona("Hi, I'm Priya from Acme.", agent_name="Anjali", business_name="Acme")
    assert other_persona("This is Anjali.", agent_name="Anjali", business_name="Acme") is None
    assert (
        other_persona("This is Acme Homes.", agent_name="Anjali", business_name="Acme Homes")
        is None
    )


def _script(**kw: Any) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=kw.get("opening", "Hello from Acme, how can I help?"),
        stages=[
            ConversationStage(
                id="s1",
                name="Offer a site visit",
                instruction=kw.get("instruction", "Offer a site visit at two times."),
                sounds_like=kw.get("sounds", "Would tomorrow suit you?"),
            )
        ],
        example_exchange=[
            ExampleLine(speaker="caller", text="Any discount? Any offer? Today?"),
            ExampleLine(speaker="agent", text=kw.get("agent_line", "The team will confirm.")),
        ],
        policies=ScriptPolicies(take_bookings=kw.get("bookings", True)),
    )


def test_the_whole_script_is_linted_but_a_callers_line_is_theirs() -> None:
    context = LintContext(manifest=NOTHING, agent_name="Anjali")
    assert script_problems(_script(), context) == []
    bad = _script(
        opening="Hi, I'm Priya. Limited offer today, shall we talk? Is now fine?",
        instruction="Say you will send the brochure on WhatsApp.",
    )
    found = script_problems(bad, context)
    assert any("limited offer" in p.lower() for p in found)
    assert any("asks 2 questions" in p for p in found)
    assert any('"Priya"' in p for p in found)
    assert any("WhatsApp" in p and p.startswith("stages.0.instruction") for p in found)
    raw = CallScript.from_freeform("Hurry, only today!")
    assert script_problems(raw, context)


def test_the_writer_repairs_what_the_lint_finds_in_its_own_lines_only() -> None:
    context = LintContext(manifest=NOTHING, agent_name="Anjali")
    bad = _script(agent_line="I will send it on WhatsApp, best price!")
    problems = language_problems(bad, "en-IN", lint=context)
    assert any("WhatsApp" in p for p in problems)
    assert any("best price" in p.lower() for p in problems)
    # The owner's own line, already in the script, is never the model's to fix.
    assert not any("example_exchange" in p for p in language_problems(bad, "en-IN", before=bad))


def test_the_brief_carries_the_manifest_the_facts_and_the_sixth_answer() -> None:
    assert OWNER_QUESTIONS["one_thing"] == "What one thing should every caller know about you?"
    brief = ScriptBrief(
        business_name="Acme",
        direction="outbound",
        language="en-IN",
        answers=(("one_thing", "Open since 1998."),),
        capabilities=CapabilityManifest(call_backs=True, lead_sources=("web_form",)),
        facts=("Possession in March 2027.",),
    )
    message = brief.user_message()
    assert "What this agent can do on a call: offer a call back" in message
    assert "It can NOT: book or confirm a time" in message
    assert "Where its leads come from: web_form" in message
    assert "- Possession in March 2027." in message
    assert VALUE_FACT_NOTE in message
    assert "What one thing should every caller know about you? Open since 1998." in message
    assert "2027" in brief.lint_context().facts and "1998" in brief.lint_context().facts
    assert VALUE_FACT_NOTE not in ScriptBrief(direction="inbound").user_message()


# --- the plans ---------------------------------------------------------------------------


def test_calling_plans_say_one_true_fact_then_offer_two_exact_times() -> None:
    for trade, words in TRADE_WORDS.items():
        assert words.value_topics, trade
        for job in ("call_leads", "call_new_leads"):
            plan = playbook_for(trade, job, starters.TRADES[trade])
            titles = [step.title for step in plan.steps]
            value = titles.index(VALUE_STEP_TITLE)
            assert titles[value - 1] == "Find out what they need"
            assert titles[value + 1].startswith("Offer ")
            offer, close = plan.steps[value + 1], plan.steps[-1]
            assert "two exact times" in offer.instruction
            assert '"or another time that suits you"' in offer.instruction
            assert "weekday, date, time and place" in close.instruction
            objections = [said for said, _ in plan.objections]
            for asked in (
                "I'm busy right now.",
                "How much does it cost?",
                "Not now, maybe in a few months.",
                "Where did you get my number?",
                "Just send it on WhatsApp.",
                "I don't want to talk to a machine.",
            ):
                assert asked in objections or job == "call_new_leads", (trade, asked)
        answering = playbook_for(trade, "answer_calls", starters.TRADES[trade])
        assert VALUE_STEP_TITLE not in [step.title for step in answering.steps]
    assert set(JOB_SHAPES) >= {"call_leads", "call_new_leads"}
    guide = playbook_guidance("real_estate", "outbound", "te-IN")
    assert VALUE_STEP_TITLE in guide and "possession date" in guide


# --- the turn checks ---------------------------------------------------------------------


def test_who_is_this_answered_then_a_question_is_a_note() -> None:
    stacked = [Turn("Who is this?", "I'm Anjali from Acme, about your enquiry. Free now?")]
    kinds = [p.kind for p in conversation_problems(stacked)]
    assert kinds == ["stacked_after_who"] and "stacked_after_who" in SOUND_KINDS
    waits = [Turn("Who is this?", "I'm Anjali from Acme, about your enquiry.")]
    assert conversation_problems(waits) == []


def test_a_name_already_given_is_not_asked_again() -> None:
    turns = [
        Turn("My name is Ravi, I want a 2BHK.", "Which area are you looking at?"),
        Turn("Kokapet.", "And what is your name?"),
    ]
    assert [p.kind for p in conversation_problems(turns)] == ["reasked_name"]
    assert "reasked_name" in SOUND_KINDS


def test_a_promise_the_account_cannot_keep_fails_the_test() -> None:
    turns = [Turn("Send me the details.", "Sure, I'll send it on WhatsApp right away.")]
    assert [p.kind for p in conversation_problems(turns, manifest=NOTHING)] == ["unbacked_promise"]
    assert conversation_problems(turns, manifest=EVERYTHING) == []
    assert conversation_problems(turns) == []
    assert "unbacked_promise" in JOB_KINDS


def test_a_weekday_must_fall_on_its_date() -> None:
    friday = date(2026, 10, 30)
    assert wrong_weekday("How about Sunday, 1 November at 11?", friday) is None
    assert wrong_weekday("How about Monday, 1 November at 11?", friday) == "Monday, 1 November"
    assert wrong_weekday("1 November, Sunday works.", friday) is None
    assert wrong_weekday("Tomorrow, Saturday, then.", friday) is None
    assert wrong_weekday("Tomorrow, Thursday, then.", friday) == "Tomorrow, Thursday"
    assert wrong_weekday("రేపు శనివారం కుదురుతుందా?", friday) is None
    assert wrong_weekday("రేపు ఆదివారం కుదురుతుందా?", friday) == "రేపు ఆదివారం"
    # Early January reads December as the one just gone; 31 February is no date at all.
    assert wrong_weekday("Thursday, 31 December", date(2027, 1, 2)) is None
    assert wrong_weekday("Monday, 31 February", friday) is None
    turns = [Turn("When?", "Monday, 1 November at 11, or another time that suits you?")]
    kinds = [p.kind for p in conversation_problems(turns, today=friday)]
    assert kinds == ["wrong_weekday"] and "wrong_weekday" in JOB_KINDS


def test_the_rule_context_judges_promises_against_what_the_agent_can_do() -> None:
    rules = RuleContext(manifest=NOTHING, today=date(2026, 10, 30))
    scenario = Scenario(
        key="k", title="Wants details", category="business", turns=("hi",), expect=""
    )
    turns = [Turn("Send it?", "I'll send it on WhatsApp now.")]
    verdict = hard_check(scenario, turns, rules=rules)
    assert verdict.verdict == "failed" and verdict.fix == "platform"


# --- the advisory scorecard --------------------------------------------------------------


def test_the_scorecard_is_advice_and_never_moves_a_verdict() -> None:
    assert scorecard_from({"reason_given": "no", "qualified": "maybe", "x": "yes"}) == (
        ("reason_given", "no"),
    )
    assert scorecard_from(None) == ()
    scenario = Scenario(
        key="k", title="Wants a visit", category="business", turns=("hi",), expect=""
    )
    every_no = tuple((item, "no") for item in SCORECARD_ITEMS)
    judged = Judged(verdict="passed", reason="Fine.", scorecard=every_no)
    result = decide(
        scenario, [Turn("hi", "Hello, which area?")], judged, language="en-IN", unjudged_reason=""
    )
    assert result["verdict"] == "passed" and result["scorecard"] == dict(every_no)
    schema = agent_test_ai._JUDGED_PROPERTIES["scorecard"]
    assert isinstance(schema, dict) and schema["required"] == list(SCORECARD_ITEMS)
    assert "advice only and never moves the verdict" in agent_test_ai.JUDGE_INSTRUCTION
    parsed = agent_test_ai.judgements_from_model(
        {
            "results": [
                {
                    "key": "k",
                    "reason": "ok",
                    "verdict": "passed",
                    "scorecard": dict.fromkeys(SCORECARD_ITEMS, "yes"),
                }
            ]
        },
        {"k"},
    )
    assert parsed is not None and dict(parsed["k"].scorecard)["read_back"] == "yes"


def test_a_promise_that_fails_one_try_fails_the_test() -> None:
    tries = [
        {"key": "k", "verdict": "passed", "scorecard": {"close_offered": "yes"}},
        {"key": "k", "verdict": "failed", "fix": "platform", "reason": "It promised x."},
        {"key": "k", "verdict": "passed"},
    ]
    out = trial_results.aggregate(tries)
    assert out["verdict"] == "failed" and out["passes"] == 2
    assert trial_results.reliability(out) == "flaky"


def test_the_practice_callers_include_the_five_sales_people() -> None:
    text_ = agent_test_ai.GENERATE_INSTRUCTION
    for who in (
        "busy right now",
        "pushes back on the price",
        "who gave the business their number",
        "does not want to talk to a machine",
        "vague about when",
    ):
        assert who in text_, who


# --- the sixth owner question ------------------------------------------------------------


def test_every_first_run_asks_the_one_thing_last_and_once() -> None:
    assert len(ONE_THING.id) <= 8 and ONE_THING.maps_to is None and ONE_THING.kind == "text"
    once = with_one_thing(with_one_thing([]))
    assert once == [ONE_THING]


# --- the calendar reminder ---------------------------------------------------------------


def test_only_a_calling_agent_that_books_visits_is_reminded() -> None:
    assert books_visits("outbound", _script())
    assert books_visits("both", _script())
    assert not books_visits("inbound", _script())
    assert not books_visits("outbound", _script(bookings=False))
    talk = _script().model_copy(
        update={"stages": [ConversationStage(id="s1", name="Ask", instruction="Ask their need.")]}
    )
    assert not books_visits("outbound", talk)


def test_advice_is_passed_through_and_never_scored() -> None:
    advice = readiness.ReadinessAdviceOut(kind="calendar", action="Connect.", href="/x")
    inputs = readiness.ReadinessInputs(
        agent_id=uuid.uuid4(),
        agent_name="A",
        tests_passed=1,
        tests_counted=1,
        has_test_run=True,
        knowledge_items=9,
        open_gaps=0,
        opening_chars=40,
        opening_room=100,
        published=True,
        live=True,
        draft_waiting=False,
        out_of_sync=False,
        missed_7d=0,
        advice=(advice,),
    )
    out = readiness.score(inputs, now=datetime(2026, 10, 30, tzinfo=UTC))
    assert out.score == 100 and out.advice == [advice] and out.fixes == []


async def test_the_account_is_read_for_the_manifest_the_facts_and_the_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = uuid.UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar())
        )
        await session.execute(
            text("UPDATE agents SET direction = 'outbound', handoff_enabled = true WHERE id = :a"),
            {"a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO kb_facts (id, tenant_id, text, pinned, origin, created_at, "
                "updated_at) VALUES (:id, :tid, 'Possession in March 2027.', true, 'taught', "
                "now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=_script(opening="Hello, limited offer this week, shall we talk?"),
            notes=None,
            created_by=None,
        )
        manifest = await manifest_for(session, tenant_id=tenant_id, agent_id=agent_id)
        facts = await owner_facts(session, tenant_id=tenant_id, agent_id=agent_id)
        context = await lint_context_for(session, tenant_id=tenant_id, agent_id=agent_id)
        assert manifest.hand_over and not manifest.booking_tool and not manifest.whatsapp
        assert any("2027" in fact for fact in facts)
        assert context.agent_name == "Reception" and context.business_name == "Clinic"
        monkeypatch.setattr(readiness, "calendar_configured", lambda: True)
        agent = await roster.agent_by_id(session, agent_id)
        assert agent is not None
        advice = await readiness.advice_for(session, agent)
        monkeypatch.setattr(readiness, "calendar_configured", lambda: False)
        without = await readiness.advice_for(session, agent)
    assert [a.kind for a in advice] == ["calendar", "script"]
    assert advice[0].href == f"/agents/{agent_id}?section=actions"
    assert advice[1].detail is not None and advice[1].detail.startswith("The opening line: ")
    assert "limited offer" in advice[1].detail.lower()
    assert [a.kind for a in without] == ["script"]

    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        checked = await http.post(
            f"/v1/agents/{agent_id}/script/check",
            json={
                "script": _script(agent_line="I will send it on WhatsApp, hurry!").model_dump(
                    mode="json"
                )
            },
            headers=headers,
        )
        clean = await http.post(
            f"/v1/agents/{agent_id}/script/check",
            json={"script": _script().model_dump(mode="json")},
            headers=headers,
        )
    assert checked.status_code == 200, checked.text
    warnings = checked.json()["warnings"]
    assert any("WhatsApp" in w for w in warnings)
    # The put-live dialog shows promotional wording through the D-943 promo check, once.
    assert not any("hurry" in w.lower() for w in warnings)
    assert clean.json() == {"warnings": []}


def test_a_finding_names_its_place_in_the_owners_words() -> None:
    assert plain("stages.1.sounds_like: asks 2 questions") == "Step 2: asks 2 questions"
    assert plain("opening_line: x") == "The opening line: x"
    assert plain("outbound_opening_line: x") == "The opening on calls it makes: x"
    assert plain("objections.0.response: x") == "Push-back answer 1: x"
    assert plain("example_exchange.3.text: x") == "The example call: x"
    assert plain("style.sample_phrases.2: x") == "A sample phrase: x"
    assert plain("style.tone: x") == "How it speaks: x"
    assert plain("script: x") == "The script: x"
    assert plain("goal: x") == "Goal: x"
    assert plain("no place here") == "no place here"


def test_the_starters_are_reminded_by_their_own_booking_word() -> None:
    for trade in ("clinic", "real_estate", "education"):
        script = starters.CATALOGUE[(trade, "call_leads")].call_script(business="Acme")
        assert books_visits("outbound", script), trade
    shop = starters.CATALOGUE[("retail", "call_leads")].call_script(business="Acme")
    assert not books_visits("outbound", shop)
