"""What an alarm means to a person: a plain headline, who it affects, and what to do.

WHERE EACH PART COMES FROM, AND WHY TWO SOURCES RATHER THAN ONE NEW ONE. "What it means"
and "what to do" are read at send time from `runbooks/alarm-index.md`, the operator's own
document: it ships in the image (`Dockerfile` copies `runbooks/` for D-499),
`scripts/check_alarm_wiring.py` already forces one row per raised code, and any copy of
those two columns kept here would drift from the document an operator is told to trust.
The index has no plain-language headline and no "who is affected" column, and adding them
across 400 rows of a file other work edits would be a rewrite; so those two short fields
live in `ALARM_SUMMARIES` below, for the `page` codes only (the one rung that mails), and
the same gate refuses a `page` code with no summary or a summary for a code that is not a
`page`.

Everything here is OUR text. It is still HTML-escaped by the composer like any value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: `runbooks/alarm-index.md`, resolved from this file: `apps/api/core` -> repo root.
ALARM_INDEX: Final = Path(__file__).resolve().parents[3] / "runbooks" / "alarm-index.md"
_ALARM_HEADING: Final = "## Alarm codes"


@dataclass(frozen=True, slots=True)
class AlarmSummary:
    """Two sentences a non-engineer can act on. `headline` is sentence case, no full stop."""

    headline: str
    affects: str


def _s(headline: str, affects: str) -> AlarmSummary:
    return AlarmSummary(headline=headline, affects=affects)


_BACKUP_AFFECTS: Final = (
    "No client is affected right now. What is at risk is our ability to restore the "
    "database after a failure."
)
_SECRET_AFFECTS: Final = (
    "Every client. The features that need this secret stop rather than run unprotected "
    "until it is restored."
)

#: Keyed by the code exactly as `alert()` receives it, minus any `:Suffix`.
ALARM_SUMMARIES: Final[dict[str, AlarmSummary]] = {
    # --- the voice path ---------------------------------------------------------------
    "engine_error_spike": _s(
        "The voice platform is failing requests",
        "Every client: calls, agent publishes and call reconciliation can all fail until it "
        "recovers.",
    ),
    "engine_agent_drift_detected": _s(
        "A live agent is running a script we did not publish",
        "One client's callers are hearing a script someone edited outside Calevate.",
    ),
    "supermemory_index_purge_failed": _s(
        "An account erasure is blocked",
        "One client's erasure request: nothing was erased and no certificate was issued.",
    ),
    "engine_inbound_binding_failed": _s(
        "A client's number may not reach its agent",
        "Callers to one client's number may reach the wrong agent, or nothing.",
    ),
    "inbound_credit_cutover_failed": _s(
        "A credit change did not reach the voice platform",
        "One client: either a paying client's callers are being turned away, or calls are "
        "answered with no credit to pay for them.",
    ),
    "inbound_truthful_answer_silence_unsupported": _s(
        "An agent without its AI-disclosure rule is still answering calls",
        "Callers to one client's agent may not be told truthfully that it is an AI or that "
        "the call is recorded.",
    ),
    "number_bought_but_not_recorded": _s(
        "A phone number was bought but not recorded",
        "Our account: we are paying for a number that nothing in Calevate points at.",
    ),
    "number_rented_but_unrecorded": _s(
        "We are paying for numbers Calevate does not know about",
        "Our account: monthly rent is going on numbers that serve no client.",
    ),
    "number_recorded_but_not_held": _s(
        "A client's number is missing at the voice platform",
        "One client's inbound calls may be going unanswered.",
    ),
    "engine_ingest_abandoned": _s(
        "A finished call could not be recorded",
        "One call has no record, so its lead, transcript and usage are missing.",
    ),
    "engine_drift_sweep_abandoned": _s(
        "Live agents are no longer being checked",
        "Every client: changes made to a live agent outside Calevate go unnoticed until the "
        "check runs again.",
    ),
    "postcall_pipeline_stalled": _s(
        "Leads from finished calls are late",
        "Every client with recent calls: new leads are not appearing within the two-minute target.",
    ),
    "post_call_abandoned": _s(
        "A finished call was not processed",
        "One call has no lead, no extracted details and no usage record.",
    ),
    "cartesia_call_without_attested_tts_price": _s(
        "Studio voice calls are running without a price",
        "Our margin: these calls record no voice cost, so they look cheaper than they are.",
    ),
    "call_billable_without_cost": _s(
        "A billable call has no cost recorded",
        "Our margin: we were charged for a call we could not meter.",
    ),
    "engine_minute_rate_unattested": _s(
        "Calls are being metered without a per-minute price",
        "Our margin and client usage: the minutes are recorded with no cost.",
    ),
    "engine_publish_refused_unpriced": _s(
        "A client could not publish an agent because calling has no price",
        "One client is blocked from going live until a per-minute price is set.",
    ),
    "recording_source_gone": _s(
        "A call recording was lost before we copied it",
        "One call has its lead and transcript but no recording.",
    ),
    "recording_copy_at_risk": _s(
        "Call recordings will be lost within a week unless saved",
        "The clients whose calls are listed: those calls have no copy of their recording.",
    ),
    "engine_balance_exhausted": _s(
        "The voice platform balance cannot pay for calls",
        "Every client: outbound and test calls are refused until the balance is topped up.",
    ),
    "engine_dial_setup_refused": _s(
        "Calls can't be placed",
        "Every call through the refused agent or number fails, test calls included, until the "
        "set-up is fixed.",
    ),
    "engine_agent_settings_drifted": _s(
        "A live agent's settings are wrong and could not be repaired",
        "One client's agent may be able to dial, message or transfer outside our controls.",
    ),
    "engine_call_cost_variance": _s(
        "A call's cost does not match what we were charged",
        "Our margin: the price we meter for calls no longer matches the vendor's charge.",
    ),
    "engine_studio_synthesis_cost_missing": _s(
        "A Studio call is missing its voice cost",
        "Our margin: the call looks cheaper than it was.",
    ),
    "engine_key_cannot_place_calls": _s(
        "Our voice platform key cannot place calls",
        "Every client: every outbound and test call is refused.",
    ),
    "engine_charge_mismatch": _s(
        "Call charges do not match our price",
        "Our margin and client billing: every call's recorded cost may be wrong.",
    ),
    "engine_actions_unreachable": _s(
        "An agent's in-call actions cannot reach us",
        "Callers to one client's agent cannot opt out, book or be handed over during the call.",
    ),
    "dial_recall_unstopped": _s(
        "Some calls could not be stopped after outbound was halted",
        "Dials already accepted by the voice platform may still ring.",
    ),
    "dial_recall_incomplete": _s(
        "Not every queued call was checked after outbound was halted",
        "More dials may still be queued at the voice platform and could ring.",
    ),
    "dial_recall_impossible": _s(
        "Queued calls could not be recalled after outbound was halted",
        "Every dial already queued at the voice platform will still ring.",
    ),
    "dial_recall_abandoned": _s(
        "Recalling queued calls failed after outbound was halted",
        "Dials already accepted by the voice platform were not pulled back and will ring.",
    ),
    "dial_recall_not_queued": _s(
        "Outbound was halted but queued calls were not recalled",
        "Dials already accepted by the voice platform may still ring.",
    ),
    "dnc_recall_undetermined": _s(
        "We cannot confirm calls to a do-not-call number were stopped",
        "A person who asked not to be called may still be called.",
    ),
    "dnc_recall_incomplete": _s(
        "Not every call to a do-not-call number was checked",
        "More calls to a suppressed number may still be queued and could ring.",
    ),
    "dnc_recall_abandoned": _s(
        "Calls to a do-not-call number were not pulled back",
        "Calls already queued to a suppressed number may ring.",
    ),
    "outbound_pool_empty": _s(
        "No outbound lines are available",
        "Every client: no campaign can dial.",
    ),
    "dispatch_tenant_failed": _s(
        "Some clients were skipped by campaign dialling",
        "The named clients' campaigns and call-backs did not dial on this tick.",
    ),
    "campaign_complaint_spike": _s(
        "A campaign was paused after many opt-outs",
        "One client's campaign has stopped dialling.",
    ),
    # --- compliance and consent -------------------------------------------------------
    "retention_below_trai_floor": _s(
        "A retention setting is below the legal minimum",
        "One client: the retention sweep refused to delete their records.",
    ),
    "erasure_requests_overdue": _s(
        "An erasure request is past its deadline",
        "A person's data-deletion request has not been carried out in time.",
    ),
    "processor_erasure_overdue": _s(
        "A sub-processor still holds a caller's recording after erasure",
        "A person whose data we erased still has a copy at a sub-processor after 30 days.",
    ),
    "action_audit_unrecorded": _s(
        "An agent action ran without an audit record",
        "One client: the action happened, but the audit trail does not show it.",
    ),
    "tenant_erasure_mark_failed": _s(
        "An account erasure did not complete",
        "One closing client: nothing was erased.",
    ),
    # --- leads, notifications, integrations -------------------------------------------
    "auth_email_exhausted": _s(
        "A sign-in email could not be delivered",
        "Someone cannot sign in, reset a password or accept an invitation.",
    ),
    "job_function_not_registered": _s(
        "A background job was dropped",
        "Whatever that job does silently did not happen.",
    ),
    # --- the reliability path ---------------------------------------------------------
    "outbox_dead_letter": _s(
        "Background messages failed after every retry",
        "The side effects they carry (emails, syncs, engine updates) have not happened yet.",
    ),
    "outbox_queue_unreachable": _s(
        "The job queue is unreachable",
        "Background work is waiting. Nothing is lost; it is sent once the queue is back.",
    ),
    "webhook_intake_unavailable": _s(
        "Call events from the voice platform are being refused",
        "Every client: finished calls are not reaching us, and the voice platform turns the "
        "endpoint off after five refusals.",
    ),
    # --- the auto-healer --------------------------------------------------------------
    "agent_line_broken": _s(
        "An agent's calls are failing",
        "One client's callers are being handed to their fallback phone or told the line is "
        "unavailable.",
    ),
    "engine_platform_outage": _s(
        "The voice platform is having an outage",
        "Every client: lines are held and campaigns are paused until it recovers.",
    ),
    "healer_forward_not_cleared": _s(
        "A restored agent's calls are still forwarded",
        "One client's callers ring the client's own phone instead of the agent.",
    ),
    "healer_needs_person": _s(
        "The auto-healer needs a person",
        "An incident it could not fix is waiting for an operator.",
    ),
    "healer_line_relapsed": _s(
        "A repaired line broke again",
        "One client's agent is held again and will not be restored automatically.",
    ),
    "healer_line_hold_failed": _s(
        "A broken agent is answering again",
        "One client's callers reach an agent with a broken set-up until the hold is re-applied.",
    ),
    "studio_voice_key_push_failed": _s(
        "A new Studio voice key did not reach a workspace",
        "Studio calls there still use the previous key, and stop speaking if that key was revoked.",
    ),
    "studio_workspace_drift": _s(
        "A Studio client workspace is off our voice key",
        "One client's Studio agents are on a different voice and rate than we bill, or silent.",
    ),
    "engine_workspace_retention_drift": _s(
        "The voice platform could not be set to the client's retention period",
        "The platform may keep that client's call recordings and transcripts past its policy.",
    ),
    "own_model_key_push_failed": _s(
        "A new model key did not reach a client workspace",
        "Calls there still use the previous key, and fail if that key was revoked.",
    ),
    "own_model_workspace_drift": _s(
        "A client workspace is off our model key",
        "One client's agents run on another model and rate than the one we meter.",
    ),
    "own_model_tokens_unpriced": _s(
        "Calls ran on a model with no price",
        "Our margin: those calls' model usage is recorded with no cost.",
    ),
    # --- money and platform state -----------------------------------------------------
    "razorpay_webhook_unconfigured": _s(
        "Payments cannot be verified",
        "Clients' top-ups are arriving and cannot be credited until the webhook secret is set.",
    ),
    "razorpay_unknown_tenant": _s(
        "A payment arrived for an account we cannot find",
        "A client has paid and has not been credited.",
    ),
    "razorpay_money_unapplied": _s(
        "A verified payment was not applied",
        "A client's money moved at the payment provider and their wallet did not change.",
    ),
    "topup_attempt_not_recorded": _s(
        "A top-up order was not linked to its record",
        "No money is at risk; the history of one client's top-up is incomplete.",
    ),
    "topup_settlement_silent": _s(
        "Top-up payments are not settling",
        "Clients who pay may not be credited; payment notifications may not be reaching us.",
    ),
    "topup_settlement_sweep_abandoned": _s(
        "The payment settlement check failed",
        "A payment notification that stops arriving would go unnoticed until it runs again.",
    ),
    "razorpay_refund_failed": _s(
        "A refund failed at the payment provider",
        "One client has not received a refund we issued.",
    ),
    "payment_dispute_opened": _s(
        "A client's bank disputed a payment",
        "That client's outbound calling is paused and the amount is held; inbound still works.",
    ),
    "payment_dispute_action_required": _s(
        "A payment dispute needs evidence",
        "One client's dispute will be lost if no evidence is sent in time.",
    ),
    "razorpay_reconciliation_unexplained": _s(
        "The payment provider holds payments our ledger cannot explain",
        "Client wallets may be missing money, or hold money that does not match.",
    ),
    "platform_fee_paid_twice": _s(
        "A platform fee was paid twice",
        "One client has paid money that is not recorded anywhere.",
    ),
    "platform_fee_payment_unmatched": _s(
        "A platform fee payment was not matched",
        "One client has paid and their outbound pause, if any, has not lifted.",
    ),
    "ai_platform_brake_tripped": _s(
        "AI help is paused for everyone",
        "Every client's and the admin console's AI assistant. Calls, campaigns and leads are "
        "unaffected.",
    ),
    "ai_provider_degraded": _s(
        "An AI provider is failing",
        "The assistant answers on its standby; lead extraction or search may be delayed.",
    ),
    "platform_secret_unreadable": _s(
        "Stored credentials cannot be decrypted",
        _SECRET_AFFECTS,
    ),
    # --- the host backup chain --------------------------------------------------------
    "basebackup_failed": _s("Tonight's database backup failed", _BACKUP_AFFECTS),
    "base_backup_stale": _s("The latest database backup is too old", _BACKUP_AFFECTS),
    "no_base_backup": _s("There is no usable database backup", _BACKUP_AFFECTS),
    "backup_list_failed": _s("We cannot tell whether a database backup exists", _BACKUP_AFFECTS),
    "backup_list_unparseable": _s("The latest backup's age is unknown", _BACKUP_AFFECTS),
    "archiver_failing": _s("Database changes are not being archived", _BACKUP_AFFECTS),
    "archiver_never_succeeded": _s("Database archiving has never worked", _BACKUP_AFFECTS),
    "archive_stale": _s("Database archiving has fallen behind", _BACKUP_AFFECTS),
    "pg_wal_backlog": _s(
        "Unarchived database changes are piling up",
        "Every client, if it keeps growing: the database stops accepting writes.",
    ),
    "wal_chain_broken": _s("The database backup chain has a gap", _BACKUP_AFFECTS),
    "walg_unavailable": _s("The backup tool is missing on the host", _BACKUP_AFFECTS),
    "backup_timer_missing": _s("A backup is not scheduled", _BACKUP_AFFECTS),
    "backup_timer_inactive": _s("A backup timer is switched off", _BACKUP_AFFECTS),
    "backup_timer_not_firing": _s("A backup timer is not running", _BACKUP_AFFECTS),
    "offsite_pgdump_failed": _s("Tonight's offsite database copy failed", _BACKUP_AFFECTS),
    "offsite_dump_shrank": _s(
        "Tonight's offsite database copy is suspiciously small", _BACKUP_AFFECTS
    ),
    "offsite_encrypt_failed": _s(
        "The offsite database copy could not be encrypted", _BACKUP_AFFECTS
    ),
    "offsite_upload_failed": _s("The offsite database copy did not upload", _BACKUP_AFFECTS),
    "offsite_readback_failed": _s("The offsite database copy cannot be read back", _BACKUP_AFFECTS),
    "offsite_digest_mismatch": _s(
        "The offsite database copy does not match what was written", _BACKUP_AFFECTS
    ),
    "alert_delivery_failed": _s(
        "A server alert could not be sent",
        "No client directly; an alarm on the server reached only its log.",
    ),
    "alert_delivery_unconfigured": _s(
        "Server alerts have nowhere to go",
        "No client directly; server alarms reach only the server's log.",
    ),
    # --- schedules and certificates ---------------------------------------------------
    "tls_certificate_expiring": _s(
        "Our HTTPS certificate expires soon",
        "Every client and visitor, once it expires: browsers will refuse the site.",
    ),
    "tls_certificate_unreadable": _s(
        "Our HTTPS certificate cannot be read",
        "Possibly every client and visitor: the site may be down or unreachable.",
    ),
    "kb_embed_width_mismatch": _s(
        "Knowledge search indexing is stopped",
        "New knowledge-base content is not becoming searchable for any client.",
    ),
    "caller_embed_width_mismatch": _s(
        "Call and lead search indexing is stopped",
        "Recent calls and leads stay keyword-searchable only, for every client.",
    ),
    "caller_subject_key_unreachable": _s(
        "Some caller data can no longer be found for erasure",
        "A deletion request for those callers would miss rows and report zero.",
    ),
    # --- refusals that alarm because they are 5xx -------------------------------------
    "payment_order_amount_mismatch": _s(
        "A payment amount does not match our order",
        "One client's payment and our records disagree.",
    ),
    "refund_amount_mismatch": _s(
        "A refund amount does not match our records",
        "One client's refund and our records disagree.",
    ),
    "platform_kek_unusable": _s("The platform encryption key cannot be used", _SECRET_AFFECTS),
    "engine_intake_kek_unusable": _s(
        "Call events from the voice platform cannot be verified",
        "Every client: call events are refused and webhook secrets cannot be stored.",
    ),
    "platform_secret_corrupt": _s("A stored secret is corrupt", _SECRET_AFFECTS),
    "platform_secret_unwrappable": _s("A stored secret cannot be unlocked", _SECRET_AFFECTS),
    "engine_compliance_floor_absent": _s(
        "A call was refused because it had no AI-disclosure rule",
        "One client's dial was blocked; nothing rang.",
    ),
    "audit_chain_not_configured": _s(
        "The audit trail cannot be signed",
        "Every client: actions that need a signed audit record are stopped.",
    ),
    "copilot_proposals_not_configured": _s(
        "The assistant cannot make changes",
        "Every client and operator: the assistant can answer but cannot act.",
    ),
    "idempotency_not_configured": _s(
        "Retry-safe actions are stopped",
        "Every client: payments, dials and other retry-safe writes are refused.",
    ),
    "impersonation_not_configured": _s(
        "Support cannot view client accounts",
        "Operators cannot open or use a view-as session.",
    ),
}


def base_code(code: str) -> str:
    """`unhandled_exception:IntegrityError` -> `unhandled_exception`."""
    return code.split(":", 1)[0]


@dataclass(frozen=True, slots=True)
class IndexRow:
    """One row of `runbooks/alarm-index.md`, cell text as written (markdown inline)."""

    meaning: str
    what_to_do: str


def _cells(row: str) -> list[str]:
    """Split a markdown table row on `|`, ignoring `\\|` and pipes inside backticks."""
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    index = 0
    while index < len(row):
        char = row[index]
        if char == "\\" and index + 1 < len(row) and row[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells[1:-1] if len(cells) >= 2 else cells


_ROW_CODE = re.compile(r"^`([a-z][a-z0-9_]*)`$")


@lru_cache(maxsize=1)
def _index() -> dict[str, IndexRow]:
    try:
        text = ALARM_INDEX.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:  # ValueError: a file that is not valid UTF-8
        # The mail still goes, without these two sections: an alarm must not wait on a doc.
        log.warning("alarm_index_unreadable", extra={"reason": type(exc).__name__})
        return {}
    start = text.find(_ALARM_HEADING)
    section = text[start:] if start >= 0 else ""
    end = section.find("\n## ", len(_ALARM_HEADING))
    section = section if end < 0 else section[:end]
    rows: dict[str, IndexRow] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = _cells(line)
        match = _ROW_CODE.match(cells[0]) if cells else None
        if match is None or len(cells) < 4:
            continue
        rows[match.group(1)] = IndexRow(
            meaning=cells[3], what_to_do=cells[4] if len(cells) > 4 else ""
        )
    return rows


def index_row(code: str) -> IndexRow | None:
    return _index().get(base_code(code))


def summary_for(code: str) -> AlarmSummary | None:
    return ALARM_SUMMARIES.get(base_code(code))


def headline_for(code: str) -> str:
    """The summary's headline; for a code with none, a neutral line that names the code."""
    summary = summary_for(code)
    return summary.headline if summary is not None else f"Alarm {base_code(code)} fired"


__all__ = [
    "ALARM_INDEX",
    "ALARM_SUMMARIES",
    "AlarmSummary",
    "IndexRow",
    "base_code",
    "headline_for",
    "index_row",
    "summary_for",
]
