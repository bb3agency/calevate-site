"""Guardrail: the docs make MECHANICAL claims about this tree — do they still hold?

D-29 lists `check:docs-drift` for M2: "commands/targets named in docs exist in
Makefile/package scripts; decision-log references (D-xx) resolve; rate-zone table in
DEPLOYMENT.md matches `rate-zones.conf.template`". CLAUDE.md makes `docs/` authoritative,
which is exactly why drift here is expensive: an agent or a new hire reads the doc, runs
the command it names, and gets `No rule to make target`. The doc was believed — it was
just wrong about a fact nobody re-checked.

So this file does NOT judge prose. It answers four questions that have exactly one right
answer, each against a LIVE artefact rather than against a list of what we remember:

1. **Commands resolve.** Every `make <target>`, `pnpm <script>` and `python -m <module>`
   written as a COMMAND in a doc is looked up in the real `Makefile`, the real
   `package.json` of the package the command would actually run in, and the real tree.
   `pnpm gen:api` at the repo root is not the same claim as `pnpm -C apps/web gen:api`,
   and the first one fails — the root `package.json` has no scripts at all.
2. **Every `D-xx` resolves**, and the log has no duplicate ids. The decision log
   (ROADMAP §6) is the closest thing this repo has to a constitution: CLAUDE.md, the
   guardrails and half the module docstrings cite it by number. A reference to a number
   the log does not carry is a citation to nothing; a SECOND row with an existing number
   is worse, because every reference to it is now ambiguous and both readings look
   correct. (No example number is written out here — this file is scanned by its own
   section 2, and an illustration would be a dangling reference.)
3. **SECURITY-COMPLIANCE §3 still names things the code has.** §3 says of itself that
   each bullet names "the blocker `campaigns.service.launch_blockers` returns, so a
   screen, a test and this section can cite the same string". That promise is only worth
   something if a rename breaks it loudly. This is the rule-name-drift check
   `check_compliance_invariants` explicitly declined and pointed here
   ("that is `check:docs-drift`... Building half of it here would leave two checks that
   disagree about who owns the answer").
4. **The rate-zone table mirrors the nginx template** — the moment that template exists.
   See DEFERRED_MIRRORS below: the config half of this claim has never been in the repo,
   the deferral says so, and the deferral FAILS the day the file lands.

Docs win over code (CLAUDE.md), so nothing here rewrites anything or picks a side: every
failure names the artefact it read, the file and line the claim is on, and the artefact
the claim missed. Resolving it in one step is the whole point — a drift report that says
"something disagrees" is a second investigation, not a finding.

WHAT THIS DELIBERATELY DOES NOT DO, AND WHY
-------------------------------------------
* **Not a spell-checker, a link-checker or a prose linter.** Only claims a machine can
  decide. Whether a paragraph still describes the system is a review question and always
  will be; a check that guessed at it would be wrong often enough to train people to
  ignore it, which is how a guardrail dies.
* **No "every backticked path exists" check** — measured, then dropped. On today's tree
  that class produces ~17 hits and ~10 survive every honest narrowing, because the docs
  legitimately describe things that do not exist yet or deliberately do not exist:
  `scripts/vps-deploy.sh` and `.github/workflows/deploy.yml` (DEPLOYMENT describes the CD
  design; §7 is explicit that parts of it are "reviewed-but-unapplied"),
  `apps/api/src/engine/` (quoted by D-17 as the layout it REJECTED),
  `docs/evidence/restore-drill-YYYY-QN.md` (a filename template). Making that class green
  needs an exemption list that grows with every planned artefact — the failure mode this
  guardrail is written to avoid. The genuinely stale spellings it would have found
  (`packages/shared/config.py` for `packages/shared/src/calevate_shared/config.py`) are
  worth one review comment, not a check with a growing allowlist.
* **No telling a counter-example from an instruction.** A doc that wants to say "do NOT
  run `make lint` before committing, run the check-only target" cannot put the wrong
  command in a code span — section 1 will resolve it like any other claim. Accepted
  deliberately rather than papered over with a marker comment: the instruction is the
  reading that costs somebody an afternoon, and the cost of the rule is one sentence
  rewritten into prose.
* **No reverse command check** (a Makefile target no doc mentions). `make help` is the
  discovery surface, not the docs, and requiring prose for every target would push people
  to write filler.
* **No `uv run <tool>` check.** `pytest`, `ruff`, `alembic`, `arq` are dependency-provided
  console scripts; resolving them means resolving the lock file's entry points, and their
  drift mode (a tool removed from the dev group) is caught by the first CI run.
* **No coverage of flags or arguments.** `--client=<slug>` vs `--client <slug>` is
  argparse's business, and a doc that shows a placeholder is not making a claim about a
  literal string.
* **Nothing about §3 blockers the code emits but the doc does not name.** That direction
  is not drift: `big_red_switch`, `calling_hours`, `dnc`, `agent_not_live` are dial-time
  rules that SEC-COMP §2 and §3 discuss in prose without quoting the string, and a check
  demanding a mention for each would fire on correct docs.

Run: `uv run python -m scripts.check_docs_drift`  (also in `make guardrails`)

WHY `make guardrails` AND NOT PYTEST. Same argument `check_wiring` and
`check_compliance_invariants` make, and it lands the same way here: this check needs no
database and no app boot, and its subject is the SHAPE of the repo — the doc set against
the Makefile, the package scripts, the decision log and the code's own vocabulary — which
is the class of question `lint-imports` and the other tree scans answer in that sweep. Its
NEGATIVE CONTROLS need a mutated copy of the real tree and belong in pytest, where they
are: `tests/docs_drift_guard_test.py`.

Research note (2026-08, before writing this), so the next reader inherits the evidence
rather than the conclusion:

* **`markdown-link-check` / `lychee` / `mkdocs` strict mode** (lycheeverse/lychee;
  tcort/markdown-link-check). The standard tools for doc CI, and they answer a DIFFERENT
  question — does a URL or a relative link resolve. Useful, orthogonal, and none of them
  can tell that `make web-chek` is not a target, or that a cited decision number is not
  in the log, because the claim is not a link. Not adopted, not precluded: if this repo ever grows
  cross-document links worth checking, that is the tool, not this file.
* **Literate/executable documentation** — `mdsh`, `cog`, `pytest-codeblocks`, Rust's
  doctests: run the code blocks and diff the output. REJECTED for the command class: our
  doc blocks are `make dev`, `docker compose up -d`, `alembic downgrade base` — running
  them is not a check, it is a deployment. Resolving the NAME against the registry that
  would run it is the part with no side effects, and it is the part that drifts.
* **`ripgrep`-in-CI one-liners** (the raghava `docs:runtime-drift-check` shape this is
  adapted from). Adopted as the IDEA, not the mechanism: a grep asserts a string is
  present somewhere, which stays green when the string moves into a docstring that also
  went stale. Every question here resolves against a parsed registry instead — Makefile
  targets, `package.json` scripts, the decision-log table, the AST of the code — so a
  match cannot be satisfied by prose about itself.
* **Vale / textlint** (prose linters). Correctly rejected by the design constraint above:
  style opinions in a compliance-bearing repo's CI produce noise and no facts.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The doc set this guards. `docs/` is authoritative (CLAUDE.md), the runbooks are read at
# 3am by whoever is on call, and CLAUDE.md/README are the two files a new agent or hire
# reads first — a wrong command there costs the most and is seen the least.
DOC_ROOTS: tuple[Path, ...] = (REPO_ROOT / "docs", REPO_ROOT / "runbooks")
EXTRA_DOCS: tuple[Path, ...] = (REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md")

# Where the code's own vocabulary comes from (section 3). Not `tests/`: a test naming a
# rule string is a consumer of the name, not a definition of it.
CODE_ROOTS: tuple[Path, ...] = (REPO_ROOT / "apps", REPO_ROOT / "packages")

# Every place a `D-xx` may be cited. Wider than the doc set on purpose: a citation in a
# migration or a guardrail is exactly as dangling as one in a doc.
CITATION_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "docs",
    REPO_ROOT / "runbooks",
    REPO_ROOT / "apps",
    REPO_ROOT / "packages",
    REPO_ROOT / "scripts",
    REPO_ROOT / "tests",
    REPO_ROOT / "alembic",
    REPO_ROOT / "infra",
)

MAKEFILE = REPO_ROOT / "Makefile"
ROADMAP = REPO_ROOT / "docs" / "ROADMAP.md"
SECURITY_COMPLIANCE = REPO_ROOT / "docs" / "SECURITY-COMPLIANCE.md"
DEPLOYMENT = REPO_ROOT / "docs" / "DEPLOYMENT.md"

# The nginx snippet D-29's spec names. Located by FILENAME rather than by a hardcoded
# directory: the doc names the file, not its home, and pinning a directory here would
# make the check miss the real thing the day somebody lands it one level over.
RATE_ZONE_TEMPLATE_NAME = "rate-zones.conf.template"

# The one half of D-29's spec whose subject is not in this tree, with what closes it.
# A DEFERRAL, not an exemption: `stale_deferrals()` fails the moment the file exists, so
# this dict can only shrink and only by the artefact arriving. Same contract as
# `check_wiring.UNWIRED_BASELINE` and for the same reason — an exemption nobody can take
# away is one nobody can prove still describes reality.
DEFERRED_MIRRORS: dict[str, str] = {
    RATE_ZONE_TEMPLATE_NAME: (
        "nginx config has never lived in this repo. DEPLOYMENT §5 reuses raghava's "
        "`client.conf.template` + a `limit_req_zone` snippet installed at "
        "`/etc/nginx/snippets/` on the VPS, and §9's `vps-deploy.sh` (also not in the "
        "tree yet) is what renders it — so there is no local artefact for §5.4's zone "
        "table to disagree with, and inventing one here would be a config file nothing "
        "reads. `rate_zone_drift()` below is the comparator, written and tested, and it "
        "starts running the day a file with this name lands anywhere in the repo; this "
        "entry FAILS on that same day, so the deferral cannot outlive its subject."
    ),
}

# pnpm subcommands that are pnpm's own, not a script in a package.json. `test` and
# `start` are deliberately NOT here: pnpm shorthands them to the script of that name, so
# `pnpm test` is a claim about a script and must resolve like one.
PNPM_BUILTINS = frozenset(
    {
        "add",
        "audit",
        "config",
        "create",
        "deploy",
        "dlx",
        "exec",
        "fetch",
        "i",
        "import",
        "init",
        "install",
        "licenses",
        "link",
        "list",
        "ls",
        "outdated",
        "patch",
        "prune",
        "publish",
        "rebuild",
        "remove",
        "rm",
        "setup",
        "store",
        "up",
        "update",
        "why",
    }
)
# Flags that redirect pnpm at another package — the difference between a claim about the
# root `package.json` and a claim about `apps/web`'s.
PNPM_DIR_FLAGS = frozenset({"-C", "--dir"})
PNPM_FILTER_FLAGS = frozenset({"-F", "--filter"})

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_INLINE = re.compile(r"`([^`\n]+)`")
_MAKE_TARGET = re.compile(r"^([A-Za-z][\w-]*):", re.MULTILINE)
_DECISION_ROW = re.compile(r"^\|\s*(D-\d+)", re.MULTILINE)
_DECISION_REF = re.compile(r"\bD-\d+\b")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SNAKE_TOKEN = re.compile(r"[a-z][a-z0-9_]*$")
# `auth` 20r/m · `admin_api` 180r/m — DEPLOYMENT §5.4's table.
_DOC_ZONE = re.compile(r"`([a-z_]+)`\s+(\d+)r/([sm])")
# limit_req_zone $binary_remote_addr zone=auth:10m rate=20r/m;
_CONF_ZONE = re.compile(r"zone=([a-z_]+):\S*\s+rate=(\d+)r/([sm])")

# A shell segment boundary: what follows is a new command. `|` requires the spaces so
# that `dev|build|typecheck|test` (CLAUDE.md's alternation shorthand) is not mistaken for
# a pipeline.
_SEGMENT = re.compile(r"&&|\|\||;|\s\|\s")


@dataclass(frozen=True, slots=True)
class Claim:
    """A command a doc tells a human to run, and where it says so."""

    doc: str
    line: int
    command: str

    @property
    def where(self) -> str:
        return f"{self.doc}:{self.line}"


# --- reading the artefacts ------------------------------------------------------


def doc_files(
    roots: Iterable[Path] | None = None, extra: Iterable[Path] | None = None
) -> list[Path]:
    files = [
        path
        for root in (DOC_ROOTS if roots is None else roots)
        if root.exists()
        for path in sorted(root.rglob("*.md"))
    ]
    files += [path for path in (EXTRA_DOCS if extra is None else extra) if path.exists()]
    return files


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _code_spans(text: str) -> Iterator[tuple[int, str]]:
    """`(line number, code text)` for every fenced block body and inline code span.

    Prose is not scanned at all, which is the narrowing that makes the command check
    usable: "would make the NEXT publish refuse" contains `make the`, and a scan of raw
    prose reports it as a missing target. A doc that means a command writes it as one.
    """
    fenced: list[tuple[int, int]] = []
    for match in _FENCE.finditer(text):
        fenced.append((match.start(), match.end()))
        yield text.count("\n", 0, match.start(1)) + 1, match.group(1)
    for match in _INLINE.finditer(text):
        if any(start <= match.start() < end for start, end in fenced):
            continue  # backticks inside a fenced block are content, not a span
        yield text.count("\n", 0, match.start()) + 1, match.group(1)


def command_claims(paths: Iterable[Path] | None = None) -> list[Claim]:
    """Every code-span LINE that begins with a command this check can resolve.

    Anchored to the start of a line (or of a shell segment) because that is what makes a
    string a command rather than a mention of one.
    """
    claims: list[Claim] = []
    for path in doc_files() if paths is None else list(paths):
        text = path.read_text(encoding="utf-8")
        for start_line, span in _code_spans(text):
            for offset, line in enumerate(span.splitlines()):
                for segment in _SEGMENT.split(line):
                    command = segment.strip().lstrip("$ ").strip()
                    if command:
                        claims.append(Claim(_rel(path), start_line + offset, command))
    return claims


_MODULE_COMMAND = re.compile(r"^(?:uv\s+run\s+)?python[\d.]*\s+-m\s+([\w.]+)")


def recognized_commands(claims: Iterable[Claim] | None = None) -> list[Claim]:
    """The subset of code-span lines that are commands THIS check can resolve.

    `command_claims()` yields every shell-looking segment in the doc set, most of which
    are `docker compose up -d`, `psql`, `alembic` and friends — none of this file's
    business. The recognized subset is what section 1 actually judges, so it is the
    number `blind_spots()` watches and the number the OK line prints: "4709 segments
    scanned" would stay reassuringly large long after the resolvers stopped matching.
    """
    return [
        claim
        for claim in (command_claims() if claims is None else claims)
        if claim.command.split()[0] in {"make", "pnpm"} or _MODULE_COMMAND.match(claim.command)
    ]


def makefile_targets(makefile: Path | None = None) -> set[str]:
    return set(_MAKE_TARGET.findall((makefile or MAKEFILE).read_text(encoding="utf-8")))


def package_scripts(root: Path | None = None) -> dict[str, tuple[Path, frozenset[str]]]:
    """`{package name or directory: (package.json, its scripts)}` for the workspace.

    Read off the real `package.json` files rather than off `pnpm-workspace.yaml`'s globs:
    the file that defines the script is the file pnpm will read, and a package missing
    from the workspace list would still be reachable by `pnpm -C`.
    """
    base = root or REPO_ROOT
    packages: dict[str, tuple[Path, frozenset[str]]] = {}
    candidates = [base / "package.json", *sorted(base.glob("*/*/package.json"))]
    for manifest in candidates:
        if not manifest.exists() or "node_modules" in manifest.parts:
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        scripts = frozenset(data.get("scripts", {}))
        directory = manifest.parent.relative_to(base).as_posix() or "."
        packages[directory] = (manifest, scripts)
        name = data.get("name")
        if isinstance(name, str):
            packages.setdefault(name, (manifest, scripts))
    return packages


def decision_ids(roadmap: Path | None = None) -> list[str]:
    """The decision log's ids, IN ORDER — order is what makes duplicates visible."""
    return _DECISION_ROW.findall((roadmap or ROADMAP).read_text(encoding="utf-8"))


