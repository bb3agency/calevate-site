"""The background fleet's wiring guard, proved against the states it exists to catch.

`scripts/check_job_wiring.py` is the gate; this file is the evidence that the gate can
go red — the shape `tests/wiring_guard_test.py` uses for `check_wiring`, and for the
same reason: a check nobody has watched fail is a check nobody knows is connected.

WHAT THIS FILE USED TO BE, AND WHY IT IS NOT THAT ANY MORE. It carried its own AST scan
over `*_JOB*` constants and asked ONE of the three questions (enqueued-but-unregistered).
Two ways of asking one question is the defect CLAUDE.md names even when both work, and
the second one is where the drift starts — this file's own docstring recorded three
shapes its scan had silently stopped seeing. The scan now lives in the script, the
script is in `make guardrails` and in CI, and this file mutates the script's inputs.

THE THREE SHAPES, each reconstructed from a state that actually shipped here:

* `notify_hot_lead_whatsapp` — written against the WhatsApp seam and never added to
  `FUNCTIONS`. The outbox published it, arq did not recognise the name, and every screen
  reported the message as queued.
* a job function defined and registered nowhere — it cannot run, and it reads as a
  feature in review.
* a registration nothing enqueues — the registry is where a reader learns what the
  system does, so a name nothing reaches is a lie told to the next person.
"""

from __future__ import annotations

import pytest
from apps.workers.settings import CRON_JOBS
from scripts import check_job_wiring
from scripts.check_job_wiring import EnqueueSite, JobDefinition

# --- the standing assertions (the same call `make guardrails` makes) ----------


def test_the_live_tree_is_wired_three_ways() -> None:
    assert check_job_wiring.main() == 0


def test_the_scan_is_not_blind() -> None:
    """The floors, checked on the real tree. Everything below mutates inputs; this is
    the one assertion that the inputs are real."""
    assert check_job_wiring.blindness() == []


def test_the_registry_the_guard_reads_is_the_one_the_worker_boots() -> None:
    """Rebind `WorkerSettings.functions` and every assertion in this file becomes a
    statement about a list nobody executes."""
    assert check_job_wiring.registry_is_the_one_the_worker_boots() == []


def test_the_registry_has_no_duplicate_names() -> None:
    """Two functions answering to one name means one of them never runs, and which one
    depends on registration order — a coin flip nobody would think to look at."""
    from apps.workers.settings import FUNCTIONS

    names = [getattr(fn, "__name__", "") for fn in FUNCTIONS]
    assert len(names) == len(set(names)), f"duplicate job names in FUNCTIONS: {names}"


def test_tracing_did_not_rename_a_job() -> None:
    """`traced_job` wraps every entry. If it stopped preserving `__name__`, every job
    would register under the wrapper's own name and the three comparisons above would
    still agree — against a registry of identical names."""
    names = check_job_wiring.registered_functions() | check_job_wiring.registered_crons()
    assert "wrapper" not in names and "inner" not in names, f"traced_job renames: {sorted(names)}"
    assert "run_post_call_pipeline" in names, "the registry lost a job it has always had"


# --- shape 1: defined and never registered ------------------------------------


def test_a_job_function_nobody_registered_is_caught() -> None:
    definitions = check_job_wiring.defined_jobs()
    registered = check_job_wiring.registered_functions() | check_job_wiring.registered_crons()
    assert check_job_wiring.defined_but_not_registered(definitions, registered) == []

    orphan = JobDefinition("reap_abandoned_widgets", "apps/workers/widgets.py:12")
    offenders = check_job_wiring.defined_but_not_registered([*definitions, orphan], registered)
    assert len(offenders) == 1 and "reap_abandoned_widgets" in offenders[0], offenders
    assert "can never run" in offenders[0]


def test_the_definition_scan_subtracts_the_lifecycle_hooks_and_only_those() -> None:
    """The scan's own blind spot, asserted rather than trusted.

    arq's four worker hooks share the job signature, so they must be subtracted — and
    the subtraction is read off `WorkerSettings` rather than hardcoded, because a
    hardcoded name survives a rename and goes on excluding a set it is no longer in.
    A hook that stopped being subtracted would make this guard cry wolf four times; a
    JOB that started being subtracted would make it blind, which is worse.
    """
    hooks = check_job_wiring.lifecycle_hook_names()
    assert hooks == {"startup", "shutdown", "on_job_start", "on_job_end"}, hooks
    defined = {definition.name for definition in check_job_wiring.defined_jobs()}
    assert not defined & hooks, "a lifecycle hook is being counted as a job"
    assert "run_post_call_pipeline" in defined and "apply_retention" in defined


