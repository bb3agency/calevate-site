"""The docs-drift guardrail's own test suite: does it FAIL when a doc is wrong?

`scripts/check_docs_drift.py` claims that every command the docs name resolves, that
every `D-xx` citation lands on a row of ROADMAP §6, and that SECURITY-COMPLIANCE §3 still
quotes names the code has. A check making those claims while blind to a violation is
worse than no check: it turns "the docs are authoritative" into "the docs are unverified
and nobody will look".

Same two kinds of test `tests/guardrail_audit_test.py` established and
`tests/compliance_guard_test.py` follows:

- **wiring** — the check is pointed at the REAL artefacts (the real Makefile, the real
  `package.json`s, the real decision log, the real §3, the real code) so a check that has
  drifted away from what it claims to read fails here.
- **detection** — take the real artefact, apply ONE minimal mutation that IS the drift,
  and assert it is named. Every mutation below is a copy of a real repo file with one
  string changed, mirrored into a tmp tree at its real relative path — an invented
  fixture would stop resembling the docs the moment the docs moved.

Plus a third kind this particular guardrail needs more than the others: **calibration**.
A docs check that cries wolf gets its findings ignored first and deleted second, so the
false-positive shapes that were measured while writing it — prose that contains the word
"make", `<placeholder>` arguments, alternation shorthand, pnpm's own subcommands — are
pinned here as tests that must report NOTHING.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts import check_docs_drift as guard

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- helpers ------------------------------------------------------------------


def _mirror(tmp_path: Path, *relative: str) -> Path:
    """Copy real repo files into a tmp tree at their real relative paths.

    Offenders are reported as `path:line`, so a mutation only reads like the real thing
    if it sits where the real thing sits.
    """
    for name in relative:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / name, target)
    return tmp_path


def _edit(root: Path, relative: str, old: str, new: str) -> Path:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    assert old in source, f"the mutation no longer matches {relative} — update this test"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return path


def _claims(path: Path) -> list[guard.Claim]:
    return guard.command_claims([path])


def _absent_decision(offset: int = 1) -> str:
    """A decision number the log does not carry, DERIVED from the live log.

    Never a literal: this file is itself scanned by `dangling_decisions()` (a citation in
    a test is as unfollowable as one in a doc), so an invented number written out here
    would be a real finding against the real tree — the check caught exactly that on the
    first run of this suite. Deriving it also means the fixture cannot be overtaken by
    the log growing past it.
    """
    highest = max(int(identifier.split("-")[1]) for identifier in guard.decision_ids())
    return f"D-{highest + offset:02d}"


# ============================================================================
# wiring — the check is looking at the real thing
# ============================================================================


class TestWiring:
    def test_the_real_tree_is_clean(self) -> None:
        assert guard.blind_spots() == []
        assert guard.unresolved_commands() == []
        assert guard.dangling_decisions() == []
        assert guard.duplicate_decision_ids() == []
        assert guard.unknown_rule_names() == []
        assert guard.rate_zone_drift() == []
        assert guard.stale_deferrals() == []

    def test_it_reads_the_real_makefile(self) -> None:
        targets = guard.makefile_targets()
        assert {"check", "guardrails", "web-check", "db-reset"} <= targets

    def test_it_reads_the_real_package_manifests(self) -> None:
        """`pnpm -C apps/web typecheck` and `pnpm gen:api` are claims about DIFFERENT
        files. A check that resolved both against one manifest would miss the second."""
        packages = guard.package_scripts()
        assert "typecheck" in packages["apps/web"][1]
        assert "gen:api" in packages["apps/web"][1]
        assert packages["."][1] == frozenset(), "the root manifest has no scripts"

    def test_it_finds_the_commands_the_docs_actually_give(self) -> None:
        """The count is not pinned — a new documented command must not cost a test edit.
        What is pinned is that the extractor still SEES the known ones: a scan that found
        nothing would report OK on any drift."""
        commands = {claim.command for claim in guard.recognized_commands()}
        assert "make check" in commands
        assert "make guardrails" in commands
        assert any(command.startswith("uv run python -m scripts.seed") for command in commands)
        assert len(commands) >= 20

    def test_it_reads_the_real_decision_log(self) -> None:
        identifiers = guard.decision_ids()
        assert identifiers[0] == "D-01"
        assert len(identifiers) == len(set(identifiers)) >= 50

    def test_it_reads_the_real_compliance_section(self) -> None:
        tokens = set(guard.compliance_section_tokens())
        assert {"tm_registration_missing", "number_series_mismatch", "kyc_missing"} <= tokens

    def test_it_knows_the_rule_names_the_gates_emit(self) -> None:
        """Both shapes: the `LaunchBlocker(...)`/`DispatchDecision(rule=...)` constructors
        and the `(rule, reason)` pairs `kyc_blocker` and `first_campaign_hold_blocker`
        return. Missing the second shape would make §3's KYC and first-review bullets
        unverifiable."""
        rules = guard.emitted_rule_names()
        assert {"tm_registration_missing", "spend_cap", "dnc"} <= rules
        assert {"kyc_missing", "kyc_not_verified", "first_campaign_review_pending"} <= rules

    def test_it_reads_the_real_rate_zone_table(self) -> None:
        zones = guard.doc_rate_zones()
        assert zones["auth"] == "20r/m"
        assert {"admin_api", "client_api", "webhooks", "health", "default"} <= set(zones)


# ============================================================================
# detection — one real mutation each
# ============================================================================


class TestCommands:
    def test_catches_a_doc_naming_a_makefile_target_that_does_not_exist(
        self, tmp_path: Path
    ) -> None:
        """The drift this check exists for, and the cheapest to ship: a target is renamed
        in the Makefile and the four docs that name it are not."""
        root = _mirror(tmp_path, "docs/DEV-SETUP.md")
        path = _edit(root, "docs/DEV-SETUP.md", "make db-reset", "make db-restore")
        failures = guard.unresolved_commands(_claims(path))
        assert any("make db-restore" in f and "no such target" in f for f in failures), failures

    def test_catches_a_pnpm_script_that_is_not_in_that_packages_manifest(
        self, tmp_path: Path
    ) -> None:
        root = _mirror(tmp_path, "docs/DEV-SETUP.md")
        path = _edit(root, "docs/DEV-SETUP.md", "pnpm -C apps/web dev", "pnpm -C apps/web serve")
        failures = guard.unresolved_commands(_claims(path))
        assert any("pnpm serve" in f and "apps/web/package.json" in f for f in failures), failures

    def test_catches_a_script_named_against_the_wrong_package(self, tmp_path: Path) -> None:
        """`pnpm gen:api` and `pnpm -C apps/web gen:api` are not the same command: the
        first runs in the repo root, whose manifest declares no scripts at all. This was
        live drift in CLAUDE.md and docs/AGENTS.md when the check first ran."""
        root = tmp_path
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "X.md").write_text(
            "Regenerate the typed client with `pnpm gen:api`.\n", encoding="utf-8"
        )
        failures = guard.unresolved_commands(_claims(root / "docs" / "X.md"))
        assert any("pnpm gen:api" in f and "package.json" in f for f in failures), failures

    def test_catches_a_module_that_does_not_exist(self, tmp_path: Path) -> None:
        """`uv run python -m eval.run` — the second piece of live drift the first run
        found. The harness has been `scripts.eval` since it shipped."""
        root = tmp_path
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "X.md").write_text(
            "Run the harness (`uv run python -m eval.run --client <slug>`).\n", encoding="utf-8"
        )
        failures = guard.unresolved_commands(_claims(root / "docs" / "X.md"))
        assert any("python -m eval.run" in f for f in failures), failures

    def test_catches_a_bad_target_inside_a_fenced_block(self, tmp_path: Path) -> None:
        """Fenced blocks are where the copy-pasteable commands live, so a check that only
        read inline spans would miss the ones people actually run."""
        root = tmp_path
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "X.md").write_text(
            "Daily loop:\n\n```bash\nmake up\nmake typecheck\n```\n", encoding="utf-8"
        )
        failures = guard.unresolved_commands(_claims(root / "docs" / "X.md"))
        assert any("make typecheck" in f for f in failures), failures
        assert not any("make up" in f for f in failures), failures

    def test_catches_a_bad_command_after_an_and(self, tmp_path: Path) -> None:
        """`pnpm install && pnpm -C apps/web dev` is one line and two claims."""
        root = tmp_path
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "X.md").write_text(
            "```bash\npnpm install && pnpm -C apps/web devserver\n```\n", encoding="utf-8"
        )
        failures = guard.unresolved_commands(_claims(root / "docs" / "X.md"))
        assert any("pnpm devserver" in f for f in failures), failures


class TestCommandCalibration:
    """Measured false-positive shapes. Each of these WOULD have fired on the real docs
    before it was narrowed, and each stays green here or the narrowing has been lost."""

    def _findings(self, tmp_path: Path, markdown: str) -> list[str]:
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        path = tmp_path / "docs" / "X.md"
        path.write_text(markdown, encoding="utf-8")
        return guard.unresolved_commands(_claims(path))

    def test_prose_that_merely_contains_the_word_make(self, tmp_path: Path) -> None:
        """`-- is gone would make the NEXT publish refuse` (DATA-MODEL §, inside a SQL
        block). A doc that MEANS a command writes it at the start of a line."""
        block = "```sql\n-- this would make the NEXT publish refuse\n```\n"
        assert self._findings(tmp_path, block) == []

    def test_a_placeholder_argument(self, tmp_path: Path) -> None:
        """README documents `pnpm -C apps/web <script>` as a shape, not as a script."""
        assert self._findings(tmp_path, "breaks `pnpm -C apps/web <script>`\n") == []

    def test_the_alternation_shorthand(self, tmp_path: Path) -> None:
        """CLAUDE.md's `pnpm -C apps/web dev|build|typecheck|test` is FOUR claims, all
        true. Skipping it for containing a bar would silently drop four checks; treating
        it as a shell pipeline would invent a script called `dev|build|typecheck|test`."""
        assert self._findings(tmp_path, "`pnpm -C apps/web dev|build|typecheck|test`\n") == []

    def test_the_alternation_shorthand_is_still_checked(self, tmp_path: Path) -> None:
        findings = self._findings(tmp_path, "`pnpm -C apps/web dev|buidl|test`\n")
        assert any("pnpm buidl" in f for f in findings), findings

    def test_pnpms_own_subcommands(self, tmp_path: Path) -> None:
        block = "```bash\npnpm install\npnpm audit\npnpm dlx x\n```\n"
        assert self._findings(tmp_path, block) == []

    def test_make_flags_are_not_targets(self, tmp_path: Path) -> None:
        assert self._findings(tmp_path, "`make -j check`\n") == []

    def test_a_real_pipeline_is_split_but_a_shell_pipe_is_not_a_target(
        self, tmp_path: Path
    ) -> None:
        assert self._findings(tmp_path, "```bash\nmake check | tee out.log\n```\n") == []


class TestDecisionReferences:
    def test_catches_a_dangling_reference_in_a_doc(self, tmp_path: Path) -> None:
        absent = _absent_decision()
        root = tmp_path
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "X.md").write_text(
            f"The engine adapter follows D-31 and the retention floor {absent}.\n",
            encoding="utf-8",
        )
        failures = guard.dangling_decisions(roots=(root,))
        assert any(absent in f and "docs/X.md:1" in f for f in failures), failures
        assert not any("D-31" in f for f in failures), failures

    def test_catches_a_dangling_reference_in_code(self, tmp_path: Path) -> None:
        """A decision cited in a migration or a module docstring is exactly as unfollowable
        as one cited in a doc — which is why the citation scan is wider than the doc set."""
        absent = _absent_decision(offset=50)
        root = tmp_path
        (root / "apps").mkdir(parents=True, exist_ok=True)
        (root / "apps" / "service.py").write_text(
            f'"""Two-speed publishing per {absent}."""\n', encoding="utf-8"
        )
        failures = guard.dangling_decisions(roots=(root,))
        assert any(absent in f for f in failures), failures

    def test_catches_a_reference_that_a_renumbered_log_no_longer_carries(self) -> None:
        """The mutation is the LOG, not the citation: shorten the log and every real
        reference above the cut must come back into view. If it does not, the check is
        not actually reading the log and would not see a dangling number either."""
        identifiers = guard.decision_ids()
        failures = guard.dangling_decisions(ids=[i for i in identifiers if i != "D-31"])
        assert any("D-31" in f for f in failures), failures

    def test_catches_a_duplicate_decision_id(self) -> None:
        """Two branches both appending the next number is the likeliest collision on a
        trunk-based workflow, and it makes every citation of that number ambiguous."""
        repeated = guard.decision_ids()[-1]
        failures = guard.duplicate_decision_ids([*guard.decision_ids(), repeated])
        assert any(repeated in f and "ambiguous" in f for f in failures), failures


class TestRuleNames:
    def test_catches_a_rule_name_the_code_renamed_out_from_under_the_doc(self) -> None:
        """§3 promises "a screen, a test and this section can cite the same string". The
        mutation is the doc keeping a name the code no longer has — which is what a
        rename that stops at the code looks like from here."""
        document = guard.SECURITY_COMPLIANCE.read_text(encoding="utf-8")
        stale = document.replace("`number_series_mismatch`", "`number_series_mismatched`", 1)
        failures = guard.unknown_rule_names(text=stale)
        assert any("number_series_mismatched" in f for f in failures), failures

    def test_catches_a_blocker_the_doc_promises_and_nothing_emits(self) -> None:
        """The other direction of the same drift: a bullet written for a rule that was
        specified, agreed, and never built."""
        document = guard.SECURITY_COMPLIANCE.read_text(encoding="utf-8")
        bullet = "- Reseller cap not exceeded (`reseller_cap_exceeded`).\n"
        invented = document.replace("- Per-tenant caps", bullet + "- Per-tenant caps", 1)
        failures = guard.unknown_rule_names(text=invented)
        assert any("reseller_cap_exceeded" in f for f in failures), failures

    def test_does_not_cry_wolf_on_the_non_rule_vocabulary_of_the_same_section(self) -> None:
        """§3 quotes tables (`platform_state`, `spend_state`), enum members
        (`purchased_list`, `self_serve`, `submitted`) and functions (`launch_blockers`)
        in the same backticks as its rule names, and prose cannot tell them apart. They
        resolve because the CODE has them — which is why this check asks "does the code
        still spell this" instead of guessing which kind each token is. That is what
        keeps it exemption-free."""
        tokens = set(guard.compliance_section_tokens())
        assert {"platform_state", "purchased_list", "self_serve", "launch_blockers"} <= tokens
        assert guard.unknown_rule_names() == []

    def test_a_name_that_survives_only_in_a_docstring_does_not_count(self, tmp_path: Path) -> None:
        """The narrowing that makes section 3 work. A renamed rule almost always leaves
        its old name in a docstring somewhere (`provisioning_routes.py` documents
        `number_series_mismatch` in its module docstring), and counting prose about the
        code as the code would blind this check exactly where the drift is."""
        root = tmp_path / "apps"
        root.mkdir(parents=True, exist_ok=True)
        (root / "m.py").write_text(
            '"""Refuses with `number_series_mismatch`."""\n\nRULE = "series_mismatch"\n',
            encoding="utf-8",
        )
        vocabulary = guard.code_vocabulary(roots=(root,))
        assert "series_mismatch" in vocabulary
        assert "number_series_mismatch" not in vocabulary


class TestRateZones:
    """D-29's spec, no longer deferred. `infra/nginx/rate-zones.conf.template` landed with
    the deploy path, so `rate_zone_drift()` now judges the REAL tree on every CI run
    (`TestWiring.test_the_real_tree_is_clean`). These cases keep judging the comparator
    itself against synthetic templates in tmp_path — a check that is only ever run against
    a tree that passes has never been shown to fail."""

    def _template(self, root: Path, body: str) -> Path:
        path = root / "infra" / "nginx" / guard.RATE_ZONE_TEMPLATE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def _faithful(self) -> str:
        return "".join(
            f"limit_req_zone $binary_remote_addr zone={zone}:10m rate={rate};\n"
            for zone, rate in guard.doc_rate_zones().items()
        )

    def test_a_faithful_template_is_clean(self, tmp_path: Path) -> None:
        self._template(tmp_path, self._faithful())
        assert guard.rate_zone_drift(root=tmp_path) == []

    def test_catches_a_rate_that_disagrees(self, tmp_path: Path) -> None:
        """The drift that reads as fine in review, because every name lines up."""
        self._template(
            tmp_path,
            self._faithful().replace("zone=auth:10m rate=20r/m", "zone=auth:10m rate=200r/m"),
        )
        failures = guard.rate_zone_drift(root=tmp_path)
        assert any("`auth`" in f and "20r/m" in f and "200r/m" in f for f in failures), failures

    def test_catches_a_zone_the_edge_does_not_define(self, tmp_path: Path) -> None:
        body = "\n".join(
            line for line in self._faithful().splitlines() if "zone=webhooks" not in line
        )
        self._template(tmp_path, body)
        failures = guard.rate_zone_drift(root=tmp_path)
        assert any("`webhooks`" in f and "does not define it" in f for f in failures), failures

    def test_catches_a_zone_the_doc_never_declared(self, tmp_path: Path) -> None:
        self._template(
            tmp_path,
            self._faithful() + "limit_req_zone $binary_remote_addr zone=internal:10m rate=9r/s;\n",
        )
        failures = guard.rate_zone_drift(root=tmp_path)
        assert any("`internal`" in f and "does not list it" in f for f in failures), failures

    def test_the_deferral_fails_the_day_the_template_lands(self, tmp_path: Path) -> None:
        """A deferral outlives its subject or it is an excuse. This is what keeps
        DEFERRED_MIRRORS shrink-only: the entry cannot survive the file arriving.

        The real dict is now EMPTY — the template landed with the deploy path and the
        entry was deleted in the same change — so the deferral is supplied explicitly
        here. The mechanism still has to be exercised: the next deferral anybody adds
        inherits this rule, and a test that only passed while one particular entry
        existed would have retired the rule along with the entry."""
        self._template(tmp_path, self._faithful())
        failures = guard.stale_deferrals(
            root=tmp_path,
            deferrals={
                guard.RATE_ZONE_TEMPLATE_NAME: (
                    "a reason long enough to pass the thinness check, standing in for "
                    "the one this entry carried before the template landed"
                )
            },
        )
        assert any("Delete the entry" in f for f in failures), failures

    def test_a_reasonless_deferral_is_refused(self) -> None:
        failures = guard.stale_deferrals(deferrals={guard.RATE_ZONE_TEMPLATE_NAME: "TODO"})
        assert any("too thin" in f for f in failures), failures

    def test_the_deferral_is_pinned(self) -> None:
        """Deferring a mirror costs a visible diff in a TEST, not one line in a dict —
        the rule `guardrail_audit_test` applies to every other exemption here.

        The set is now empty, and that is the assertion worth keeping: `rate-zones.conf.template`
        exists in the tree, `rate_zone_drift()` judges it on every CI run, and nothing is
        deferred. Adding an entry to `DEFERRED_MIRRORS` must break this line."""
        assert set(guard.DEFERRED_MIRRORS) == set()


class TestBlindSpots:
    """A check that cannot find its subject must say so, never print OK."""

    def test_an_empty_doc_set_is_reported_as_blindness(self, tmp_path: Path) -> None:
        assert guard.doc_files(roots=(tmp_path,), extra=()) == []

    def test_a_makefile_with_no_targets_would_be_reported(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("# comments only\n", encoding="utf-8")
        assert guard.makefile_targets(tmp_path / "Makefile") == set()

    def test_a_log_whose_table_shape_changed_would_be_reported(self, tmp_path: Path) -> None:
        (tmp_path / "ROADMAP.md").write_text("D-01 Brand\nD-02 Engine\n", encoding="utf-8")
        assert guard.decision_ids(tmp_path / "ROADMAP.md") == []

    def test_a_renamed_compliance_section_yields_nothing(self) -> None:
        assert guard.compliance_section_tokens("## 2. Something\n`kyc_missing`\n") == []

    def test_a_rate_zone_table_that_moved_yields_nothing(self) -> None:
        assert guard.doc_rate_zones("## 5. nginx\nno table here\n") == {}


# ============================================================================
# the Makefile / CI surface
# ============================================================================


def test_the_guardrail_runs_in_both_gates() -> None:
    """A check nobody runs is a file. `tests/guardrail_audit_test.py` now globs
    `scripts/check_*.py` and asserts this for every guardrail; kept here too so the
    failure lands next to the check it is about."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts.check_docs_drift" in makefile
    assert "scripts.check_docs_drift" in workflow
