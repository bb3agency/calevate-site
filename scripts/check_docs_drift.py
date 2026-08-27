"""Guardrail: the docs make MECHANICAL claims about this tree — do they still hold?

D-29 lists `check:docs-drift` for M2: "commands/targets named in docs exist in
Makefile/package scripts; decision-log references (D-xx) resolve; rate-zone table in
DEPLOYMENT.md matches `rate-zones.conf.template`". CLAUDE.md makes `docs/` authoritative,
which is exactly why drift here is expensive: an agent or a new hire reads the doc, runs
the command it names, and gets `No rule to make target`. The doc was believed — it was
just wrong about a fact nobody re-checked.

So this file does NOT judge prose. It answers six questions that have exactly one right
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
   the deferral says so, and the deferral FAILS the day the file lands. Note what this
   one is NOT about: `limit_req_zone` is REQUESTS per second, not rupees.
4b. **The MONEY rate card mirrors what the biller bills.** TRD §10.1 prices the two TTS
   rungs and `billing/rates.py::TTS_INR_PER_10K_CHARS` charges them, and until this
   section existed a vendor price move could land in one and not the other with nothing
   in the tree able to see it — the same class as 5 below, on the axis where it costs
   money rather than credibility. §10.1 states each rate TWICE (per 10,000 chars in the
   Sarvam card, per 1,000 in the per-minute table), so the doc is also checked against
   itself: a document that disagrees with its own other table is the cheapest version of
   this failure and the likeliest to survive review.
5. **Prose that STATES a capability constant's value states the value the tree has.**
   This repo's defence against overclaiming is a greppable boolean beside the code —
   `PROVIDER_CREATES_ORDERS`, `LEAD_RETRIEVAL_IMPLEMENTED`, `PROVISIONING_IMPLEMENTED`,
   `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA`, `ENGINE_REPORTS_TTS_MODEL` — so that "is this
   built" is answered by `grep`, not by a paragraph. It works in one direction only: it
   stops us claiming a capability we do not have. It has never noticed the REVERSE, which
   is what D-102 was written for and what an audit found four times over — a constant
   flips to True and every sentence quoting its old value keeps saying "not built". That
   understates the system, which reads as modesty and is just as wrong: it is why a
   shipped checkout sat behind three docs saying no checkout existed. See
   `capability_drift()` for the matching rule and, more importantly, for the false
   positives it is shaped to avoid.

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
* **No judging a capability sentence that quotes no constant.** Section 5 reads
  `NAME is False`, never "WhatsApp has no vendor adapter, because no decision picks a
  BSP" — which was live drift in BUILD-LOG's inventory (D-91 picked Meta Cloud API and
  `apps/workers/whatsapp_cloud.py` implements the transport) and which no matcher can
  decide, because the sentence names nothing a machine can look up. Deliberately given
  up rather than approximated: a grep-shaped guard over this class was written for the
  credential rule earlier in the same day, flagged three files that merely NAMED a
  credential, caught neither real offender, and was thrown away. Half of a mechanically
  decidable question is worth more than all of an undecidable one. What closes the other
  half is a constant: a capability worth a paragraph is worth a greppable boolean, and
  the moment WhatsApp's got one — `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` — the prose
  about it became checkable here.

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
import io
import json
import re
import sys
import tokenize
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
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

# Section 5's two halves. CAPABILITY_ROOTS is where a capability constant may be DEFINED
# and where Python prose about one may live; `tests/` is in it for the prose half (a test
# docstring quoting a constant's value drifts exactly like a doc's) and costs nothing on
# the definition half, because no test defines a module-level boolean.
CAPABILITY_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "apps",
    REPO_ROOT / "packages",
    REPO_ROOT / "scripts",
    REPO_ROOT / "alembic",
    REPO_ROOT / "tests",
    REPO_ROOT / "infra",
)
# The console carries the same claims in JSDoc above the screens that render the refusal
# (`/c/[slug]/verification` explains why there is no purchase form). Scanned as raw text
# rather than through a JS comment parser: `True`/`False` are Python spellings, TypeScript
# writes `true`/`false`, and no `.ts` file binds these names — so a hit in this tree is
# necessarily prose ABOUT the Python constant and never TypeScript source.
WEB_SOURCE_ROOT = REPO_ROOT / "apps" / "web" / "src"

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

# Deferrals: half of a spec whose subject is not in this tree, each with what closes it.
# A DEFERRAL, not an exemption: `stale_deferrals()` fails the moment the file exists, so
# this dict can only shrink and only by the artefact arriving. Same contract as
# `check_wiring.UNWIRED_BASELINE` and for the same reason — an exemption nobody can take
# away is one nobody can prove still describes reality.
#
# EMPTY, and it got that way the honest way. It held exactly one entry —
# `rate-zones.conf.template`, deferred because nginx config had never lived in this repo.
# `infra/nginx/rate-zones.conf.template` landed with the deploy path (`scripts/vps-deploy.sh`
# renders it), so `rate_zone_drift()` below stopped returning early and now diffs
# DEPLOYMENT §5.4's zone table against the directives the edge would actually load. The
# entry was deleted in the same change, which is what the deferral's own text promised
# would happen on that day.
#
# Leave the dict here rather than deleting the mechanism: the next spec whose subject
# lands later needs somewhere to say so out loud, and `stale_deferrals()` is what keeps
# such an entry from becoming permanent.
DEFERRED_MIRRORS: dict[str, str] = {}

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
#: id | title | what was decided | why. Named rather than inlined so the message
#: below and the check itself cannot drift apart.
_DECISION_COLUMNS = 4
#: Rows that merge "what" and "why" into one cell. Two contiguous runs, so two waves each
#: dropped the column rather than nine authors doing it independently. Listed rather than
#: rewritten because splitting somebody else's narrative into two cells is editing the
#: record, not fixing it — and listed rather than ignored because the "why" column is the
#: one CLAUDE.md's quality bar cares about. **This set may only SHRINK**: an id here that
#: has since grown its fourth column fails the check, which is what stops it becoming an
#: exemption file (the `UNWIRED_BASELINE` construction, D-48).
_MERGED_WHY_ROWS = frozenset(
    {"D-230", "D-231", "D-232", "D-233", "D-234", "D-235", "D-260", "D-261", "D-262"}
)
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

# Section 5's matching rule, and every character of it is a narrowing. Read
# `capability_drift()` for the argument; the shape is: an UPPER_SNAKE name, then a
# PRESENT-TENSE copula, then a boolean literal, with nothing between them but markdown
# punctuation. Adjacency is the whole design — proximity would report
# "`LEAD_RETRIEVAL_IMPLEMENTED` use — and it stays False" (whatsapp_cloud.py, where the
# "it" is a different constant) and a check that does that gets deleted within a month.
_VALUE_CLAIM = re.compile(
    r"(?P<name>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)"  # UPPER_SNAKE; one underscore minimum
    r"[`*]*\s*"  # a code span or bold run may close right after the name
    r"(?:"
    r"={1,2}"  # `NAME = False` — how the code writes it, so how docs quote it
    r"|is(?:\s+(?:now|still|currently|already))?"
    r"|stays|remains"
    r"|flips\s+to"
    r")"
    r"\s*[`*]*"
    r"(?P<value>True|False)"
    r"(?!\w)"
)
# The doc set's own way of saying "this sentence is withdrawn" — BUILD-LOG uses it for
# exactly that (§"`redact_trace_payload`", §"`inbound_webhooks` rows"). A retracted claim
# is not a claim, and a check that fired on the correct way to retract one would be
# pushing people to delete the record instead, which is the opposite of what this file
# is for.
#
# Bounded at a blank line, matching GFM: strikethrough is inline emphasis and cannot
# cross a paragraph. Without the bound, ONE stray `~~` and the next one four sections
# later would mask everything between them — a silent blind spot is a worse failure here
# than a missed retraction, because nothing announces it.
_STRUCK = re.compile(r"~~(?:[^\n]|\n(?!\s*\n))+?~~")


def _mask(match: re.Match[str]) -> str:
    """Blank a span in place, keeping newlines so every later line keeps its number."""
    return re.sub(r"[^\n]", " ", match.group())


@dataclass(frozen=True, slots=True)
class Claim:
    """A command a doc tells a human to run, and where it says so."""

    doc: str
    line: int
    command: str

    @property
    def where(self) -> str:
        return f"{self.doc}:{self.line}"


@dataclass(frozen=True, slots=True)
class ValueClaim:
    """A sentence that STATES a capability constant's value, and where it says so."""

    doc: str
    line: int
    name: str
    stated: bool
    sentence: str

    @property
    def where(self) -> str:
        return f"{self.doc}:{self.line}"


@dataclass(frozen=True, slots=True)
class ConstantFact:
    """A module-level boolean constant as the AST reads it — the side that cannot lie."""

    name: str
    module: str
    line: int
    value: bool

    @property
    def where(self) -> str:
        return f"{self.module}:{self.line}"


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


