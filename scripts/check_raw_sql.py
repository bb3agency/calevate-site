"""Guardrail: nothing but our own source text is ever spliced into a SQL string (D-172).

`text()` is the only door raw SQL uses in this tree — there is no `exec_driver_sql`, no
`literal_column`, no bare-string `execute` (SQLAlchemy 2.0 refuses that one) — and it is
used 493 times in the two trees this check scans (and about four times that again in
`tests/`, which is out of scope — see below), because most tenant-scoped access here is
hand-written SQL rather than ORM queries. Every one of those statements runs as a role that
is `NOSUPERUSER
NOBYPASSRLS`, so a successful injection does not merely read a table: it runs inside a
session whose `tenant_id` GUC decides visibility, and the first thing an attacker would
reach for is `SET LOCAL`. **An injection here is a cross-tenant breach of hard rule 1, not
a data leak in one account.** That is the whole reason this check exists at the level of
"no runtime value reaches the string" rather than at the level of "no obvious `%s`".

The rule, stated once
---------------------
A SQL string may be built ONLY from text written in this repository. Values go in as
BOUND PARAMETERS (`:name`); identifiers and SQL fragments may be interpolated only when
every character of them was typed by us.

Mechanically, the expression handed to `text(...)` must be *literal-derived*:

* a `str` constant (including implicit concatenation and triple-quoted blocks);
* an f-string, `%`, `+`, `.format()`, `.join()`, `.strip()`-family, a conditional
  expression or a comprehension, **all of whose parts are themselves literal-derived**;
* a name that resolves — in the enclosing function, then the module, then across a
  `from x import Y` — to literal-derived expressions only;
* a call to a function in this repo, **every `return` of which is literal-derived**;
* a call to a declared identifier validator (`SAFE_IDENTIFIER_CALLS`), which is the one
  way a genuinely dynamic identifier may reach SQL.

The interprocedural half is what makes this more than a linter
--------------------------------------------------------------
When a parameter is spliced into SQL, the safety of that statement is not decidable in
the function that writes it — it lives at the CALL SITES. `plans.plan_in_effect_sql`
says so in its own docstring: *"a caller that passes a user string is writing an
injection, and no caller does."* That sentence was true and enforced by nothing. So when
this check reaches a parameter, it does not give up and it does not wave it through: it
finds every call of that function in `apps/` and `packages/`, resolves the argument bound
to that parameter, and applies the same rule to it — recursively, with memoisation, so a
helper that passes a fragment down three layers is checked at the top of the chain.

That is also why the check needs no allowlist for `db/transition.py`, whose `table` and
`status_column` parameters go straight into an UPDATE: they are reassigned through
`_identifier()` first, and `_identifier` is a declared validator. The narrowing that
matters is that the validator must be applied **to the name that is interpolated**, in
the function that interpolates it — a validator called on some other variable proves
nothing about this one.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
* **`tests/` is out of scope.** A test builds SQL from its own literals against its own
  fixtures; there is no request, so there is no attacker-controlled value to splice. Ten
  test helpers take a `table` parameter and interpolate it, and every argument is a table
  name from `TENANT_TABLES`. Including them would add ~40 allowlist entries whose reason
  would be the same sentence, and an allowlist people skim is an allowlist people extend.
  `alembic/` is out for the same reason plus a stronger one: migrations are reviewed by
  hand as a matter of hard rule 8.
* **No taint tracking from request models.** That would be the stronger analysis and it is
  not the one this repo needs: the rule above is *stricter* than "no request data in SQL",
  because it refuses ALL runtime values, including ones that happen to be safe today. A
  narrower rule would need to be right about where data comes from; this one only needs to
  be right about what a literal is.
* **No opinion on the SQL itself.** Whether a statement is correct, indexed or tenant-
  scoped is the business of `check_rls_coverage`, the RLS sweep and review.

Allowances are per SITE and carry a reason (`SPLICE_ALLOWANCES`). There are none today,
which is the state to keep: an allowance here is a promise that a human reads every future
caller of that function, and this file exists because that promise does not survive.

Run: `uv run python -m scripts.check_raw_sql`
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where production SQL lives. `tests/` and `alembic/` are excluded on purpose — see the
#: module docstring.
SCAN_ROOTS: tuple[str, ...] = ("apps", "packages")

#: The SQLAlchemy constructor that turns a string into an executable statement. This is
#: the only raw-SQL door in the tree; the check asserts that below so a second one cannot
#: be added silently.
SQL_SINK = "text"

#: Other ways SQLAlchemy will execute a string. None of these is used here and none may
#: be: they would each be a second door this check does not watch, and "one way per
#: problem" (CLAUDE.md) applies to doors most of all.
FORBIDDEN_SINKS: frozenset[str] = frozenset({"exec_driver_sql", "literal_column"})

#: Functions that turn an untrusted string into a SQL identifier or refuse. A call to one
#: of these is literal-derived BY CONSTRUCTION, which is the only sanctioned way a runtime
#: value becomes SQL text. Adding a name here is adding a trust anchor: the function must
#: reject everything outside a fixed character class, and it must raise rather than
#: sanitise, because a sanitiser turns a hostile identifier into a valid one.
SAFE_IDENTIFIER_CALLS: frozenset[str] = frozenset({"_identifier"})

#: Per-site allowances: `"path/to/file.py:LINE"` -> why this splice cannot carry a runtime
#: value. Empty, and meant to stay that way; an entry is a standing promise to re-read
#: every caller of that function forever.
SPLICE_ALLOWANCES: dict[str, str] = {}

_MIN_REASON = 40

# String methods that cannot introduce text from outside their receiver and arguments.
_TEXT_METHODS: frozenset[str] = frozenset(
    {"format", "join", "strip", "lstrip", "rstrip", "upper", "lower", "replace", "removeprefix"}
)

# Builtins that only ever re-shape what they are given. `list(scope)` is exactly as safe
# as `scope`, and refusing it would push people to write `[*scope]` for the guardrail's
# benefit rather than the reader's.
_CONTAINER_BUILTINS: frozenset[str] = frozenset({"list", "tuple", "set", "sorted", "reversed"})

# Mutations that append text to a list later `join`ed into SQL. Without these,
# `clauses = ["a"]` followed by `clauses.append(user_input)` reads as safe.
_LIST_GROWERS: frozenset[str] = frozenset({"append", "extend", "insert"})


class RawSqlError(RuntimeError):
    """The check could not be run at all — a broken premise, not a verdict."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One SQL string this check cannot vouch for."""

    path: str
    line: int
    expression: str
    because: str

    @property
    def site(self) -> str:
        return f"{self.path}:{self.line}"

    def __str__(self) -> str:
        return f"{self.site}: {self.because}\n      text({self.expression})"


