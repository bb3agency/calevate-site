"""Golden-transcript tests for gap detection — the deterministic reader, no DB.

The claim under test: a deflection the agent SPOKE is recognised, the caller-facing quotes
come straight off the (already-redacted) turns, a clean call yields nothing, and a topic
repeated within a call is counted once as a gap with a bumped hit_count. The transcripts
here are the kind the pipeline hands over: `RedactedTurn`s carrying `text_redacted`.
"""

from __future__ import annotations

from apps.api.insights.detection import RedactedTurn, detect_gaps


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
