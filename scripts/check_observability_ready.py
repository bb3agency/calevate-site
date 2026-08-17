"""Guardrail: a component that is DECLARED ON is actually on, and is still filtered.

A monitoring stack has three states and only two of them are ever discussed. Off is
loud — `init_observability` logs `observability_local_only` — and on-and-working needs
nothing said. The third is a process that believes it is reporting and is not: a DSN with
a typo in its project id, an OTLP endpoint that already ends in `/v1/traces` so the
exporter appends a second one, a sample ratio of 0.0, a `sentry-sdk` that is in a
dependency GROUP nobody installed. Every one of those boots green and stays silent, and
from the outside that is indistinguishable from a platform that is not failing.

**Three components, one ladder** (the shape is deliberately the reference implementation's
— `otel-readiness-check.js:42-95` — because it is the right one: disabled SKIPS cleanly so
that nobody learns to ignore the check, and enabled-but-misconfigured FAILS naming the
specific setting):

* **sentry** — declared on by `SENTRY_DSN`. Configuration shape, SDK presence, release
  identity, and the four `sentry_sdk.init` keywords that make hard rule 6 hold on the
  error path.
* **otel** — declared on by `OTEL_EXPORTER_OTLP_ENDPOINT`. Endpoint shape, sample ratio,
  SDK presence, and that every span processor is fed through `_RedactingSpanExporter`.
* **langfuse** — declared on by NOTHING TODAY, and that absence is the check. D-49 removed
  the keys rather than leaving a settings field that looks wired, so the rung asks the
  repository rather than the settings: is there a langfuse import, dependency or settings
  field anywhere? If one appears, hard rule 6 says the trace path must still be redacted,
  and the Langfuse v3 SDK is its own OpenTelemetry pipeline — a direct client is a SECOND,
  UNFILTERED exporter beside the one this repo scrubs, which is the same defect
  `traces_sample_rate` turned out to be. So the rung fails on arrival and asks for the
  decision-log entry `packages/shared/src/calevate_shared/config.py` already names.

WHAT THIS DELIBERATELY DOES NOT DO, AND WHY IT MUST NOT
------------------------------------------------------
**It does not touch the network, and it never reports reachability.** It cannot: this
container has no Sentry project, no collector and no credential, and a check that
"verified" either by parsing a string would be an unverified vendor behaviour presented as
an observation — the defect class D-31 and D-32 exist for, one layer further in. The line
is drawn once and named on every run: configuration validity is decided here, and
**delivery is OPERATIONS §2 gate 15**, performed against the real hosts with the real
credentials and recorded there like every other vendor claim in that table.

So a green run here means "nothing in this configuration can be shown to be broken", never
"errors are arriving". The two sentences are different and the second one is a gate.

Run: `uv run python -m scripts.check_observability_ready`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

from apps.api.core.observability import (
    READINESS_MISCONFIGURED,
    READINESS_READY,
    READINESS_SKIPPED,
    ComponentReadiness,
    ReadinessProblem,
    observability_readiness,
)
from apps.api.core.settings import get_settings
from calevate_shared.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
OBSERVABILITY = REPO_ROOT / "apps" / "api" / "core" / "observability.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
#: Where a langfuse client could plausibly be constructed. `docs/` is excluded on purpose:
#: the decision NOT to wire Langfuse is written down in several places and prose about an
#: absent client is not a client.
IMPORT_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "apps",
    REPO_ROOT / "packages",
    REPO_ROOT / "scripts",
)

#: `sentry_sdk.init` keywords that carry hard rule 6 on the error path, each with what is
#: lost when it goes. Read against the LIVE call in `init_observability` rather than
#: trusted, because every one of them is a single word somebody can delete while tidying.
REQUIRED_SENTRY_INIT: dict[str, str] = {
    "before_send": (
        "the event scrubber. Without it the exception message, the request body, the "
        "frame locals and the logging integration's `logentry` all ship verbatim — which "
        "on this codebase means a transcript"
    ),
    "before_breadcrumb": (
        "the breadcrumb scrubber. The logging integration builds one from every log "
        "record using `record.getMessage()`, so our JsonFormatter's redaction never runs "
        "on it"
    ),
    "send_default_pii": "the SDK's own PII gathering, which must stay off",
    "max_request_body_size": (
        "the request-body capture, which must be `never` — a webhook body is a transcript"
    ),
}

#: Keywords that must NOT appear. `traces_sample_rate` turns on Sentry's own performance
#: tracing: a second span pipeline carrying SQL descriptions and full outbound URLs, and
#: `before_send` DOES NOT RUN on transaction events (getsentry/sentry-python#1226). One
#: tracing pipeline per problem, and the one this repo keeps is the filtered one.
FORBIDDEN_SENTRY_INIT: dict[str, str] = {
    "traces_sample_rate": (
        "it enables Sentry performance tracing, a SECOND span pipeline whose events "
        "`before_send` never sees. Use the OTel pipeline, whose exporter is wrapped"
    ),
    "profiles_sample_rate": (
        "profiling ships stack samples through the same transaction path `before_send` "
        "does not filter"
    ),
}

#: The wrapper every span must pass through before it reaches a vendor.
REDACTING_EXPORTER = "_RedactingSpanExporter"
SPAN_PROCESSORS = ("BatchSpanProcessor", "SimpleSpanProcessor")


# --- rung 1 + 2: configuration validity, shared with the boot path --------------


def configured_components(settings: Settings | None = None) -> tuple[ComponentReadiness, ...]:
    """The settings half of the ladder, from `observability.py` itself.

    Imported rather than restated: the boot log and this script must never be able to
    disagree about whether a DSN is usable, and two copies of the rule is how they start.
    """
    return observability_readiness(settings or get_settings())


def unresolvable_settings() -> list[str] | None:
    """The `Settings` fields that stop this process building a configuration at all.

    Returns None when settings resolve. This is NOT an environment-parity check
    (`check_env_parity` owns that question and owns it alone) — it is this check refusing
    to report a verdict it did not reach. A shell with no `.env` cannot be asked whether
    a DSN is well formed, and answering "OK" there would be the same manufactured
    confidence the whole ladder exists to remove.
    """
    from pydantic import ValidationError

    try:
        get_settings()
    except ValidationError as exc:
        return sorted({str(error["loc"][0]) for error in exc.errors() if error.get("loc")})
    return None


# --- rung 3: the hooks that make hard rule 6 hold on each export path -----------


def _init_keywords(source: str, function: str, callee: str) -> dict[str, ast.expr] | None:
    """Keywords of the single `callee(...)` call inside `function`, or None if absent."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = call.func
            spelled = name.attr if isinstance(name, ast.Attribute) else getattr(name, "id", "")
            if spelled == callee:
                return {kw.arg: kw.value for kw in call.keywords if kw.arg}
    return None


