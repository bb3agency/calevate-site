"""The routing table is a product decision, so it is asserted as one.

Every test here names a QUESTION a caller or a client would really ask, not a token that
happens to be in the table — a test that asserts `classify("policy")` proves the `in`
operator works and nothing about the router.
"""

from __future__ import annotations

import pytest

from apps.api.retrieval.routing import (
    DEFAULT_INTENT,
    LONG_QUESTION_WORDS,
    ROUTING_TABLE,
    classify,
)

# The four classes the brief names as "answered by the compiled facts", in the words an
# SMB's caller uses. Each is `~80%` of a receptionist's day (TRD §6).
CHEAP_PATH = [
    ("are you open on sunday", "hours"),
    ("what time do you close today", "hours"),
    ("what are your timings", "hours"),
    ("where are you located", "location"),
    ("what is your address", "location"),
    ("is there parking", "location"),
    ("which doctor is available", "staff"),
    ("who is on the team", "staff"),
    ("how much does a root canal cost", "services_pricing"),
    ("what are your fees", "services_pricing"),
    ("can I book an appointment", "booking"),
]

# Questions that are not answerable from one compiled line and must reach a search.
RETRIEVAL_PATH = [
    "what is your cancellation policy",
    "do you accept insurance claims",
    "why do you need a deposit",
    "explain how the treatment works",
    "what is the difference between the two packages",
    "what happens if I miss my slot",
]


@pytest.mark.parametrize(("question", "intent"), CHEAP_PATH)
def test_the_everyday_questions_take_the_cheap_path(question: str, intent: str) -> None:
    """T0 answers these with zero retrieval, which is the whole economic argument for a
    router. FAILS IF: a table edit sends an opening-hours question to a search."""
    decision = classify(question)
    assert decision.tier == "t0"
    assert decision.intent == intent


@pytest.mark.parametrize("question", RETRIEVAL_PATH)
def test_open_ended_questions_earn_a_retrieval(question: str) -> None:
    decision = classify(question)
    assert decision.tier == "t3", decision


def test_a_policy_question_beats_the_booking_row_it_shares_a_word_with() -> None:
    """THE ORDERING TEST, and the reason the t3 rows are first.

    "cancel" is a booking word and "cancellation policy" is not a booking question. If the
    booking row were above the policy row this would answer a policy question out of two
    compiled lines about appointment slots — a commitment made on the client's behalf from
    the wrong source.
    """
    assert classify("what is your cancellation policy").intent == "policy"
    assert classify("I want to cancel my appointment").intent == "booking"


def test_an_unmatched_question_goes_to_retrieval_not_to_the_cheap_path() -> None:
    """THE SAFETY PROPERTY. The table is English and this is a Telugu-first product, so a
    Telugu question matches nothing — and must fall through to "search", never to "the
    answer is already in the prompt".

    FAILS IF: somebody makes the default t0 to save a lookup. That trade answers a question
    nobody looked up as though we had.
    """
    telugu = classify("మీ రద్దు విధానం ఏమిటి")
    assert telugu.tier == "t3"
    assert telugu.intent == DEFAULT_INTENT
    assert telugu.rule is None, "nothing matched, and the decision must say so"


def test_a_long_question_is_open_ended_even_when_it_names_a_cheap_word() -> None:
    """The one non-keyword signal, and it may only route UP."""
    long_question = (
        "we are moving our clinic to a new building next month and I want to know how the "
        "agent should describe the price of a consultation to people who ask about it "
        "before we have finished the move"
    )
    assert len(long_question.split()) > LONG_QUESTION_WORDS
    decision = classify(long_question)
    assert decision.tier == "t3"
    assert decision.rule == "services_pricing", "the matched row is still reported"


def test_a_word_boundary_is_not_a_substring() -> None:
    """`open` must not match `opened`, or every question about an opened account becomes an
    opening-hours question."""
    assert classify("who opened this account").intent == DEFAULT_INTENT
    assert classify("are you open").intent == "hours"


def test_classification_is_deterministic_and_case_insensitive() -> None:
    for question in ("WHAT ARE YOUR HOURS", "what are your hours", "What Are Your Hours?"):
        assert classify(question) == classify("what are your hours")


def test_every_row_is_documented_and_uniquely_named() -> None:
    """The table is edited by humans, so the properties that make it readable are asserted:
    a reason on every row, and one row per intent (two rows sharing an intent would make a
    log line ambiguous about which rule fired)."""
    intents = [rule.intent for rule in ROUTING_TABLE]
    assert len(intents) == len(set(intents))
    for rule in ROUTING_TABLE:
        assert len(rule.why) > 40, f"{rule.intent} has no real reason on it"
        assert rule.phrases, f"{rule.intent} matches nothing"
        assert all(phrase == phrase.lower() for phrase in rule.phrases)


def test_the_router_spends_no_model_call() -> None:
    """The design claim, asserted as a property rather than as a comment: `classify` is a
    pure function of a string. If it ever grew an await, this stops compiling as written —
    which is the point.
    """
    import inspect

    from apps.api.retrieval import routing

    assert not inspect.iscoroutinefunction(routing.classify)
    source = inspect.getsource(routing)
    for forbidden in ("httpx", "chat.", "await ", "openai"):
        assert forbidden not in source, f"the router reached for {forbidden}"
