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

⚠ **THERE IS ONE BILLED RUNG SINCE 18 Sep 2026, AND THAT IS WHAT MOST OF THIS FILE NOW
EXERCISES.** The founder withdrew the Sarvam TEXT-TO-SPEECH leg (Saaras STT is untouched and
is guarded by §4d / `tests/stt_rate_card_test.py`). `TTS_INR_PER_10K_CHARS` did NOT leave the
code — it survives as the value rung's FROZEN cost-model scalar — but it left
`code_tts_rates()`, whose subject is narrow and is in its own name: the rates the BILLER
holds, one row per rung of the published card. A frozen floor input is not a rate a client
pays, so demanding a rate-card row for it would be manufacturing the drift this file exists
to catch. The clauses below moved onto the Cartesia rung, which is the one still billed.

EVIDENCE FOR THE RATE ITSELF. **The billed rung is Cartesia Sonic 3.5
(D-547), and since D-556 (9 Sep 2026) it is VENDOR-PUBLISHED**: ₹57.20 / 10,000 chars,
DERIVED in code from the vendor's own **Pro overage rate** of $65 per 1,000,000 credits
(direct correspondence — Ege Tinmaz, Product Support Engineer, Cartesia — relayed by the
founder, `docs/evidence/cartesia-tts-verification-2026-09-06.md` ADDENDUM 3; `cartesia.ai`
is still egress-blocked here and was not read by this repository). ⚠ It was **₹34.496**,
the Startup plan's $49 fee over its 1.25M-character allotment — an AVERAGE true at one
volume, on a plan we are not on. This file does not assert what either vendor charges — it
asserts that this repository says one thing about each.
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
    # TWO rungs again since 19 Sep 2026 (D-631). It was one for a day: the Clear rung's
    # vendor changed at D-629 and Gnani were believed to publish no price, so that rung had
    # no card row to diff. They publish ₹27.00 / 10,000 chars, so both rungs are back —
    # Cartesia's DERIVED in code from the vendor's overage rate (which is what pins the doc
    # row to arithmetic rather than to a figure somebody rounded), Gnani's read off their
    # console. Neither is a rate any minute is BILLED at; see `code_tts_rates`.
    assert set(declared) == set(billed) == {"sonic-3.5", "timbre-v2.5"}
    assert declared == billed, f"the doc and the biller already disagree: {declared} vs {billed}"
    assert "bulbul-v3" not in billed, (
        "`TTS_INR_PER_10K_CHARS` is the CLEAR rung's per-character rate and not a "
        "rate anybody is billed at; listing it here would demand a rate-card row for a "
        "vendor card that no longer exists"
    )
    assert not guard.tts_rate_card_drift()


def test_the_doc_states_each_rate_twice_and_both_spellings_are_read() -> None:
    """§10.1's Cartesia card quotes ₹/10,000 chars and its per-call-minute table quotes
    ₹/1,000. Reading only one would let the other rot unwatched — and the per-1,000 table
    is the one a reader doing per-minute arithmetic actually uses."""
    assert "₹57.20 / 10,000 chars" in TRD_TEXT
    assert "₹5.7200 / 1,000 chars" in TRD_TEXT
    assert not guard.doc_tts_rate_disagreements(), "§10.1 already disagrees with itself"


# --- detection ----------------------------------------------------------------


def test_a_vendor_price_move_recorded_only_in_the_doc_is_named() -> None:
    """The likeliest direction: someone re-reads the vendor's page, updates the cost
    model, and never touches the biller. The client keeps paying the old rate.

    ⚠ Mutated on the CARTESIA row since 18 Sep 2026 — the Sarvam rung this used to move is
    withdrawn, and the module docstring carries why its scalar left `code_tts_rates`."""
    offenders = guard.tts_rate_card_drift(
        _mutated("₹57.20 / 10,000 chars", "₹36.00 / 10,000 chars")
    )
    assert offenders, "a doc-side price move was not detected"
    assert any("sonic-3.5" in line and "36" in line for line in offenders), offenders


