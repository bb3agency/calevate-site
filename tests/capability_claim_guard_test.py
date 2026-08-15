"""Section 5 of the docs-drift guardrail: does it FAIL when a doc understates the tree?

`scripts/check_docs_drift.py` grew a fifth question (D-102): prose that STATES a
capability constant's value must state the value the constant has. It exists because a
readiness audit found four claims that were wrong in the same direction — the capability
had been BUILT and the doc still described it as missing — which the repo's existing
honesty machinery is structurally unable to see. `UNWIRED_BASELINE` may only shrink and
the pilot scorecard derives its verdict; both guard against OVERclaiming. Nothing guarded
the reverse, and the reverse is what actually happened.

Three kinds of test, the same three `tests/docs_drift_guard_test.py` established:

- **wiring** — the check is pointed at the REAL constants and the REAL prose, so a check
  that has drifted away from what it claims to read fails here.
- **detection** — one minimal mutation that IS the drift, asserted to be named. Mutations
  come in both directions (the doc moves; the CODE moves under a correct doc), because a
  check that only ever saw a doctored doc has not been shown to read the live constant.
- **calibration** — a docs check that cries wolf gets ignored first and deleted second.
  Every false-positive shape measured while writing section 5 is pinned here as a case
  that must report NOTHING. The strongest of them are not invented: they are the real
  sentences in `apps/workers/whatsapp_cloud.py` and `apps/api/billing/payments.py` that a
  proximity-based or occurrence-based rule reports and this one does not.

A note on the deliberate self-reference: `tests/` is inside `CAPABILITY_ROOTS`, so this
file's own docstrings and comments are scanned by the thing it tests. Fixture prose
therefore lives in ordinary string literals, never in a docstring — a docstring here that
quoted a stale value would be a real finding against the real tree, which is the same
trap `_absent_decision()` was written for one section over.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts import check_docs_drift as guard

REPO_ROOT = Path(__file__).resolve().parent.parent

# A name no module binds, used for the rename half. Suffixed so that a future constant
# cannot accidentally adopt it and quietly turn this fixture into a true statement.
ABSENT_CONSTANT = "SPEECH_LEG_CONFIRMED_AGAINST_LIVE_PSTN_XX"


# --- helpers ------------------------------------------------------------------


def _blocks(*prose: tuple[str, str]) -> list[tuple[str, int, str]]:
    """`(file, text)` pairs as the `(file, first line, text)` triples the scanner takes."""
    return [(where, 1, text) for where, text in prose]


def _findings(*prose: tuple[str, str]) -> list[str]:
    """Section 5's verdict on synthetic prose, judged against the REAL constants."""
    return guard.capability_drift(claims=guard.value_claims(_blocks(*prose)))


def _module(root: Path, relative: str, body: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _mirror(tmp_path: Path, *relative: str) -> Path:
    for name in relative:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / name, target)
    return tmp_path


# ============================================================================
# wiring — the check is looking at the real thing
# ============================================================================


class TestWiring:
    def test_the_real_tree_is_clean(self) -> None:
        assert guard.capability_drift() == []
        assert guard.capability_ambiguities() == []

    def test_it_discovers_the_capability_constants_rather_than_listing_them(self) -> None:
        """The registry is an AST walk, not a hand-written set — which is why
        `ENGINE_REPORTS_TTS_MODEL`, absent from the audit's list of four, is guarded too.

        The values are pinned deliberately. Flipping one of these is precisely the moment
        every sentence quoting it has to be swept, and a required test edit is the
        cheapest possible reminder that the sweep is part of the change (D-102)."""
        facts = guard.capability_constants()
        assert facts["PROVIDER_CREATES_ORDERS"].value is True
        assert facts["PROVIDER_CREATES_ORDERS"].module == "apps/api/billing/payments.py"
        assert facts["LEAD_RETRIEVAL_IMPLEMENTED"].value is True
        assert facts["PROVISIONING_IMPLEMENTED"].value is False
        assert facts["CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA"].value is False
        assert facts["ENGINE_REPORTS_TTS_MODEL"].value is False

    def test_it_reads_prose_from_all_three_places_the_claim_actually_lives(self) -> None:
        """Markdown, Python docstrings/comments, and the console's JSDoc. A section that
        read only `docs/` would miss the commonest home of the claim — the module
        docstring directly above the constant."""
        scanned = {where for where, _, _ in guard.prose_blocks()}
        assert "docs/BUILD-LOG.md" in scanned
        assert "apps/api/billing/payments.py" in scanned
        assert "apps/workers/whatsapp_cloud.py" in scanned
        assert "apps/web/src/app/c/[slug]/verification/page.tsx" in scanned
        assert "tests/capability_claim_guard_test.py" in scanned, "this file is judged too"

    def test_it_finds_the_real_sentences_that_quote_a_value(self) -> None:
        """Not pinned by count — a new correct sentence must not cost a test edit. Pinned
        is that the scan still SEES the known ones across all three prose kinds."""
        found = {(claim.doc, claim.name, claim.stated) for claim in guard.value_claims()}
        assert ("runbooks/topup-payments.md", "PROVIDER_CREATES_ORDERS", True) in found
        assert ("apps/api/ingest/meta.py", "LEAD_RETRIEVAL_IMPLEMENTED", True) in found
        assert ("apps/api/billing/rates.py", "ENGINE_REPORTS_TTS_MODEL", False) in found
        assert (
            "apps/web/src/app/c/[slug]/verification/page.tsx",
            "PROVISIONING_IMPLEMENTED",
            False,
        ) in found
        assert len(found) >= 15


