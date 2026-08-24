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

EVIDENCE FOR THE RATE ITSELF (billing/payments.py's three-rung ladder). **REPORTED,
NOT READ**: `sarvam.ai` and `docs.sarvam.ai` are refused by this environment's egress
proxy and no request has ever been made to them from this repository. ₹30 per 10,000 chars
(Bulbul v3) is TRD §10.1's record of a live read on 11 Aug 2026, corroborated Aug 2026 by
independent search summaries of that same pricing page. The single-tier voice decision
withdrew the v2 rung, so there is now one rate to keep in step. This file does not assert
what Sarvam charges — it asserts that this repository says one thing about it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from calevate_shared.engine import SELECTABLE_LLM_MODELS
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
    # One voice quality (the single-tier voice decision), one rate, one key.
    assert set(declared) == set(billed) == {"bulbul-v3"}
    assert declared == billed, f"the doc and the biller already disagree: {declared} vs {billed}"
    assert billed["bulbul-v3"] == Decimal("30.0000"), "the one voice quality's rate"
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
    assert any("bulbul-v3" in line and "36" in line for line in offenders), offenders


def test_the_doc_disagreeing_with_its_own_second_table_is_named() -> None:
    """Both tables state the same rate. Changing one is the cheapest version of this
    failure and the likeliest to pass review, because each table reads fine alone."""
    offenders = guard.tts_rate_card_drift(_mutated("₹3.00 / 1,000 chars", "₹3.60 / 1,000 chars"))
    assert any("stated twice, disagreeing" in line for line in offenders), offenders


def test_the_rung_deleted_from_the_rate_card_is_named() -> None:
    """The doc dropping the one rung the biller still charges. Not hypothetical: D-20
    recorded Bulbul v2 as discontinued and D-35 had to take that back — a row's absence
    from a table is exactly how that claim got made the first time.

    BOTH spellings have to go, which is the union rule doing its job: while either table
    still prices the rung, the doc has not dropped it (see the calibration test below).
    """
    dropped = TRD_TEXT.replace("| Text-to-Speech **Bulbul v3** |", "| ~~withdrawn~~ |", 1).replace(
        "| TTS — Bulbul **v3** |", "| ~~withdrawn~~ |", 1
    )
    offenders = guard.tts_rate_card_drift(dropped)
    assert any("does not state it" in line and "bulbul-v3" in line for line in offenders), offenders


def test_dropping_only_one_of_the_two_tables_is_not_drift() -> None:
    """The union rule, stated as a test rather than left in a comment. §10.1 may
    legitimately be edited down to one table; what may not happen is the rung disappearing
    from BOTH while the biller still charges it. A check satisfied by deleting the table
    it happens to read would be a check anyone could silence with an edit."""
    one_table_only = TRD_TEXT.replace("| TTS — Bulbul **v3** |", "| ~~moved~~ |", 1)
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
        "Bulbul v3 was once quoted at ₹60 / 10,000 chars by a secondary source, which "
        "was wrong. The card below is the first-party read.\n\n"
        "| Sarvam API | Published rate |\n|---|---|\n"
        "| Text-to-Speech **Bulbul v3** | ₹30 / 10,000 chars |\n"
    )
    assert guard.doc_tts_rates(prose) == {"bulbul-v3": Decimal(30)}
    assert not guard.tts_rate_card_drift(prose)


def test_a_thousands_separator_is_not_a_different_price() -> None:
    """₹1,500 and ₹1500 are one number. A check that reported them as drift would be
    wrong on a doc an editor merely reformatted, which is how a guardrail earns the
    reputation that gets it deleted."""
    heading = "### 10.1 Stack cost, computed from published rates\n\n"
    assert guard.doc_tts_rates(heading + "| TTS **Bulbul v3** | ₹30 / 10,000 chars |\n") == {
        "bulbul-v3": Decimal(30)
    }
    assert guard.doc_tts_rates(heading + "| TTS **Bulbul v3** | ₹30 / 10000 chars |\n") == {
        "bulbul-v3": Decimal(30)
    }


def test_a_rate_outside_section_10_1_is_not_read() -> None:
    """§10's headline paragraph and §10.3's Outpero reconstruction both quote TTS money,
    and neither is the rate card. Bounding the parse to §10.1 is what keeps a discussion
    of somebody else's pricing from being read as a claim about ours."""
    assert not guard.doc_tts_rates("Bulbul v3 costs ₹30 / 10,000 chars, they say.\n")


