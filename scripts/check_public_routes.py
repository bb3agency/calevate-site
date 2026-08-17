"""Guardrail: the UNAUTHENTICATED surface is enumerated, not inherited (D-173).

`core/rbac.assert_policy_registry_complete` is the strongest check in this repo: at boot,
on the live route table, every route must DECLARE a permission and actually ENFORCE it.
It has one blind spot, and it is structural — it starts by skipping everything under
`PUBLIC_PREFIXES`:

    if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        continue

A prefix is default-OPEN for everything that lands under it later. `/v1/auth/` holds one
route today; the first-party auth module — designed, and landing in a parallel slice — adds
login, refresh, logout, password reset, OTP request and verify, and invite setup, and every
one of them would be exempt from the registry the moment it is mounted, with nothing
anywhere that noticed.
That is not a hypothetical failure mode: it is the shape the reference repository this
check was written from ended up in, where `AUTH_ADMIN_EXEMPT_ROUTES` grew to twelve
hand-commented entries that nothing ever re-read
(`docs/evidence/raghava-platform-teardown.md` §2).

So this check turns the prefix into an ENUMERATION. Five questions, all against the live
app rather than against a list of what we remember:

1. **Every exempt route is declared** in `UNAUTHENTICATED_ROUTES`, by method and path,
   with a reason. A new route under a public prefix fails CI until somebody writes down
   why the world may call it. That is the whole point: the cost of opening a route moves
   from zero to one reviewed line.
2. **Every declaration matches a live exempt route.** The registry may only shrink. An
   entry that outlives its route is worse than useless — it is a standing permission
   waiting for a path to be reused.
3. **Every `PUBLIC_PREFIXES` entry covers at least one live route.** A prefix that matches
   nothing is a false statement about the surface, and it is a trap: it exempts, silently,
   whatever is mounted under it next.
4. **Every MUTATING exempt route names the credential it checks instead**, and that
   credential is verified to be present in the module that defines the handler. Every one
   of ours has one — an HMAC, a Svix signature, a per-source shared secret, or a verified
   token with no membership yet — and this is the clause that makes the registry a claim
   rather than a comment. It is the same move `check_redaction_exposure` makes when it
   verifies its own allowlist's promises against the live app.
5. **No exempt route also declares `x-calevate-permission`.** The declaration would be
   pure decoration — the registry never reads it — and it reads as protection in the
   OpenAPI schema, the generated TypeScript client and any review that greps for
   `permission_meta`. Either the route is public and the label goes, or it is not and the
   route moves out of the prefix.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
* **It does not re-check the guarded routes.** `assert_policy_registry_complete` owns
  that and runs at boot on every process; a second implementation of the same rule is the
  defect CLAUDE.md's "one way per problem" names. This is its complement, and the two
  partition the route table between them with no overlap.
* **It does not judge whether a credential is STRONG.** Whether the Svix verification is
  constant-time, whether the ingest secret is long enough, whether Razorpay's HMAC covers
  the right bytes — those are questions for the module's own tests
  (`tests/api_security_test.py`, `tests/ingest_*`), and a static check that pretended to
  answer them would be answering from a name.
* **`apps/voice-runtime` is not in scope.** Its whole surface is unauthenticated-by-design
  webhooks under hard rule 3, verified by source-IP allowlist and execution-id dedupe; it
  is a separate app with a separate boundary, and `check_wiring` is what watches it.

Run: `uv run python -m scripts.check_public_routes`
"""

from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cost is paid only when the check runs
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MIN_REASON = 40


@dataclass(frozen=True, slots=True)
class PublicRoute:
    """One route the world may call, and what stands in for a session.

    `credential` names a symbol that must appear in the handler's own module. It is not a
    signature of the check — it is the promise this row makes, checked. `None` means the
    route is genuinely open, which is only tolerable for a GET that discloses nothing.
    """

    why: str
    credential: str | None = None


