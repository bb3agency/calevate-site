"""Guardrail: hard rule 5 — the compliance invariants, asserted over the whole tree.

D-29 listed `check:compliance-invariants` to land "with the milestone that creates the
surface". That surface is now unmistakably here: on top of DNC, calling hours and the
disclosure line, the gate has grown the KYC hold, the first-campaign review, consent
provenance, messaging consent and the TM/PE registration reads. Hard rule 5 has been
enforced up to now by tests that assert EXAMPLES — a capped tenant, a revoked template, a
purchased list. Every one of those proves that a known path refuses a known input. None
of them can say anything about the path somebody adds next week, and the path somebody
adds next week is the whole failure mode: TRAI does not fine us for the dial we tested.

So this file asks its questions the way `tests/impersonation_reads_test.py` asks about
D-22 and `scripts/check_wiring.py` asks about half-wired features — against a REGISTRY of
what actually exists, never against a list of the paths we happen to remember:

1. **The chokepoint holds.** `VoiceEngine.start_outbound_call` is reached from exactly
   one place outside the vendor adapters: `agents.service.dispatch_call`. Everything
   downstream of this file's other questions is worthless if a module can dial around it.
2. **Every dial passes the gate, and OBEYS it.** For each call of `dispatch_call`, some
   enclosing function must call `check_dispatch`/`assert_dispatch_allowed` BEFORE it and
   act on the answer. The second half is the part a name-scan cannot do: `check_dispatch`
   deliberately RETURNS a decision instead of raising (so a UI can explain a disabled
   button — SURFACES §2b), which means naming it and dialling anyway type-checks, passes
   review, and rings the phone. `tests/compliance_audit_test.py` proves the first half
   per function; this proves the second and does it over the enclosing-function chain, so
   a dial inside a closure or a nested helper cannot slip between the two.
3. **Every business-initiated message evidences an opt-in.** SEC-COMP §4: messaging
   consent "is its own permission, and it is never inferred". Meta's Business Messaging
   Policy requires an affirmative opt-in whose timestamp and source we can produce on
   challenge; DPDP §6 binds it to its purpose. `Destination.opt_in_at` is where that
   evidence becomes a fact in this codebase, so every send site must consult it first.
4. **No bypass exists.** Hard rule 5 forbids a gate bypass "for testing" — and it arrives
   in two shapes. A PARAMETER (`skip_gate`, `force`, `for_testing`) on the gate-bearing
   surface, which `tests/campaign_dispatch_audit_test.py` already checks for the campaign
   dispatcher alone; and an ENVIRONMENT CHECK inside the gate, which nothing checked at
   all and which does not look like a bypass — `if settings.app_env != "production"` is
   how a staging convenience becomes a production hole.
5. **The schema still carries the invariants the code assumes.** `disclosure_line` NOT
   NULL and non-empty (SEC-COMP §2.1); the `dnc_list` unique key that `add_to_dnc`'s
   `ON CONFLICT` needs, without which an in-call opt-out raises instead of registering;
   and the CHECK that stops a `messaging` consent row omitting its source. Read from
   `pg_catalog`, because a migration is a claim and the catalog is the fact — the same
   argument `check_rls_coverage` makes.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
* **Ledger immutability is not re-implemented here.** Hard rule 4 is fully covered by
  `scripts/check_ledger_immutability.py` — source scan plus a live check that each
  ledger's trigger is enabled and actually raises. A second implementation of that rule
  would be the "two ways of doing one thing" CLAUDE.md calls a defect even when both
  work, and the copy is where the drift starts. Consent, audit and usage ledgers are
  compliance invariants; they are checked THERE.
* **Transcript redaction** is `check_redaction_exposure`'s question (hard rule 5's other
  clause), against the live OpenAPI. Not duplicated for the same reason.
* **No rule-name drift check against SECURITY-COMPLIANCE.md.** Every blocker string in
  §3 could be diffed against the ones the code emits, and it would be useful — but that
  is `check:docs-drift`, which D-29 lists as its own guardrail for M2. Building half of
  it here would leave two checks that disagree about who owns the answer.
* **No claim that the launch path is gated.** "Campaign-launch path calls the compliance
  gate" is asserted where it can be asserted with meaning: `campaigns_test.py` (the gate
  refuses each blocker) and `campaign_dispatch_audit_test.py` (the claiming function
  names `dispatch_blockers` AND `check_dispatch`). A structural version here would have
  to encode "a status transition to `running`", and the RESUME path deliberately has no
  launch gate on it — the dial-time check is what catches a lapsed registration. A
  guardrail whose first act is to fire on correct code is a guardrail with an exemption
  list, and the exemption list is the end of it.
* **Nothing about polarity, values or ordering INSIDE the gate.** Whether the DNC read
  comes before the caps read, whether a rule returns the right string — behaviour, and
  behaviour is what the pytest suites above are for. This file only asserts that the
  gate is on the path, unbypassable, and backed by the schema it assumes.

Run: `uv run python -m scripts.check_compliance_invariants`  (also in `make guardrails`)

Research note (2026-08, before writing any of this), so the next reader inherits the
evidence rather than the conclusion:

* **Fitness functions / ArchUnit** (Ford, Parsons & Kua; ArchUnit 1.3, Spring Modulith
  1.4, jMolecules 2026.0 — dev.to "The Modular Monolith 2026 Complete Guide";
  lukasniessen.com "Fitness Functions: Automating Your Architecture Decisions"). ADOPTED
  as the SHAPE: a fitness function tests that the system's structure still matches the
  stated intent, sits in CI beside the unit tests, and is written against the real
  artefact. That is exactly D-29's argument and exactly what the five sections above do.
  The Java tooling itself is not portable — ArchUnit's vocabulary is packages, classes
  and dependencies; "this call must be preceded by that call" is not expressible in it.
* **Semgrep** (semgrep.dev/docs/writing-rules/data-flow/taint-mode/overview; the
  `pattern-not-inside` KB article; jdsalaro.com on emulating Pro taint mode with join
  mode). REJECTED, with regret, for section 2. `patterns` + `pattern-not-inside` can say
  "a `dispatch_call` not inside a function that also contains `check_dispatch`" — that is
  the check we ALREADY have in `compliance_audit_test`. What it cannot say is "and the
  returned decision was acted upon before the dial": taint mode is intra-procedural in
  the OSS engine and models data flowing TO a sink, not a control-dependency between two
  calls; the interprocedural/interfile analysis is the Pro tier. Adding a second rule
  ENGINE — a new dependency, a rules DSL, and a second place a compliance rule can live —
  to express less than 200 lines of `ast` gives us costs the rule does not pay for.
* **OPA / conftest** (policy-as-code, rego). REJECTED for this: it evaluates structured
  documents (JSON/YAML — Terraform plans, k8s manifests), which is a real fit for
  `infra/` and no fit at all for "which Python function calls which". Noted here so the
  next person reaching for policy-as-code does not re-derive it.
* **`vulture` / dead-code scanners.** Same rejection `check_wiring.py` records: they
  answer "is this symbol referenced", which on FastAPI/SQLAlchemy code is a
  false-positive machine, and their answer to that is a whitelist — the exemption
  treadmill this file is written to avoid.

The departure from all of the above is one idea: every question here is asked against
something the running system also uses — the imported gate functions, the engine
Protocol, the enclosing-function chain, `pg_catalog` — so a rename cannot quietly empty
the check (`blind_spots()` fails if it does) and a green run means the registry was
consulted, not that a pattern failed to match.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
# `scripts/` is in here, and it is not padding. It was the ONE directory containing code
# that reaches `VoiceEngine.start_outbound_call` and that neither this guardrail nor
# `tests/platform_audit_test.py::test_every_outbound_path_passes_the_compliance_gate`
# could see — both walked `apps/` only, so the pilot harness's two live dial sites were
# invisible to the census that claims to enumerate every way this repo can ring a phone.
# The harness is legitimate (see ENGINE_REACH_EXEMPTIONS), which is exactly the point:
# the exemption is now WRITTEN DOWN and re-verified on every run, and the next script
# that dials fails the build instead of being unenumerated. This file's own premise is
# that "the path somebody adds next week is the whole failure mode"; a scan root that
# excludes the directory people add one-off operational scripts to contradicts it.
SCAN_ROOTS: tuple[Path, ...] = (REPO_ROOT / "apps", REPO_ROOT / "packages", REPO_ROOT / "scripts")

# The module that OWNS the gate. Every function defined in it is treated as gate-bearing
# for section 4, because a weakening there weakens every dial at once. Resolved from the
# imported symbol at runtime (see `gate_registry`), not hardcoded — this is only the
# fallback spelling used for reporting when the import fails.
GATE_MODULE_KEY = "apps/api/compliance/service.py"

# Engine reaches that are legitimate, each with the reason and each VERIFIED LIVE by
# `stale_exemptions()`: an entry that stops naming a real engine reach fails the guard,
# so this cannot rot into a hiding place for the next module that lands on that name.
# Keyed per FILE::FUNCTION for the reason `check_redaction_exposure`'s exemptions are
# keyed per field — a module-level entry would cover the next function somebody adds.
ENGINE_REACH_EXEMPTIONS: dict[str, str] = {
    "apps/api/agents/service.py::dispatch_call": (
        "THE chokepoint itself. Hard rule 5 is buildable only because one function places "
        "every outbound call: the pre-dispatch `calls` row, the metering hook and the "
        "audit trail exist once rather than once per surface, and section 2 of this "
        "guardrail has a single place to point at. Its own callers are what section 2 "
        "judges; adding a second entry here is how that stops being true"
    ),
    "scripts/pilot/gates_api.py::run_gate_2": (
        "The pilot harness, which OPERATIONS §2 gate 2 requires to place a call through "
        "our own adapter, and which cannot pass the gate because it holds no database "
        "session to pass it with — `scripts/pilot/safety.py` calls that absence its "
        "fourth defence and `tests/pilot_safety_test.py` asserts it against the package "
        "source, so the harness structurally cannot enumerate contacts or discover any "
        "number other than the single `--to` an operator typed. In place of the gate it "
        "carries: dry run by default behind `--yes-place-real-calls-and-spend-money`, a "
        "mandatory `--max-calls` under a hard ceiling of 25 enforced at "
        "`GateContext.spend_a_call`, and a refusal to run at all against a "
        "production-shaped configuration. CLOSED BY: the harness growing a session, a "
        "contact list, or any destination it was not handed — at which point it is a "
        "dialler and takes the gate like every other"
    ),
    "scripts/pilot/concurrency.py::dial": (
        "The same harness, same controls, same budget counter — OPERATIONS §2 gate 13 "
        "ramps concurrent calls to the SAME single `--to` destination to find the line "
        "ceiling, and hangs each probe up immediately. Exempt for the reason "
        "`run_gate_2` is and closed by the same change; listed separately rather than "
        "per-module because a module-level entry would cover the next function somebody "
        "adds to it"
    ),
}

# A bypass arrives as a parameter, never as a comment. Names taken from the narrow
# version in `tests/campaign_dispatch_audit_test.py` (which scans the campaign dispatcher
# only) and widened to the whole gate-bearing surface — see `gate_bypasses`.
BANNED_BYPASS_NAMES = frozenset(
    {
        "allow_blocked",
        "bypass",
        "bypass_gate",
        "for_testing",
        "force",
        "force_dispatch",
        "ignore_dnc",
        "no_gate",
        "skip_checks",
        "skip_compliance",
        "skip_gate",
        "test_mode",
        "unsafe",
    }
)

# The other shape of bypass, and the one that does not look like one. Scoped to
# gate-bearing FUNCTIONS rather than to compliance packages, deliberately: `compliance/
# audit.py` salts the audit hash chain with `app_env` and the WhatsApp transport factory
# refuses the dev sink outside local — both legitimate, both would be reported by a
# package-scoped check, and the exemptions that followed would be the end of this file.
ENV_WEAKENING_NAMES = frozenset(
    {
        "APP_ENV",
        "PYTEST_CURRENT_TEST",
        "app_env",
        "environ",
        "getenv",
        "is_local",
        "is_testing",
        "pytest",
    }
)

_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


# --- the registry this check keys on ------------------------------------------


@dataclass(frozen=True, slots=True)
class GateRegistry:
    """Live names, read off the imported objects.

    Everything below matches on NAMES, which is unavoidable in a static check — so the
    names are taken from the real callables rather than typed in. A rename then either
    updates this registry automatically or fails `blind_spots()`; what it can never do is
    leave the guard matching nothing and printing OK.
    """

    dial: str
    gates: frozenset[str]
    engine_start: str
    transport_factory: str
    opt_in_field: str
    gate_call_names: frozenset[str]
    gate_module_key: str


def gate_registry() -> GateRegistry:
    from apps.api.agents.service import dispatch_call
    from apps.api.campaigns.service import dispatch_blockers, launch_blockers
    from apps.api.compliance.service import (
        add_to_dnc,
        assert_dispatch_allowed,
        check_dispatch,
        credits_exhausted,
        first_campaign_hold_blocker,
        kyc_blocker,
        spend_capped,
    )
    from apps.workers.whatsapp import Destination, get_whatsapp_transport
    from calevate_shared.engine import VoiceEngine

    gates = frozenset({check_dispatch.__name__, assert_dispatch_allowed.__name__})
    # Everything that ASKS a compliance question. A function calling any of these is
    # gate-bearing, which is the scope section 4 polices.
    predicates = {
        add_to_dnc,
        credits_exhausted,
        dispatch_blockers,
        first_campaign_hold_blocker,
        kyc_blocker,
        launch_blockers,
        spend_capped,
    }
    return GateRegistry(
        dial=dispatch_call.__name__,
        gates=gates,
        engine_start=VoiceEngine.start_outbound_call.__name__,
        transport_factory=get_whatsapp_transport.__name__,
        opt_in_field=next(name for name in Destination.__dataclass_fields__ if name == "opt_in_at"),
        gate_call_names=gates | {dispatch_call.__name__} | {f.__name__ for f in predicates},
        gate_module_key=_key(Path(str(sys.modules[check_dispatch.__module__].__file__))),
    )


def blind_spots() -> list[str]:
    """Has the tree moved out from under this check?

    A guardrail that cannot find its own subject must say so rather than report a clean
    run — `check_redaction_exposure` announces the same way when its permission walk
    stops finding anything.
    """
    try:
        registry = gate_registry()
    except Exception as exc:  # pragma: no cover - exercised by deleting a symbol
        return [
            f"this check cannot resolve the gate it polices ({type(exc).__name__}: {exc}). "
            "Every section below would match nothing and report OK — fix the registry in "
            "`gate_registry()` before trusting a green run."
        ]

    failures: list[str] = []
    if registry.gate_module_key != GATE_MODULE_KEY:
        failures.append(
            f"the gate now lives in {registry.gate_module_key}, not {GATE_MODULE_KEY} — "
            "update GATE_MODULE_KEY so section 4 keeps covering the whole gate module"
        )
    if not any(site.qualname in ENGINE_REACH_EXEMPTIONS for site in _engine_sites()):
        failures.append(
            "no engine reach matched the chokepoint exemption — either the outbound "
            "start was renamed or `dispatch_call` no longer calls it, and section 1 is "
            "now watching an empty tree"
        )
    return failures


# --- walking --------------------------------------------------------------------


def _python_files(roots: Iterable[Path] | None = None) -> Iterator[Path]:
    """Every source file the SERVICES are built from.

    Includes `apps/voice-runtime`, which `lint-imports` structurally cannot see — grimp
    walks packages and D-18's directory is hyphenated. The latency-critical service is
    exactly where a dial would be least reviewed, so a guardrail that could not see it
    would have a hole shaped like its most dangerous file.
    """
    for root in SCAN_ROOTS if roots is None else roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            parts = path.parts
            if "__pycache__" in parts or "alembic" in parts or path.name.endswith("_test.py"):
                continue
            yield path


def _key(path: Path, roots: Iterable[Path] | None = None) -> str:
    """A repo-relative, forward-slashed path — the string a human can open.

    Falls back to the scan root when the file is not under the repo (the negative
    controls mirror real files into a tmp tree at their real relative paths, and an
    offender that did not read like the real one would prove nothing).
    """
    for base in (REPO_ROOT, *(roots or ())):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class CallSite:
    path: str
    stack: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]
    call: ast.Call

    @property
    def qualname(self) -> str:
        name = self.stack[-1].name if self.stack else "<module>"
        return f"{self.path}::{name}"

    @property
    def lineno(self) -> int:
        return self.call.lineno


def _called_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _call_sites(tree: ast.AST, path: str, names: Iterable[str]) -> Iterator[CallSite]:
    """Calls of `names`, each carrying the chain of functions enclosing it.

    The chain, not just the innermost function: a dial placed inside a closure or a
    `try` helper is still gated if an enclosing function gated it, and a check that
    demanded the gate in the innermost frame would be wrong about correct code.
    """
    wanted = set(names)

    def walk(
        node: ast.AST, stack: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]
    ) -> Iterator[CallSite]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield from walk(child, (*stack, child))
                continue
            if isinstance(child, ast.Call) and _called_name(child) in wanted:
                yield CallSite(path=path, stack=stack, call=child)
            yield from walk(child, stack)

    yield from walk(tree, ())


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _scan(names: Iterable[str], roots: Iterable[Path] | None = None) -> Iterator[CallSite]:
    root_tuple = tuple(SCAN_ROOTS if roots is None else roots)
    for path in _python_files(root_tuple):
        yield from _call_sites(_parse(path), _key(path, root_tuple), names)


# --- 1. the chokepoint ----------------------------------------------------------


def _engine_sites(roots: Iterable[Path] | None = None) -> list[CallSite]:
    try:
        start = gate_registry().engine_start
    except Exception:  # pragma: no cover - blind_spots() reports this first
        start = "start_outbound_call"
    return list(_scan((start,), roots))


def engine_reach(
    roots: Iterable[Path] | None = None,
    exemptions: dict[str, str] | None = None,
) -> list[str]:
    """Who can make the vendor ring a phone.

    Hard rule 2 keeps vendor payload shapes inside `engine/`; this asks the compliance
    half of the same question — who can INVOKE the outbound start. A module that reaches
    the engine directly has no gate, no `calls` row and no audit trail, and every other
    section of this file would still report OK.
    """
    allowed = ENGINE_REACH_EXEMPTIONS if exemptions is None else exemptions
    return [
        f"{site.qualname} reaches the engine's outbound start directly (no exemption recorded)"
        for site in _engine_sites(roots)
        if site.qualname not in allowed
    ]


def stale_exemptions(
    roots: Iterable[Path] | None = None,
    exemptions: dict[str, str] | None = None,
) -> list[str]:
    """The exemption list may only shrink, and every entry must still name something real.

    Two ways it rots, and both are how an exemption list becomes a hiding place: an entry
    for a site that no longer exists (a hole waiting for the next function to land on
    that name), and an entry whose "reason" is not an argument a reviewer can weigh.
    `impersonation_reads_test` requires each of its exemptions to name a LIVE route for
    exactly this reason.
    """
    allowed = ENGINE_REACH_EXEMPTIONS if exemptions is None else exemptions
    live = {site.qualname for site in _engine_sites(roots)}
    failures: list[str] = []
    for key, reason in sorted(allowed.items()):
        if key not in live:
            failures.append(
                f"exemption {key} names no engine reach in this tree — remove it before "
                "it starts covering something else"
            )
        if len(reason.strip()) < 40:
            failures.append(
                f"exemption {key} has a reason too thin to review: {reason!r}. Say what "
                "makes this reach legitimate and what would close it"
            )
    return failures


# --- 2. every dial passes the gate, and obeys it --------------------------------


def _names_in(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def _binding_of(function: ast.AST, call: ast.Call) -> str | None:
    """The variable a gate call's decision was assigned to, if any."""
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.Await):
            value = value.value
        if value is call and node.targets and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
    return None