def _citation_files(roots: Iterable[Path] | None = None) -> Iterator[Path]:
    for root in CITATION_ROOTS if roots is None else roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix in {".md", ".py", ".sql", ".yml", ".yaml", ".toml", ".conf"}:
                yield path


# --- 1. commands resolve --------------------------------------------------------


def _placeholder(token: str) -> bool:
    """`<script>`, `${VAR}`, `…` — a shape, not a name. Nothing to resolve."""
    return any(character in token for character in "<>${}…") or "..." in token


def _resolve_make(claim: Claim, targets: set[str]) -> str | None:
    words = claim.command.split()
    if not words or words[0] != "make":
        return None
    rest = [word for word in words[1:] if not word.startswith("-")]
    if not rest or _placeholder(rest[0]):
        return None
    target = rest[0]
    if target in targets:
        return None
    return (
        f"{claim.where} tells the reader to run `make {target}`, and the Makefile has no "
        f"such target (it has: {', '.join(sorted(targets))}). Rename the target or fix "
        "the doc — docs win, so if the target is the wrong name, the target moves."
    )


def _pnpm_target(command: str, packages: dict[str, tuple[Path, frozenset[str]]]) -> str | None:
    """The package key `pnpm ...` would run in, or None when the doc names none.

    `-C apps/web` and `--filter web` are the same claim about `apps/web/package.json`;
    a bare `pnpm gen:api` is a claim about the ROOT manifest, which is a different file
    with a different set of scripts.
    """
    words = command.split()
    index, key = 1, "."
    while index < len(words) and words[index].startswith("-"):
        flag = words[index]
        if flag in PNPM_DIR_FLAGS | PNPM_FILTER_FLAGS and index + 1 < len(words):
            key = words[index + 1].strip("./")
            index += 2
            continue
        index += 1
    return key if key in packages or index < len(words) else None


