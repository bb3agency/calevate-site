"""THE registry of what the healer may do without a person (D-701).

Every automatic repair on this platform is a row here: what wakes it, what it does, how it
proves the repair worked, how often it may try, what undoes it, and how far a mistake
could reach. The seven repair sweeps that each ran on their own clock are rows too
(`job`), so there is one place that answers "what fixes itself", one kill switch per row
(`Settings.healer_paused_playbooks`) and one global (`Settings.healer_enabled`), and one
ledger (`heal_actions`) of everything any of them did.

What is NOT here, and cannot be added: anything that changes how an agent behaves — its
prompt, voice, model, knowledge or disclosure lines. Those are proposals
(`healer/proposals.py`) a person approves. The model is the narrow, pre-approved,
verified, reversible actions AI-SRE tools automate (Datadog Bits AI, Rootly), not a
general fixer; no voice-AI vendor sells true self-healing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from apps.api.core.settings import get_settings

#: How far a wrong action could reach: one agent's line, one client, or every client.
BlastRadius = Literal["agent", "tenant", "platform"]

#: Raised by the health score (`healer/health.py`), never by a single call: an agent whose
#: score sat below its own baseline for `SUSTAINED_WINDOWS` windows.
AGENT_HEALTH_DEGRADED: Final = "agent_health_degraded"
#: Most of an agent's recent real calls failed or ended inside ten seconds.
AGENT_LINE_BROKEN: Final = "agent_line_broken"
#: Engine failures across the fleet, or broken lines at several clients at once.
ENGINE_PLATFORM_OUTAGE: Final = "engine_platform_outage"


@dataclass(frozen=True, slots=True)
class Playbook:
    key: str
    #: Operator wording for the healer page.
    title: str
    #: Alarm codes that open an incident for this playbook.
    triggers: tuple[str, ...]
    #: What it does, how it proves it worked, and what undoes it, in operator words.
    action: str
    verify: str
    undo: str
    max_attempts: int
    cooldown_s: int
    blast_radius: BlastRadius
    #: The repair sweep this playbook runs on its schedule (`workers/settings.CRON_JOBS`).
    job: str | None = None
    #: False for a playbook that only opens an incident and pages: money is never moved
    #: by the healer.
    automatic: bool = True
    #: False when the playbook also enforces a hard rule, so no switch may stop it.
    pausable: bool = True


PLAYBOOKS: Final[tuple[Playbook, ...]] = (
    # ---- the seven repair sweeps, absorbed -----------------------------------------
    Playbook(
        key="engine_drift",
        title="Agent settings drift repair",
        triggers=(),
        action="Read every live agent back from the voice platform; put our settings, "
        "in-call actions and voice key back where they moved.",
        verify="The next read-back of the same agent matches.",
        undo="None needed: it writes only values our own records decide.",
        max_attempts=4,
        cooldown_s=30 * 60,
        blast_radius="agent",
        job="sweep_engine_drift",
        # The same read-back is what silences an agent proven to have lost its
        # truthful-answer rule (hard rule 5), so neither kill switch may stop it.
        pausable=False,
    ),
    Playbook(
        key="engine_webhooks",
        title="Call-event delivery repair",
        triggers=("engine_webhook_redelivery_failed", "engine_webhook_sweep_incomplete"),
        action="Re-register, re-enable or resubscribe each agent's call-event endpoint and "
        "ask the platform to redeliver the last seven days.",
        verify="The alarm that woke it has not recurred since the repair.",
        undo="None needed: the endpoint is ours.",
        max_attempts=3,
        cooldown_s=20 * 60,
        blast_radius="platform",
        job="reconcile_engine_webhooks",
    ),
    Playbook(
        key="workspace_retry",
        title="Client workspace retry",
        triggers=("engine_workspace_provisioning_failed",),
        action="Queue the client's voice-platform workspace again.",
        verify="The client's workspace is active.",
        undo="None needed: a workspace is created once and reused.",
        max_attempts=3,
        cooldown_s=60 * 60,
        blast_radius="tenant",
        job="retry_engine_workspaces",
    ),
    Playbook(
        key="workspace_sweep",
        title="Client workspace upkeep",
        triggers=(),
        action="Resubmit expired business details, check each workspace inherits our voice "
        "key, forget clones the platform no longer holds.",
        verify="The sweep finished its walk.",
        undo="None needed.",
        max_attempts=1,
        cooldown_s=24 * 60 * 60,
        blast_radius="tenant",
        job="sweep_engine_workspaces",
    ),
    Playbook(
        key="kb_drift",
        title="Knowledge drift check",
        triggers=(),
        action="Compare each agent's knowledge on the platform with ours and record drift.",
        verify="The sweep finished its batch.",
        undo="None needed: it records only.",
        max_attempts=1,
        cooldown_s=60 * 60,
        blast_radius="agent",
        job="sweep_kb_drift",
    ),
    Playbook(
        key="number_reconcile",
        title="Phone number attachment repair",
        triggers=(),
        action="Put each number's agent back where the platform moved it; alarm on numbers "
        "rented but unrecorded.",
        verify="The sweep finished its walk.",
        undo="None needed: the attachment our records name is the right one.",
        max_attempts=1,
        cooldown_s=24 * 60 * 60,
        blast_radius="tenant",
        job="reconcile_engine_numbers",
    ),
    Playbook(
        key="charge_reconcile",
        title="Call charge reconciliation",
        triggers=(),
        action="Compare what the platform charged per call with what we metered.",
        verify="The sweep finished its walk.",
        undo="None needed: it records only.",
        max_attempts=1,
        cooldown_s=60 * 60,
        blast_radius="platform",
        job="reconcile_engine_charges",
    ),
    # ---- woken by an alarm ------------------------------------------------------------
    Playbook(
        key="outbox_replay",
        title="Dead-letter replay",
        triggers=("outbox_dead_letter",),
        action="Put each job's dead letters back on the queue, one job at a time.",
        verify="That job's dead-letter count is back to zero.",
        undo="None needed: every queued job is idempotent on its key.",
        max_attempts=2,
        cooldown_s=30 * 60,
        blast_radius="platform",
    ),
    Playbook(
        key="agent_repair",
        title="Agent plumbing repair",
        triggers=(AGENT_HEALTH_DEGRADED,),
        action="Re-check and repair one agent's settings, call-event endpoint and in-call "
        "actions; propose a fix to the client when the cause is the agent's own behaviour.",
        verify="The agent's next scored windows are back within its baseline.",
        undo="None needed: it writes only values our own records decide.",
        max_attempts=2,
        cooldown_s=30 * 60,
        blast_radius="agent",
    ),
    Playbook(
        key="line_protection",
        title="Line protection",
        triggers=(AGENT_LINE_BROKEN,),
        action="Repair once; if calls still fail, hand callers to the client's own phone "
        "where the platform can, otherwise answer with a polite can't-take-your-call line; "
        "pause the agent's campaigns; tell the client.",
        verify="The agent reads back cleanly and the voice platform has answered without "
        "errors for fifteen minutes; then the line is given back and watched for two hours.",
        undo="Give the line back with a verified publish, resume only the campaigns it "
        "paused, and re-queue attempts that failed during the incident.",
        max_attempts=2,
        cooldown_s=15 * 60,
        blast_radius="agent",
    ),
    Playbook(
        key="engine_outage",
        title="Voice platform outage",
        triggers=(ENGINE_PLATFORM_OUTAGE,),
        action="Post on the status page, protect every client's line, pause every campaign "
        "and page the founder. There is no second voice platform to move calls to.",
        verify="No platform failures for fifteen minutes and agents read back.",
        undo="Give every line back, resume the campaigns it paused, re-queue failed attempts.",
        max_attempts=1,
        cooldown_s=5 * 60,
        blast_radius="platform",
    ),
    Playbook(
        key="money_review",
        title="Money mismatch review",
        triggers=("engine_charge_mismatch", "engine_charge_unmatched", "engine_call_cost_variance"),
        action="Open an incident and page. The healer never moves money.",
        verify="A person resolves the incident.",
        undo="Not applicable.",
        max_attempts=0,
        cooldown_s=24 * 60 * 60,
        blast_radius="platform",
        automatic=False,
    ),
    Playbook(
        key="status_post",
        title="Status page post",
        triggers=(),
        action="An operator posted a problem on the public status page by hand.",
        verify="The operator resolves it.",
        undo="Take it off the page or resolve it.",
        max_attempts=0,
        cooldown_s=24 * 60 * 60,
        blast_radius="platform",
        automatic=False,
    ),
)

PLAYBOOK_BY_KEY: Final[dict[str, Playbook]] = {p.key: p for p in PLAYBOOKS}
PLAYBOOK_BY_JOB: Final[dict[str, Playbook]] = {p.job: p for p in PLAYBOOKS if p.job}
PLAYBOOK_BY_TRIGGER: Final[dict[str, Playbook]] = {
    code: p for p in PLAYBOOKS for code in p.triggers
}


def paused_keys(raw: str | None = None) -> frozenset[str]:
    """The playbook keys the console paused. Unknown keys are kept so the page can flag them."""
    value = get_settings().healer_paused_playbooks if raw is None else raw
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def unknown_paused_keys() -> tuple[str, ...]:
    return tuple(sorted(paused_keys() - PLAYBOOK_BY_KEY.keys()))


def may_run(key: str) -> bool:
    """Whether the kill switches let this playbook act right now (read per call)."""
    playbook = PLAYBOOK_BY_KEY.get(key)
    if playbook is not None and not playbook.pausable:
        return True
    return get_settings().healer_enabled and key not in paused_keys()


__all__ = [
    "AGENT_HEALTH_DEGRADED",
    "AGENT_LINE_BROKEN",
    "ENGINE_PLATFORM_OUTAGE",
    "PLAYBOOKS",
    "PLAYBOOK_BY_JOB",
    "PLAYBOOK_BY_KEY",
    "PLAYBOOK_BY_TRIGGER",
    "BlastRadius",
    "Playbook",
    "may_run",
    "paused_keys",
    "unknown_paused_keys",
]