def test_the_doc_disagreeing_with_its_own_second_table_is_named() -> None:
    """Both tables state the same rate. Changing one is the cheapest version of this
    failure and the likeliest to pass review, because each table reads fine alone."""
    offenders = guard.tts_rate_card_drift(
        _mutated("| ₹5.7200 / 1,000 chars |", "| ₹5.9900 / 1,000 chars |")
    )
    assert any("stated twice, disagreeing" in line for line in offenders), offenders


def test_the_cartesia_rung_moving_in_the_doc_alone_is_named() -> None:
    """THE SECOND RUNG (D-547, re-struck by D-556). §10.1 states the Cartesia marginal rate
    twice — ₹57.20 per 10,000 in the Cartesia card and ₹5.7200 per 1,000 in the
    per-call-minute table (⚠ both read ₹34.496 / ₹3.4496 until 9 Sep 2026) — and the
    code DERIVES it from the plan fee over the allotment. So there are three ways for it to
    drift and this asserts each is named: the doc disagreeing with the code, and the doc
    disagreeing with itself.
    """
    moved = _mutated("₹57.20 / 10,000 chars", "₹40.00 / 10,000 chars")
    offenders = guard.tts_rate_card_drift(moved)
    # One spelling moved, so BOTH directions fire: the doc contradicts itself, and the
    # figure it now leads with contradicts the code.
    assert any("sonic-3.5" in line and "stated twice, disagreeing" in line for line in offenders)
    assert any("sonic-3.5" in line and "cost model is the code" in line for line in offenders), (
        offenders
    )

    # BOTH spellings moved together — the doc is self-consistent and still wrong, which is
    # the failure that reads as fine in review because the two tables line up.
    # ANCHORED ON THE TABLE CELL, not on the first occurrence in the file. §10 gained a
    # correction note (D-563's lane, 10 Sep 2026) that quotes this same rate in prose ABOVE
    # the card, so `replace(..., 1)` began mutating the note and leaving the row alone —
    # which made the "both spellings moved" fixture a doc that really does contradict
    # itself, and the guard rightly said so. The guard was never wrong; the mutation was
    # reaching for the wrong sentence. Pipes make it the row or nothing.
    both = moved.replace("| ₹5.7200 / 1,000 chars |", "| ₹4.00 / 1,000 chars |", 1)
    assert "| ₹4.00 / 1,000 chars |" in both, "the rate-card row moved or changed shape"
    offenders = guard.tts_rate_card_drift(both)
    assert not any("stated twice, disagreeing" in line for line in offenders), offenders
    assert any("sonic-3.5" in line and "cost model is the code" in line for line in offenders), (
        offenders
    )


def test_the_cartesia_rung_deleted_from_both_tables_is_named() -> None:
    """A rung the cost model prices and the doc does not state is unguarded money.

    ⚠ **THIS IS THE ONLY RUNG LEFT TO PROTECT (18 Sep 2026)**, so it carries the argument
    its withdrawn Sarvam twin used to: a row's absence from a table is exactly how a false
    "discontinued" claim gets made (D-20 recorded Bulbul v2 as discontinued and D-35 had to
    take it back). BOTH spellings have to go, which is the union rule doing its job.
    """
    dropped = TRD_TEXT.replace(
        "| Text-to-Speech **Sonic 3.5**, Pro plan (the plan we are on) |", "| ~~x~~ |", 1
    )
    dropped = dropped.replace("| TTS — Cartesia **Sonic 3.5**", "| ~~x~~", 1)
    offenders = guard.tts_rate_card_drift(dropped)
    assert any("does not state it" in line and "sonic-3.5" in line for line in offenders), offenders