def _resolve_pnpm(claim: Claim, packages: dict[str, tuple[Path, frozenset[str]]]) -> list[str]:
    words = claim.command.split()
    if not words or words[0] != "pnpm":
        return []
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in PNPM_DIR_FLAGS | PNPM_FILTER_FLAGS else 1
    if index >= len(words):
        return []
    word = words[index]
    if word == "run":
        if index + 1 >= len(words):
            return []
        word = words[index + 1]
    if _placeholder(word) or word in PNPM_BUILTINS:
        return []

    key = _pnpm_target(claim.command, packages)
    if key is None or key not in packages:
        return [
            f"{claim.where} runs `{claim.command}` against a package this workspace does "
            f"not have ({key!r}). Fix the `-C`/`--filter` argument."
        ]
    manifest, scripts = packages[key]
    # `dev|build|typecheck|test` — CLAUDE.md's shorthand for four commands. Split, so the
    # shorthand is checked rather than silently skipped for containing a bar.
    return [
        f"{claim.where} tells the reader to run `pnpm {alternative}` in "
        f"{_rel(manifest.parent) or 'the repo root'}, and {_rel(manifest)} declares no "
        f"such script (it declares: {', '.join(sorted(scripts)) or 'none'})."
        for alternative in word.split("|")
        if alternative and alternative not in scripts
    ]


