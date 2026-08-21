"""Guardrail: an idempotency scope names a PRINCIPAL, never an address or a header.

An idempotency record is a cache of a completed response, keyed on `(scope_key, route,
method, idempotency_key)` (BACKEND-PATTERNS §4, migration `05bba2f3c19c`). Everything
about whether that cache is safe collapses into one question: **can two different callers
ever compute the same scope?** If they can, the second one is served the first one's
stored `response_payload` — a cross-tenant read through a mechanism nobody thinks of as a
read path, and one no RLS policy is in a position to stop, because the replay happens
before any tenant-scoped query runs.

WHERE THIS CAME FROM. A teardown of a reference platform whose idempotency design is
otherwise ours line for line — same tuple, same body hash, same 24h TTL — found its scope
falling back to the client address for an unauthenticated caller:

    if (request.user?.sub)  return `user:${fingerprint(request.user.sub)}`;
    if (cartCookie)         return `cart:${fingerprint(cartCookie)}`;
    return `anon:${fingerprint(request.ip)}`;          // <- the whole finding

Behind nginx or a CDN, `request.ip` is the edge's own address unless the proxy trust
configuration is exactly right, and then every anonymous caller in the world shares one
scope. That is the same defect class `check_audit_ip` exists for — eighty of our handlers
once read the socket peer inline — pointed at a far worse destination: a wrong audit ip is
a bad evidence field, a wrong idempotency scope is caller A receiving caller B's response.

**WE DO NOT HAVE IT** (audited D-175). Our `reliability.scope_key` takes `tenant_id` and
`user_id` as `UUID | None` and has no fallback branch at all; all four `claim_idempotency`
call sites pass ids off a verified `Principal` or off a tenant id resolved from a
signature-verified payment. This check is therefore not a fix — it is the property made
CHECKABLE, which is the deliverable when an audit finds nothing: the reference project's
fallback was also absent once.

FOUR PROPERTIES, because there are four ways to lose it:

1. **`scope_key` keeps its typed, keyword-only signature.** This is the load-bearing one
   and it is not enforced here so much as DECLARED here: because both parameters are
   annotated `UUID | None`, mypy strict already refuses `scope_key(tenant_id=request.
   headers.get("x-tenant"))` at every call site in the repo — a header is a `str`. Widening
   either annotation to `str` would silently retire that guarantee everywhere at once, so
   the widening is what this check fails on.
2. **`scope_key` is the only producer of a scope.** Every `claim_idempotency(..., scope=)`
   resolves to a `scope_key(...)` call — directly, or through one local variable. A literal,
   an f-string or a second helper is how a second scoping rule gets born.
3. **`scope_key`'s arguments are plain id references.** `None`, a name, or an attribute —
   never a CALL, which is the shape `client_request_ip(request)` and `fingerprint(ip)` both
   have, and never a subscript, which is how a header or a cookie is read.
4. **No socket peer reaches ANY replay key.** Not just the idempotency scope: the webhook
   inbox's `(provider, event_key)` and the outbox's `dedupe_key` are replay namespaces
   with the same collision consequence, so the peer is banned from those arguments too.

WHY THIS ISN'T FOLDED INTO `check_audit_ip`. That guard answers "who is the caller?" and
its scope is `apps/api`; this one answers "what may a replay key be derived from?" and has
to reach `apps/voice-runtime` and `apps/workers`, which hold `claim_inbox_event` and
`enqueue_outbox_once` call sites and which `check_audit_ip` deliberately does not scan. The
one thing the two genuinely share — what counts as reading the peer — is IMPORTED from it
rather than restated (`is_peer_read`), so a fourth spelling teaches both guards at once.

WHY A SCRIPT AND NOT A TEST: the same line every `scripts/check_*` sits on — decidable from
syntax, no database, no app boot, and it must cover files no test imports.

Negative controls in `tests/idempotency_scope_guard_test.py`.

Run: `uv run python -m scripts.check_idempotency_scope`  (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Final

from scripts.check_audit_ip import is_peer_read

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

#: Everywhere a replay key can be constructed. Wider than `check_audit_ip`'s `apps/api`
#: on purpose: `enqueue_outbox_once` is called from `apps/workers` and `claim_inbox_event`
#: from `apps/voice-runtime`, and a dedupe key derived from an address would be just as
#: collidable there.
SCOPES: Final[tuple[Path, ...]] = (
    REPO_ROOT / "apps" / "api",
    REPO_ROOT / "apps" / "voice-runtime",
    REPO_ROOT / "apps" / "workers",
    REPO_ROOT / "packages" / "shared",
)

#: The one producer of an idempotency scope, and where its signature lives.
PRODUCER: Final = "scope_key"
PRODUCER_MODULE: Final = REPO_ROOT / "apps" / "api" / "reliability" / "service.py"

#: The signature that makes mypy the first line of defence. Keyword-only, both `UUID |
#: None` — so no `str` (a header, a cookie, an address) can reach it from anywhere.
REQUIRED_PARAMETERS: Final[tuple[tuple[str, str], ...]] = (
    ("tenant_id", "UUID | None"),
    ("user_id", "UUID | None"),
)

#: Every argument that becomes part of a replay namespace, by the function it is passed
#: to. `claim_idempotency`'s `key=` is deliberately ABSENT: the `Idempotency-Key` header is
#: supposed to be the caller's to choose — that is the whole contract — and it is only safe
#: BECAUSE the scope beside it is not. The inbox pair and the outbox key are here because
#: two principals sharing one of them has the same consequence as sharing a scope.
REPLAY_ARGUMENTS: Final[dict[str, tuple[str, ...]]] = {
    "claim_idempotency": ("scope",),
    "claim_inbox_event": ("provider", "event_key"),
    "enqueue_outbox_once": ("dedupe_key",),
}


def _called_name(node: ast.Call) -> str | None:
    """The bare function name of a call, however it was imported (`f`, `mod.f`)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_producer_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _called_name(node) == PRODUCER


