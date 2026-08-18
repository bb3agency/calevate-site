"""Guardrail: the half-wired shapes `check_wiring` declines, swept over the whole backend.

CLAUDE.md names four: "A route nobody mounted, a job nobody registered, a column nobody
reads and a migration nobody applied are not progress — they are defects that look like
progress on a screen." `scripts/check_wiring.py` guards those four, and its docstring is
explicit about what it does NOT do:

    Not "written but never read". Distinguishing a write from a read would need a SQL
    parser […] so a column with a writer and no reader is NOT caught here.

That sentence is the seam this file closes, plus the shapes neither file covered: a
`Settings` knob nothing consumes, an exported symbol nothing names, a stub body standing
in for logic, a handler that turns a failure green, and a marker that defers work without
saying what closes it.

═══ WHY TWO FILES AND NOT ONE ═══

They ask different questions and fail for different reasons, and merging them would
produce a gate whose output nobody can act on.

`check_wiring` asks **"is this declaration in the registry that gives it effect?"** — the
app's route table, alembic's revision map, the set of names any executable line mentions.
Its answers are yes/no and its evidence is a live object.

This file asks **"does the code that exists do the thing it appears to do?"** — which is
a judgement about POSITION (a name in a write clause is not a name in a read clause) and
about BODY (a handler that logs nothing is not a handler that handles). Every section
here needs a baseline or a heuristic; not one section there does. Keeping them apart is
what lets `check_wiring` stay exemption-free.

The split is stated in both files so a reader who lands on either knows where the other
half of the question lives.

═══ WHAT IS NOT CHECKABLE HERE, SAID PLAINLY ═══

* **Frontend consumption.** "A mounted route no client calls" is derivable — mounted
  paths against `apps/web` — but it is a REPORT, not a defect: an admin route that ships
  ahead of its screen is legitimate, and an ops route deliberately has no screen. Making
  it fail would be a gate whose only remedy is an exemption.
* **Whether a metric anybody records is anybody's alarm.** `alerting._record` reaches a
  log and no pipeline (its own comment says so); "this series is unread" is a question
  about a system that does not exist yet.
* **Whether a read is a MEANINGFUL read.** A column selected into a dataclass nobody
  renders passes section 1. Position is decidable; purpose is not, and a check that
  guessed would train people to add exemptions until it means nothing —
  `check_wiring`'s argument, inherited.
* **Enum members and `Literal` values.** Same reason `check_wiring` gives: they are
  legitimately produced by a DB row, an engine payload or client input.

Run: `uv run python -m scripts.check_half_wired`  (also in `make guardrails`)
Negative controls: `tests/half_wired_guard_test.py`.

Exit codes: 0 = clean, 1 = findings, **2 = REFUSED** (a scan could not see its subject).
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

# The column parser, the file walk and the docstring filter come from `check_wiring`
# rather than being written again. Two parsers of `Mapped[...]` that can disagree about
# what a column IS would be the exact defect both files exist to catch, and the private
# names are imported deliberately: they are this repo's one implementation, and a public
# copy of them would be the second.
from scripts.check_wiring import (
    _declared_columns,
    _docstring_nodes,
    _model_files,
    _python_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = (
    REPO_ROOT / "apps",
    REPO_ROOT / "packages",
    REPO_ROOT / "scripts",
)
#: Where a symbol may be USED from without being production wiring. Tests count as a
#: reference — a helper only its own test calls is still reachable, and deleting it would
#: delete the test with it — but they are listed so section 3 can say which kind of
#: reference it found.
TEST_ROOTS = (REPO_ROOT / "tests",)


def _every_python_file(roots: Iterable[Path]) -> Iterator[Path]:
    """Every `.py` under `roots`, **tests included**.

    `check_wiring._python_files` deliberately skips `*_test.py`, which is right for
    asking "what does production wire up" and wrong for asking "what references this
    symbol": a helper the suite calls is reached, and deleting it would delete its own
    test with it. This walk is the reference side; `_python_files` stays the declaration
    side.
    """
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _display(path: Path) -> str:
    """A path as this check reports it — repo-relative where possible, absolute where the
    scan was pointed at a temporary tree by a negative control."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ══════════════════════════════════════════════════════════ 1. write-only columns


