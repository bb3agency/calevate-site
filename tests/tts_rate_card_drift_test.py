"""The money rate card's drift check: does it FAIL when the price moves in one place?

`scripts/check_docs_drift.py` section 4b claims that TRD §10.1's TTS rate card and
`billing/rates.py::TTS_INR_PER_10K_CHARS` — the table a client is actually billed
against — state the same rupees, and that §10.1's two spellings of each rate agree with
each other. A check making that claim while blind to a violation is worse than no check,
because "the cost model was verified" is exactly the sentence a margin gets defended
with.

WHY THIS CLASS NEEDED A CHECK OF ITS OWN. The four preceding waves (D-102, D-103, D-104,
D-105) all found one shape: a fact with no single home, so a correction has one place to
land and several to be missed. The money path had never been swept for it. What was
there: `rate_zone_drift` — which sounds like a rate-card check and is about nginx
`limit_req_zone` directives, requests per second, no rupees anywhere — and nothing else.
D-105 is the concrete precedent for why this is expensive rather than untidy: a Sarvam
identifier moved under us and TRD §10 went on pricing a model the pipeline had stopped
calling.

Three kinds of test, following `tests/docs_drift_guard_test.py`:

- **wiring** — the check is pointed at the REAL doc and the REAL constant, so a check
  that has drifted away from what it claims to read fails here;
- **detection** — take the real §10.1, apply ONE minimal mutation that IS the drift, and
  assert it is named, in each of the four directions the failure can run;
- **calibration** — the shapes that must report NOTHING, because a check that cries wolf
  is ignored first and deleted second.

EVIDENCE FOR THE RATES THEMSELVES (billing/payments.py's three-rung ladder). **REPORTED,
NOT READ**: `sarvam.ai` and `docs.sarvam.ai` are refused by this environment's egress
proxy and no request has ever been made to them from this repository. ₹30 / ₹15 per
10,000 chars is TRD §10.1's record of a live read on 11 Aug 2026 (D-35), corroborated
Aug 2026 by two independent search summaries of that same pricing page ("Text-to-Speech
costs ₹15-30 per 10,000 characters"; "Bulbul v3 is priced at ₹30 per 10,000 characters").
This file does not assert what Sarvam charges — it asserts that this repository says one
thing about it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from scripts import check_docs_drift as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
TRD_TEXT = (REPO_ROOT / "docs" / "TRD.md").read_text(encoding="utf-8")


def _mutated(old: str, new: str) -> str:
    """The real TRD with ONE string changed. An invented fixture would stop resembling
    the doc the moment the doc moved, which is the failure this whole file is about."""
    assert old in TRD_TEXT, f"the mutation no longer matches TRD.md — update this test: {old!r}"
    return TRD_TEXT.replace(old, new, 1)


# --- wiring -------------------------------------------------------------------


def test_the_check_reads_the_real_rate_card_and_the_real_biller() -> None:
    """Both halves resolve against the live artefacts, and they agree TODAY.

    This is the assertion that makes every detection test below meaningful: a check
    reading an empty table would report OK on any mutation.
    """
    declared = guard.doc_tts_rates()
    billed = guard.code_tts_rates()
    assert declared, "TRD §10.1's TTS rate card did not parse — section 4b is reading nothing"
    assert set(declared) == set(billed) == {"premium", "value"}
    assert declared == billed, f"the doc and the biller already disagree: {declared} vs {billed}"
    assert billed["premium"] == Decimal("30.0000"), "D-36's default rung, D-35's read"
    assert billed["value"] == Decimal("15.0000"), "the value rung, live at half (D-35)"
    assert not guard.tts_rate_card_drift()


def test_the_doc_states_each_rate_twice_and_both_spellings_are_read() -> None:
    """§10.1's Sarvam card quotes ₹/10,000 chars and its per-call-minute table quotes
    ₹/1,000. Reading only one would let the other rot unwatched — and the per-1,000 table
    is the one a reader doing per-minute arithmetic actually uses."""
    assert "₹30 / 10,000 chars" in TRD_TEXT
    assert "₹3.00 / 1,000 chars" in TRD_TEXT
    assert not guard.doc_tts_rate_disagreements(), "§10.1 already disagrees with itself"


# --- detection ----------------------------------------------------------------


def test_a_vendor_price_move_recorded_only_in_the_doc_is_named() -> None:
    """The likeliest direction: someone re-reads the vendor's page, updates the cost
    model, and never touches the biller. The client keeps paying the old rate."""
    offenders = guard.tts_rate_card_drift(_mutated("₹30 / 10,000 chars", "₹36 / 10,000 chars"))
    assert offenders, "a doc-side price move was not detected"
    assert any("premium" in line and "36" in line for line in offenders), offenders


def test_a_price_move_in_the_value_rung_alone_is_named() -> None:
    """The rung most likely to move without anyone noticing, because it is the one no
    plan quotes a retail price for yet (`plans.overage_rate_value` is NULL everywhere)."""
    offenders = guard.tts_rate_card_drift(_mutated("₹15 / 10,000 chars", "₹18 / 10,000 chars"))
    assert any("value" in line for line in offenders), offenders


def test_the_doc_disagreeing_with_its_own_second_table_is_named() -> None:
    """Both tables state the same rate. Changing one is the cheapest version of this
    failure and the likeliest to pass review, because each table reads fine alone."""
    offenders = guard.tts_rate_card_drift(_mutated("₹3.00 / 1,000 chars", "₹3.60 / 1,000 chars"))
    assert any("stated twice, disagreeing" in line for line in offenders), offenders


def test_a_rung_deleted_from_the_rate_card_is_named() -> None:
    """The doc dropping a rung the biller still charges. Not hypothetical: D-20 recorded
    Bulbul v2 as discontinued and D-35 had to take that back — a row's absence from a
    table is exactly how that claim got made the first time.

    BOTH spellings have to go, which is the union rule doing its job: while either table
    still prices the rung, the doc has not dropped it (see the calibration test below).
    """
    dropped = TRD_TEXT.replace("| Text-to-Speech **Bulbul v2** |", "| ~~withdrawn~~ |", 1).replace(
        "| TTS — Bulbul **v2** |", "| ~~withdrawn~~ |", 1
    )
    offenders = guard.tts_rate_card_drift(dropped)
    assert any("does not state it" in line and "value" in line for line in offenders), offenders


def test_dropping_only_one_of_the_two_tables_is_not_drift() -> None:
    """The union rule, stated as a test rather than left in a comment. §10.1 may
    legitimately be edited down to one table; what may not happen is a rung disappearing
    from BOTH while the biller still charges it. A check satisfied by deleting the table
    it happens to read would be a check anyone could silence with an edit."""
    one_table_only = TRD_TEXT.replace("| TTS — Bulbul **v2** |", "| ~~moved~~ |", 1)
    assert guard.doc_tts_rates(one_table_only) == guard.code_tts_rates()
    assert not guard.tts_rate_card_drift(one_table_only)


def test_a_heading_rename_that_blinds_the_check_is_caught_by_the_blind_spot() -> None:
    """The failure mode a doc check dies of: the section moves, the parse returns nothing,
    and the check reports OK on every price forever. `blind_spots()` owns this, which is
    why the mutation is asserted there rather than in `tts_rate_card_drift`."""
    assert not guard.doc_tts_rates(_mutated("### 10.1 Stack cost", "### 10.1a Stack cost"))
    assert any("TTS rate card parsed to" in line for line in guard.blind_spots()) is False, (
        "the real tree parses fine; this asserts the control, not a failure"
    )


# --- calibration --------------------------------------------------------------


def test_prose_about_a_rate_is_not_read_as_a_rate() -> None:
    """§10.1 discusses these rates in sentences as well as tables — "v2+Sarvam LLM is
    ~45% cheaper", the ⚠ note correcting D-20. Only a TABLE ROW is a rate claim, because
    only a table row states one unambiguously."""
    prose = (
        "### 10.1 Stack cost, computed from published rates (Aug 2026)\n\n"
        "Bulbul v2 was once quoted at ₹60 / 10,000 chars by a secondary source, which "
        "was wrong. The card below is the first-party read.\n\n"
        "| Sarvam API | Published rate |\n|---|---|\n"
        "| Text-to-Speech **Bulbul v3** | ₹30 / 10,000 chars |\n"
        "| Text-to-Speech **Bulbul v2** | ₹15 / 10,000 chars |\n"
    )
    assert guard.doc_tts_rates(prose) == {"premium": Decimal(30), "value": Decimal(15)}
    assert not guard.tts_rate_card_drift(prose)


def test_a_thousands_separator_is_not_a_different_price() -> None:
    """₹1,500 and ₹1500 are one number. A check that reported them as drift would be
    wrong on a doc an editor merely reformatted, which is how a guardrail earns the
    reputation that gets it deleted."""
    heading = "### 10.1 Stack cost, computed from published rates\n\n"
    assert guard.doc_tts_rates(
        heading
        + "| TTS **Bulbul v3** | ₹30 / 10,000 chars |\n"
        + "| TTS **Bulbul v2** | ₹15 / 10,000 chars |\n"
    ) == {"premium": Decimal(30), "value": Decimal(15)}
    assert guard.doc_tts_rates(heading + "| TTS **Bulbul v3** | ₹30 / 10000 chars |\n") == {
        "premium": Decimal(30)
    }


def test_a_rate_outside_section_10_1_is_not_read() -> None:
    """§10's headline paragraph and §10.3's Outpero reconstruction both quote TTS money,
    and neither is the rate card. Bounding the parse to §10.1 is what keeps a discussion
    of somebody else's pricing from being read as a claim about ours."""
    assert not guard.doc_tts_rates("Bulbul v3 costs ₹30 / 10,000 chars, they say.\n")
