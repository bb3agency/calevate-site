"""Guardrail: nothing is declared that nothing reaches (CLAUDE.md, "leave no
half-wired feature"; ENGINEERING-PRACTICES §2).

    A route nobody mounted, a job nobody registered, a column nobody reads and a
    migration nobody applied are not progress — they are defects that look like
    progress on a screen.

That rule was enforced by reading, and reading is the part that does not scale: each of
the four shapes below shipped in this repo and was caught by a person, late. D-29's
whole argument is that a rule which depends on human vigilance gets violated exactly
when the codebase grows fastest.

**Why an unmounted router is the one with teeth.** It does not merely do nothing. Every
sweep this repo relies on for authorization — `assert_policy_registry_complete` at boot,
`impersonation_reads_test`, `authz_audit_test`, `check_redaction_exposure` — enumerates
the routes of the LIVE app. A router nothing mounts is in none of those enumerations, so
it can carry a D-22 violation, an undeclared permission or a raw-PII response for as long
as it stays unmounted, and every one of those checks reports green. The day somebody
mounts it, the violation arrives with it. `apps/api/agents/publishing_routes.py` sat in
exactly that state, complete and tested.

WHAT THIS DOES NOT DO, AND WHY (see also the research note at the bottom of this file):

* Not a general dead-code scan. `vulture` and `deadcode` answer "is this symbol
  referenced", which on a FastAPI/SQLAlchemy/Pydantic codebase is a false-positive
  machine — decorator-registered handlers, ORM attributes and response-model fields are
  all "unreferenced" and all alive. This file asks four narrow, framework-aware
  questions instead, each with a live registry to compare against.
* Not "written but never read". Distinguishing a write from a read would need a SQL
  parser (most of this repo's column access is raw `text()` SQL, per BACKEND-PATTERNS),
  so `agents.business_hours` — which had a writer and no reader — is NOT caught here.
  Named honestly rather than half-implemented: what is caught is the stronger and
  commoner form, a column no code touches at all.
* No enum/`Literal`-member reachability check. An enum member is legitimately produced
  by a DB row, an engine payload or client input, so "no code path produces it" is not
  statically decidable here and a check that guessed would train people to add
  exemptions. Those values are constrained where they can be: CHECK constraints in the
  migration, and the engine conformance suite.
* No ARQ cron check. `cron()` takes the coroutine BY REFERENCE, so "a cron registered
  with no function" cannot be expressed; the real failure — a job enqueued by a name no
  worker answers to — is `tests/job_registration_test.py`. What this file adds there is
  in `tests/wiring_guard_test.py`: that `WorkerSettings` still IS those two lists.

Run: `uv run python -m scripts.check_wiring`  (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
API_ROOT = REPO_ROOT / "apps" / "api"
VOICE_RUNTIME_ROOT = REPO_ROOT / "apps" / "voice-runtime"
SCAN_ROOTS = (REPO_ROOT / "apps", REPO_ROOT / "packages")

# Modules that build a router somewhere other than module level, with the reason. The
# scan cannot see these, so `tests/wiring_guard_test.py` requires every route-owning
# module to be either visible or listed here — otherwise "invisible" and "mounted" look
# identical to this file.
DYNAMIC_ROUTER_MODULES: dict[str, str] = {
    "apps.api.core.health": (
        "the health router is built inside `health_router(...)` per service and mounted "
        "by `core.bootstrap.create_app`, so every service that boots has it by "
        "construction — there is no state in which it exists unmounted"
    ),
}

# Columns nothing in the tree touches, as of the day this guard landed. A BASELINE, not
# an allowlist: `stale_baseline()` fails on any entry whose column has since been wired,
# so the list can only shrink, and a NEW unwired column fails the guard outright. Every
# entry says what closes it — an entry that cannot say that is a defect wearing a
# comment (`check_redaction_exposure`'s KNOWN_SAFE_FIELDS is the precedent, and it is
# keyed per FIELD for the same reason: a model-level exemption would cover the next
# column somebody adds).
UNWIRED_BASELINE: dict[str, str] = {
    "Agent.engine_staging_ref": (
        "D-39 two-speed publishing: the staging-side engine ref. `agents/publishing.py` "
        "currently stages through `engine_agent_ref` only; closes when the engine "
        "adapter gains a staging clone (pilot gate 5)"
    ),
    "Campaign.engine_campaign_ref": (
        "the id Bolna's own campaign object would carry. TRD §5 lists engine campaigns "
        "as UNVERIFIED, so dispatch runs in our layer and writes nothing here; closes "
        "with the campaign built-in verification or is dropped in a two-step (rule 8)"
    ),
    "Call.consent_recording": (
        "recording consent per call. The disclosure line is enforced and logged, but "
        "the engine reports no per-call recording consent yet (pilot gate 3); "
        "`consent_ledger` is the ledger of record until it does"
    ),
    "KbRetrievalLog.query": (
        "deliberate and dated — see the class docstring in apps/api/kb/models.py. It "
        "would hold raw caller utterances in a table with no `text_redacted` "
        "counterpart, so hard rule 5 blocks the obvious producer outright"
    ),
    "KbRetrievalLog.top_score": (
        "deliberate and dated — see the class docstring in apps/api/kb/models.py. "
        "In-call retrieval happens inside the engine (D-33) and neither engine surface "
        "reports a retrieval outcome; a producer becomes possible at pilot gate 8"
    ),
    "KbRetrievalLog.latency_ms": (
        "same deferral as KbRetrievalLog.top_score — inventing a latency for a "
        "retrieval we did not perform is worse than an empty column"
    ),
}

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# --- 1. routers ---------------------------------------------------------------


def _python_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.endswith("_test.py"):
            continue
        yield path


def _module_name(path: Path) -> str:
    """Import name for a file, honouring D-18's hyphenated service directory.

    `apps/voice-runtime/` is not a legal module path, which is why `lint-imports`
    cannot see it at all (grimp walks packages). It runs with `--app-dir`, so its
    modules import by bare stem — the same way `main:app` does under uvicorn.
    """
    if VOICE_RUNTIME_ROOT in path.parents:
        return path.stem
    return ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)


def declared_routers() -> list[tuple[str, str]]:
    """`(module, attribute)` for every module-level `X = APIRouter(...)`.

    Read off the AST rather than by importing and scanning `dir()`: a module-level
    declaration is the thing the repo's convention promises, and the AST sees it whether
    or not the module imports cleanly in this process. Module level ONLY — a router
    inside a function is a factory, handled by `DYNAMIC_ROUTER_MODULES`.
    """
    found: list[tuple[str, str]] = []
    for root in (API_ROOT, VOICE_RUNTIME_ROOT):
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in tree.body:  # module level only
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                    continue
                func = node.value.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name != "APIRouter":
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.append((_module_name(path), target.id))
    return found


def mounted_endpoints() -> set[Any]:
    """Endpoint functions the two live apps will actually serve.

    Endpoint IDENTITY, not path strings: `include_router` copies route objects but
    carries the same function object across, so this compares the router's contents to
    the app's contents without matching on anything a rename could break.
    """
    from apps.api.core.rbac import iter_api_routes
    from apps.api.main import app as api_app

    if str(VOICE_RUNTIME_ROOT) not in sys.path:
        sys.path.insert(0, str(VOICE_RUNTIME_ROOT))
    voice_app = importlib.import_module("main").app

    return {route.endpoint for app in (api_app, voice_app) for route in iter_api_routes(app)}


def unmounted_routers(
    declared: Iterable[tuple[str, str]] | None = None,
    mounted: set[Any] | None = None,
) -> list[str]:
    """Routers with routes that no app serves.

    `mounted` is injectable for the same reason `check_redaction_exposure`'s allowlist
    is: an exemption — or a registry — nobody can take away in a test is one nobody can
    prove still sees anything (`tests/wiring_guard_test.py` reconstructs the
    publishing-routes state with it).
    """
    routers = list(declared_routers() if declared is None else declared)
    live = mounted_endpoints() if mounted is None else mounted
    offenders: list[str] = []

    for module, attribute in routers:
        router = getattr(importlib.import_module(module), attribute, None)
        # `getattr(..., "endpoint", None)`, not `route.endpoint`. A nested
        # `include_router` leaves an `_IncludedRouter` marker in `router.routes`
        # which has no `.endpoint`, and reading it raised AttributeError — so this
        # guard CRASHED on a repo shape rather than judging it, which is the worst
        # way for executable governance to fail: it looks like a broken tool, not a
        # finding, and the reflex is to work around the guard. Markers carry no
        # endpoint identity of their own and the routes they stand for are judged
        # under their own module, so dropping them loses nothing.
        endpoints = {
            endpoint
            for route in getattr(router, "routes", [])
            if (endpoint := getattr(route, "endpoint", None)) is not None
        }
        if not endpoints:
            # A router with no routes cannot be half-wired; it is scaffolding, and the
            # first route added to it will be judged here.
            continue
        missing = endpoints - live
        if missing == endpoints:
            offenders.append(
                f"{module}.{attribute}: declares {len(endpoints)} route(s) and the app "
                "mounts none of them — invisible to the boot RBAC assertion and to every "
                "route-table sweep. Add it to `_mount_routers` in apps/api/main.py."
            )
        elif missing:
            names = sorted(getattr(endpoint, "__name__", "?") for endpoint in missing)
            offenders.append(
                f"{module}.{attribute}: partially mounted — {names} are on the router and "
                "not in the app. `include_router` copies the routes that exist WHEN IT IS "
                "CALLED, so a route decorated after the mount call is silently dropped."
            )
    return offenders


# --- 2. migrations ------------------------------------------------------------


def _script_directory(alembic_dir: Path) -> Any:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(alembic_dir))
    return ScriptDirectory.from_config(config)


def migration_head(alembic_dir: Path | None = None) -> str:
    heads = _script_directory(alembic_dir or REPO_ROOT / "alembic").get_heads()
    return str(heads[0])


def migration_base(alembic_dir: Path | None = None) -> str:
    """The first revision — the one whose `down_revision` is None."""
    script = _script_directory(alembic_dir or REPO_ROOT / "alembic")
    oldest = list(script.iterate_revisions(migration_head(alembic_dir), "base"))[-1]
    return str(oldest.revision)


def unreachable_migrations(alembic_dir: Path | None = None) -> list[str]:
    """Revisions `alembic upgrade head` would not apply.

    Alembic's own `ScriptDirectory` walks the revision map, so this is the same graph
    the migration runner uses rather than a re-implementation of it (the documented
    single-head check: `get_heads()` is longer than one when a branch exists —
    alembic.sqlalchemy.org/en/latest/api/script.html). Two agents generating a
    migration in the same afternoon is all it takes, and the loser's tables exist in
    the file, in review, and in nobody's database.
    """
    script = _script_directory(alembic_dir or REPO_ROOT / "alembic")
    heads = script.get_heads()
    if len(heads) <= 1:
        return []
    # The trunk is the head with the longest ancestry, not `heads[0]` — the order
    # alembic returns them in is not defined, and picking the wrong one would report
    # every real migration in the repo as the orphan.
    primary = max(heads, key=lambda head: len(list(script.iterate_revisions(head, "base"))))
    reachable = {revision.revision for revision in script.iterate_revisions(primary, "base")}
    return [
        f"revision {revision.revision} ({Path(revision.path).name}) is on a second head — "
        f"`alembic upgrade head` from {primary} never reaches it. Merge the branch "
        "(`alembic merge`) or re-parent the migration."
        for head in heads[1:]
        for revision in script.iterate_revisions(head, "base")
        if revision.revision not in reachable
    ]


# --- 3. columns ---------------------------------------------------------------


def _model_files(roots: Iterable[Path]) -> list[Path]:
    """Where columns are DECLARED: `models.py` plus the mixin base they inherit from."""
    files: list[Path] = []
    for root in roots:
        files += [path for path in _python_files(root) if path.name in ("models.py", "base.py")]
    return files


def _declared_columns(model_files: Iterable[Path]) -> dict[str, Path]:
    """`{Model.column: file}` for every `Mapped[...]` attribute."""
    columns: dict[str, Path] = {}
    for path in model_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                target = statement.target
                if not isinstance(target, ast.Name):
                    continue
                if "Mapped" in ast.unparse(statement.annotation):
                    columns[f"{node.name}.{target.id}"] = path
    return columns


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of the Constant nodes that are docstrings — prose, not wiring."""
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


