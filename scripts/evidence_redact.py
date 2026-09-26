"""Hard rule 6 at the last step before an artefact is written to `docs/evidence/`.

Why this exists when `apps/workers/redaction.py` already redacts: an evidence artefact is
committed to the repository, which is forever. A leak there is not a log line that rotates
away; it is a caller's phone number in the permanent history of a shared repository. The
one caller is `scripts/eval.py::write_evidence`, which already masks every value on the way
into a report and runs this as the second layer.

`redact()` from the post-call pipeline does the real work — it carries the validated
Aadhaar/PAN/Luhn/UPI logic and the spoken-digit-word normaliser. On top of it sits ONE extra
sweep this context needs and that one does not: any free-standing run of 7+ digits. The
shared redactor recognises SHAPES, tuned for spoken transcript text where a looser rule
would mask an appointment time or a price; an artefact interpolates ids, counts and
whatever a reporting path happened to format, and a shape-based pattern cannot be complete
over that. `tests/evidence_redact_test.py` asserts the ABSENCE of the digits rather than
which layer masked them, so either layer may own a string.
"""

from __future__ import annotations

import re
from typing import Any

from apps.workers.redaction import redact

#: Any FREE-STANDING run of this many digits is scrubbed, whatever it looks like. Seven
#: because the shortest thing worth protecting here is a subscriber number without its
#: country code; below that the artefact's own content is millisecond counts, ports and
#: byte sizes.
#:
#: "Free-standing" — the lookarounds — exists because a first version masked an engine
#: agent ref: `fakeagent_ee4edcaa460007891e333f44` contains the nine
#: digits `460007891` in the middle of a hex id. Masking ids is not a safe conservative
#: default here, it is a loud false positive on every single line of a healthy run, and
#: an alarm that fires on healthy output is one nobody reads when it fires for real. A
#: phone number is never embedded inside a longer alphanumeric token; a hex id's digit
#: runs always are. An id that is ENTIRELY digits is still masked, deliberately — at that
#: point it is genuinely indistinguishable from a subscriber number and the artefact is
#: permanent.
_LONG_DIGIT_RUN = re.compile(r"(?<![0-9A-Za-z])\d{7,}(?![0-9A-Za-z])")
DIGIT_MASK = "[digits redacted]"


def scrub_text(value: str) -> tuple[str, int]:
    """Redacted text plus the number of substitutions made.

    The COUNT is returned rather than swallowed because a non-zero count is a defect
    report: the reporting path let something through, and the writer should say so loudly
    instead of quietly cleaning up after a caller that will do it again tomorrow.
    """
    result = redact(value)
    cleaned, extra = _LONG_DIGIT_RUN.subn(DIGIT_MASK, result.text)
    return cleaned, len(result.kinds) + extra


def scrub(value: Any) -> tuple[Any, int]:
    """Recursively scrub a JSON-shaped structure. Keys are scrubbed too.

    Keys as well as values because a caller that writes `{"+919876543210": "ok"}` has
    leaked exactly as much as one that writes it the other way round, and a scrubber
    that only looked at values would be a scrubber somebody trusted.
    """
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        total = 0
        for key, item in value.items():
            clean_key, key_hits = scrub_text(str(key))
            clean_item, item_hits = scrub(item)
            out[clean_key] = clean_item
            total += key_hits + item_hits
        return out, total
    if isinstance(value, list | tuple):
        cleaned = []
        total = 0
        for item in value:
            clean_item, hits = scrub(item)
            cleaned.append(clean_item)
            total += hits
        return cleaned, total
    return value, 0


__all__ = ["DIGIT_MASK", "scrub", "scrub_text"]
