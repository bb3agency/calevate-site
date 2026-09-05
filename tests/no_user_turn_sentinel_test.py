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


def test_the_constant_matches_the_literal_the_vendor_documents() -> None:
    """The exact string, from the migration guide's own worked example.

    Pinned separately from the tolerant matcher because they answer different questions:
    the matcher asks "could this be the sentinel", this asks "is the sentinel still what
    the vendor said it was". If the vendor changes the wording, the tolerant match keeps
    working for the old string and this test is what says the new one is unhandled.
    """
    assert "No User Turn Detected".lower() == NO_USER_TURN_SENTINEL


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


def test_the_sentinel_guard_cannot_be_bypassed_by_a_second_reader() -> None:
    """FAILS IF: `extracted_data` grows a second parse site.

    The guard above is only as good as its being the ONLY door. Today the vendor's
    `extracted_data` is read in exactly one place and that place hands it to
    `flatten_extracted_data`, so nothing can reach `engine_extracted` without passing the
    sentinel check. A second reader — a listing path that builds its own snapshot, a
    metrics job counting fields, a debug endpoint — would carry the sentence straight past
    it, and would look perfectly reasonable in review.

    This asserts the shape rather than the behaviour, because the behaviour is
    unobservable from outside until the day it is wrong in production.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "apps/api/engine/bolna.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    readers: list[int] = []
    for node in ast.walk(tree):
        # `<something>.get("extracted_data")` or `<something>["extracted_data"]`
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and any(
                isinstance(a, ast.Constant) and a.value == "extracted_data" for a in node.args
            ):
                readers.append(node.lineno)
        elif isinstance(node, ast.Subscript):
            key = node.slice
            if isinstance(key, ast.Constant) and key.value == "extracted_data":
                readers.append(node.lineno)

    assert len(readers) == 1, (
        f"`extracted_data` is now read at lines {sorted(readers)}. Every reader must pass "
        "through `flatten_extracted_data`, which is where the no-user-turn sentinel is "
        "dropped — a second reader carries that sentence into a client's CRM columns."
    )

    # ...and that one reader hands it to the flattener rather than using it raw.
    line = readers[0]
    wrapped = [
        call.lineno
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "flatten_extracted_data"
        and call.lineno == line
    ]
    assert wrapped, (
        f"the only read of `extracted_data` (line {line}) does not go through "
        "`flatten_extracted_data`, so the sentinel is no longer dropped"
    )


def test_no_vendor_summary_is_read_without_the_sentinel_check() -> None:
    """FAILS IF: the adapter starts reading the vendor's top-level `summary`.

    The migration guide warns in terms: *"The top-level `summary` key will return it too.
    Anything writing `summary` into a CRM note, ticket field, or report will write that
    string. Check for it before persisting."*

    We are safe today for a STRUCTURAL reason rather than a checked one — this adapter
    reads no vendor summary at all (`ExecutionSnapshot` has no such field, and the summary
    a client sees is our own pass over the raw transcript). That is a stronger guarantee
    than a check, and a more fragile one: it holds only until somebody wires the vendor's
    summary in, which would look like a free improvement and would carry the sentence into
    every silent call's CRM note.

    So the property is asserted rather than assumed. If the vendor summary is ever wanted,
    this test is the place that says what has to happen first: put it through
    `_is_no_user_turn`, then change this test to expect that.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "apps/api/engine/bolna.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    reads: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and any(
                isinstance(a, ast.Constant) and a.value == "summary" for a in node.args
            ):
                reads.append(node.lineno)
        elif isinstance(node, ast.Subscript):
            key = node.slice
            if isinstance(key, ast.Constant) and key.value == "summary":
                reads.append(node.lineno)

    assert not reads, (
        f"the Bolna adapter now reads a vendor `summary` at line(s) {sorted(reads)}. On a "
        "call where nobody spoke that field carries the no-user-turn sentence, and this "
        "adapter is the only place it can be stopped before it becomes a client's CRM "
        "note. Route it through `_is_no_user_turn` and update this test."
    )
