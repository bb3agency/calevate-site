"""The web-env-parity guardrail, proved against the states it exists to catch.

`scripts/check_web_env_parity.py` claims that every variable `apps/web` reads is declared,
that every declared variable is read, that no `NEXT_PUBLIC_` key is shaped like a secret,
and that nothing reaches `process.env` in a form `next build` cannot inline. A check making
those claims while blind to a violation is worse than no check here specifically, because
the violation it guards is ALREADY silent: an undeclared browser key does not throw, it
compiles to the empty string and ships.

Same three kinds of test the newer guardrails established
(`tests/docs_drift_guard_test.py`, `tests/compliance_guard_test.py`):

- **wiring** — the check is pointed at the REAL tree, so a check that has drifted away from
  what it claims to read fails here;
- **detection** — mirror the real `apps/web` into a scratch tree, apply ONE minimal mutation
  that IS the violation, and run the REAL `main()` against it. Every mutation below is a
  real file with one line changed; an invented fixture would stop resembling the app the
  moment the app moved;
- **calibration** — the false-positive shapes that would have fired before the scan was
  narrowed (a key named in a comment, a `//` inside a URL string), pinned as tests that must
  report NOTHING.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts import check_web_env_parity as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARATION = guard.DECLARATION_FILE.as_posix()


# --- helpers ------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A scratch copy of the real web package: its sources and its declaration file.

    `apps/web/src` verbatim rather than a fixture, at its real relative path, because every
    failure names `path:line` and a mutation only reads like the real thing if it sits where
    the real thing sits. `node_modules`/`.next` are not copied — the scan excludes them, and
    copying them would cost seconds per test.
    """
    web = tmp_path / guard.WEB_PACKAGE
    web.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / guard.WEB_PACKAGE / "src", web / "src")
    shutil.copy(REPO_ROOT / guard.DECLARATION_FILE, web / ".env.example")
    return tmp_path