def _highest(ids: Iterable[str]) -> str | None:
    """The largest decision id BY NUMBER, or None for an empty log. `max()` on these
    strings is not it — see the comment in `dangling_decisions`, which is the message
    that read wrong.

    Returning None rather than a zeroth-decision sentinel is not fussiness: this file is
    itself scanned for citations, so a decision-shaped literal in the checker IS a
    dangling citation and the checker reported itself. The alternative — splicing the
    string so the pattern misses it — hides the literal from the guard instead of
    removing it, which is the move this whole file exists to catch. That also rules out
    NAMING the old sentinel in this docstring; prose that quotes the banned token trips
    the guard exactly as source does, which is how it was found.
    """
    return max(ids, key=lambda identifier: int(identifier.removeprefix("D-")), default=None)


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
    highest = _highest(known)
    # An empty log makes "the log runs to ..." a lie, so the hint is dropped rather than
    # filled with a placeholder — see `_highest` for why the placeholder was the bug.
    runs_to = f" (the log runs to {highest})" if highest else " (the log is empty)"
    failures: list[str] = []
    # `max(known)` was a STRING max, so a log running to D-148 reported itself as running
    # to "D-99" — `'9' > '1'`. The number in this message is the one a reader uses to pick
    # the next free decision id, so a wrong one sends them to a number already taken.
    for path in _citation_files(roots):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            for reference in sorted(set(_DECISION_REF.findall(line))):
                if reference not in known:
                    failures.append(
                        f"{_rel(path)}:{line_number} cites {reference}, which is not a row "
                        f"in {_rel(ROADMAP)} §6{runs_to}. Append the decision or fix the "
                        "reference."
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


def broken_decision_rows(roadmap: Path | None = None) -> list[str]:
    """Every row of the decision log is ONE line, so every row is a row.

    A markdown table row cannot span lines: a newline inside one silently ends the
    table, and everything after it renders as loose prose. The parser above cannot see
    that, because it finds rows by their leading `| D-nnn` — a broken row's tail lines
    do not start with a pipe, so they are simply invisible and the count still looks
    right. Two shapes of break were live when this landed, and neither was visible from
    a diff. **A blank line** — 27 of them, from D-31 onward, the first immediately after
    D-30 — so the log rendered as a 30-row table followed by 303 lines of literal
    `| D-nnn | ... |` text. **A newline inside a row**: D-433, whose own subject is a
    CRLF that bash misread, was written with LITERAL newlines inside its code spans
    while describing them, which split its row across three lines. Through all of it
    `dangling_decisions` and `duplicate_decision_ids` stayed green, because both count
    `| D-` line starts and there were still 333 of those.

    So this checks the shape the other two assume: from the first decision row to the
    last, every line starts a row and carries the table's four columns. Escape the
    newline (`\\r\\n`) rather than embedding it.
    """
    lines = (roadmap or ROADMAP).read_text(encoding="utf-8").splitlines()
    rows = [i for i, line in enumerate(lines) if _DECISION_ROW.match(line)]
    if not rows:
        return []
    failures: list[str] = []
    for index in range(rows[0], rows[-1] + 1):
        line = lines[index]
        match = _DECISION_ROW.match(line)
        if match is None:
            failures.append(
                f"{_rel(roadmap or ROADMAP)}:{index + 1} sits between decision rows and is "
                "not one — a row above it carries a literal newline, which ends the "
                "markdown table there. Escape the newline instead of embedding it."
            )
            continue
        identifier = match.group(1)
        columns = line.count("|") - 1
        if columns < _DECISION_COLUMNS and identifier not in _MERGED_WHY_ROWS:
            failures.append(
                f"{_rel(roadmap or ROADMAP)}:{index + 1} ({identifier}) has {columns} of the "
                f"decision log's {_DECISION_COLUMNS} columns — id, title, what, why. The "
                "fourth is where the rejected alternative goes."
            )
        elif columns >= _DECISION_COLUMNS and identifier in _MERGED_WHY_ROWS:
            failures.append(
                f"{identifier} has its fourth column now — drop it from `_MERGED_WHY_ROWS`. "
                "That set is the debt, and it may only shrink."
            )
    return failures


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

    A RULE NAMED BY A MODULE CONSTANT COUNTS AS EMITTED, and that is not a convenience.
    `legal.service.agreements_blocker` returns `(AGREEMENTS_RULE, AGREEMENTS_REASON)`
    because SEC-COMP §3, the readiness screen's copy table, the campaign gates and the
    dispatch gate must all cite ONE string — which is exactly the discipline §3 asks for
    — and reading only `ast.Constant` punished it: the better-written gate was the one
    this extractor could not see, so `legal/readiness.py`'s copy table looked like it
    explained a rule nothing emits. Module-level `NAME = "literal"` bindings in the same
    file are resolved; anything else still has to be a literal at the call site.
    """
    from apps.api.campaigns.service import LaunchBlocker
    from apps.api.compliance.service import DispatchDecision

    constructors = {LaunchBlocker.__name__, DispatchDecision.__name__}
    names: set[str] = set()
    for path in _python_files(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                called = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else getattr(function, "id", "")
                )
                if called in constructors:
                    if node.args:
                        names |= _as_rule_name(node.args[0], constants)
                    for keyword in node.keywords:
                        if keyword.arg == "rule":
                            names |= _as_rule_name(keyword.value, constants)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                names |= _pair_returns(node, constants)
    return names


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, including annotated ones.

    Top level only, deliberately: a name bound inside a function is not the shared
    vocabulary §3 is about, and following one would mean resolving scopes for a gain
    nothing in this tree needs.
    """
    bindings: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        bindings.update(
            {target.id: value.value for target in targets if isinstance(target, ast.Name)}
        )
    return bindings


def _as_rule_name(node: ast.expr, constants: dict[str, str]) -> set[str]:
    """One rule name from an expression that is a string literal or a module constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name) and node.id in constants:
        return {constants[node.id]}
    return set()


def _pair_returns(
    function: ast.FunctionDef | ast.AsyncFunctionDef, constants: dict[str, str] | None = None
) -> set[str]:
    """First elements of the `(rule, reason)` tuples a blocker predicate produces.

    Any function whose return annotation MENTIONS `tuple[str, str]` — `... | None` for a
    single blocker (`kyc_blocker`), `list[tuple[str, str]]` for the composed ones
    (`outbound_entity_blockers`, which appends its pairs into a list rather than returning
    each) — so every 2-element string-first tuple in the body is collected, not only the
    ones that are the direct value of a `return`. Without this the shared entity helper's
    `tm_registration_missing` would vanish from the emitted set the moment the campaign
    gate stopped constructing a `LaunchBlocker` for it inline.

    `constants` are the enclosing module's string bindings, so a pair built from a shared
    rule constant (`(AGREEMENTS_RULE, AGREEMENTS_REASON)`) resolves — see
    `emitted_rule_names`. Optional so the function still answers for a bare tuple literal
    when a caller has no module in hand.
    """
    if function.returns is None or "tuple[str, str]" not in ast.unparse(function.returns):
        return set()
    bindings = constants or {}
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Tuple) and len(node.elts) == 2:
            names |= _as_rule_name(node.elts[0], bindings)
    return names


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
    """The template wherever it lives, or None while it lives nowhere.

    HIDDEN DIRECTORIES ARE SKIPPED, AND THAT IS A BUG FIX, NOT TIDYING. This is the one
    place in this file that walks from the repository root rather than from a named root,
    and `sorted()` puts a dot-prefixed directory FIRST — so a leftover agent worktree under
    `.claude/worktrees/` shadowed `infra/nginx/`, and the gate reported a disagreement
    between the doc and a stale copy of the config while the real config agreed with it
    perfectly. The failure is the worst shape a gate can have: it fires, it names a file,
    and the file it names is not the one that ships. CI never saw it (those directories do
    not exist there), which is precisely why it could sit here.

    Locating by FILENAME is still right, for the reason above the constant — the doc names
    the file, not its home. What is excluded is only what is not the repository's own
    tree: dotted directories (`.claude`, `.git`, `.venv`) and vendored dependencies.
    """
    base = root or REPO_ROOT
    return next(
        (
            path
            for path in sorted(base.rglob(RATE_ZONE_TEMPLATE_NAME))
            if "node_modules" not in path.parts
            and not any(part.startswith(".") for part in path.relative_to(base).parts)
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


# --- 4d. the legal catalogue mirrors the web bundle -----------------------------------
#
# WHY THIS EXISTS. `apps/api/legal/catalogue.py` decides which published documents a
# client must accept and at which VERSION, and that version is written into an
# append-only ledger and compared by four outbound gates. It has to live on the Python
# side, because the comparison happens on a machine that never runs Node. The browser
# needs the same facts to show a reader which version of `/legal/<slug>` they are looking
# at, so `apps/web/src/lib/legal/versions.ts` carries a copy — and a copy nothing checks
# is a copy that is wrong the first time one side moves, which is the whole argument of
# 4b one directory over.
#
# WHAT IT COMPARES, AND WHAT IT CANNOT. Four things, all mechanical:
#
#   1. `PENDING_LEGAL_REVIEW` — the constant in `placeholders.ts` against the one in
#      `catalogue.py`. This is the load-bearing half TODAY: flipping it publishes eight
#      legal documents and invalidates every acceptance in the ledger, and flipping it on
#      one side only would leave the server demanding `1+pre-review` while the page shows
#      `1`.
#   2. The SLUG SET, three ways: the document modules' own `slug:` fields, the mirror's
#      keys, and the catalogue's. A ninth document that nobody told the API about would
#      otherwise be published, linked and unacceptable.
#   3. Per document: `title` (which is the bundle's `shortTitle`), `blocking`, the
#      revision list with each revision's `material` flag, and `effectiveDate`.
#   4. Nothing else, because nothing else is decidable from here.
#
# ⚠ IT COMPARES IDENTITY, NOT TEXT, AND THE GAP IS REAL. Nothing in this tree can read
# the PROSE of a TypeScript module from Python without a TS parser, so a lawyer editing a
# clause in `terms.ts` without appending a revision produces an acceptance row naming a
# version whose words have changed, and no check here sees it. Said plainly rather than
# implied by omission: the discipline that closes it is written at the top of both
# `REVISIONS` blocks and is human. Approximating it — hashing the file, say — would fire
# on a comment change and be switched off within a week, which is the failure mode this
# whole module is written to avoid (see "WHAT THIS DELIBERATELY DOES NOT DO").

LEGAL_BUNDLE = REPO_ROOT / "apps" / "web" / "src" / "lib" / "legal"

#: `export const PENDING_LEGAL_REVIEW = true;`
_TS_PENDING_REVIEW = re.compile(r"export\s+const\s+PENDING_LEGAL_REVIEW\s*=\s*(true|false)")
#: `slug: "acceptable-use",` — one per document module.
_TS_SLUG = re.compile(r'^\s*slug:\s*"([^"]+)"', re.MULTILINE)
#: `shortTitle: "Acceptable Use",`
_TS_SHORT_TITLE = re.compile(r'^\s*shortTitle:\s*"([^"]+)"', re.MULTILINE)


def web_pending_legal_review() -> bool | None:
    """`PENDING_LEGAL_REVIEW` as the web bundle declares it, or None if it is unreadable.

    None rather than a default: "the constant is not there any more" is a finding, not a
    reason to assume one of its two values.
    """
    source = (LEGAL_BUNDLE / "placeholders.ts").read_text(encoding="utf-8")
    match = _TS_PENDING_REVIEW.search(source)
    return None if match is None else match.group(1) == "true"


def web_legal_documents() -> dict[str, str]:
    """`slug -> shortTitle` for every document module in the bundle.

    Read from the modules themselves rather than from `index.ts`, because the modules are
    where a ninth document's slug is actually born. A module with a `slug` and no
    `shortTitle` (or the reverse) is reported by the comparison as a missing entry rather
    than crashing here.
    """
    found: dict[str, str] = {}
    for path in sorted(LEGAL_BUNDLE.glob("*.ts")):
        if path.name in ("index.ts", "types.ts", "placeholders.ts", "versions.ts"):
            continue
        source = path.read_text(encoding="utf-8")
        slugs, titles = _TS_SLUG.findall(source), _TS_SHORT_TITLE.findall(source)
        if slugs and titles:
            found[slugs[0]] = titles[0]
    return found


def web_legal_versions() -> dict[str, dict[str, object]]:
    """The mirror in `versions.ts`, parsed into the shape `catalogue.DOCUMENTS` has.

    A block-at-a-time parse rather than a JSON round trip: the file is TypeScript with
    comments, and shelling out to Node inside a Python guardrail would make this the one
    check that cannot run without the frontend toolchain installed.
    """
    source = (LEGAL_BUNDLE / "versions.ts").read_text(encoding="utf-8")
    body = source.split("LEGAL_VERSIONS", 1)[-1]
    entries: dict[str, dict[str, object]] = {}
    for block in re.finditer(
        r'^  "?([a-z0-9-]+)"?:\s*\{(.*?)^  \},', body, re.MULTILINE | re.DOTALL
    ):
        slug, fields = block.group(1), block.group(2)
        title = re.search(r'title:\s*"([^"]*)"', fields)
        blocking = re.search(r"blocking:\s*(true|false)", fields)
        effective = re.search(r'effectiveDate:\s*(?:null|"([^"]*)")', fields)
        entries[slug] = {
            "title": title.group(1) if title else None,
            "blocking": blocking.group(1) == "true" if blocking else None,
            "revisions": [
                (rev.group(1), rev.group(2) == "true")
                for rev in re.finditer(
                    r'\{\s*revision:\s*"([^"]+)",\s*material:\s*(true|false)\s*\}', fields
                )
            ],
            "effective_date": effective.group(1) if effective and effective.group(1) else None,
        }
    return entries


def legal_catalogue_drift() -> list[str]:
    """The API's legal catalogue against the web bundle. Every direction that can differ."""
    from apps.api.legal import catalogue

    failures: list[str] = []

    declared = web_pending_legal_review()
    if declared is None:
        failures.append(
            "apps/web/src/lib/legal/placeholders.ts no longer exports "
            "`PENDING_LEGAL_REVIEW`, and `apps/api/legal/catalogue.py` mirrors it. The "
            "constant is what decides whether an acceptance is provisional"
        )
    elif declared != catalogue.PENDING_LEGAL_REVIEW:
        failures.append(
            f"PENDING_LEGAL_REVIEW: the web bundle says {declared}, "
            f"`apps/api/legal/catalogue.py` says {catalogue.PENDING_LEGAL_REVIEW}. Flipping "
            "it changes every document's version and re-demands every acceptance, so both "
            "sides move in one change"
        )

    published = web_legal_documents()
    mirror = web_legal_versions()
    api = {doc.slug: doc for doc in catalogue.DOCUMENTS}

    failures += [
        f"`/legal/{slug}` is published by the web bundle and "
        f"`apps/api/legal/catalogue.py` does not list it — it is linkable and cannot be "
        "accepted or versioned"
        for slug in sorted(set(published) - set(api))
    ]
    failures += [
        f"`apps/api/legal/catalogue.py` lists `{slug}` and the web bundle publishes no "
        "such document — a client would be asked to accept a page that 404s"
        for slug in sorted(set(api) - set(published))
    ]
    failures += [
        f"`{slug}` is in `apps/api/legal/catalogue.py` and not in "
        "apps/web/src/lib/legal/versions.ts, so the page can show no version"
        for slug in sorted(set(api) - set(mirror))
    ]
    failures += [
        f"apps/web/src/lib/legal/versions.ts carries `{slug}`, which "
        "`apps/api/legal/catalogue.py` does not know"
        for slug in sorted(set(mirror) - set(api))
    ]

    for slug in sorted(set(api) & set(mirror)):
        spec, copy = api[slug], mirror[slug]
        if copy["title"] != spec.title:
            failures.append(
                f"`{slug}`: versions.ts titles it {copy['title']!r}, the catalogue {spec.title!r}"
            )
        if slug in published and published[slug] != spec.title:
            failures.append(
                f"`{slug}`: the document module's shortTitle is {published[slug]!r}, the "
                f"catalogue's title is {spec.title!r} — one document, one name"
            )
        if copy["blocking"] != spec.blocking:
            failures.append(
                f"`{slug}`: versions.ts says blocking={copy['blocking']}, the catalogue "
                f"says {spec.blocking}. That decides whether an unaccepted copy stops the "
                "account dialling"
            )
        if copy["effective_date"] != spec.effective_date:
            failures.append(
                f"`{slug}`: versions.ts dates it {copy['effective_date']!r}, the catalogue "
                f"{spec.effective_date!r}"
            )
        expected = [(rev.revision, rev.material) for rev in spec.revisions]
        if copy["revisions"] != expected:
            failures.append(
                f"`{slug}`: versions.ts has revisions {copy['revisions']}, the catalogue "
                f"has {expected}. The last entry decides the CURRENT version, and every "
                "`material` flag decides whether a stored acceptance still counts"
            )
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


# --- 4b. the TTS rate card mirrors the rate card the code bills on ---------------
#
# WHY THIS SECTION EXISTS. Section 4 above is about NGINX rate LIMIT zones — `limit_req_
# zone`, requests per second. Nothing in this file, and nothing anywhere in the tree,
# checked a MONEY rate against the doc that states it, which is where the drift class
# D-102/D-103/D-105 found is most expensive: TRD §10.1 is the cost model the margin is
# reasoned from, `billing/rates.py::TTS_INR_PER_10K_CHARS` is what a client is actually
# billed against, and until now a vendor price move could land in one and not the other
# with nothing able to notice. D-105 is the precedent that makes it concrete — a Sarvam
# identifier moved under us and the cost model went on pricing the model we had stopped
# calling.
#
# THE DOC STATES THE SAME RATE TWICE, and both spellings are checked. §10.1's Sarvam card
# quotes the vendor's own unit ("₹30 / 10,000 chars"); the per-call-minute table below it
# re-expresses the same rate per 1,000 ("₹3.00 / 1,000 chars"). A doc that disagrees with
# ITSELF about a price is the cheapest possible version of this failure and the one most
# likely to survive review, because each table reads fine alone.
#
# EVIDENCE LADDER (billing/payments.py's three rungs). The rates themselves are REPORTED,
# NOT READ: `sarvam.ai` and `docs.sarvam.ai` are refused by this environment's egress
# proxy, so the ₹30 / ₹15 figures are TRD §10.1's record of a live read on 11 Aug 2026
# (D-35), corroborated Aug 2026 by two independent search summaries of the same pricing
# page ("₹15-30 per 10,000 characters"; "₹30 per 10,000 characters"). What this check
# proves is narrower and still worth having: that the doc and the code say ONE thing, so
# the next correction has one place to land.

#: Which doc carries the money rate card, and the heading its Sarvam table sits under.
TRD = REPO_ROOT / "docs" / "TRD.md"
TTS_RATE_HEADING = "### 10.1 Stack cost, computed from published rates"

#: `| Text-to-Speech **Bulbul v3** | ₹30 / 10,000 chars |` — the vendor's own unit.
#: ONLY v3 matches: the single-tier voice decision withdrew the v2 "value" rung, so a
#: lingering `Bulbul v2` row in the doc is drift the check should NOT accidentally
#: reconcile against a code rate that no longer exists.
_DOC_TTS_10K = re.compile(
    r"\|[^|\n]*Bulbul\s*\*{0,2}(v3)\*{0,2}[^|\n]*\|[^|\n]*?₹\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*/\s*10,?000\s*chars",
    re.IGNORECASE,
)
#: `| TTS — Bulbul **v3** | ₹3.00 / 1,000 chars | ... |` — the same rate, per 1,000.
_DOC_TTS_1K = re.compile(
    r"\|[^|\n]*Bulbul\s*\*{0,2}(v3)\*{0,2}[^|\n]*\|[^|\n]*?₹\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*/\s*1,?000\s*chars",
    re.IGNORECASE,
)

#: Which code key each doc row is a claim about. There is ONE voice quality (the
#: single-tier voice decision) — the doc names the VENDOR's product (Bulbul v3) and the
#: code holds one scalar rate — so the mapping is a single entry, stated once here rather
#: than assumed by either side.
TTS_DOC_ROW_TO_TIER: dict[str, str] = {"v3": "bulbul-v3"}


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def doc_tts_rates(text: str | None = None) -> dict[str, Decimal]:
    """TRD §10.1's TTS rate card as `{tier: INR per 10,000 chars}`.

    Both doc spellings are read and reconciled: a per-1,000 figure is multiplied by ten,
    and a row that appears in both tables at rates that do not reconcile yields the
    per-10,000 figure PLUS a disagreement reported by `tts_rate_card_drift`. Returning
    the union rather than one table means the check cannot be satisfied by deleting the
    table it happens to read.
    """
    document = text if text is not None else TRD.read_text(encoding="utf-8")
    body = _section(document, TTS_RATE_HEADING, "\n### ")
    if body is None:
        return {}
    rates: dict[str, Decimal] = {}
    for version, amount in _DOC_TTS_10K.findall(body):
        rates[TTS_DOC_ROW_TO_TIER[version.lower()]] = _decimal(amount)
    for version, amount in _DOC_TTS_1K.findall(body):
        rates.setdefault(TTS_DOC_ROW_TO_TIER[version.lower()], _decimal(amount) * 10)
    return rates


def doc_tts_rate_disagreements(text: str | None = None) -> list[str]:
    """Where §10.1's two tables price the same rung differently."""
    document = text if text is not None else TRD.read_text(encoding="utf-8")
    body = _section(document, TTS_RATE_HEADING, "\n### ")
    if body is None:
        return []
    per_10k = {v.lower(): _decimal(a) for v, a in _DOC_TTS_10K.findall(body)}
    per_1k = {v.lower(): _decimal(a) * 10 for v, a in _DOC_TTS_1K.findall(body)}
    return [
        f"{_rel(TRD)} §10.1 prices Bulbul {version} at ₹{per_10k[version]}/10,000 chars in "
        f"the Sarvam card and ₹{per_1k[version] / 10}/1,000 chars (= ₹{per_1k[version]}"
        "/10,000) in the per-call-minute table — the same rate, stated twice, disagreeing"
        for version in sorted(set(per_10k) & set(per_1k))
        if per_10k[version] != per_1k[version]
    ]


def code_tts_rates() -> dict[str, Decimal]:
    """`billing/rates.py::TTS_INR_PER_10K_CHARS` — what a client is billed against.

    Imported rather than parsed, for the reason `conf_rate_zones` parses the DIRECTIVE
    rather than the comment beside it: the value the code holds at runtime is the thing a
    tenant's bill is computed from, and a source scan could be satisfied by a literal the
    module never uses.

    ONE ENTRY now — the constant is a single scalar since the single-tier voice decision
    (it was a `Mapping[TtsTier, Decimal]`), keyed to the one doc row it must agree with.
    """
    from apps.api.billing.rates import TTS_INR_PER_10K_CHARS

    return {"bulbul-v3": TTS_INR_PER_10K_CHARS}


def tts_rate_card_drift(text: str | None = None) -> list[str]:
    """TRD §10.1's rate card against the rate card the biller uses. Both directions.

    A tier in one and not the other is drift, and so is a tier in both at different
    rupees — the second is the one that reads as fine in review, because the rungs all
    line up and only the number moved.
    """
    declared = doc_tts_rates(text)
    billed = code_tts_rates()
    failures = list(doc_tts_rate_disagreements(text))
    failures += [
        f"{_rel(TRD)} §10.1 prices the {tier} TTS rung at ₹{rate}/10,000 chars, and "
        "`billing/rates.py::TTS_INR_PER_10K_CHARS` has no such rung"
        for tier, rate in sorted(declared.items())
        if tier not in billed
    ]
    failures += [
        f"`billing/rates.py::TTS_INR_PER_10K_CHARS` bills the {tier} rung at ₹{rate}/10,000 "
        f"chars, and {_rel(TRD)} §10.1's rate card does not state it"
        for tier, rate in sorted(billed.items())
        if tier not in declared
    ]
    failures += [
        f"the {tier} TTS rung: {_rel(TRD)} §10.1 says ₹{declared[tier]}/10,000 chars, "
        f"`billing/rates.py` bills ₹{billed[tier]}. A client is billed the code"
        for tier in sorted(set(declared) & set(billed))
        if declared[tier] != billed[tier]
    ]
    return failures


# --- 4d. the STT rate card, the other half of the speech leg ---------------------------
#
# WHY THIS EXISTS SEPARATELY FROM 4b. Same defect, second leg, different UNIT — and the
# unit is the whole reason it was missed. TTS is billed per CHARACTER and had a code home
# (`TTS_INR_PER_10K_CHARS`) and a check the day the rate card was written; STT is billed
# per unit of AUDIO TIME and had NEITHER until now. The ₹30/hour figure lived in §10.1
# prose and, blended with four other legs, inside `SELF_SERVE_COST_FLOOR_INR_PER_MIN` —
# a money figure with no code home and nothing able to notice a vendor move, which is
# D-103/D-105 exactly.
#
# BOTH SPELLINGS, AND THEY ARE CHECKED AGAINST EACH OTHER TOO, for 4b's reason: §10.1's
# Sarvam card quotes the vendor's own unit ("₹30 / hour") and the per-call-minute table
# below it re-expresses the same rate as "₹0.50". A doc that disagrees with ITSELF about a
# price is the cheapest version of this failure and the likeliest to survive review,
# because each table reads fine alone.
#
# THE DIARIZATION ROW IS EXCLUDED, DELIBERATELY AND BY NAME. §10.1 prices STT with
# diarization at ₹45/hour, and it is a real vendor rate — but nothing in this repository
# enables diarization, so there is no code constant for it and there must not be one
# (`billing/rates.py` states why). Reconciling that row against `STT_INR_PER_HOUR` would
# report drift on a document that is right; silently letting a bare `₹.../hour` regex
# swallow it would be worse, because it would then be the row that has to stay ₹30 for the
# check to pass. So the exclusion is a named predicate rather than a regex accident.
#
# EVIDENCE LADDER. Unlike 4b's rates, this one is **VENDOR-PUBLISHED**: the Sarvam
# dashboard Model Catalogue prices `saaras:v3` and `saaras:v4` at ₹30/hour of audio (and
# ₹45/hour with diarization), read by the founder on 27 Aug 2026 and relayed. This
# container still cannot fetch Sarvam (`docs.sarvam.ai`, `www.sarvam.ai` → 403 on CONNECT,
# re-measured the same day), so what THIS check proves is the narrower thing it can: that
# the doc and the code state ONE rate, so the next correction has one place to land.

#: `| Speech-to-Text **and Translate** (Saaras) | ₹30 / hour |` and the per-call-minute
#: table's `| STT — Saaras (STT+Translate) | ₹30/hr | **₹0.50** |` — every ₹/hour spelling
#: of the STT rate, in whichever table it appears.
_DOC_STT_PER_HOUR = re.compile(
    r"₹\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*/\s*(?:hour|hr)\b",
    re.IGNORECASE,
)
#: The third cell of `| STT — … | ₹30/hr | **₹0.50** |`: the per-call-minute figure. Read
#: from the CELL rather than by matching "₹0.50" anywhere on the line, so the rate column
#: beside it cannot be mistaken for it.
_DOC_STT_PER_MINUTE = re.compile(
    r"^\|[^|\n]*\|[^|\n]*\|[^|\n]*?₹\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
)


def _is_stt_row(line: str) -> bool:
    """A §10.1 table row pricing the STT leg we actually run.

    Diarization is excluded by name: it is a different rate for a feature this repository
    does not enable (`billing/rates.py::STT_INR_PER_HOUR`), so it is not a claim about
    `STT_INR_PER_HOUR` and must not be reconciled against it.
    """
    if not line.startswith("|") or "diariz" in line.lower():
        return False
    return "speech-to-text" in line.lower() or line.lower().startswith("| stt")


def doc_stt_rates_per_hour(text: str | None = None) -> list[Decimal]:
    """Every ₹/hour STT figure §10.1 states, in document order.

    A LIST, not a set, and not a single value: §10.1 states the rate on three separate
    rows (plain STT, Saaras, and the rate column of the per-call-minute table), and a
    vendor move that lands on two of them is exactly the half-applied edit this is for.
    """
    document = text if text is not None else TRD.read_text(encoding="utf-8")
    body = _section(document, TTS_RATE_HEADING, "\n### ")
    if body is None:
        return []
    return [
        _decimal(amount)
        for line in body.splitlines()
        if _is_stt_row(line)
        for amount in _DOC_STT_PER_HOUR.findall(line)
    ]


def doc_stt_rates_per_minute(text: str | None = None) -> list[Decimal]:
    """Every per-call-minute STT figure §10.1 states, in document order."""
    document = text if text is not None else TRD.read_text(encoding="utf-8")
    body = _section(document, TTS_RATE_HEADING, "\n### ")
    if body is None:
        return []
    return [
        _decimal(amount)
        for line in body.splitlines()
        if _is_stt_row(line)
        for amount in _DOC_STT_PER_MINUTE.findall(line)
    ]


def stt_rate_card_drift(text: str | None = None) -> list[str]:
    """TRD §10.1's STT rate against `billing/rates.py::STT_INR_PER_HOUR`. Both directions,
    both spellings, and the two spellings against each other.

    AN EMPTY READING IS A FAILURE, not a pass — `llm_cost_curve_drift`'s argument. A guard
    that cannot find its subject has not verified it, and the way this check dies quietly
    is a table reword that leaves the money unguarded while the gate still prints OK.
    """
    from apps.api.billing.rates import STT_INR_PER_HOUR, stt_rate_inr_per_minute

    per_hour = doc_stt_rates_per_hour(text)
    per_minute = doc_stt_rates_per_minute(text)
    if not per_hour:
        return [
            f"{_rel(TRD)} §10.1 states no `₹N / hour` STT rate at all. The STT leg is a "
            "third of the per-minute cost model and `billing/rates.py::STT_INR_PER_HOUR` "
            "is priced against that row; restore it or delete this check deliberately."
        ]
    if not per_minute:
        return [
            f"{_rel(TRD)} §10.1's per-call-minute table states no STT figure. It is the "
            "spelling the ₹/hour rate is consumed in and the one a founder reads; restore "
            "it or delete this check deliberately."
        ]
    failures = [
        f"{_rel(TRD)} §10.1 prices the STT leg at ₹{rate}/hour on one row and "
        f"₹{per_hour[0]}/hour on another — the same rate, stated twice, disagreeing"
        for rate in per_hour[1:]
        if rate != per_hour[0]
    ]
    failures += [
        f"{_rel(TRD)} §10.1 quotes the STT leg at ₹{rate}/call-minute, and its own "
        f"₹{per_hour[0]}/hour rate is ₹{per_hour[0] / 60}/minute — the same rate, stated "
        "in two units, disagreeing"
        for rate in per_minute
        if rate != _at_doc_precision(per_hour[0] / 60, rate)
    ]
    failures += [
        f"{_rel(TRD)} §10.1 prices the STT leg at ₹{per_hour[0]}/hour and "
        f"`billing/rates.py::STT_INR_PER_HOUR` holds ₹{STT_INR_PER_HOUR}. The cost model "
        "and the code are one number"
    ] * (per_hour[0] != STT_INR_PER_HOUR)
    failures += [
        f"{_rel(TRD)} §10.1 quotes ₹{rate}/call-minute and "
        f"`billing/rates.py::stt_rate_inr_per_minute()` computes "
        f"₹{_at_doc_precision(stt_rate_inr_per_minute(), rate)}"
        for rate in per_minute
        if rate != _at_doc_precision(stt_rate_inr_per_minute(), rate)
    ]
    return failures


# --- 4c. the LLM per-minute figures mirror the function that computes them -------------
#
# WHY THIS EXISTS SEPARATELY FROM 4b. That one guards a rate the biller charges; this one
# guards a rate nothing charges yet — the in-call LLM leg, which D-36 priced at ₹0.00
# because Sarvam 105B is free per token and which D-400 moved to a paid account. A number
# nobody bills against is exactly the number that rots, and this one is load bearing
# anyway: TRD §10 is where the founder reasons about margin, and the LLM leg went from
# "free, ignore it" to a leg that costs more per minute the longer a call runs.
#
# THE FIGURE IS A CURVE, NOT A RATE, which is why the doc states three points and why the
# check reads all of them. §6.1 resends the whole conversation every turn, so input tokens
# grow through a call and total input cost is quadratic in duration — one "₹x/min" would
# be a blended average that a long call skews above. `llm_cost_inr_per_minute` is the one
# computation; the doc quotes it at 1, 5 and 10 minutes; this proves the quotes are still
# what the function returns.
#
# AND THERE IS ONE CURVE PER SELECTABLE MODEL — FIVE SINCE THE CATALOGUE OPENED TO THREE
# LEGS, TWO BEFORE. A client picks their own model per agent (D-454) and the spread across
# the offered set is now nearly 8x per minute at five minutes, so §10.1 publishes a row for
# each and this check scores each row against
# `llm_cost_inr_per_minute(minutes, model=<that row's model>)`. THE CONTRACT WITH THE DOC IS
# ONE LINE: a `| LLM …` row must contain the model's exact identifier, because that
# identifier is how this check knows which price the row's figures are supposed to be. Every
# model in `SELECTABLE_LLM_MODELS` must have such a row — a missing one is reported, not
# skipped, for the reason `llm_cost_curve_drift` gives.
#
# ⚠ **SCORED AGAINST THE CATALOGUE REFERENCE, NOT AGAINST AN ATTESTED PRICE**, and that is
# why `llm_cost_inr_per_minute` keeps reading `llm_reference_inr_per_ktok`. §10 is the MARGIN
# MODEL — the same number on a laptop, in CI and on a founder's screen. An attestation is
# per-deployment and absent in CI, so a doc gate stated over one would be unrunnable
# anywhere the ops console had not been filled in, and TRD's published economics would move
# whenever an operator typed. What a minute costs THIS account is `llm_inr_per_ktok`; the
# known gap between the two is the +10% Azure Regional Standard premium named in
# `billing/rates.py`.
#
# ⚠ **STATED OVER `SELECTABLE_LLM_MODELS`, NOT `AZURE_OPENAI_MODELS`, AND NOT OVER THE
# OFFERABLE SET.** The Azure spelling was this scoring's subject while Azure was the only
# leg; the offerable set would be wrong in the other direction, because it depends on a
# credential and an attestation that no CI run has — so a doc row would silently stop being
# scored on the machine where the check matters most.

#: `| LLM — **gpt-4o-mini** | … | **₹0.10 (1 min) / ₹0.16 (5 min) / ₹0.24 (10 min)** |` —
#: every `₹X (N min)` pair in one §10.1 LLM row.
_DOC_LLM_PER_MINUTE = re.compile(
    r"₹\s*([0-9]+(?:\.[0-9]+)?)\s*\((\d+)\s*min\)",
)


def doc_llm_per_minute(text: str | None = None, *, model: str | None = None) -> dict[int, Decimal]:
    """TRD §10.1's in-call LLM cost curve for one model, as `{minutes: INR per minute}`.

    Read from the row that NAMES `model`, defaulting to the shipped default
    (`AZURE_OPENAI_DEFAULT_MODEL`). The default is about which ROW to read and not about
    which price to apply — `llm_cost_inr_per_minute` takes no such default, deliberately
    (`billing/rates.py`) — and it is what lets the one-line summary at the bottom of this
    script quote a figure without choosing a model for the reader.

    The Sarvam row beside these is a superseded default and is not what
    `llm_cost_inr_per_minute` computes; scoring it would report a disagreement that is the
    table working as intended.

    ⚠ **THE IDENTIFIER IS MATCHED IN BACKTICKS, NOT AS A BARE SUBSTRING, AND THAT IS A BUG
    FIX RATHER THAN A TIGHTENING.** A bare `wanted in line` was correct for exactly as long
    as no model identifier was a PREFIX of another: it silently scored `gemini-2.5-flash`
    against the `gemini-2.5-flash-lite` row — whichever came first in the table — and
    reported drift of 3x on a document that was right. The same collision is waiting in
    `gpt-4.1` / `gpt-4.1-mini` and `gpt-5.4` / `gpt-5.4-mini`, so the fix is the general one
    and not a re-ordering of the rows. Every §10.1 LLM row already spells its identifier in
    backticks, so the contract with the doc is unchanged in practice and is now stated
    precisely: **a `| LLM …` row must contain its model identifier in backticks.**
    """
    from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL

    wanted = f"`{model or AZURE_OPENAI_DEFAULT_MODEL}`"
    document = text if text is not None else TRD.read_text(encoding="utf-8")
    body = _section(document, TTS_RATE_HEADING, "\n### ")
    if body is None:
        return {}
    row = next(
        (line for line in body.splitlines() if line.startswith("| LLM") and wanted in line),
        None,
    )
    if row is None:
        return {}
    return {int(minutes): _decimal(amount) for amount, minutes in _DOC_LLM_PER_MINUTE.findall(row)}


def doc_llm_cost_points(text: str | None = None) -> dict[str, dict[int, Decimal]]:
    """Every §10.1 LLM row, keyed by the model it names — exactly what
    `llm_cost_curve_drift` scores, so the summary line at the bottom of this script counts
    the same points the check verified rather than one model's worth of them."""
    from calevate_shared.engine import SELECTABLE_LLM_MODELS

    return {model: doc_llm_per_minute(text, model=model) for model in sorted(SELECTABLE_LLM_MODELS)}


def _at_doc_precision(computed: Decimal, quoted: Decimal) -> Decimal:
    """`computed` rounded to however many decimals the doc chose to print.

    THE DOC IS ALLOWED TO ROUND AND THE LEDGER IS NOT. `llm_cost_inr_per_minute` returns
    NUMERIC(12,4) because that is what `unit_cost_paid` stores; §10 prints paise because
    a margin table is read by a person. Comparing them raw reports ₹0.2310 against ₹0.23
    as drift, which trains the next reader to print four decimals in a prose table to
    quiet a check — the exact failure mode `tests/money_rounding_mode_test.py` exists to
    prevent on the other side. ROUND_HALF_UP for that test's reason: it is the convention
    an Indian tax invoice is checked against, and the rest of this repo passes it
    explicitly rather than inheriting the ambient decimal context.
    """
    return computed.quantize(quoted, rounding=ROUND_HALF_UP)


def llm_cost_curve_drift(text: str | None = None) -> list[str]:
    """§10.1's quoted points, per model, against `billing/rates.py::llm_cost_inr_per_minute`.

    An EMPTY reading is a failure, not a pass — for EVERY model, not just the default.
    These rows are the only place the cost of the LLM decision is stated in the document a
    founder reasons about margin from, and a check that silently passed when a row was
    reworded would be worse than no check — it is the
    `check_redaction_exposure.check_allowlist` argument: a guard that cannot find its
    subject has not verified it. A missing row for the NON-default model is the likelier
    half of that failure and the more expensive one: `gpt-4.1-mini` is one console edit
    away and costs 2.7x, so a margin table that quotes only the cheap model is a table
    that is wrong the moment the switch is flipped.
    """
    from apps.api.billing.rates import llm_cost_inr_per_minute

    offenders: list[str] = []
    for model, quoted in doc_llm_cost_points(text).items():
        if not quoted:
            offenders.append(
                f"{_rel(TRD)} §10.1 carries no `| LLM …` row naming `{model}` and quoting "
                "`₹X (N min)` points. Every model this platform can be switched to has a "
                "cost curve the margin turns on; restore the row (it must contain the "
                "model identifier in backticks) or delete this check deliberately."
            )
            continue
        computed = {
            minutes: _at_doc_precision(llm_cost_inr_per_minute(minutes, model=model), amount)
            for minutes, amount in quoted.items()
        }
        offenders.extend(
            f"{_rel(TRD)} §10.1 quotes `{model}` at ₹{amount}/min on a {minutes}-minute "
            f"call; `billing/rates.py::llm_cost_inr_per_minute({minutes}, model='{model}')` "
            f"computes ₹{computed[minutes]}. The function is the cost model"
            for minutes, amount in sorted(quoted.items())
            if computed[minutes] != amount
        )
    return offenders


# --- 5. prose that quotes a capability constant's value quotes the right one ----


def _boolean_definitions(roots: Iterable[Path] | None = None) -> dict[str, list[ConstantFact]]:
    """`{name: every module-level boolean definition of it}` — the raw reading."""
    definitions: dict[str, list[ConstantFact]] = {}
    for path, _, tree in _python_sources(roots):
        module = _rel(path)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets: list[ast.expr] = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, bool):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    definitions.setdefault(target.id, []).append(
                        ConstantFact(target.id, module, node.lineno, bool(value.value))
                    )
    return definitions