#: Columns with a writer and no reader, as of the day this guard landed. A BASELINE, not
#: an allowlist, on `check_wiring.UNWIRED_BASELINE`'s exact terms: `stale_baselines()`
#: fails on any entry whose column has since gained a reader or ceased to exist, so it can
#: only shrink, and a NEW write-only column fails outright. Every entry says what closes
#: it — an entry that cannot say that is a defect wearing a comment.
WRITE_ONLY_BASELINE: dict[str, str] = {
    "WebhookDelivery.signature_valid": (
        "forensic, and the reader is a person with psql. It records whether an inbound "
        "engine webhook was HMAC-verified or merely IP-allowlisted (SEC-COMP §4), which "
        "is the first question of a webhook-spoofing investigation and is asked once a "
        "year, not by a screen. Closes when the ops incident-scope surface exists — a "
        "response-model change, so it lands with `apps/web` rather than here"
    ),
    "Lead.first_call_id": (
        "the call that created the lead. `last_call_id` is selected and returned; this "
        "one is written by the same INSERT and never read, and giving it a reader means "
        "adding a field to `LeadOut` — a response-model change, which regenerates "
        "`apps/web/src/lib/api/openapi.json`. Closes with that snapshot, in the change "
        "that adds the field"
    ),
    "CampaignContact.dedupe_hash": (
        "write-stopped, step 1 of hard rule 8's two-step (D-233). `service.add_contacts` "
        "no longer writes it; retention's erase still NULLs the values older rows carry, "
        "which is the only statement left naming it. Closes with the DROP migration"
    ),
}


#: THE TWO FILES THAT NAME COLUMNS IN ORDER TO EXEMPT THEM, excluded from the evidence.
#:
#: This guard blinded itself on its first run: `WRITE_ONLY_BASELINE` below names
#: `Lead.first_call_id` in a string, `_positions_in` counts string identifiers as reads
#: (it must — most column access here is raw `text()` SQL), and so every entry in the
#: baseline was "read" by the baseline. `stale_baselines()` then reported all three as
#: fixed and demanded their removal, which would have deleted the record and let the
#: columns fail the check again on the next run — a guardrail oscillating against itself.
#:
#: `check_wiring` does not hit this only because its scan roots stop at `apps` and
#: `packages`; this one covers `scripts/` too, which is where both registries live. The
#: rule generalises: a registry that names its own subject is never evidence about it.
_REGISTRY_FILES = frozenset(
    {
        Path(__file__).resolve(),
        REPO_ROOT / "scripts" / "check_wiring.py",
    }
)


def _check_constraint_names(model_files: Iterable[Path]) -> set[str]:
    """Identifiers named inside a `CheckConstraint`/`Index`/`UniqueConstraint` argument.

    **A DATABASE CONSTRAINT IS A READER**, and the sharpest kind: it evaluates the column
    on every write and refuses the row. `AuthSession.revoked_reason`,
    `QaCallSample.reviewed_by_admin_id`, `FirstCampaignReview.decision_source` and
    `RecordingErasureHold.tenant_erasure_id` are each written by exactly one statement
    and selected by none — and each is half of an integrity rule that would fail loudly
    if the column stopped being written. Counting them as unread would have made this
    check's first run four-fifths noise, which is how a guardrail teaches people to add
    exemptions.
    """
    names: set[str] = set()
    for path in model_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called not in ("CheckConstraint", "Index", "UniqueConstraint", "ForeignKey"):
                continue
            for piece in ast.walk(node):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    names.update(_IDENT.findall(piece.value))
                elif isinstance(piece, ast.Name):
                    names.add(piece.id)
    return names


_SQL_HINT = re.compile(r"\b(select|insert\s+into|update|delete\s+from|set|where)\b", re.I)
_INSERT_COLUMNS = re.compile(r"insert\s+into\s+[\w.\"]+\s*\(([^)]*)\)", re.I | re.S)
# The SET clause ends at WHERE / RETURNING / FROM, whichever comes first — everything
# after those is a READ again, including `RETURNING processed_at`.
_SET_CLAUSE = re.compile(r"\bset\b(.*?)(?=\bwhere\b|\breturning\b|\bfrom\b|$)", re.I | re.S)
_ASSIGNMENT_TARGET = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=")