def _tests_the_decision(test: ast.expr, binding: str) -> bool:
    for node in ast.walk(test):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "allowed"
            and isinstance(node.value, ast.Name)
            and node.value.id == binding
        ):
            return True
    return False


def _negated(test: ast.expr) -> bool:
    return any(
        isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) for node in ast.walk(test)
    )


def _contains(statements: Sequence[ast.stmt], target: ast.AST) -> bool:
    return any(node is target for statement in statements for node in ast.walk(statement))


def _terminates(statements: Sequence[ast.stmt]) -> bool:
    """Does this branch stop, or does control fall through to the dial below it?

    `if not decision.allowed: log(...)` followed by the dial is the shape that reads like
    a gate and is not one.
    """
    return any(isinstance(node, _TERMINATORS) for node in ast.walk(ast.Module(statements, [])))


def _decision_is_obeyed(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    binding: str,
    dial: ast.Call,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.If) or not _tests_the_decision(node.test, binding):
            continue
        if _contains(node.body, dial):
            # `if decision.allowed: dial()` — correct, and only when the test is positive.
            return not _negated(node.test)
        if _contains(node.orelse, dial):
            return _negated(node.test)
        if node.lineno < dial.lineno and _negated(node.test) and _terminates(node.body):
            # `if not decision.allowed: return ...` and the dial below it.
            return True
    return False