def _edit(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    assert old in source, f"the mutation no longer matches {relative} — update this test"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _append(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """The real gate, against a scratch tree. Returns its exit code and what it printed."""
    code = guard.main(root=root)
    return code, capsys.readouterr().out


# ============================================================================
# wiring + does-not-cry-wolf on the CURRENT tree
# ============================================================================


class TestTheRealTree:
    def test_the_gate_is_green_and_says_what_it_saw(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The standing assertion, and the calibration that matters most: this check runs
        over the app as it is today and must find NOTHING. A guardrail whose first act is to
        fire on correct code is a guardrail with an exemption list."""
        assert guard.main() == 0
        assert "WEB ENV PARITY: OK" in capsys.readouterr().out

    def test_every_section_is_clean(self) -> None:
        state = guard.collect()
        for title, offenders in guard.evaluate(state):
            assert offenders == [], f"{title}: {offenders}"

    def test_it_reads_the_real_declaration_file(self) -> None:
        state = guard.collect()
        assert state.declaration_exists
        assert "NEXT_PUBLIC_AUTH_MODE" in state.declared
        assert state.declared["NEXT_PUBLIC_API_BASE_URL"] == "http://localhost:8000"
        assert state.duplicates == []

    def test_it_finds_the_reads_the_app_actually_makes(self) -> None:
        """Not a pinned count — a new browser key must not cost a test edit. What is pinned
        is that the scan still SEES the load-bearing ones, including the one that decides
        which credential the browser presents."""
        reads = guard.collect().usage.reads
        assert "NEXT_PUBLIC_AUTH_MODE" in reads
        assert "NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY" in reads
        assert "NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY" in reads
        assert any("lib/auth/mode.ts" in site for site in reads["NEXT_PUBLIC_AUTH_MODE"])

    def test_the_two_halves_of_config_parity_do_not_overlap(self) -> None:
        """One way per problem: the API's file declares no browser key, and the browser's
        file declares nothing the API's `Settings` would have to carry."""
        from scripts import check_env_parity

        api_declared, _ = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        web_declared = set(guard.collect().declared)
        assert not any(key.startswith("next_public_") for key in api_declared)
        assert not {key.lower() for key in web_declared} & api_declared

    def test_the_registry_is_pinned(self) -> None:
        """Declaring a browser-visible value "public by design" costs a visible diff in a
        TEST, not one line in a dict — the rule every other exemption here follows."""
        assert set(guard.PUBLIC_BY_DESIGN) == {
            "NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY",
            "NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY",
        }


# ============================================================================
# detection — one real mutation each, through the real main()
# ============================================================================


class TestUndeclaredReads:
    def test_the_mirror_starts_green(self, tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Without this, every detection test below could pass for the wrong reason."""
        code, output = _run(tree, capsys)
        assert code == 0, output

    def test_catches_a_read_nothing_declares(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The failure this guardrail exists for. In the bundle this is not an error and not
        a crash — it is `""`, in production, on a screen."""
        _append(
            tree,
            "apps/web/src/lib/api/signup.ts",
            '\nexport const PLAN_TIER = process.env.NEXT_PUBLIC_DEFAULT_PLAN_TIER ?? "starter";\n',
        )
        code, output = _run(tree, capsys)
        assert code == 1
        assert "NEXT_PUBLIC_DEFAULT_PLAN_TIER is read at" in output
        assert "lib/api/signup.ts" in output

    def test_catches_a_misspelled_key_even_though_the_right_one_is_declared(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The typo case, which is the likeliest of all and the one `tsc` is blindest to:
        `process.env.ANYTHING` type-checks."""
        _edit(
            tree,
            "apps/web/src/lib/api/client.ts",
            "process.env.NEXT_PUBLIC_API_BASE_URL",
            "process.env.NEXT_PUBLIC_API_BASEURL",
        )
        code, output = _run(tree, capsys)
        assert code == 1
        assert "NEXT_PUBLIC_API_BASEURL is read at" in output
        assert "NEXT_PUBLIC_API_BASE_URL and nothing" in output, "and the real key is now dead"


class TestUnreadDeclarations:
    def test_catches_a_declaration_nothing_reads(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """How a stale key survives a refactor: it stays in the template and in three deploy
        environments, and the next person configures something that decides nothing."""
        _append(tree, DECLARATION, "NEXT_PUBLIC_LEGACY_PORTAL_URL=https://old.calevate.tech\n")
        code, output = _run(tree, capsys)
        assert code == 1
        assert "declares NEXT_PUBLIC_LEGACY_PORTAL_URL and nothing" in output
        assert "reads it" in output

    def test_catches_the_auth_mode_read_being_replaced_by_a_constant(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The sharpest instance of the stale direction, and a proof that PROSE IS NOT A
        READ: `mode.ts` names `NEXT_PUBLIC_AUTH_MODE` five times in its docstring and once as
        a string constant. With the actual read gone, the deployment's `clerk`/`dev` choice
        is decided by nothing — and the check must still see that, or the comments are doing
        the work the code stopped doing."""
        _edit(tree, "apps/web/src/lib/auth/mode.ts", "process.env.NEXT_PUBLIC_AUTH_MODE", '""')
        code, output = _run(tree, capsys)
        assert code == 1
        assert "declares NEXT_PUBLIC_AUTH_MODE" in output
        assert "as a string, not as `process.env.NEXT_PUBLIC_AUTH_MODE`" in output


class TestSecretShapedKeys:
    def test_catches_a_secret_shaped_public_key(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`NEXT_PUBLIC_` is not a namespace, it is a PUBLICATION instruction: the value is
        written into the JavaScript every visitor downloads. A BYOK vendor key reaching it is
        a credential disclosure that lints clean and type-checks."""
        _append(tree, DECLARATION, "NEXT_PUBLIC_SARVAM_API_KEY=\n")
        _append(
            tree,
            "apps/web/src/lib/api/client.ts",
            "\nexport const SARVAM = process.env.NEXT_PUBLIC_SARVAM_API_KEY;\n",
        )
        code, output = _run(tree, capsys)
        assert code == 1
        assert "NEXT_PUBLIC_SARVAM_API_KEY is named like a credential (`_KEY`)" in output
        assert "there is no private one" in output

    @pytest.mark.parametrize(
        "key",
        [
            "NEXT_PUBLIC_WEBHOOK_SECRET",
            "NEXT_PUBLIC_ADMIN_PASSWORD",
            "NEXT_PUBLIC_SESSION_TOKEN",
            "NEXT_PUBLIC_SIGNING_PRIVATE_KEY",
        ],
    )
    def test_the_shapes_it_refuses(self, key: str) -> None:
        assert guard._secret_shape(key) is not None

    @pytest.mark.parametrize(
        "key",
        [
            "NEXT_PUBLIC_AUTH_MODE",
            "NEXT_PUBLIC_API_BASE_URL",
            "NEXT_PUBLIC_SIGNUP_CONTACT_EMAIL",
            "NEXT_PUBLIC_SORT_KEY_LABEL",
        ],
    )
    def test_the_shapes_it_leaves_alone(self, key: str) -> None:
        """`_KEY` is credential-shaped at the END of a name and nowhere else. A check that
        fired on `SORT_KEY_LABEL` would teach people to add exemptions."""
        assert guard._secret_shape(key) is None

    def test_a_publishable_key_passes_only_because_the_registry_says_why(self) -> None:
        """The mutation is the EXEMPTION, not the tree: the two Clerk keys are legitimately
        named and legitimately public, and the ONLY thing keeping them green is the entry
        recording that `publishable` is the vendor's own word for the public half. Take it
        away and they must come back into view, or the entry is load-bearing for nothing."""
        offenders = guard.secret_shaped_keys(guard.collect(), registry={})
        assert any("NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY" in o for o in offenders)
        assert any("NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY" in o for o in offenders)

    def test_a_stale_registry_entry_is_refused(self) -> None:
        state = guard.collect()
        failures = guard.stale_registry(
            state,
            registry={
                **guard.PUBLIC_BY_DESIGN,
                "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY": (
                    "kept long after the key was removed, which is how an exemption list "
                    "turns into a hiding place for the next key that lands on that name"
                ),
            },
        )
        assert any("NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY" in f and "remove it" in f for f in failures)

    def test_a_reasonless_registry_entry_is_refused(self) -> None:
        state = guard.collect()
        failures = guard.stale_registry(
            state, registry={"NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY": "it's fine"}
        )
        assert any("too thin to review" in f for f in failures)


class TestUninlinableReads:
    def test_catches_a_dynamic_lookup(self, tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Next's own documented limitation: static replacement matches the literal
        expression and nothing else, so `process.env[name]` is `undefined` in the browser.
        This is the refactor that turns a working read into an empty one while every test
        that stubs `process.env` in node keeps passing."""
        _edit(
            tree,
            "apps/web/src/lib/auth/adminRealm.tsx",
            "process.env.NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY",
            "process.env[ADMIN_PUBLISHABLE_KEY_ENV]",
        )
        code, output = _run(tree, capsys)
        assert code == 1
        assert "reaches `process.env` other than as `process.env.NAME`" in output
        assert "lib/auth/adminRealm.tsx" in output

    def test_catches_a_destructure(self, tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _append(
            tree,
            "apps/web/src/lib/api/signup.ts",
            "\nconst { NEXT_PUBLIC_SIGNUP_CONTACT_EMAIL: fallback } = process.env;\n"
            "export const CONTACT = fallback;\n",
        )
        code, output = _run(tree, capsys)
        assert code == 1
        assert "reaches `process.env` other than as `process.env.NAME`" in output


class TestTheTemplateIsSafeToCopy:
    def test_catches_an_empty_declaration_that_would_override_a_default(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`??` falls back on `undefined`, never on the `""` a bare `KEY=` line produces. A
        developer who copies the template would point every request at "" — relative, and
        404 against the Next server. The template has to be safe to copy or it is a trap."""
        _edit(
            tree,
            DECLARATION,
            "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000",
            "NEXT_PUBLIC_API_BASE_URL=",
        )
        code, output = _run(tree, capsys)
        assert code == 1
        assert "declares NEXT_PUBLIC_API_BASE_URL empty" in output
        assert "http://localhost:8000" in output

    def test_an_empty_declaration_is_fine_when_the_code_defaults_to_empty(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Calibration: the publishable keys read `?? ""`, so an empty line changes nothing
        and must not be reported. The rule is about a default the template would DESTROY."""
        code, output = _run(tree, capsys)
        assert code == 0, output

    def test_catches_a_duplicate_declaration(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """dotenv keeps the LAST assignment, so the line somebody edits may not be the line
        that wins — the same trap the API's half of this rule catches in the root file."""
        _append(tree, DECLARATION, "NEXT_PUBLIC_AUTH_MODE=dev\n")
        code, output = _run(tree, capsys)
        assert code == 1
        assert "declares NEXT_PUBLIC_AUTH_MODE twice" in output


# ============================================================================
# blind spots — a check that cannot see its subject must say so
# ============================================================================


class TestBlindSpots:
    def test_a_moved_package_fails_rather_than_reporting_ok(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The house rule: a scan that matches nothing FAILS. Move the package — a rename,
        a second web app, a `packages/` reshuffle — and every question above would be
        comparing an empty scan against an empty file and printing OK.

        Note what is NOT asserted: the scan does not care where inside `apps/web` a source
        file sits, so renaming `src/` proves nothing (the walk finds it anyway). Only the
        package moving out from under `WEB_PACKAGE` actually blinds this check, so that is
        the mutation."""
        (tree / "apps/web").rename(tree / "apps/webapp")
        code, output = _run(tree, capsys)
        assert code == 1
        assert "does not exist" in output
        assert "the scan is looking at the wrong place" in output
        assert "no `process.env` read found" in output

    def test_a_renamed_source_directory_is_still_seen(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The other side of the same coin, pinned so nobody "fixes" the scan by hardcoding
        `src/`: what Next compiles is decided by file EXTENSION and by what is excluded, not
        by one directory name."""
        (tree / "apps/web/src").rename(tree / "apps/web/source")
        code, output = _run(tree, capsys)
        assert code == 0, output

    def test_a_missing_declaration_file_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / DECLARATION).unlink()
        code, output = _run(tree, capsys)
        assert code == 1
        assert "does not exist" in output

    def test_a_declaration_file_that_stopped_parsing_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A file whose grammar changed — every line commented out, say — leaves both
        directions comparing against nothing."""
        path = tree / DECLARATION
        path.write_text("# nothing but prose now\n", encoding="utf-8")
        code, output = _run(tree, capsys)
        assert code == 1
        assert "parsed to zero keys" in output


# ============================================================================
# calibration — the lexer, on the shapes that would have broken it
# ============================================================================


class TestCommentStripping:
    def test_a_key_named_only_in_a_comment_is_not_a_read(self) -> None:
        """The narrowing that makes the stale direction work — and it is load-bearing on the
        REAL tree: `lib/auth/clientRealm.tsx` explains in a comment why the key is NOT called
        `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`. Counted as a mention, that comment alone would
        fail this guardrail against correct code."""
        code = guard.strip_comments(
            "// process.env.NEXT_PUBLIC_GHOST\n"
            "/* NEXT_PUBLIC_PHANTOM */\n"
            "const real = process.env.NEXT_PUBLIC_REAL;\n"
        )
        assert "NEXT_PUBLIC_GHOST" not in code
        assert "NEXT_PUBLIC_PHANTOM" not in code
        assert "process.env.NEXT_PUBLIC_REAL" in code

    def test_a_double_slash_inside_a_string_is_not_a_comment(self) -> None:
        """`"http://localhost:8000"` is in the real `client.ts`, two lines from a read. A
        naive comment-stripper eats the rest of that line and the read with it."""
        source = 'const base = "http://localhost:8000";\nconst x = process.env.NEXT_PUBLIC_X;\n'
        assert "process.env.NEXT_PUBLIC_X" in guard.strip_comments(source)

    def test_line_numbers_survive_stripping(self) -> None:
        """Offsets are preserved so every finding can name `path:line`. A stripper that
        deleted characters would report the wrong line, which is a finding nobody can act
        on."""
        source = "/* a\n   multi-line\n   comment */\nconst x = process.env.NEXT_PUBLIC_X;\n"
        stripped = guard.strip_comments(source)
        assert len(stripped) == len(source)
        position = stripped.index("process.env")
        assert guard._line_of(stripped, position) == 4

    def test_a_template_literal_hole_is_still_code(self) -> None:
        source = "const u = `${process.env.NEXT_PUBLIC_API_BASE_URL}/v1/calls`;\n"
        assert "process.env.NEXT_PUBLIC_API_BASE_URL" in guard.strip_comments(source)


# ============================================================================
# the Makefile / CI surface
# ============================================================================


def test_the_guardrail_runs_in_both_gates() -> None:
    """A check nobody runs is a file. `tests/guardrail_audit_test.py` globs
    `scripts/check_*.py` and asserts this for every guardrail; kept here too so the failure
    lands next to the check it is about."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts.check_web_env_parity" in makefile
    assert "scripts.check_web_env_parity" in workflow


def test_the_declaration_file_is_committed_not_ignored() -> None:
    """`apps/web/.gitignore` ignores `.env*`, and a template nobody can check out is not a
    template. The negation is in that file for this reason; a checkout without the file
    fails `blind_spots()` on the next run, so this is the earlier, clearer failure."""
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "-q", guard.DECLARATION_FILE.as_posix()],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 1, f"{DECLARATION} is git-ignored"