def sql_positions(statement: str) -> tuple[set[str], set[str]]:
    """`(written, read)` identifiers in one SQL-looking string.

    Most column access in this repo is raw `text()` SQL (BACKEND-PATTERNS §1's "no
    repository layer"), so a scan that ignored strings would see almost no access at all.
    A full SQL parser was considered and rejected: `sqlglot` is a new runtime dependency
    for a check that needs one distinction — is this identifier in a position that STORES
    a value, or one that CONSUMES it — and hard rule 9 makes every added package a
    supply-chain decision. The two storing positions are closed-form:

    * the column list of an `INSERT INTO t (...)`
    * the assignment TARGETS of a `SET` clause, up to WHERE/RETURNING/FROM

    Everything else in the statement is a read, which is the safe direction: this check
    MISSES rather than ACCUSES.
    """
    written: set[str] = set()
    write_spans: list[tuple[int, int]] = []
    for match in _INSERT_COLUMNS.finditer(statement):
        written |= set(_IDENT.findall(match.group(1)))
        write_spans.append(match.span(1))
    for match in _SET_CLAUSE.finditer(statement):
        body, offset = match.group(1), match.start(1)
        for target in _ASSIGNMENT_TARGET.finditer(body):
            written.add(target.group(1))
            write_spans.append((offset + target.start(1), offset + target.end(1)))
    read = {
        found.group(0)
        for found in _IDENT.finditer(statement)
        if not any(start <= found.start() < end for start, end in write_spans)
    }
    return written, read


