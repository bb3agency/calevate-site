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
5. **The schema still carries the invariants the code assumes.** The AI disclosure
   sentence NOT NULL and non-empty (SEC-COMP §2.1) — on `ai_disclosure_line` since D-163,
   and on the legacy `disclosure_line` for as long as step 1 of that two-step keeps
   writing it; the two notice toggles NOT NULL; the `dnc_list` unique key that
   `add_to_dnc`'s `ON CONFLICT` needs, without which an in-call opt-out raises instead of
   registering; and the CHECK that stops a `messaging` consent row omitting its source.
   Read from `pg_catalog`, because a migration is a claim and the catalog is the fact —
   the same argument `check_rls_coverage` makes.
6. **The truthful answer cannot be switched off** (D-163, and the reason hard rule 5 was
   rewritten rather than relaxed). SEC-COMP §2's two OPENING notices are now per-agent
   toggles; the answer a caller gets when they ASK is not, and "not toggleable" is a
   claim about code that has to be checked like one. Four questions, in
   `truthful_answer_unfalsifiable()`:

   * the directive exists, is non-empty, and CONTAINS the marker every read-back is
     scored on (read off the imported constants, so a rename cannot empty the check);
   * it is a `Final` CONSTANT and not a field of `AgentConfig` — a field is a writer, and
     a writer is how a tenant's column eventually reaches it;
   * no shipped module assigns to it, passes it as a keyword, or `model_copy`s over it;
   * the composer that carries it onto the engine is reached by every adapter — asserted
     against the live adapter registry rather than a list of adapter names.

   What this file deliberately does NOT assert: that the ENGINE is holding it. That is a
   runtime fact about a vendor, it is scored by `agents/verification.judge` on every
   publish and every half-hourly drift sweep, and a syntax checker claiming it would be
   the true-by-construction move P3.3 exists to record.

7. **No lifecycle state but the active one can dial** (D-440, and the section this file
   was missing the day an agent grew a fourth state). The dial gate's status test and the
   launch gate's are two independent enumerations of ONE policy — which state may place
   calls — and until now nothing held them together but the fact that one person wrote
   both. `dialable_lifecycle_states()` runs each of them over the WHOLE `AGENT_STATUSES`
   vocabulary, read off the live `Literal`, and fails when:

   * more than one state is dialable, or none is. The gate is an ALLOW-LIST of the ACTIVE
     state; two dialable states means an agent its owner switched off can place calls, and
     zero means the enumeration matches nothing and every section here is watching a gate
     that refuses everything;
   * the two gates disagree about any state. That is the drift `launch_blockers`' own
     docstring names — "a launch screen that explained one of them differently from the
     dispatcher's refusal would be two gates disagreeing in front of a client" — and it is
     the shape a widening actually takes, because nobody edits both files at once.

   NO STATE NAME IS WRITTEN DOWN HERE, deliberately: the check is about the SHAPE of the
   allow-list, not about the word `live`, so a renamed state passes and a widened gate
   fails. And because the vocabulary comes from the type rather than from a list, a FIFTH
   status enrolls itself in this check on the day it is declared — which is the exact
   failure the first four states' section could not have caught, since `archived` did not
   exist when this file was written.

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
* **Nothing about polarity, values or ordering INSIDE the gate**, with ONE exception,
  named because the caveat used to be absolute. Whether the DNC read comes before the
  caps read, whether a rule returns the right string — behaviour, and behaviour is what
  the pytest suites above are for. Section 7 is the exception and it is not a behaviour
  claim: it asserts the SHAPE of one allow-list (exactly one lifecycle state dials) and
  that two gates agree about it, neither of which any single pytest can hold, because the
  thing being guarded is that a state added NEXT WEEK does not quietly land on the
  dialable side of either.

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

