"""Golden-transcript tests for gap detection — the deterministic reader, no DB.

The claim under test: a deflection the agent SPOKE is recognised, the caller-facing quotes
come straight off the (already-redacted) turns, a clean call yields nothing, and a topic
repeated within a call is counted once as a gap with a bumped hit_count. The transcripts
here are the kind the pipeline hands over: `RedactedTurn`s carrying `text_redacted`.
"""

from __future__ import annotations

from apps.api.insights.detection import RedactedTurn, caller_asked, detect_gaps, is_gap


def _turns(*pairs: tuple[str, str]) -> list[RedactedTurn]:
    return [RedactedTurn(speaker=s, text=t) for s, t in pairs]  # type: ignore[arg-type]


def test_a_clear_deflection_is_one_gap_with_the_redacted_quotes() -> None:
    gaps = detect_gaps(
        _turns(
            ("agent", "Namaskaram, how can I help?"),
            ("caller", "How much is the consultation fee?"),
            ("agent", "I don't know the exact price, I'll WhatsApp you the details."),
        )
    )
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.topic_key == "pricing"
    assert gap.topic_label == "Pricing"
    # dont_know wins over the WhatsApp punt in the same turn — the stronger signal.
    assert gap.signal == "dont_know"
    assert gap.question_redacted == "How much is the consultation fee?"
    assert "WhatsApp" in gap.answer_redacted
    assert gap.hit_count == 1


def test_a_clean_transcript_yields_no_gaps() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "How much is the consultation fee?"),
            ("agent", "It is 500 rupees, adjusted against treatment the same day."),
            ("caller", "Great, book me for tomorrow."),
            ("agent", "Done, you are booked for 11am tomorrow."),
        )
    )
    assert gaps == []


def test_a_whatsapp_punt_without_i_dont_know_is_a_deferred_channel_gap() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "Do you deliver to Kukatpally?"),
            ("agent", "Let me have the team WhatsApp you about delivery."),
        )
    )
    assert len(gaps) == 1
    assert gaps[0].topic_key == "delivery"
    assert gaps[0].signal == "deferred_channel"


def test_a_stall_on_a_direct_question_is_an_unanswered_question() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "What are your opening hours on Sunday?"),
            ("agent", "Let me check and get back to you."),
        )
    )
    assert len(gaps) == 1
    assert gaps[0].topic_key == "timings"
    # "get back to you" is a deferred channel and takes precedence over the stall.
    assert gaps[0].signal == "deferred_channel"


def test_a_bare_stall_after_a_question_is_unanswered_not_deferred() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "Where exactly is your clinic located?"),
            ("agent", "Let me check that for you."),
        )
    )
    assert len(gaps) == 1
    assert gaps[0].signal == "unanswered_question"
    assert gaps[0].topic_key == "location"


def test_a_stall_with_no_caller_question_is_not_a_gap() -> None:
    # "let me check" against a statement, not a question, is an ordinary working turn.
    gaps = detect_gaps(
        _turns(
            ("caller", "I already paid for my order."),
            ("agent", "Let me check your order."),
        )
    )
    assert gaps == []


def test_a_deflection_with_no_preceding_caller_turn_is_skipped() -> None:
    gaps = detect_gaps(_turns(("agent", "I don't know, honestly.")))
    assert gaps == []


def test_the_same_topic_twice_in_one_call_is_one_gap_with_hit_count_two() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "How much for a cleaning?"),
            ("agent", "I don't know that price."),
            ("caller", "And the cost of a filling?"),
            ("agent", "I'm not sure about that cost either."),
        )
    )
    assert len(gaps) == 1
    assert gaps[0].topic_key == "pricing"
    assert gaps[0].hit_count == 2
    # The example is the FIRST occurrence's quote.
    assert gaps[0].question_redacted == "How much for a cleaning?"


def test_a_telugu_dont_know_is_detected() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "Warranty enni years untundi?"),
            ("agent", "Adi naaku teliyadu andi."),
        )
    )
    assert len(gaps) == 1
    assert gaps[0].topic_key == "warranty"
    assert gaps[0].signal == "dont_know"