@dataclass(slots=True)
class Module:
    """One parsed source file, indexed for name resolution."""

    path: Path
    rel: str
    tree: ast.Module
    assignments: dict[str, list[ast.expr]] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    #: local name -> dotted module path it was imported from (`from a.b import c as d`).
    imported_from: dict[str, str] = field(default_factory=dict)
    #: local name -> original name in that module.
    imported_as: dict[str, str] = field(default_factory=dict)
    #: every function/lambda body node -> the function that owns it.
    owner: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)


def _module_name(rel: str) -> str:
    """`apps/api/billing/plans.py` -> `apps.api.billing.plans`.

    `apps/voice-runtime` is deliberately not importable (D-18's hyphen), so its modules
    get the same treatment every other file does and simply never match an import.
    """
    stem = rel[: -len(".py")]
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def _absolute_import(rel: str, node: ast.ImportFrom) -> str | None:
    """`from .plans import x` inside `apps/api/billing/charges.py` -> `apps.api.billing.plans`.

    Relative imports are the common spelling inside a package here, and resolving only
    absolute ones would silently make every same-package helper unresolvable — which this
    check reports as unsafe, so the cost of getting it wrong is noise, not a false pass.
    """
    if node.level == 0:
        return node.module
    package = _module_name(rel).split(".")
    if not rel.endswith("/__init__.py"):
        package = package[:-1]
    if node.level - 1 > len(package):
        return None
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, node.module]) if node.module else ".".join(base)


#: A literal that is safe by construction, handed out when a binding is provably not text
#: from outside — the integer `enumerate` produces, for instance.
_SAFE_LITERAL = ast.Constant(value=0)