def _referenced_names(path: Path) -> set[str]:
    """Every name this file could be touching a column by.

    Structural, with one deliberate exception. Attribute access, keyword arguments,
    bare names and annotated fields come off the AST — a Pydantic response field named
    for the column IS a read, and a `Model(col=...)` keyword IS a write. The exception
    is string constants, tokenized: most column access in this repo is raw `text()`
    SQL (BACKEND-PATTERNS §3), and a scan that ignored strings would call the entire
    admin intake module unwired. Docstrings are excluded, because a half-wired column
    is usually DESCRIBED somewhere — counting prose as wiring would blind the check
    precisely where the bug lives. Comments never reach the AST at all.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = _docstring_nodes(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            names.update(_IDENTIFIER.findall(node.value))
    return names


def unwired_columns(
    roots: Iterable[Path] | None = None,
    baseline: dict[str, str] | None = None,
) -> list[str]:
    """Columns no non-model file mentions in any executable position.

    Blind by construction on columns whose name is a common word (`status`, `tier`,
    `query`): some unrelated variable will mention it. That is the safe direction —
    this check misses rather than accuses, because a guardrail with false positives
    trains people to add exemptions until it means nothing.
    """
    scan_roots = SCAN_ROOTS if roots is None else tuple(roots)
    known = UNWIRED_BASELINE if baseline is None else baseline
    model_files = _model_files(scan_roots)
    columns = _declared_columns(model_files)

    mentioned: set[str] = set()
    for root in scan_roots:
        for path in _python_files(root):
            if path in model_files:
                continue
            mentioned |= _referenced_names(path)

    return sorted(
        f"{key} ({path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path.name})"
        for key, path in columns.items()
        if key.split(".")[1] not in mentioned and key not in known
    )


def stale_baseline() -> list[str]:
    """The baseline may only shrink, and only by wiring something.

    Two ways it rots: an entry for a column that no longer exists (a hole waiting for
    the next column to land on that name), and an entry for a column somebody has since
    wired (a permanent excuse for a fixed problem). Both fail.
    """
    model_files = _model_files(SCAN_ROOTS)
    columns = _declared_columns(model_files)
    still_unwired = set(unwired_columns(baseline={}))
    failures: list[str] = []
    for key in sorted(UNWIRED_BASELINE):
        if key not in columns:
            failures.append(f"UNWIRED_BASELINE entry {key} names no column — remove it")
        elif not any(offender.startswith(f"{key} ") for offender in still_unwired):
            failures.append(
                f"UNWIRED_BASELINE entry {key} is wired now — delete the entry. The "
                "baseline only shrinks."
            )
    return failures


# --- gate ---------------------------------------------------------------------


def main() -> int:
    sections = (
        ("routers nothing mounts", unmounted_routers()),
        ("migrations no head reaches", unreachable_migrations()),
        ("columns no code touches", unwired_columns()),
        ("baseline entries that no longer hold", stale_baseline()),
    )
    failed = False
    for title, offenders in sections:
        if offenders:
            failed = True
            print(f"WIRING: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            "\nCLAUDE.md: leave no half-wired feature. Finish the seam, or — for a "
            "deliberate deferral — record it in this script's registry WITH the reason "
            "and what closes it."
        )
        return 1

    print(
        f"WIRING: OK ({len(declared_routers())} routers all mounted, "
        f"1 migration head, {len(UNWIRED_BASELINE)} deferred columns recorded)"
    )
    return 0


# Research note (2026-08, before writing any of the above), so the next reader inherits
# the evidence and not just the conclusion:
#
# * `vulture` — the standard Python dead-code finder. Rejected as the mechanism: it
#   answers "is this symbol referenced anywhere", and on framework code that is a
#   false-positive machine — it flags Pydantic model fields (102 of them in FastAPI's
#   own repo) because a field is serialized, never called, and it cannot know that a
#   mounted `@router.get` is alive while an unmounted one is not. Its own answer to
#   this is a whitelist file that simulates usage, i.e. exactly the exemption treadmill
#   the design constraint here forbids. (github.com/jendrikseipp/vulture;
#   dev.to/duriantaco "Python Dead Code: I Scanned Flask, FastAPI and 7 Other Repos")
# * `ruff` — F401/F841/F811 only ever see one file at a time; unused-import is a
#   different question from unreachable-registration. Already a CI gate here, and it
#   would not have caught one of the four instances. (docs.astral.sh/ruff/rules)
# * `deadcode`, `deptry` — same shape as vulture (globally unused symbols) and unused
#   dependencies respectively; neither knows what a live route table is.
# * `import-linter` — already in `make guardrails` for hard rule 2. It constrains which
#   modules may import which, and an unmounted router breaks no import contract: the
#   module is imported by nothing, which is legal and invisible. Also cannot see
#   `apps/voice-runtime` at all (grimp walks packages; D-18's directory is hyphenated),
#   which is why the router scan above handles that directory itself.
# * alembic's `ScriptDirectory.get_heads()` — ADOPTED rather than re-implemented, per
#   the documented single-head-in-CI recipe. Parsing `down_revision` by hand would be a
#   second implementation of the revision map that can disagree with the real one.
#
# The departure from all of the above is the same one in each case: this file does not
# ask whether a symbol is referenced. It asks whether a declaration appears in the
# REGISTRY that gives it effect — the app's route table, alembic's revision map, the
# set of names any executable line mentions. That is what makes a whitelist unnecessary
# for the shapes it does check, and it is why it declines to check the shapes where no
# such registry exists (enum members, read-vs-write).

if __name__ == "__main__":
    sys.exit(main())
