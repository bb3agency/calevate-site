"""The log redactor has to mask people without mangling identifiers.

Those two requirements pull against each other, and getting either wrong is expensive
in a different direction. Too loose and a phone number reaches the log stream (hard rule
6). Too greedy and it corrupts the ids a log line exists to carry — which is worse than
it sounds, because the corruption is SILENT and DATA-DEPENDENT: a uuid_v7 is
time-prefixed, so its leading segments are mostly decimal, and whether a given one
happens to contain a phone-shaped digit run is luck. `019fef30-ef78-7420-900b-…`
contains `78-7420-900`.

That is not hypothetical. It surfaced as an audit test that failed on one run and passed
on the next, and the first diagnosis was that an unrelated change had broken it. The
tests below exist so the next person gets a named failure instead of a mystery.
"""

from __future__ import annotations

import hashlib
import sys
import traceback
import uuid
from datetime import UTC, datetime

from apps.api.core.logging import redact_exception, redact_mapping, redact_text
from apps.api.db.base import uuid7

# The exact uuid from the run that exposed this. Kept verbatim rather than generated,
# because the property it demonstrates is a coincidence and a random uuid reproduces it
# only occasionally — which is the whole problem.
MANGLED_UUID = "019fef30-ef78-7420-900b-c603a569b465"


def test_the_uuid_that_started_this_survives_redaction() -> None:
    assert redact_text(MANGLED_UUID) == MANGLED_UUID


def test_no_uuid_v7_is_ever_mangled() -> None:
    """uuid_v7 is the id type this codebase uses everywhere (conventions), so the
    property has to hold for the generator, not just for one lucky example. 500 of them
    is enough that a regression shows up on the first run rather than the fiftieth."""
    for _ in range(500):
        value = str(uuid7())
        assert redact_text(value) == value, f"redaction corrupted {value}"


def test_a_uuid_inside_a_sentence_survives_with_its_neighbours() -> None:
    line = f"claimed outbox row {MANGLED_UUID} for tenant {uuid.uuid4()}"
    assert redact_text(line) == line


def test_a_phone_number_is_still_masked() -> None:
    """The other side of the trade. If protecting ids ever costs us this, the fix is
    wrong — a leaked number is a compliance breach and a mangled id is an inconvenience."""
    for number in (
        "+919876543210",
        "919876543210",
        "9876543210",
        "+91 98765 43210",
        "+91-98765-43210",
    ):
        assert number not in redact_text(f"caller said {number} loudly")
        assert "[phone]" in redact_text(f"caller said {number} loudly")


def test_a_phone_number_next_to_a_uuid_is_still_masked() -> None:
    """The adversarial case for the fix: protecting the uuid must not create a shadow
    the number can hide in."""
    line = f"lead {MANGLED_UUID} phone +919876543210 recorded"
    masked = redact_text(line)
    assert MANGLED_UUID in masked
    assert "9876543210" not in masked
    assert "[phone]" in masked


def test_the_length_cap_measures_what_a_reader_sees() -> None:
    """Truncation runs after the ids are restored, so the 200-char cap describes the
    final text rather than the placeholder form — otherwise the cap would drift with
    however many ids the line happened to contain."""
    masked = redact_text("x" * 500)
    assert masked.endswith("…[truncated]")
    assert len(masked.removesuffix("…[truncated]")) == 200


def test_no_stash_marker_survives_into_the_output() -> None:
    """The placeholder is a NUL sentinel. One leaking into a log line would be invisible
    on a terminal and would corrupt a JSON log parser downstream."""
    line = f"a {MANGLED_UUID} b {uuid7()} c"
    assert "\x00" not in redact_text(line)


def test_an_audit_summary_keeps_its_ids_and_loses_its_numbers() -> None:
    """The end-to-end shape: `write_audit` sends its summary through `redact_mapping`,
    and that summary is how an investigation correlates a log line back to a row."""
    entry_id = str(uuid7())
    summary = redact_mapping(
        {
            "request_id": entry_id,
            "subject_ref": "67f5cc9ca451c598d14313258429e5c9",
            "note": "reached +919876543210 on the second try",
        }
    )
    assert summary["request_id"] == entry_id, "an audit row you cannot correlate is noise"
    assert summary["subject_ref"] == "67f5cc9ca451c598d14313258429e5c9"
    assert "9876543210" not in str(summary["note"])