def _resolve_module(claim: Claim) -> str | None:
    match = _MODULE_COMMAND.match(claim.command)
    if match is None:
        return None
    module = match.group(1)
    base = REPO_ROOT.joinpath(*module.split("."))
    if base.with_suffix(".py").exists() or (base / "__init__.py").exists():
        return None
    return (
        f"{claim.where} tells the reader to run `python -m {module}`, and there is no "
        f"such module in this tree ({_rel(base)}.py does not exist)."
    )


def unresolved_commands(claims: Iterable[Claim] | None = None) -> list[str]:
    """Commands a doc names that nothing in this repo answers to.

    The cheapest possible drift and the most expensive to meet: an agent following the
    doc runs the command, gets an error, and now has to decide whether the doc or the
    repo is wrong — which is the decision this check makes unnecessary by naming both
    sides.
    """
    targets = makefile_targets()
    packages = package_scripts()
    failures: list[str] = []
    for claim in command_claims() if claims is None else claims:
        make_failure = _resolve_make(claim, targets)
        if make_failure:
            failures.append(make_failure)
        failures.extend(_resolve_pnpm(claim, packages))
        module_failure = _resolve_module(claim)
        if module_failure:
            failures.append(module_failure)
    return failures


# --- 2. decision references resolve ---------------------------------------------