# --- shape 2: registered and never enqueued -----------------------------------


def test_a_registration_nothing_enqueues_is_caught() -> None:
    functions = check_job_wiring.registered_functions()
    crons = check_job_wiring.registered_crons()
    sites = check_job_wiring.enqueue_sites()
    assert check_job_wiring.registered_but_never_enqueued(functions, crons, sites) == []

    # Every call site for ONE job removed, which is what deleting the last producer of a
    # side effect actually looks like in a diff.
    orphaned = [site for site in sites if site.job != "notify_hot_lead"]
    offenders = check_job_wiring.registered_but_never_enqueued(functions, crons, orphaned)
    assert len(offenders) == 1 and offenders[0].startswith("notify_hot_lead "), offenders


def test_a_cron_is_not_reported_as_unenqueued() -> None:
    """Crons are exempt BY CONSTRUCTION, not by exemption: `cron()` takes the coroutine
    by reference and the schedule IS the trigger. A guard that demanded an enqueuer for
    `apply_retention` would be reporting twelve false positives on a clean tree, which
    is how a guardrail gets an allowlist and then stops meaning anything."""
    crons = check_job_wiring.registered_crons()
    assert "apply_retention" in crons and "dispatch_campaign_tick" in crons
    offenders = check_job_wiring.registered_but_never_enqueued(
        check_job_wiring.registered_functions(), crons, []
    )
    assert not any(name in offender for name in crons for offender in offenders), offenders


# --- shape 3: enqueued by a name no worker answers to -------------------------


def test_an_enqueue_for_an_unregistered_name_is_caught() -> None:
    """`notify_hot_lead_whatsapp` as it actually shipped: the call site existed, the
    registration did not."""
    sites = check_job_wiring.enqueue_sites()
    registered = check_job_wiring.registered_functions() | check_job_wiring.registered_crons()
    assert check_job_wiring.enqueued_but_not_registered(sites, registered) == []

    offenders = check_job_wiring.enqueued_but_not_registered(
        sites, registered - {"notify_hot_lead_whatsapp"}
    )
    assert len(offenders) == 1 and "notify_hot_lead_whatsapp" in offenders[0], offenders
    assert "no worker registers" in offenders[0]


def test_the_enqueue_scan_reads_the_outbox_call_sites() -> None:
    """The half the predecessor guard was entirely inert for.

    `enqueue_outbox`'s first positional is the SESSION, so a scan that read `args[0]`
    for every callee saw nothing at every outbox call site — which is most of them, and
    the ones where an unrecognised name is published and reported as delivered.
    """
    resolved = {site.job for site in check_job_wiring.enqueue_sites()}
    for job in (
        "deliver_auth_email",  # keyword `job=`, outbox
        "execute_deletion_request",  # keyword `job=`, outbox
        "notify_hot_lead_whatsapp",  # keyword `job=`, outbox-once
        "run_post_call_pipeline",  # positional, direct enqueue
        "record_in_call_optout",  # positional, from voice-runtime
    ):
        assert job in resolved, f"the enqueue scan cannot see {job}'s call site"


