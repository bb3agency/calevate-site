"""What each assistant tool is called on the person's screen, while it runs and once it ran.

The panel used to print the tool's machine name and its timing ("search_calls 93 ms"). That
name is still the one the logs, the audit rows and support use, and it stays on the frame as
`tool`; this table is the words a business owner reads instead ("Searched your calls").

ONE TABLE, KEYED BY EVERY NAME `service.tool_array` OFFERS in either realm, and
`step_labels_test.py` fails when a tool is offered without a label here, so a new tool cannot
reach the panel as a bare identifier. A name that is not a tool at all (a model inventing
one) gets `UNKNOWN`, which says something was tried without naming it.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class StepLabel(NamedTuple):
    #: While it runs, ending in an ellipsis: "Searching your calls…".
    running: str
    #: Once it ran: "Searched your calls".
    done: str


def _l(running: str, done: str) -> StepLabel:
    return StepLabel(running=f"{running}…", done=done)


STEP_LABELS: Final[dict[str, StepLabel]] = {
    # The screen's own form.
    "set_fields": _l("Filling in this form", "Filled in this form"),
    # Client reads.
    "business_snapshot": _l("Checking your account", "Checked your account"),
    "leads_search": _l("Searching your leads", "Searched your leads"),
    "leads_semantic_search": _l("Searching your leads", "Searched your leads"),
    "calls_recent": _l("Checking recent calls", "Checked recent calls"),
    "campaigns_list": _l("Checking your campaigns", "Checked your campaigns"),
    "agents_list": _l("Checking your agents", "Checked your agents"),
    "search_knowledge": _l("Searching your knowledge", "Searched your knowledge"),
    "search_calls": _l("Searching your calls", "Searched your calls"),
    "agent_detail": _l("Reading the agent", "Read the agent"),
    "lead_detail": _l("Reading the lead", "Read the lead"),
    "call_detail": _l("Reading the call", "Read the call"),
    "calls_live": _l("Checking calls in progress", "Checked calls in progress"),
    "callbacks_list": _l("Checking call-backs", "Checked call-backs"),
    "knowledge_sources": _l("Checking your knowledge", "Checked your knowledge"),
    "numbers_list": _l("Checking your numbers", "Checked your numbers"),
    "numbers_available": _l("Looking for numbers to buy", "Looked for numbers to buy"),
    "billing_overview": _l("Checking your credit", "Checked your credit"),
    "verification_status": _l("Checking your verification", "Checked your verification"),
    "integrations_status": _l("Checking your connections", "Checked your connections"),
    "needs_attention": _l("Checking what needs you", "Checked what needs you"),
    "quality_reports": _l("Reading quality reports", "Read quality reports"),
    "campaign_detail": _l("Reading the campaign", "Read the campaign"),
    "team_members": _l("Checking your team", "Checked your team"),
    "voices_offered": _l("Checking the voices", "Checked the voices"),
    # Client changes.
    "lead_set_status": _l("Updating the lead", "Updated the lead"),
    "dnc_add": _l("Adding to do-not-call", "Added to do-not-call"),
    "campaign_pause": _l("Pausing the campaign", "Paused the campaign"),
    "propose_knowledge": _l("Preparing knowledge to add", "Prepared knowledge to add"),
    "agent_create": _l("Creating the agent", "Created the agent"),
    "agent_rename": _l("Renaming the agent", "Renamed the agent"),
    "agent_publish": _l("Switching the agent on", "Switched the agent on"),
    "campaign_launch": _l("Launching the campaign", "Launched the campaign"),
    "lead_assign": _l("Assigning the lead", "Assigned the lead"),
    "lead_rename": _l("Renaming the lead", "Renamed the lead"),
    "leads_bulk_update": _l("Updating leads", "Updated leads"),
    "dnc_remove": _l("Removing from do-not-call", "Removed from do-not-call"),
    "call_place": _l("Placing the call", "Placed the call"),
    "callback_book": _l("Booking a call-back", "Booked a call-back"),
    "callback_reschedule": _l("Moving the call-back", "Moved the call-back"),
    "callback_cancel": _l("Cancelling the call-back", "Cancelled the call-back"),
    "campaign_create": _l("Creating the campaign", "Created the campaign"),
    "campaign_clone": _l("Copying the campaign", "Copied the campaign"),
    "campaign_add_leads": _l("Adding leads to the campaign", "Added leads to the campaign"),
    "campaign_schedule": _l("Scheduling the campaign", "Scheduled the campaign"),
    "campaign_unschedule": _l("Unscheduling the campaign", "Unscheduled the campaign"),
    "campaign_resume": _l("Resuming the campaign", "Resumed the campaign"),
    "agent_edit": _l("Changing the agent", "Changed the agent"),
    "agent_edit_live": _l("Changing the live agent", "Changed the live agent"),
    "agent_capture_fields_set": _l("Changing what the agent captures", "Changed what it captures"),
    "agent_changes_apply": _l("Applying the agent's changes", "Applied the agent's changes"),
    "agent_deactivate": _l("Switching the agent off", "Switched the agent off"),
    "agent_delete": _l("Deleting the agent", "Deleted the agent"),
    "business_hours_set": _l("Setting your hours", "Set your hours"),
    "knowledge_link_add": _l("Adding a web page", "Added a web page"),
    "knowledge_remove": _l("Removing knowledge", "Removed knowledge"),
    "number_buy": _l("Buying the number", "Bought the number"),
    "number_release": _l("Releasing the number", "Released the number"),
    "agent_test_call": _l("Placing a test call", "Placed a test call"),
    "business_profile_set": _l("Updating your business details", "Updated your business details"),
    "open_screen": _l("Opening the screen", "Opened the screen"),
    "run_in_background": _l("Starting a background task", "Started a background task"),
    # Operator reads and actions (admin realm).
    "platform_tenants": _l("Checking the accounts", "Checked the accounts"),
    "platform_health": _l("Checking platform health", "Checked platform health"),
    "platform_ops_state": _l("Checking operations", "Checked operations"),
    "search_runbooks": _l("Searching the runbooks", "Searched the runbooks"),
    "admin_kyc_queue": _l("Checking the verification queue", "Checked the verification queue"),
    "admin_held_accounts": _l("Checking held accounts", "Checked held accounts"),
    "admin_alerts": _l("Checking alerts", "Checked alerts"),
    "admin_voices": _l("Checking the voices", "Checked the voices"),
    "platform_halt_outbound": _l("Halting outgoing calls", "Halted outgoing calls"),
    "admin_kyc_review": _l("Recording the verification decision", "Recorded the decision"),
    "admin_first_campaign_decide": _l("Recording the campaign decision", "Recorded the decision"),
    "admin_workspace_provision": _l("Setting up the workspace", "Set up the workspace"),
    "admin_number_release": _l("Releasing the number", "Released the number"),
    "admin_voice_set": _l("Changing the voice", "Changed the voice"),
}

UNKNOWN: Final[StepLabel] = _l("Trying something", "Tried something it could not do")


def step_label(tool: str, *, running: bool) -> str:
    label = STEP_LABELS.get(tool, UNKNOWN)
    return label.running if running else label.done


__all__ = ["STEP_LABELS", "UNKNOWN", "StepLabel", "step_label"]
