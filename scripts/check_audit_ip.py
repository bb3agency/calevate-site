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

1. **No handler reads the socket peer.** `request.client` anywhere under `apps/api`
   outside the one permitted line is the defect returning. Not `ip=` specifically: the
   next author will spell it differently, and what is actually wrong is CONSULTING the
   peer rather than the predicate.
2. **The permitted line is still inside the predicate.** An exception that outlives the
   function it was granted for is a hole with a comment on it, so the allowance names the
   function and fails if `client_request_ip` stops containing it — which is what would
   happen if somebody "simplified" the resolver back to a peer read.

`apps/voice-runtime` is deliberately OUT OF SCOPE and not an oversight: it reads the peer
to decide whether the peer is trusted, which is the same argument-not-answer distinction
the allowance below rests on, and its own suite pins it (`voice_runtime_security_test`).

Run: `uv run python -m scripts.check_audit_ip`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SCOPE: Final = REPO_ROOT / "apps" / "api"

#: The ONE place `apps/api` may read the socket peer, and why. `client_ip` takes the peer
#: as an ARGUMENT and decides whether it is a trusted proxy before believing any header it
#: sent — so the read is an input to the judgement, not a substitute for it.
PERMITTED_FUNCTION: Final = "client_request_ip"
PERMITTED_FILE: Final = SCOPE / "core" / "auth.py"


def _peer_reads(tree: ast.AST) -> list[tuple[int, str | None]]:
    """Every `request.client` attribute access, with the enclosing function's name.

    AST rather than a regex so a `request.client` inside a docstring or a comment — of
    which `core/auth.py` has several, explaining this very rule — is not a finding.
    """
    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and child.attr == "client":
                    enclosing[id(child)] = node.name

    found: list[tuple[int, str | None]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "client"
            and isinstance(node.value, ast.Name)
            and node.value.id == "request"
        ):
            found.append((node.lineno, enclosing.get(id(node))))
    return found


def main() -> int:
    problems: list[str] = []
    permitted_seen = False

    for path in sorted(SCOPE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a broken file fails its own gate
            problems.append(f"{path.relative_to(REPO_ROOT)}: could not parse ({exc})")
            continue

        for lineno, function in _peer_reads(tree):
            allowed = path == PERMITTED_FILE and function == PERMITTED_FUNCTION
            if allowed:
                permitted_seen = True
                continue
            problems.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno} reads `request.client` "
                f"in `{function or '<module>'}` — behind nginx that is the PROXY, not the "
                f"caller. Use `core.auth.{PERMITTED_FUNCTION}(request)`, which asks "
                f"whether the peer is a trusted proxy before believing its headers "
                f"(SEC-COMP §5, D-131/D-139)."
            )

    if not permitted_seen:
        problems.append(
            f"`{PERMITTED_FUNCTION}` in {PERMITTED_FILE.relative_to(REPO_ROOT)} no longer "
            "reads `request.client`. Either it stopped resolving the caller — in which "
            "case every audit row's `ip` is now decided somewhere this check cannot see — "
            "or it moved, and this allowance must move with it. An exception that "
            "outlives its reason is a hole with a comment on it."
        )

    if problems:
        print("AUDIT IP: FAIL")
        for line in problems:
            print(f"  - {line}")
        return 1

    print(f"AUDIT IP: OK (one caller of the socket peer: {PERMITTED_FUNCTION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