# ============================================================================
# detection — one real mutation each
# ============================================================================


class TestDetection:
    def test_catches_the_inventory_claim_that_started_this(self, tmp_path: Path) -> None:
        """BUILD-LOG's "Built but INERT" list, reverted to the sentence the audit found.
        Mirrored from the real file rather than invented: a fixture stops resembling the
        doc the moment the doc moves."""
        root = _mirror(tmp_path, "docs/BUILD-LOG.md")
        path = root / "docs" / "BUILD-LOG.md"
        source = path.read_text(encoding="utf-8")
        stale = source.replace(
            "`PROVIDER_CREATES_ORDERS` is True",
            "`PROVIDER_CREATES_ORDERS` is False",
            1,
        )
        assert stale != source, "the mutation no longer matches BUILD-LOG — update this test"
        failures = guard.capability_drift(
            claims=guard.value_claims([("docs/BUILD-LOG.md", 1, stale)])
        )
        assert any(
            "PROVIDER_CREATES_ORDERS" in f and "apps/api/billing/payments.py" in f for f in failures
        ), failures

    def test_catches_a_doc_that_understates_a_built_capability(self) -> None:
        text = "The Graph read is not built: `LEAD_RETRIEVAL_IMPLEMENTED = False`.\n"
        failures = _findings(("docs/X.md", text))
        assert any("states `LEAD_RETRIEVAL_IMPLEMENTED` is False" in f for f in failures), failures
        assert any("defines it True" in f for f in failures), failures

    def test_catches_a_doc_that_overstates_an_unbuilt_capability(self) -> None:
        """The direction the repo already defended, checked anyway: this section is
        symmetric, and a check that only caught understatement would leave the older
        failure mode resting entirely on human review."""
        failures = _findings(
            ("docs/X.md", "Numbers self-serve: `PROVISIONING_IMPLEMENTED` is True.\n")
        )
        assert any("states `PROVISIONING_IMPLEMENTED` is True" in f for f in failures), failures
        assert any("defines it False" in f for f in failures), failures

    def test_catches_a_stale_value_in_a_module_docstring(self, tmp_path: Path) -> None:
        """Where these claims most often live. `payments.py`, `meta.py`, `rates.py`,
        `provisioning.py` and both WhatsApp modules all describe their constant in the
        docstring directly above it, which is exactly the prose a code rename forgets."""
        text = '"""The vendor half is unrun: `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` is True."""\n'
        module = _module(tmp_path, "apps/w.py", text)
        blocks = list(guard.prose_blocks(docs=[], roots=(module.parent,), web=tmp_path / "none"))
        failures = guard.capability_drift(claims=guard.value_claims(blocks))
        assert any("CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA" in f for f in failures), failures

    def test_catches_a_stale_value_in_a_run_of_comments(self, tmp_path: Path) -> None:
        """Consecutive `#` lines are joined, so a claim that wraps across two of them is
        still one sentence to the matcher. `calevate_shared/config.py` writes one exactly
        this way."""
        text = (
            "X = 1\n"
            "# the selector lives one module over and\n"
            "# `PROVISIONING_IMPLEMENTED`\n"
            "# is True\n"
        )
        module = _module(tmp_path, "apps/w.py", text)
        blocks = list(guard.prose_blocks(docs=[], roots=(module.parent,), web=tmp_path / "none"))
        failures = guard.capability_drift(claims=guard.value_claims(blocks))
        assert any("PROVISIONING_IMPLEMENTED" in f for f in failures), failures

    def test_catches_a_stale_value_in_the_consoles_jsdoc(self, tmp_path: Path) -> None:
        """`/c/[slug]/verification` explains to a client why there is no purchase form,
        quoting the constant. A screen that keeps explaining an absence after the thing
        exists is the same defect one layer out."""
        web = tmp_path / "src"
        _module(web, "app/page.tsx", " * (`PROVISIONING_IMPLEMENTED = True`), so there is a form\n")
        blocks = list(guard.prose_blocks(docs=[], roots=(), web=web))
        failures = guard.capability_drift(claims=guard.value_claims(blocks))
        assert any("PROVISIONING_IMPLEMENTED" in f for f in failures), failures

    def test_catches_a_claim_wrapped_across_two_lines(self) -> None:
        """Docs here wrap at ~88 columns, so the name and its value routinely land on
        different lines. A line-at-a-time scan would go quietly blind at the margin."""
        text = "No checkout can be opened, because `PROVIDER_CREATES_ORDERS`\nis False today.\n"
        failures = _findings(("docs/X.md", text))
        assert any("PROVIDER_CREATES_ORDERS" in f for f in failures), failures

    def test_a_wrapped_claim_is_reported_once_and_on_the_line_the_name_is_on(self) -> None:
        text = "one\n`PROVIDER_CREATES_ORDERS`\nis False\n"
        claims = guard.value_claims(_blocks(("docs/X.md", text)))
        assert [(c.line, c.name) for c in claims] == [(2, "PROVIDER_CREATES_ORDERS")]

    def test_the_verdict_moves_when_the_code_moves_under_a_correct_doc(
        self, tmp_path: Path
    ) -> None:
        """The mutation is the CONSTANT, not the prose — the drift as it actually happens.
        Nobody edits a doc to make it wrong; somebody flips a boolean and ships, and every
        sentence quoting the old value becomes false without being touched. If this check
        were comparing against a remembered value rather than the live AST, this is the
        case it would pass and it should not."""
        text = "The adapter is unbuilt: `SAMPLE_CAPABILITY_BUILT` is False.\n"
        module = _module(tmp_path, "apps/m.py", "SAMPLE_CAPABILITY_BUILT = False\n")
        constants = guard.capability_constants(roots=(module.parent,))
        known = guard.module_level_names(roots=(module.parent,))
        claims = guard.value_claims(_blocks(("docs/X.md", text)))
        assert guard.capability_drift(claims=claims, constants=constants, known=known) == []

        module.write_text("SAMPLE_CAPABILITY_BUILT = True\n", encoding="utf-8")
        constants = guard.capability_constants(roots=(module.parent,))
        failures = guard.capability_drift(
            claims=claims,
            constants=constants,
            known=guard.module_level_names(roots=(module.parent,)),
        )
        assert any("SAMPLE_CAPABILITY_BUILT" in f and "defines it True" in f for f in failures), (
            failures
        )

    def test_catches_a_value_stated_for_a_name_the_tree_no_longer_spells(self) -> None:
        """The rename hole, and it is the one that would have retired this whole section
        silently: rename `PROVIDER_CREATES_ORDERS` and every sentence quoting it stops
        being compared to anything, while all of them stay readable and wrong."""
        failures = _findings(("docs/X.md", f"The pilot gate: `{ABSENT_CONSTANT}` is True.\n"))
        assert any(ABSENT_CONSTANT in f and "spells it" in f for f in failures), failures