def capability_constants(roots: Iterable[Path] | None = None) -> dict[str, ConstantFact]:
    """Every module-level `NAME = <bool literal>` in the repo's Python, by name.

    Discovered, never listed. A hand-written registry of "the capability constants" would
    be the exemption list this file refuses everywhere else: the fifth one
    (`rates.ENGINE_REPORTS_TTS_MODEL`) was not in the audit's list of four and is checked
    anyway because the AST found it, and the sixth will be checked the day it is written.
    The selection rule is mechanical rather than semantic — UPPER_SNAKE, module level,
    literal `True`/`False` — which on today's tree selects exactly the honesty device and
    nothing else, because a boolean somebody wanted to CHANGE at runtime would be config
    or a feature flag (D-78), not a `Final` in a module.

    A name defined twice with disagreeing values is not returned: `capability_ambiguities`
    reports it through `blind_spots()` instead, because a doc quoting an ambiguous name
    cannot be judged and picking one definition silently would be inventing the answer.
    """
    return {
        name: facts[-1]
        for name, facts in _boolean_definitions(roots).items()
        if len({fact.value for fact in facts}) == 1
    }


def capability_ambiguities(roots: Iterable[Path] | None = None) -> list[str]:
    """Names two modules define as different booleans. Reported, never resolved."""
    return [
        f"`{name}` is defined as a module-level boolean in more than one place with "
        f"disagreeing values ({', '.join(fact.where for fact in facts)}). No sentence "
        "quoting that name can be judged, so section 5 is blind to it until one of them "
        "is renamed."
        for name, facts in sorted(_boolean_definitions(roots).items())
        if len({fact.value for fact in facts}) > 1
    ]


