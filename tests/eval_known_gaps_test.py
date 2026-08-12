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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from apps.workers.extraction import OfflineExtractor
from calevate_shared.extraction import ExtractionSchemaSpec

REPO = Path(__file__).resolve().parent.parent


def _union_schema() -> ExtractionSchemaSpec:
    """The suite's own schema, so a pin here scores the columns a client really has."""
    payload = json.loads((REPO / "tests" / "fixtures" / "golden_transcripts.json").read_text())
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


# --- Gap 2: a denied enum is still filed (offline extractor) ----------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OfflineExtractor applies `_denied` to bool fields and to nothing else. The "
        "enum branch matches the enum VALUE as a word anywhere in a caller turn, so a "
        "caller refusing the thing files the thing. Fix belongs in "
        "apps/workers/extraction.py (the denial guard the bool branch already has)."
    ),
)
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Same root as the case above and a second victim: the enum branch takes the "
        "FIRST enum value that appears anywhere in the caller's turns, so a "
        "requirement the caller supersedes wins over the one they settled on. Fix "
        "belongs in apps/workers/extraction.py."
    ),
)
async def test_a_requirement_the_caller_replaced_is_not_the_one_filed() -> None:
    """Written as a golden fixture first (`re_spouse_takes_the_phone`) and pulled back
    to here when it turned out to fail as a `capture_wrong`: the phone changes hands,
    the second speaker says 3BHK and that 2BHK will not do, and the extractor files
    2BHK. A wrong size sends this household every listing they have just ruled out —
    unwaivable on every model, which is why it cannot sit in the suite until it is
    fixed."""
    data = await _offline(
        "agent: Namaskaram, idi Skyline Ventures AI assistant. Ee call record avutundi.\n"
        "caller: 2BHK gurinchi adagataniki chesanu... maa aavida matladatharu.\n"
        "caller: Manaki 3BHK ne kavali, 2BHK saripodu."
    )
    assert data.get("bhk_size") == "3BHK"


# --- Gap 3: a self-corrected name keeps the first version ------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "`OfflineExtractor._NAME_RE.search` takes the FIRST match in the transcript. A "
        "caller who corrects themselves is corrected against. Fix belongs in "
        "apps/workers/extraction.py (last match wins, or a correction-aware rule)."
    ),
)
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The bool branch probes on the FIRST WORD of the field label ('Site visit' -> "
        "'site'), so any caller sentence containing that word and no denial marker "
        "sets the flag true. Fix belongs in apps/workers/extraction.py."
    ),
)
async def test_asking_for_an_address_is_not_agreeing_to_a_site_visit() -> None:
    """A caller asking where the site is has agreed to nothing. `site_visit_interest`
    is the conversion event a real-estate client pays for and staffs a Sunday around —
    a true in that column sends a sales team to meet nobody."""
    data = await _offline(
        "agent: Namaskaram, idi Skyline Ventures AI assistant. Ee call record avutundi.\n"
        "caller: Mee site address cheppandi, nenu maps lo chusukuntanu."
    )
    assert data.get("site_visit_interest") is None


# --- Gap 5: an in-call opt-out never reaches the DNC list --------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "`dnc.SOURCES` has carried `call_optout` since the DNC module shipped and only "
        "tests ever write it: nothing in apps/workers or apps/voice-runtime turns a "
        "caller saying 'remove my number' into a `dnc_list` row. The suppression is "
        "reachable only by a human pasting the number into the console. Fix belongs in "
        "the post-call pipeline (a detection step + `compliance.add_to_dnc`), with the "
        "decision-log entry a new pipeline stage needs."
    ),
)
def test_the_post_call_pipeline_writes_an_in_call_opt_out_to_the_dnc_list() -> None:
    """The compliance gate reads `dnc_list` live on every dispatch precisely so an
    opt-out lands before the next tick (hard rule 5) — but nothing on the automated
    path ever writes one. `core5_compliance` and `re_promo_dnc_optout` have scored the
    agent SAYING it was done since the suite shipped, which is a hand-written line in a
    fixture; this is the assertion about our code that was missing behind them, and
    under TCCCPR the consumer's opt-out is the one instruction with a regulator behind
    it."""
    # A structural pin, deliberately: the behaviour cannot be asserted end to end
    # before the seam exists, and naming the exact function keeps the pin from being
    # satisfied by a comment about DNC.
    source = (REPO / "apps" / "workers" / "pipeline.py").read_text()
    assert "add_to_dnc" in source