# ============================================================================
# calibration — the shapes that must report NOTHING
# ============================================================================


class TestCalibration:
    """Measured false-positive shapes. Each of these WOULD have fired under a looser rule,
    and each stays green here or the narrowing has been lost.

    The rule this section defends: naming a constant is not claiming a value. A guard for
    the credential rule was written the same week on an occurrence grep, flagged three
    files that merely mentioned the thing they named, caught neither real offender, and
    was thrown away. Section 5 is what is left after that lesson."""

    def test_naming_a_constant_without_stating_its_value(self) -> None:
        """`payments.py` names its constant four times without ever giving the value; so
        do `flags/registry.py`, `provisioning_routes.py` and a runbook heading. None of
        them can be wrong about a value it does not state."""
        text = (
            "`PROVIDER_CREATES_ORDERS` is a claim about CODE: an adapter exists.\n"
            "Never flip `PROVIDER_CREATES_ORDERS` to make a frontend happy.\n"
            "`campaigns.provisioning.PROVISIONING_IMPLEMENTED` says so in a constant.\n"
        )
        assert _findings(("docs/X.md", text)) == []

    def test_the_real_pronoun_sentence_in_whatsapp_cloud(self) -> None:
        """The sentence that killed proximity matching, read off the live tree rather than
        transcribed: `whatsapp_cloud.py` names two constants that are both True and then
        says "it stays False" about a THIRD. A window-based rule reports that line twice
        and is wrong twice. Asserted against the real file so a rewrite of it cannot
        quietly retire the calibration."""
        named = {
            claim.name
            for claim in guard.value_claims()
            if claim.doc == "apps/workers/whatsapp_cloud.py"
        }
        assert named == {"CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA"}, named

    def test_a_pronoun_between_the_name_and_the_value(self) -> None:
        text = "The device `LEAD_RETRIEVAL_IMPLEMENTED` uses — and it stays False until then.\n"
        assert _findings(("docs/X.md", text)) == []

    def test_the_past_tense_of_a_chronological_log(self) -> None:
        """BUILD-LOG is dated, newest-first, and its older sections correctly record
        states that have since changed. A check that judged them would make an accurate
        history a CI failure, and the only way to pass would be to falsify the record."""
        text = (
            "At that commit `PROVIDER_CREATES_ORDERS` was False and no order could be made.\n"
            "`LEAD_RETRIEVAL_IMPLEMENTED` had been False since the receiver shipped.\n"
        )
        assert _findings(("docs/X.md", text)) == []

    def test_a_plan_or_a_requirement_is_not_a_claim_about_now(self) -> None:
        text = (
            "`CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` will be True once a person runs the gate.\n"
            "`PROVISIONING_IMPLEMENTED` must be False in every release until KYC lands.\n"
            "`PROVIDER_CREATES_ORDERS` would be False if the adapter were reverted.\n"
        )
        assert _findings(("docs/X.md", text)) == []

    def test_a_struck_through_retraction(self) -> None:
        """BUILD-LOG's own way of withdrawing a statement while keeping the record —
        it uses it twice in the very inventory this section guards. Firing on the correct
        way to retract a claim would push people to delete the entry instead, which is the
        opposite of what this file is for."""
        text = "- ~~`PROVIDER_CREATES_ORDERS` is False.~~ D-98 built the adapter.\n"
        assert _findings(("docs/X.md", text)) == []

    def test_a_retraction_does_not_shift_the_line_numbers_after_it(self) -> None:
        """The mask blanks the span in place and keeps its newlines. Filling it with plain
        spaces instead would collapse a wrapped retraction into one line and report every
        later offender in the file at the wrong place — a finding an author cannot find is
        a finding they stop trusting."""
        text = "~~a wrapped\nretraction~~\nfiller\n`PROVIDER_CREATES_ORDERS` is False\n"
        claims = guard.value_claims(_blocks(("docs/X.md", text)))
        assert [(c.line, c.name) for c in claims] == [(4, "PROVIDER_CREATES_ORDERS")]

    def test_one_stray_marker_cannot_blank_the_rest_of_a_document(self) -> None:
        """A single unpaired `~~` — a shell snippet, a torn edit — plus the next real one
        four sections down would mask everything between them under an unbounded rule.
        A silent blind spot is worse here than a missed retraction: nothing announces it.
        GFM bounds strikethrough at a paragraph, and so does this."""
        text = (
            "a stray ~~ marker\n"
            "\n"
            "`PROVIDER_CREATES_ORDERS` is False\n"
            "\n"
            "and much later ~~something struck~~\n"
        )
        failures = _findings(("docs/X.md", text))
        assert any("PROVIDER_CREATES_ORDERS" in f for f in failures), failures

    def test_code_is_not_prose(self, tmp_path: Path) -> None:
        """The definition line, an `assert X is True` in a test and a
        `capability = X and credentials()` in a service all match the shape and none of
        them is a doc. They cannot drift from themselves, and reporting them would make
        the offender message a lie about half its hits."""
        body = (
            "from typing import Final\n\n"
            "PROVISIONING_IMPLEMENTED: Final = True\n\n"
            "def t() -> None:\n"
            "    assert PROVISIONING_IMPLEMENTED is True\n"
        )
        module = _module(tmp_path, "apps/m.py", body)
        blocks = list(guard.prose_blocks(docs=[], roots=(module.parent,), web=tmp_path / "none"))
        assert guard.value_claims(blocks) == []

    def test_a_lowercase_config_key_is_not_a_capability_constant(self) -> None:
        """`self_serve_signup_enabled` and `provider_order_pending` are config rows and
        response fields, live values with no compile-time truth to compare against — and
        ROADMAP §5 writes "stays true" about one of them on the same line as a real
        constant claim."""
        text = "`PROVIDER_CREATES_ORDERS` is True and `provider_order_pending` stays true.\n"
        assert _findings(("docs/X.md", text)) == []

    def test_an_env_var_documented_the_way_env_vars_are_written(self) -> None:
        """`.env.example` and the deployment docs write `false`, not Python's `False`."""
        assert (
            _findings(("docs/X.md", "Set `NEXT_PUBLIC_SELF_SERVE_SIGNUP_ENABLED=false`.\n")) == []
        )

    def test_a_table_of_constants_is_a_layout_not_a_sentence(self) -> None:
        """Nothing joins the name to the value in `| NAME | False |` — a cell boundary is
        not a copula, and guessing that it is would make every two-column table a claim."""
        assert _findings(("docs/X.md", "| `PROVISIONING_IMPLEMENTED` | True |\n")) == []

    def test_an_upper_name_that_is_not_snake_case(self) -> None:
        """Acronyms are everywhere in this doc set (TRAI, DLT, DPDP, RBI). The name half
        requires an underscore so a sentence about a regulator can never be read as a
        constant claim."""
        assert _findings(("docs/X.md", "The DPDP is True to its own definition of harm.\n")) == []