def _is_id_reference(node: ast.expr) -> bool:
    """`None`, a name, or a dotted attribute of one — and nothing else.

    What is being excluded is the interesting half. A CALL is how `client_request_ip(
    request)` or `fingerprint(addr)` would arrive; a SUBSCRIPT is how a header or a cookie
    is read; an f-string or a bare string is how somebody spells a scope by hand. All three
    are refused, so what remains is a reference to something the server already resolved.
    """
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_id_reference(node.value)
    return False


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _local_bindings(function: ast.AST) -> dict[str, list[ast.expr]]:
    """Every value a simple local name is assigned in this function.

    Only bare-name targets: an assignment to `obj.attr` or `d[k]` is not a name a call site
    can pass as `scope=`, so tracking it would buy nothing and cost false confidence.
    """
    bindings: dict[str, list[ast.expr]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings.setdefault(target.id, []).append(value)
    return bindings


def _resolves_to_producer(value: ast.expr, bindings: dict[str, list[ast.expr]]) -> bool:
    """The scope is a `scope_key(...)` call, or a local name bound only to such calls.

    ONE HOP, not a fixpoint. `scope = scope_key(...)` is the single indirection the repo
    actually uses (`billing/payment_routes.py`, which must commit the claim before a
    network call and so builds the scope a few lines earlier). Chasing further would mean
    approximating dataflow in a guard whose value is that its answer is obvious; a second
    hop can be added the day a call site needs one, and until then refusing it is the
    safe direction.
    """
    if _is_producer_call(value):
        return True
    if isinstance(value, ast.Name):
        bound = bindings.get(value.id, [])
        return bool(bound) and all(_is_producer_call(expr) for expr in bound)
    return False


def _signature_problems() -> list[str]:
    """Property 1: the annotations that make mypy refuse a header at every call site."""
    # A MISSING FILE IS A FINDING, not a traceback: `reliability/service.py` moving is
    # precisely the case this property exists to catch, and a guard that crashes on its
    # own subject reads to CI as "the check is broken" rather than "the guarantee left".
    try:
        source = PRODUCER_MODULE.read_text(encoding="utf-8")
    except OSError:
        source = ""
    definitions = [f for f in _functions(ast.parse(source)) if f.name == PRODUCER]
    if not definitions:
        return [
            f"{_rel(PRODUCER_MODULE)} no longer defines `{PRODUCER}`. The scope is now "
            "produced somewhere this check cannot see — a green check over an absent "
            "guarantee is worse than a red one."
        ]

    problems: list[str] = []
    for definition in definitions:
        args = definition.args
        positional = [a.arg for a in (*args.posonlyargs, *args.args)]
        if positional:
            problems.append(
                f"{_rel(PRODUCER_MODULE)}:{definition.lineno} `{PRODUCER}` takes positional "
                f"parameters ({', '.join(positional)}). Keyword-only is what stops a caller "
                "swapping tenant and user — or passing one value meaning neither."
            )
        actual = {
            a.arg: ast.unparse(a.annotation) if a.annotation else None for a in args.kwonlyargs
        }
        for name, annotation in REQUIRED_PARAMETERS:
            if actual.get(name) != annotation:
                problems.append(
                    f"{_rel(PRODUCER_MODULE)}:{definition.lineno} `{PRODUCER}` must take "
                    f"`{name}: {annotation}`, not `{name}: {actual.get(name)}`. THE TYPE IS "
                    "THE GUARD: mypy strict refuses a header, a cookie or an address at every "
                    "call site only while this is a UUID, and widening it retires that "
                    "everywhere at once (D-175)."
                )
    return problems


def _rel(path: Path) -> str:
    # `.as_posix()`, never `str()`: on Windows `str()` renders backslashes, so the one
    # thing this gate PRINTS — the file to go and fix — came out in a spelling that
    # matches neither CI's output nor the repo-relative paths every other guard emits.
    # The finding was correct and the report was unusable; three of this gate's own
    # negative controls failed on the separator alone.
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:  # pragma: no cover — every scanned path is under the root
        return path.as_posix()


def _call_problems(path: Path, tree: ast.AST) -> tuple[list[str], int, int]:
    """Properties 2-4 over one file. Returns (problems, claims seen, producers seen)."""
    problems: list[str] = []
    claims = producers = 0

    for function in _functions(tree):
        bindings = _local_bindings(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)

            if name == "claim_idempotency":
                claims += 1
                scope = next((k.value for k in node.keywords if k.arg == "scope"), None)
                if scope is None:
                    problems.append(
                        f"{_rel(path)}:{node.lineno} `claim_idempotency` in `{function.name}` "
                        "passes no `scope=`. Every idempotency record is namespaced by a "
                        f"principal; use `{PRODUCER}(tenant_id=…, user_id=…)`."
                    )
                elif not _resolves_to_producer(scope, bindings):
                    problems.append(
                        f"{_rel(path)}:{node.lineno} `claim_idempotency` in `{function.name}` "
                        f"builds its scope from `{ast.unparse(scope)}` rather than from "
                        f"`{PRODUCER}(...)`. A second way to scope a replay cache is how one "
                        "of them ends up keyed on something a caller can choose."
                    )

            if name == PRODUCER:
                producers += 1
                keywords = {k.arg for k in node.keywords if k.arg is not None}
                expected = {name for name, _ in REQUIRED_PARAMETERS}
                if node.args or keywords != expected:
                    problems.append(
                        f"{_rel(path)}:{node.lineno} `{PRODUCER}` in `{function.name}` is "
                        f"called with {sorted(keywords) or 'positional arguments'}, not "
                        f"exactly {sorted(expected)} as keywords."
                    )
                for keyword in node.keywords:
                    if keyword.arg in expected and not _is_id_reference(keyword.value):
                        problems.append(
                            f"{_rel(path)}:{node.lineno} `{PRODUCER}` in `{function.name}` "
                            f"takes `{keyword.arg}={ast.unparse(keyword.value)}` — not a plain "
                            "id reference. A call, a subscript or a literal here is how an "
                            "address, a header or a cookie becomes the scope two strangers "
                            "share (D-175)."
                        )

            for argument in REPLAY_ARGUMENTS.get(name or "", ()):
                value = next((k.value for k in node.keywords if k.arg == argument), None)
                if value is None:
                    continue
                if any(is_peer_read(child) for child in ast.walk(value)):
                    problems.append(
                        f"{_rel(path)}:{node.lineno} `{name}` in `{function.name}` derives "
                        f"`{argument}=` from the socket peer. Behind nginx that is OUR OWN "
                        "EDGE, so every caller shares one replay namespace and the second one "
                        "is served the first one's stored response (D-175, and the same read "
                        "`check_audit_ip` bans from `audit_log.ip`)."
                    )

    return problems, claims, producers


def main() -> int:
    problems = _signature_problems()
    claims = producers = 0

    for scope in SCOPES:
        for path in sorted(scope.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:  # pragma: no cover — a broken file fails its own gate
                problems.append(f"{_rel(path)}: could not parse ({exc})")
                continue
            found, seen_claims, seen_producers = _call_problems(path, tree)
            problems.extend(found)
            claims += seen_claims
            producers += seen_producers

    # THE MUST-BITE ASSERTION, on `check_audit_ip`'s doctrine that an allowance which
    # outlives its reason is a hole with a comment on it — here applied to the check
    # itself. A tree with no `claim_idempotency` call sites passes every rule above
    # vacuously, and the likeliest cause is not that idempotency was deleted but that it
    # moved somewhere `SCOPES` does not reach.
    if not claims or not producers:
        problems.append(
            f"found {claims} `claim_idempotency` and {producers} `{PRODUCER}` call site(s) "
            f"under {', '.join(_rel(s) for s in SCOPES)}. Zero of either means this check "
            "passed without examining anything — either the machinery moved out of these "
            "roots, or it was renamed and this guard was left behind."
        )

    if problems:
        print("IDEMPOTENCY SCOPE: FAIL")
        for line in problems:
            print(f"  - {line}")
        return 1

    print(
        f"IDEMPOTENCY SCOPE: OK ({claims} claim site(s), {producers} `{PRODUCER}` call(s); "
        "no replay key is derived from an address or a header)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