def dangling_decisions(
    ids: Iterable[str] | None = None, roots: Iterable[Path] | None = None
) -> list[str]:
    """Every `D-xx` in the repo names a row of ROADMAP §6.

    The log is cited by number in CLAUDE.md, in guardrail docstrings, in migrations and
    in the docs set; a number that resolves to nothing is a citation the reader cannot
    follow, and the usual cause is a decision that was drafted, referenced, and never
    appended.
    """
    known = set(decision_ids() if ids is None else ids)
    failures: list[str] = []
    for path in _citation_files(roots):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            for reference in sorted(set(_DECISION_REF.findall(line))):
                if reference not in known:
                    failures.append(
                        f"{_rel(path)}:{line_number} cites {reference}, which is not a row "
                        f"in {_rel(ROADMAP)} §6 (the log runs to {max(known)}). Append the "
                        "decision or fix the reference."
                    )
    return failures


def duplicate_decision_ids(ids: Iterable[str] | None = None) -> list[str]:
    """Two rows with one number make every citation of it ambiguous — and both readings
    look right, which is why this is worse than a dangling reference. It is also the
    likeliest collision on a trunk-based workflow: two branches both append the next number."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for identifier in decision_ids() if ids is None else ids:
        if identifier in seen and identifier not in duplicates:
            duplicates.append(identifier)
        seen.add(identifier)
    return [
        f"{_rel(ROADMAP)} §6 has more than one {identifier} row — every citation of it is "
        "ambiguous. Renumber the later decision."
        for identifier in duplicates
    ]


# --- 3. SEC-COMP §3 still names things the code has -----------------------------


def _section(text: str, heading: str, next_heading: str) -> str | None:
    if heading not in text:
        return None
    body = text.split(heading, 1)[1]
    return body.split(next_heading, 1)[0] if next_heading in body else body


def _docstring_constants(tree: ast.AST) -> set[int]:
    """Ids of Constant nodes that are docstrings — prose about the code, not the code.

    Excluded from the vocabulary below for the reason `check_wiring` excludes them from
    its column scan: a renamed rule usually leaves its old name in a docstring somewhere,
    and counting that as "the code still has this name" blinds the check exactly where
    the drift is.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _python_files(roots: Iterable[Path] | None = None) -> Iterator[Path]:
    for root in CODE_ROOTS if roots is None else roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path.name.endswith("_test.py"):
                continue
            yield path