#: The complete unauthenticated surface of `apps/api`. Adding a row is the reviewable act
#: this check exists to force; nothing may be exempt without one.
UNAUTHENTICATED_ROUTES: dict[str, PublicRoute] = {
    "GET /healthz": PublicRoute(
        why=(
            "Liveness word and status code only. `core/health` gates every detail behind "
            "`ops:manage` itself, so the open half discloses nothing an attacker can use."
        )
    ),
    "GET /healthz/live": PublicRoute(
        why=(
            "The process-is-up probe the container runtime calls before any credential "
            "store is reachable; requiring auth here makes an outage unrecoverable."
        )
    ),
    "GET /healthz/ready": PublicRoute(
        why=(
            "Readiness for the load balancer, same reasoning as /healthz/live. Detail is "
            "behind `ops:manage`; this answers ready or not-ready and nothing else."
        )
    ),
    "POST /hooks/v1/clerk": PublicRoute(
        why=(
            "Identity-mirror webhook. Clerk cannot hold one of our sessions, so the Svix "
            "signature over the raw body IS the credential; it fails CLOSED when the "
            "webhook secret is unset, because an unverifiable identity feed would let "
            "anyone create rows in the table RLS keys membership off."
        ),
        credential="verify_svix",
    ),
    "POST /hooks/v1/razorpay": PublicRoute(
        why=(
            "Payment-captured webhook. HMAC over the raw bytes before anything is parsed "
            "and before any row is written, and it fails CLOSED when the secret is unset "
            "— an unverifiable payment feed credits wallets on anyone's say-so."
        ),
        credential="verify_signature",
    ),
    "POST /hooks/v1/ingest/{webhook_id}": PublicRoute(
        why=(
            "Generic lead-source intake (D-23). The webhook id is the routing key and the "
            "per-source shared secret is the credential; an unknown id answers 404 rather "
            "than 401 so a prober cannot enumerate live endpoints."
        ),
        credential="verify_ingest_secret",
    ),
    "GET /hooks/v1/ingest/meta/{webhook_id}": PublicRoute(
        why=(
            "Meta's subscription handshake, which must echo `hub.challenge` verbatim as "
            "plain text. It is a GET that writes nothing and is answered only when the "
            "presented verify token matches the source's current secret."
        ),
        credential="_meta_config",
    ),
    "POST /hooks/v1/ingest/meta/{webhook_id}": PublicRoute(
        why=(
            "Meta Lead Ads delivery. Body is bounded first, then the app-secret signature "
            "is verified over the raw bytes, and only then is anything parsed — an "
            "unauthenticated caller must not decide how much we allocate."
        ),
        credential="verify_signature",
    ),
    "POST /v1/auth/signup": PublicRoute(
        why=(
            "Self-serve tenant creation (D-34). Authenticated but membership-LESS by "
            "design: the caller holds a verified realm token and the request is what "
            "creates the organization a permission check would need to exist first."
        ),
        credential="current_identity",
    ),
    "POST /v1/invitations/accept": PublicRoute(
        why=(
            "Accepting an invitation is what CREATES the membership a permission check "
            "would require, so it cannot require one. The verified token identifies the "
            "caller and the single-use invitation token authorizes the join."
        ),
        credential="current_identity",
    ),
}


class PublicRouteError(RuntimeError):
    """The check could not be run — a broken premise, not a verdict."""


def build_app() -> FastAPI:
    """The live app, imported the way `check_openapi_fresh` imports it: inside a
    function, so `--help` and an import of this module cost no bootstrap."""
    from apps.api.main import app

    return app


def exempt_routes(app: FastAPI) -> dict[str, APIRoute]:
    """`"METHOD /path"` -> route, for exactly the routes the RBAC registry skips.

    The prefix test is READ FROM `rbac` rather than restated here. Restating it is how the
    two would drift apart, and the direction of that drift is a route this check believes
    is guarded while the registry believes it is public.
    """
    from apps.api.core.rbac import PUBLIC_PREFIXES, iter_api_routes

    found: dict[str, APIRoute] = {}
    for route in iter_api_routes(app):
        if not any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        for method in sorted(route.methods or []):
            found[f"{method} {route.path}"] = route
    return found


def undeclared(exempt: dict[str, APIRoute]) -> list[str]:
    """Question 1. A route the world may call that nobody wrote down."""
    return sorted(
        f"{key} is exempt from the RBAC registry and is in no UNAUTHENTICATED_ROUTES entry"
        for key in exempt
        if key not in UNAUTHENTICATED_ROUTES
    )


def stale_declarations(exempt: dict[str, APIRoute]) -> list[str]:
    """Question 2. A declaration outliving its route."""
    return sorted(
        f"{key} is declared public but is not a live exempt route — delete the entry"
        for key in UNAUTHENTICATED_ROUTES
        if key not in exempt
    )