def test_a_hex_digest_is_not_mistaken_for_a_phone_number() -> None:
    """The same hazard as the uuid, and worse. `subject_ref` is sha256[:32] and is what
    ties a DPDP access request to the erasure that answered it; the audit chain's
    `entry_hash` is what proves the chain was not edited. A digest is a third digits by
    construction, so a phone-shaped run inside one is routine, not unlucky — this exact
    digest contains `14313258429`.
    """
    digest = "67f5cc9ca451c598d14313258429e5c9"
    assert redact_text(digest) == digest
    assert redact_text(f"erased subject {digest} ok") == f"erased subject {digest} ok"

    chain_hash = hashlib.sha256(b"audit").hexdigest()
    assert redact_text(chain_hash) == chain_hash


def test_an_iso_timestamp_is_not_mistaken_for_a_phone_number() -> None:
    """The third identifier shape that is mostly digits and separators, and it was live.

    `2026-08-16` is ten characters of digits and dashes, so the phone pattern matched it
    whole: `billing/plans.py`'s `plan_window_leaves_tenant_unpriced` extra carried
    `"at": ...isoformat()` and rendered as `[phone]T02:00:00+00:00`. A mangled instant is
    worse than a missing one, because it reads as a redaction doing its job and invites
    the reader to believe a caller's number was there.
    """
    for value in (
        "2026-08-16",
        "2026-08-16T09:34:30+00:00",
        "2026-08-16 09:34:30",
        "2026-01-01T00:00:00Z",
    ):
        assert redact_text(value) == value, f"redaction corrupted {value}"
    # The exact spelling the live site produces, so a change to either end shows up here.
    now = datetime.now(UTC).isoformat()
    assert redact_text(f"window closed at {now}") == f"window closed at {now}"


def test_holding_a_date_does_not_open_a_hiding_place_for_a_number() -> None:
    """The adversarial half of the trade, same shape as the uuid case above. The month
    and day ranges are what keep the exemption narrow, and the tail is `(?!\\d)` rather
    than `\\b` so a longer digit run cannot masquerade as a date and take the rest of
    itself with it."""
    assert redact_text("2026-08-1698765432") == "[phone]", "a run that continues is not a date"
    assert redact_text("9812-31-1234") == "[phone]", "day 31 of month 12 only; 31 as month is not"
    assert redact_text("2026-13-16") == "[phone]", "month 13 is not a month"
    assert "9876543210" not in redact_text("booked 2026-08-16 for +919876543210")
    assert "2026-08-16" in redact_text("booked 2026-08-16 for +919876543210")


def test_an_extra_that_is_not_a_string_is_rendered_by_us_and_then_masked() -> None:
    """The branch that used to hand the object straight to `json.dumps(default=str)`.

    A tuple, a set, a model, a `bytes` blob: none of them is a `dict`, a `str` or a
    `list`, so all four fell through unredacted and the object's own `repr()` became the
    log line. Sequences collapse to a count, a RECORD (a model or a dataclass — a bag of
    named fields whose repr IS a payload) collapses to its class name, and anything else
    is stringified by us and then masked. Money and counts have to survive all three:
    the metric recorders ride this path.
    """
    from dataclasses import dataclass
    from decimal import Decimal

    from pydantic import BaseModel

    class Turn(BaseModel):
        speaker: str
        text: str

    @dataclass
    class Lead:
        phone_e164: str
        note: str

    out = redact_mapping(
        {
            "turns": ("naa number +919876543210", "second"),
            "seen": {"+919876543210"},
            "blob": b"naa number +919876543210",
            "amount_inr": Decimal("1234.5600"),
            "rows": 42,
            "ratio": 0.5,
            "nothing": None,
            "turn": Turn(speaker="caller", text="naa peru Ravi, number 9876543210"),
            "lead": Lead("+919876543210", "naa peru Ravi"),
        }
    )
    assert out["turn"] == "<Turn>", "a model's repr is an extraction payload"
    assert out["lead"] == "<Lead>"
    assert "Ravi" not in str(out), "a record's field values never reach the line"
    assert out["turns"] == "[2 items]"
    assert out["seen"] == "[1 items]"
    assert "9876543210" not in str(out["blob"])
    # Money and counts have to survive intact — the metric recorders ride this path.
    assert out["amount_inr"] == "1234.5600"
    assert out["rows"] == 42
    assert out["ratio"] == 0.5
    assert out["nothing"] is None


