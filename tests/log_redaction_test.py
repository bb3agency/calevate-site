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
import uuid

from apps.api.core.logging import redact_mapping, redact_text
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


def test_a_long_digit_run_that_is_not_an_identifier_is_still_masked() -> None:
    """The protection is scoped to identifier SHAPES (a uuid, a 32+ hex digest), not to
    "anything long" — a 20-digit blob in free text is not an id we recognise and gets
    masked, which is the safe direction."""
    masked = redact_text("account 12345678901234567890 mentioned")
    assert "12345678901234567890" not in masked