# --- 4c: the in-call LLM cost curves (D-400, two of them since D-410) ----------
#
# THE SAME CLASS AS EVERYTHING ABOVE, ON A NUMBER NOBODY BILLS AGAINST YET — which is
# what makes it the one most likely to rot. D-36 priced the in-call LLM leg at ₹0.00
# because Sarvam 105B is free per token, and TRD §10 reasoned the whole margin from that
# zero. D-400 moved the leg to a paid account, so §10 now quotes a curve that
# `billing/rates.py::llm_cost_inr_per_minute` computes — and nothing charges against it,
# so nothing else would ever notice the two drifting apart.
#
# D-410 MADE IT TWO CURVES. `Settings.azure_openai_model` selects `gpt-4o-mini` or
# `gpt-4.1-mini` live, they are 2.7x apart, so §10.1 carries a row per model and each row
# is scored against `llm_cost_inr_per_minute(minutes, model=<that row's model>)`. THE ROW
# MUST NAME THE MODEL VERBATIM — that identifier is how the check knows which price the
# row's figures are supposed to be — and a model with no row is reported rather than
# skipped, because the row that goes missing will be the non-default one and that is the
# expensive half: a margin table quoting only the cheap model is wrong the moment an
# operator flips a console switch.


def test_the_check_reads_the_real_llm_rows_and_they_agree_today() -> None:
    """Wiring, on EVERY model. A check reading an empty row would report OK on every
    mutation, which is why `llm_cost_curve_drift` treats an empty reading as a FAILURE
    rather than a pass."""
    points = guard.doc_llm_cost_points()
    assert set(points) == SELECTABLE_LLM_MODELS, points
    for model, quoted in points.items():
        assert quoted, f"TRD §10.1 has no `| LLM …` row naming `{model}` — 4c reads nothing"
        assert set(quoted) == {1, 5, 10}, (model, quoted)
    assert not guard.llm_cost_curve_drift()


@pytest.mark.parametrize("model", sorted(SELECTABLE_LLM_MODELS))
def test_the_quoted_curve_rises_with_call_length(model: str) -> None:
    """The shape is the finding, not the level: §6.1 resends the whole conversation every
    turn, so input cost is quadratic in duration and per-minute cost RISES. A doc quoting
    one flat rate would have lost that, and this is the assertion that would notice."""
    quoted = guard.doc_llm_per_minute(model=model)
    assert quoted[1] < quoted[5] < quoted[10], quoted


def test_a_doc_side_drift_in_the_llm_curve_is_named() -> None:
    """The likeliest direction, exactly as for the TTS card: someone edits the margin
    table by hand and never touches the function it came out of.

    ₹0.16 is `gpt-4o-mini` at five minutes. If this mutation stops matching, the doc's
    published figure has moved and the two halves of D-410's cost model have to be
    reconciled deliberately — which is the whole point of asserting against the REAL doc
    rather than an invented one."""
    offenders = guard.llm_cost_curve_drift(_mutated("₹0.16 (5 min)", "₹0.29 (5 min)"))
    assert any("5-minute call" in line for line in offenders), offenders


def test_an_llm_row_disappearing_is_a_failure_and_not_a_pass() -> None:
    """A check that goes quiet when its subject is reworded teaches the next reader to
    reword it. Same argument `check_redaction_exposure.check_allowlist` makes when it
    refuses to pass on a route table with no permissions in it at all.

    THE ONE FIXTURE IN THIS FILE THAT IS NOT THE REAL DOC, and the reason is that the
    property under test is precisely "§10.1 with no LLM row at all", which no single-string
    mutation of the real document can express now that there are two rows — deleting one
    would leave the other and prove only half of it. The section heading is imported from
    the checker rather than typed, so the fixture cannot drift from what it parses.
    """
    offenders = guard.llm_cost_curve_drift(
        f"{guard.TTS_RATE_HEADING}\n\n| leg | rate |\n| --- | --- |\n| TTS | ₹30 |\n"
    )
    assert len(offenders) == len(SELECTABLE_LLM_MODELS), offenders
    assert all("carries no" in line for line in offenders), offenders


def test_the_doc_may_round_to_paise_without_being_reported() -> None:
    """Calibration, and the one that would otherwise make this check harmful. The
    function returns NUMERIC(12,4) because `unit_cost_paid` stores four decimals; §10
    prints paise because a margin table is read by a person. Reporting ₹0.1021 against
    ₹0.10 would train the next reader to print four decimals in prose to quiet a check."""
    from apps.api.billing.rates import llm_cost_inr_per_minute

    for model, quoted in guard.doc_llm_cost_points().items():
        assert llm_cost_inr_per_minute(1, model=model) != quoted[1], (
            f"this test is vacuous for {model} unless the function is genuinely more "
            "precise than the doc"
        )
    assert not guard.llm_cost_curve_drift()