def check_sentry_hooks(source: str | None = None) -> list[str]:
    """`sentry_sdk.init` still installs both scrubbers and starts no second pipeline."""
    text = source if source is not None else OBSERVABILITY.read_text(encoding="utf-8")
    keywords = _init_keywords(text, "init_observability", "init")
    if keywords is None:
        return [
            "sentry: `init_observability` no longer contains a `sentry_sdk.init(...)` "
            "call, so this check cannot see how the error tracker is configured. If the "
            "init moved, move this check with it — a guardrail that cannot find its "
            "subject must say so rather than pass."
        ]
    failures: list[str] = []
    for keyword, why in REQUIRED_SENTRY_INIT.items():
        if keyword not in keywords:
            failures.append(
                f"sentry: `sentry_sdk.init` no longer passes `{keyword}`, which is {why}. "
                "Hard rule 6 is not a property of the logger alone — an error tracker is a "
                "log with better search."
            )
    for keyword, why in FORBIDDEN_SENTRY_INIT.items():
        if keyword in keywords:
            failures.append(
                f"sentry: `sentry_sdk.init` passes `{keyword}`, and it must not — {why}."
            )
    scrubbers = {"before_send": "scrub_event", "before_breadcrumb": "scrub_breadcrumb"}
    for keyword, expected in scrubbers.items():
        value = keywords.get(keyword)
        if value is not None and getattr(value, "id", None) != expected:
            failures.append(
                f"sentry: `{keyword}` is set to something other than `{expected}`. The "
                "hook is the enforcement point for hard rule 6 on the error path; a "
                "different function there is a different guarantee, and this check cannot "
                "judge it."
            )
    return failures