def module_level_names(roots: Iterable[Path] | None = None) -> set[str]:
    """Every UPPER_SNAKE name ASSIGNED at module level in the repo's Python, any value.

    Wider than `capability_constants()` on purpose, and used only to answer "does the tree
    still define this name". `PAYMENT_PROVIDER` is not a boolean, so a doc quoting a value
    for it would be nonsense — but it is not the RENAME the second half of
    `capability_drift()` is looking for, and reporting it would be a guess about intent.

    Assignments only: `from ... import PROVIDER_CREATES_ORDERS` is deliberately NOT a
    spelling of the name. Measured, because the first run of the rename negative control
    stayed green on it — a half-finished rename leaves exactly that stale import behind
    (in `payments_provider_seam_test.py`, here), and counting it would let the import
    shield every doc sentence quoting the old name from ever being compared again. Costs
    nothing on today's tree: dropping imports adds zero findings.
    """
    names: set[str] = set()
    for _, _, tree in _python_sources(roots):
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return {name for name in names if name.isupper()}


def _capability_python(roots: Iterable[Path] | None = None) -> Iterator[Path]:
    for root in CAPABILITY_ROOTS if roots is None else roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


@cache
def _default_python_sources() -> tuple[tuple[Path, str, ast.Module], ...]:
    """Every Python file section 5 reads, parsed ONCE.

    Section 5 asks four questions of the same syntax trees (what booleans are defined,
    what UPPER names exist at all, what the docstrings say, whether two modules disagree),
    and `blind_spots()` asks two of them again before `main()` prints the OK line. Parsing
    ~400 files six times cost more than every other section of this check combined.

    Safe to memoise because this is a one-shot process: it parses, reports and exits.
    Callers that mutate a tree between calls — the negative controls — pass explicit
    `roots`, which never touches this cache; `cache_clear()` is there for anything that
    ever needs to.
    """
    return tuple(_parse_python(path) for path in _capability_python())