# WHO MAY DECIDE WHETHER AN AGENT EXISTS AND WHAT STATE IT IS IN (D-440, hard rule 5).
#
# `agents.status` is the column the dial gate reads, and `INSERT INTO agents` is the
# statement that decides whether a new agent has an AI disclosure on file at all. Both
# were single-writer by CONVENTION and by a docstring — `agents/lifecycle.py::create_agent`
# opened with "THE ONE INSERT INTO `agents` IN THIS REPOSITORY", which was not true when it
# was written: `scripts/restore_drill.py::_seed` is a second, spelling the two disclosure
# sentences out in English rather than composing them from the language templates. It is
# legitimate (a scratch-database fixture, see its entry) and that is exactly the point — an
# unenumerated second writer is indistinguishable from a third nobody meant to add.
#
# Keyed per FILE::FUNCTION for `ENGINE_REACH_EXEMPTIONS`' reason: a module-level entry
# would cover the next function somebody adds to that module. Verified live by
# `unregistered_agent_state_writers`, which fails on an entry that names nothing (a hiding
# place waiting for the next function to land on the name) and on a reason too thin to
# review.
AGENT_STATE_WRITERS: dict[str, str] = {
    "apps/api/agents/lifecycle.py::create_agent": (
        "THE BIRTH. Both disclosure sentences are composed from the language templates "
        "here and never taken from the caller, both toggles are written TRUE, the legacy "
        "bundle is composed from the pair, and the row is born `draft` — so there is no "
        "argument to any create surface that produces an agent with no AI sentence on "
        "file. CLOSED BY: nothing; a second birth path takes an entry of its own and the "
        "reviewer then has to say why two places decide what a new agent discloses"
    ),
    "apps/api/agents/service.py::publish_agent": (
        "THE ONLY WRITER OF `live`, and it earns the word: the agent is created or "
        "updated at the engine and READ BACK (D-64) before any column claims it, so "
        "`status = 'live'` is a fact about the vendor rather than an intention of ours. "
        "The lifecycle's `activate` deliberately writes no status and calls this instead"
    ),
    "apps/api/agents/lifecycle.py::deactivate_agent": (
        "`live -> paused` through the transition primitive, with the agent's inbound "
        "numbers released at the vendor in the same transaction — outbound stops by "
        "itself at the dial gate, inbound does not"
    ),
    "apps/api/agents/lifecycle.py::archive_agent": (
        "`draft`/`live`/`paused` -> `archived`, stamping `archived_at` in the same "
        "statement so `ck_agents_archived_at_matches_status` is never momentarily false, "
        "and releasing the numbers for `deactivate_agent`'s reason"
    ),
    "apps/api/agents/lifecycle.py::restore_agent": (
        "`archived -> paused` and nothing else. Never straight to `live`: an agent that "
        "sat retired has no proof left that the engine still holds its configuration, "
        "and only a publish with its read-back can establish one"
    ),
    "scripts/restore_drill.py::_seed": (
        "THE BACKUP-RESTORE DRILL'S FIXTURE, and the one entry here that is not a product "
        "path. It writes two agent rows into a SCRATCH database whose name has already "
        "been through `assert_scratch` (refused if it is named in `.env` or does not match "
        "the scratch pattern), so that the restored copy can be compared row-for-row "
        "against the source. The rows are `draft` with both disclosure sentences and the "
        "legacy bundle set, carry no script and are never published or dialled — the "
        "drill has no engine and no dispatcher. It cannot call `create_agent`: that needs "
        "an `AsyncSession` against an open tenant, and the drill drives raw psycopg over "
        "databases it creates and drops. CLOSED BY: the drill growing a session, at which "
        "point the fixture becomes the product path like every other agent"
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
    #: D-163. The names section 6 polices, read off the imported objects for this
    #: dataclass's whole reason: a rename either updates them or fails `blind_spots()`,
    #: and what it can never do is leave the check matching nothing and printing OK.
    truthful_marker: str
    truthful_directive: str
    truthful_names: frozenset[str]
    prompt_composer: str
    agent_config_fields: frozenset[str]
    #: D-282. The names section 6's SECOND half polices — the per-call home hard rule 5
    #: gets on an engine whose agent record cannot hold a prompt. Read off the real
    #: objects for this dataclass's whole reason.
    call_floor_guard: str
    call_prompt_field: str
    hosting_shapes: frozenset[str]
    external_hosting: str
    #: D-440. Section 7's subject: the whole agent-lifecycle vocabulary and the two gates
    #: that decide which of it may dial. The vocabulary comes off the live `Literal`, so a
    #: fifth status enrolls itself; the gates come off the imported callables, so a rename
    #: either updates this registry or fails `blind_spots()`.
    agent_statuses: frozenset[str]
    dial_status_refusal: Callable[[str], tuple[str, str] | None]
    launch_status_refusal: Callable[[str], object | None]


def gate_registry() -> GateRegistry:
    from apps.api.agents.models import AGENT_STATUSES
    from apps.api.agents.service import dispatch_call
    from apps.api.campaigns.service import (
        dispatch_blockers,
        launch_blockers,
        launch_refusal_for_agent_status,
    )
    from apps.api.compliance.service import (
        add_to_dnc,
        assert_dispatch_allowed,
        check_dispatch,
        credits_exhausted,
        dial_refusal_for_agent_status,
        first_campaign_hold_blocker,
        kyc_blocker,
        spend_capped,
    )
    from apps.api.engine.capabilities import require_call_compliance_floor
    from apps.workers.whatsapp import Destination, get_whatsapp_transport
    from calevate_shared.engine import (
        TRUTHFUL_ANSWER_DIRECTIVE,
        TRUTHFUL_ANSWER_MARKER,
        AgentConfig,
        AgentHosting,
        CallContext,
        VoiceEngine,
        compose_engine_prompt,
    )

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
        truthful_marker=TRUTHFUL_ANSWER_MARKER,
        truthful_directive=TRUTHFUL_ANSWER_DIRECTIVE,
        truthful_names=frozenset({"TRUTHFUL_ANSWER_MARKER", "TRUTHFUL_ANSWER_DIRECTIVE"}),
        prompt_composer=compose_engine_prompt.__name__,
        agent_config_fields=frozenset(AgentConfig.model_fields),
        call_floor_guard=require_call_compliance_floor.__name__,
        call_prompt_field=next(
            name for name in CallContext.model_fields if name == "system_prompt"
        ),
        # From the Literal, never retyped: a hosting shape added to the port lands in this
        # set on the day it is declared, and the section below then has to say what that
        # shape owes hard rule 5 instead of silently exempting it.
        hosting_shapes=frozenset(AgentHosting.__args__),
        external_hosting="external_deployment",
        agent_statuses=frozenset(AGENT_STATUSES),
        dial_status_refusal=dial_refusal_for_agent_status,
        launch_status_refusal=launch_refusal_for_agent_status,
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


# --- 8. who may create an agent, and who may move its status ---------------------

#: An agent row being created, or its `status` being assigned. `RETURNING status` must NOT
#: match — `set_call_cap` and `set_agent_voice` read the column back to decide whether to
#: republish, which is not a write — so the SET clause is isolated before looking.
_AGENT_INSERT = re.compile(r"insert\s+into\s+agents\b", re.IGNORECASE)
_AGENT_UPDATE = re.compile(
    r"update\s+agents\s+set\b(?P<assignments>.*?)(?=\bwhere\b|$)", re.S | re.IGNORECASE
)
_STATUS_ASSIGNED = re.compile(r"\bstatus\s*=", re.IGNORECASE)
_STATUS_LIVE = re.compile(r"\bstatus\s*=\s*'live'", re.IGNORECASE)


def _writes_agent_state(sql: str) -> bool:
    """Does this SQL literal create an agent row or assign its `status`?"""
    if _AGENT_INSERT.search(sql):
        return True
    return any(
        _STATUS_ASSIGNED.search(match.group("assignments")) for match in _AGENT_UPDATE.finditer(sql)
    )


def _agent_state_sites(roots: Iterable[Path] | None = None) -> Iterator[tuple[str, str, bool]]:
    """`(file::function, sql, writes_live)` for every place that decides an agent's state.

    TWO SHAPES, because the tree has two. A literal `INSERT INTO agents` / `UPDATE agents
    SET status = ...` is found in the string constant (Python joins adjacent literals at
    parse time, so a statement written across ten lines is one `ast.Constant`). The other
    is `db/transition.py::transition_status`, which BUILDS the UPDATE from its arguments —
    invisible to any scan of SQL text, and the shape three of the four lifecycle movers
    use. It is matched on `table="agents"` instead, which is the only literal it leaves.

    A BARE STRING EXPRESSION IS SKIPPED, which is docstrings and nothing else that matters.
    Not tidiness: this file's own docstrings quote the statements it hunts for, so without
    it the check's first act was to report itself — and the general rule ("a string nobody
    passes anywhere is not a statement anybody runs") is the one that also keeps the next
    module's prose out of a compliance failure list.
    """
    for path in _python_files(roots):
        tree = _parse(path)
        key = _key(path, roots)
        stack: list[str] = []

        def walk(
            node: ast.AST, stack: list[str] = stack, key: str = key
        ) -> Iterator[tuple[str, str, bool]]:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    stack.append(child.name)
                    yield from walk(child)
                    stack.pop()
                    continue
                if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
                    continue
                where = f"{key}::{'.'.join(stack) or '<module>'}"
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    if _writes_agent_state(child.value):
                        yield (where, child.value, bool(_STATUS_LIVE.search(child.value)))
                elif isinstance(child, ast.Call) and any(
                    keyword.arg == "table"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "agents"
                    for keyword in child.keywords
                ):
                    yield (where, "transition_status(table='agents')", False)
                yield from walk(child)

        yield from walk(tree)


def unregistered_agent_state_writers(
    roots: Iterable[Path] | None = None, writers: dict[str, str] | None = None
) -> list[str]:
    """Only the registered places may create an agent or move its status (hard rule 5).

    THE CLAIM THIS TURNS INTO A GATE. Everything hard rule 5 promises about an agent —
    that it has an AI disclosure on file, that `live` was earned by a read-back rather
    than asserted, that a retired one stays retired — is a claim about the writers of two
    things: the row, and the column the dial gate reads. Those were single-writer by
    convention and by a docstring that was already wrong, which is a rule with no
    enforcement and a comment that reads like enforcement.

    THREE FAILURES, and the third is the one worth the section on its own: a writer that
    is not registered; a registration that names nothing real (a hiding place waiting for
    the next function to land on the name — `stale_exemptions`' argument); and any writer
    other than `publish_agent` assigning the literal `'live'`. That last one is D-64: the
    word means the ENGINE was read back and observed to be holding this agent's script and
    the truthful-answer directive, and a second place writing it would be a claim about a
    vendor derived from a fact about ourselves.
    """
    registry = AGENT_STATE_WRITERS if writers is None else writers
    live_writer = "apps/api/agents/service.py::publish_agent"
    failures: list[str] = []
    seen: set[str] = set()
    for where, sql, writes_live in _agent_state_sites(roots):
        seen.add(where)
        if where not in registry:
            failures.append(
                f"{where} creates an agent row or moves `agents.status` and is not in "
                f"AGENT_STATE_WRITERS: {' '.join(sql.split())[:120]}. Every writer of the "
                "compliance floor is registered with the reason it is allowed to be one — "
                "add it there, or route it through `agents/lifecycle.py`"
            )
        if writes_live and where != live_writer:
            failures.append(
                f"{where} writes `status = 'live'` and is not {live_writer}. `live` means "
                "the engine was READ BACK and observed to be holding this agent's script, "
                "opening line and truthful-answer directive (D-64); a second writer of "
                "that word is a claim about the vendor derived from a fact about us"
            )
    for where, reason in sorted(registry.items()):
        if where not in seen:
            failures.append(
                f"AGENT_STATE_WRITERS names {where}, which no longer creates an agent or "
                "moves its status — remove it before it starts covering something else"
            )
        if len(reason.strip()) < 40:
            failures.append(
                f"AGENT_STATE_WRITERS entry {where} has a reason too thin to review: "
                f"{reason!r}. Say what makes this writer legitimate and what would close it"
            )
    return failures


# --- 7. no lifecycle state but the active one can dial --------------------------


def dialable_lifecycle_states(registry: GateRegistry | None = None) -> list[str]:
    """Run both status gates over the whole agent vocabulary and report the disagreements.

    THE ONLY SECTION HERE THAT EXECUTES CODE RATHER THAN READING IT, and the reason is
    that the question is about a SET the gates compute, not about a call somebody made.
    The two predicates are pure and take a string, so running them costs nothing and needs
    no database — and running them is what makes this immune to the way a widening is
    actually written: `status not in ("live", "archived")` is one green character to an AST
    scan and a second dialable state to this.

    `registry` is injectable so the negative controls can hand it two gates that disagree;
    a check whose subject cannot be replaced in a test is one nobody can prove still sees
    anything (`check_redaction_exposure`'s allowlist argument).
    """
    live = gate_registry() if registry is None else registry
    dialable = sorted(
        status for status in live.agent_statuses if live.dial_status_refusal(status) is None
    )
    launchable = sorted(
        status for status in live.agent_statuses if live.launch_status_refusal(status) is None
    )
    failures: list[str] = []
    if len(dialable) != 1:
        failures.append(
            f"the dial gate admits {len(dialable)} agent lifecycle states ({dialable}) out "
            f"of {sorted(live.agent_statuses)}, and hard rule 5 admits exactly one — the "
            "ACTIVE state. More than one means an agent its owner switched off, retired or "
            "never published can place calls; none means the gate refuses everything and "
            "every other section here is watching a door that is already welded shut"
        )
    if dialable != launchable:
        failures.append(
            f"the dial gate admits {dialable} and the campaign launch gate admits "
            f"{launchable}. These are two enumerations of one policy and they have drifted "
            "— one of them will let a client launch a campaign the dispatcher then refuses "
            "contact by contact, or (worse) dial an agent the launch screen would have "
            "stopped. Fix `dial_refusal_for_agent_status` / "
            "`launch_refusal_for_agent_status` so they agree about every state"
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


# --- 6. the truthful answer cannot be switched off ------------------------------

#: Adapter modules whose prompt MUST come from the one composer. Derived from the engine
#: package rather than listed: an adapter added tomorrow is covered on the day it lands,
#: which is the property `ENGINE_REACH_EXEMPTIONS` gets from being re-verified every run.
_ADAPTER_DIR = REPO_ROOT / "apps" / "api" / "engine"
#: The two files in that package that are NOT adapters — a shared descriptor table and a
#: shared archiving helper, neither of which builds an agent body. Named individually so
#: a third non-adapter has to be argued for rather than assumed.
_ADAPTER_EXCLUDED = frozenset({"__init__.py", "capabilities.py", "document.py"})


def _adapter_files(roots: Iterable[Path] | None = None) -> list[Path]:
    """Every vendor adapter, discovered rather than listed.

    `roots` is the negative controls' door in: they mirror the real adapters into a tmp
    tree and doctor one, so the check has to be able to look at a tree that is not this
    one — the same argument every other section in this file makes for its `roots`.
    """
    directories = (
        [_ADAPTER_DIR] if roots is None else [root / "apps" / "api" / "engine" for root in roots]
    )
    return [
        path
        for directory in directories
        if directory.exists()
        for path in sorted(directory.glob("*.py"))
        if path.name not in _ADAPTER_EXCLUDED and not path.name.endswith("_test.py")
    ]


def truthful_answer_unfalsifiable(roots: Iterable[Path] | None = None) -> list[str]:
    """Hard rule 5's one non-toggleable clause, checked as CODE rather than as a promise.

    D-163 made both opening notices per-agent toggles. The answer a caller gets when they
    ASK stays mandatory on every agent, always, and this is the section that stops that
    sentence from being merely written down. Every question below is asked against
    something the running system also uses — the imported constants, `AgentConfig`'s own
    field registry, the engine package on disk — so a rename cannot quietly empty it.
    """
    registry = gate_registry()
    failures: list[str] = []

    if not registry.truthful_marker.strip():
        failures.append(
            "TRUTHFUL_ANSWER_MARKER is empty. It is the needle every publish read-back "
            "is scored on, and `marker in prompt` is True for the empty string — so an "
            "empty marker certifies every agent, including one holding none of the rules"
        )
    elif registry.truthful_marker not in registry.truthful_directive:
        failures.append(
            "TRUTHFUL_ANSWER_MARKER is not inside TRUTHFUL_ANSWER_DIRECTIVE, so the "
            "publish read-back is scoring a string the adapters never send. The verdict "
            "would be False on a correctly published agent, or — if the marker happens "
            "to appear elsewhere — True on one missing the whole block"
        )

    # A FIELD IS A WRITER. Every field on `AgentConfig` is, somewhere upstream, a column
    # a tenant or an operator can write; the directive must not become one of them.
    settable = sorted(
        field
        for field in registry.agent_config_fields
        if "truthful" in field or "honest" in field or "always_answer" in field
    )
    if settable:
        failures.append(
            f"AgentConfig now has settable field(s) {settable}. The truthful-answer rule "
            "is a Final constant precisely so it has no writer: a field can be emptied, "
            "defaulted away, or `model_copy`d over — which is what `_variant_config` "
            "already does to `system_prompt`"
        )

    root_tuple = tuple(SCAN_ROOTS if roots is None else roots)
    for file_path in _python_files(root_tuple):
        path = _key(file_path, root_tuple)
        tree = _parse(file_path)
        for node in ast.walk(tree):
            # `TRUTHFUL_ANSWER_DIRECTIVE = ...` anywhere but its own home, or a
            # `model_copy(update={"truthful_answer_...": ...})` — both are a rebind of a
            # constant whose whole value is that it has no writer.
            if isinstance(node, ast.Assign):
                targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
                rebound = sorted(targets & registry.truthful_names)
                if rebound and not path.endswith("calevate_shared/engine.py"):
                    failures.append(
                        f"{path} rebinds {rebound[0]}. The rule a client cannot remove is "
                        "a constant in the portability contract; a second binding is a "
                        "second answer, and only one of them reaches the engine"
                    )
        for name in sorted(registry.truthful_names):
            for keyword in _keywords_named(tree, name.lower()):
                failures.append(
                    f"{path} passes `{keyword}=` — the truthful-answer rule is being "
                    "made a parameter of something. It takes no arguments and has no "
                    "per-agent variant; a parameter is a switch with a longer name"
                )

    # EVERY ADAPTER, not a list of adapters — and WHAT each one owes depends on the
    # hosting shape it declares (D-282). There are two homes for the directive and an
    # adapter must be holding it in the one its own `EngineCapabilities` names:
    #
    #   control_plane        the prompt is agent-record state, so the adapter must build
    #                        it with `compose_engine_prompt`;
    #   external_deployment  there is no agent record, so the prompt rides the CALL and
    #                        the adapter must run `require_call_compliance_floor` inside
    #                        `start_outbound_call` — which refuses a dial that is not
    #                        carrying the rule, including one this adapter cannot carry.
    #
    # Before this, section 6 asked every adapter for the first one. That was right while
    # every engine was Bolna-shaped and became wrong the day one was not: `cartesia.py`
    # composes nothing because it writes no agent, and a check that could only see the
    # composer would have forced a dead call to it — a guardrail teaching the code to lie
    # to it, which is worse than no guardrail.
    for adapter in _adapter_files(roots):
        tree = _parse(adapter)
        declared = _declared_hosting(tree, registry)
        unknown = sorted(declared - registry.hosting_shapes)
        if unknown:
            failures.append(
                f"{adapter.name} declares agent hosting {unknown[0]!r}, which is not a "
                "member of `AgentHosting`. This section only knows what the two shipped "
                "shapes owe hard rule 5; a third has to say so here before it can ship"
            )
        # A CALL, not a mention: an adapter that keeps the import and hand-rolls the
        # f-string underneath it is exactly the regression this section exists for, and a
        # substring search would report it clean.
        composes = any(
            isinstance(node, ast.Call) and _called_name(node) == registry.prompt_composer
            for node in ast.walk(tree)
        )
        renders_agents = any(
            isinstance(node, ast.Name) and node.id == "AgentConfig" for node in ast.walk(tree)
        )
        hosts = bool(declared - {registry.external_hosting}) or not declared
        if renders_agents and hosts and not composes:
            failures.append(
                f"{adapter.name} renders an agent without calling "
                f"`{registry.prompt_composer}`. Every engine prompt is composed by that "
                "one function so the truthful-answer rule cannot be forgotten per vendor "
                "— and the conformance suite reads it back off each adapter for the same "
                "reason"
            )
        if registry.external_hosting not in declared:
            continue
        # IN `start_outbound_call`, not merely somewhere in the file. The guard's whole
        # value is that it runs before the vendor is asked to dial; one sitting in a
        # helper nothing calls would satisfy a file-wide search and stop no call.
        dial = _function_named(tree, registry.engine_start)
        if dial is None:
            failures.append(
                f"{adapter.name} declares {registry.external_hosting!r} agent hosting and "
                f"has no `{registry.engine_start}`, so the one place its agents could "
                "receive the truthful-answer rule does not exist"
            )
        elif not any(
            isinstance(node, ast.Call) and _called_name(node) == registry.call_floor_guard
            for node in ast.walk(dial)
        ):
            failures.append(
                f"{adapter.name} declares {registry.external_hosting!r} agent hosting and "
                f"dials without `{registry.call_floor_guard}`. On that shape the engine "
                "holds no prompt of ours, so nothing else can stop a call being placed "
                "with no rule making the agent answer truthfully about being an AI"
            )

    # AND THE WRITER. The guard refuses a dial that is not carrying the prompt; something
    # has to put one there, and there is exactly one outbound entry point in this system
    # (section 1 is the check that keeps it exactly one). A `CallContext` built without
    # the field would make every dial on an externally-deployed engine refuse — the safe
    # direction, and still a broken product — so it is checked rather than assumed.
    for file_path in _python_files(root_tuple):
        dispatch = _function_named(_parse(file_path), registry.dial)
        if dispatch is None:
            continue
        contexts = [
            node
            for node in ast.walk(dispatch)
            if isinstance(node, ast.Call) and _called_name(node) == "CallContext"
        ]
        for context in contexts:
            if not any(kw.arg == registry.call_prompt_field for kw in context.keywords):
                failures.append(
                    f"{_key(file_path, root_tuple)}::{registry.dial} builds a CallContext "
                    f"without `{registry.call_prompt_field}=`. On an engine whose agents "
                    "are deployed elsewhere that field is the only place the "
                    "truthful-answer rule can ride, so every dial there would be refused"
                )
    return failures


def _declared_hosting(tree: ast.AST, registry: GateRegistry) -> set[str]:
    """The `agent_hosting` values this adapter file declares, read off its
    `EngineCapabilities(...)` literals.

    READ FROM THE AST rather than by importing the module, because the negative controls
    mirror the adapters into a tmp tree and doctor one — the same door every other section
    here opens with `roots`. An adapter with more than one profile (the fake engine has
    three) declares all of them, and owes what each shape owes: it is one file that can be
    run as either engine, so a rule satisfied for only one of its profiles is a rule that
    is not satisfied.
    """
    shapes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called_name(node) != "EngineCapabilities":
            continue
        for keyword in node.keywords:
            if keyword.arg == "agent_hosting" and isinstance(keyword.value, ast.Constant):
                shapes.add(str(keyword.value.value))
    return shapes


def _function_named(tree: ast.AST, name: str) -> ast.AST | None:
    """The `def`/`async def` called `name`, or None.

    Scoped lookup rather than a file-wide walk: "the guard is in this file" and "the guard
    runs before this vendor is dialled" are different claims, and only the second is worth
    checking.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _keywords_named(tree: ast.AST, name: str) -> list[str]:
    return sorted(
        {
            keyword.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg is not None and keyword.arg == name
        }
    )


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
        key="agents.ai_disclosure_line NOT NULL",
        holds=lambda facts: _not_null(facts, "agents", "ai_disclosure_line"),
        failure=(
            "agents.ai_disclosure_line is not NOT NULL. Hard rule 5 and SEC-COMP §2.1: "
            "every agent HAS an AI disclosure sentence on file even when its owner has "
            "chosen not to volunteer it — `check_dispatch` refuses a dial without one, "
            "and the answer to a caller who asks 'are you an AI?' needs a sentence to be"
        ),
    ),
    SchemaInvariant(
        key="agents.ai_disclosure_line non-empty",
        holds=lambda facts: _check_matching(
            facts,
            "agents",
            r"(length\s*\(\s*btrim\s*\(\s*ai_disclosure_line|ai_disclosure_line\s*(<>|!=)\s*'')",
        ),
        failure=(
            "no CHECK constraint stops agents.ai_disclosure_line being empty or blank. "
            "NOT NULL alone admits '' and ' ' — an agent with no AI sentence at all, "
            "which is the one state D-163 does NOT permit: the notice is optional, the "
            "sentence is not"
        ),
    ),
    SchemaInvariant(
        key="agents.recording_notice_line non-empty",
        holds=lambda facts: (
            _not_null(facts, "agents", "recording_notice_line")
            and _check_matching(
                facts,
                "agents",
                r"length\s*\(\s*btrim\s*\(\s*recording_notice_line",
            )
        ),
        failure=(
            "agents.recording_notice_line is nullable or unconstrained. A client who "
            "switches the recording notice back ON must get a sentence rather than "
            "silence, and a column that can be blank makes 'on' and 'off' the same state"
        ),
    ),
    SchemaInvariant(
        key="agents notice toggles NOT NULL",
        holds=lambda facts: (
            _not_null(facts, "agents", "ai_disclosure_enabled")
            and _not_null(facts, "agents", "recording_notice_enabled")
        ),
        failure=(
            "a disclosure toggle on `agents` is nullable. NULL is a third state for a "
            "two-state compliance posture, and every reader would have to invent which "
            "way it falls — `compose_opening_line` treats it as OFF, which is the one "
            "reading an omission must never silently produce (D-163)"
        ),
    ),
    SchemaInvariant(
        # STEP 1 OF THE TWO-STEP (hard rule 8): D-163 stopped READING this column on the
        # publish path and did not stop writing it. While it is still written it is still
        # constrained, so the deprecation cannot rot into a column full of empty strings
        # that a step-2 reviewer reads as "nothing depended on it".
        key="agents.disclosure_line (legacy bundle) still NOT NULL and non-empty",
        holds=lambda facts: (
            _not_null(facts, "agents", "disclosure_line")
            and _check_matching(
                facts,
                "agents",
                r"(length\s*\(\s*disclosure_line|disclosure_line\s*(<>|!=)\s*'')",
            )
        ),
        failure=(
            "the legacy agents.disclosure_line lost its NOT NULL or its non-empty CHECK. "
            "D-163 keeps writing it for one release (hard rule 8's two-step); dropping "
            "the constraint without dropping the column is neither step"
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
        ("the truthful answer became switchable", truthful_answer_unfalsifiable()),
        ("a lifecycle state other than the active one can dial", dialable_lifecycle_states()),
        (
            "an unregistered writer of an agent's existence or status",
            unregistered_agent_state_writers(),
        ),
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
        f"{len(_adapter_files())} adapter modules holding the truthful-answer rule in the "
        f"home their declared agent hosting gives it, {len(SCHEMA_INVARIANTS)} schema "
        "invariants verified against "
        f"pg_catalog, 1 of {len(gate_registry().agent_statuses)} agent lifecycle states "
        f"dialable and both gates agreeing on which, {len(AGENT_STATE_WRITERS)} registered "
        "writers of an agent's existence or status)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
