"""`redact()`'s phone patterns, against the forms this product actually holds.

Hard rule 6 is enforced by one function, and until this file existed nothing tested that
function's patterns directly — the suites around it asserted that `redact()` was CALLED
(`call_summary_redaction_test`), never that it WORKED on a given shape. A rule enforced
by a helper nobody unit-tests is enforced by whoever last read the regex.

**The defect that prompted this file.** The pattern was

    (?:\\+91[ -]?)?\\b([6-9]\\d{9})\\b

and the `\\b` after the optional `+91` can never match when the prefix is present with no
separator, because `1` and `9` are both word characters and there is no boundary between
them. So the country-code branch was dead for exactly the format the product stores —
`leads.phone_e164`, and CLAUDE.md's "Phone: E.164 strings" — and it was live: the hot-lead
notification composes `Phone: {redact(phone).text}` from `l.phone_e164`, under a docstring
reading "The phone is masked even here… an email forwarded outside the business is not".
The comment asserted precisely the property that was false, and the email carried the
caller's full number.

Found by a pilot slice planting PII into a payload and asserting none of it reached the
artifact, which is the only reason anybody looked.
"""

from __future__ import annotations

import pytest
from apps.workers.notifications import _compose
from apps.workers.redaction import redact

#: An invented number in the range Indian mobiles occupy (leading 6-9, ten digits). Every
#: spelling below is the SAME subscriber — which is the point: a redactor that masks one
#: spelling and not another has not masked the number, it has masked one way of writing it.
NATIONAL = "9876543210"
LAST_TWO = "••10"


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param("+919876543210", id="e164-no-separator"),
        pytest.param("+91 9876543210", id="e164-space"),
        pytest.param("+91-9876543210", id="e164-hyphen"),
        pytest.param("919876543210", id="country-code-bare"),
        pytest.param("9876543210", id="national"),
        pytest.param("call +919876543210 now", id="e164-mid-sentence"),
        pytest.param("my number is 9876543210.", id="national-before-full-stop"),
    ],
)
def test_every_spelling_of_one_number_is_masked(spelling: str) -> None:
    out = redact(spelling).text
    assert NATIONAL not in out, out
    assert "919876543210" not in out, out
    # The mask is lossy ON PURPOSE — the last two digits stay so staff can recognise the
    # lead they are looking at (see the module docstring in apps/workers/redaction.py).
    assert LAST_TWO in out, out


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("order 123456789012 shipped", id="twelve-digits-not-a-phone"),
        pytest.param("1234567890", id="ten-digits-wrong-leading-digit"),
        pytest.param("invoice 2026 total 4500", id="ordinary-numbers"),
    ],
)
def test_a_number_that_is_not_a_phone_is_left_alone(text: str) -> None:
    """The other half, and the one a wider pattern would break.

    Masking everything ten digits long would eat order ids and invoice totals out of a
    client's own call summaries, which is data loss dressed as privacy. Indian mobile
    numbers lead with 6-9; nothing here does, or nothing here is ten digits.
    """
    assert redact(text).text == text


def test_the_hot_lead_email_masks_the_number_it_was_given() -> None:
    """The leak site itself, asserted end to end rather than through the primitive.

    `_compose` is handed `leads.phone_e164` straight from the query in
    `notifications.py`, so this is the exact value a client's inbox would have received.
    An email is the most forwardable artifact this product creates: it leaves the
    role-checked CRM by design, which is what its own docstring says the masking is for.
    """
    body = _compose(
        name="Sri Clinic",
        phone=f"+91{NATIONAL}",
        status="hot",
        summary=None,
        triggers=["asked for pricing"],
    )
    assert NATIONAL not in body, body
    assert f"+91{NATIONAL}" not in body, body
    assert LAST_TWO in body, body


def test_the_summary_in_that_email_is_redacted_too() -> None:
    """A caller who reads their number aloud puts it in the SUMMARY, not the phone field.

    Two independent paths into one email; masking the structured field while passing the
    prose through would leak the same digits one line lower.
    """
    body = _compose(
        name=None,
        phone=f"+91{NATIONAL}",
        status="hot",
        summary=f"Caller asked us to ring {NATIONAL} instead.",
        triggers=[],
    )
    assert NATIONAL not in body, body