def _positions_in(path: Path, *, strings_are_evidence: bool = True) -> tuple[set[str], set[str]]:
    """`(written, read)` names in one Python file, by AST position.

    * `x.col = ...` / `f(col=...)` — a constructor keyword, a `.values(col=...)` — WRITE.
    * `x.col` in load position, a bare name, a Pydantic field annotation — READ.
    * string constants: SQL by position (above), anything else read as identifiers,
      because a job name or a column referenced through a dict key is a use.

    Docstrings are excluded. A half-wired column is usually DESCRIBED somewhere, and
    counting prose as wiring blinds the check exactly where the bug lives —
    `check_wiring`'s reasoning, kept identical so the two agree about what a mention is.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = _docstring_nodes(tree)
    written: set[str] = set()
    read: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            (written if isinstance(node.ctx, ast.Store) else read).add(node.attr)
        elif isinstance(node, ast.Name):
            (written if isinstance(node.ctx, ast.Store) else read).add(node.id)
        elif isinstance(node, ast.keyword) and node.arg:
            written.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            read.add(node.target.id)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and strings_are_evidence
        ):
            if _SQL_HINT.search(node.value):
                statement_written, statement_read = sql_positions(node.value)
                written |= statement_written
                read |= statement_read
            else:
                read.update(_IDENT.findall(node.value))
    return written, read


def write_only_columns(
    roots: Iterable[Path] | None = None,
    baseline: dict[str, str] | None = None,
) -> list[str]:
    """Columns something stores and nothing consumes.

    Blind by construction on columns whose name is a common word — some unrelated
    variable reads it — and on columns nothing touches at all, which are
    `check_wiring.unwired_columns`' subject rather than this one's.
    """
    scan = SCAN_ROOTS if roots is None else tuple(roots)
    known = WRITE_ONLY_BASELINE if baseline is None else baseline
    model_files = _model_files(scan)
    columns = _declared_columns(model_files)
    constrained = _check_constraint_names(model_files)

    written: set[str] = set()
    read: set[str] = set()
    for root in scan:
        for path in _python_files(root):
            if path in model_files:
                continue
            # A registry file's STRINGS are not evidence about its own subject; its code
            # still is. See `_REGISTRY_FILES`.
            file_written, file_read = _positions_in(
                path, strings_are_evidence=path.resolve() not in _REGISTRY_FILES
            )
            written |= file_written
            read |= file_read

    offenders = []
    for key in sorted(columns):
        name = key.split(".", 1)[1]
        if name in read or name in constrained or name not in written or key in known:
            continue
        offenders.append(
            f"{key}: stored and never consumed — no SELECT, no RETURNING, no response "
            "field, no CHECK constraint. Either give it a reader or stop writing it "
            "(hard rule 8's two-step), and record a deliberate deferral in "
            "WRITE_ONLY_BASELINE with what closes it."
        )
    return offenders


# ══════════════════════════════════════════════════════════ 2. settings nobody reads


#: Files that DECLARE or CLASSIFY a setting without consuming it. A name appearing only
#: here is a knob an operator can install that changes nothing — `cohere_api_key` was
#: exactly that: declared, classified `applies: live` so the ops console offered it, and
#: read by no code path in the repository.
_SETTINGS_DECLARATION_SITES = (
    "packages/shared/src/calevate_shared/config.py",
    "apps/api/core/platform_config.py",
    "apps/api/core/settings.py",
)


def settings_fields() -> dict[str, int]:
    """`{field: line}` for every `Settings` attribute, off the AST.

    The AST rather than `Settings.model_fields`, so this answers the same way whether or
    not a `.env` in the working directory lets the model instantiate.
    """
    path = REPO_ROOT / "packages" / "shared" / "src" / "calevate_shared" / "config.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    fields: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    fields[statement.target.id] = statement.lineno
    return fields


def unconsumed_settings(fields: dict[str, int] | None = None) -> list[str]:
    """Settings fields no code outside the declaration sites ever names."""
    declared = settings_fields() if fields is None else fields
    consumers: dict[str, set[str]] = {}
    for path in _every_python_file((*SCAN_ROOTS, *TEST_ROOTS)):
        relative = _display(path)
        if relative in _SETTINGS_DECLARATION_SITES:
            continue
        _, read = _positions_in(path)
        for name in declared:
            if name in read:
                consumers.setdefault(name, set()).add(relative)
    return [
        f"Settings.{name} (config.py:{line}): declared, classifiable and read by nothing. "
        "A key an operator can install that changes no behaviour is worse than no key — "
        "delete the field with its classification row, or land it in the same change as "
        "the code that reads it (the argument D-177 made when it deleted the Clerk six)."
        for name, line in sorted(declared.items())
        if name not in consumers
    ]


# ══════════════════════════════════════════════════════════ 3. exports nothing names


#: Public module-level functions that nothing in the repository references. Shrink-only,
#: same terms as `WRITE_ONLY_BASELINE`.
UNREFERENCED_BASELINE: dict[str, str] = {
    "scripts/pilot/record.py::recorded_fixtures": (
        "the replay seam for adapter fixtures captured DURING the Bolna pilot. There are "
        "no fixtures and therefore no replay tests, because no pilot has run — an "
        "external blocker (a Bolna account with credit, OPERATIONS §2). Closes when the "
        "first gate is executed and `load_fixture`'s callers arrive with it"
    ),
}

#: HTTP verbs: `@<anything>_router.post(...)` is FastAPI dispatch. Matched on the verb
#: rather than on the receiver, because this repo names its routers `invite_router`,
#: `sources_router`, `national_dnd_router` and a dozen more — an exact-match list of
#: receiver names is a list that goes stale on the next module, which is how a guardrail
#: starts reporting live endpoints as dead code.
_ROUTE_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "websocket"})

#: Decorators that mean "a framework calls this, not us". A name reached by dispatch is
#: alive however few source references it has, and reporting one is how a guardrail gets
#: a reputation for being wrong.
_DISPATCHED_DECORATORS = frozenset(
    {
        "app",
        "router",
        "field_validator",
        "model_validator",
        "validator",
        "fixture",
        "hookimpl",
        "asynccontextmanager",
        "contextmanager",
        "overload",
        "cached_property",
        "property",
        "setter",
        "singledispatch",
        "register",
        "cache",
        "lru_cache",
    }
)

#: Names a framework calls BY NAME with no reference anywhere: pytest's hook protocol and
#: the module entry point. Prefix-matched, because the hook set grows.
_DISPATCHED_PREFIXES = ("pytest_", "test_", "main", "upgrade", "downgrade")


def _decorator_roots(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    roots: set[str] = set()
    for decorator in node.decorator_list:
        for piece in ast.walk(decorator):
            if isinstance(piece, ast.Name):
                roots.add(piece.id)
            elif isinstance(piece, ast.Attribute):
                roots.add(piece.attr)
    return roots


def _public_functions(roots: Iterable[Path] | None = None) -> dict[str, tuple[str, int]]:
    """`{name: (file, line)}` for public module-level functions the frameworks do not
    dispatch. A name defined twice is dropped: two modules owning one name is section 8's
    question, and judging reachability across them needs the import graph."""
    seen: dict[str, tuple[str, int]] = {}
    duplicated: set[str] = set()
    for root in SCAN_ROOTS if roots is None else tuple(roots):
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                name = node.name
                if name.startswith("_") or name.startswith(_DISPATCHED_PREFIXES):
                    continue
                roots = _decorator_roots(node)
                if roots & _DISPATCHED_DECORATORS or roots & _ROUTE_VERBS:
                    continue
                if name in seen:
                    duplicated.add(name)
                seen[name] = (_display(path), node.lineno)
    return {name: place for name, place in seen.items() if name not in duplicated}


def _export_list_nodes(tree: ast.AST) -> set[int]:
    """Ids of every node under an `__all__` assignment.

    **`__all__` IS NOT A CALLER.** It is a re-export list, so a name whose only mention
    anywhere is its own module's `__all__` is exported to nobody — which is the exact
    state `fail_fast`, `get_sample` and `voice_selection_available` were found in: three
    public functions, three `__all__` entries, zero call sites in the whole repository
    including the suite.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        ids.update(id(piece) for piece in ast.walk(node))
    return ids