def dial_sites(roots: Iterable[Path] | None = None) -> list[CallSite]:
    return list(_scan((gate_registry().dial,), roots))


def ungated_dials(roots: Iterable[Path] | None = None) -> list[str]:
    """Hard rule 5's core: no outbound path skips the gate, and none ignores its answer.

    Structural over the enclosing-function chain rather than over a list of the four
    surfaces that dial today (campaign dispatcher, D-21 single-lead button, D-21 callback,
    instant-lead-callback webhook). The fifth is the one that matters.
    """
    registry = gate_registry()
    offenders: list[str] = []
    for site in _scan((registry.dial,), roots):
        gated = False
        called_but_ignored = False
        for function in reversed(site.stack):
            gate_calls = [
                call
                for call in _scan_function(function, registry.gates)
                if call.lineno < site.lineno
            ]
            if any(_called_name(call) == "assert_dispatch_allowed" for call in gate_calls):
                gated = True
                break
            for call in gate_calls:
                binding = _binding_of(function, call)
                if binding is not None and _decision_is_obeyed(function, binding, site.call):
                    gated = True
                    break
                called_but_ignored = True
            if gated:
                break
        if gated:
            continue
        if called_but_ignored:
            offenders.append(
                f"{site.qualname} calls the compliance gate and does not act on the "
                "decision it returns — `check_dispatch` RETURNS a refusal rather than "
                "raising (SURFACES §2b), so the dial happens anyway. Branch on "
                "`.allowed` and refuse, or use `assert_dispatch_allowed`"
            )
        else:
            offenders.append(
                f"{site.qualname} places an outbound call and never calls "
                "`check_dispatch`/`assert_dispatch_allowed` before it (hard rule 5). "
                "Every dial passes the gate — there is no exemption and no test flag"
            )
    return offenders


