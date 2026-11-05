"""Outcomes, moments, follow-ups, notices, profile, questions, topics, routing and WhatsApp
follow each business's capability profile (`tenancy/business_copy.Capabilities`).

Three businesses throughout: a free app that calls its registered users to help them (Rytu
Khata's shape: sells nothing, books nothing, quotes no prices, has no premises), a shop that
does all of it, and a business not judged yet, which must read exactly as before.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.first_run.questions import QuestionWords, fallback_questions
from apps.api.follow_ups import starters
from apps.api.follow_ups.definition import LeadDateTrigger
from apps.api.insights.detection import RedactedTurn, detect_gaps, topics_in, withheld_topics
from apps.api.notifications.daily_summary import (
    DailySummary,
    email_facts,
    email_lines,
    email_subject,
)
from apps.api.retrieval.routing import classify
from apps.api.teach.questions import TOPIC_QUESTIONS, _gap_question
from apps.api.tenancy import business_profile as bp
from apps.api.tenancy.business_copy import CAPABILITY_KEYS, Capabilities
from apps.api.tenancy.caller_words import CallerWords
from apps.api.whatsapp.templates import STANDARD, standard_for
from apps.workers.business_outcomes_draft import SYSTEM_PROMPT, system_prompt
from apps.workers.notifications import HOT_LEAD_SUBJECT, _compose, hot_lead_subject
from calevate_shared.business_outcomes import (
    PAST_STARTING_OUTCOMES,
    STARTING_OUTCOMES,
    BusinessOutcome,
)
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionSchemaSpec,
    MomentsBrief,
    build_extraction_prompt,
    clean_moment_candidates,
    interest_moments_label,
    withheld_moment_kinds,
)


def _caps(applies: bool | None) -> Capabilities:
    return Capabilities.model_validate(
        {key: {"reason": "judged", "applies": applies} for key in CAPABILITY_KEYS}
    )


APP = _caps(False)  # Rytu Khata's shape
SHOP = _caps(True)
UNKNOWN = Capabilities.unknown()


def _withheld_kinds(caps: Capabilities) -> frozenset[str]:
    return withheld_moment_kinds(
        takes_bookings=caps.takes_bookings.applies,
        takes_orders=caps.takes_orders.applies,
        quotes_prices=caps.quotes_prices.applies,
        has_premises=caps.has_premises.applies,
        sells=caps.sells.applies,
    )


# --- B1/B2 outcomes -----------------------------------------------------------------------


def test_the_starting_outcomes_assume_no_sale() -> None:
    words = " ".join(f"{o.label} {o.meaning}" for o in STARTING_OUTCOMES).lower()
    for sales in ("buy", "order", "book", "price"):
        assert sales not in words
    moves = {o.key: o.lead_status for o in STARTING_OUTCOMES}
    assert moves["interested"] == "interested"
    assert "got_what_they_needed" in moves and moves["not_interested"] == "contacted"
    # A call read under the earlier set still has its lead move.
    assert {o.key for o in PAST_STARTING_OUTCOMES} == {"wants_to_buy", "asked_for_information"}


def test_the_draft_prompt_phrases_the_positive_outcome_by_what_the_business_does() -> None:
    app, shop = system_prompt(APP), system_prompt(SHOP)
    assert "never propose buying, ordering, booking or paying" in app
    assert "wants to buy" not in app
    assert "wants to buy, order or book" in shop
    assert system_prompt(UNKNOWN) == SYSTEM_PROMPT == shop
    books_only = _caps(True).model_copy(
        update={"takes_orders": APP.takes_orders, "sells": SHOP.sells}
    )
    assert "wants to buy or book" in system_prompt(books_only)


# --- B3 moments ---------------------------------------------------------------------------

SPEC = ExtractionSchemaSpec(fields=[ExtractionField(key="village", label="Village", type="text")])


def test_a_business_that_sells_nothing_is_never_read_for_a_purchase() -> None:
    withheld = _withheld_kinds(APP)
    assert withheld == {
        "booking_agreed",
        "price_quoted",
        "asked_delivery_or_payment",
        "will_buy_or_visit",
    }
    assert _withheld_kinds(SHOP) == frozenset() == _withheld_kinds(UNKNOWN)
    prompt = build_extraction_prompt(
        SPEC, "caller: hello", moments=MomentsBrief(withheld_kinds=sorted(withheld))
    )
    for kind in withheld:
        assert f"    {kind} " not in prompt
    assert "strong_interest is only for wanting to go ahead" in prompt
    raw = [
        {"line": 1, "kind": "price_quoted", "label": "Price given"},
        {"line": 1, "kind": "strong_interest", "label": "Keen to use the app"},
    ]
    kept = clean_moment_candidates(raw, SPEC, withheld=withheld)
    assert [m.kind for m in kept] == ["strong_interest"]


def test_an_unjudged_business_reads_the_moment_prompt_unchanged() -> None:
    plain = build_extraction_prompt(SPEC, "caller: hello", moments=MomentsBrief())
    assert "are buying signals: only\n  for wanting to buy, order, book or visit" in plain
    assert interest_moments_label(sells=None) == "Buying signal"
    assert interest_moments_label(sells=True) == "Buying signal"
    assert interest_moments_label(sells=False) == "Strong interest"


# --- B4/B5 follow-up starters -------------------------------------------------------------


def _account(**over: Any) -> Any:
    base: dict[str, Any] = {
        "agent": uuid.uuid4(),
        "template": uuid.uuid4(),
        "owner": uuid.uuid4(),
        "has_call_new_leads": False,
        "outcomes": STARTING_OUTCOMES,
        "date_fields": (),
    }
    return starters._Account(**{**base, **over})


def test_qualify_branches_on_every_outcome_that_moves_a_lead() -> None:
    own = (
        BusinessOutcome(key="using_the_app", label="Using the app", lead_status="interested"),
        BusinessOutcome(key="wants_a_demo", label="Wants a demo", lead_status="hot"),
        BusinessOutcome(key="got_help", label="Got help", lead_status="contacted"),
    )
    found = {s.key: s for s in starters.build(_account(outcomes=own))}
    decide = next(step for step in found["qualify_new_leads"].steps if step.kind == "decide")
    assert decide.on["using_the_app"] == decide.on["wants_a_demo"] == "s3"
    assert "got_help" not in decide.on
    assert decide.on["call_back_booked"] == "s5" and decide.on["not_interested"] == "s7"
    assert found["qualify_new_leads"].steps[-1].kind == "end"


def test_reminders_exist_only_for_a_date_the_agents_capture() -> None:
    keys = [s.key for s in starters.build(_account())]
    assert "appointment_reminder" not in keys and "payment_reminder" not in keys
    dates = (
        starters.DateField(key="renewal_date", label="Renewal date"),
        starters.DateField(key="emi_due", label="EMI due date"),
    )
    found = {s.key: s for s in starters.build(_account(date_fields=dates))}
    visit, payment = found["appointment_reminder"], found["payment_reminder"]
    assert isinstance(visit.trigger, LeadDateTrigger)
    assert isinstance(payment.trigger, LeadDateTrigger)
    assert (visit.trigger.field, visit.name) == ("renewal_date", "Renewal date reminder")
    assert payment.trigger.field == "emi_due"


# --- B6 notifications ---------------------------------------------------------------------


def _summary(words: CallerWords) -> DailySummary:
    from datetime import date
    from decimal import Decimal

    return DailySummary(
        day=date(2026, 11, 5),
        business_name="Rytu Khata",
        slug="rytu",
        answered=3,
        missed=0,
        leads=2,
        hot_leads=1,
        top_hot=(),
        spent_inr=Decimal("10"),
        per_lead_inr=Decimal("5"),
        follow_ups_waiting=0,
        words=words,
    )


def test_a_business_that_sells_nothing_hears_about_interested_users_not_leads() -> None:
    app = CallerWords(sells=False, caller_noun="user")
    assert email_subject(_summary(app)) == "Today: 3 calls answered, 2 interested users"
    assert email_lines(_summary(app))[1] == "2 interested users, 1 of them most interested."
    assert email_facts(_summary(app))[1][0] == "Cost per interested user today"
    assert hot_lead_subject(app, None) == "Most interested user from your AI agent"
    assert hot_lead_subject(app, "Using the app") == "Using the app: a call your AI agent flagged"
    body = _compose(
        "Ravi", "+919000000001", "hot", None, [], slug="rytu", lead_id=uuid.uuid4(), words=app
    )
    assert body.startswith("Your AI agent flagged this interested user for you.")


@pytest.mark.parametrize("words", [CallerWords(), CallerWords(sells=True, caller_noun="customer")])
def test_a_selling_or_unjudged_business_keeps_its_lead_words(words: CallerWords) -> None:
    assert email_subject(_summary(words)) == "Today: 3 calls answered, 2 new leads"
    assert email_facts(_summary(words))[1][0] == "Cost per lead today"
    assert hot_lead_subject(words, None) == HOT_LEAD_SUBJECT
    body = _compose(
        "Ravi", "+919000000001", "hot", None, [], slug="s", lead_id=uuid.uuid4(), words=words
    )
    assert body.startswith("A lead was flagged")


# --- C1/C2 profile ------------------------------------------------------------------------


def _profile(**over: Any) -> bp.Profile:
    base: dict[str, Any] = {
        "tenant_id": uuid.uuid4(),
        "hours": {"mon": {"opens": "09:00", "closes": "18:00"}},
        "services": [
            bp.ServiceItem(name="Crop records"),
            bp.ServiceItem(name="Loan", price_inr="9"),
        ],
        "contacts": [bp.Contact(uuid.uuid4(), 0, "Help", "+919000000123", None)],
    }
    return bp.Profile(**{**base, **over})


def test_an_unpriced_offer_has_no_price_clause_when_the_business_quotes_none() -> None:
    lines = bp.fact_lines(_profile(), bp.FactWords(offer_label="Feature", quotes_prices=False))
    assert "Feature: Crop records" in lines and "Feature: Loan" in lines
    assert not any("price" in line or "₹" in line for line in lines)
    before = bp.fact_lines(_profile())
    assert "Service: Crop records — price on request" in before
    assert "Service: Loan — ₹9" in before


def test_the_address_blocks_go_live_only_where_callers_come_to_a_place() -> None:
    assert "branch_missing" in bp.go_live_blockers(_profile())
    assert "branch_missing" not in bp.go_live_blockers(_profile(), needs_address=False)
    assert "branches" not in bp.required_steps(needs_contact=True, needs_address=False)


# --- C3 first-run questions ---------------------------------------------------------------


def test_the_fixed_questions_ask_only_for_what_the_business_has() -> None:
    empty = bp.Profile(tenant_id=uuid.uuid4())
    app = QuestionWords(has_premises=False, quotes_prices=False, goes_ahead=False)
    asked = fallback_questions(empty, None, limit=5, words=app)
    prompts = [q.prompt for q in asked]
    assert "Where are you?" not in prompts
    assert not any("book" in p.lower() or "cost" in p.lower() for p in prompts)
    assert "What do you offer?" in prompts
    unknown = [q.prompt for q in fallback_questions(empty, None, limit=5)]
    assert "Where are you?" in unknown and "What do you offer, and what does it cost?" in unknown
    titled = QuestionWords(booking_title="How do people sign up?", booking_hint="Who confirms.")
    booking = fallback_questions(empty, None, limit=5, words=titled)[-1]
    assert (booking.prompt, booking.hint) == ("How do people sign up?", "Who confirms.")


# --- C4/C5 topics -------------------------------------------------------------------------


def test_topics_a_business_cannot_have_fall_to_the_callers_own_words() -> None:
    withheld = withheld_topics(APP)
    assert {"pricing", "location", "timings", "booking"} <= withheld
    assert withheld_topics(SHOP) == frozenset() == withheld_topics(UNKNOWN)
    turns = [
        RedactedTurn("caller", "Where is the khata screen?"),
        RedactedTurn("agent", "I don't know."),
    ]
    assert detect_gaps(turns)[0].topic_key == "location"
    assert detect_gaps(turns, withheld=withheld)[0].topic_key.startswith("q_")
    assert topics_in("what is the price", withheld) == frozenset()
    assert _gap_question("pricing", "Pricing", "Is the app free?", withheld) == "Is the app free?"
    assert _gap_question("pricing", "Pricing", "Is it free?") == TOPIC_QUESTIONS["pricing"]


# --- D5 routing ---------------------------------------------------------------------------


def test_routing_reaches_the_compiled_facts_only_for_a_section_that_holds_something() -> None:
    assert classify("what is your address").tier == "t0"
    assert classify("what is your address", t0_with_content=frozenset()).tier == "t3"
    assert classify("is the dentist here").intent == "staff"
    assert classify("is the dentist here", health=False).rule is None
    assert classify("is the dentist here", health=True).intent == "staff"


# --- WhatsApp -----------------------------------------------------------------------------


def test_standard_messages_follow_what_the_business_does() -> None:
    assert standard_for(UNKNOWN) == STANDARD == standard_for(SHOP)
    purposes = {t.purpose for t in standard_for(APP)}
    assert purposes == {"details_requested", "callback_time"}