def code_vocabulary(roots: Iterable[Path] | None = None) -> set[str]:
    """Every name the RUNNING code uses: identifiers plus non-docstring string literals.

    Non-docstring literals matter because most of the vocabulary §3 quotes lives in
    strings — rule names, enum members, table and column names in raw `text()` SQL
    (BACKEND-PATTERNS §3). Identifiers matter because §3 also cites functions
    (`launch_blockers`, `check_dispatch`) in the same backticks.
    """
    vocabulary: set[str] = set()
    for path in _python_files(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                vocabulary.add(node.id)
            elif isinstance(node, ast.Attribute):
                vocabulary.add(node.attr)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                vocabulary.add(node.name)
            elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg):
                vocabulary.add(str(node.arg))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                vocabulary.update(_IDENTIFIER.findall(node.value))
    return vocabulary


def emitted_rule_names(roots: Iterable[Path] | None = None) -> set[str]:
    """The rule strings the compliance gates actually produce.

    Keyed on the LIVE class names (`LaunchBlocker`, `DispatchDecision` are imported, not
    typed in) so a rename of either cannot leave this matching nothing, and extended with
    the `(rule, reason)` pair convention `kyc_blocker` / `first_campaign_hold_blocker`
    return — those two are annotated `tuple[str, str] | None` and their first element is
    the rule name a screen renders.
    """
    from apps.api.campaigns.service import LaunchBlocker
    from apps.api.compliance.service import DispatchDecision

    constructors = {LaunchBlocker.__name__, DispatchDecision.__name__}
    names: set[str] = set()
    for path in _python_files(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                called = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else getattr(function, "id", "")
                )
                if called in constructors:
                    if node.args and isinstance(node.args[0], ast.Constant):
                        names.add(str(node.args[0].value))
                    names.update(
                        str(keyword.value.value)
                        for keyword in node.keywords
                        if keyword.arg == "rule" and isinstance(keyword.value, ast.Constant)
                    )
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                names |= _pair_returns(node)
    return names


def _pair_returns(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """First elements of the `(rule, reason)` tuples a blocker predicate returns."""
    if function.returns is None or "tuple[str, str]" not in ast.unparse(function.returns):
        return set()
    return {
        str(node.value.elts[0].value)
        for node in ast.walk(function)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Tuple)
        and len(node.value.elts) == 2
        and isinstance(node.value.elts[0], ast.Constant)
        and isinstance(node.value.elts[0].value, str)
    }


def compliance_section_tokens(text: str | None = None) -> list[str]:
    """The snake_case names SECURITY-COMPLIANCE §3 quotes in backticks."""
    document = text if text is not None else SECURITY_COMPLIANCE.read_text(encoding="utf-8")
    body = _section(document, "\n## 3.", "\n## 4.")
    if body is None:
        return []
    return sorted({token for token in _INLINE.findall(body) if _SNAKE_TOKEN.match(token)})


