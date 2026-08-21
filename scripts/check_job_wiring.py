"""Guardrail: the three-way agreement between DEFINED, REGISTERED and ENQUEUED jobs.

`scripts/check_wiring.py` is the same doctrine on routers, migrations and columns, and
its docstring says in terms that it does NOT check ARQ: *"No ARQ cron check ... the real
failure — a job enqueued by a name no worker answers to — is
`tests/job_registration_test.py`."* That test asked ONE of the three questions, off a
hand-maintained regex over `*_JOB*` constants. This file asks all three, off the tree and
off the live registry, and it is the gate — the test file is now its negative controls.

THE THREE SHAPES, AND WHY THE THIRD IS THE WORST

1. **Defined and never registered.** A `async def job(ctx, ...)` in `apps/workers` that
   is in neither `FUNCTIONS` nor `CRON_JOBS` can never run. It reads as a feature in
   review, in the file tree and in a grep; it is a function nothing calls.

2. **Registered and never enqueued or cronned.** The worker answers to a name nothing
   ever says. Dead code wearing a registration — and the expensive kind, because the
   registry is where a reader goes to learn what this system DOES.

3. **Enqueued by name and not registered.** The enqueue SUCCEEDS. `arq` accepts any
   string; the worker that picks the job up looks it up in `self.functions`, misses, and
   — verified against the installed arq 0.28.0 in `Worker.run_job` — does this:

       logger.warning('job %s, function %r not found', job_id, function_name)
       return await job_failed(JobExecutionFailed(f'function {function_name!r} not found'))

   No retry (`job_failed` is terminal), no alert, nothing in `apps/` or `scripts/` reads
   an arq result key. The outbox row says `published`, the delivery record says queued,
   every screen above them is green, and the side effect never happened. That is how
   `notify_hot_lead_whatsapp` and `escalate_campaign_contact` shipped.

WHY A DERIVED SCAN AND NOT A LIST

The predecessor's own docstring named its blind spot — "a literal that never became a
constant is the one shape this file cannot see" — and then spent a paragraph on the two
more shapes it turned out not to see either. A list of what to check is a list that goes
stale in the direction of silence. So every set here is computed:

* DEFINED comes off the AST of `apps/workers/**`, on the shape arq itself imposes: a
  module-level `async def` whose first parameter is `ctx`. That is not a convention this
  file invented, it is arq's calling signature.
* REGISTERED comes off the imported `WorkerSettings` — the same objects the worker boots
  with, asserted to BE those objects, because a guard that reads a list the worker does
  not use is an assertion about nothing.
* ENQUEUED comes off every call to the four enqueue seams (`enqueue`, `enqueue_outbox`,
  `enqueue_outbox_once`, `job_id_for`), with the job argument resolved through
  module-level string constants. A job argument this file cannot resolve is a FAILURE
  unless it is acknowledged in `DYNAMIC_ENQUEUE_SITES` with a reason — an unresolvable
  name is precisely the hole shape 3 hides in.

REFUSING RATHER THAN PASSING — `check_wiring.blind_spots()` (D-176) is the precedent and
this is the same argument on a different registry, followed rather than re-invented.
Four of the five sets above can go empty for reasons that have nothing to do with the
tree being clean — a moved module, a renamed seam, an import that started failing. An
empty scan compared against an empty registry agrees perfectly. So each scan states its
own floor and the gate REFUSES when one is not met, rather than printing OK.

Run: `uv run python -m scripts.check_job_wiring`  (also in `make guardrails` and CI)
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKERS_ROOT = REPO_ROOT / "apps" / "workers"
#: Where a job can be enqueued FROM. `apps/voice-runtime` needs no special handling the
#: way `check_wiring` gives it — nothing here IMPORTS that directory, it only parses it,
#: and D-18's hyphenated name is only a problem for an importer.
#:
#: `scripts/` is deliberately excluded: nothing there
#: enqueues today, and a one-off script that did would be a wiring question about the
#: script rather than about the fleet.
ENQUEUE_SCAN_ROOTS = (REPO_ROOT / "apps", REPO_ROOT / "packages")

#: The four seams a job name can reach the queue through, and WHERE the name sits in
#: each. `None` means "keyword only" — `enqueue_outbox(session, *, job=...)` is
#: keyword-only in its signature, and the predecessor guard read `args[0]` for every
#: callee, which made it silently inert for every outbox call site.
#:
#: Read off the real signatures rather than remembered: `apps/api/core/queue.py` defines
#: `enqueue(job, *args, ...)` and `job_id_for(job, *key_parts)`, and
#: `apps/api/reliability/service.py` defines both outbox writers with `session` first and
#: `job` keyword-only. `_assert_the_seams_still_look_like_this()` pins that below, so a
#: signature change fails this guard instead of blinding it.
ENQUEUE_SEAMS: dict[str, int | None] = {
    "enqueue": 0,
    "job_id_for": 0,
    "enqueue_outbox": None,
    "enqueue_outbox_once": None,
}

#: Call sites whose job name is not a constant this file can resolve, with the reason.
#:
#: There is exactly one, and its dynamism is the whole point of the outbox: the
#: dispatcher publishes whatever `outbox_messages.job` says, and that column was written
#: by a PRODUCER — which is a call site this scan does read. So the generic drain is
#: covered by the producers it drains, and acknowledging it here costs no coverage.
#:
#: Keyed by `path::expression` rather than by line number, so the entry survives an edit
#: above it; `stale_exemptions()` fails on any entry that no longer matches a real site,
#: for `check_wiring.stale_baseline`'s reason — an exemption nobody can prove still
#: applies is a hole with a comment on it.
DYNAMIC_ENQUEUE_SITES: dict[str, str] = {
    "apps/workers/dispatcher.py::message.job": (
        "the outbox drain publishes the job name stored on the row. Every writer of that "
        "column goes through `enqueue_outbox`/`enqueue_outbox_once`, which this scan "
        "reads, so the name is covered at the producer where it is actually chosen"
    ),
}

#: Floors. Each is a fact about the tree today, one below the real number, so a normal
#: change does not touch them and a scan that has gone blind cannot pass. They are NOT
#: expected counts — an assertion of the exact number would fail on every new job, which
#: is how a floor turns into a chore and then into a raised exemption.
MIN_DEFINITIONS = 15
MIN_REGISTERED = 15
MIN_ENQUEUE_SITES = 8
MIN_RESOLVED_NAMES = 8


class JobDefinition(NamedTuple):
    name: str
    location: str


class EnqueueSite(NamedTuple):
    #: The resolved job name, or None when the argument is not a resolvable constant.
    job: str | None
    #: `path::expression`, the key `DYNAMIC_ENQUEUE_SITES` uses.
    key: str
    location: str


# --- the tree: what is DEFINED ------------------------------------------------


def _python_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.endswith("_test.py"):
            continue
        yield path


def _relative(path: Path) -> str:
    """Repo-relative where possible, absolute otherwise.

    The fallback is not cosmetic: the negative-control tests point the scan at a `tmp_path`
    tree — the only honest way to exercise a scan over a tree — and `relative_to` raises
    rather than returning something outside the root. `check_wiring.unwired_columns` takes
    the same escape for the same reason.
    """
    return (path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path).as_posix()


def lifecycle_hook_names() -> set[str]:
    """arq's four worker hooks, read off `WorkerSettings` rather than listed.

    They share the job signature — `async def hook(ctx)` — so a scan that did not
    subtract them would report the worker's own bootstrap as four unregistered jobs, and
    the obvious fix (a hardcoded name list) is one rename away from being wrong in the
    other direction: a hook renamed and left on the class would go on being subtracted
    from a set it is no longer in.
    """
    from apps.workers.settings import WorkerSettings

    hooks = ("on_startup", "on_shutdown", "on_job_start", "on_job_end")
    return {
        name
        for hook in hooks
        if (name := getattr(getattr(WorkerSettings, hook, None), "__name__", "")) != ""
    }


def defined_jobs() -> list[JobDefinition]:
    """Every module-level `async def f(ctx, ...)` under `apps/workers`, minus the hooks.

    The `ctx`-first signature is arq's, not ours: `Worker.run_job` calls
    `function.coroutine(ctx, *args, **kwargs)`. So this is not a naming convention that
    could drift — it is the only shape a registerable job can have, which is what lets
    the scan be exhaustive rather than a list.
    """
    hooks = lifecycle_hook_names()
    found: list[JobDefinition] = []
    for path in _python_files(WORKERS_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # module level only — a nested coroutine is a helper
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            args = node.args.args
            if not args or args[0].arg != "ctx" or node.name in hooks:
                continue
            found.append(JobDefinition(node.name, f"{_relative(path)}:{node.lineno}"))
    return found


# --- the worker: what is REGISTERED -------------------------------------------


def registered_functions() -> set[str]:
    """Names an enqueued job can be answered by.

    Read off the wrappers, the way arq reads them (`__name__`), so a decorator that
    stopped preserving the name is caught here rather than at 3am.
    """
    from apps.workers.settings import FUNCTIONS

    return {name for fn in FUNCTIONS if (name := getattr(fn, "__name__", ""))}


def registered_crons() -> set[str]:
    """Names the SCHEDULE triggers. A cron needs no enqueuer — the schedule is one."""
    from apps.workers.settings import CRON_JOBS

    return {
        name
        for job in CRON_JOBS
        if (name := getattr(getattr(job, "coroutine", None), "__name__", ""))
    }


def registry_is_the_one_the_worker_boots() -> list[str]:
    """`WorkerSettings` must BE the two lists this file reads.

    Rebind either and every assertion here becomes a statement about a list nobody
    executes — the same failure mode as a guard whose scan matches nothing, arrived at
    from the registry side instead of the tree side.
    """
    from apps.workers.settings import CRON_JOBS, FUNCTIONS, WorkerSettings

    failures: list[str] = []
    if WorkerSettings.functions is not FUNCTIONS:
        failures.append("WorkerSettings.functions is not the FUNCTIONS list this guard reads")
    if WorkerSettings.cron_jobs is not CRON_JOBS:
        failures.append("WorkerSettings.cron_jobs is not the CRON_JOBS list this guard reads")
    return failures


# --- the tree: what is ENQUEUED -----------------------------------------------


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "..."` and `NAME: Final = "..."`.

    BOTH assignment forms. The predecessor read `ast.Assign` only, so the annotated
    spelling this repo prefers for constants (`TENANT_ERASURE_JOB: Final = "..."`) was
    invisible to it — and it was invisible in the direction that passes.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value  # `X: Final` with no value is not a name
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _job_argument(node: ast.Call, callee: str) -> ast.expr | None:
    """Where THIS callee keeps the job name. `None` when the call passes none."""
    for keyword in node.keywords:
        if keyword.arg == "job":
            return keyword.value
    index = ENQUEUE_SEAMS[callee]
    if index is not None and len(node.args) > index:
        return node.args[index]
    return None


def enqueue_sites(roots: Iterable[Path] | None = None) -> list[EnqueueSite]:
    """Every call to an enqueue seam, with its job name resolved where it can be.

    Resolution is deliberately shallow — a literal, or a module-level constant in the
    same file. A deeper resolver (imported constants, attribute chains) would be a small
    interpreter with its own bugs, and the shallow one needs no exemptions: this repo
    already funnels job names through module constants precisely so the name has one
    home. What the shallowness costs is caught rather than hidden — anything it cannot
    resolve is a failure until somebody records why.
    """
    scan_roots = ENQUEUE_SCAN_ROOTS if roots is None else tuple(roots)
    sites: list[EnqueueSite] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            constants = _module_string_constants(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if callee not in ENQUEUE_SEAMS:
                    continue
                argument = _job_argument(node, callee)
                if argument is None:
                    continue
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    resolved: str | None = argument.value
                elif isinstance(argument, ast.Name) and argument.id in constants:
                    resolved = constants[argument.id]
                else:
                    resolved = None
                expression = ast.unparse(argument)
                sites.append(
                    EnqueueSite(
                        job=resolved,
                        key=f"{_relative(path)}::{expression}",
                        location=f"{_relative(path)}:{node.lineno} → {callee}({expression})",
                    )
                )
    return sites


# --- the three questions ------------------------------------------------------


def defined_but_not_registered(
    definitions: Iterable[JobDefinition] | None = None,
    registered: set[str] | None = None,
) -> list[str]:
    """Shape 1: it can never run."""
    defs = list(defined_jobs() if definitions is None else definitions)
    known = (registered_functions() | registered_crons()) if registered is None else registered
    return [
        f"{definition.name} ({definition.location}) is a job function that no worker "
        "registers — it can never run. Add it to `FUNCTIONS` or `CRON_JOBS` in "
        "apps/workers/settings.py, or, if it is a helper rather than a job, give its "
        "first parameter a name other than `ctx`."
        for definition in defs
        if definition.name not in known
    ]


def registered_but_never_enqueued(
    registered: set[str] | None = None,
    crons: set[str] | None = None,
    sites: Iterable[EnqueueSite] | None = None,
) -> list[str]:
    """Shape 2: nothing ever says the name.

    Crons are exempt BY CONSTRUCTION and not by exemption — `cron()` takes the coroutine
    by reference and the schedule is the trigger, so "registered and never enqueued" is
    the normal, correct state for one.
    """
    functions = registered_functions() if registered is None else registered
    scheduled = registered_crons() if crons is None else crons
    reachable = {site.job for site in (enqueue_sites() if sites is None else sites)}
    return [
        f"{name} is registered with the worker and nothing enqueues it — no call to "
        f"{'/'.join(sorted(ENQUEUE_SEAMS))} names it. Either wire the producer or drop "
        "the registration; a registry entry nothing reaches reads as a feature."
        for name in sorted(functions - scheduled)
        if name not in reachable
    ]


def enqueued_but_not_registered(
    sites: Iterable[EnqueueSite] | None = None,
    registered: set[str] | None = None,
) -> list[str]:
    """Shape 3: the enqueue succeeds and the job silently never runs."""
    call_sites = list(enqueue_sites() if sites is None else sites)
    known = (registered_functions() | registered_crons()) if registered is None else registered
    return [
        f"{site.location} enqueues {site.job!r}, which no worker registers. arq accepts "
        "the enqueue, the outbox row reads `published`, and `Worker.run_job` drops the "
        "job with a `function not found` warning nothing reads. Add the function to "
        "`FUNCTIONS` in apps/workers/settings.py."
        for site in call_sites
        if site.job is not None and site.job not in known
    ]


def unresolvable_enqueue_sites(sites: Iterable[EnqueueSite] | None = None) -> list[str]:
    """Call sites whose job name this file cannot read, and which nothing acknowledges.

    Not a fourth shape — a hole in the third. An unresolved name is a name the scan
    cannot compare against the registry, so leaving one unacknowledged would let the
    exact failure above walk straight past the gate.
    """
    call_sites = list(enqueue_sites() if sites is None else sites)
    return [
        f"{site.location}: the job name is not a literal or a module-level constant in "
        "this file, so it cannot be checked against the registry. Declare it as a "
        "module-level constant, or record the site in "
        "`check_job_wiring.DYNAMIC_ENQUEUE_SITES` with the reason it must stay dynamic."
        for site in call_sites
        if site.job is None and site.key not in DYNAMIC_ENQUEUE_SITES
    ]


def stale_exemptions(sites: Iterable[EnqueueSite] | None = None) -> list[str]:
    """Every `DYNAMIC_ENQUEUE_SITES` entry must still name a real unresolved site."""
    call_sites = list(enqueue_sites() if sites is None else sites)
    live = {site.key for site in call_sites if site.job is None}
    return [
        f"DYNAMIC_ENQUEUE_SITES entry {key} matches no unresolved enqueue site any more "
        "— delete it. The registry only shrinks."
        for key in sorted(DYNAMIC_ENQUEUE_SITES)
        if key not in live
    ]


# --- the scan's own health ----------------------------------------------------


def _assert_the_seams_still_look_like_this() -> list[str]:
    """`ENQUEUE_SEAMS` says where each callee keeps its job name. Prove it.

    A signature change — `enqueue_outbox` growing a positional `job`, `enqueue` taking a
    queue first — would leave this file reading the wrong argument and reporting a clean
    tree. Read off the real functions rather than trusted, the same way
    `job_registration_test` learned to check the outbox call sites it had been silently
    skipping.
    """
    import inspect

    from apps.api.core.queue import enqueue, job_id_for
    from apps.api.reliability.service import enqueue_outbox, enqueue_outbox_once

    seams = {
        "enqueue": enqueue,
        "job_id_for": job_id_for,
        "enqueue_outbox": enqueue_outbox,
        "enqueue_outbox_once": enqueue_outbox_once,
    }
    failures: list[str] = []
    for callee, function in seams.items():
        parameters = list(inspect.signature(function).parameters.values())
        names = [parameter.name for parameter in parameters]
        if "job" not in names:
            failures.append(f"{callee} has no `job` parameter — ENQUEUE_SEAMS is out of date")
            continue
        index = names.index("job")
        # `None` = keyword-only, which is what the AST reader must be told: reading
        # `args[0]` on a keyword-only seam is how the predecessor guard became entirely
        # inert for every outbox call site.
        actual = (
            index if parameters[index].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD else None
        )
        if actual != ENQUEUE_SEAMS[callee]:
            failures.append(
                f"{callee}'s `job` is at position {actual!r} and ENQUEUE_SEAMS says "
                f"{ENQUEUE_SEAMS[callee]!r} — the scan is reading the wrong argument"
            )
    return failures


def blindness(
    definitions: Iterable[JobDefinition] | None = None,
    registered: set[str] | None = None,
    sites: Iterable[EnqueueSite] | None = None,
) -> list[str]:
    """REFUSE rather than pass when a scan has stopped seeing anything.

    Three of the four sets below compare against each other, so an empty scan agrees
    perfectly with an empty registry and prints OK — which is the one output a guardrail
    must never produce for a reason unrelated to the tree.
    """
    defs = list(defined_jobs() if definitions is None else definitions)
    known = (registered_functions() | registered_crons()) if registered is None else registered
    call_sites = list(enqueue_sites() if sites is None else sites)
    resolved = {site.job for site in call_sites if site.job is not None}

    failures: list[str] = []
    if len(defs) < MIN_DEFINITIONS:
        failures.append(
            f"the definition scan found {len(defs)} job function(s) under "
            f"{_relative(WORKERS_ROOT)}, below the floor of {MIN_DEFINITIONS} — it is "
            "blind, not clean"
        )
    if len(known) < MIN_REGISTERED:
        failures.append(
            f"the worker registry holds {len(known)} name(s), below the floor of "
            f"{MIN_REGISTERED} — `WorkerSettings` is not what this guard is reading"
        )
    if len(call_sites) < MIN_ENQUEUE_SITES:
        failures.append(
            f"the enqueue scan found {len(call_sites)} call site(s), below the floor of "
            f"{MIN_ENQUEUE_SITES} — the seams moved and the scan is inert"
        )
    if len(resolved) < MIN_RESOLVED_NAMES:
        failures.append(
            f"the enqueue scan resolved {len(resolved)} distinct job name(s), below the "
            f"floor of {MIN_RESOLVED_NAMES} — it is finding call sites and reading "
            "nothing out of them"
        )
    return (
        failures + registry_is_the_one_the_worker_boots() + _assert_the_seams_still_look_like_this()
    )


# --- gate ---------------------------------------------------------------------


def main() -> int:
    # Computed once and threaded through, so the report is a snapshot of ONE scan rather
    # than of six that could disagree if the tree changed underneath them.
    definitions = defined_jobs()
    functions = registered_functions()
    crons = registered_crons()
    known = functions | crons
    sites = enqueue_sites()

    sections: tuple[tuple[str, list[str]], ...] = (
        ("the scan itself", blindness(definitions, known, sites)),
        ("jobs defined and never registered", defined_but_not_registered(definitions, known)),
        (
            "jobs registered and never enqueued or cronned",
            registered_but_never_enqueued(functions, crons, sites),
        ),
        ("jobs enqueued by a name no worker answers to", enqueued_but_not_registered(sites, known)),
        ("enqueue sites whose job name cannot be read", unresolvable_enqueue_sites(sites)),
        ("dynamic-site exemptions that no longer hold", stale_exemptions(sites)),
    )
    failed = False
    for title, offenders in sections:
        if offenders:
            failed = True
            print(f"JOB WIRING: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            "\nCLAUDE.md: leave no half-wired feature. A job nobody registered, a "
            "registration nobody reaches and an enqueue nobody answers are all defects "
            "that look like progress on a screen."
        )
        return 1

    print(
        f"JOB WIRING: OK ({len(definitions)} job functions, {len(functions)} queued + "
        f"{len(crons)} cron registrations, {len(sites)} enqueue site(s), "
        f"{len(DYNAMIC_ENQUEUE_SITES)} dynamic site(s) recorded)"
    )
    return 0


# Research note (2026-08), so the next reader inherits the evidence:
#
# * arq 0.28.0 `Worker.run_job`, read from the installed package rather than from
#   memory: an unknown `function_name` is a `logger.warning` plus `job_failed(...)` with
#   NO retry, and `max_tries` exhaustion is a bare `logger.warning`. Neither reaches
#   `on_job_start`/`on_job_end`. That is why shape 3 is silent and why a static gate is
#   the only thing that catches it before production.
# * `cron()` takes the coroutine BY REFERENCE, so "a cron registered with no function"
#   is not expressible — which is why this file checks crons only for shape 1 and
#   deliberately exempts them from shape 2.
# * `vulture`/`deadcode` were rejected for `check_wiring`'s reason and it holds harder
#   here: a job function is referenced exactly once, in a list literal, which is the
#   pattern those tools are least able to judge.
# * The `traced_job` wrapper preserves `__name__` via `functools.wraps`; this file reads
#   the wrapper (what arq registers), not the wrapped function, so a wrapper that
#   renamed its target fails the floor check rather than passing silently.

if __name__ == "__main__":
    sys.exit(main())