# ============================================================================
# blind spots — a check that cannot find its subject must say so
# ============================================================================


class TestBlindSpots:
    def test_a_tree_with_no_capability_constants_is_reported(self, tmp_path: Path) -> None:
        _module(tmp_path, "apps/m.py", "VALUE = 3\n")
        assert guard.capability_constants(roots=(tmp_path / "apps",)) == {}

    def test_two_modules_defining_one_name_differently_are_reported_not_guessed(
        self, tmp_path: Path
    ) -> None:
        """Picking a definition silently would be inventing the answer, and half the
        sentences quoting that name would then be graded against the wrong module."""
        _module(tmp_path, "apps/a.py", "SPLIT_CAPABILITY = True\n")
        _module(tmp_path, "apps/b.py", "SPLIT_CAPABILITY = False\n")
        roots = (tmp_path / "apps",)
        assert "SPLIT_CAPABILITY" not in guard.capability_constants(roots=roots)
        failures = guard.capability_ambiguities(roots=roots)
        assert any("SPLIT_CAPABILITY" in f and "disagreeing values" in f for f in failures), (
            failures
        )

    def test_an_ambiguous_name_is_not_reported_as_a_rename(self, tmp_path: Path) -> None:
        """It is spelled by the tree, so the second half must stay quiet about it — the
        ambiguity is already reported once, and reporting it twice under a wrong heading
        sends the reader to rename prose that is fine."""
        _module(tmp_path, "apps/a.py", "SPLIT_CAPABILITY = True\n")
        _module(tmp_path, "apps/b.py", "SPLIT_CAPABILITY = False\n")
        roots = (tmp_path / "apps",)
        failures = guard.capability_drift(
            claims=guard.value_claims(_blocks(("docs/X.md", "`SPLIT_CAPABILITY` is True.\n"))),
            constants=guard.capability_constants(roots=roots),
            known=guard.module_level_names(roots=roots),
        )
        assert failures == [], failures

    def test_the_blind_spot_floors_are_wired_into_the_gate(self) -> None:
        """`blind_spots()` is what turns "found nothing" into a failure instead of an OK
        line. Both floors must be genuinely below today's tree, or they are decoration."""
        assert guard.blind_spots() == []
        assert len(guard.capability_constants()) >= 3
        assert len(guard.value_claims()) >= 8


# ============================================================================
# the surface
# ============================================================================


def test_section_five_runs_in_the_same_gate_as_the_other_four() -> None:
    """No Makefile or workflow edit was needed and that is the point: section 5 lives
    inside `check_docs_drift`, which both gates already invoke. A check nobody runs is a
    file."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts.check_docs_drift" in makefile
    assert "scripts.check_docs_drift" in workflow