class _Elements(ast.expr):
    """Synthetic node meaning "one thing yielded by iterating `value`".

    Iterating and indexing are different questions and a dict answers them with different
    halves of itself: `transition_status` builds `{":__t_from0": state}` where the KEYS are
    literals it wrote and the VALUES are the caller's statuses, then splices the keys and
    binds the values. Judging that dict with one verdict is wrong in one direction or the
    other — values-only passes a splice of the keys unread, keys-and-values refuses a
    statement that is correct. So a loop variable binds to `_Elements(iterable)` and the
    resolver asks the iteration question about it.
    """

    _fields = ("value",)

    def __init__(self, value: ast.expr) -> None:
        super().__init__()
        self.value = value


def _destructure(target: ast.expr, value: ast.expr) -> list[tuple[str, ast.expr]]:
    """Bind names on the left of `=` to the expressions that reach them.

    Written out rather than collapsed to "bind everything to the whole right-hand side"
    because that spelling produces the wrong answer in both directions on the two shapes
    this repo actually uses: `statement, params = (SQL, {"tid": tenant_id})` would make a
    literal SQL constant unsafe (the params dict holds a UUID), and a runtime tuple would
    make an unsafe element look safe if any sibling were a literal.
    """
    if isinstance(target, ast.Name):
        # `x = x` binds nothing. Without this it binds `x` to itself, the cycle guard
        # answers True on the back-edge, and a parameter launders itself clean in one line.
        if isinstance(value, ast.Name) and value.id == target.id:
            return []
        return [(target.id, value)]
    if not isinstance(target, (ast.Tuple, ast.List)):
        return []
    if isinstance(value, ast.IfExp):
        return _destructure(target, value.body) + _destructure(target, value.orelse)
    if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
        pairs: list[tuple[str, ast.expr]] = []
        for sub_target, sub_value in zip(target.elts, value.elts, strict=True):
            pairs.extend(_destructure(sub_target, sub_value))
        return pairs
    # Shape we cannot follow: every name takes the whole value, which `safe` will judge.
    return [(name.id, value) for name in target.elts if isinstance(name, ast.Name)]


def _destructure_iteration(target: ast.expr, iterable: ast.expr) -> list[tuple[str, ast.expr]]:
    """Bind loop variables to `_Elements(iterable)`, unwrapping the shapes we can read."""
    if isinstance(target, ast.Name):
        return [(target.id, _Elements(iterable))]
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(iterable, ast.Call):
        callee = iterable.func
        name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
        if name == "enumerate" and iterable.args and len(target.elts) == 2:
            # The index is an int this loop produced; only the second name sees the data.
            return [
                *_destructure(target.elts[0], _SAFE_LITERAL),
                *_destructure_iteration(target.elts[1], iterable.args[0]),
            ]
        if name == "zip" and len(iterable.args) == len(target.elts):
            pairs: list[tuple[str, ast.expr]] = []
            for sub_target, sub_iterable in zip(target.elts, iterable.args, strict=True):
                pairs.extend(_destructure_iteration(sub_target, sub_iterable))
            return pairs
        if name == "items" and isinstance(callee, ast.Attribute) and len(target.elts) == 2:
            # `for key, value in mapping.items()` — the two names see opposite halves.
            return [
                *_destructure(target.elts[0], _Elements(callee.value)),
                *_destructure(
                    target.elts[1], ast.Subscript(value=callee.value, slice=_SAFE_LITERAL)
                ),
            ]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [
            pair for element in target.elts for pair in _destructure_iteration(element, iterable)
        ]
    return []


def _collect_assignments(node: ast.stmt, into: dict[str, list[ast.expr]]) -> None:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            for name, value in _destructure(target, node.value):
                into.setdefault(name, []).append(value)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        if node.value is not None:
            into.setdefault(node.target.id, []).append(node.value)
    elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        into.setdefault(node.target.id, []).append(node.value)


