"""The one way a data-rights request names a person.

WHY THIS EXISTS. `/v1/compliance/subject-export` and `/v1/compliance/deletion-requests`
both required strict E.164 (`^\\+[1-9]\\d{7,18}$`) while the form in front of them told the
client "Ten digits, or the full number starting with +" — and every other phone surface in
the product (`/v1/dnc`, the national-DND upload, ingest) takes the number as pasted and
lets `ingest.normalize_phone` decide. So the two endpoints a data principal's rights run
through were the two that refused the form's own instruction, with a 422 whose message
named a regular expression.

That is worse than a papercut. A client relaying somebody's erasure request types the
number the way it was read out to them; being told their input is invalid, on a screen
about a legal obligation, is a reason to give up on filing it at all.

ONE NORMALIZER, NOT A SECOND PATTERN. `normalize_phone` is already the single door from a
raw string to E.164 (`compliance/caller_ref.py:153` says so in as many words), it refuses
to guess a country, and it re-checks its own output. Reproducing a laxer regex here would
be a second way to do one thing — the drift this repo treats as a defect even when both
halves work.

WHAT IT STILL REFUSES. Everything `normalize_phone` refuses: a number with no country we
can infer, a malformed one, a `++91`. The security argument for these endpoints is "one
phone number and nothing else", and that is unweakened — normalising happens before the
value reaches any query, so what the handler receives is E.164 exactly as before.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field

from apps.api.ingest.service import normalize_phone

#: The message a person reads when we cannot make sense of what they typed. No pattern, no
#: field name, no "E.164" — it says what to do instead, which is the only part they can act
#: on.
UNREADABLE = (
    "We could not read that as a phone number. Enter the ten digits of an Indian mobile, "
    "or the full number starting with + and the country code."
)


def _to_e164(raw: str) -> str:
    normalized = normalize_phone(raw)
    if normalized is None:
        raise ValueError(UNREADABLE)
    return normalized


#: A phone number as a human typed it, normalized to E.164 before the handler sees it.
#: The length bounds are a cheap ceiling on what reaches the normalizer at all; the
#: normalizer, not the bounds, is what decides whether the value is a number.
SubjectPhone = Annotated[str, Field(min_length=8, max_length=32), AfterValidator(_to_e164)]