def test_a_traceback_keeps_its_frames_and_withholds_every_message() -> None:
    """`redact_exception`, both halves.

    The message is prose assembled upstream and no redactor here can prove it is not a
    transcript, so it goes — the same verdict the span exporter reaches for the same
    field. The FRAMES stay, because `redact_text`'s cap is measured from the start of the
    string and used to cut a twelve-frame stack off inside frame three, leaving the one
    durable record of a 500 naming nothing but ASGI middleware.
    """
    spoken = "caller said +919876543210 and her name is Priya"
    try:
        raise ValueError(spoken)
    except ValueError:
        rendered = redact_exception("".join(traceback.format_exception(*sys.exc_info())))

    assert rendered.startswith("Traceback (most recent call last):")
    assert rendered.rstrip().endswith("ValueError: [message withheld]")
    assert "Priya" not in rendered, "a NAME is what redact_text cannot see and why this drops"
    assert "9876543210" not in rendered

    # WHERE, asserted structurally rather than by quoting this file's own source: every
    # `File "…"` line is followed by its indented SOURCE line, which is what makes a
    # withheld message survivable (the reader sees the `raise` itself). Pinning the
    # literal text instead would pin this test to its own line numbers, and CPython
    # renders the frame from the file on disk at render time.
    lines = rendered.splitlines()
    frames = [index for index, line in enumerate(lines) if line.lstrip().startswith('File "')]
    assert frames, "the frames are what say WHERE"
    for index in frames:
        following = lines[index + 1]
        assert following.startswith("  ") and following.strip(), (
            f"frame {lines[index].strip()} lost its source line"
        )
    # The source line is rendered by CPython from the FILE, so a literal written into
    # source would still appear — which is why `_mask` runs over frame lines too, and
    # why the value under test is held in a variable the way real code holds one.


def test_a_runaway_traceback_is_bounded_and_keeps_the_end() -> None:
    """A recursion error renders a thousand identical frames. The cap keeps the head
    (where the request entered) and the TAIL, because the tail is where the exception
    line is — the same reasoning that made a head-measured character cap wrong."""

    # Built rather than raised: CPython COMPRESSES identical repeated frames into
    # `[Previous line repeated N more times]`, so a real recursion produces a short
    # traceback and would test nothing. What the cap is for is a deep stack of DISTINCT
    # frames — an ASGI chain through a worker through an adapter — and this is that
    # shape, rendered exactly as `format_exception` renders it.
    frames = "".join(
        f'  File "/app/apps/api/step_{index}.py", line {index}, in step_{index}\n'
        f"    call_step_{index}()\n"
        for index in range(300)
    )
    rendered = redact_exception(
        "Traceback (most recent call last):\n" + frames + "ValueError: deep\n"
    )

    lines = rendered.splitlines()
    assert len(lines) <= 97, f"unbounded traceback: {len(lines)} lines"
    assert "traceback lines elided" in rendered
    assert lines[-1].endswith("[message withheld]"), "the exception line survives the cap"


def test_a_long_digit_run_that_is_not_an_identifier_is_still_masked() -> None:
    """The protection is scoped to identifier SHAPES (a uuid, a 32+ hex digest), not to
    "anything long" — a 20-digit blob in free text is not an id we recognise and gets
    masked, which is the safe direction."""
    masked = redact_text("account 12345678901234567890 mentioned")
    assert "12345678901234567890" not in masked