def load_modules(root: Path = REPO_ROOT, scan_roots: tuple[str, ...] = SCAN_ROOTS) -> list[Module]:
    """Parse every production source file once. Raises rather than skipping a file it
    cannot read: a module this check silently dropped is a module it silently stops
    guarding."""
    modules: list[Module] = []
    for scan in scan_roots:
        base = root / scan
        if not base.is_dir():
            raise RawSqlError(f"scan root {scan!r} does not exist under {root}")
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=rel)
            except SyntaxError as exc:  # pragma: no cover - a broken tree fails CI anyway
                raise RawSqlError(f"{rel}: {exc}") from exc
            module = Module(path=path, rel=rel, tree=tree)
            for stmt in tree.body:
                _collect_assignments(stmt, module.assignments)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    module.functions.setdefault(node.name, node)
                    for child in ast.walk(node):
                        module.owner.setdefault(id(child), node)
                elif isinstance(node, ast.ImportFrom):
                    origin = _absolute_import(rel, node)
                    if origin is None:
                        continue
                    for alias in node.names:
                        local = alias.asname or alias.name
                        module.imported_from[local] = origin
                        module.imported_as[local] = alias.name
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module.imported_from[alias.asname or alias.name] = alias.name
                        module.imported_as[alias.asname or alias.name] = ""
            # Second pass: comprehension targets OUTSIDE any function are module-scope
            # names. `_NOT_AI_UNITS = "…" + ", ".join(f"'{u}'" for u in AI_UNITS)` binds `u`
            # here and nowhere else, and without this the constant reads as unsafe.
            for node in ast.walk(tree):
                if isinstance(node, ast.comprehension) and id(node) not in module.owner:
                    for name, value in _destructure_iteration(node.target, node.iter):
                        module.assignments.setdefault(name, []).append(value)
            modules.append(module)
    if not modules:
        raise RawSqlError("no source files found — the scan roots are wrong")
    return modules