def check_tracing_export_is_wrapped(source: str | None = None) -> list[str]:
    """Every span processor in `init_tracing` is fed the redacting exporter.

    The exporter — not the call sites — is where hard rule 6 is enforced on the trace
    path, because `record_exception=True` is the SDK's default and it writes
    `exception.message` and `exception.stacktrace` onto spans no allowlist ever sees.
    A processor wired straight to the OTLP exporter reopens that, silently, for every
    span in the process.
    """
    text = source if source is not None else OBSERVABILITY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "init_tracing"
        ),
        None,
    )
    if function is None:
        return [
            "otel: `init_tracing` is gone from apps/api/core/observability.py, so the "
            "export path this check guards no longer exists where it can be read."
        ]
    # Names bound to a `_RedactingSpanExporter(...)` call anywhere in the function. The
    # production spelling assigns it first (`redacting_exporter: Any = ...`) and passes
    # the name; a direct call is accepted too.
    wrapped: set[str] = set()
    for node in ast.walk(function):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and getattr(value.func, "id", None) == REDACTING_EXPORTER
            and len(targets) == 1
            and isinstance(targets[0], ast.Name)
        ):
            wrapped.add(targets[0].id)

    failures: list[str] = []
    seen_processor = False
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        callee = getattr(node.func, "id", None)
        if callee not in SPAN_PROCESSORS:
            continue
        seen_processor = True
        argument = node.args[0] if node.args else None
        direct = (
            isinstance(argument, ast.Call)
            and getattr(argument.func, "id", None) == REDACTING_EXPORTER
        )
        indirect = isinstance(argument, ast.Name) and argument.id in wrapped
        if not (direct or indirect):
            failures.append(
                f"otel: `{callee}` in `init_tracing` is not fed a "
                f"`{REDACTING_EXPORTER}`. Every span — including the ones the SDK writes "
                "by itself, `exception.message` and `exception.stacktrace` among them — "
                "would then leave this process unscrubbed. Wrap the exporter, do not "
                "filter at the call sites: a guard you have to remember is the one that "
                "fails when the codebase grows fastest (D-29)."
            )
    if not seen_processor:
        failures.append(
            "otel: `init_tracing` registers no span processor this check recognises "
            f"({', '.join(SPAN_PROCESSORS)}). Either tracing no longer exports, or it "
            "exports through something this guardrail cannot see — both need an answer "
            "before a span leaves the process."
        )
    return failures


# --- rung 3, langfuse half: is it here at all, and would it be filtered? --------


def langfuse_footholds(
    roots: tuple[Path, ...] | None = None, pyproject: Path | None = None
) -> list[str]:
    """Every place Langfuse has entered the tree, as `location — what it is`.

    Three surfaces because there are three ways it can arrive and only one of them is a
    settings field: an import, a dependency, or a `Settings` key. Import detection is by
    AST, never by text, so the prose in `config.py` explaining why Langfuse is ABSENT does
    not read as Langfuse being present.
    """
    found: list[str] = []
    for root in IMPORT_ROOTS if roots is None else roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                if any(name == "langfuse" or name.startswith("langfuse.") for name in names):
                    where = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
                    found.append(f"{where}:{node.lineno} — imports langfuse")
    manifest = pyproject or PYPROJECT
    if manifest.exists():
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        project = data.get("project", {})
        groups = data.get("dependency-groups", {})
        specs: list[tuple[str, str]] = [
            ("project.dependencies", spec) for spec in project.get("dependencies", [])
        ]
        for group, entries in groups.items():
            specs += [
                (f"dependency-groups.{group}", entry) for entry in entries if isinstance(entry, str)
            ]
        for where, spec in specs:
            if spec.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip() == "langfuse":
                found.append(f"pyproject.toml {where} — declares the langfuse package")
    found += [
        f"Settings.{field} — a langfuse-shaped configuration field"
        for field in Settings.model_fields
        if "langfuse" in field
    ]
    return found