def unknown_rule_names(text: str | None = None, roots: Iterable[Path] | None = None) -> list[str]:
    """Names §3 cites that the code no longer has, under any spelling.

    §3 promises that "a screen, a test and this section can cite the same string". The
    check that promise needs is not "is this token a rule" — that is not decidable from
    prose — but "does the code still contain this name at all", asked against the live
    vocabulary. A rename of `number_series_mismatch` empties the code side and this
    fires; a token that is a table name, an enum member or a function keeps resolving,
    so the check has no exemption list and never had to guess which kind each token is.
    """
    vocabulary = code_vocabulary(roots) | emitted_rule_names(roots)
    return [
        f"{_rel(SECURITY_COMPLIANCE)} §3 cites `{token}`, and no non-docstring name in "
        "apps/ or packages/ spells it. The gate's blocker strings are what a screen, a "
        "test and §3 are supposed to share — either the code was renamed and §3 was not, "
        "or §3 names a rule that was never built."
        for token in compliance_section_tokens(text)
        if token not in vocabulary
    ]


# --- 4. the rate-zone table mirrors the nginx template --------------------------


def doc_rate_zones(text: str | None = None) -> dict[str, str]:
    """DEPLOYMENT §5.4's zone table, as `{zone: rate}`."""
    document = text if text is not None else DEPLOYMENT.read_text(encoding="utf-8")
    body = _section(document, "**Rate zones**", "\n\n")
    if body is None:
        return {}
    return {zone: f"{rate}r/{unit}" for zone, rate, unit in _DOC_ZONE.findall(body)}


def conf_rate_zones(text: str) -> dict[str, str]:
    """`limit_req_zone` directives from an nginx template, as `{zone: rate}`.

    Parsed from the directive rather than from a comment, because the directive is what
    nginx enforces — the same argument `check_rls_coverage` makes for reading
    `pg_policies` instead of the migration that claims to have created the policy.
    (nginx.org/en/docs/http/ngx_http_limit_req_module.html — `zone=name:size`,
    `rate=Nr/s|Nr/m`.)
    """
    return {zone: f"{rate}r/{unit}" for zone, rate, unit in _CONF_ZONE.findall(text)}


def rate_zone_template(root: Path | None = None) -> Path | None:
    """The template wherever it lives, or None while it lives nowhere."""
    base = root or REPO_ROOT
    return next(
        (
            path
            for path in sorted(base.rglob(RATE_ZONE_TEMPLATE_NAME))
            if "node_modules" not in path.parts
        ),
        None,
    )


def rate_zone_drift(root: Path | None = None, text: str | None = None) -> list[str]:
    """The doc's table against the config the edge would actually load.

    Both directions: a zone in one and not the other is drift, and so is a zone in both
    at different rates — the second is the one that reads as fine in review, because the
    names all line up.
    """
    template = rate_zone_template(root)
    if template is None:
        return []  # deferred; `stale_deferrals()` owns the day that stops being true
    declared = doc_rate_zones(text)
    configured = conf_rate_zones(template.read_text(encoding="utf-8"))
    failures = [
        f"{_rel(DEPLOYMENT)} §5.4 declares rate zone `{zone}` at {rate}, and "
        f"{_rel(template)} does not define it"
        for zone, rate in sorted(declared.items())
        if zone not in configured
    ]
    failures += [
        f"{_rel(template)} defines rate zone `{zone}` at {rate}, and {_rel(DEPLOYMENT)} "
        "§5.4's table does not list it"
        for zone, rate in sorted(configured.items())
        if zone not in declared
    ]
    failures += [
        f"rate zone `{zone}`: {_rel(DEPLOYMENT)} §5.4 says {declared[zone]}, "
        f"{_rel(template)} says {configured[zone]}. The edge enforces the template"
        for zone in sorted(set(declared) & set(configured))
        if declared[zone] != configured[zone]
    ]
    return failures


