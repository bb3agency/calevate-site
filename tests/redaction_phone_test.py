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

import re

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
        # The spellings a HUMAN writes, none of which the contiguous-run pattern could
        # see. These are not exotic: 5+5 is how an Indian mobile is printed on a visiting
        # card, and the trunk-0 form is how it is dictated over the phone. Each of them
        # was reaching `text_redacted` — the field hard rule 5 promises is safe in every
        # API response and export — in full.
        pytest.param("98765 43210", id="grouped-5-5"),
        pytest.param("+91 98765 43210", id="e164-grouped-5-5"),
        pytest.param("9876-543-210", id="grouped-4-3-3-hyphen"),
        pytest.param("98765-43210", id="grouped-5-5-hyphen"),
        pytest.param("09876543210", id="trunk-zero"),
        pytest.param("098765 43210", id="trunk-zero-grouped"),
        pytest.param("ring 98765 43210 before 6", id="grouped-mid-sentence"),
    ],
)
def test_every_spelling_of_one_number_is_masked(spelling: str) -> None:
    out = redact(spelling).text
    assert NATIONAL not in out, out
    assert "919876543210" not in out, out
    # Separators are not protection. `98765 43210` is the same subscriber as
    # `9876543210`, so the check has to be made against the digits rather than against
    # the spelling — otherwise every grouped case here passes while leaking.
    assert NATIONAL not in re.sub(r"\D", "", out), out
    # The mask is lossy ON PURPOSE — the last two digits stay so staff can recognise the
    # lead they are looking at (see the module docstring in apps/workers/redaction.py).
    assert LAST_TWO in out, out


#: A Hyderabad landline: trunk 0 + STD 40 + eight-digit subscriber. Nothing in the old
#: pattern covered STD-code numbers at all, so a receptionist reading back the clinic's
#: own landline — or a caller giving theirs — went into `text_redacted` in full.
LANDLINE_NATIONAL = "4023456789"


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param("04023456789", id="landline-trunk-zero"),
        pytest.param("+914023456789", id="landline-e164"),
        pytest.param("+91 40 2345 6789", id="landline-e164-grouped"),
        pytest.param("040 2345 6789", id="landline-trunk-grouped"),
        pytest.param("040-23456789", id="landline-trunk-hyphen"),
        pytest.param("call 04023456789 for the clinic", id="landline-mid-sentence"),
    ],
)
def test_a_landline_that_says_it_is_a_phone_is_masked(spelling: str) -> None:
    """Landlines are masked when the text marks them as phones, and only then.

    DoT's 2003 National Numbering Plan gives a landline the same 10 national digits as a
    mobile (STD code 2-4 digits + subscriber 6-8), but its leading digit is 1-8, which is
    also what an order id or an invoice reference leads with. The `+91` and the trunk `0`
    are the difference between "this is a number" and "this is a phone number".
    """
    out = redact(spelling).text
    assert LANDLINE_NATIONAL not in re.sub(r"\D", "", out), out
    assert "••89" in out, out


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("order 123456789012 shipped", id="twelve-digits-not-a-phone"),
        pytest.param("1234567890", id="ten-digits-wrong-leading-digit"),
        pytest.param("invoice 2026 total 4500", id="ordinary-numbers"),
        # The cases a SEPARATOR-TOLERANT pattern breaks, which is the whole cost of this
        # fix. Once spaces and hyphens may sit inside a number, a run of unrelated
        # numbers is indistinguishable from a grouped phone unless the grouping itself
        # is constrained: no single-digit groups, never a two-digit group last, and at
        # most four groups in all. Each of the three is what stops one line below.
        pytest.param("9500 3000 25", id="three-amounts-summing-to-ten-digits"),
        pytest.param("quotes 8 500 750 300", id="a-stray-digit-beside-three-amounts"),
        pytest.param("slots 6 7 8 9 10 11 12 13", id="a-list-of-small-numbers"),
        pytest.param("order 12345 67890", id="grouped-ten-digits-wrong-leading-digit"),
        pytest.param("4023456789", id="bare-landline-is-not-distinguishable"),
        pytest.param("20-08-2026 4500 12", id="a-date-beside-an-amount"),
        pytest.param("Reference 234123412345", id="twelve-digits-failing-verhoeff"),
    ],
)
def test_a_number_that_is_not_a_phone_is_left_alone(text: str) -> None:
    """The other half, and the one a wider pattern would break.

    Masking everything ten digits long would eat order ids and invoice totals out of a
    client's own call summaries, which is data loss dressed as privacy. Indian mobile
    numbers lead with 6-9; nothing here does, or nothing here is ten digits, or nothing
    here is grouped the way a phone number is written.
    """
    assert redact(text).text == text


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("15-08 9876543210", id="date-then-phone"),
        pytest.param("20-08-2026 9876543210", id="full-date-then-phone"),
        pytest.param("meet 15-08, ring 98765 43210", id="date-then-grouped-phone"),
        # The mirror image: the phone comes FIRST and the stray number after it. The
        # widest window here is twelve digits and invalid, so the matcher has to try a
        # shorter one at the same starting group rather than only a later one.
        pytest.param("ring 9876543210 12", id="phone-then-stray-number"),
    ],
)
def test_a_number_beside_a_phone_does_not_hide_the_phone(text: str) -> None:
    """The failure mode a greedy separator-tolerant pattern hands you for free.

    `15-08 9876543210` is one unbroken run of digits and separators, so a greedy match
    takes all fourteen digits, fails the numbering plan on the total, and leaves the
    phone number in the clear — a WIDER pattern that leaks where the narrow one did not.
    The matcher therefore retries from each digit group instead of giving up on the span.
    """
    out = redact(text).text
    assert NATIONAL not in re.sub(r"\D", "", out), out
    assert LAST_TWO in out, out


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
