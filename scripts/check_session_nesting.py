"""Guardrail: how many pooled connections ONE task may hold at once (D-182).

`apps/api/db/session.py` sizes the pool with `max_overflow` at exactly the depth this
check enforces, so the number here and the number there are one decision written twice
and must not drift. The pool is `pool_size=DB_POOL_SIZE, max_overflow=1`: N persistent
connections plus one burst slot. That single slot is what makes a NESTED checkout safe —
a task that already holds a session and opens a second one cannot deadlock against a pool
at its ceiling, because one of the waiters always gets the overflow, finishes its short
inner read and releases. It is enough for depth 2 and it is not enough for depth 3:
three-deep nesting on a saturated pool is a self-deadlock that ends in `QueuePool limit
reached` for every task at once, five seconds apart.

So the invariant is not "one session at a time" — the comment `session.py` used to carry,
and which two paths already broke on the day it was written — but:

    NO TASK HOLDS MORE THAN TWO POOLED CONNECTIONS AT ONCE.

WHY A SCRIPT AND NOT A TEST. The property is decidable from syntax — no database, no app
boot, no network — which is this repo's line for `scripts/check_*` (`check_audit_ip` and
`check_model_residency` make the same argument). It also has to see files no test imports.

HOW IT DECIDES. Every function under `apps/` is given a COST: the largest number of
connections it can hold simultaneously, counting the session context managers it opens
lexically plus, inside each such block, the cost of everything it calls from within it.
The cross-module chain is the point — `check_dispatch` → `get_platform_status` →
`_read_durable` → `untenanted_session` is invisible to any single-file reader, and it is
one of the two legitimate depth-2 paths.

CALLS ARE RESOLVED THROUGH THE IMPORTS, not by bare name. The first draft matched on the
callee's name alone and it was useless: `thread.start()` resolved to `agents.experiments.
start`, `match.start()` to the same, and the tree came back three-deep everywhere. So a
call is followed only when this file can say WHICH function it reaches — a name imported
into the calling module, a function defined in it, `module_alias.function` for an alias
this file imported, or `self.method` inside the same class.

WHAT IT CANNOT SEE, and what that costs: a callable held in a variable, a `getattr`, or a
job handed to the queue (a different task, therefore a different budget — correctly out of
scope). Nothing on a session path in this tree does the first two; if that changes, the
check goes QUIET rather than wrong, which is why the depth-2 chains are printed on success
as well as on failure. A reader who sees the census shrink knows to look.

Run: `uv run python -m scripts.check_session_nesting`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SCOPE: Final = REPO_ROOT / "apps"

#: The one number, and it is `max_overflow + 1` from `db/session.py`.
MAX_DEPTH: Final = 2

#: Every context manager in `apps/api/db/session.py` that checks a connection out.
#: Kept in step with that file by `tests/session_nesting_guard_test.py`, which reads its
#: `@asynccontextmanager` definitions and fails if one is missing here — a new opener this
#: list did not know would make the whole check silently under-report (`credential_session`
#: arrived from D-177 while D-182 was being written, which is how that test came to exist).
SESSION_OPENERS: Final[frozenset[str]] = frozenset(
    {
        "tenant_session",
        "untenanted_session",
        "user_session",
        "invite_session",
        "ingest_config_session",
        "credential_session",
        "admin_session",
    }
)

#: `engine.begin()` — a connection that does not come from `session.py`'s helpers.
#: `reliability.claim_outbox_batch` is its only user in app code and it is deliberate (the
#: claim must commit independently of its caller's transaction), which is exactly why it
#: has to be counted: it is one of the two legitimate depth-2 chains.
ENGINE_RECEIVER_HINT: Final = "engine"

#: `session.py` DEFINES the openers; analysing its bodies would count the primitive twice.
DEFINITION_FILE: Final = SCOPE / "api" / "db" / "session.py"

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
#: (module, function) — the key a call resolves to.
Ref = tuple[str, str]


def _module_name(path: Path, base: Path) -> str:
    """Dotted module for a file, in the spelling its importers use.

    `apps/voice-runtime` is not an importable package (the hyphen), so uvicorn runs it
    with `--app-dir` and its siblings import each other as top-level modules —
    `from webhook_routes import router`. Naming them the same way here is what lets a call
    into that service resolve at all.

    `base` is the directory the dotted name is rooted at — the repo for the real tree, a
    tmp directory for the negative controls in `tests/session_nesting_guard_test.py`,
    which is the only reason it is a parameter.
    """
    if path.parent.name == "voice-runtime":
        return path.stem
    return ".".join(path.relative_to(base).with_suffix("").parts)


def _depends_argument(node: ast.expr | None) -> ast.expr | None:
    """The callable inside a `Depends(...)`, wherever it is written.

    Three spellings reach one meaning, and a check that knew only the first would have
    missed every route in `crm/routes.py`:
      - `x = Depends(db)`                        — the default
      - `Annotated[AsyncSession, Depends(db)]`   — inline on the parameter
      - `Session = Annotated[AsyncSession, Depends(db)]` — the module-level alias, which
        is what this repo actually writes (`crm/routes.py:74`)
    """
    if node is None:
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends":
        return node.args[0] if node.args else None
    if isinstance(node, ast.Subscript):
        elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        for element in elements:
            found = _depends_argument(element)
            if found is not None:
                return found
    return None


class _Module:
    """One file's functions and the names it can reach."""

    def __init__(self, name: str, tree: ast.Module) -> None:
        self.name = name
        self.functions: dict[str, FunctionNode] = {}
        #: local name -> (module, function) for `from x import f` / `from x import f as g`
        self.imported_functions: dict[str, Ref] = {}
        #: local name -> module for `import x.y as z` / `from x import y` (y a module)
        self.imported_modules: dict[str, str] = {}
        #: `Session = Annotated[AsyncSession, Depends(db)]` — the spelling every route
        #: module actually uses. The dependency hides in a type alias, not in a default.
        self.annotated_dependencies: dict[str, ast.expr] = {}
        self._index(tree)

    def _index(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Flat by simple name: a module with two same-named methods on different
                # classes would merge, which over-reports (safe) rather than under.
                self.functions.setdefault(node.name, node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imported_modules[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                dependency = _depends_argument(node.value)
                if isinstance(target, ast.Name) and dependency is not None:
                    self.annotated_dependencies[target.id] = dependency
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    local = alias.asname or alias.name
                    # `from apps.api.integrations import service` imports a MODULE; the
                    # ambiguity is resolved at lookup time by trying both.
                    self.imported_functions[local] = (node.module, alias.name)
                    self.imported_modules[local] = f"{node.module}.{alias.name}"


class _Analyzer:
    def __init__(self) -> None:
        self.modules: dict[str, _Module] = {}
        self._memo: dict[tuple[Ref, bool], tuple[int, list[str]]] = {}
        self._in_progress: set[Ref] = set()

    def add_file(self, path: Path, tree: ast.Module, base: Path = REPO_ROOT) -> None:
        if path == DEFINITION_FILE:
            return
        module = _module_name(path, base)
        self.modules[module] = _Module(module, tree)

    # -- resolution ---------------------------------------------------------------

    def _resolve(self, module: str, call: ast.Call) -> Ref | None:
        """Which function this call reaches, or None when this file cannot say."""
        here = self.modules.get(module)
        if here is None:
            return None
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in here.functions:
                return (module, func.id)
            target = here.imported_functions.get(func.id)
            if target is not None and target[1] in self.modules.get(target[0], _EMPTY).functions:
                return target
            return None
        if isinstance(func, ast.Attribute):
            receiver = func.value
            if isinstance(receiver, ast.Name):
                if receiver.id == "self" and func.attr in here.functions:
                    return (module, func.attr)
                other = here.imported_modules.get(receiver.id)
                if other is not None and func.attr in self.modules.get(other, _EMPTY).functions:
                    return (other, func.attr)
        return None

    def _is_opener(self, module: str, node: ast.expr) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name) and func.id in SESSION_OPENERS:
            return True
        if isinstance(func, ast.Attribute):
            if func.attr in SESSION_OPENERS:
                return True
            if func.attr == "begin":
                return ENGINE_RECEIVER_HINT in ast.unparse(func.value)
        return False

    # -- costing ------------------------------------------------------------------

    def cost(self, ref: Ref, *, injected: bool = True) -> tuple[int, list[str]]:
        """(connections held at once, the chain that reaches that depth).

        `injected` charges the caller for a session FastAPI opened around it, and it is
        false when this function is reached as a CALLEE: calling a route handler directly
        (`get_agent` calls `list_agents`) passes the session along as an argument — the
        dependency does not run a second time, and charging it twice would invent a depth
        the process cannot reach.
        """
        key = (ref, injected)
        if key in self._memo:
            return self._memo[key]
        if ref in self._in_progress:
            # Recursion. A cycle that held a connection per level would blow the stack
            # long before it exhausted the pool, so it is costed at its first level only.
            return 0, []
        node = self.modules.get(ref[0], _EMPTY).functions.get(ref[1])
        if node is None:
            return 0, []
        self._in_progress.add(ref)
        depth, chain = self._body_cost(ref[0], node, nested_defs=False)
        held, holder = self._injected_session(ref[0], node) if injected else (0, [])
        self._in_progress.discard(ref)
        self._memo[key] = (depth + held, [ref[1], *holder, *chain])
        return self._memo[key]

    def _injected_session(self, module: str, node: FunctionNode) -> tuple[int, list[str]]:
        """1 if a `Depends(...)` on this signature holds a session for the whole call.

        THE HALF A LEXICAL READER MISSES. A route handler's session is not opened in its
        body — `Depends(deps.db)` opens it before the handler runs and closes it after,
        so every line of the handler executes while holding one connection. Without this,
        `POST /v1/leads/{lead_id}/call` reads as depth 1 while actually being the request
        session plus `check_dispatch`'s durable platform read, which is exactly the pair
        the audit found.
        """
        here = self.modules.get(module, _EMPTY)
        candidates: list[ast.expr] = []
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is None:
                continue
            found = _depends_argument(default)
            if found is not None:
                candidates.append(found)
        for argument in [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]:
            annotation = argument.annotation
            if annotation is None:
                continue
            inline = _depends_argument(annotation)
            if inline is not None:
                candidates.append(inline)
            elif isinstance(annotation, ast.Name) and annotation.id in here.annotated_dependencies:
                candidates.append(here.annotated_dependencies[annotation.id])
        for dependency in candidates:
            ref = self._resolve(module, ast.Call(func=dependency, args=[], keywords=[]))
            if ref is not None and self._yields_inside_a_session(ref):
                return 1, [f"Depends({ref[1]})"]
        return 0, []

    def _yields_inside_a_session(self, ref: Ref) -> bool:
        """Does this dependency keep its session open while the endpoint runs?

        Only a GENERATOR dependency does. `deps.db` opens `tenant_session` and yields
        inside it, so FastAPI holds that connection until the response is built; a plain
        `async def` dependency like `auth.tenant_of` opens and closes whatever it needs
        before the handler starts, and charging the handler for it would be an
        over-report of exactly the kind that makes a guardrail get switched off.
        """
        node = self.modules.get(ref[0], _EMPTY).functions.get(ref[1])
        if node is None:
            return False
        for candidate in ast.walk(node):
            if (
                isinstance(candidate, ast.With | ast.AsyncWith)
                and any(self._is_opener(ref[0], item.context_expr) for item in candidate.items)
                and any(isinstance(inner, ast.Yield) for inner in ast.walk(candidate))
            ):
                return True
        return False

    def _body_cost(self, module: str, node: ast.AST, *, nested_defs: bool) -> tuple[int, list[str]]:
        """Deepest simultaneous holding under `node`.

        A `with` that opens a connection costs 1 + the deepest cost reachable from inside
        its block. A call OUTSIDE such a block costs only its own depth, which is what
        makes the open-close-then-call-the-vendor shape read as depth 1 rather than as a
        finding.
        """
        best = (0, [""])
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and not nested_defs:
                continue  # costed under its own name, when something calls it
            candidate = self._statement_cost(module, child, nested_defs=nested_defs)
            if candidate[0] > best[0]:
                best = candidate
        return best

    def _statement_cost(
        self, module: str, node: ast.AST, *, nested_defs: bool
    ) -> tuple[int, list[str]]:
        """`_body_cost` for a statement INCLUDING itself.

        Split out because the first draft only asked the question of a node's children,
        so `async with tenant_session(...)` wrapping `async with untenanted_session()`
        scored 2 rather than 3 — the check missed the one shape it was written to catch,
        which is why `tests/session_nesting_guard_test.py` builds that exact tree.
        """
        if isinstance(node, ast.With | ast.AsyncWith) and any(
            self._is_opener(module, item.context_expr) for item in node.items
        ):
            inner = (0, [""])
            for statement in node.body:
                for candidate in (
                    self._call_cost(module, statement),
                    self._statement_cost(module, statement, nested_defs=True),
                ):
                    if candidate[0] > inner[0]:
                        inner = candidate
            return (1 + inner[0], inner[1])
        best = self._body_cost(module, node, nested_defs=nested_defs)
        reached = self._call_cost(module, node, shallow=True)
        return reached if reached[0] > best[0] else best

    def _call_cost(
        self, module: str, node: ast.AST, *, shallow: bool = False
    ) -> tuple[int, list[str]]:
        """Costliest call under `node`. `shallow` stops at a connection-opening `with`,
        which `_body_cost` has already costed — counting it twice would double it."""
        best = (0, [""])
        if (
            shallow
            and isinstance(node, ast.With | ast.AsyncWith)
            and any(self._is_opener(module, item.context_expr) for item in node.items)
        ):
            return best
        if isinstance(node, ast.Call):
            if self._is_opener(module, node):
                best = (1, [""])
            else:
                ref = self._resolve(module, node)
                if ref is not None:
                    best = self.cost(ref, injected=False)
        for child in ast.iter_child_nodes(node):
            deeper = self._call_cost(module, child, shallow=shallow)
            if deeper[0] > best[0]:
                best = deeper
        return best

    def census(self) -> list[tuple[int, str, str]]:
        """(depth, `module.function`, chain) for everything at or over the ceiling."""
        found: list[tuple[int, str, str]] = []
        for module in sorted(self.modules):
            for name in sorted(self.modules[module].functions):
                depth, chain = self.cost((module, name))
                if depth >= MAX_DEPTH:
                    found.append((depth, f"{module}.{name}", " -> ".join(p for p in chain if p)))
        return sorted(found, key=lambda row: (-row[0], row[1]))


_EMPTY: Final = _Module("", ast.parse(""))


def analyze(root: Path, base: Path | None = None) -> _Analyzer:
    """Cost every file under `root`, with dotted module names rooted at `base`."""
    if base is None:
        base = REPO_ROOT if root.is_relative_to(REPO_ROOT) else root
    analyzer = _Analyzer()
    for path in sorted(root.rglob("*.py")):
        try:
            analyzer.add_file(path, ast.parse(path.read_text(encoding="utf-8")), base)
        except SyntaxError as exc:  # pragma: no cover - a broken file fails its own gate
            print(f"SESSION NESTING: could not parse {path} ({exc})")
    return analyzer


def main(root: Path = SCOPE, base: Path | None = None) -> int:
    rows = analyze(root, base).census()
    too_deep = [row for row in rows if row[0] > MAX_DEPTH]
    if too_deep:
        print("SESSION NESTING: FAIL")
        for depth, name, chain in too_deep:
            print(
                f"  - `{name}` can hold {depth} pooled connections at once ({chain}). The "
                f"pool allows {MAX_DEPTH} (`db/session.py`: pool_size + max_overflow=1), so "
                "under saturation every task at this depth waits for a connection only "
                "another task at this depth can release. Close the outer session before the "
                "inner one opens, or read the inner value first and pass it in."
            )
        return 1
    # Grouped by WHAT the second connection is, not by which of the fifty entry points
    # reaches it: the entry points change every week and the mechanisms do not, so a
    # per-function list would be noise that hides the one line worth reading — the day a
    # new mechanism appears in this census.
    reasons = sorted({chain.split(" -> ")[1] for _, _, chain in rows if " -> " in chain})
    print(
        f"SESSION NESTING: OK (ceiling {MAX_DEPTH}; {len(rows)} function(s) at it, "
        f"via: {', '.join(reasons) or 'none'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