def stale_deferrals(root: Path | None = None, deferrals: dict[str, str] | None = None) -> list[str]:
    """A deferral outlives its subject or it is an excuse. Two ways this rots: the
    artefact arrives and the entry stays (the comparator above is now running, so the
    entry buys nothing and hides that fact), or the reason is too thin to weigh."""
    entries = DEFERRED_MIRRORS if deferrals is None else deferrals
    failures: list[str] = []
    for name, reason in sorted(entries.items()):
        if name == RATE_ZONE_TEMPLATE_NAME and rate_zone_template(root) is not None:
            failures.append(
                f"DEFERRED_MIRRORS still defers `{name}`, and the file now exists at "
                f"{_rel(rate_zone_template(root) or Path(name))}. Delete the entry — the "
                "comparator has been running since it landed."
            )
        if len(reason.strip()) < 40:
            failures.append(
                f"DEFERRED_MIRRORS entry `{name}` has a reason too thin to review: "
                f"{reason!r}. Say why the subject is absent and what closes it."
            )
    return failures


# --- has the tree moved out from under this check? ------------------------------


def blind_spots() -> list[str]:
    """A check that finds no subject must say so, never print OK.

    Each of the four sections above is a comparison, and every one of them passes
    vacuously if the artefact it reads stops parsing — a renamed heading, a Makefile it
    cannot find, a decision log whose table gains a column. This is where that becomes a
    failure instead of a green run.
    """
    failures: list[str] = []
    documents = doc_files()
    if len(documents) < 5:
        failures.append(
            f"only {len(documents)} doc(s) found under {[_rel(root) for root in DOC_ROOTS]} — "
            "the doc scan is looking at the wrong place and every section below is empty"
        )
    if not makefile_targets():
        failures.append(f"no targets parsed out of {_rel(MAKEFILE)} — section 1 matches nothing")
    if not any(scripts for _, scripts in package_scripts().values()):
        failures.append("no package.json in the workspace declares any script")
    claims = recognized_commands()
    if len(claims) < 20:
        failures.append(
            f"only {len(claims)} command claim(s) extracted from the doc set — the code-span "
            "scan has stopped seeing commands, so section 1 would report OK on anything"
        )
    identifiers = decision_ids()
    if len(identifiers) < 10:
        failures.append(
            f"{_rel(ROADMAP)} §6 parsed to {len(identifiers)} decision(s) — the log table's "
            "shape changed and every `D-xx` reference would be reported as dangling"
        )
    tokens = compliance_section_tokens()
    rules = emitted_rule_names()
    if not tokens:
        failures.append(
            f"{_rel(SECURITY_COMPLIANCE)} §3 yielded no backticked names — the heading moved "
            "and the rule-name check is reading an empty section"
        )
    if not rules:
        failures.append(
            "no rule names extracted from the gate constructors — `LaunchBlocker` / "
            "`DispatchDecision` changed shape and section 3 lost half its registry"
        )
    if tokens and rules and not (set(tokens) & rules):
        failures.append(
            f"{_rel(SECURITY_COMPLIANCE)} §3 quotes no rule the gate emits. §3's own promise "
            "is that it cites the strings `launch_blockers` returns; either that stopped "
            "being true or this check is reading the wrong section"
        )
    if not doc_rate_zones():
        failures.append(
            f"{_rel(DEPLOYMENT)} §5.4's rate-zone table did not parse — section 4 would "
            "accept any template that ever lands"
        )
    return failures


# --- gate -----------------------------------------------------------------------


def main() -> int:
    sections: tuple[tuple[str, list[str]], ...] = (
        ("this check cannot see its own subject", blind_spots()),
        ("a doc names a command nothing answers to", unresolved_commands()),
        ("a decision reference resolves to nothing", dangling_decisions()),
        ("the decision log numbers a decision twice", duplicate_decision_ids()),
        ("a compliance rule name the code no longer has", unknown_rule_names()),
        ("the rate-zone table and the nginx template disagree", rate_zone_drift()),
        ("a deferral that no longer holds", stale_deferrals()),
    )
    failed = False
    for title, offenders in sections:
        if offenders:
            failed = True
            print(f"DOCS DRIFT: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            "\nThe docs are authoritative (CLAUDE.md), so this reports rather than "
            "picks: each line names the artefact it read and where. Fix whichever side "
            "is wrong — and if it is the code, the doc is the spec."
        )
        return 1

    print(
        f"DOCS DRIFT: OK ({len(recognized_commands())} command claims resolve, "
        f"{len(decision_ids())} decisions with no dangling reference, "
        f"{len(compliance_section_tokens())} names in SEC-COMP §3 still in the code, "
        f"{len(doc_rate_zones())} rate zones declared, "
        f"{len(DEFERRED_MIRRORS)} deferred mirror)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
