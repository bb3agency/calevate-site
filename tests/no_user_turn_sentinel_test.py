"""A call in which nobody spoke must produce no extracted fields, not a sentence in each.

THE CHANGE THIS ANSWERS. Bolna's deprecation notice of 3 Sep 2026 says that from
18 September 2026, on a call with no user turns — voicemail, an immediate hangup, a ring
the platform still reports `completed` — every extraction and the summary come back
carrying a fixed sentence instead of a model's guess. The vendor made that change to stop
its own model hallucinating into a silence, which is right; the hazard moves to us.

WHAT A PASSTHROUGH WOULD HAVE DONE. `engine_extracted` is a flat `{field: value}` map, and
on an outbound campaign silent calls are not the rare case, they are most of the dials. So
the sentence would land in every column a client configured: a lead named
"No User Turn Detected", a callback number that is a sentence, an outcome tag that is an
apology — on most rows in the CRM, looking exactly like extracted data. Pilot gate 7 would
PASS those calls, because it compares field NAMES and every name would be present. A false
pass on a fidelity gate is worse than a false fail: it is read as the vendor working.

EVIDENCE CLASS: VENDOR-PUBLISHED, from an email, NOT from a page anyone here has read.
`bolna-findings/mirror/` predates the announcement and `www.bolna.ai` is egress-blocked
from this container, so the migration guide has not been opened. The match is therefore
case- and space-insensitive: an email's casing is not a wire contract, and a sentinel we
fail to recognise becomes a client's data, while one we over-match costs an empty map that
already means "no extraction ran". OPERATIONS §2 gate 43h is the re-verification.

Run: uv run pytest tests/no_user_turn_sentinel_test.py -q
"""

from __future__ import annotations

import pytest
from apps.api.engine.bolna import NO_USER_TURN_SENTINEL, flatten_extracted_data


@pytest.mark.parametrize(
    "spelling",
    [
        "No User Turn Detected",
        "no user turn detected",
        "NO USER TURN DETECTED",
        "  No User Turn Detected  ",
    ],
)
def test_the_sentinel_is_not_a_value_however_it_is_spelled(spelling: str) -> None:
    """FAILS IF: the sentence reaches a CRM column.

    Spelling variants are asserted because the exact casing is known only from an email.
    A sentinel we fail to recognise is the failure that costs a client's data.
    """
    nested = {
        "Lead": {
            "Name": {"objective": spelling, "subjective": ""},
            "Callback Number": {"objective": "", "subjective": spelling},
        }
    }
    assert flatten_extracted_data(nested) == {}


def test_a_flat_payload_carrying_the_sentinel_is_also_empty() -> None:
    """The older flat shape too — both are live in payloads today, per the same notice."""
    assert flatten_extracted_data({"lead_name": NO_USER_TURN_SENTINEL, "interested": None}) == {
        "interested": None
    }


def test_a_real_answer_beside_a_sentinel_survives() -> None:
    """FAILS IF: one sentinel empties the whole map.

    The notice says every extraction carries it on a silent call, so this should not occur
    — but "should not occur" is not "cannot", and throwing away a real extracted value
    because a sibling field was blank would be the more expensive mistake of the two.
    """
    nested = {
        "Lead": {
            "Name": {"objective": "Ravi Kumar", "subjective": ""},
            "Notes": {"objective": "", "subjective": "No User Turn Detected"},
        }
    }
    assert flatten_extracted_data(nested) == {"Name": "Ravi Kumar"}


def test_values_that_merely_resemble_the_sentinel_are_kept() -> None:
    """FAILS IF: the match widens into real speech.

    A caller can say something containing these words. Only the whole value, trimmed,
    counts — a substring match here would silently delete what somebody actually said.
    """
    nested = {
        "Lead": {
            "Notes": {
                "objective": "",
                "subjective": "Caller said no user turn detected on their old system",
            }
        }
    }
    assert flatten_extracted_data(nested) == {
        "Notes": "Caller said no user turn detected on their old system"
    }


def test_false_and_zero_are_still_answers() -> None:
    """The regression this sits next to: a truthiness test here would drop them."""
    assert flatten_extracted_data({"user_interested": False, "calls": 0}) == {
        "user_interested": False,
        "calls": 0,
    }