def _scan_function(function: ast.AST, names: Iterable[str]) -> list[ast.Call]:
    wanted = set(names)
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _called_name(node) in wanted
    ]


# --- 3. every message evidences an opt-in ---------------------------------------


def unevidenced_messages(roots: Iterable[Path] | None = None) -> list[str]:
    """SEC-COMP §4: messaging consent is its own permission and is never inferred.

    The registry here is `Destination.opt_in_at` — the one place in this codebase where
    "we can evidence an opt-in" becomes a value. `None` means "we cannot show one", which
    both send sites treat as refusal, and which is what Meta's Business Messaging Policy
    asks us to produce (timestamp + source) when a number is challenged. A send that
    never consults it is a send we cannot defend.

    Deliberately NOT "must call `check_dispatch`": the hot-lead alert messages OUR CLIENT
    (their own owner's number), not a consumer, and DNC/calling-hours are the wrong
    questions to ask about a business we are notifying about their own leads. The
    consumer-facing send (`_send_escalation`) does pass `check_dispatch`, and section 2's
    reasoning does not reach it — so that one is pinned behaviourally in
    `tests/campaign_escalation_test.py` rather than guessed at from the syntax.
    """
    registry = gate_registry()
    offenders: list[str] = []
    for site in _scan((registry.transport_factory,), roots):
        if not site.stack:
            continue
        guarded = False
        for function in reversed(site.stack):
            for node in ast.walk(function):
                if not isinstance(node, ast.If):
                    continue
                if registry.opt_in_field not in _names_in(node.test):
                    continue
                if node.lineno < site.lineno and not _contains(node.body, site.call):
                    guarded = True
                    break
            if guarded:
                break
        if not guarded:
            offenders.append(
                f"{site.qualname} sends a business-initiated message without first "
                f"consulting `{registry.opt_in_field}` (SEC-COMP §4). An opt-in we "
                "cannot evidence is not an opt-in, and Meta asks for the timestamp and "
                "the source when a number is challenged"
            )
    return offenders