def test_both_constant_spellings_resolve(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`X = "..."` and `X: Final = "..."` both name a job here, and reading only the
    first is how one constant went unchecked for as long as it did."""
    (tmp_path / "producer.py").write_text(
        "from typing import Final\n"
        'PLAIN_JOB = "plain_job"\n'
        'ANNOTATED_JOB: Final = "annotated_job"\n'
        "def go(session):\n"
        "    enqueue(PLAIN_JOB, {})\n"
        "    enqueue_outbox(session, job=ANNOTATED_JOB, payload={})\n"
    )
    resolved = {site.job for site in check_job_wiring.enqueue_sites(roots=(tmp_path,))}
    assert resolved == {"plain_job", "annotated_job"}, resolved


def test_a_literal_job_name_is_resolved_rather_than_missed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The predecessor's stated blind spot, closed rather than forbidden.

    It banned bare literals at call sites because its scan started from CONSTANTS and a
    literal was invisible to it. This scan starts from CALL SITES, so a literal is read
    like anything else — which is strictly stronger, and it removes a rule that only
    existed to prop up the old mechanism.
    """
    (tmp_path / "producer.py").write_text('def go():\n    enqueue("some_forgotten_job", {})\n')
    sites = check_job_wiring.enqueue_sites(roots=(tmp_path,))
    assert [site.job for site in sites] == ["some_forgotten_job"]
    offenders = check_job_wiring.enqueued_but_not_registered(sites, {"run_post_call_pipeline"})
    assert len(offenders) == 1 and "some_forgotten_job" in offenders[0], offenders


# --- the hole in shape 3: a name the scan cannot read -------------------------


def test_an_unresolvable_job_name_fails_unless_acknowledged(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """An unresolved name is a name that cannot be compared against the registry, so
    passing it would let the silent failure walk straight through the gate."""
    (tmp_path / "producer.py").write_text(
        "def go(row):\n    enqueue(row.whatever_job, {})\n",
    )
    sites = check_job_wiring.enqueue_sites(roots=(tmp_path,))
    assert [site.job for site in sites] == [None]
    offenders = check_job_wiring.unresolvable_enqueue_sites(sites)
    assert len(offenders) == 1 and "cannot be checked against the registry" in offenders[0]


def test_the_one_dynamic_site_is_the_outbox_drain_and_it_is_still_there() -> None:
    """The exemption, and the anti-rubber-stamp half: it must still match a real site.

    An entry that no longer matches anything is a hole with a comment on it
    (`check_wiring.stale_baseline`, `check_redaction_exposure.check_registry_freshness`).
    """
    sites = check_job_wiring.enqueue_sites()
    assert check_job_wiring.unresolvable_enqueue_sites(sites) == []
    assert check_job_wiring.stale_exemptions(sites) == []
    assert set(check_job_wiring.DYNAMIC_ENQUEUE_SITES) == {
        "apps/workers/dispatcher.py::message.job"
    }
    offenders = check_job_wiring.stale_exemptions(
        [site for site in sites if site.key != "apps/workers/dispatcher.py::message.job"]
    )
    assert len(offenders) == 1 and "only shrinks" in offenders[0], offenders


# --- the scan refusing rather than passing ------------------------------------


@pytest.mark.parametrize(
    ("definitions", "registered", "sites", "expected"),
    [
        ([], None, None, "definition scan"),
        (None, set(), None, "worker registry"),
        (None, None, [], "enqueue scan found 0"),
        (
            None,
            None,
            [EnqueueSite(None, "a.py::x", "a.py:1 → enqueue(x)")] * 40,
            "resolved 0 distinct",
        ),
    ],
)
def test_a_scan_that_matches_nothing_refuses(
    definitions: list[JobDefinition] | None,
    registered: set[str] | None,
    sites: list[EnqueueSite] | None,
    expected: str,
) -> None:
    """`check_wiring`'s doctrine, applied here: three of these sets are only ever
    compared against each other, so an empty scan agrees perfectly with an empty
    registry and prints OK. That is the one output a guardrail must never produce for a
    reason unrelated to the tree."""
    failures = check_job_wiring.blindness(
        check_job_wiring.defined_jobs() if definitions is None else definitions,
        (check_job_wiring.registered_functions() | check_job_wiring.registered_crons())
        if registered is None
        else registered,
        check_job_wiring.enqueue_sites() if sites is None else sites,
    )
    assert any(expected in failure for failure in failures), failures


def test_the_seam_signatures_are_read_and_not_remembered() -> None:
    """`ENQUEUE_SEAMS` says where each callee keeps its job name. If `enqueue_outbox`
    grew a positional `job`, the AST reader would be looking at the session argument and
    reporting a clean tree — so the map is checked against the real signatures."""
    assert check_job_wiring._assert_the_seams_still_look_like_this() == []
    original = dict(check_job_wiring.ENQUEUE_SEAMS)
    try:
        check_job_wiring.ENQUEUE_SEAMS["enqueue_outbox"] = 1
        assert check_job_wiring._assert_the_seams_still_look_like_this() != []
    finally:
        check_job_wiring.ENQUEUE_SEAMS.clear()
        check_job_wiring.ENQUEUE_SEAMS.update(original)


# ---------------------------------------------------------------- the retry ladder
#
# THE FOURTH WAY A JOB IS WIRED AND STILL DOES NOT WORK, and nothing checked it across
# the fleet (D-361). `arq.cron()` defaults `max_tries` to 1, and `WorkerSettings.
# max_tries` is only the default for a function that does NOT carry its own — so a cron
# registered without it has NO ladder, whatever the class attribute says. Its `raise
# Retry` is honoured exactly zero times, and its terminal `alert()` — the only
# dead-letter mechanism this repo has (`settings.py`) — can never be reached, because
# the job is finished the first time it fails.
#
# `check_job_wiring` cannot see this: it proves a name is DEFINED, REGISTERED and
# REACHED, which is a question about the registry's three sides and not about the
# arguments one registration was given. Eight `cron()` call sites argue `max_tries` at
# length in prose, and four individual tests (`kb_drift_reconciliation_test`,
# `qa_sampling_test`, `setup_fee_test`, `reconciliation_sweep_isolation_test`) pin it for
# the four crons somebody remembered. The NEXT cron gets none of that: it is registered,
# it looks green, and it has one attempt.
#
# So the rule is INVERTED here: every cron carries a real ladder unless it is named
# below with the reason it does not need one. A count in prose is the defect class
# `db/registry.APPEND_ONLY_TABLES` exists for; this is the same instrument.

#: Crons that legitimately run with `max_tries=1`, and why. An entry has to say what
#: makes the NEXT TICK a sufficient retry — that is the only argument that works, and it
#: only works for a cadence measured in seconds.
NO_LADDER_NEEDED: dict[str, str] = {
    "cron:dispatch_outbox": (
        "every ten seconds, and recovery is structurally the next tick: a claimed row's "
        "lease is minutes, so an aborted tick's messages return to the claim with their "
        "attempt counts intact. An arq ladder on top would re-run the same tick inside "
        "the lease and find nothing to do (`dispatcher.dispatch_outbox`)"
    ),
    "cron:dispatch_campaign_tick": (
        "every thirty seconds, single-flighted by `campaign_dispatch._tick_lease` rather "
        "than by arq. A retried tick would be a SECOND tick racing the lease of the one "
        "after it, and the work it dropped — claimed contacts — is already recovered by "
        "`_reap_stuck_dialing` and by the claim CAS itself"
    ),
}


def test_every_cron_has_a_retry_ladder_or_says_why_it_does_not() -> None:
    """The assertion `apply_retention` would have failed before P6.2 (D-361).

    `max_tries=1` on a nightly legal obligation meant one transient database error, or a
    deploy landing at 03:40, and the night's retention sweep was gone until tomorrow with
    nothing marked wrong.
    """
    ladderless = {
        job.name: job.max_tries
        for job in CRON_JOBS
        if (job.max_tries or 1) <= 1 and job.name not in NO_LADDER_NEEDED
    }
    assert not ladderless, (
        "these crons are registered with no retry ladder — `cron()` defaults max_tries "
        f"to 1 and `WorkerSettings.max_tries` does not reach them: {ladderless}. Pass "
        "`max_tries=WORKER_MAX_TRIES` at the `cron()` call site, or add an entry to "
        "`NO_LADDER_NEEDED` saying what makes the next tick a sufficient retry."
    )


def test_the_ladder_exemptions_still_name_crons_that_exist() -> None:
    """A stale exemption is worse than none: it silently covers whatever cron inherits
    the name, and it makes the list above read as broader coverage than it has."""
    registered = {job.name for job in CRON_JOBS}
    stale = sorted(set(NO_LADDER_NEEDED) - registered)
    assert not stale, f"NO_LADDER_NEEDED names crons that are no longer registered: {stale}"


def test_the_exempt_crons_are_the_ones_that_actually_run_in_seconds() -> None:
    """The exemption's whole argument is "the next tick is the retry", which is only true
    at a cadence measured in seconds. Asserted rather than trusted, because an edit that
    moved one of these onto an hourly schedule would keep the exemption and lose the
    property it rests on.

    `isinstance(..., set)` rather than a truth test: arq stores `second=0` for a cron
    registered on `minute=`, and `0` is falsy for the wrong reason — a sub-minute cron
    registered as `second={0}` would be a set, be truthy, and pass a truth test that a
    `minute=`-only cron also passes by accident.
    """
    by_name = {job.name: job for job in CRON_JOBS}
    for name in NO_LADDER_NEEDED:
        job = by_name[name]
        assert isinstance(job.second, set) and len(job.second) > 1, (
            f"{name} is exempt from the retry ladder because its next tick comes in "
            f"seconds, but it is registered on second={job.second!r} — that argument no "
            "longer holds, so it needs a real `max_tries` instead"
        )
