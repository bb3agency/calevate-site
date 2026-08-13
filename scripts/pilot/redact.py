"""Hard rule 6 at the pilot harness's only exit — the last thing before bytes leave.

Why this file exists at all, when `apps/workers/redaction.py` already redacts: the
pilot's output is a file an operator commits to `docs/evidence/`. Git is forever, the
repo is shared, and the harness is the one thing in this system that handles a REAL
caller number (`--to`) and a REAL transcript (Get Execution) on a laptop, outside every
API response path that hard rule 5 already defends. A leak here is not a bad log line
that rotates away in a week; it is a caller's phone number in the permanent history of
a repository.

TWO LAYERS, DELIBERATELY, AND THEY ARE TESTED SEPARATELY:

1. **Gates never put PII into a result in the first place.** They report field NAMES,
   ids and counts — "`to_e164` differs between the webhook and Get Execution" is the
   finding; the two numbers are not. `tests/pilot_redaction_test.py` asserts this
   against RAW GateRun objects, before this module ever runs, because a test that
   only checks the scrubbed output would pass just as happily if layer 1 were deleted.
2. **This scrubber, as defence in depth**, on the serialized artefact.

`redact()` from the post-call pipeline does the real work — one way per problem, and it
carries the validated Aadhaar/PAN/Luhn/UPI logic plus the spoken-digit-word normaliser
that a fresh regex here would not. On top of it sits ONE extra sweep this context needs
and that one does not: any run of 7+ digits.

That sweep is not belt-and-braces, it is load-bearing, and here is the concrete case.
The pipeline's phone pattern is `(?:\\+91[ -]?)?\\b([6-9]\\d{9})\\b` — an Indian mobile
with an OPTIONAL country code — and on the E.164 string this harness actually handles,
`+919876543210`, it does not match at all: there is no word boundary anywhere inside a
continuous digit run, so the `\\b` after the optional `+91` can never be satisfied. It
is right for what it guards (spoken transcript text, where a looser rule would mask
appointment references and prices out of every Telugu call) and wrong for what this
guards (E.164 strings, and possibly not Indian ones — a vendor trial dials whatever
number the founder could buy). Different input, different threshold.
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
#: "Free-standing" — the lookarounds — was added after the first run of this harness
#: masked an engine agent ref: `fakeagent_ee4edcaa460007891e333f44` contains the nine
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
    report: layer 1 let something through, and the run should say so loudly instead of
    quietly cleaning up after a gate that will do it again tomorrow.
    """
    result = redact(value)
    cleaned, extra = _LONG_DIGIT_RUN.subn(DIGIT_MASK, result.text)
    return cleaned, len(result.kinds) + extra


def scrub(value: Any) -> tuple[Any, int]:
    """Recursively scrub a JSON-shaped structure. Keys are scrubbed too.

    Keys as well as values because a gate that writes `{"+919876543210": "ok"}` has
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


def call_ref(handle: str) -> str:
    """How a call is named in output: its ENGINE EXECUTION ID, never its number.

    Exists as a named function rather than as a convention so the intent survives the
    next person: the execution id is the only identifier that is both useful to an
    operator (it is what `GET /executions/{id}` takes) and not personal data.
    """
    return handle


__all__ = ["DIGIT_MASK", "call_ref", "scrub", "scrub_text"]