# --- 4. no bypass ---------------------------------------------------------------


def _gate_bearing(
    tree: ast.AST, path: str, registry: GateRegistry
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Functions where a bypass would actually bypass something.

    Two ways in: defined in the gate module (a weakening there weakens every dial at
    once), or calls a compliance predicate / the dial. Scoped this way rather than by
    package so that legitimate environment reads in compliance-adjacent code — the audit
    hash-chain salt, the WhatsApp dev-sink refusal — are not reported. A guardrail with
    false positives teaches people to add exemptions.
    """
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if path == registry.gate_module_key:
        return functions
    return [
        function for function in functions if _scan_function(function, registry.gate_call_names)
    ]


def gate_bypasses(roots: Iterable[Path] | None = None) -> list[str]:
    """Hard rule 5: "never add a bypass 'for testing' (use staging fixtures instead)".

    `tests/campaign_dispatch_audit_test.py` asks the parameter half of this question of
    `apps/workers/campaign_dispatch.py` alone. Generalised here to every gate-bearing
    function in the tree — the dispatcher is not where the next bypass will be written,
    because that is the file everybody reviews — and widened with the environment check,
    which nothing checked and which is the shape that does not announce itself.
    """
    registry = gate_registry()
    root_tuple = tuple(SCAN_ROOTS if roots is None else roots)
    offenders: list[str] = []
    for file_path in _python_files(root_tuple):
        path = _key(file_path, root_tuple)
        tree = _parse(file_path)
        for function in _gate_bearing(tree, path, registry):
            arguments = function.args
            declared = {
                argument.arg
                for argument in (
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                )
            }
            passed = {
                keyword.arg
                for call in _scan_function(function, {*registry.gate_call_names})
                for keyword in call.keywords
                if keyword.arg is not None
            }
            for name in sorted((declared | passed) & BANNED_BYPASS_NAMES):
                offenders.append(
                    f"{path}::{function.name} takes or passes `{name}` on the "
                    "gate-bearing path. Hard rule 5: there is no bypass, not for "
                    "testing — the one place it gets left on is production. Use a "
                    "staging fixture"
                )
            for name in sorted(_names_in(function) & ENV_WEAKENING_NAMES):
                offenders.append(
                    f"{path}::{function.name} reads the environment (`{name}`) on the "
                    "gate-bearing path. A gate that behaves differently outside "
                    "production is a gate nobody has tested, and staging dials real "
                    "phones"
                )
    return offenders


# --- 5. the schema still carries what the code assumes --------------------------


@dataclass(frozen=True, slots=True)
class CheckFacts:
    table: str
    name: str
    definition: str


@dataclass(frozen=True, slots=True)
class UniqueFacts:
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchemaFacts:
    # (table, column, not_null)
    columns: frozenset[tuple[str, str, bool]]
    checks: tuple[CheckFacts, ...]
    uniques: tuple[UniqueFacts, ...]


@dataclass(frozen=True, slots=True)
class SchemaInvariant:
    key: str
    holds: Callable[[SchemaFacts], bool]
    failure: str


def _not_null(facts: SchemaFacts, table: str, column: str) -> bool:
    return (table, column, True) in facts.columns


def _check_matching(facts: SchemaFacts, table: str, pattern: str) -> bool:
    expression = re.compile(pattern, re.IGNORECASE)
    return any(
        check.table == table and expression.search(check.definition) for check in facts.checks
    )


def _unique_on(facts: SchemaFacts, table: str, columns: set[str]) -> bool:
    return any(unique.table == table and set(unique.columns) == columns for unique in facts.uniques)


# Matched on the constraint DEFINITION, never on its name: renaming a constraint is a
# legal migration, so a name-keyed check would fire on the rename and stay green on the
# drop — exactly backwards.
SCHEMA_INVARIANTS: tuple[SchemaInvariant, ...] = (
    SchemaInvariant(
        key="agents.disclosure_line NOT NULL",
        holds=lambda facts: _not_null(facts, "agents", "disclosure_line"),
        failure=(
            "agents.disclosure_line is not NOT NULL. Hard rule 5 and SEC-COMP §2.1: every "
            "agent discloses that it is an AI on its first utterance, and the column is "
            "what guarantees it — the gate's own check is belt and braces"
        ),
    ),
    SchemaInvariant(
        key="agents.disclosure_line non-empty",
        holds=lambda facts: _check_matching(
            facts,
            "agents",
            r"(length\s*\(\s*disclosure_line|disclosure_line\s*(<>|!=)\s*'')",
        ),
        failure=(
            "no CHECK constraint stops agents.disclosure_line being empty. NOT NULL alone "
            "admits '' — an agent that opens a call disclosing nothing, which is the IT "
            "Act exposure SEC-COMP §1 records rather than a cosmetic gap"
        ),
    ),
    SchemaInvariant(
        key="dnc_list unique (tenant_id, phone_e164)",
        holds=lambda facts: _unique_on(facts, "dnc_list", {"tenant_id", "phone_e164"}),
        failure=(
            "dnc_list has no unique key on (tenant_id, phone_e164). `add_to_dnc` is "
            "`ON CONFLICT (tenant_id, phone_e164) DO NOTHING`, so without it the in-call "
            "opt-out tool RAISES on the second attempt instead of registering — hard rule "
            "5's propagation deadline missed on the one path that matters most, the "
            "caller who asked"
        ),
    ),
    SchemaInvariant(
        key="consent_ledger messaging rows name their source",
        holds=lambda facts: _check_matching(
            facts, "consent_ledger", r"messaging(?s:.)*consent_source\s+IS\s+NOT\s+NULL"
        ),
        failure=(
            "consent_ledger admits a messaging consent row that names no source. SEC-COMP "
            "§4 encodes messaging consent as a row with a MANDATORY consent_source, "
            "because what Meta asks for when a number is challenged is the timestamp AND "
            "the source; a row that can omit it is not evidence"
        ),
    ),
)


def fetch_schema(engine: Engine) -> SchemaFacts:
    with engine.connect() as connection:
        columns = frozenset(
            (str(row[0]), str(row[1]), row[2] == "NO")
            for row in connection.execute(
                text(
                    "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        )
        checks = tuple(
            CheckFacts(str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                text(
                    "SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid) "
                    "FROM pg_constraint con "
                    "JOIN pg_class rel ON rel.oid = con.conrelid "
                    "JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace "
                    "WHERE nsp.nspname = 'public' AND con.contype = 'c'"
                )
            )
        )
        # `indpred IS NULL` on purpose: a PARTIAL unique index is not a valid arbiter for
        # an unqualified `ON CONFLICT (...)`, so counting one would report a conflict
        # target that Postgres refuses at runtime.
        uniques = tuple(
            UniqueFacts(str(row[0]), tuple(str(name) for name in row[1]))
            for row in connection.execute(
                text(
                    "SELECT rel.relname, array_agg(att.attname ORDER BY k.ord) "
                    "FROM pg_index idx "
                    "JOIN pg_class rel ON rel.oid = idx.indrelid "
                    "JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace "
                    "JOIN LATERAL unnest(idx.indkey) WITH ORDINALITY AS k(attnum, ord) ON true "
                    "JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = k.attnum "
                    "WHERE nsp.nspname = 'public' AND idx.indisunique AND idx.indpred IS NULL "
                    "GROUP BY rel.relname, idx.indexrelid"
                )
            )
        )
    return SchemaFacts(columns=columns, checks=checks, uniques=uniques)


def evaluate_schema(facts: SchemaFacts) -> list[str]:
    return [invariant.failure for invariant in SCHEMA_INVARIANTS if not invariant.holds(facts)]


def check_schema() -> list[str]:
    from apps.api.core.settings import get_settings

    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    return evaluate_schema(fetch_schema(create_engine(url)))


# --- gate -----------------------------------------------------------------------


def main() -> int:
    sections: tuple[tuple[str, list[str]], ...] = (
        ("this check cannot see its own subject", blind_spots()),
        ("code reaches the voice engine outside the chokepoint", engine_reach()),
        ("an outbound dial that does not pass the gate", ungated_dials()),
        ("a message sent without evidence of an opt-in", unevidenced_messages()),
        ("a bypass on the gate-bearing path", gate_bypasses()),
        ("an exemption that no longer holds", stale_exemptions()),
    )
    failed = False
    for title, offenders in sections:
        if offenders:
            failed = True
            print(f"COMPLIANCE INVARIANTS: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            "\nHard rule 5 is not negotiable and has no test flag. If a new surface "
            "needs to place calls, it calls the gate; if the gate is wrong for it, the "
            "gate changes."
        )
        return 1

    try:
        schema_failures = check_schema()
    except Exception as exc:
        # Unverified is not verified-good. Locally (no docker) that is a warning; in CI
        # the database is a service container, so an unreachable one is a broken check
        # pretending to be a green one — the position `check_ledger_immutability` takes.
        if os.environ.get("CI"):
            print(f"COMPLIANCE INVARIANTS: FAIL — database unreachable in CI ({exc!r})")
            return 1
        print(f"COMPLIANCE INVARIANTS: code OK; schema unchecked ({type(exc).__name__})")
        print("Start the database (`make up`) to verify the schema half.")
        return 0

    if schema_failures:
        print("COMPLIANCE INVARIANTS: FAIL — the schema no longer carries an invariant")
        for failure in schema_failures:
            print(f"  - {failure}")
        print("\nFix it in a migration (reversible, RLS included — hard rule 8).")
        return 1

    # The engine-reach count is READ, never asserted as 1: the chokepoint is one of
    # several legitimate reaches now that `scripts/` is scanned, and a hardcoded "1"
    # would have been a sentence this file could print while its own exemption list said
    # otherwise. What section 1 actually guarantees is that every reach is exempted BY
    # NAME with a reviewable reason, which is what this number counts.
    print(
        f"COMPLIANCE INVARIANTS: OK ({len(dial_sites())} dial sites all gated and obeying "
        f"the decision, {len(_engine_sites())} engine reaches all accounted for, "
        f"{len(SCHEMA_INVARIANTS)} schema invariants verified against pg_catalog)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
