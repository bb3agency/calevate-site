"""Defects the M3 suite growth found, pinned where they cannot be forgotten.

Growing the regression suite towards OPERATIONS §3's 50-100 scenarios per client turned
up five real gaps (six pins below: two of them share one root cause). None is fixed
here — this change owns the eval harness, not `apps/` — and none is papered over
either, because the two obvious ways to make them disappear are both dishonest:

- **Shipping them as golden fixtures** would put `make eval-ci` permanently red. The
  kinds these fail on (`redaction`, `restraint`, `capture_wrong`) are unwaivable BY
  DESIGN — the baseline exists for a weaker model missing a field, never for our own
  code leaking PII — so the ratchet has no honest way to absorb them, and D-29's rule
  is that the gate fails on a REGRESSION, not on absolute red.
- **Writing the scenario around them** — a Hindi caller who never reads a number aloud,
  a caller who never denies the thing they just said — is writing fixtures that fit the
  scorer, which is the failure mode this whole file set exists to prevent.

So they are strict xfails: the DESIRED behaviour is written down and runs on every
push, the suite stays green while it is false, and the day somebody fixes the underlying
code `xfail_strict` (pyproject) turns the XPASS into a failure that says "promote this
into `tests/fixtures/golden_transcripts.json` now". That is the same device this repo
already uses for `kb_tiers_test` and `authz_audit_test`, applied to quality.

Severity is NOT equal across them. Gap 1 is a live PII leak on the real call path
for every Hindi-speaking caller; the rest are the deterministic fallback extractor and
a missing compliance seam. Read the docstrings, not the count.

**Status: every pin in this file has now been promoted.** Gap 1 (redaction), gaps 2-4
(the offline extractor) and gap 5 (the in-call opt-out that never reached the DNC list)
are all fixed, and their assertions run as ordinary tests plus scored fixtures — the
promotion this file's whole device was built to force. What remains here is the RECORD:
each gap keeps a comment saying what it was and where its assertion went, because a fix
with no trace of what it fixed is how the next session re-derives the same defect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.workers.extraction import OfflineExtractor
from calevate_shared.extraction import ExtractionSchemaSpec

REPO = Path(__file__).resolve().parent.parent


def _union_schema() -> ExtractionSchemaSpec:
    """The suite's own schema, so a pin here scores the columns a client really has."""
    payload = json.loads(
        (REPO / "tests" / "fixtures" / "golden_transcripts.json").read_text(encoding="utf-8")
    )
    return ExtractionSchemaSpec(version=1, fields=payload["schema"])


async def _offline(transcript: str) -> dict[str, Any]:
    return await OfflineExtractor().run(_union_schema(), transcript)


# --- Gap 1: FIXED, and left here as a pointer ------------------------------------
#
# Hindi digit words survived redaction — `_DIGIT_WORDS` mapped English and Telugu only,
# so a Hindi-speaking caller reading their number aloud reached `text_redacted` in full
# while the same caller in Telugu was masked. Fixed in apps/workers/redaction.py; the
# assertion moved to `redaction_test.py::test_spoken_digits_in_hindi_are_caught_too`,
# beside the English/Telugu case it belongs with, rather than living on here as a gap
# that is no longer a gap. Kept as a comment because this file's value is the record of
# what the red-team set found, and a fix with no trace of what it fixed is how the next
# session re-derives the same leak.


# --- Gaps 2-4: FIXED, one property, and kept here as the record -------------------
#
# The four assertions below were strict xfails. They are not any more, and they were not
# four bugs: the offline extractor took the FIRST thing that matched and had no way to
# ask whether a later clause revoked it — a denied enum, a superseded requirement, a
# self-corrected name and a topic word read as a consent are that one hole seen from
# four sides. `apps/workers/extraction.py` now decides every field through one scan
# (`_mentions` + `_settled`): for each candidate value the caller's LAST word on it
# decides whether it stands, a negation in its clause means it does not, and the field
# takes the last value still standing. They stay in this file, promoted, because the
# value of this file is the record of what the red-team set found — and because a test
# that lives beside the gap it closed is how the next session learns the gap existed.
#
# All four are now scored by the suite too, as `cl_do_not_cancel_the_appointment`,
# `re_spouse_takes_the_phone`, `cl_self_corrected_name` and
# `re_site_address_is_not_a_visit` in `tests/fixtures/golden_transcripts.json`, which is
# what makes them a RATCHET rather than four unit tests somebody can delete.


