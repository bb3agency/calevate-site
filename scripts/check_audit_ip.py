"""Guardrail: `audit_log.ip` records the CALLER, and only one function may decide who that is.

SEC-COMP §5 asks every audit row to carry "actor, tenant, at, ip". For most of this
repo's life the fourth field was satisfied in SHAPE ONLY: eighty handlers wrote

    ip=request.client.host if request.client else None

inline into `write_audit(...)`, and behind nginx `request.client.host` is the proxy. So
the evidentiary column that answers "where did this act come from?" recorded our own edge
on every audited route — one copy of the defect per route, none of them wrong-looking.

D-131 fixed the definition (`core.auth.client_request_ip`, over the promoted
`calevate_shared.client_address.client_ip` that voice-runtime already used to authenticate
an unsigned engine by source address). D-139 swept the eighty callers. This check is what
makes the sweep durable, and it exists because the alternative was a grep in a docstring —
a worklist is a promise, and a check is a guarantee.

WHY A SCRIPT AND NOT A TEST. The property is decidable from syntax with no database, no
app boot and no network, which is this repo's line for `scripts/check_*` (the same reason
`check_model_residency` is a script and the §52 surface guard is a vitest). It also has to
run over files that no test imports.

TWO CHECKS, because there are two ways to lose the property:

1. **No handler reads the socket peer.** A peer read anywhere under `apps/api` outside the
   permitted functions is the defect returning. Not `ip=` specifically: the next author
   will spell it differently, and what is actually wrong is CONSULTING the peer rather
   than the predicate.
2. **The permitted lines are still inside the predicates.** An exception that outlives the
   function it was granted for is a hole with a comment on it, so each allowance names its
   function and fails if that function stops containing the read — which is what would
   happen if somebody "simplified" a resolver back to something else.

**BOTH SPELLINGS OF THE PEER READ, which is what this check missed when it shipped.** Its
own rationale is that the next author will write it differently, and a different spelling
was already in the tree the day it landed: `core/middleware.py` reads the ASGI scope
(`scope.get("client")`) rather than `request.client`, because it runs before a `Request`
object exists. So the AST walk below matches the peer in every form `apps/api` can reach
it — `request.client`, `scope["client"]`, `scope.get("client")` and the same two through
`request.scope` — and grants a SECOND named allowance, to `RateLimitMiddleware.
_address_subject`, on identical grounds to the first. A guard that only knew one spelling
would have passed a handler that stamped `request.scope["client"][0]` into an audit row.

`apps/voice-runtime` is deliberately OUT OF SCOPE and not an oversight: it reads the peer
to decide whether the peer is trusted, which is the same argument-not-answer distinction
the allowances below rest on, and its own suite pins it (`voice_runtime_security_test`).
`apps/workers` is out of scope because it CANNOT hold the defect — verified, not assumed:
it has no `Request`, no ASGI scope, and no `write_audit` call at all (the post-call
pipeline's provenance is the engine's execution id, not a caller address).

Run: `uv run python -m scripts.check_audit_ip`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SCOPE: Final = REPO_ROOT / "apps" / "api"

#: The places `apps/api` may read the socket peer, and why. In both, `client_ip` takes the
#: peer as an ARGUMENT and decides whether it is a trusted proxy before believing any
#: header it sent — the read is an input to the judgement, not a substitute for it. Each
#: entry is `(file, function)`: bound to the FUNCTION, so moving the read one function
#: down does not inherit the exception, and every entry must still be present (below).
PERMITTED: Final[tuple[tuple[Path, str], ...]] = (
    (SCOPE / "core" / "auth.py", "client_request_ip"),
    # Runs before routing, so there is no `Request` to ask — hence the ASGI spelling, and
    # hence the second allowance rather than a second definition of "who is calling".
    (SCOPE / "core" / "middleware.py", "_address_subject"),
)
#: Named in the failure message as the remedy.
PERMITTED_FUNCTION: Final = "client_request_ip"


def is_peer_read(node: ast.AST) -> bool:
    """True for every way a FastAPI/ASGI handler can reach the socket peer.

    PUBLIC, and imported by `scripts/check_idempotency_scope.py` — "one way per problem".
    That check bans the peer from a different destination (an idempotency scope, a dedupe
    key) across a wider tree (`apps/voice-runtime` and `apps/workers` too), but "what
    counts as reading the peer" is one question and must not grow a second answer; the
    day somebody teaches this predicate a fourth spelling, both guards learn it.

    Three shapes, one meaning (four counting the two ways `scope` is spelled):
      - `request.client`                        — the `Request` attribute
      - `scope["client"]` / `request.scope[...]` — the ASGI mapping, subscripted
      - `scope.get("client")` / `request.scope.get(...)` — the same, defensively

    The mapping forms are recognised only on something SPELLED `scope` (a bare name, or an
    attribute access ending in `.scope`), so an unrelated dict with a `"client"` key is not
    a finding. AST rather than a regex so the prose explaining this rule — which
    `core/auth.py`, `core/middleware.py` and this file all contain — is not one either.
    """
    if isinstance(node, ast.Attribute) and node.attr == "client":
        return isinstance(node.value, ast.Name) and node.value.id == "request"
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == "client" and _is_scope(node.value)
    if isinstance(node, ast.Call):
        func = node.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and _is_scope(func.value)
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "client"
        )
    return False


def _is_scope(node: ast.AST) -> bool:
    """`scope`, or anything's `.scope` — the two ways the ASGI mapping is named here."""
    if isinstance(node, ast.Name):
        return node.id == "scope"
    return isinstance(node, ast.Attribute) and node.attr == "scope"


def _peer_reads(tree: ast.AST) -> list[tuple[int, str | None]]:
    """Every socket-peer read, with the enclosing function's name."""
    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if is_peer_read(child):
                    enclosing[id(child)] = node.name

    # `ast.expr`, not `ast.AST`: every shape `is_peer_read` matches is an expression, so
    # `lineno` is guaranteed — `ast.AST` alone does not carry position information.
    return [
        (node.lineno, enclosing.get(id(node)))
        for node in ast.walk(tree)
        if isinstance(node, ast.expr) and is_peer_read(node)
    ]


def main() -> int:
    problems: list[str] = []
    seen: set[tuple[Path, str]] = set()

    for path in sorted(SCOPE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a broken file fails its own gate
            problems.append(f"{path.relative_to(REPO_ROOT).as_posix()}: could not parse ({exc})")
            continue

        for lineno, function in _peer_reads(tree):
            if function is not None and (path, function) in PERMITTED:
                seen.add((path, function))
                continue
            problems.append(
                f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno} reads the socket peer "
                f"in `{function or '<module>'}` — behind nginx that is the PROXY, not the "
                f"caller. Use `core.auth.{PERMITTED_FUNCTION}(request)`, which asks "
                f"whether the peer is a trusted proxy before believing its headers "
                f"(SEC-COMP §5, D-131/D-139)."
            )

    for file, function in PERMITTED:
        if (file, function) in seen:
            continue
        problems.append(
            f"`{function}` in {file.relative_to(REPO_ROOT).as_posix()} no longer reads the socket "
            "peer. Either it stopped resolving the caller — in which case the address it "
            "answered for is now decided somewhere this check cannot see — or it moved, "
            "and this allowance must move with it. An exception that outlives its reason "
            "is a hole with a comment on it."
        )

    if problems:
        print("AUDIT IP: FAIL")
        for line in problems:
            print(f"  - {line}")
        return 1

    named = ", ".join(function for _, function in PERMITTED)
    print(f"AUDIT IP: OK (callers of the socket peer: {named})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