def _parse_python(path: Path) -> tuple[Path, str, ast.Module]:
    source = path.read_text(encoding="utf-8")
    return path, source, ast.parse(source, filename=str(path))


def _python_sources(
    roots: Iterable[Path] | None = None,
) -> tuple[tuple[Path, str, ast.Module], ...]:
    if roots is None:
        return _default_python_sources()
    return tuple(_parse_python(path) for path in _capability_python(roots))


def _python_prose(text: str, tree: ast.Module) -> Iterator[tuple[int, str]]:
    """`(first line, text)` for each docstring and each run of `#` comments.

    Prose only. The definition line, the `assert X is True` in a test and the
    `capability = X and credentials()` in a service are CODE — they are the thing being
    described, they cannot drift from themselves, and judging them would make the
    offender message ("a doc states…") a lie about half its hits.

    Runs of consecutive comment lines are joined, and each line's `#` marker is stripped,
    so a claim wrapping across two of them reads as the one sentence it is. Without the
    stripping the marker sits between the name and its value and defeats the adjacency
    rule — the matcher would go blind at exactly the 100-column margin where a long
    comment wraps, which is where this repo's comments live.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            yield first.value.lineno, first.value.value
    run: list[str] = []
    start = 0
    previous = -2
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type != tokenize.COMMENT:
            continue
        if token.start[0] != previous + 1:
            if run:
                yield start, "\n".join(run)
            run, start = [], token.start[0]
        run.append(token.string.lstrip("#"))
        previous = token.start[0]
    if run:
        yield start, "\n".join(run)


def prose_blocks(
    docs: Iterable[Path] | None = None,
    roots: Iterable[Path] | None = None,
    web: Path | None = None,
) -> Iterator[tuple[str, int, str]]:
    """`(file, first line, text)` for everywhere in this repo a claim can be written.

    Three kinds, because the claim is written in all three: markdown (`doc_files()`),
    Python docstrings and comments, and the console's JSDoc. A section that read only
    `docs/` would miss the commonest home of the claim — the module docstring sitting
    directly above the constant.
    """
    for path in doc_files() if docs is None else list(docs):
        yield _rel(path), 1, path.read_text(encoding="utf-8")
    for path, source, tree in _python_sources(roots):
        for line, text in _python_prose(source, tree):
            yield _rel(path), line, text
    web_root = WEB_SOURCE_ROOT if web is None else web
    if web_root.exists():
        for path in sorted(web_root.rglob("*.ts*")):
            if "node_modules" not in path.parts:
                yield _rel(path), 1, path.read_text(encoding="utf-8")


@cache
def _default_value_claims() -> tuple[ValueClaim, ...]:
    """Scanned once. `blind_spots()`, `capability_drift()` and the OK line all want it."""
    return tuple(value_claims(prose_blocks()))


def value_claims(blocks: Iterable[tuple[str, int, str]] | None = None) -> list[ValueClaim]:
    """Every present-tense statement of a boolean's value, anywhere in the repo.

    Lines are matched in overlapping PAIRS and a hit is kept only when the NAME starts in
    the first of them, so a claim wrapped by an 88-column doc is still seen exactly once
    and attributed to the line the name is on.
    """
    if blocks is None:
        return list(_default_value_claims())
    claims: list[ValueClaim] = []
    for where, first_line, text in blocks:
        lines = _STRUCK.sub(_mask, text).splitlines()
        for index, line in enumerate(lines):
            window = line if index + 1 >= len(lines) else f"{line}\n{lines[index + 1]}"
            for match in _VALUE_CLAIM.finditer(window):
                if match.start("name") >= len(line):
                    continue  # belongs to the next line; that line's own window has it
                claims.append(
                    ValueClaim(
                        doc=where,
                        line=first_line + index,
                        name=match.group("name"),
                        stated=match.group("value") == "True",
                        sentence=" ".join(window.split())[:120],
                    )
                )
    return claims


def capability_drift(
    claims: Iterable[ValueClaim] | None = None,
    constants: dict[str, ConstantFact] | None = None,
    known: set[str] | None = None,
) -> list[str]:
    """The reverse check this repo never had: prose quoting a constant it has outgrown.

    THE MATCHING RULE, and why it does not cry wolf. Three narrowings do the work, and
    each was measured against the real tree before it was kept:

    * **Stating a value, not naming the constant.** `payments.py` names
      `PROVIDER_CREATES_ORDERS` four times without stating what it is; so do
      `flags/registry.py`, `provisioning_routes.py` and a runbook heading. None of them
      is judged, because none of them can be wrong about a value it does not give. Only
      the joined forms are — `NAME = False`, `NAME is False`, `is now`, `is still`,
      `stays`, `remains`, `flips to` — which is the whole difference between this check
      and the occurrence-grep that was thrown away for flagging three files that merely
      mentioned a credential.
    * **Adjacency, not proximity.** Nothing may sit between the copula and the literal but
      backticks and asterisks. `whatsapp_cloud.py` writes "the same device
      `payments.py::PROVIDER_CREATES_ORDERS` and `ingest/meta.py::LEAD_RETRIEVAL_IMPLEMENTED`
      use — and it stays False", where the "it" is a THIRD constant and both named ones
      are True. Any window-based rule reports that line twice and is wrong twice.
    * **Present tense only.** BUILD-LOG is a chronological log whose older sessions
      correctly record states that have since changed. "was False", "had been False",
      "will be True", "must be False" are history, plan or requirement — none of them a
      claim about this tree — and none of them matches. The four real offenders all wrote
      "is False" or "= False", in the present, about now.

    What it costs: a doc CAN dodge the check by never stating the value, and that is
    fine — the constant is still greppable and the doc has claimed nothing. What it buys
    is that the sentence which sounds authoritative is the one that has to be right.
    """
    facts = capability_constants() if constants is None else constants
    spelled = module_level_names() if known is None else known
    failures: list[str] = []
    for claim in value_claims() if claims is None else claims:
        fact = facts.get(claim.name)
        if fact is not None:
            if fact.value != claim.stated:
                failures.append(
                    f"{claim.where} states `{claim.name}` is {claim.stated}, and "
                    f"{fact.where} defines it {fact.value}. The greppable constant is this "
                    "repo's answer to 'is it built' — when it flips, the prose quoting it "
                    "moves in the same change or the doc is confidently wrong in the "
                    f"direction nobody audits. Sentence: {claim.sentence!r}"
                )
            continue
        if claim.name not in spelled:
            failures.append(
                f"{claim.where} states `{claim.name}` is {claim.stated}, and no module-level "
                f"name in {[_rel(root) for root in CAPABILITY_ROOTS]} spells it. A renamed "
                "capability constant takes every sentence quoting it out of this check's "
                "sight while leaving them all readable and wrong — rename the prose too. "
                f"Sentence: {claim.sentence!r}"
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
    # The money rate card, blinded the same way. A heading rename or a table rewritten
    # into prose leaves `doc_tts_rates()` empty, at which point section 4b would report
    # OK on any price the biller carried — including one nobody agreed.
    declared_tts = doc_tts_rates()
    if set(declared_tts) != set(code_tts_rates()):
        failures.append(
            f"{_rel(TRD)} §10.1's TTS rate card parsed to {sorted(declared_tts)} against "
            f"the {sorted(code_tts_rates())} rungs `billing/rates.py` bills — the table's "
            "shape moved, so section 4b is comparing against a partial reading"
        )
    constants = capability_constants()
    if len(constants) < 3:
        failures.append(
            f"only {len(constants)} module-level boolean constant(s) found in "
            f"{[_rel(root) for root in CAPABILITY_ROOTS]} — the honesty device this repo "
            "runs on has either been deleted or stopped being discoverable, and section 5 "
            "would pass on any prose"
        )
    stated = value_claims()
    if len(stated) < 8:
        failures.append(
            f"only {len(stated)} sentence(s) in the whole repo state a boolean constant's "
            "value — the matcher has stopped matching (a markdown or docstring convention "
            "moved), so section 5 would report OK on a doc that contradicts every constant"
        )
    # Section 7's left side: the gate roster. An OPERATIONS §2 whose table shape moved
    # parses to nothing, at which point every "assumed … (gate n)" sentence in the tree is
    # judged against an empty roster and section 7 reports OK on all of them — the same
    # vacuous pass this function exists for. The VERDICTS are deliberately not floored:
    # "no gate carries a terminal verdict" is the true state of the pilot today, and a
    # floor there would fail on the truth.
    gates = gate_roster()
    if len(gates) < 10:
        failures.append(
            f"only {len(gates)} pilot gate(s) parsed out of {_rel(_GATE_ROSTER_DOC)} §2 — "
            "the gate table's shape changed, so section 7 would accept an assumption "
            "citing any number at all"
        )
    # And the floor above is NOT enough, which is worth the extra six lines because the
    # miss already happened once. Losing ONE row out of twenty-eight passes any count
    # floor and still makes section 7 report a live citation as dangling — which is how
    # gate 7's `| 7 **H** *(was S …)*` spelling was found. The scorecard is the second
    # reading of the same roster, so the honest floor is a subset check: every gate the
    # committed scorecard scores must be a gate OPERATIONS §2 declares. The reverse does
    # not hold and must not be asserted — the roster carries gates (15, 16b…16f, 20b/20c)
    # the Bolna scorecard has no row for.
    scored = set(_scorecard_gate_ids())
    if gates and (missing := sorted(scored - gates)):
        failures.append(
            f"{_rel(_SCORECARD_DOC)} scores gate(s) {', '.join(missing)} that "
            f"{_rel(_GATE_ROSTER_DOC)} §2 does not declare — either a gate lost its row "
            "in the authoritative roster, or `_GATE_ROW` has stopped matching the shape "
            "one row is written in, and section 7 would call every citation of it dangling"
        )
    # The third reading, and the one the two above cannot make. Both floors compare the
    # roster against something else — a count, and the scorecard's subset. Neither can
    # see a row the PATTERN never matched, because a row that does not match is not a row
    # as far as either floor is concerned: it is simply absent, and absent looks exactly
    # like a gate that was never written. `L` proved that — two rows sat unreadable
    # behind a count floor that had been raised specifically to catch this.
    failures.extend(unknown_gate_priorities())
    failures.extend(capability_ambiguities())
    return failures


# --- 6. what readiness reports, against what the docs say it reports ------------------
#
# WHY THIS SECTION EXISTS. Four documents — `runbooks/deploy-failed.md`, DEPLOYMENT §9,
# `scripts/vps-deploy.sh`'s preflight comment and PRODUCTION-READINESS P5.15 — each said
# `PLATFORM_KEK` is "in neither `BOOTSTRAP_REQUIRED` nor `runtime_config_missing_keys`",
# and it has been in the second of those for as long as the sentence has existed (D-393).
# One of the four went further and concluded from it that the KEK is "Unguarded in code".
#
# That is not a typo, it is the D-103/D-105 class: a fact about the code, spelled by hand,
# in four places, all copied from the first. What makes it operational is WHERE it is
# read — an operator at 3am, told the probe already answering their question will not.
#
# Section 5's device does not reach it: `capability_drift` compares prose against
# module-level BOOLEAN CONSTANTS, and this is a membership question about a list a
# function builds at runtime. So the membership is asked directly, of a `Settings` with
# nothing set outside `local`, which is the state every one of those sentences is about.
#: A line that DENIES membership: it names the function and negates it. Matched on the
#: line rather than on a hand-parsed sentence — the four real offenders spelled it four
#: ways ("in neither X nor Y", "it is not in Y", "and not in Y", a table cell whose
#: subject is three columns to the left), and a grammar that fitted them all would fit
#: nothing else. The negation words are what separate a denial from an ordinary mention;
#: the OK line's count is what shows the section is still reading something.
_READINESS_FUNCTION = "runtime_config_missing_keys"
_READINESS_DENIAL = re.compile(r"\b(not|neither|nor|without|lacks|absent)\b", re.IGNORECASE)
#: How far back a negation may sit and still be ABOUT this function. Forty characters is
#: "in neither `BOOTSTRAP_REQUIRED` nor " with room to spare, and short enough that a
#: negation about a different clause earlier in the sentence is not read as one about
#: this one — the corrected sentences all begin "it is not in `BOOTSTRAP_REQUIRED`, so …"
#: and would otherwise be flagged for the words that make them correct.
_DENIAL_REACH = 40
#: An explicit affirmation anywhere on the line wins over a negation near the name. Every
#: sentence that CORRECTS one of these claims says so out loud, and saying so is exactly
#: what should switch this section off for that line.
_READINESS_AFFIRMATION = re.compile(r"\b(does|reports?|names?|lists?|listed|included)\b")
#: Any environment-variable-shaped token on such a line. Bounded to 4+ characters so
#: `RPO`, `IST` and `SLO` are not read as keys, and matched anywhere on the line because
#: the subject of the sentence is not reliably beside the verb.
_ENV_KEY = re.compile(r"\b([A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+)\b")


def _readiness_keys_when_nothing_is_set() -> frozenset[str]:
    """What `/healthz/ready` names on a non-local deployment with nothing configured.

    Built from the real function rather than a list, because a list here would be the
    fifth hand-written copy of the thing this section exists to catch.
    """
    import os

    from apps.api.core.settings import runtime_config_missing_keys
    from calevate_shared.config import Settings

    settings = Settings.model_validate(
        {
            "app_env": "prod",
            "database_url": "postgresql+psycopg://u:p@localhost:5432/x",
            "redis_url": "redis://localhost:6379/0",
            "object_store_endpoint": "https://example.invalid",
            "object_store_bucket": "b",
        }
    )
    # The two object-store names are read off `os.environ`, not off `Settings`, so they
    # are reported here whatever the caller's shell holds. Neutralised so this answer is
    # about the code and not about the machine running the check.
    saved = {k: os.environ.pop(k, None) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")}
    try:
        return frozenset(runtime_config_missing_keys(settings))
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def readiness_claim_drift(paths: Iterable[Path] | None = None) -> list[str]:
    """Prose saying a key is NOT a readiness key, where readiness names it."""
    reported = _readiness_keys_when_nothing_is_set()
    if not reported:
        # `blind_spots()`' doctrine: an empty answer means the probe stopped answering,
        # and a section that compares against nothing reports OK on every sentence.
        return [
            "`runtime_config_missing_keys` named no key at all on a bare non-local "
            "Settings — section 6 is comparing every doc claim against an empty set"
        ]
    offenders: list[str] = []
    roots = DOC_ROOTS if paths is None else None
    documents = list(doc_files(roots)) if paths is None else list(paths)
    # The deploy script is prose too, in a comment, and it carried the same sentence.
    documents.append(REPO_ROOT / "scripts" / "vps-deploy.sh")
    for path in documents:
        # THE DECISION LOG IS EXEMPT, AND IT IS THE ONE EXEMPTION. A `D-xxx` row's job is
        # to quote the sentence it fixed — D-393's own row contains the PLATFORM_KEK
        # denial verbatim, because a decision that did not say what was wrong is not a
        # decision. Every other document in the set is read as CURRENT INSTRUCTION, which
        # is what makes a stale sentence there an operational defect rather than a record.
        if not path.exists() or path == ROADMAP:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            at = line.find(_READINESS_FUNCTION)
            if at < 0 or _READINESS_AFFIRMATION.search(line):
                continue
            if not _READINESS_DENIAL.search(line[max(0, at - _DENIAL_REACH) : at]):
                continue
            for key in _ENV_KEY.findall(line):
                if key in reported:
                    offenders.append(
                        f"{_rel(path)}:{lineno} denies that {key} is in "
                        f"`{_READINESS_FUNCTION}`, and readiness reports it — an operator "
                        "is being told the probe already answering their question will not"
                    )
    return offenders


# --- 7. an assumption the pilot has since ANSWERED ------------------------------------
#
# D-413, recovered from an abandoned branch. The marked-assumption doctrine (D-31/D-32)
# says a vendor behaviour is a GATE or a MARKED ASSUMPTION and never a silent premise, and
# this repo keeps that side of the bargain: PRODUCTION-READINESS §D lists every premise
# baked into the adapter, and the runbooks and adapter comments each cite the gate that
# settles theirs.
#
# The half nothing checked is what happens when a gate is ANSWERED. A pilot run that closes
# gate 8 does not visit the sentences saying `list_kb`'s agent linkage is "assumed present";
# they keep reading as open, an operator keeps treating a measured fact as a guess, and —
# worse in the other direction — a gate answered RED leaves a sentence saying "assumed"
# where the truth is "refuted". An assumption that has been answered and still reads as
# open is exactly as misleading as an unmarked one, which is the case `capability_drift`
# makes for capability constants and this section makes for pilot gates.
#
# WHAT IT COMPARES. The gate ROSTER comes from OPERATIONS §2, which the scorecard itself
# calls authoritative; the VERDICTS come from `docs/evidence/bolna-pilot-scorecard.md`,
# which is generated from typed results and drift-guarded against them
# (`scripts/pilot/scorecard.py --check`). A citation is judged only when it sits in a
# sentence that MARKS AN ASSUMPTION — "assumed", "unverified", "inferred", "undocumented"
# and the rest of `_OPEN_ASSUMPTION` — because a sentence that merely says "gate 6 measures
# the page size" describes the gate and cannot be stale.
#
# TWO FAILURES, and the second is the one armed today while the first waits for the pilot:
#
#   (a) the cited gate carries a TERMINAL verdict (PASS or FAIL) and the sentence still
#       says the question is open;
#   (b) the citation names a gate OPERATIONS §2 does not have — a renumbering, a typo, or
#       a gate that was removed, which reads as tracked and is tracked by nothing. This is
#       section 2's `D-xx` rule applied to the other set of numbers this repo cites.
#
# Fails OPEN on anything it cannot parse: an unreadable verdict cell counts as NOT RUN, so
# a scorecard whose format moves makes this section quiet rather than wrong. The ROSTER
# half is the half that would be wrong instead of quiet, so it is floored in `blind_spots`
# — see there for why the floor is a subset check and not a count.
_GATE_ROSTER_DOC = REPO_ROOT / "docs" / "OPERATIONS.md"
_SCORECARD_DOC = REPO_ROOT / "docs" / "evidence" / "bolna-pilot-scorecard.md"

#: The first cell of an OPERATIONS §2 gate row: an id, then the H/S priority marker.
#: `\*{0,2}` around the marker is not defensive padding — gate 7 is spelled
#: `| 7 **H** *(was S — raised by D-261)* |` because D-261 raised it, and a pattern
#: demanding a bare `H` silently drops that row. It dropped it while this section was
#: being ported: the roster came back 27 gates instead of 28 and every "assumed … gate 7"
#: sentence in the tree — including one in `engine/bolna.py` — was reported as citing a
#: gate that does not exist. A roster that loses a row is the failure mode this whole
#: section is about, one level down.
_GATE_ROW = re.compile(r"^\|\s*(\d+[a-z]?)\s+\*{0,2}([A-Z])\*{0,2}\b")

#: The priority letters OPERATIONS §2 actually uses. NOT used to decide what a row IS —
#: `_GATE_ROW` matches any capital, so an unknown letter is CAUGHT rather than skipped —
#: only to decide whether the roster still understands the document it is reading.
#:
#: THIS SET EXISTS BECAUSE WIDENING THE PATTERN ONCE WAS NOT ENOUGH. The comment above
#: records the pattern being widened for `**H** *(was S …)*` after gate 7 vanished. The
#: identical class then recurred with a letter instead of a marker: `L` was introduced,
#: `[HS]` did not match it, and gates 14c and 20d dropped out of the roster silently —
#: found by a human counting rows, which is the reading this section exists to replace.
#: Enumerating the pattern's alternatives is how it keeps happening, so the pattern now
#: accepts the SHAPE and this set audits the VOCABULARY; a new priority letter fails the
#: build by name instead of shrinking the roster to something that still looks fine.
_GATE_PRIORITIES = frozenset({"H", "S", "L"})
#: `| 6 | **Webhook loss behaviour** … | automated | _NOT RUN_ | … |` in the scorecard.
_SCORECARD_ROW = re.compile(r"^\|\s*(\d+[a-z]?)\s*\|(.+)$")
#: A citation: `gate 6b`, `gate 12(f)`, `pilot gate 8a`, `gate 14`.
_GATE_CITATION = re.compile(r"\bgate\s+(\d+)\s*(?:\(([a-z])\)|([a-z])\b)?", re.IGNORECASE)
#: What makes a sentence a CLAIM about an open question rather than a description of one.
_OPEN_ASSUMPTION = re.compile(
    r"\b(assumed|assumes|assumption|unverified|not verified|never verified|guess(es|ed)?|"
    r"inferred|undocumented|unconfirmed|open pilot gate)\b",
    re.IGNORECASE,
)
_TERMINAL_VERDICTS = ("**PASS**", "**FAIL**")


def unknown_gate_priorities(path: Path | None = None) -> list[str]:
    """Gate rows whose priority letter is not one this module knows.

    Separated from `gate_roster` so the roster stays a plain set and the REFUSAL is a
    finding with a line number. A row reaching here is already IN the roster — the point
    is not to drop it, it is to say out loud that the document grew a vocabulary this
    file has not been taught, before somebody reads a gate count that quietly means
    something else.
    """
    doc = _GATE_ROSTER_DOC if path is None else path
    if not doc.exists():
        return []
    return [
        f"{doc.name}:{lineno} gate {match.group(1)} has priority "
        f"{match.group(2)!r}, which `_GATE_PRIORITIES` does not know "
        f"({', '.join(sorted(_GATE_PRIORITIES))}). Teach this module the letter, or fix "
        "the row — a priority nobody declared is a gate nobody triages."
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1)
        if (match := _GATE_ROW.match(line)) and match.group(2) not in _GATE_PRIORITIES
    ]


def gate_roster(path: Path | None = None) -> set[str]:
    """Every gate id OPERATIONS §2 declares, e.g. {"1", …, "14b", "20c"}."""
    doc = _GATE_ROSTER_DOC if path is None else path
    if not doc.exists():
        return set()
    return {
        match.group(1)
        for line in doc.read_text(encoding="utf-8").splitlines()
        if (match := _GATE_ROW.match(line))
    }


def _scorecard_gate_ids(path: Path | None = None) -> set[str]:
    """Every gate id the committed scorecard has a row for, verdict or not.

    Read separately from `gate_verdicts` because the two questions differ: that one asks
    what has been SETTLED (and is empty today, correctly), this one asks what the
    scorecard is ABOUT — which is a second reading of the roster and therefore the thing
    `blind_spots` can hold the roster against.
    """
    doc = _SCORECARD_DOC if path is None else path
    if not doc.exists():
        return set()
    return {
        match.group(1)
        for line in doc.read_text(encoding="utf-8").splitlines()
        if (match := _SCORECARD_ROW.match(line))
    }


def gate_verdicts(path: Path | None = None) -> dict[str, str]:
    """Gate id -> the terminal verdict cell the committed scorecard renders for it.

    A gate with no terminal cell is absent from this mapping rather than present with a
    falsy value: NOT RUN and unparseable are the same answer here — "nothing has settled
    this" — and collapsing them is what makes the section fail open.
    """
    doc = _SCORECARD_DOC if path is None else path
    if not doc.exists():
        return {}
    verdicts: dict[str, str] = {}
    for line in doc.read_text(encoding="utf-8").splitlines():
        match = _SCORECARD_ROW.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(2).split("|")]
        terminal = [cell for cell in cells if cell in _TERMINAL_VERDICTS]
        if terminal:
            verdicts[match.group(1)] = terminal[0]
    return verdicts


def answered_assumptions(
    *,
    roster: set[str] | None = None,
    verdicts: dict[str, str] | None = None,
    files: Iterable[Path] | None = None,
) -> list[str]:
    known = gate_roster() if roster is None else roster
    settled = gate_verdicts() if verdicts is None else verdicts
    scanned = _citation_files() if files is None else files
    failures: list[str] = []
    for path in scanned:
        if path in (_GATE_ROSTER_DOC, _SCORECARD_DOC):
            continue  # the artefacts themselves: a roster and a result, not claims
        if path.name.endswith("_test.py"):
            # A test's own fixtures say "assumed … (gate <n>)" in order to drive this
            # check. Excluded HERE rather than in `_citation_files`, because a dangling
            # `D-xx` in a test IS a citation to nothing while a synthetic gate sentence is
            # the subject under test. (No example number is spelled out anywhere in this
            # file, for the reason section 2 gives about `D-xx`: this file is scanned by
            # its own section, and an illustration would be a citation to nothing.)
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not _OPEN_ASSUMPTION.search(line):
                continue
            for match in _GATE_CITATION.finditer(line):
                base = match.group(1)
                letter = match.group(2) or match.group(3) or ""
                if known and base not in known:
                    failures.append(
                        f"{_rel(path)}:{number} marks an assumption against gate "
                        f"{base}{letter}, and OPERATIONS §2 has no gate {base}. A premise "
                        "tracked by a gate that does not exist is tracked by nothing "
                        f"(known gates: {', '.join(sorted(known))}). Sentence: "
                        f"{line.strip()[:160]!r}"
                    )
                    continue
                verdict = settled.get(base)
                if verdict:
                    failures.append(
                        f"{_rel(path)}:{number} still reads as open — it marks an "
                        f"assumption against gate {base}{letter}, which "
                        f"{_rel(_SCORECARD_DOC)} records as {verdict}. An answered "
                        "assumption that still says 'assumed' is as misleading as an "
                        "unmarked one: rewrite the sentence with what the gate found. "
                        f"Sentence: {line.strip()[:160]!r}"
                    )
    return failures


# --- gate -----------------------------------------------------------------------


def main() -> int:
    sections: tuple[tuple[str, list[str]], ...] = (
        ("this check cannot see its own subject", blind_spots()),
        ("a doc names a command nothing answers to", unresolved_commands()),
        ("a decision reference resolves to nothing", dangling_decisions()),
        ("the decision log numbers a decision twice", duplicate_decision_ids()),
        ("a decision row is not one line, so the table ends there", broken_decision_rows()),
        ("a compliance rule name the code no longer has", unknown_rule_names()),
        ("the rate-zone table and the nginx template disagree", rate_zone_drift()),
        ("the cost model and the biller price a TTS rung differently", tts_rate_card_drift()),
        ("the cost model and the code disagree on the in-call LLM leg", llm_cost_curve_drift()),
        ("the cost model and the biller price the STT leg differently", stt_rate_card_drift()),
        ("the legal catalogue and the web bundle disagree", legal_catalogue_drift()),
        ("a deferral that no longer holds", stale_deferrals()),
        ("prose states a capability constant's value, and the tree disagrees", capability_drift()),
        ("a doc denies a key readiness actually reports", readiness_claim_drift()),
        ("an assumption the pilot has answered still reads as open", answered_assumptions()),
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
        f"{len(doc_tts_rates())} TTS rungs priced identically by TRD §10.1 and the biller, "
        f"{len(doc_stt_rates_per_hour()) + len(doc_stt_rates_per_minute())} STT rate "
        f"statements in TRD §10.1 agreeing with `STT_INR_PER_HOUR`, "
        f"{sum(len(points) for points in doc_llm_cost_points().values())} in-call LLM cost "
        f"points, across {len(doc_llm_cost_points())} models, matching "
        f"`llm_cost_inr_per_minute`, "
        f"{len(value_claims())} sentences quote one of "
        f"{len(capability_constants())} capability constants correctly, "
        f"{len(DEFERRED_MIRRORS)} deferred mirror, "
        f"{len(web_legal_versions())} legal documents versioned identically by "
        f"the API catalogue and the web bundle, "
        f"{len(gate_roster())} pilot gates with no assumption outliving its answer)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
