"""The "why there is no circuit breaker" pointer has to land on the argument.

**THE DEFECT THIS PINS ALREADY HAPPENED.** `engine/bolna.py`'s module docstring told the
reader that the breaker `SURFACES §3.3` describes is deliberately not built and sent them
to "the throttle block below for what is and is not retried, and why" — a block that
discusses 429 handling and says nothing about a breaker. The pointer was not broken in a
way any tool could see: both halves existed, they were simply about different questions,
and the reader arrived at an answer to the one they had not asked.

So the pointer is checked the only way a prose pointer can be: the file it names must
exist and must actually carry the argument. Grepping for the SUBJECT (a breaker, and the
slowness case that is the uncovered one) rather than for a sentence, so rewriting the
paragraph is free and deleting it is not.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BOLNA = REPO_ROOT / "apps" / "api" / "engine" / "bolna.py"
VENDOR_HTTP = REPO_ROOT / "apps" / "api" / "engine" / "vendor_http.py"


def _docstring_of(path: Path) -> str:
    """The module docstring, read as text — the pointer lives in prose, not in an AST."""
    body = path.read_text(encoding="utf-8")
    opened = body.index('"""')
    return body[opened + 3 : body.index('"""', opened + 3)]


def test_bolnas_breaker_paragraph_points_at_the_file_that_holds_the_argument() -> None:
    paragraph = _docstring_of(BOLNA)
    assert "circuit breaker" in paragraph.lower()
    assert "vendor_http.py" in paragraph, (
        "the breaker paragraph must name the file the argument lives in; it previously "
        "said 'the throttle block below', which was in this file and was about retries"
    )
    assert VENDOR_HTTP.exists()


def test_the_argument_answers_the_case_that_is_actually_uncovered() -> None:
    """SLOWNESS, not 429. `REQUEST_TIMEOUT_S` bounds one call and never the aggregate, so
    a vendor answering every request in nine seconds trips no ladder while holding every
    caller — that is the shape a breaker would be for, and the decision not to build one
    is only honest if it is the shape the argument addresses."""
    text = VENDOR_HTTP.read_text(encoding="utf-8")
    breaker_at = text.lower().index("circuit breaker")
    throttle_at = text.index("THROTTLE_STATUS = 429")
    argument = text[breaker_at:throttle_at]
    assert "SLOWNESS" in argument
    # The two bounds the decision rests on. If either stops being the reason, the decision
    # has to be re-made rather than re-worded — so they are named here, not paraphrased.
    assert "_tick_lease" in argument
    assert "_outbound_pool" in argument