async def test_a_cancellation_the_caller_refused_is_not_filed_as_one() -> None:
    """'Naa appointment cancel cheyakandi' is a caller asking us NOT to cancel. Filing
    intent=cancel off the word alone cancels a real appointment — the restraint failure
    with the most expensive consequence in the clinic vertical, and the reason the
    denial rule was written for booleans in the first place."""
    data = await _offline(
        "agent: Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.\n"
        "caller: Naa appointment cancel cheyakandi, adi alaage unchandi."
    )
    assert data.get("intent") != "cancel"


async def test_a_requirement_the_caller_replaced_is_not_the_one_filed() -> None:
    """Written as a golden fixture first (`re_spouse_takes_the_phone`), pulled back to
    here when it turned out to fail as a `capture_wrong`, and now returned to the suite:
    the phone changes hands, the second speaker says 3BHK and that 2BHK will not do, and
    the extractor filed 2BHK. A wrong size sends this household every listing they have
    just ruled out — unwaivable on every model, which is why it could not sit in the
    suite until it was fixed."""
    data = await _offline(
        "agent: Namaskaram, idi Skyline Ventures AI assistant. Ee call record avutundi.\n"
        "caller: 2BHK gurinchi adagataniki chesanu... maa aavida matladatharu.\n"
        "caller: Manaki 3BHK ne kavali, 2BHK saripodu."
    )
    assert data.get("bhk_size") == "3BHK"


# --- Gap 3: a self-corrected name keeps the first version ------------------------


async def test_a_self_corrected_name_keeps_the_correction() -> None:
    """Self-correction is ordinary phone speech, not an edge case, and this one is a
    `capture_wrong` rather than a miss: the CRM row carries a confident name that the
    caller explicitly retracted, and staff greet them by it."""
    data = await _offline(
        "agent: Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.\n"
        "caller: Naa peru Ravi, kaadu kaadu — naa peru Raviteja andi."
    )
    assert data.get("name") == "Raviteja"


# --- Gap 4: a word in the transcript becomes a consent -----------------------------


async def test_asking_for_an_address_is_not_agreeing_to_a_site_visit() -> None:
    """A caller asking where the site is has agreed to nothing. `site_visit_interest`
    is the conversion event a real-estate client pays for and staffs a Sunday around —
    a true in that column sends a sales team to meet nobody."""
    data = await _offline(
        "agent: Namaskaram, idi Skyline Ventures AI assistant. Ee call record avutundi.\n"
        "caller: Mee site address cheppandi, nenu maps lo chusukuntanu."
    )
    assert data.get("site_visit_interest") is None


# --- Gap 5: FIXED, and left here as a pointer ------------------------------------
#
# No in-call opt-out ever reached `dnc_list` — `dnc.SOURCES` carried `call_optout` from
# the start and only TESTS wrote it, so a caller could ask to be removed, the agent
# could confirm, and the next campaign tick dialled them again. Closed by D-56: a phrase
# detector plus ONE write path (`apps/api/compliance/optout.py`), reached from two
# layers — the post-call pipeline's step 2b and voice-runtime's `/tools/v1/{engine}/
# opt-out` → `apps/workers/optout.py`.
#
# The pin was STRUCTURAL ("`add_to_dnc` appears in pipeline.py") because the behaviour
# could not be asserted before the seam existed. It is now behavioural and lives in
# `tests/call_optout_test.py`, where the proof is the real campaign dispatcher refusing
# the dial after the opt-out rather than a row appearing in a table — and the fixture
# half is scored on every run by `scripts/eval.py::_check_compliance`, which now asserts
# OUR detector against every `requires_dnc` case instead of only the agent's words.
# Kept as a comment for the reason Gap 1 is: this file's value is the record of what the
# red-team set found, and a fix with no trace of what it fixed is how the next session
# re-derives the same hole.