def empty_prefixes(exempt: dict[str, APIRoute]) -> list[str]:
    """Question 3. A prefix that exempts nothing today and everything tomorrow."""
    from apps.api.core.rbac import PUBLIC_PREFIXES

    covered = {key.split(" ", 1)[1] for key in exempt}
    return sorted(
        f"PUBLIC_PREFIXES entry {prefix!r} matches no live route — it is a standing "
        "exemption for whatever is mounted under it next"
        for prefix in PUBLIC_PREFIXES
        if not any(path.startswith(prefix) for path in covered)
    )


def unbacked_credentials(exempt: dict[str, APIRoute]) -> list[str]:
    """Question 4. The registry's own promise, checked against the handler's module.

    A NAME rather than a call graph on purpose: the question here is "does the module that
    serves this route REFERENCE the verification this row claims", which is decidable and
    fails loudly on a rename. Whether the verification is correct is the module's tests'
    job, and is said so in the docstring above.
    """
    problems: list[str] = []
    for key, declared in sorted(UNAUTHENTICATED_ROUTES.items()):
        route = exempt.get(key)
        if route is None:
            continue  # `stale_declarations` already named it.
        method = key.split(" ", 1)[0]
        if declared.credential is None:
            if method in _MUTATING:
                problems.append(
                    f"{key} mutates and names no credential — an unauthenticated write "
                    "needs something standing in for a session"
                )
            continue
        if declared.credential not in _referenced_names(route):
            problems.append(
                f"{key} claims {declared.credential!r} as its credential, which is not "
                f"referenced by {getattr(route.endpoint, '__module__', '?')}"
            )
    return problems


def _referenced_names(route: APIRoute) -> frozenset[str]:
    """Every name the handler's module actually REFERENCES, off the AST.

    A substring search over the source would be satisfied by a comment or a docstring
    mentioning the verifier — which is exactly the weakness this check was written from
    (`route-discipline-check.js` regexes the route config's source text, so a commented-out
    guard reads as a guard). Names, attributes and imports only; prose does not count.
    """
    module = inspect.getmodule(route.endpoint)
    if module is None:  # pragma: no cover - every handler here is a module-level def
        raise PublicRouteError(f"cannot locate the module serving {route.path}")
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return frozenset(names)


def decorated_but_unenforced(exempt: dict[str, APIRoute]) -> list[str]:
    """Question 5. A permission label on a route the registry never reads."""
    return sorted(
        f"{key} declares permission {(route.openapi_extra or {})['x-calevate-permission']!r} "
        "but is under a public prefix, so the registry never checks it — the label reads "
        "as protection in the OpenAPI schema and the generated client"
        for key, route in exempt.items()
        if (route.openapi_extra or {}).get("x-calevate-permission")
    )


def thin_reasons() -> list[str]:
    return sorted(
        f"{key}: reason is {len(entry.why.strip())} characters; {_MIN_REASON} is the floor"
        for key, entry in UNAUTHENTICATED_ROUTES.items()
        if len(entry.why.strip()) < _MIN_REASON
    )


def audit(app: FastAPI) -> list[str]:
    """Every way the unauthenticated surface currently disagrees with its declaration."""
    exempt = exempt_routes(app)
    if not exempt:
        raise PublicRouteError(
            "no exempt routes found. Either PUBLIC_PREFIXES is empty or route discovery "
            "is broken — a clean report from a check that found nothing to check is not a "
            "clean report."
        )
    return [
        *undeclared(exempt),
        *stale_declarations(exempt),
        *empty_prefixes(exempt),
        *unbacked_credentials(exempt),
        *decorated_but_unenforced(exempt),
        *thin_reasons(),
    ]


def main() -> int:
    try:
        problems = audit(build_app())
    except PublicRouteError as exc:
        print(f"FAIL check_public_routes: {exc}", file=sys.stderr)
        return 2

    if problems:
        print(
            "FAIL check_public_routes — the unauthenticated surface is not what we say:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  Either guard the route (`Depends(requires(...))` + `permission_meta(...)`) "
            "or add an UNAUTHENTICATED_ROUTES entry saying why the world may call it and "
            "what it verifies instead.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK check_public_routes: {len(UNAUTHENTICATED_ROUTES)} unauthenticated routes, "
        "all declared and backed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
