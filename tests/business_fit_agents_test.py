"""What an agent is set up to do, and how it is tested, follows what the business does.

The business copy judges each business once (`tenancy/business_copy.Capabilities`); the
starters, the call plans, the "may do" switches, the calendar reminder and the practice
callers read it through `agents/business_fit`. Three businesses: a free app's helpline that
books, orders, sells and prices nothing (Rytu Khata's shape), a shop that does all of it, and
one nobody has judged, which must get exactly what it got before the profile existed.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace

import pytest
from apps.api.agents import specimen_scenarios as specimens
from apps.api.agents import starters, test_conversations
from apps.api.agents.business_fit import UNKNOWN, BusinessFit, business_fit, fit_of
from apps.api.agents.capability_manifest import books_visits
from apps.api.agents.script_routes import policies_applicable
from apps.api.agents.starter_plans import PlanStep
from apps.api.agents.trade_playbooks import NEXT_STEP_TITLE, playbook_for, playbook_guidance
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.tenancy.business_copy import Capabilities, GeneratedCopy
from apps.workers import agent_test_ai
from apps.workers.script_assist import ScriptBrief
from sqlalchemy import text
from tests.agent_test_loop_test import BRIEF as TEST_BRIEF
from tests.api_security_test import _make_tenant
from tests.business_copy_test import _capability, _not_selling, copy_dict

#: Words that assume a sale or a booking, which a free app's helpline must never be given.
SELLING = re.compile(
    r"\b(?:price|prices|booking|bookings|book|order|orders|delivery|buy|bought|purchase|"
    r"chilli|kilo|kilos|stock)\b",
    re.IGNORECASE,
)


def _helpline_copy() -> GeneratedCopy:
    raw = _not_selling()
    raw["example_questions"] = [
        "How do I add my crop to the app?",
        "Why can I not see my land record?",
        "Is my data safe?",
    ]
    raw["objections"] = [
        {
            "caller_says": "I already keep my records in a notebook.",
            "how_to_answer": "Say the app keeps them safe and searchable, once, then let it go.",
        }
    ]
    raw["caller_noun"] = "user"
    # The worker stores "no booking job" as absent (`_without_empty_booking_job`).
    for key in ("booking_job_title", "booking_job_line"):
        raw["placeholders"].pop(key)
    return GeneratedCopy.model_validate(raw)


HELPLINE = fit_of(_helpline_copy(), language="en-IN")
SHOP = BusinessFit(
    takes_bookings=True,
    takes_orders=True,
    quotes_prices=True,
    has_premises=True,
    sells=True,
)


# --- the starters --------------------------------------------------------------------------


@pytest.mark.parametrize("job", starters.STARTER_JOBS)
def test_a_helpline_starter_offers_nothing_and_agrees_the_next_step(
    job: starters.StarterJob,
) -> None:
    starter = starters.starter_for("custom", job, HELPLINE)
    titles = [step.title for step in starter.steps]
    assert NEXT_STEP_TITLE in titles
    assert not any(title.startswith("Offer") for title in titles)
    assert len(starter.steps) == starters.JOB_STEP_COUNTS[job]
    assert not starter.share_prices and not starter.take_bookings
    # The objections' caller lines are the business's own; nothing is about a sale.
    assert "I already keep my records in a notebook." in [o for o, _r in starter.objections]
    without_own = "\n".join(
        f"{s.title} {s.instruction} {s.exit_when}" for s in starter.steps
    ) + " ".join(f"{o} {r}" for o, r in starter.objections)
    assert not SELLING.search(without_own), SELLING.search(without_own)
    script = starter.call_script(business="Rytu Khata", language="te-IN")
    assert not script.policies.share_prices and not script.policies.take_bookings
    assert "weekday" not in " ".join(stage.instruction for stage in script.stages)


def test_a_helpline_starter_takes_the_copys_own_goal_role_and_names() -> None:
    raw = _helpline_copy().model_dump()
    raw["placeholders"]["call_goal"] = "The user leaves knowing how to do what they rang about."
    raw["placeholders"]["agent_role"] = "You help Rytu Khata's users with the app."
    fit = fit_of(GeneratedCopy.model_validate(raw))
    answering = starters.starter_for(None, "answer_calls", fit)
    assert answering.goal == "The user leaves knowing how to do what they rang about."
    assert answering.identity == "You help Rytu Khata's users with the app."
    assert answering.name_suggestion == "Help desk"
    assert "front desk" not in answering.tone
    calling = starters.starter_for(None, "call_leads", fit)
    assert calling.goal.endswith("Take no for an answer.")
    assert calling.name_suggestion == "User follow-up"


def test_with_no_goal_in_the_copy_a_helpline_agrees_the_next_step() -> None:
    fit = replace(HELPLINE, call_goal=None, agent_role=None)
    answering = starters.starter_for(None, "answer_calls", fit)
    assert "agree the next step" in answering.goal and "arrange" not in answering.goal
    assert "prices" not in answering.identity and "location" not in answering.identity
    calling = starters.starter_for(None, "call_new_leads", fit)
    assert "agree the next step" in calling.goal


def test_a_shop_starter_keeps_its_offer_and_switches() -> None:
    starter = starters.starter_for("custom", "call_leads", SHOP)
    assert "Offer a booking or order" in [s.title for s in starter.steps]
    assert starter.share_prices and starter.take_bookings
    retail = starters.starter_for("retail", "answer_calls", SHOP)
    assert "Offer an order" in [s.title for s in retail.steps]
    only_orders = replace(SHOP, takes_bookings=False)
    assert "Offer an order" in [
        s.title for s in starters.starter_for(None, "answer_calls", only_orders).steps
    ]


@pytest.mark.parametrize("vertical", [*starters.TRADES, None, "bakery"])
def test_an_unjudged_business_gets_a_neutral_starter(vertical: str | None) -> None:
    """G1-1: not judged yet is neutral. Nothing offers a booking or quotes a price, and the
    switches start off for the owner to turn on."""
    for job in starters.STARTER_JOBS:
        starter = starters.starter_for(vertical, job, UNKNOWN)
        assert starter == starters.CATALOGUE[(starters.vertical_of(vertical), job)]
        assert NEXT_STEP_TITLE in [s.title for s in starter.steps]
        assert not any(s.title.startswith("Offer") for s in starter.steps)
        assert "arrange" not in starter.goal
        assert "front desk" not in starter.tone
        script = starters.starter_script(vertical, job, business="Acme")
        assert not script.policies.share_prices and not script.policies.take_bookings


def test_a_business_plan_keeps_the_platforms_words_on_the_replaced_step() -> None:
    plan = tuple(PlanStep(title=f"Own step {i}", focus="theirs") for i in range(5))
    planned = starters.starter_for(None, "answer_calls", HELPLINE).planned(plan)
    assert [s.title for s in planned.steps] == [
        "Own step 0",
        "Own step 1",
        "Own step 2",
        NEXT_STEP_TITLE,
        "Own step 4",
    ]
    assert "theirs" not in planned.steps[3].instruction
    script = planned.call_script(business="Rytu Khata")
    lines = [f"line {i}" for i in range(5)]
    written = starters.with_example_lines(script, lines)
    assert [stage.sounds_like for stage in written.stages] == [
        "line 0",
        "line 1",
        "line 2",
        "",
        "line 4",
    ]
    guide = playbook_guidance(None, "inbound", {"answer_calls": plan}, HELPLINE)
    assert f"4. {NEXT_STEP_TITLE}:" in guide and "Own step 3" not in guide


def test_a_both_ways_helpline_script_has_no_offer_in_either_block() -> None:
    script = starters.starter_script(
        None, ("answer_calls", "call_new_leads", "call_leads"), business="Rytu", fit=HELPLINE
    )
    names = [stage.name for stage in script.stages]
    assert sum(name.endswith(NEXT_STEP_TITLE) for name in names) == 2
    assert not any("Offer" in name for name in names)
    assert not script.policies.share_prices


def test_the_neutral_trade_names_only_what_the_business_does() -> None:
    unknown = starters.trade_for("custom")
    assert unknown.topics == "what you offer"
    assert unknown.receptionist_name == "Help desk" and unknown.caller_name == "Follow-up calls"
    assert unknown.caution.startswith("Never promise anything your facts do not say")
    helpline = starters.trade_for("custom", HELPLINE)
    assert helpline.topics == "what you offer"
    assert helpline.capture == "what they need"
    assert helpline.caution.startswith("Never promise anything your facts do not say")
    shop = starters.trade_for("custom", replace(SHOP, takes_orders=False))
    assert shop.caution.startswith("Never promise a price or availability")
    assert starters.trade_for("clinic", replace(HELPLINE, words=None)) == starters.TRADES["clinic"]
    assert starters.trade_for("clinic", HELPLINE).receptionist_name == "Help desk"


# --- the plans, objections and the writer's brief ------------------------------------------


def test_an_unjudged_plan_raises_no_price() -> None:
    """G2-3: a price objection only for a business judged to quote prices."""
    plan = playbook_for("custom", "call_leads", starters.TRADES["custom"])
    assert "Can you just tell me the price?" not in [o for o, _r in plan.objections]
    assert "How much does it cost?" not in [o for o, _r in plan.objections]
    priced = playbook_for("custom", "call_leads", starters.TRADES["custom"], SHOP)
    assert "How much does it cost?" in [o for o, _r in priced.objections]
    seller = replace(SHOP, objections=())
    judged = playbook_for("custom", "call_leads", starters.TRADES["custom"], seller)
    assert "Can you just tell me the price?" not in [o for o, _r in judged.objections]
    assert "How much does it cost?" in [o for o, _r in judged.objections]


def test_the_writer_is_told_what_the_business_does() -> None:
    about = HELPLINE.brief_text()
    assert "takes no bookings or orders" in about
    assert "sells nothing" in about and "does not tell callers prices" in about
    assert "never visit it in person" in about
    assert "It calls the people on its calls: user." in about
    assert "How do I add my crop to the app?" in about
    assert "I already keep my records in a notebook." in about
    assert UNKNOWN.brief_text() == ""
    assert "callers book times with it; callers order from it" in SHOP.brief_text()
    brief = ScriptBrief(business_name="Rytu Khata", fit=HELPLINE)
    assert about in brief.user_message()
    assert "takes no bookings" not in ScriptBrief(business_name="Acme").user_message()


def test_the_practice_caller_writer_is_told_what_the_business_does() -> None:
    told = agent_test_ai.brief_text(replace(TEST_BRIEF, fit=HELPLINE))
    assert "does not tell callers prices" in told
    assert "does not tell callers prices" not in agent_test_ai.brief_text(TEST_BRIEF)
    assert "a price or a purchase only for a business that sells" in (
        agent_test_ai.GENERATE_INSTRUCTION
    )


def test_a_copy_written_before_the_profile_lends_only_its_words() -> None:
    raw = copy_dict()
    for key in ("capabilities", "objections", "caller_noun", "pip_questions"):
        raw.pop(key)
    fit = fit_of(GeneratedCopy.model_validate(raw))
    assert fit.books is None and fit.objections is None and fit.sells is None
    assert fit.example_questions and fit_of(None) == UNKNOWN
    assert fit.offer_noun is None


# --- the switches the web shows --------------------------------------------------------------


def test_the_switches_that_apply_follow_the_profile() -> None:
    helpline = policies_applicable(_helpline_copy().capabilities or Capabilities.unknown())
    assert helpline.offer_call_backs.applies
    assert not helpline.share_prices.applies
    assert helpline.share_prices.reason == "A free app helping its registered users."
    assert not helpline.take_bookings.applies
    assert "Nothing is ordered" in helpline.take_bookings.reason
    unknown = policies_applicable(Capabilities.unknown())
    assert unknown.share_prices.applies and unknown.take_bookings.applies
    assert unknown.share_prices.reason == ""
    shop = GeneratedCopy.model_validate(copy_dict()).capabilities
    assert shop is not None
    applies = policies_applicable(shop)
    assert applies.share_prices.applies and applies.take_bookings.applies
    assert applies.take_bookings.reason == "Callers order oil for pickup or delivery."
    raw = copy_dict()
    raw["capabilities"]["quotes_prices"] = _capability(False, "Prices are given in person.")
    withheld = GeneratedCopy.model_validate(raw).capabilities
    assert withheld is not None
    assert policies_applicable(withheld).share_prices.reason == "Prices are given in person."


# --- the calendar reminder -----------------------------------------------------------------


def test_the_calendar_reminder_follows_whether_callers_book() -> None:
    unjudged = starters.CATALOGUE[("clinic", "call_leads")].call_script(business="Acme")
    assert not books_visits("outbound", unjudged)
    clinic = starters.starter_for("clinic", "call_leads", SHOP).call_script(business="Acme")
    assert books_visits("outbound", clinic, SHOP)
    assert not books_visits("outbound", clinic, replace(SHOP, takes_bookings=False))
    shop = starters.starter_for("retail", "call_leads", SHOP).call_script(business="Acme")
    assert not books_visits("outbound", shop, replace(SHOP, takes_bookings=False))
    assert books_visits("outbound", shop, SHOP)
    assert not books_visits("inbound", shop, SHOP)


# --- the practice callers ------------------------------------------------------------------


def _all_text(scenarios: list[test_conversations.Scenario]) -> str:
    return " ".join(f"{s.title} {' '.join(s.turns)} {s.expect}" for s in scenarios)


@pytest.mark.parametrize("language", ["te-IN", "hi-IN", "en-IN"])
def test_a_helplines_standard_callers_carry_no_shop_lines(language: str) -> None:
    unknown = test_conversations.standard_scenarios(language, "outbound")
    helpline = test_conversations.standard_scenarios(language, "outbound", HELPLINE)
    keys = {s.key for s in helpline}
    assert "price_in_words" not in keys and "asks_about_products" not in keys
    neutral = {"vague_answer", "goes_quiet", "asks_what_callers_ask"}
    if language == "en-IN":
        assert neutral | {"low_interest"} <= keys
        asked = next(s for s in helpline if s.key == "asks_what_callers_ask")
        assert asked.turns == ("How do I add my crop to the app?",)
    else:
        # G5-1: the neutral callers are written in English only, so a Telugu or Hindi agent
        # runs none of them and the run says what went untested.
        assert "low_interest" in keys and not neutral & keys
        assert test_conversations.untested_callers(language, "outbound", HELPLINE) == [
            "Asks what your callers ask",
            "Answers vaguely",
            "Goes quiet",
        ]
    unknown_turns = {t for s in unknown for t in s.turns}
    shop_only = {
        t for s in unknown if s.key in ("asks_about_products", "price_in_words") for t in s.turns
    } | {s.turns[0] for s in unknown if s.key in ("vague_answer", "goes_quiet")}
    assert not shop_only & {t for s in helpline for t in s.turns}
    assert unknown_turns
    # The business's own push-back only where its caller lines are in this language.
    assert ("raises_own_objection" in keys) == (language == "en-IN")


def test_a_shop_keeps_its_callers_and_an_unjudged_business_gets_neutral_ones() -> None:
    shop = test_conversations.standard_scenarios("te-IN", "inbound", replace(SHOP))
    assert {"asks_about_products", "price_in_words"} <= {s.key for s in shop}
    unjudged = {s.key for s in test_conversations.standard_scenarios("te-IN", "inbound")}
    assert not {"asks_about_products", "price_in_words"} & unjudged


def test_a_business_that_prices_but_takes_no_orders_gets_a_neutral_price_caller() -> None:
    clinic = replace(SHOP, takes_orders=False, example_questions=())
    callers = test_conversations.standard_scenarios("en-IN", "inbound", clinic)
    price = next(s for s in callers if s.key == "price_in_words")
    assert price.turns == ("How much does it cost?", "Okay. Is that the full amount?")
    vague = next(s for s in callers if s.key == "vague_answer")
    assert vague.turns == ("What can you help me with?", "Just the usual.")
    assert "kilo" not in _all_text(callers).casefold()


def test_a_helplines_specimen_callers_carry_no_shop_lines() -> None:
    for business_type in ("retail", "custom"):
        callers = specimens.all_specimen_scenarios(
            "te-IN", business_type, business_name="Rytu Khata", fit=HELPLINE
        )
        keys = {s.key for s in callers}
        assert "specimen_already_bought" not in keys
        side = next(s for s in callers if s.key == "specimen_side_question")
        assert "two of them" not in " ".join(side.turns)
        fact = next(s for s in callers if s.key == "specimen_fact_not_in_knowledge")
        assert fact.turns == ("How do I add my crop to the app?",)
        assert fact.title == "Asks what its facts may not say"
        done = next(s for s in callers if s.key == "specimen_done_without_action")
        assert "powder" not in " ".join(done.turns)
    unknown = specimens.all_specimen_scenarios("en-IN", "custom", business_name="Acme")
    assert "specimen_already_bought" not in {s.key for s in unknown}
    fact = next(
        s
        for s in specimens.all_specimen_scenarios(
            "en-IN", "custom", fit=replace(HELPLINE, example_questions=())
        )
        if s.key == "specimen_fact_not_in_knowledge"
    )
    assert fact.turns == ("Can you tell me more about how that works?",)
    picked = specimens.specimen_scenarios(
        "en-IN", "custom", round_key="r", count=len(specimens.CLASSES), fit=HELPLINE
    )
    assert "specimen_already_bought" not in {s.key for s in picked}
    # A clinic sells: it keeps its own lines and the "already bought" caller.
    clinic = replace(SHOP, takes_orders=False)
    kept = specimens.all_specimen_scenarios("en-IN", "clinic", fit=clinic)
    assert "specimen_already_bought" in {s.key for s in kept}
    assert next(s for s in kept if s.key == "specimen_fact_not_in_knowledge").turns == (
        "Does the doctor's fee include the tests?",
    )


# --- read from the account -----------------------------------------------------------------


async def _seed(tenant_id: uuid.UUID, generated: dict[str, object]) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, generated, language, generated_at) "
                "VALUES (:id, :t, CAST(:g AS jsonb), 'en-IN', now())"
            ),
            {"id": uuid7(), "t": tenant_id, "g": json.dumps(generated)},
        )


async def test_the_fit_is_read_from_the_accounts_copy_and_no_price_is_nagged_for() -> None:
    helpline, _s, _t = await _make_tenant()
    unjudged, _s2, _t2 = await _make_tenant()
    await _seed(helpline, _helpline_copy().model_dump(mode="json"))
    async with tenant_session(helpline) as session:
        fit = await business_fit(session, helpline)
        assert fit == HELPLINE
        assert await business_fit(session) == HELPLINE
        assert await test_conversations.missing_facts(session) == []
    async with tenant_session(unjudged) as session:
        assert await business_fit(session, unjudged) == UNKNOWN
        # Not judged to quote prices: no price nag (G1-1).
        assert await test_conversations.missing_facts(session) == []


async def test_the_script_writer_is_given_this_agents_own_job() -> None:
    """G1-2: a draft is written for the agent's own switches, like every other consumer of
    the fit (`BusinessFit.for_agent`): a support agent whose owner turned prices and
    bookings off is not briefed as a seller, whatever the business does."""
    from apps.api.agents import script_builder, script_proposals
    from calevate_shared.call_script import CallScript, ScriptPolicies
    from tests.conftest import create_org_with_receptionist

    created = await create_org_with_receptionist(
        name="Fit Lane H",
        slug=f"fit-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        assert (await script_proposals.brief_for(session, tenant_id, agent_id)).fit == UNKNOWN
        await script_builder.save_draft(
            session,
            agent_id,
            CallScript(policies=ScriptPolicies(share_prices=False, take_bookings=False)),
        )
        fit = (await script_proposals.brief_for(session, tenant_id, agent_id)).fit
    assert fit.quotes_prices is False
    assert fit.takes_bookings is False
    assert fit.takes_orders is False