def test_two_different_topics_in_one_call_are_two_gaps() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "What are your timings?"),
            ("agent", "I don't know the timings."),
            ("caller", "And do you offer any discount?"),
            ("agent", "I'm not sure about offers."),
        )
    )
    keys = {gap.topic_key for gap in gaps}
    assert keys == {"timings", "offers"}


def test_an_unmapped_question_still_becomes_a_gap_under_a_phrase_label() -> None:
    gaps = detect_gaps(
        _turns(
            ("caller", "Can you service Bajaj Pulsar bikes?"),
            ("agent", "I don't know, I'll find out."),
        )
    )
    assert len(gaps) == 1
    # No canonical keyword matched, so the topic is derived from the caller's content words.
    assert gaps[0].topic_key.startswith("q_")
    assert gaps[0].signal == "dont_know"


#: The Rytu Khata call of 4 Nov 2026 at 0:46, in English (the call was in Telugu): the caller
#: agreed to try the app and the agent's next line gave the business's WhatsApp number. The
#: agreement was listed as a question the agent could not answer.
RYTU_KHATA_AGREEMENT = (
    ("agent", "Open the app and tap Dashboard at the bottom to write an expense."),
    ("caller", "I will try."),
    (
        "agent",
        "Good. If you have any doubt, message us on WhatsApp at nine eight seven six five, "
        "four three two one zero. Anything else?",
    ),
    ("caller", "Say the number again."),
    ("agent", "Nine eight seven six five, four three two one zero, on WhatsApp."),
    ("caller", "Say it a bit slowly."),
    ("agent", "Nine. Eight. Seven. Six. Five. Four. Three. Two. One. Zero. On WhatsApp."),
    ("caller", "Written it down. Nothing else."),
)


def test_an_agreement_followed_by_a_whatsapp_number_is_no_gap() -> None:
    assert detect_gaps(_turns(*RYTU_KHATA_AGREEMENT)) == []


def test_only_a_line_that_asks_for_something_can_be_a_gap() -> None:
    for said in ("I will try.", "Okay.", "Thank you.", "Yes, I installed it."):
        assert not caller_asked(said), said
    for said in ("Say the number again?", "Can you repeat that?", "Say it slowly."):
        assert not caller_asked(said), said
    assert caller_asked("How do I add an expense?")
    assert caller_asked("Do you deliver on Sunday")
    assert is_gap("I will try.", "Message us on WhatsApp if you need help.") is None
    assert is_gap("What does it cost?", "Message us on WhatsApp for the price.") == (
        "deferred_channel"
    )


#: The audit's probe lines (L5-05, 5 Nov 2026): agreements and plans, none of them a question.
#: The Telugu two are the audit's own probe ("somehow I'll try", "saw it somewhere, I'll try"):
#: a question word with an ending fused on is another word.
NOT_QUESTIONS = (
    "ఎలాగైనా ట్రై చేస్తాను",
    "ఎక్కడో చూసాను, ట్రై చేస్తా",
    "I will try when I get time",
    "ok I will try what you said",
    "naaku help kavali ante cheptanu",
    "I will try.",
)


def test_a_question_word_inside_a_plan_or_a_longer_word_asks_nothing() -> None:
    for said in NOT_QUESTIONS:
        assert not caller_asked(said), said
        assert is_gap(said, "Message us on WhatsApp if you need help.") is None, said


def test_questions_are_still_heard_in_every_shape() -> None:
    for said in (
        "What is the price",
        "ok, how do I add an expense",
        "Is there parking",
        "tell me the timings",
        "I want to know the fee",
        "price enta",
        "delivery eppudu",
        "Where is your office",
    ):
        assert caller_asked(said), said


def test_sending_what_was_asked_for_is_the_answer_not_a_gap() -> None:
    """L5-06: for a business whose answer is a link on WhatsApp, sending it answers."""
    assert is_gap("How do I install the app?", "Sure, I'll send you the link on WhatsApp now.") is None
    assert is_gap("How do I install the app?", "Please message us on WhatsApp.") == (
        "deferred_channel"
    )


def test_a_call_back_the_caller_asked_for_is_not_a_punt() -> None:
    assert is_gap("Can you call me back tomorrow?", "Sure, we will call you back tomorrow.") is None
    assert is_gap("What is the warranty?", "The team will call you back about that.") == (
        "deferred_channel"
    )