class Resolver:
    """Answers one question: could this expression carry text we did not write?"""

    def __init__(self, modules: list[Module]) -> None:
        self.modules = modules
        self.by_name = {_module_name(m.rel): m for m in modules}
        self._in_progress: set[tuple[str, str, str]] = set()
        # Two indexes built once. Without them a single parameter query re-walked every
        # module in the tree, and the check took 23s; the rule is unchanged, the cost is
        # 0.8s, and a guardrail nobody waits for is a guardrail that stays in the loop.
        self._calls_by_name: dict[str, list[tuple[Module, ast.Call]]] = {}
        for module in modules:
            for node in ast.walk(module.tree):
                if isinstance(node, ast.Call):
                    callee = node.func
                    name = (
                        callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
                    )
                    if isinstance(name, str):
                        self._calls_by_name.setdefault(name, []).append((module, node))
        self._locals: dict[int, dict[str, list[ast.expr]]] = {}

    # --- name resolution -------------------------------------------------------

    def _function_of(
        self, module: Module, node: ast.AST
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return module.owner.get(id(node))

    def _local_values(
        self, func: ast.FunctionDef | ast.AsyncFunctionDef, name: str
    ) -> list[ast.expr]:
        """Every value assigned to `name` anywhere in `func`. ALL of them, not the last:
        a variable assigned a literal on one branch and a parameter on another is unsafe,
        and taking the last assignment would report whichever branch was written second."""
        cached = self._locals.get(id(func))
        if cached is not None:
            return cached.get(name, [])
        found: dict[str, list[ast.expr]] = {}
        for node in ast.walk(func):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                _collect_assignments(node, found)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                # `for k in from_binds` — an element of a safe iterable is safe.
                for bound, value in _destructure_iteration(node.target, node.iter):
                    found.setdefault(bound, []).append(value)
            elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
                found.setdefault(node.optional_vars.id, []).append(node.context_expr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                # `clauses.append(fragment)` contributes `fragment` to `clauses`.
                receiver = node.func.value
                if node.func.attr in _LIST_GROWERS and isinstance(receiver, ast.Name):
                    for argument in node.args:
                        found.setdefault(receiver.id, []).append(argument)
        self._locals[id(func)] = found
        return found.get(name, [])

    def _is_parameter(self, func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
        args = func.args
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if args.vararg is not None:
            every.append(args.vararg)
        if args.kwarg is not None:
            every.append(args.kwarg)
        return any(a.arg == name for a in every)

    def _resolve_import(self, module: Module, name: str) -> tuple[Module, str] | None:
        target = module.imported_from.get(name)
        if target is None:
            return None
        origin = self.by_name.get(target)
        if origin is None:
            return None
        return origin, module.imported_as.get(name) or name

    # --- the rule ---------------------------------------------------------------

    def safe(self, node: ast.expr, module: Module) -> bool:
        """True when every character `node` can produce was typed in this repository."""
        if isinstance(node, ast.Constant):
            # ANY constant, not just `str`. `f"...{DASHBOARD_DAYS - 1}..."` splices an int
            # that was typed in this file; a literal is a literal whatever its type.
            return True
        if isinstance(node, ast.JoinedStr):
            return all(
                self.safe(part.value, module)
                for part in node.values
                if isinstance(part, ast.FormattedValue)
            )
        if isinstance(node, ast.IfExp):
            return self.safe(node.body, module) and self.safe(node.orelse, module)
        if isinstance(node, ast.BinOp):
            return self.safe(node.left, module) and self.safe(node.right, module)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return all(self.safe(elt, module) for elt in node.elts)
        if isinstance(node, ast.Dict):
            # The VALUES: `safe(d)` is asked when something indexes `d`. Iteration asks
            # `_safe_elements`, which reads the keys instead.
            return all(self.safe(value, module) for value in node.values)
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            return self.safe(node.elt, module)
        if isinstance(node, ast.DictComp):
            return self.safe(node.value, module)
        if isinstance(node, _Elements):
            return self._safe_elements(node.value, module)
        if isinstance(node, ast.Starred):
            return self.safe(node.value, module)
        if isinstance(node, ast.Subscript):
            # Indexing a container of literals yields a literal. The INDEX is irrelevant:
            # whatever it selects, every element was written here.
            return self.safe(node.value, module)
        if isinstance(node, ast.Call):
            return self._safe_call(node, module)
        if isinstance(node, ast.Name):
            return self._safe_name(node, module)
        # Attribute reads, subscripts, awaits, comparisons: not text we can vouch for.
        return False

    def _safe_elements(self, node: ast.expr, module: Module) -> bool:
        """True when everything ITERATING `node` yields was typed in this repository."""
        if isinstance(node, ast.Dict):
            return all(key is not None and self.safe(key, module) for key in node.keys)
        if isinstance(node, ast.DictComp):
            return self.safe(node.key, module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "keys":
                return self._safe_elements(node.func.value, module)
            if node.func.attr == "values":
                return self.safe(node.func.value, module)
        if isinstance(node, ast.Name):
            values = self._values_of(node, module)
            if values is not None:
                key = (module.rel, "<elements>", node.id)
                if key in self._in_progress:
                    return True
                self._in_progress.add(key)
                try:
                    return all(self._safe_elements(value, module) for value in values)
                finally:
                    self._in_progress.discard(key)
        if isinstance(node, _Elements):
            # Iterating an iterable of iterables. Both levels hold our own text or neither.
            return self._safe_elements(node.value, module)
        # Lists, tuples, sets, comprehensions and everything else: `safe` already means
        # "every element is ours" for those shapes.
        return self.safe(node, module)

    def _values_of(self, node: ast.Name, module: Module) -> list[ast.expr] | None:
        """Every expression `node` could hold, or None when the name does not resolve."""
        func = self._function_of(module, node)
        if func is not None:
            local = self._local_values(func, node.id)
            if local:
                return local
        module_values = module.assignments.get(node.id)
        if module_values:
            return module_values
        imported = self._resolve_import(module, node.id)
        if imported is not None:
            origin, original = imported
            values = origin.assignments.get(original)
            if values:
                return values
        return None

    def _safe_call(self, node: ast.Call, module: Module) -> bool:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _TEXT_METHODS:
            return (
                self.safe(func.value, module)
                and all(self.safe(a, module) for a in node.args)
                and all(self.safe(k.value, module) for k in node.keywords)
            )
        # PLAIN NAMES ONLY from here. `obj.plan_in_effect_sql(...)` and
        # `module.plan_in_effect_sql(...)` are indistinguishable from the AST, so resolving
        # an ATTRIBUTE call to the module-level function of the same name would let any
        # object with a same-named method inherit that function's verdict. Every SQL helper
        # in this tree is imported and called by its bare name; if one ever needs to be
        # reached through a module alias, that is a deliberate change here, not a silent
        # widening. `_TEXT_METHODS` above is the one exception and it is closed-world.
        if not isinstance(func, ast.Name):
            return False
        name = func.id
        if name in SAFE_IDENTIFIER_CALLS:
            return True
        if name in _CONTAINER_BUILTINS:
            return all(self.safe(a, module) for a in node.args)
        target = self._lookup_function(module, name)
        if target is None:
            return False
        origin, definition = target
        return self._returns_safe(origin, definition)

    def _lookup_function(
        self, module: Module, name: str
    ) -> tuple[Module, ast.FunctionDef | ast.AsyncFunctionDef] | None:
        local = module.functions.get(name)
        if local is not None:
            return module, local
        imported = self._resolve_import(module, name)
        if imported is None:
            return None
        origin, original = imported
        definition = origin.functions.get(original)
        return None if definition is None else (origin, definition)

    def _returns_safe(self, module: Module, func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        key = (module.rel, func.name, "<return>")
        if key in self._in_progress:
            # Recursion: assume safe on the back-edge; the base case decides.
            return True
        self._in_progress.add(key)
        try:
            returns = [
                node.value
                for node in ast.walk(func)
                if isinstance(node, ast.Return) and node.value is not None
            ]
            if not returns:
                return False
            return all(self.safe(value, module) for value in returns)
        finally:
            self._in_progress.discard(key)

    def _safe_name(self, node: ast.Name, module: Module) -> bool:
        func = self._function_of(module, node)
        if func is not None:
            locals_ = self._local_values(func, node.id)
            if locals_:
                key = (module.rel, func.name, node.id)
                if key in self._in_progress:
                    return True
                self._in_progress.add(key)
                try:
                    if not all(self.safe(value, module) for value in locals_):
                        return False
                finally:
                    self._in_progress.discard(key)
                # A name may be BOTH assigned and a parameter (`table = _identifier(table)`).
                # The assignments decided it; the parameter is shadowed from here on.
                return True
            if self._is_parameter(func, node.id):
                return self._callers_pass_safe_values(module, func, node.id)
        module_values = module.assignments.get(node.id)
        if module_values:
            key = (module.rel, "<module>", node.id)
            if key in self._in_progress:
                return True
            self._in_progress.add(key)
            try:
                return all(self.safe(value, module) for value in module_values)
            finally:
                self._in_progress.discard(key)
        imported = self._resolve_import(module, node.id)
        if imported is not None:
            origin, original = imported
            values = origin.assignments.get(original)
            if values:
                key = (origin.rel, "<module>", original)
                if key in self._in_progress:
                    return True
                self._in_progress.add(key)
                try:
                    return all(self.safe(value, origin) for value in values)
                finally:
                    self._in_progress.discard(key)
            definition = origin.functions.get(original)
            if definition is not None:
                return self._returns_safe(origin, definition)
        return False

    # --- the interprocedural half ------------------------------------------------

    def _callers_pass_safe_values(
        self, module: Module, func: ast.FunctionDef | ast.AsyncFunctionDef, param: str
    ) -> bool:
        """`param` is spliced into SQL. Its safety lives at the call sites, so go there.

        A function nobody calls answers False: an unreachable splice is not proof of
        anything, and the day somebody calls it the argument goes unchecked.
        """
        key = (module.rel, func.name, param)
        if key in self._in_progress:
            return True
        self._in_progress.add(key)
        try:
            index = self._parameter_index(func, param)
            has_default = self._default_for(func, param)
            calls = list(self.call_sites(module, func))
            if not calls:
                return False
            for caller, call in calls:
                argument = self._argument_for(call, index, param)
                if argument is None:
                    if has_default is None:
                        # Bound by **kwargs or a star-args splat we cannot follow.
                        return False
                    if not self.safe(has_default, module):
                        return False
                    continue
                if not self.safe(argument, caller):
                    return False
            return True
        finally:
            self._in_progress.discard(key)

    @staticmethod
    def _parameter_index(func: ast.FunctionDef | ast.AsyncFunctionDef, param: str) -> int | None:
        positional = [*func.args.posonlyargs, *func.args.args]
        for i, arg in enumerate(positional):
            if arg.arg == param:
                return i
        return None

    @staticmethod
    def _default_for(func: ast.FunctionDef | ast.AsyncFunctionDef, param: str) -> ast.expr | None:
        positional = [*func.args.posonlyargs, *func.args.args]
        offset = len(positional) - len(func.args.defaults)
        for i, arg in enumerate(positional):
            if arg.arg == param and i >= offset:
                return func.args.defaults[i - offset]
        for arg, default in zip(func.args.kwonlyargs, func.args.kw_defaults, strict=True):
            if arg.arg == param:
                return default
        return None

    @staticmethod
    def _argument_for(call: ast.Call, index: int | None, param: str) -> ast.expr | None:
        for keyword in call.keywords:
            if keyword.arg == param:
                return keyword.value
            if keyword.arg is None:
                return None  # `**kwargs` — we cannot see what it carries.
        if index is not None and index < len(call.args):
            argument = call.args[index]
            return None if isinstance(argument, ast.Starred) else argument
        return None

    def call_sites(
        self, module: Module, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[tuple[Module, ast.Call]]:
        """Every call of `func` in the scanned tree, resolved through imports rather than
        matched on the bare name: two helpers may share a name and only one is this one.

        The name index includes ATTRIBUTE calls, which `_safe_call` deliberately refuses to
        resolve. The asymmetry is intentional and points the safe way: over-including a call
        site means checking one more argument, while over-resolving a callee means trusting
        one more function.
        """
        found: list[tuple[Module, ast.Call]] = []
        for candidate, node in self._calls_by_name.get(func.name, ()):
            resolved = self._lookup_function(candidate, func.name)
            if resolved is not None and resolved[1] is func:
                found.append((candidate, node))
        return found


def sql_sites(module: Module) -> list[ast.Call]:
    """Every `text(...)` call with a statement argument."""
    sites: list[ast.Call] = []
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
            if name == SQL_SINK and node.args:
                sites.append(node)
    return sites


def forbidden_sink_uses(modules: list[Module]) -> list[str]:
    """A second raw-SQL door would make every verdict here partial."""
    offenders: list[str] = []
    for module in modules:
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Call):
                callee = node.func
                name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
                if name in FORBIDDEN_SINKS:
                    offenders.append(f"{module.rel}:{node.lineno}: {name}() bypasses this check")
    return offenders


def audit(modules: list[Module] | None = None) -> list[Finding]:
    """Every SQL string whose text this check cannot trace back to our own source."""
    modules = modules if modules is not None else load_modules()
    resolver = Resolver(modules)
    findings: list[Finding] = []
    for module in modules:
        for call in sql_sites(module):
            statement = call.args[0]
            if resolver.safe(statement, module):
                continue
            findings.append(
                Finding(
                    path=module.rel,
                    line=call.lineno,
                    expression=_snippet(statement),
                    because="SQL text this check cannot trace to a literal in this repo",
                )
            )
    return findings


def _snippet(node: ast.expr, width: int = 140) -> str:
    rendered = " ".join(ast.unparse(node).split())
    return rendered if len(rendered) <= width else rendered[: width - 1] + "…"


def stale_allowances(findings: list[Finding]) -> list[str]:
    """An allowance for a site that is now clean, or that no longer exists. The registry
    may only shrink — the failure mode it prevents is an exemption outliving the code it
    excused and then silently covering whatever moved onto that line."""
    live = {finding.site for finding in findings}
    return sorted(site for site in SPLICE_ALLOWANCES if site not in live)


def thin_reasons() -> list[str]:
    return sorted(
        f"{site}: reason is {len(reason)} characters; {_MIN_REASON} is the floor"
        for site, reason in SPLICE_ALLOWANCES.items()
        if len(reason.strip()) < _MIN_REASON
    )


def main() -> int:
    try:
        modules = load_modules()
    except RawSqlError as exc:
        print(f"FAIL check_raw_sql: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []
    problems.extend(forbidden_sink_uses(modules))

    findings = audit(modules)
    if not sql_sites_exist(modules):
        print(
            "FAIL check_raw_sql: found no `text(...)` call anywhere. Statement discovery "
            "is broken — fix it rather than believing the clean report.",
            file=sys.stderr,
        )
        return 2

    problems.extend(thin_reasons())
    problems.extend(
        f"{site}: allowance no longer matches a finding" for site in stale_allowances(findings)
    )
    problems.extend(str(f) for f in findings if f.site not in SPLICE_ALLOWANCES)

    if problems:
        print(
            "FAIL check_raw_sql — SQL built from something other than our own source:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  Bind values as `:name` parameters. If the splice is an IDENTIFIER, put it "
            "through `_identifier()`. If it is a fragment passed by callers, the callers "
            "must pass literals — this check reads them.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK check_raw_sql: {sum(len(sql_sites(m)) for m in modules)} SQL statements, "
        "all literal-derived"
    )
    return 0


def sql_sites_exist(modules: list[Module]) -> bool:
    return any(sql_sites(module) for module in modules)


if __name__ == "__main__":
    raise SystemExit(main())