def check_langfuse(footholds: list[str] | None = None) -> tuple[ComponentReadiness, list[str]]:
    """The rung, and the failures it produces. Absent is the pass."""
    present = langfuse_footholds() if footholds is None else footholds
    if not present:
        return (
            ComponentReadiness(
                "langfuse",
                READINESS_SKIPPED,
                "Not present in the tree: no import, no dependency, no settings field "
                "(D-49). Per-call token cost and the TRD §2 latency breakdown are "
                "therefore a NAMED GAP and not a broken component.",
            ),
            [],
        )
    failures = [
        f"langfuse: found at {where}. Hard rule 6 says Langfuse traces go through the "
        "redaction hook, and this repository has exactly one — `_RedactingSpanExporter`, "
        "applied to every span leaving the process. The Langfuse v3 SDK is its own "
        "OpenTelemetry pipeline, so a direct client is a SECOND exporter that never meets "
        "it, carrying the extraction prompt (a raw transcript) to a vendor. Restoring "
        "Langfuse needs the decision-log entry config.py names, and it exports through "
        "the existing OTLP path or not at all."
        for where in present
    ]
    return (
        ComponentReadiness(
            "langfuse",
            READINESS_MISCONFIGURED,
            "Langfuse has entered the tree.",
            tuple(ReadinessProblem("langfuse_unfiltered_path", failure) for failure in failures),
        ),
        failures,
    )


# --- report --------------------------------------------------------------------


#: Rung -> the four characters an operator scans the output for. Keyed off the constants
#: rather than their spellings, so renaming a rung is a type error rather than a KeyError
#: discovered by whoever runs the check next.
_MARKS: dict[str, str] = {
    READINESS_SKIPPED: "skip",
    READINESS_READY: "pass",
    READINESS_MISCONFIGURED: "FAIL",
}


def _render(component: ComponentReadiness) -> list[str]:
    lines = [f"  [{_MARKS[component.status]}] {component.component}: {component.summary}"]
    lines += [f"         - {problem.message}" for problem in component.problems]
    return lines


def main() -> int:
    """Exit 0 = nothing shown to be broken. 1 = a verdict. 2 = REFUSED to reach one.

    The three-way exit is `check_coverage_ratchet`'s, for its reason: a check that could
    not judge must not be the step that lets a deploy through, and it must not be
    reported as a pass either.
    """
    unresolved = unresolvable_settings()
    langfuse, _ = check_langfuse()
    # The structural rungs read the TREE, so they answer with or without a configuration —
    # and they are the rungs that carry hard rule 6, so they run first and always.
    structural = check_sentry_hooks() + check_tracing_export_is_wrapped()
    components = [] if unresolved else [*configured_components()]
    components.append(langfuse)

    failures = [
        problem.message
        for component in components
        if component.status == READINESS_MISCONFIGURED
        for problem in component.problems
    ]
    failures += structural

    print("OBSERVABILITY READINESS")
    if unresolved:
        print(
            "  [----] sentry, otel: NOT JUDGED — this process cannot build a Settings "
            f"object at all ({', '.join(unresolved)} unresolved), so there is no "
            "configuration to inspect. Set the deployment's environment and re-run."
        )
    for component in components:
        for line in _render(component):
            print(line)
    for failure in structural:
        print(f"  [FAIL] {failure}")
    print(
        "  NOT CHECKED HERE, BY DESIGN: whether a Sentry event is accepted, whether the "
        "collector answers, and whether a human sees either. That is OPERATIONS §2 gate "
        "15 — a live call from a real host, not a string this process can parse."
    )

    if failures:
        print("OBSERVABILITY READINESS: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    if unresolved:
        print("OBSERVABILITY READINESS: REFUSED (no resolvable configuration to judge)")
        return 2
    declared = [c.component for c in components if c.status != READINESS_SKIPPED]
    skipped = [c.component for c in components if c.status == READINESS_SKIPPED]
    summary = ", ".join(f"{name} declared on" for name in declared) or "nothing declared on"
    print(
        f"OBSERVABILITY READINESS: OK ({summary}; not configured: "
        f"{', '.join(skipped) or 'none'}; both export filters intact; "
        "reachability deliberately unasserted)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