def _definition_name_nodes(tree: ast.AST) -> set[int]:
    """Ids of the DECORATOR nodes of every function definition.

    A decorator mentions the thing it wraps only in `@name.setter` shapes, but the
    walk below would otherwise count `@router.get(...)` on `def foo` as a reference to
    whatever `get` happens to name. Cheap, and it keeps the reference set to actual uses.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for decorator in node.decorator_list:
                ids.update(id(piece) for piece in ast.walk(decorator))
    return ids


def unreferenced_exports(
    baseline: dict[str, str] | None = None,
    roots: Iterable[Path] | None = None,
) -> list[str]:
    """Public functions no file — including their own, and including the suite — names.

    "No reference" is not proof of death on its own, which is why every deletion this
    guard motivates needs a human to rule out dispatch by name. What it IS proof of is
    that nothing STATIC reaches the symbol, and in a repo whose dynamic dispatch is
    bounded (arq job names are constants, FastAPI endpoints are decorated, pytest hooks
    are prefixed) that is a strong enough signal to have to answer.
    """
    known = UNREFERENCED_BASELINE if baseline is None else baseline
    scan = (*SCAN_ROOTS, *TEST_ROOTS) if roots is None else tuple(roots)
    functions = _public_functions(scan)
    references: dict[str, set[str]] = {}
    for path in _every_python_file(scan):
        # Same self-blinding this file hit on columns, and the narrow form of the same
        # fix: `UNREFERENCED_BASELINE` names the functions it exempts, and a string
        # identifier counts as a reference — so a registry file's STRINGS are not
        # evidence. Its real calls still are: `sections()` calling `write_only_columns()`
        # is a caller like any other, and dropping the whole file reported this script's
        # own sections as dead code.
        strings_are_evidence = path.resolve() not in _REGISTRY_FILES
        relative = _display(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        # Docstrings excluded for the reason `_positions_in` excludes them: a symbol that
        # is DESCRIBED somewhere is not a symbol that is called, and a dead function is
        # usually described — including, as this check found on its own negative controls,
        # by the test file that exists to prove it is dead.
        skip = _export_list_nodes(tree) | _definition_name_nodes(tree) | _docstring_nodes(tree)
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.Name):
                found = node.id
            elif isinstance(node, ast.Attribute):
                found = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if strings_are_evidence:
                    for token in _IDENT.findall(node.value):
                        if token in functions:
                            references.setdefault(token, set()).add(relative)
                continue
            else:
                continue
            if found in functions:
                references.setdefault(found, set()).add(relative)

    offenders = []
    for name, (file, line) in sorted(functions.items()):
        reached = references.get(name, set())
        if reached or f"{file}::{name}" in known:
            continue
        offenders.append(
            f"{file}:{line} {name}(): public, exported and referenced by nothing — not by "
            "another module, not by its own, not by a test. Prove it is dispatched by "
            "name, delete it, or record it in UNREFERENCED_BASELINE with what closes it."
        )
    return offenders


# ══════════════════════════════════════════════════════════ 4. stub bodies


def _is_protocol_or_abstract(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in ("Protocol", "ABC"):
            return True
    return False


def stub_bodies(roots: Iterable[Path] | None = None) -> list[str]:
    """Functions whose body stands in for logic that is not there.

    `...` in a `Protocol` body is the language's own spelling of "this is a signature",
    and `packages/shared/src/calevate_shared/engine.py` is 20 of them — so Protocol and
    ABC members are excluded by CLASS, not by an allowlist of names. What is left is a
    real stub: a concrete function that passes, ellipses, raises `NotImplementedError`,
    or returns a bare constant where logic belongs.

    A documented constant return is allowed through when the docstring says so —
    `engine/fake.py::holds_credentials` returns True because the fake adapter IS its own
    vendor, and `engine/cartesia.py::_cost` returns None because a guessed currency is
    worse than no cost. The rule is the same one CLAUDE.md applies everywhere: a deferral
    that names what closes it is a decision; one that does not is a leftover.
    """
    scan = SCAN_ROOTS if roots is None else tuple(roots)
    offenders: list[str] = []
    for root in scan:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            protocol_members: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and _is_protocol_or_abstract(node):
                    protocol_members.update(
                        id(member)
                        for member in ast.walk(node)
                        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
                    )
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if id(node) in protocol_members:
                    continue
                documented = ast.get_docstring(node) is not None
                body = node.body[1:] if documented else list(node.body)
                if len(body) != 1:
                    continue
                statement = body[0]
                shape: str | None = None
                if isinstance(statement, ast.Pass):
                    shape = "an empty body"
                elif (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and statement.value.value is Ellipsis
                ):
                    shape = "an ellipsis outside a Protocol"
                elif isinstance(statement, ast.Raise):
                    raised = statement.exc
                    target = raised.func if isinstance(raised, ast.Call) else raised
                    if isinstance(target, ast.Name) and target.id == "NotImplementedError":
                        shape = "NotImplementedError"
                if shape is None or documented:
                    continue
                offenders.append(
                    f"{_display(path)}:{node.lineno} {node.name}(): {shape}, "
                    "with no docstring saying what it stands in for. Implement it, or say "
                    "in the docstring what closes it (CLAUDE.md: a deferral names its "
                    "closer or it is not a deferral)."
                )
    return offenders


# ══════════════════════════════════════════════════════════ 5. handlers that swallow


#: Statement kinds that mean the handler DID something with the failure — logged it,
#: alerted, re-raised, recorded a counter, or set the state that makes a probe go red.
#:
#: THE RULE IS "DID NOTHING", NOT "LOGGED NOTHING", and the difference decides whether
#: this section is usable. A first cut demanded a logging call and reported four correct
#: handlers: `core/health.ready` sets `redis_ok = False` (the failure IS the readiness
#: verdict), `observability._RedactingExporter.export` bumps a dropped-span counter,
#: `observability._sentry_problems` appends a `ReadinessProblem`. Each acts on the
#: failure without a log line, and a guard that called them defects would have been
#: answered with an allowlist. What CLAUDE.md forbids is narrower and sharper: "Never
#: swallow an exception to make a path look green" — a handler whose entire body is
#: `pass`, `continue`, or `return <constant>` does exactly that and nothing else.
_ACTED_ON = (ast.Call, ast.Raise, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Await, ast.Yield)


def _handler_is_observed(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, _ACTED_ON) for node in ast.walk(handler))


def swallowed_exceptions(roots: Iterable[Path] | None = None) -> list[str]:
    """Broad handlers that leave no trace of the failure.

    NARROW handlers are not the subject and never fail here: `except ValueError: return
    None` around a parse is the function's interface, and this repo has ~30 of them. What
    this catches is a handler that names `Exception`, `BaseException` or nothing at all —
    i.e. one that will also catch the bug nobody predicted — and then neither logs, nor
    alerts, nor re-raises. CLAUDE.md: "Never swallow an exception to make a path look
    green."

    Re-raising counts, including `raise` from a wider `except` that narrows to a
    ProblemError. Returning a fallback does NOT count on its own — a fallback with no log
    line is precisely the shape that makes a dependency outage look like a quiet day.
    """
    scan = SCAN_ROOTS if roots is None else tuple(roots)
    offenders: list[str] = []
    for root in scan:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                caught = node.type
                if caught is None:
                    label = "a bare `except:`"
                elif isinstance(caught, ast.Name) and caught.id in ("Exception", "BaseException"):
                    label = f"`except {caught.id}`"
                else:
                    continue
                if _handler_is_observed(node):
                    continue
                offenders.append(
                    f"{_display(path)}:{node.lineno}: {label} whose body does "
                    "nothing at all — no log, no alert, no re-raise, no state change. The "
                    "failure reaches nobody and the path reads green. Log it with an "
                    "operator-actionable event name, or narrow the handler to the "
                    "exception the code actually expects."
                )
    return offenders


# ══════════════════════════════════════════════════════════ 6. unclosed deferrals


#: A MARKER, not the WORD. `#\s*TODO` catches the comment form with or without a colon;
#: `TODO:` / `TODO(` catches it inside a docstring. Prose that merely names the
#: vocabulary does not match — `engine_conformance/contract_test.py` argues that a
#: refusal "becomes a TODO with a name" the day an engine grows campaign objects, which
#: is a sentence about markers rather than one, and a check that cannot tell those apart
#: is a check people route around.
_MARKER = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b|(?<![A-Za-z_])(TODO|FIXME|XXX|HACK)\s*[:(]")
#: Files whose SUBJECT is the marker vocabulary — the deploy preflight refuses a `.env`
#: value carrying one, and the coverage ratchet argues about them in prose. Naming a
#: marker is not leaving one.
_MARKER_VOCABULARY_FILES = (
    "scripts/check_deploy_env.py",
    "scripts/check_coverage_ratchet.py",
    "scripts/check_half_wired.py",
)


def unclosed_deferrals(roots: Iterable[Path] | None = None) -> list[str]:
    """`TODO`/`FIXME`/`XXX`/`HACK` anywhere in the scanned tree, comments included.

    Read off the raw text rather than the AST, because a marker is almost always in a
    comment and comments never reach an AST at all — a marker scan over parsed source is
    a scan that cannot see its own subject.

    The rule this enforces is CLAUDE.md's, not a style preference: "A deferral is a
    decision-log entry naming what closes it, or it is not a deferral." A marker is a
    deferral with no owner, no closer and no expiry.
    """
    scan = SCAN_ROOTS if roots is None else tuple(roots)
    offenders: list[str] = []
    for root in scan:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = _display(path)
            if relative in _MARKER_VOCABULARY_FILES:
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                found = _MARKER.search(line)
                if found:
                    marker = found.group(1) or found.group(2)
                    offenders.append(
                        f"{relative}:{number}: `{marker}` — a deferral with no "
                        "closer. Do it now, or write it into the decision log naming what "
                        "closes it and delete the marker."
                    )
    return offenders


# ══════════════════════════════════════════════════════════ 0. can this see its subject


def blind_spots() -> list[str]:
    """Refuse rather than print OK when a scan matches nothing (D-176).

    Every section here compares a derived set against another derived set, and a
    comparison whose left side is empty answers "clean" for everything. `check_wiring`
    printed `WIRING: OK (0 routers all mounted)` from exactly this, which is why it grew
    the section this one copies.

    Floors an order of magnitude below the real counts: the question is "is this scan
    still populated", and a floor that tracked the true number would fail on every
    deletion.
    """
    failures: list[str] = []
    columns = _declared_columns(_model_files(SCAN_ROOTS))
    if len(columns) < 100:
        failures.append(
            f"only {len(columns)} `Mapped[...]` column(s) found under "
            f"{[root.name for root in SCAN_ROOTS]} — section 1 would report every "
            "write-only column as consumed because it can see none of them"
        )
    if len(settings_fields()) < 20:
        failures.append(
            f"only {len(settings_fields())} `Settings` field(s) parsed — section 2 is "
            "comparing an empty declaration list against the whole tree and cannot fail"
        )
    if len(_public_functions()) < 100:
        failures.append(
            f"only {len(_public_functions())} public module-level function(s) found — "
            "section 3 has lost its subject"
        )
    handlers = sum(
        isinstance(node, ast.ExceptHandler)
        for root in SCAN_ROOTS
        for path in _python_files(root)
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
    )
    if handlers < 50:
        failures.append(
            f"only {handlers} exception handler(s) parsed — sections 4 and 5 walk the "
            "same trees and would report a clean tree from an empty one"
        )
    return failures


def stale_baselines() -> list[str]:
    """A baseline may only shrink, and only by fixing something.

    Two ways each rots: an entry naming something that no longer exists (a hole for the
    next symbol to land in), and an entry for something already fixed (a standing excuse
    for a solved problem). Both fail.
    """
    failures: list[str] = []

    columns = _declared_columns(_model_files(SCAN_ROOTS))
    still_write_only = {offender.split(":")[0] for offender in write_only_columns(baseline={})}
    for key in sorted(WRITE_ONLY_BASELINE):
        if key not in columns:
            failures.append(f"WRITE_ONLY_BASELINE entry {key} names no column — remove it")
        elif key not in still_write_only:
            failures.append(
                f"WRITE_ONLY_BASELINE entry {key} has a reader now — delete the entry. "
                "The baseline only shrinks."
            )

    still_unreferenced = {
        f"{offender.split(':')[0]}::{offender.split(' ')[1].removesuffix('():')}"
        for offender in unreferenced_exports(baseline={})
    }
    for key in sorted(UNREFERENCED_BASELINE):
        if key not in still_unreferenced:
            failures.append(
                f"UNREFERENCED_BASELINE entry {key} is referenced now (or gone) — delete "
                "the entry. The baseline only shrinks."
            )
    return failures


# ══════════════════════════════════════════════════════════ gate


def sections() -> tuple[tuple[str, list[str]], ...]:
    return (
        ("columns something writes and nothing reads", write_only_columns()),
        ("settings nothing consumes", unconsumed_settings()),
        ("public functions nothing references", unreferenced_exports()),
        ("stub bodies standing in for logic", stub_bodies()),
        ("broad handlers that leave no trace", swallowed_exceptions()),
        ("deferral markers with no closer", unclosed_deferrals()),
        ("baseline entries that no longer hold", stale_baselines()),
    )


def main() -> int:
    refusals = blind_spots()
    if refusals:
        print("HALF-WIRED: REFUSED — this check cannot see its own subject")
        for refusal in refusals:
            print(f"  - {refusal}")
        print(
            "\nExit 2, not 1: nothing was judged. A guardrail that reports OK on a tree "
            "it cannot read is worse than one that is missing."
        )
        return 2

    failed = False
    for title, offenders in sections():
        if offenders:
            failed = True
            print(f"HALF-WIRED: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            "\nCLAUDE.md: leave no half-wired feature. Finish the seam, or — for a "
            "deliberate deferral — record it in this script's registry WITH the reason "
            "and what closes it."
        )
        return 1

    columns = len(_declared_columns(_model_files(SCAN_ROOTS)))
    print(
        f"HALF-WIRED: OK ({columns} columns and {len(settings_fields())} settings all "
        f"consumed, {len(_public_functions())} public functions all referenced, "
        f"{len(WRITE_ONLY_BASELINE) + len(UNREFERENCED_BASELINE)} deferrals recorded)"
    )
    return 0


def _iter_scanned() -> Iterator[Path]:
    """Every file this check judges — the one place the scan set is spelled, so a test
    can ask what it covered without re-deriving it."""
    for root in SCAN_ROOTS:
        yield from _python_files(root)


if __name__ == "__main__":
    sys.exit(main())