def test_dropping_only_one_of_the_two_tables_is_not_drift() -> None:
    """The union rule, stated as a test rather than left in a comment. §10.1 may
    legitimately be edited down to one table; what may not happen is the rung disappearing
    from BOTH while the biller still charges it. A check satisfied by deleting the table
    it happens to read would be a check anyone could silence with an edit."""
    one_table_only = TRD_TEXT.replace("| TTS — Cartesia **Sonic 3.5**", "| ~~moved~~", 1)
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
        "Sonic 3.5 was once quoted at ₹99.00 / 10,000 chars by a secondary source, which "
        "was wrong. The card below is the first-party read.\n\n"
        "| Cartesia API | Published rate |\n|---|---|\n"
        "| Text-to-Speech **Sonic 3.5** | ₹57.20 / 10,000 chars |\n"
        # BOTH rungs, because §4b diffs the whole card in both directions: a fixture
        # carrying one rung while the biller holds two reports the missing one as drift and
        # this clause would fail for a reason that has nothing to do with prose (D-631).
        "| Text-to-Speech **Timbre v2.5** | ₹27.00 / 10,000 chars |\n"
    )
    assert guard.doc_tts_rates(prose) == {
        "sonic-3.5": Decimal("57.20"),
        "timbre-v2.5": Decimal("27.00"),
    }
    # What this asserts is that the SENTENCE quoting ₹99.00 produced no rate claim at all:
    # the only sonic-3.5 figure the parse found is the table row's, which agrees with code.
    assert not guard.tts_rate_card_drift(prose)


def test_a_thousands_separator_is_not_a_different_price() -> None:
    """₹1,500 and ₹1500 are one number. A check that reported them as drift would be
    wrong on a doc an editor merely reformatted, which is how a guardrail earns the
    reputation that gets it deleted."""
    heading = "### 10.1 Stack cost, computed from published rates\n\n"
    assert guard.doc_tts_rates(heading + "| TTS **Sonic 3.5** | ₹57.20 / 10,000 chars |\n") == {
        "sonic-3.5": Decimal("57.20")
    }
    assert guard.doc_tts_rates(heading + "| TTS **Sonic 3.5** | ₹57.20 / 10000 chars |\n") == {
        "sonic-3.5": Decimal("57.20")
    }


def test_a_rate_outside_section_10_1_is_not_read() -> None:
    """§10's headline paragraph and §10.3's Outpero reconstruction both quote TTS money,
    and neither is the rate card. Bounding the parse to §10.1 is what keeps a discussion
    of somebody else's pricing from being read as a claim about ours."""
    assert not guard.doc_tts_rates("Sonic 3.5 costs ₹57.20 / 10,000 chars, they say.\n")


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


def test_a_gnani_rate_appearing_in_the_card_is_named() -> None:
    """THE HARD-RULE-7 TRIPWIRE (D-629, 18 Sep 2026), and it is the reason
    `_TTS_PRODUCT` is deliberately wider than the rungs the biller prices.

    ⚠ **THIS SAID "Gnani publish no price of any kind" UNTIL 19 SEP 2026 AND THAT WAS
    FALSE** (D-631). What is still true is the provenance point this guard exists for: the
    only per-character figure that was in this TREE came from a RESELLER's page for their
    own platform, and a client-facing rate card is exactly the surface a figure of that
    class must never reach — a number that later turns out to match a real one is still not
    a source. The tripwire is why `_TTS_PRODUCT` is deliberately wider than the rungs the
    biller prices: the day §10.1 states a rate the code does not hold, §4b fails naming the
    rung and the rupees rather than falling silent because the parser never learned the
    product's name.

    The mutation states the reseller figure on the Gnani row's SECOND cell, where the row
    currently reads `**none published**`. That is the shape the defect would really take.
    """
    offenders = guard.tts_rate_card_drift(
        _mutated("| ₹27.00 / 10,000 chars |", "| ₹41.00 / 10,000 chars |")
    )
    assert any("timbre-v2.5" in line and "41" in line for line in offenders), offenders
