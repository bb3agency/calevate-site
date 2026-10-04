"""The "why there is no circuit breaker" argument has to address the uncovered case.

An adapter docstring once pointed readers at a block that discussed 429 handling and said
nothing about a breaker, so the argument now lives in one place, `vendor_http.py`, the
ladder every adapter shares. This greps for the SUBJECT (a breaker, and the slowness case
that is the uncovered one) rather than for a sentence, so rewriting the paragraph is free
and deleting it is not.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_HTTP = REPO_ROOT / "apps" / "api" / "engine" / "vendor_http.py"


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
    assert "outbound_line_pool" in argument
