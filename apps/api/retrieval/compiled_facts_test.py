"""The T0 ranker, without a database. The tenancy half is `compiled_facts_rls_test.py`."""

from __future__ import annotations

from apps.api.agents.t0 import T0_HEADER, T0_KNOWLEDGE_MARKER
from apps.api.retrieval.compiled_facts import facts_of, score_line, tokens

BLOCK = "\n".join(
    [
        T0_HEADER,
        "Hours: mon-sat 09:30-18:00; sun closed",
        "Address: 12 Banjara Hills Road No 2, Hyderabad",
        "Service: Root canal — ₹8000",
        "",
        T0_KNOWLEDGE_MARKER,
        "- Fees: A consultation costs 500 rupees and is payable at reception.",
    ]
)


def test_the_block_yields_its_facts_and_neither_of_its_markers() -> None:
    """The header and the section marker are structure, not knowledge. Returning them would
    put "[T0 FACTS]" in front of a client as an answer."""
    lines = facts_of(BLOCK)
    assert T0_HEADER not in lines
    assert T0_KNOWLEDGE_MARKER not in lines
    assert "" not in lines
    assert len(lines) == 4


def test_the_markers_are_imported_rather_than_respelled() -> None:
    """Two modules spelling the same marker is how the block came to have two headers once
    (`tests/t0_recompile_test.py` pins the pair). If `agents/t0.py` renames one, this file
    follows automatically and the parser above cannot silently stop stripping it."""
    assert BLOCK.startswith(T0_HEADER)


def test_a_question_ranks_the_line_that_answers_it_first() -> None:
    question = tokens("what time do you close on sunday")
    ranked = sorted(facts_of(BLOCK), key=lambda line: score_line(question, line), reverse=True)
    assert ranked[0].startswith("Hours:")


def test_a_price_question_finds_the_price_line_not_the_address() -> None:
    question = tokens("how much does a root canal cost")
    scores = {line: score_line(question, line) for line in facts_of(BLOCK)}
    best = max(scores, key=lambda line: scores[line])
    assert "Root canal" in best
    assert scores["Address: 12 Banjara Hills Road No 2, Hyderabad"] == 0.0


def test_a_question_about_nothing_on_file_scores_zero_everywhere() -> None:
    """Which is what makes T4 (refuse and escalate) possible: a zero-scoring question
    returns no passages at all rather than the nearest line."""
    question = tokens("do you sell bicycles")
    assert all(score_line(question, line) == 0.0 for line in facts_of(BLOCK))


def test_scoring_normalises_by_the_question_not_by_the_line() -> None:
    """The argued choice, asserted. Normalising by the LINE would rank a short heading above
    the sentence that answers, because the heading has a higher hit rate while carrying
    less."""
    question = tokens("what does a consultation cost")
    heading = "Fees"
    answer = "- Fees: A consultation costs 500 rupees and is payable at reception."
    assert score_line(question, answer) > score_line(question, heading)


def test_stop_words_and_single_characters_carry_no_signal() -> None:
    assert tokens("what is the a of on") == frozenset()
    assert "x" not in tokens("x ray")


def test_a_telugu_question_tokenises() -> None:
    """`\\w+` is unicode-aware, so a Telugu question ranks on its own content words rather
    than producing an empty token set (which would score every line zero and make T0 look
    broken in the product's first language)."""
    assert tokens("మీ చిరునామా ఏమిటి")


def test_a_digit_is_a_token_because_a_caller_may_ask_about_a_price() -> None:
    assert score_line(tokens("is it 8000 rupees"), "Service: Root canal — ₹8000") > 0.0
