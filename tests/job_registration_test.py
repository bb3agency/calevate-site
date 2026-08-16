"""Every job name the system can enqueue must be a job some worker knows.

An unregistered job is not a dormant feature. The outbox publishes it, arq does not
recognise the name, and the row walks its retry ladder into the DLQ — while the outbox
row, the delivery record and every screen above them report that the message was queued.
The failure is silent in exactly the place a silent failure is most expensive: a
compliance follow-up, a hot-lead alert, an erasure.

That is not hypothetical. `notify_hot_lead_whatsapp` shipped with the WhatsApp seam and
was never added to `FUNCTIONS`; `escalate_campaign_contact` was written against the same
module and would have shipped the same way. Both were caught by reading, which is the
part that does not scale — hence this file.

**Why the constants rather than the call sites.** A job name reaches the queue as a
string, through `enqueue`, `enqueue_outbox`, `job_id_for` and the outbox row's `job`
column, and chasing every one of those with an AST walk would be a parser with its own
bugs. The repo already funnels them through module-level `*_JOB*` constants precisely so
the name has one home per job, so those constants ARE the enqueueable set — and the last
assertion here is what keeps that true: a literal that never became a constant is the
one shape this file cannot see, so new job names must land as constants.

**AND THAT SENTENCE WAS FALSE IN TWO WAYS UNTIL P6.9** — the guard could not see three
more shapes, which is worse than a guard that admits a gap:

* the constant scan read `ast.Assign` only, so `TENANT_ERASURE_JOB: Final = "..."` — an
  `AnnAssign`, and the annotated spelling this repo prefers — was never checked;
* the literal scan inspected `node.args[0]` for every enqueuer, and `enqueue_outbox`'s
  first positional is the SESSION. It was therefore ENTIRELY INERT for every outbox call
  site, which is most of them, and inert in the direction that matters: the outbox is the
  path where an unrecognised job name is published and reported as queued.

Run against the tree at the time: one missed constant, two invisible keyword literals.
All three named jobs that WERE registered, so there was no live outage — the defect was
a guard reporting coverage it did not have, which is the class this whole file exists
for. Both are closed and both are sabotage-verified.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from apps.workers.settings import CRON_JOBS, FUNCTIONS

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_ROOTS = ("apps", "packages")

# `*_JOB = "..."` / `JOB_NAME = "..."` / `*_JOB_NAME = "..."` — the naming this repo
# already uses for the string that identifies a job to arq.
_JOB_CONST = re.compile(r"^(?:[A-Z0-9_]*_)?JOB(?:_NAME)?$")


def _registered_names() -> set[str]:
    """What a worker booted from `settings.py` would actually answer to.

    `traced_job` wraps each function, so the name is read off the wrapper the way arq
    reads it — via `__name__`/`__qualname__` — rather than off the undecorated function,
    which is what the registry would have looked like if the decorator were transparent.
    A wrapper that renamed its target would be a real defect and this reads it as one.
    """
    names = {getattr(fn, "__name__", "") for fn in FUNCTIONS}
    names |= {getattr(getattr(job, "coroutine", None), "__name__", "") for job in CRON_JOBS}
    return {name for name in names if name}


def _job_name_constants() -> dict[str, str]:
    """Every `*_JOB*` string constant in the tree, as {file:line: value}."""
    found: dict[str, str] = {}
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts or path.name.endswith("_test.py"):
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in tree.body:  # module level only: a job name is a module fact
                # BOTH assignment forms (P6.9). This read `ast.Assign` only, so
                # `TENANT_ERASURE_JOB: Final = "execute_tenant_erasure"` — an `AnnAssign`,
                # and the annotated form this repo prefers for constants — was not checked
                # at all. Measured against the tree at the time: one constant missed. The
                # job it names IS registered, so there was no live outage; what there was
                # is a guard whose docstring claims to see every job-name constant and
                # could not see the spelling half of them use.
                if isinstance(node, ast.Assign):
                    targets: list[ast.expr] = list(node.targets)
                    value = node.value
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                    value = node.value  # `X: Final` with no value is not a job name
                else:
                    continue
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    continue
                for target in targets:
                    if isinstance(target, ast.Name) and _JOB_CONST.match(target.id):
                        rel = path.relative_to(REPO_ROOT)
                        found[f"{rel}:{node.lineno}"] = value.value
    return found


def test_every_job_name_constant_is_registered_with_a_worker() -> None:
    """The assertion the WhatsApp jobs would have failed."""
    registered = _registered_names()
    constants = _job_name_constants()
    assert constants, "found no job-name constants at all — the scan is broken, not the code"

    orphans = {where: name for where, name in constants.items() if name not in registered}
    assert not orphans, (
        "these job names can be enqueued and no worker answers to them — the outbox will "
        f"publish them straight into the DLQ: {orphans}. Add the function to "
        "`apps/workers/settings.FUNCTIONS`."
    )


def test_the_registry_has_no_duplicate_names() -> None:
    """Two functions answering to one name means one of them never runs, and which one
    depends on registration order — a coin flip nobody would think to look at."""
    names = [getattr(fn, "__name__", "") for fn in FUNCTIONS]
    assert len(names) == len(set(names)), f"duplicate job names in FUNCTIONS: {names}"


def test_tracing_did_not_rename_a_job() -> None:
    """`traced_job` wraps every entry. If it ever stopped preserving `__name__`, every
    job in the system would silently register under the wrapper's own name and nothing
    else in this file would notice — the orphan check would still pass, against a
    registry of identical names."""
    names = _registered_names()
    assert "wrapper" not in names and "inner" not in names, (
        f"traced_job is not preserving __name__; the registry reads as {sorted(names)}"
    )
    assert "run_post_call_pipeline" in names, "the registry lost a job it has always had"


def test_a_job_name_is_declared_as_a_constant_rather_than_a_literal() -> None:
    """The assumption this whole file rests on, asserted rather than trusted.

    The scan above reads CONSTANTS. A job enqueued with a bare string literal —
    `enqueue("some_job", ...)` — is invisible to it, so the guard would pass while the
    exact bug it exists to catch shipped. Every enqueue call site must therefore name a
    constant, not a literal.
    """
    offenders: list[str] = []
    enqueuers = {"enqueue", "enqueue_outbox", "job_id_for"}
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts or path.name.endswith("_test.py"):
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name not in enqueuers:
                    continue
                # WHERE THE JOB NAME ACTUALLY SITS, per callee (P6.9). This inspected
                # `node.args[0]` for every enqueuer — and `enqueue_outbox`'s first
                # positional is the SESSION, so the check was entirely inert for every
                # outbox call site, which is the majority of them. Measured against the
                # tree at the time: two invisible keyword literals.
                #
                # The keyword form is checked for all three, because `enqueue(job=...)`
                # and `enqueue_outbox(job=...)` are both legal and both hide the name from
                # a positional-only reader.
                candidates: list[ast.expr] = []
                if name == "enqueue_outbox":
                    # `enqueue_outbox(session, job, payload, ...)` — index 1.
                    if len(node.args) > 1:
                        candidates.append(node.args[1])
                elif node.args:
                    candidates.append(node.args[0])
                candidates += [kw.value for kw in node.keywords if kw.arg == "job"]
                for candidate in candidates:
                    if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                        rel = path.relative_to(REPO_ROOT)
                        offenders.append(f"{rel}:{node.lineno} → {candidate.value!r}")
    assert not offenders, (
        "a job name was passed as a literal, which makes it invisible to the registration "
        f"guard above: {offenders}. Declare it as a module-level *_JOB constant."
    )
