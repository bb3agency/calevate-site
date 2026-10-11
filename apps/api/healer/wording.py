"""What the founder reads on `/admin/ops/healer`: every incident kind and every incident's
progress, in plain words (founder, 11 Oct 2026).

One catalogue, server-side, because the codes it translates are server facts: the browser
renders `IncidentOut.kind` and `IncidentOut.progress` and never re-derives either. The raw
code still travels beside the words, since ops searches logs by it.

Each `meaning` and `next_step` restates the code's row in `runbooks/alarm-index.md` (and
`runbooks/auto-healer.md` for the healer's own codes), so a change of behaviour there must
change the line here. Admin-only copy: it may name ThinnestAI where the alarm is specific to
that engine; client screens never read this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from apps.api.healer.playbooks import (
    AGENT_HEALTH_DEGRADED,
    AGENT_LINE_BROKEN,
    ENGINE_PLATFORM_OUTAGE,
    STATUS_POST,
)


@dataclass(frozen=True, slots=True)
class IncidentKind:
    #: A short name for the problem, in plain words.
    title: str
    #: One line on what it means.
    meaning: str
    #: One line on what the founder does about it.
    next_step: str


#: Every code an incident can be opened with: each playbook trigger, plus a status post an
#: operator wrote by hand. `tests/healer_wording_test.py` fails when one is missing.
INCIDENT_KINDS: Final[Mapping[str, IncidentKind]] = {
    "engine_webhook_redelivery_failed": IncidentKind(
        title="Missed call updates could not be re-sent",
        meaning="An agent's call-update link was switched back on, but ThinnestAI refused to "
        "re-send the updates that failed in the last 7 days.",
        next_step="In ThinnestAI's console, open the agent's webhook and press Re-send "
        "failed. Updates we already have are skipped.",
    ),
    "engine_webhook_sweep_incomplete": IncidentKind(
        title="Some agents' call-update links could not be checked",
        meaning="The check could not reach some agents' links (ThinnestAI's API, our "
        "credentials or our intake key), so a switched-off link may still be losing updates.",
        next_step="Nothing at first: the check runs again every 20 minutes. If it stays, the "
        "worker log line engine_webhook_check_failed says why.",
    ),
    "engine_workspace_provisioning_failed": IncidentKind(
        title="A client's ThinnestAI workspace could not be set up",
        meaning="After its retries, the client's own workspace could not be found or created "
        "(credentials, a missing key or ThinnestAI down; not the plan limit).",
        next_step="Open the client's admin page for the error, fix the cause, then press "
        "Retry provisioning.",
    ),
    "outbox_dead_letter": IncidentKind(
        title="Background jobs failed after every retry",
        meaning="Some queued jobs used up all their attempts. The healer puts them back on "
        "the queue, at most twice.",
        next_step="Nothing unless it is handed to you. Then follow the webhook delivery "
        "runbook, section 3.",
    ),
    AGENT_HEALTH_DEGRADED: IncidentKind(
        title="An agent's calls are going worse than usual",
        meaning="Its call health has been below its own normal level for three 15-minute "
        "windows in a row. The healer is checking and repairing its settings.",
        next_step="Nothing unless it is handed to you. If the agent's script is the cause, "
        "the client gets a suggested fix to approve.",
    ),
    AGENT_LINE_BROKEN: IncidentKind(
        title="An agent's calls are failing",
        meaning="Most of its recent real calls failed or ended within ten seconds. The healer "
        "repairs once, then holds the line and tells the client if calls still fail.",
        next_step="Watch here. If the line breaks again after being given back, find the "
        "cause (often the agent's script) and turn the line back on.",
    ),
    ENGINE_PLATFORM_OUTAGE: IncidentKind(
        title="The voice platform is down",
        meaning="Several clients' lines broke at once, or the voice platform failed many "
        "requests in ten minutes or says calls are down. Every line is held, every campaign "
        "paused, and the status page posted.",
        next_step="Confirm with the voice platform. Do not mark it handled while it still "
        "fails: the healer gives lines back after 15 quiet minutes.",
    ),
    "engine_charge_mismatch": IncidentKind(
        title="Call charges don't match our records",
        meaning="For some calls, what ThinnestAI charged differs from what we metered by more "
        "than ₹0.10 or 2%, so the per-minute rate we hold is wrong.",
        next_step="Compare the named calls in ThinnestAI's Usage → Calls with ours, then "
        "attest the corrected posted rate, before the top-up fee, from when it changed.",
    ),
    "engine_charge_unmatched": IncidentKind(
        title="ThinnestAI's charges could not be matched to our calls",
        meaning="None of the charged calls in ThinnestAI's call log matched a call we "
        "metered, so charges are not being checked.",
        next_step="If calls have been metered, compare one call's id in Usage → Calls with "
        "ours and report the difference.",
    ),
    "engine_call_cost_variance": IncidentKind(
        title="A call cost differently than we metered",
        meaning="ThinnestAI's charge for a call, with the wallet top-up fee, differs from our "
        "metered cost by more than ₹0.10 or 2%.",
        next_step="Attest ThinnestAI's posted per-minute rate, before the top-up fee, from "
        "when it changed. Past calls are not re-priced.",
    ),
    STATUS_POST: IncidentKind(
        title="A notice posted on the status page",
        meaning="Someone on the team posted this problem on the public status page by hand.",
        next_step="Mark it as handled when the problem is over; the status page then shows "
        "it as resolved.",
    ),
}


def incident_kind(code: str) -> IncidentKind:
    """The catalogue entry for `code`. A code missing from it still renders, as itself,
    rather than failing the whole list; the test keeps that from shipping."""
    kind = INCIDENT_KINDS.get(code)
    if kind is not None:
        return kind
    return IncidentKind(
        title=code.replace("_", " ").capitalize(),
        meaning="No plain description is recorded for this problem yet.",
        next_step="Look the code up in the alarm index.",
    )


def _tries(n: int) -> str:
    return "1 try" if n == 1 else f"{n} tries"


#: Where a held line's callers go, by the hold `apply_healer_silence` reported.
_HELD: Final[Mapping[str, str]] = {
    "forwarded": "Line held: callers are sent to the client's backup phone",
    "paused": "Line held: callers hear a polite can't-take-your-call message",
    "held": "Line held: its numbers were already taken off",
}


def progress(
    *, playbook: str, automatic: bool, state: str, attempts: int, last_outcome: str | None
) -> str:
    """Where the incident stands, in one plain line. `last_outcome` is the vocabulary
    `apps/workers/healer.py` writes; `signal:<name>` is the scorer's worst signal."""
    outcome = last_outcome or ""
    if state == "resolved":
        if outcome == "restored_by_person":
            return "Marked as handled by a person"
        if outcome == "verified":
            if attempts == 0:
                return "Fixed automatically"
            return f"Fixed automatically after {_tries(attempts)}"
        return "Closed"
    if outcome == "paused":
        return "Waiting: this repair is switched off in configuration"
    if playbook == STATUS_POST:
        return "Posted by hand; stays up until you mark it as handled"
    if state == "escalated":
        if not automatic:
            return "Not fixable automatically, handed to you"
        if outcome == "held_for_person":
            return "Line broke again after it was given back; held until you turn it back on"
        if attempts == 0:
            return "Handed to you"
        return f"Automatic fix tried {_tries(attempts)} without clearing it; handed to you"
    if state == "open":
        if not automatic:
            return "Just found; being handed to you"
        return "Just found; the automatic fix runs on the next minute's check"
    # mitigated: the healer has acted and is waiting to see whether it worked.
    if outcome == "held":
        return "Every line held; waiting for 15 quiet minutes"
    if outcome.startswith("held:"):
        return _HELD.get(outcome.removeprefix("held:"), "Line held") + "; checking every 15 minutes"
    if outcome == "probation":
        return "Line given back; watching it for two hours"
    if outcome == "repaired":
        return "Repaired; checking that calls work again"
    if outcome == "act_failed":
        return f"Fix attempt {attempts} hit an error; checking again shortly"
    return f"Automatic fix tried ({_tries(attempts)}); checking that it worked"


__all__ = ["INCIDENT_KINDS", "IncidentKind", "incident_kind", "progress"]
